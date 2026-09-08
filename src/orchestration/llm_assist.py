"""Merging LLM assistance into the deterministic investigation.

The contract, stated once so every function below can be checked against it:

* The LLM may **add** signal — a relation the rule vocabulary lacks, a sub-question
  phrasing, a search query, a candidate claim from narrative prose.
* The LLM may **never overrule** something matched against the archive index. If
  the rule-based analyzer resolved an entity, that entity stands.
* Nothing the LLM produces becomes evidence without being tied back to a real
  chunk. A claim naming an evidence id we did not supply is discarded, not
  repaired.

That last rule is the one that matters. It is what makes the model a search
assistant rather than an answer source, and it is enforced here rather than
trusted to a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.orchestration.state import Intent, Question

# Maps the schema's intent vocabulary onto the loop's own state machine.
_INTENT_MAP = {
    "attribute_lookup": Intent.ATTRIBUTE_LOOKUP,
    "conflict_resolution": Intent.CONFLICT_RESOLUTION,
    "relation_hop": Intent.RELATION_HOP,
    "inverse_hop": Intent.INVERSE_HOP,
    "comparison": Intent.OPEN_QUESTION,
    "timeline": Intent.OPEN_QUESTION,
    "open_question": Intent.OPEN_QUESTION,
}


@dataclass
class AssistOutcome:
    """What the LLM contributed, for the trace. Empty when it contributed nothing."""

    used: bool = False
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []


def merge_understanding(question: Question, llm: dict | None, analyzer) -> AssistOutcome:
    """Fold validated LLM output into a rule-derived Question, in place.

    Only gaps are filled. The guard on entities is the important one: a model
    naming an entity the archive does not contain is a hallucination, and we
    resolve every suggested name through the index before accepting it.
    """
    outcome = AssistOutcome()
    if not llm:
        return outcome

    # Entities: only *additional* ones, and only if the index knows them.
    known = {eid for eid, _ in question.entities}
    for surface in llm.get("entities", []):
        matched = analyzer.match_entities(surface)
        for entity_id, name in matched:
            if entity_id not in known:
                question.entities.append((entity_id, name))
                known.add(entity_id)
                outcome.used = True
                outcome.notes.append(f"LLM surfaced entity '{name}' (confirmed in index)")

    # Attribute: only when the rules found none. Candidate relations the schema
    # quarantined get one chance to resolve against attributes the archive
    # actually records — the same rule as entities: the model may propose, the
    # index decides. A name the fact store has never seen stays quarantined.
    relations = list(llm.get("relations", []))
    unresolved: list[str] = []
    for candidate in llm.get("candidate_relations", []):
        resolved = resolve_attribute(candidate, analyzer)
        if resolved and resolved not in relations:
            relations.append(resolved)
            outcome.notes.append(
                f"LLM proposed '{candidate}' → resolved to recorded attribute '{resolved}'")
        else:
            unresolved.append(candidate)
    if question.attribute is None and relations:
        question.attribute = relations[0]
        outcome.used = True
        outcome.notes.append(f"LLM supplied relation '{relations[0]}' (rules found none)")
    if question.bridge_attribute is None and len(relations) > 1:
        # A two-relation question the phrase patterns did not recognise.
        if relations[1] != question.attribute:
            question.bridge_attribute = question.attribute
            question.attribute = relations[1]
            outcome.used = True
            outcome.notes.append(
                f"LLM identified a two-step relation: {relations[0]} → {relations[1]}"
            )

    if llm.get("expects_conflict") and not question.expects_conflict:
        question.expects_conflict = True
        outcome.used = True
        outcome.notes.append("LLM flagged that the question expects disagreement")

    # Intent: only upgrade an open question; never downgrade a rule-matched one.
    mapped = _INTENT_MAP.get(llm.get("intent", ""), None)
    if question.intent is Intent.OPEN_QUESTION and mapped and mapped is not Intent.OPEN_QUESTION:
        if mapped is Intent.RELATION_HOP and not question.bridge_attribute:
            pass  # a hop intent without two relations is not actionable
        else:
            question.intent = mapped
            outcome.used = True
            outcome.notes.append(f"LLM reclassified the question as {mapped.value}")

    if unresolved:
        outcome.notes.append(
            f"LLM proposed unrecognised relations {unresolved} — "
            f"quarantined, not traversed"
        )
    return outcome


def resolve_attribute(candidate: str, analyzer) -> str | None:
    """Map a model-proposed relation onto an attribute the archive records.

    Three passes, narrowing from safest to loosest: the phrase vocabulary we
    already trust, then an exact attribute name, then a snake_case match against
    what the fact store actually contains. Anything that survives none of these
    is a name the archive has never used, so it is not accepted.
    """
    from src.orchestration.understanding import ATTRIBUTE_PHRASES

    cleaned = candidate.strip().lower().replace("-", " ")
    if cleaned in ATTRIBUTE_PHRASES:
        return ATTRIBUTE_PHRASES[cleaned]

    known = getattr(analyzer, "known_attributes", set())
    snake = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    if snake in known:
        return snake
    # A model saying "defenders" for a corpus that records "garrison_strength".
    for attribute in known:
        if snake and (attribute.startswith(snake) or snake in attribute.split("_")):
            return attribute
    return None


def verify_extracted_claims(claims: list[dict], allowed_evidence: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Keep only claims tied to evidence we actually supplied and that supports them.

    Two gates, in order:

    1. **Provenance.** The claim's ``evidence_id`` must be one we put in the
       prompt. A model that invents an id has invented the claim.
    2. **Support.** The claim's subject and value must both actually occur in
       that passage's text. This is a blunt containment check, not entailment —
       but it catches the failure that matters, where a model produces a
       plausible statement the cited passage does not make.

    Returns (kept, rejection reasons).
    """
    kept: list[dict] = []
    rejected: list[str] = []

    for claim in claims:
        evidence_id = claim.get("evidence_id", "")
        passage = allowed_evidence.get(evidence_id)
        if passage is None:
            rejected.append(
                f"'{claim.get('subject')} {claim.get('predicate')} {claim.get('value')}' "
                f"— cites unknown evidence id {evidence_id!r}"
            )
            continue

        haystack = " ".join(passage.lower().split())
        subject_ok = claim["subject"].lower() in haystack
        value_ok = claim["value"].lower() in haystack
        if not (subject_ok and value_ok):
            missing = "subject" if not subject_ok else "value"
            rejected.append(
                f"'{claim['subject']} {claim['predicate']} {claim['value']}' "
                f"— {missing} does not appear in the cited passage"
            )
            continue

        kept.append(claim)
    return kept, rejected
