"""Turning an investigation's findings into classified, scored claims.

A chunk is source material; a claim is an extracted proposition. Keeping them
apart is what makes provenance, contradiction detection and confidence scoring
possible — and it stops the answer generator treating a plausible synthesis as a
directly stated fact.

Every claim is one of four kinds:

* **direct** — a source states it;
* **inferred** — it follows from a chain of stated facts (the multi-hop case);
* **conflicting** — sources disagree, and both positions are carried;
* **unsupported** — nothing grounds it, so it never reaches the answer text.
"""

from __future__ import annotations

from src.graph.fact_query import AttributeView, FactRow
from src.orchestration.state import Claim, ClaimType, Intent, Investigation

# A claim resting on a single source cannot exceed this, however authoritative
# that source is: one record is one record.
SINGLE_SOURCE_CEILING = 0.92
# Corroboration bonus per additional independent document, capped.
CORROBORATION_BONUS = 0.04
MAX_CORROBORATION = 0.08
# Each additional hop compounds the chance of a wrong link.
HOP_PENALTY = 0.12
# An unresolved conflict must never read as confident.
CONFLICT_CEILING = 0.55


def score(rows: list[FactRow], *, hops: int = 0, conflicting: bool = False) -> float:
    """Confidence from source reliability, corroboration and chain length."""
    if not rows:
        return 0.0
    base = max(r.reliability for r in rows)
    documents = len({r.document_id for r in rows})
    base = min(base, SINGLE_SOURCE_CEILING)
    base += min((documents - 1) * CORROBORATION_BONUS, MAX_CORROBORATION)
    base -= hops * HOP_PENALTY
    if conflicting:
        base = min(base, CONFLICT_CEILING)
    return max(0.05, min(base, 0.99))


def build_claims(state: Investigation, facts) -> list[Claim]:
    """Read the satisfied sub-questions and emit the claims the answer may use."""
    claims: list[Claim] = []
    question = state.question
    views: list[AttributeView] = []

    for step in state.sub_questions:
        if not step.satisfied or not step.evidence:
            continue
        rows = step.evidence
        view = _view_for(rows)
        if view:
            views.append(view)

        # A computed value is never *stated* by a source: it is derived from two
        # that are. Typing it as inferred — and charging it the same hop penalty
        # as a bridged lookup — keeps the answer from presenting arithmetic with
        # more authority than the numbers it rests on.
        if step.key == "compute" and state.computation.get("result") is not None:
            conflicting = _is_conflicting(state, rows)
            claims.append(Claim(
                text=f"{state.computation['formula']} = "
                     f"{state.computation['result_text']}.",
                claim_type=ClaimType.CONFLICTING if conflicting else ClaimType.INFERRED,
                confidence=score(rows, hops=1, conflicting=conflicting),
                evidence=rows,
                step_key=step.key,
            ))
            continue

        # A target reached through a bridge is inferred, not directly stated:
        # no single source says "the Gravemaw Wyrm's lair is ruled by X".
        hops = 1 if (step.key == "target" and question.intent is Intent.RELATION_HOP) else 0
        conflicting = _is_conflicting(state, rows)

        claim_type = (
            ClaimType.CONFLICTING if conflicting
            else ClaimType.INFERRED if hops
            else ClaimType.DIRECT
        )
        claims.append(Claim(
            text=_render(step.key, rows, question),
            claim_type=claim_type,
            confidence=score(rows, hops=hops, conflicting=conflicting),
            evidence=rows,
            step_key=step.key,
        ))

    if not claims:
        claims.append(Claim(
            text="The archive does not record a value that answers this question.",
            claim_type=ClaimType.UNSUPPORTED,
            confidence=0.0,
        ))
    return claims


def _render(key: str, rows: list[FactRow], question) -> str:
    row = rows[0]
    subject = row.subject_name
    attribute = row.attribute.replace("_", " ")
    if key == "bridge":
        return f"{subject}'s {attribute} is {row.value_text}."
    if key == "resolve":
        return (f"The most authoritative record gives {subject}'s {attribute} as "
                f"{row.value_text} ({row.source_class}).")
    return f"{subject}'s {attribute} is {row.value_text}."


def _view_for(rows: list[FactRow]) -> AttributeView | None:
    if not rows:
        return None
    view = AttributeView(rows[0].subject_id, rows[0].subject_name, rows[0].attribute)
    for row in rows:
        view.groups.setdefault(row.value_key, []).append(row)
    return view


def _is_conflicting(state: Investigation, rows: list[FactRow]) -> bool:
    """True when a recorded conflict covers this claim's subject and attribute."""
    if not rows:
        return False
    subject, attribute = rows[0].subject_name, rows[0].attribute
    return any(c["subject"] == subject and c["attribute"] == attribute
               for c in state.conflicts)
