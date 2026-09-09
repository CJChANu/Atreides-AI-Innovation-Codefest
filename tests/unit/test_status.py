"""Completion is decided in exactly one place.

The bug these pin: output that said PARTIAL, "all required sub-questions are
supported", and "unsupported claim" at the same time. Three components each
decided completeness from a different part of the state, and they disagreed.
"""

import pytest

from src.graph.fact_query import FactRow
from src.orchestration.state import (
    Claim,
    ClaimType,
    Intent,
    Investigation,
    Question,
    StopReason,
    SubQuestion,
)
from src.orchestration.status import InvestigationStatus, evaluate


def _row(reliability: float = 0.9) -> FactRow:
    return FactRow(subject_id="x", subject_name="X", attribute="a", value_text="v",
                   value_key="v", value_number=None, chunk_id="c1", document_id="d1",
                   page=1, source_class="codex", reliability=reliability)


def _state(*, satisfied: bool = True, claims=None,
           stop: StopReason = StopReason.ALL_SUPPORTED) -> Investigation:
    step = SubQuestion("target", "What is X's a?", "a value for a")
    if satisfied:
        step.satisfy([_row()], "found")
    else:
        step.fail("not found")
    state = Investigation(
        question=Question(text="q", intent=Intent.ATTRIBUTE_LOOKUP,
                          entities=[("x", "X")], attribute="a"),
        sub_questions=[step], stop_reason=stop)
    state.claims = claims if claims is not None else [
        Claim(text="X's a is v.", claim_type=ClaimType.DIRECT, confidence=0.9,
              evidence=[_row()], step_key="target")
    ]
    return state


def test_a_fully_supported_run_is_completed():
    report = evaluate(_state())
    assert report.status is InvestigationStatus.COMPLETED
    assert not report.is_partial


def test_an_unsupported_claim_is_never_completed():
    """The contradiction: a confident answer above 'no evidence'."""
    state = _state(claims=[Claim(text="nothing", claim_type=ClaimType.UNSUPPORTED,
                                 confidence=0.0)])
    report = evaluate(state)
    assert report.status is not InvestigationStatus.COMPLETED
    assert report.is_partial


def test_a_budget_stop_is_partial_even_with_a_supported_claim():
    report = evaluate(_state(stop=StopReason.ITERATION_BUDGET))
    assert report.status is InvestigationStatus.PARTIAL_BUDGET
    assert "budget" in " ".join(report.reasons).lower()


def test_an_unmet_requirement_keeps_it_partial():
    state = _state(satisfied=False, claims=[
        Claim(text="partial", claim_type=ClaimType.DIRECT, confidence=0.7,
              evidence=[_row()], step_key="other")])
    report = evaluate(state)
    assert report.is_partial
    assert report.unmet


def test_a_rate_limit_is_reported_as_a_rate_limit_not_a_missing_archive():
    """These need different responses: retry later versus the archive lacks it."""
    state = _state(satisfied=False, claims=[
        Claim(text="p", claim_type=ClaimType.DIRECT, confidence=0.7,
              evidence=[_row()], step_key="other")])
    report = evaluate(state, ["understanding: RateLimited"])
    assert report.status is InvestigationStatus.PARTIAL_RATE_LIMITED


def test_nothing_found_is_insufficient_evidence():
    state = _state(satisfied=False,
                   claims=[Claim(text="none", claim_type=ClaimType.UNSUPPORTED,
                                 confidence=0.0)],
                   stop=StopReason.INSUFFICIENT_EVIDENCE)
    report = evaluate(state)
    assert report.status is InvestigationStatus.INSUFFICIENT_EVIDENCE


def test_an_unreadable_image_is_not_blamed_on_the_archive():
    """'We could not see it' and 'the archive lacks it' are different answers."""
    state = _state(satisfied=False,
                   claims=[Claim(text="none", claim_type=ClaimType.UNSUPPORTED,
                                 confidence=0.0)],
                   stop=StopReason.INSUFFICIENT_EVIDENCE)
    state.visual_gaps = ["Heraldry plate: vision provider unavailable"]
    report = evaluate(state)
    assert report.status is InvestigationStatus.PARTIAL_VISUAL
    assert report.reasons


def test_a_claim_without_a_citation_blocks_completion():
    state = _state(claims=[Claim(text="X's a is v.", claim_type=ClaimType.DIRECT,
                                 confidence=0.9, evidence=[], step_key="target")])
    assert evaluate(state).status is not InvestigationStatus.COMPLETED


def test_no_matching_entity_has_its_own_status():
    state = _state(satisfied=False, stop=StopReason.NO_ENTITY,
                   claims=[Claim(text="none", claim_type=ClaimType.UNSUPPORTED,
                                 confidence=0.0)])
    assert evaluate(state).status is InvestigationStatus.NO_ENTITY


@pytest.mark.parametrize("status", list(InvestigationStatus))
def test_only_completed_is_not_partial(status):
    assert status.is_partial is (status is not InvestigationStatus.COMPLETED)


def test_the_report_serialises_for_the_ui():
    payload = evaluate(_state()).to_dict()
    assert payload["status"] == "completed"
    assert payload["is_complete"] is True
    assert payload["is_partial"] is False
