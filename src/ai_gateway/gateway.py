"""The single entry point for every external AI call.

No module outside this package may talk to a provider. Centralising it is what
makes retries, caching, budgets, model switching, usage accounting and — most
importantly — *fallback* a property of the system rather than something each
caller has to remember.

The governing rule: **the LLM is a controlled tool, not a source of truth.** It
may read questions, propose searches and draft prose. It may not produce a
citation, and nothing it says becomes a fact without being matched back to an
archive evidence object. Every method here returns either validated, quarantined
output or raises — it never returns unchecked model text into the pipeline.

Transport is stdlib `urllib`: one fewer dependency, and the request/response path
stays readable, which matters for a component whose whole job is being trustworthy.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src.ai_gateway.breaker import CircuitBreaker, RetryPolicy, call_with_resilience
from src.ai_gateway.cache import ResponseCache
from src.ai_gateway.errors import (
    CircuitOpen,
    GatewayError,
    InvalidRequest,
    NotConfigured,
    RateLimited,
    SchemaViolation,
    TransientError,
)
from src.ai_gateway.schemas import (
    extract_json,
    validate_extracted_claims,
    validate_query_suggestions,
    validate_question_understanding,
    validate_answer_synthesis,
)
from src.common.config import Settings

# Bumped whenever a prompt changes, so the cache cannot serve a response that was
# produced by different instructions.
PROMPT_VERSION = "v1"

UNDERSTANDING_PROMPT = """You analyse questions about a fictional document archive.
Return ONLY a JSON object. Do not answer the question. Do not use outside knowledge.

{
  "intent": one of ["attribute_lookup","conflict_resolution","relation_hop","inverse_hop","comparison","timeline","open_question"],
  "entities": [names mentioned in the question, exactly as written],
  "relations": [relation names involved, e.g. "lair","ruled_by","member_of","victor","founded"],
  "answer_type": "value" | "number" | "year" | "entity" | "list",
  "requires_multi_hop": true/false,
  "expects_conflict": true if the question implies sources disagree (words like "actually", "truly", "the precise"),
  "sub_questions": [the steps needed, in order]
}

Question: {question}"""

QUERY_PROMPT = """You are helping search a fictional document archive.
Return ONLY a JSON object: {"queries": ["...", "..."]}

Give up to 3 short search queries (2-6 words) that would find the MISSING information.
Use only terms from the question and the findings. Invent no names.

Question: {question}
Already established: {findings}
Still missing: {gap}"""

EXTRACTION_PROMPT = """Extract factual statements from archive passages.
Return ONLY: {"claims":[{"subject":"...","predicate":"...","value":"...","evidence_id":"..."}]}

Rules:
- Use ONLY what the passage states. Add nothing from outside knowledge.
- evidence_id MUST be the id of the passage the claim came from, copied exactly.
- If a passage supports no clear factual statement, produce no claim for it.

Looking for: {gap}

Passages:
{passages}"""

SYNTHESIS_PROMPT = """Write a concise natural-language answer to a question about a fictional archive.
Return ONLY JSON: {"answer":"...", "used_evidence_ids":["..."]}

Rules:
- Use ONLY the supplied evidence passages.
- If sources differ, explain the difference instead of hiding it.
- Mention source types naturally when useful, e.g. wiki, codex, scanned document, image plate.
- Cite evidence inline with bracket ids, for example [E1].
- Do not invent facts that are not in the evidence.
- If the evidence is only related but not enough, say exactly what is missing.

Question: {question}

Evidence passages:
{passages}"""


@dataclass
class UsageRecord:
    """One call's accounting entry, for the audit log and the health endpoint."""

    capability: str
    model: str
    cached: bool
    ok: bool
    latency_ms: float
    error: str = ""


@dataclass
class GatewayStatus:
    configured: bool
    model: str
    circuit: str
    calls: int
    failures: int
    cache_hits: int
    cache_misses: int
    last_error: str = ""
    fallback_events: list[str] = field(default_factory=list)


class AIGateway:
    """LLM access with validation, resilience and honest degradation."""

    def __init__(self, settings: Settings, *, timeout: float = 30.0) -> None:
        self.settings = settings
        self.timeout = timeout
        self.model = settings.llm_model
        self.base_url = settings.llm_base_url.rstrip("/")
        self._api_key = settings.llm_api_key
        self.cache = ResponseCache(settings.cache_dir / "llm")
        self.retry = RetryPolicy()
        self.breaker = CircuitBreaker()
        self.usage: list[UsageRecord] = []
        self.fallback_events: list[str] = []

    # -- state --------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """False when no key is set. Callers treat this as normal, not an error."""
        return bool(self._api_key)

    @property
    def available(self) -> bool:
        return self.configured and not self.breaker.is_open

    def note_fallback(self, reason: str) -> None:
        """Record a degradation so the trace and the UI can show it happened."""
        self.fallback_events.append(reason)

    def status(self) -> GatewayStatus:
        return GatewayStatus(
            configured=self.configured,
            model=self.model if self.configured else "(none)",
            circuit=self.breaker.state(),
            calls=len(self.usage),
            failures=sum(1 for u in self.usage if not u.ok),
            cache_hits=self.cache.hits,
            cache_misses=self.cache.misses,
            last_error=next((u.error for u in reversed(self.usage) if u.error), ""),
            fallback_events=list(self.fallback_events),
        )

    # -- capabilities -------------------------------------------------------

    def understand_question(self, question: str) -> dict[str, Any] | None:
        """Structured question analysis. Returns None whenever the LLM is unusable.

        Returning None rather than raising is deliberate: every caller has a
        deterministic path, and an unavailable model is an expected operating
        mode, not an exception.
        """
        prompt = UNDERSTANDING_PROMPT.replace("{question}", question)
        return self._json_call("understanding", prompt, validate_question_understanding)

    def suggest_queries(self, question: str, findings: list[str], gap: str) -> list[str] | None:
        prompt = (QUERY_PROMPT
                  .replace("{question}", question)
                  .replace("{findings}", "; ".join(findings[:6]) or "nothing yet")
                  .replace("{gap}", gap))
        return self._json_call("query_suggestion", prompt, validate_query_suggestions)

    def extract_claims(self, gap: str, passages: list[tuple[str, str]]) -> list[dict[str, str]] | None:
        """Pull candidate claims out of narrative prose.

        `passages` is (evidence_id, text). The model is required to echo the
        evidence_id back on every claim; the caller then checks that the id is
        real. That check is what keeps this from being a hallucination channel.
        """
        if not passages:
            return []
        rendered = "\n\n".join(
            f"[{eid}] {' '.join(text.split())[:700]}" for eid, text in passages[:6]
        )
        prompt = (EXTRACTION_PROMPT
                  .replace("{gap}", gap)
                  .replace("{passages}", rendered))
        return self._json_call("claim_extraction", prompt, validate_extracted_claims)


    def synthesize_answer(self, question: str, passages: list[tuple[str, str, str]]) -> dict[str, Any] | None:
        """Compose a grounded prose answer from retrieved passages.

        Each passage is (evidence_id, citation_label, text). The response is still
        quarantined by schema and the caller only uses it when the cited ids are
        among the supplied evidence ids.
        """
        if not passages:
            return None
        rendered = "\n\n".join(
            f"[{eid}] {label}: {' '.join(text.split())[:1000]}"
            for eid, label, text in passages[:10]
        )
        prompt = (SYNTHESIS_PROMPT
                  .replace("{question}", question)
                  .replace("{passages}", rendered))
        result = self._json_call("answer_synthesis", prompt, validate_answer_synthesis)
        if not result:
            return None
        allowed = {eid for eid, _, _ in passages}
        used = [eid for eid in result.get("used_evidence_ids", []) if eid in allowed]
        if not used:
            answer = result.get("answer", "")
            used = [eid for eid in allowed if f"[{eid}]" in answer]
        return {"answer": result["answer"], "used_evidence_ids": used}

    # -- transport ----------------------------------------------------------

    def _json_call(self, capability: str, prompt: str, validator):
        if not self.configured:
            self.note_fallback(f"{capability}: no API key configured")
            return None
        if self.breaker.is_open:
            self.note_fallback(f"{capability}: provider circuit open")
            return None

        key = self.cache.key(model=self.model, prompt_version=PROMPT_VERSION,
                             payload={"capability": capability, "prompt": prompt})
        cached = self.cache.get(key)
        if cached is not None:
            self.usage.append(UsageRecord(capability, self.model, True, True, 0.0))
            return cached

        started = time.perf_counter()
        try:
            raw = call_with_resilience(
                lambda: self._post_chat(prompt),
                policy=self.retry, breaker=self.breaker,
            )
            validated = validator(extract_json(raw))
        except (GatewayError, CircuitOpen) as error:
            elapsed = (time.perf_counter() - started) * 1000
            self.usage.append(UsageRecord(capability, self.model, False, False, elapsed,
                                          f"{type(error).__name__}: {error}"))
            # Every failure mode ends the same way: tell the caller to fall back.
            self.note_fallback(f"{capability}: {type(error).__name__}")
            return None
        except Exception as error:
            # Belt and braces. The whole point of this gateway is that an external
            # service can never take the system down, so an *unanticipated*
            # provider quirk must degrade exactly like an anticipated one. It is
            # recorded distinctly so a genuine bug is still visible in the audit
            # log rather than silently swallowed.
            elapsed = (time.perf_counter() - started) * 1000
            self.usage.append(UsageRecord(capability, self.model, False, False, elapsed,
                                          f"UNEXPECTED {type(error).__name__}: {error}"))
            self.breaker.record_failure()
            self.note_fallback(f"{capability}: unexpected {type(error).__name__}")
            return None

        elapsed = (time.perf_counter() - started) * 1000
        self.usage.append(UsageRecord(capability, self.model, False, True, elapsed))
        self.cache.put(key, validated)
        return validated

    def _post_chat(self, prompt: str) -> str:
        """One OpenAI-compatible chat completion. Raises typed GatewayErrors."""
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,           # planning must be reproducible
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # OpenRouter asks for these; harmless elsewhere.
                "HTTP-Referer": "https://github.com/CJChANu/AI-Innovation-Codefest",
                "X-Title": "Ashen Era Archive Investigator",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            status = error.code
            detail = error.read().decode("utf-8", "replace")[:200]
            if status == 429:
                raise RateLimited(f"rate limited: {detail}", status=status) from None
            if 500 <= status < 600:
                raise TransientError(f"provider error {status}: {detail}", status=status) from None
            raise InvalidRequest(f"request rejected ({status}): {detail}", status=status) from None
        except urllib.error.URLError as error:
            raise TransientError(f"connection failed: {error.reason}") from None
        except TimeoutError:
            raise TransientError(f"timed out after {self.timeout}s") from None

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise SchemaViolation("provider response had no message content") from None

        # Observed in the wild: some free models return `content: null` (reasoning
        # models that put their output elsewhere, or an empty completion). Left
        # unchecked this reaches the JSON parser as None and raises an
        # AttributeError, which is NOT a GatewayError — so it escapes the
        # resilience wrapper and crashes the caller instead of falling back.
        if not isinstance(content, str) or not content.strip():
            raise SchemaViolation("provider returned empty message content")
        return content
