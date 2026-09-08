"""Calculation questions through the whole loop, on a miniature corpus.

Two behaviours are protected here, and they are the two halves of the same bug:
when both operands exist the loop must read *both* and show its arithmetic, and
when one is missing it must refuse and say which — never answer with the half it
happened to find.
"""

from dataclasses import replace

import pytest

from src.common.config import SETTINGS, InvestigationBudget
from src.generation.answer import headline
from src.graph.builder import GraphBuilder
from src.graph.facts import FactExtractor
from src.ingestion.pipeline import IngestionPipeline
from src.orchestration.investigator import Investigator
from src.orchestration.state import ClaimType, Intent, StopReason
from src.storage.db import ArchiveStore

HOLD = """# Embermarch

## Infobox

| Field | Value |
|---|---|
| Garrison strength | 4063 |
| Region | The Gloaming Reach |
"""

AEGIS = """# The Cinder-Wrought Aegis

## Infobox

| Field | Value |
|---|---|
| Attunement cost | 34 |
| Artifact class | regalia |
"""

# Named, numeric-attribute-bearing, but with no attunement cost recorded — the
# operand a calculation cannot be completed without.
LANTERN = """# The Thrice-Bound Lantern

## Infobox

| Field | Value |
|---|---|
| Artifact class | ward |
| Forged | 72 AS |
"""


@pytest.fixture
def investigator(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "wiki").mkdir(parents=True)
    (corpus / "wiki" / "embermarch.md").write_text(HOLD, encoding="utf-8")
    (corpus / "wiki" / "aegis.md").write_text(AEGIS, encoding="utf-8")
    (corpus / "wiki" / "lantern.md").write_text(LANTERN, encoding="utf-8")

    data = tmp_path / "data"
    settings = replace(SETTINGS, corpus_root=corpus, data_dir=data,
                       db_path=data / "t.sqlite3", assets_dir=data / "assets",
                       cache_dir=data / "cache", ocr_enabled=False)
    settings.ensure_dirs()
    with ArchiveStore(settings.db_path) as store:
        IngestionPipeline(settings, store).run()
        GraphBuilder(store).build()
        FactExtractor(store).build()
        yield Investigator(store, InvestigationBudget(max_iterations=8))


PERCENTAGE = ("What percentage of Embermarch's garrison strength is "
              "the Cinder-Wrought Aegis's attunement cost?")


def test_both_operands_are_read_not_just_the_first(investigator):
    """The reported bug: the second named entity was ignored entirely."""
    state = investigator.investigate(PERCENTAGE)
    assert state.question.intent is Intent.CALCULATION
    subjects = {operand["subject"] for operand in state.computation["operands"]}
    assert subjects == {"Embermarch", "The Cinder-Wrought Aegis"}


def test_the_arithmetic_is_correct_and_shown(investigator):
    state = investigator.investigate(PERCENTAGE)
    assert state.computation["result"] == pytest.approx(34 / 4063 * 100)
    assert headline(state) == "0.84%"
    # The formula is recorded, not re-derived, so trace and answer cannot differ.
    assert "÷" in state.computation["formula"]


def test_a_computed_value_is_inferred_rather_than_directly_stated(investigator):
    """No source states the percentage; it follows from two that state operands."""
    state = investigator.investigate(PERCENTAGE)
    computed = [c for c in state.claims if c.step_key == "compute"]
    assert computed and computed[0].claim_type is ClaimType.INFERRED


def test_every_operand_carries_a_citation(investigator):
    state = investigator.investigate(PERCENTAGE)
    for operand in state.computation["operands"]:
        assert operand["citations"], operand


def test_a_missing_operand_refuses_the_calculation_and_names_the_gap(investigator):
    state = investigator.investigate(
        "What percentage of Embermarch's garrison strength is "
        "the Thrice-Bound Lantern's attunement cost?"
    )
    assert state.computation["result"] is None
    answer = state.answer_value.lower()
    assert "not established" in answer
    assert "thrice-bound lantern" in answer
    assert state.stop_reason is not StopReason.ALL_SUPPORTED


def test_the_operand_that_was_found_is_still_reported(investigator):
    """A refusal should still hand back the half the archive does hold."""
    state = investigator.investigate(
        "What percentage of Embermarch's garrison strength is "
        "the Thrice-Bound Lantern's attunement cost?"
    )
    assert "4063" in state.answer_value


def test_a_pointless_conflict_check_does_not_spend_an_iteration(investigator):
    """One recorded value per operand means there is nothing to rank."""
    state = investigator.investigate(PERCENTAGE)
    actions = [iteration.action for iteration in state.iterations]
    assert "conflict_check" not in actions
    conflict = next(s for s in state.sub_questions if s.key == "conflict")
    assert conflict.satisfied and "no competing values" in conflict.note
