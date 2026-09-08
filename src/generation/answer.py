"""Rendering a grounded answer.

The answer is *assembled from verified claims*, not written by a language model.
That is a deliberate constraint: every sentence in the output traces to a fact row
that names its document and page, so there is no path by which a fluent-sounding
but ungrounded statement can reach the user.

Order matters — the final answer comes first, then the evidence, then the audit
trail — because a reader who trusts the system should not have to scroll, and a
reader who does not should be able to check every step.
"""

from __future__ import annotations

from src.orchestration.state import ClaimType, Intent, Investigation, StopReason

# Stops that mean "we ran out of room", not "we are done". Answers reached this
# way are labelled partial, because presenting a budget stop as certainty is the
# most damaging thing a system like this can do.
PARTIAL_STOPS = {StopReason.ITERATION_BUDGET, StopReason.QUERY_BUDGET,
                 StopReason.TIME_BUDGET, StopReason.NO_NEW_EVIDENCE,
                 StopReason.INSUFFICIENT_EVIDENCE, StopReason.NO_ENTITY}


def headline(state: Investigation) -> str:
    """The one-line answer, taken from the highest-value claim available."""
    if state.answer_value:
        return state.answer_value

    supported = [c for c in state.claims if c.claim_type is not ClaimType.UNSUPPORTED]
    if supported:
        return max(supported, key=lambda c: c.confidence).text

    retrieved = sum(len(i.retrieved_chunks) for i in state.iterations)
    if retrieved:
        return (f"No recorded value answers this directly. {retrieved} related "
                f"passage(s) were retrieved — see the evidence below.")
    return "Not established by the archive."


def _claim_for(state: Investigation, key: str):
    """Find the claim produced by a named sub-question step."""
    return next((c for c in state.claims if c.step_key == key and c.evidence), None)


def render(state: Investigation, title_of, *, show_trace: bool = True) -> str:
    """Human-readable answer: result, evidence, conflicts, then the audit trail."""
    question = state.question
    lines: list[str] = []

    partial = state.stop_reason in PARTIAL_STOPS
    lines.append("═" * 74)
    lines.append(f"QUESTION  {question.text}")
    lines.append("═" * 74)
    lines.append("")
    lines.append(f"ANSWER    {headline(state)}")
    if partial:
        lines.append("          ⚠ PARTIAL — the investigation stopped before every "
                     "sub-question\n            was supported. Treat with caution.")
    lines.append("")

    # -- claims with citations ---------------------------------------------
    lines.append("SUPPORTING CLAIMS")
    for claim in state.claims:
        marker = {
            ClaimType.DIRECT: "●", ClaimType.INFERRED: "◐",
            ClaimType.CONFLICTING: "◆", ClaimType.UNSUPPORTED: "○",
        }[claim.claim_type]
        lines.append(f"  {marker} {claim.text}")
        lines.append(f"      {claim.claim_type.value}  ·  confidence {claim.confidence:.2f}")
        for evidence in claim.evidence[:3]:
            where = f"p.{evidence.page}" if evidence.page else "infobox"
            lines.append(f"      └─ {title_of(evidence.document_id)} "
                         f"[{evidence.source_class}, {where}]  {evidence.chunk_id}")
    lines.append("")

    # -- how the facts connect ---------------------------------------------
    if state.evidence_chain:
        lines.append("EVIDENCE CHAIN")
        for index, link in enumerate(state.evidence_chain, start=1):
            lines.append(f"  {index}. {link}")
        lines.append("")

    # -- disagreements ------------------------------------------------------
    if state.conflicts:
        lines.append("CONFLICTING SOURCES")
        for conflict in state.conflicts:
            lines.append(f"  {conflict['subject']} · {conflict['attribute']}")
            for position in conflict["positions"]:
                lines.append(f"    – \"{position['value']}\"  "
                             f"[{position['source_class']}, reliability "
                             f"{position['reliability']:.2f}]")
                for source in position["sources"][:2]:
                    lines.append(f"        {source}")
            lines.append(f"    → {conflict['resolution']}")
        lines.append("")

    # -- audit trail --------------------------------------------------------
    if show_trace:
        lines.append("INVESTIGATION TRACE")
        for iteration in state.iterations:
            lines.append(f"  [{iteration.number}] {iteration.action}  "
                         f"query: {iteration.query!r}")
            lines.append(f"      sub-question : {iteration.sub_question}")
            lines.append(f"      why          : {iteration.reason}")
            if iteration.retrieval_modes:
                lines.append(f"      searched     : {', '.join(iteration.retrieval_modes)}")
            for claim in iteration.new_claims[:3]:
                lines.append(f"      learned      : {claim}")
            if iteration.new_entities:
                lines.append(f"      new entities : {', '.join(iteration.new_entities[:5])}")
            if iteration.unresolved:
                lines.append(f"      still open   : {len(iteration.unresolved)} sub-question(s)")
        lines.append("")

    # -- why it stopped -----------------------------------------------------
    lines.append("STOPPED BECAUSE")
    lines.append(f"  {state.stop_reason.value}")
    lines.append(f"  {len(state.iterations)} iteration(s) · {state.queries_issued} query/queries "
                 f"· {state.graph_expansions} graph expansion(s) "
                 f"· {state.elapsed_seconds * 1000:.0f} ms")
    return "\n".join(lines)
