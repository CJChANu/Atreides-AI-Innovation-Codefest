"""Turning an Investigation into the API response.

Kept apart from the route handlers so the mapping is testable on its own, and so
the CLI renderer and the HTTP response are demonstrably reading the same state.
"""

from __future__ import annotations

from src.api.models import AskResponse, ClaimOut, EvidenceRef
from src.generation.answer import headline
from src.orchestration.state import ClaimType, Investigation
from src.orchestration.status import evaluate


def confidence_label(value: float) -> str:
    """A word, not just a number — a bare 0.58 tells a reader nothing."""
    if value >= 0.80:
        return "high"
    if value >= 0.55:
        return "medium"
    if value > 0.0:
        return "low"
    return "none"


def confidence_reasons(claim) -> list[str]:
    """Why this claim scores what it scores, in the terms that produced it.

    Confidence here is not a model's self-report: it is computed from source
    reliability, corroboration across documents, and how many inference steps
    stand between the sources and the claim. Naming those lets a reader weigh
    the number instead of trusting it.
    """
    if not claim.evidence:
        return ["no evidence attached"]

    reasons: list[str] = []
    best = max(claim.evidence, key=lambda row: row.reliability)
    reasons.append(f"most reliable source is {best.source_class} "
                   f"({best.reliability:.2f})")

    documents = {row.document_id for row in claim.evidence}
    if len(documents) > 1:
        reasons.append(f"corroborated across {len(documents)} independent documents")
    else:
        reasons.append("single source — one record is one record")

    if claim.claim_type is ClaimType.INFERRED:
        reasons.append("derived from several facts, not stated by any one source")
    elif claim.claim_type is ClaimType.CONFLICTING:
        reasons.append("sources disagree; capped until the conflict is resolved")
    return reasons


def graph_path(state: Investigation) -> list[str]:
    """The chain of entities and relations the answer was derived through."""
    path: list[str] = []
    for link in state.evidence_chain:
        if " — " not in link:
            continue
        subject, _, rest = link.partition(" — ")
        relation, _, value = rest.partition(": ")
        if value:
            path.extend([subject.strip(), relation.strip(), value.strip()])
    # Collapse the repeated join points: A rel B, B rel C -> A rel B rel C.
    collapsed: list[str] = []
    for item in path:
        if not collapsed or collapsed[-1] != item:
            collapsed.append(item)
    return collapsed


def to_response(state: Investigation, store, title_of, fallback_events: list[str]) -> AskResponse:
    documents = {
        row["document_id"]: row
        for row in store.connection.execute(
            "SELECT document_id, title, relative_path, reliability FROM documents"
        )
    }

    # Assets for any figure evidence, so a visual claim can show the plate it
    # rests on rather than only naming it.
    # A fact lifted from a plate carries the figure's *document* id, so that is
    # the key that links a claim back to the image it was read from.
    assets = {
        row["document_id"]: row["figure_id"]
        for row in store.connection.execute(
            "SELECT document_id, figure_id FROM figures")
    }

    claims = []
    for claim in state.claims:
        evidence = []
        for item in claim.evidence:
            row = documents.get(item.document_id)
            evidence.append(EvidenceRef(
                document_id=item.document_id,
                document=title_of(item.document_id),
                relative_path=row["relative_path"] if row else "",
                page=item.page,
                chunk_id=item.chunk_id,
                source_class=item.source_class,
                reliability=item.reliability,
                excerpt=item.excerpt,
                figure_id=assets.get(item.document_id, ""),
            ))
        claims.append(ClaimOut(
            text=claim.text, claim_type=claim.claim_type.value,
            confidence=round(claim.confidence, 3),
            confidence_label=confidence_label(claim.confidence),
            confidence_reasons=confidence_reasons(claim),
            evidence=evidence,
        ))

    report = evaluate(state, fallback_events)
    return AskResponse(
        question=state.question.text,
        answer=headline(state),
        investigation_id=state.investigation_id,
        status=report.status.value,
        status_headline=report.headline,
        status_reasons=report.reasons,
        unmet_requirements=report.unmet,
        partial=report.is_partial,
        calculation=state.computation,
        ai_mode=state.ai_mode,
        claims=claims,
        evidence_chain=state.evidence_chain,
        conflicts=state.conflicts,
        graph_path=graph_path(state),
        trace=[i.to_dict() for i in state.iterations],
        sub_questions=[
            {"text": s.text, "completion": s.completion,
             "satisfied": s.satisfied, "attempted": s.attempted, "note": s.note}
            for s in state.sub_questions
        ],
        stop_reason=state.stop_reason.value,
        fallback_events=list(dict.fromkeys(fallback_events)),
        stats={
            "iterations": len(state.iterations),
            "queries": state.queries_issued,
            "graph_expansions": state.graph_expansions,
            "elapsed_ms": round(state.elapsed_seconds * 1000, 1),
            "assist_notes": state.assist_notes,
        },
    )
