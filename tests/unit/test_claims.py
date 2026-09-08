"""Confidence scoring must never let a weak chain look strong."""

from src.graph.fact_query import FactRow
from src.verification.claims import CONFLICT_CEILING, SINGLE_SOURCE_CEILING, score
from src.verification.conflicts import describe_conflict
from src.graph.fact_query import AttributeView


def _row(reliability=1.0, document_id="doc-1", value="391 AS", source="codex"):
    return FactRow("s", "S", "forging_date", value, value.lower(), None,
                   "chunk-1", document_id, 11, source, reliability)


def test_a_single_source_is_capped_however_authoritative():
    assert score([_row(reliability=1.0)]) == SINGLE_SOURCE_CEILING


def test_independent_corroboration_raises_confidence():
    one = score([_row(document_id="doc-1")])
    two = score([_row(document_id="doc-1"), _row(document_id="doc-2")])
    assert two > one


def test_repeating_the_same_document_is_not_corroboration():
    single = score([_row(document_id="doc-1")])
    repeated = score([_row(document_id="doc-1"), _row(document_id="doc-1")])
    assert repeated == single


def test_each_hop_reduces_confidence():
    assert score([_row()], hops=1) < score([_row()], hops=0)


def test_an_unresolved_conflict_can_never_read_as_confident():
    assert score([_row(reliability=1.0)], conflicting=True) <= CONFLICT_CEILING


def test_no_evidence_scores_zero():
    assert score([]) == 0.0


def _view():
    view = AttributeView("gauntlet", "Gauntlet of Sorrowfell", "forging_date")
    view.groups["391 as"] = [_row(1.0, "doc-codex", "391 AS", "codex")]
    view.groups["contested"] = [_row(0.70, "doc-wiki", "Contested", "wiki")]
    return view


def test_a_clear_reliability_gap_resolves_the_conflict():
    result = describe_conflict(_view(), lambda d: d)
    assert result["resolvable_by_reliability"]
    assert result["positions"][0]["value"] == "391 AS"


def test_comparable_sources_leave_the_conflict_open():
    """Two sources of similar authority disagreeing is a real open question."""
    view = AttributeView("x", "X", "founded")
    view.groups["a"] = [_row(0.75, "doc-a", "200 AS", "chronicle")]
    view.groups["b"] = [_row(0.70, "doc-b", "300 AS", "wiki")]
    result = describe_conflict(view, lambda d: d)
    assert not result["resolvable_by_reliability"]
    assert "does not settle" in result["resolution"]
