"""One authoritative answer to "is this investigation finished, and how did it end?"

The system used to answer that question in three places — the renderer decided
whether to print PARTIAL, the loop recorded a stop reason, and the claim builder
decided whether anything was supported — and they could disagree. They did:

    ANSWER  ... ⚠ PARTIAL
    STOPPED BECAUSE  all required sub-questions are supported
    SUPPORTING CLAIMS  ○ The archive does not record a value ... (unsupported)

Three statements about the same run, mutually contradictory, all true of some
part of the state. A reader cannot act on that, and neither can a UI.

So completion is derived exactly once, here, from the whole state, and everything
downstream reads the result. `InvestigationStatus` is the vocabulary: it says
whether the run finished, and when it did not, which specific thing stopped it —
budget, no progress, a rate limit, an unresolved conflict, or an archive that
genuinely lacks the evidence.

The rule for `COMPLETED` is deliberately strict, because it is the only status
that invites a reader to stop checking: every required sub-question satisfied,
every required calculation done, every claim carrying a citation, and no
unresolved conflict left standing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.orchestration.state import ClaimType, Investigation, StopReason


class InvestigationStatus(str, Enum):
    """How an investigation ended. Exactly one applies to a finished run."""

    COMPLETED = "completed"
    PARTIAL_BUDGET = "partial_budget"
    PARTIAL_NO_PROGRESS = "partial_no_progress"
    PARTIAL_RATE_LIMITED = "partial_rate_limited"
    PARTIAL_VISUAL = "partial_visual"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_ENTITY = "no_entity"
    FAILED = "failed"

    @property
    def is_complete(self) -> bool:
        return self is InvestigationStatus.COMPLETED

    @property
    def is_partial(self) -> bool:
        """True when the answer must carry a caveat.

        Everything that is not a clean completion is partial for display
        purposes, including an honest "the archive does not have this" — the
        reader still needs to know the answer is not a finding.
        """
        return self is not InvestigationStatus.COMPLETED


# Which stop reasons mean "we ran out of room" rather than "we are done".
_BUDGET_STOPS = {
    StopReason.ITERATION_BUDGET,
    StopReason.QUERY_BUDGET,
    StopReason.TIME_BUDGET,
}

# Fallback events that mean a provider refused us rather than the archive
# failing. Reported separately because the fix is different: retry later, versus
# the archive genuinely not holding the answer.
_RATE_LIMIT_MARKERS = ("ratelimited", "rate limited", "429", "circuit open")


@dataclass
class StatusReport:
    """The single verdict, with the reasons that produced it."""

    status: InvestigationStatus
    headline: str
    reasons: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return self.status.is_partial

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "headline": self.headline,
            "is_complete": self.status.is_complete,
            "is_partial": self.status.is_partial,
            "reasons": self.reasons,
            "unmet_requirements": self.unmet,
        }


def _rate_limited(fallback_events: list[str]) -> bool:
    joined = " ".join(fallback_events).lower()
    return any(marker in joined for marker in _RATE_LIMIT_MARKERS)


def _supported_claims(state: Investigation) -> list:
    return [c for c in state.claims if c.claim_type is not ClaimType.UNSUPPORTED]


def _claims_are_cited(state: Investigation) -> bool:
    """Every supported claim must name at least one piece of evidence.

    A claim with no evidence is a sentence, not a finding, and an investigation
    that produced one has not completed regardless of how its loop terminated.
    """
    supported = _supported_claims(state)
    return bool(supported) and all(claim.evidence for claim in supported)


def evaluate(state: Investigation, fallback_events: list[str] | None = None) -> StatusReport:
    """Derive the one status for this investigation."""
    events = fallback_events or []
    unmet = [step.text for step in state.sub_questions if not step.satisfied]
    reasons: list[str] = []

    # Nothing in the question matched the archive at all.
    if state.stop_reason is StopReason.NO_ENTITY:
        return StatusReport(
            status=InvestigationStatus.NO_ENTITY,
            headline="No entity in the question matched anything in the archive.",
            reasons=["the question named nothing the index contains"],
            unmet=unmet,
        )

    supported = _supported_claims(state)

    # An unresolved conflict outranks a clean finish: the loop may have done
    # everything asked of it and still be unable to say which value is right.
    unresolved_conflict = any(
        not conflict.get("resolved", True) for conflict in state.conflicts
    )

    if not supported:
        # No grounded claim. Whether that is "the archive lacks it" or "we were
        # cut off" depends on why we stopped.
        #
        # Visual gaps are checked first and deliberately: an image we could not
        # read is not an archive that lacks the answer. The evidence exists, on
        # a named asset, and the reader can open it — reporting that as
        # "insufficient evidence" blames the corpus for our own blind spot.
        if state.visual_gaps:
            return StatusReport(
                status=InvestigationStatus.PARTIAL_VISUAL,
                headline="The answer is in an image the system could not read.",
                reasons=list(state.visual_gaps), unmet=unmet)
        if state.stop_reason in _BUDGET_STOPS:
            return StatusReport(
                status=InvestigationStatus.PARTIAL_BUDGET,
                headline="Stopped on the investigation budget before finding evidence.",
                reasons=[state.stop_reason.value], unmet=unmet)
        if _rate_limited(events):
            return StatusReport(
                status=InvestigationStatus.PARTIAL_RATE_LIMITED,
                headline="A provider was rate-limited before the archive was fully searched.",
                reasons=events[:4], unmet=unmet)
        return StatusReport(
            status=InvestigationStatus.INSUFFICIENT_EVIDENCE,
            headline="The archive holds no evidence that answers this.",
            reasons=[state.stop_reason.value], unmet=unmet)

    # There is at least one supported claim. Completion now depends on whether
    # everything the plan required actually happened.
    if state.stop_reason in _BUDGET_STOPS:
        reasons.append(state.stop_reason.value)
        return StatusReport(
            status=InvestigationStatus.PARTIAL_BUDGET,
            headline="Answered in part; the investigation budget stopped it early.",
            reasons=reasons, unmet=unmet)

    if unmet:
        if _rate_limited(events):
            return StatusReport(
                status=InvestigationStatus.PARTIAL_RATE_LIMITED,
                headline="Answered in part; a provider was rate-limited.",
                reasons=events[:4], unmet=unmet)
        if state.stop_reason is StopReason.NO_NEW_EVIDENCE:
            return StatusReport(
                status=InvestigationStatus.PARTIAL_NO_PROGRESS,
                headline="Answered in part; further searching found nothing new.",
                reasons=[state.stop_reason.value], unmet=unmet)
        return StatusReport(
            status=InvestigationStatus.PARTIAL_NO_PROGRESS,
            headline="Answered in part; some requirements were not established.",
            reasons=[state.stop_reason.value], unmet=unmet)

    if unresolved_conflict:
        return StatusReport(
            status=InvestigationStatus.UNRESOLVED_CONFLICT,
            headline="Sources disagree and the archive does not settle it.",
            reasons=["competing values could not be ranked"], unmet=unmet)

    if state.visual_gaps:
        return StatusReport(
            status=InvestigationStatus.PARTIAL_VISUAL,
            headline="Answered in part; visual evidence could not be fully read.",
            reasons=list(state.visual_gaps), unmet=unmet)

    if not _claims_are_cited(state):
        return StatusReport(
            status=InvestigationStatus.PARTIAL_NO_PROGRESS,
            headline="Answered in part; a claim could not be tied to a source.",
            reasons=["a supported claim carried no citation"], unmet=unmet)

    return StatusReport(
        status=InvestigationStatus.COMPLETED,
        headline="Every requirement was established from cited archive evidence.",
        reasons=[state.stop_reason.value], unmet=[])
