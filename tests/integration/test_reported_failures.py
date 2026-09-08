"""The failures reported from a round of image, cross-document and multi-part testing.

One test per reported symptom, phrased as the behaviour that was wrong, so a
regression names the original complaint rather than an internal step key.
"""

from dataclasses import replace

import pytest

from src.common.config import SETTINGS, InvestigationBudget
from src.graph.builder import GraphBuilder
from src.graph.facts import FactExtractor
from src.ingestion.pipeline import IngestionPipeline
from src.orchestration.investigator import Investigator
from src.orchestration.state import Intent, StopReason
from src.storage.db import ArchiveStore

# A relic whose housing is recorded under a label the alias map used to miss,
# and whose forging year is stated only in another document's prose.
AEGIS = """# The Cinder-Wrought Aegis

The artifact was forged at [[Embermarch]] and is housed in [[Gloamreach]].

## Infobox

| Field | Value |
|---|---|
| Artifact class | regalia |
| Place of forging | [[Embermarch]] |
| Place of housing | [[Gloamreach]] |
"""

CONTRACT = """# Contract concerning the Chalice of Ashdeep

1. The **Chalice of Ashdeep**, a ward of the deep vaults.

2. **The Cinder-Wrought Aegis**, regalia shaped by the legacy of the Sundering.
Its forged year is **354 AS**.
"""

LURKER = """# Weeping Lurker

## Infobox

| Field | Value |
|---|---|
| Threat rating | 3 |
| Lair | [[Marrowwell Abbey]] |
"""

REVENANT = """# Marsh Revenant

## Infobox

| Field | Value |
|---|---|
| Threat rating | 4 |
| Habit | siege-breaker |
"""

HOLD = """# Embermarch

## Infobox

| Field | Value |
|---|---|
| Garrison strength | 4063 |
"""


@pytest.fixture
def investigator(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "wiki").mkdir(parents=True)
    (corpus / "ephemera").mkdir(parents=True)
    (corpus / "wiki" / "aegis.md").write_text(AEGIS, encoding="utf-8")
    (corpus / "wiki" / "weeping_lurker.md").write_text(LURKER, encoding="utf-8")
    (corpus / "wiki" / "marsh_revenant.md").write_text(REVENANT, encoding="utf-8")
    (corpus / "wiki" / "embermarch.md").write_text(HOLD, encoding="utf-8")
    (corpus / "ephemera" / "contract_concerning_chalice.md").write_text(
        CONTRACT, encoding="utf-8")

    data = tmp_path / "data"
    settings = replace(SETTINGS, corpus_root=corpus, data_dir=data,
                       db_path=data / "t.sqlite3", assets_dir=data / "assets",
                       cache_dir=data / "cache", ocr_enabled=False)
    settings.ensure_dirs()
    with ArchiveStore(settings.db_path) as store:
        IngestionPipeline(settings, store).run()
        GraphBuilder(store).build()
        FactExtractor(store).build()
        yield Investigator(store, InvestigationBudget(max_iterations=12))


def test_1_a_text_attribute_is_answered_from_text(investigator):
    """Reported: the housing question searched the plate and reported it pictorial."""
    state = investigator.investigate("Where is the Cinder-Wrought Aegis housed?")
    assert state.answer_value == "Gloamreach"
    assert "pictorial" not in state.answer_value.lower()


def test_3_a_value_stated_only_in_prose_is_still_found(investigator):
    """Reported: 'not established' while the value sat in a retrieved passage."""
    state = investigator.investigate("In which year was the Cinder-Wrought Aegis forged?")
    assert "354 AS" in state.answer_value


def test_6_a_multi_part_question_answers_every_part(investigator):
    state = investigator.investigate(
        "Where and in which year was the Cinder-Wrought Aegis forged, "
        "and where is it housed?"
    )
    assert state.question.intent is Intent.MULTI_FACT
    answer = state.answer_value
    assert "Embermarch" in answer      # forging site
    assert "354 AS" in answer          # forging year, from prose
    assert "Gloamreach" in answer      # housing


def test_7_the_loop_does_not_stop_while_a_required_fact_is_unsearched(investigator):
    state = investigator.investigate(
        "Where and in which year was the Cinder-Wrought Aegis forged, "
        "and where is it housed?"
    )
    operand_steps = [s for s in state.sub_questions if s.key.startswith("operand:")]
    assert len(operand_steps) >= 3
    assert all(step.attempted for step in operand_steps)


def test_8_a_single_value_is_returned_rather_than_ranked(investigator):
    """Reported: it tried to rank a 'most authoritative' value with no competitor."""
    state = investigator.investigate("What is the true threat rating of the Marsh Revenant?")
    assert state.answer_value == "4"
    assert state.stop_reason is StopReason.ALL_SUPPORTED
    resolve = next((s for s in state.sub_questions if s.key == "resolve"), None)
    assert resolve is not None and resolve.satisfied


def test_9_a_comparison_uses_both_subjects(investigator):
    """Reported: a two-creature comparison answered about one of them."""
    state = investigator.investigate(
        "Compare the threat ratings of the Weeping Lurker and the Marsh Revenant.")
    assert "3" in state.answer_value and "4" in state.answer_value
    assert "Weeping Lurker" in state.answer_value
    assert "Marsh Revenant" in state.answer_value


def test_9_a_new_question_reuses_nothing_from_the_last(investigator):
    """Reported: a prior question's number appeared in an unrelated answer."""
    first = investigator.investigate(
        "What percentage of Embermarch's garrison strength is "
        "the Cinder-Wrought Aegis's attunement cost?")
    assert "4063" in str(first.computation) or "Not established" in first.answer_value

    second = investigator.investigate(
        "Compare the threat ratings of the Weeping Lurker and the Marsh Revenant.")
    assert "4063" not in second.answer_value
    assert "Embermarch" not in second.answer_value
    assert all("Embermarch" not in link for link in second.evidence_chain)
    assert second.computation.get("kind") != "percentage"
