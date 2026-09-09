"""Schema validation for LLM output.

Deliberately hand-rolled rather than pulling in `jsonschema`. The shapes we need
are small and fixed, and writing them out means the contract is readable in one
screen — which matters because this file is the boundary between "a model said
something" and "our system will act on it".

Two rules the validators enforce beyond structure:

* **Unknown keys are dropped, not passed through.** A model that invents a field
  must not be able to smuggle it into our state.
* **Nothing here validates truth.** A schema-valid entity is still just a *claim
  that an entity exists*; it is checked against the archive index separately, in
  `understanding.py`. Schema validity is necessary, never sufficient.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.ai_gateway.errors import SchemaViolation

# Relations the planner is allowed to name. Anything outside this set is kept but
# flagged as a candidate, so a hallucinated relation cannot silently become a
# graph traversal.
SUPPORTED_RELATIONS = {
    "lair", "ruled_by", "member_of", "has_member", "victor", "victor_of",
    "founded", "forging_date", "forging_site", "housed_in", "seat", "seat_of",
    "belligerent_in", "threat_rating", "attunement_cost", "garrison_strength",
    "region", "born", "role", "outcome", "began", "ended", "related_to",
}

SUPPORTED_INTENTS = {
    "attribute_lookup", "conflict_resolution", "relation_hop", "inverse_hop",
    "comparison", "timeline", "open_question",
}

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(raw: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Models wrap JSON in prose or fences even when told not to. We try a strict
    parse first, then the outermost brace-delimited span. If neither works, that
    is a schema violation — we never "fix up" the text further, because a
    heuristic repair is exactly how malformed output starts being trusted.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise SchemaViolation("response contained no JSON object") from None
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError as error:
            raise SchemaViolation(f"response JSON is malformed: {error}") from None
    if not isinstance(parsed, dict):
        raise SchemaViolation("response JSON is not an object")
    return parsed


def _string_list(value: Any, *, field: str, limit: int = 12) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaViolation(f"'{field}' must be a list")
    out = []
    for item in value[:limit]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def validate_question_understanding(payload: dict[str, Any]) -> dict[str, Any]:
    """Contract for the question-understanding call.

    Returns a normalised dict with only the keys we consume. `entities` here are
    *surface strings the model noticed* — resolving them to canonical IDs is done
    against the archive index, never by the model.
    """
    intent = payload.get("intent")
    if not isinstance(intent, str) or intent not in SUPPORTED_INTENTS:
        raise SchemaViolation(f"intent must be one of {sorted(SUPPORTED_INTENTS)}")

    relations = _string_list(payload.get("relations"), field="relations")
    unknown = [r for r in relations if r not in SUPPORTED_RELATIONS]

    return {
        "intent": intent,
        "entities": _string_list(payload.get("entities"), field="entities"),
        "relations": [r for r in relations if r in SUPPORTED_RELATIONS],
        # Kept but quarantined: visible in the trace, never used to traverse.
        "candidate_relations": unknown,
        "answer_type": payload.get("answer_type") if isinstance(payload.get("answer_type"), str) else "value",
        "requires_multi_hop": bool(payload.get("requires_multi_hop", False)),
        "expects_conflict": bool(payload.get("expects_conflict", False)),
        "sub_questions": _string_list(payload.get("sub_questions"), field="sub_questions", limit=6),
    }


def validate_query_suggestions(payload: dict[str, Any]) -> list[str]:
    """Contract for the next-search suggestion call."""
    queries = _string_list(payload.get("queries"), field="queries", limit=5)
    if not queries:
        raise SchemaViolation("'queries' must contain at least one non-empty string")
    return queries


def validate_extracted_claims(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Contract for candidate-claim extraction from narrative prose.

    Every claim must name the ``evidence_id`` it came from. A claim without one is
    dropped outright: it cannot be verified against the archive, so by definition
    it cannot be cited, so it can never reach an answer.
    """
    raw = payload.get("claims")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SchemaViolation("'claims' must be a list")

    claims: list[dict[str, str]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject")
        predicate = item.get("predicate")
        value = item.get("value")
        evidence_id = item.get("evidence_id")
        if not all(isinstance(v, str) and v.strip()
                   for v in (subject, predicate, value, evidence_id)):
            continue
        claims.append({
            "subject": subject.strip(),
            "predicate": predicate.strip(),
            "value": value.strip(),
            "evidence_id": evidence_id.strip(),
        })
    return claims


def validate_answer_synthesis(payload: dict[str, Any]) -> dict[str, Any]:
    """Contract for evidence-grounded natural-language synthesis.

    The model may compose prose, but it must return cited source ids and must not
    claim to use anything outside the supplied passages.
    """
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise SchemaViolation("'answer' must be a non-empty string")
    used = _string_list(payload.get("used_evidence_ids"), field="used_evidence_ids", limit=12)
    return {"answer": answer.strip(), "used_evidence_ids": used}
