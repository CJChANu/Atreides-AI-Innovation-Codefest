"""Reasoning questions end to end: facts as navigation, sources as evidence.

The question these protect cannot be answered by any stored value. Two facts are
recorded — when the relic was made, when the place was destroyed — and the answer
is the relationship between them. Getting it right requires finding events from
the *event's* record rather than the place's, reading a year out of prose because
no table holds it, and reporting custody as custody rather than as presence.
"""

from dataclasses import replace

import pytest

from src.common.config import SETTINGS, InvestigationBudget
from src.graph.builder import GraphBuilder
from src.graph.facts import FactExtractor
from src.ingestion.pipeline import IngestionPipeline
from src.orchestration.investigator import Investigator
from src.orchestration.state import ClaimType, Intent
from src.storage.db import ArchiveStore

# The relic's own page records where it is *housed* and says nothing about when
# it was made — the year lives in a contract about a different relic.
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

# Gloamreach's own page does not say it was devastated. Two different wars do.
WAR = """# The War of Drowned Light

## Infobox

| Field | Value |
|---|---|
| Began | 225 AS |
| Ended | 235 AS |
| Devastated | [[Gloamreach]] in 227 AS |
"""

PURGE = """# The Purge of Blackport

## Infobox

| Field | Value |
|---|---|
| Began | 311 AS |
| Related region and year | Devastated [[Gloamreach]] in 320 AS |
"""

PLACE = """# Gloamreach

## Infobox

| Field | Value |
|---|---|
| Region | The Pale Coast |
| Garrison strength | 2483 |
"""


@pytest.fixture
def investigator(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "wiki").mkdir(parents=True)
    (corpus / "ephemera").mkdir(parents=True)
    for name, body in [("aegis", AEGIS), ("war", WAR), ("purge", PURGE),
                       ("gloamreach", PLACE)]:
        (corpus / "wiki" / f"{name}.md").write_text(body, encoding="utf-8")
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


QUESTION = ("Why would it be incorrect to conclude that the Cinder-Wrought Aegis "
            "was present in Gloamreach when it was devastated?")


def test_the_question_is_recognised_as_reasoning_not_lookup(investigator):
    state = investigator.investigate(QUESTION)
    assert state.question.intent is Intent.TEMPORAL_CHECK


def test_the_conclusion_is_reached_and_explained(investigator):
    state = investigator.investigate(QUESTION)
    answer = state.answer_value
    assert "does not follow" in answer
    assert "354" in answer          # when the relic was made
    assert "227" in answer          # when the place was destroyed


def test_both_devastations_are_found_not_just_the_first(investigator):
    """Gloamreach was devastated twice, by two different wars."""
    state = investigator.investigate(QUESTION)
    years = {finding["event_year"] for finding in state.computation["findings"]}
    assert years == {227, 320}


def test_events_are_found_from_the_events_own_record(investigator):
    """Gloamreach's page says nothing about being devastated; the wars' pages do."""
    state = investigator.investigate(QUESTION)
    events = [c for c in state.claims if c.step_key == "events"]
    assert {e.evidence[0].subject_name for e in events} == {
        "The War of Drowned Light", "The Purge of Blackport"}


def test_the_origin_year_is_read_from_prose_in_another_document(investigator):
    state = investigator.investigate(QUESTION)
    origin = next(c for c in state.claims if c.step_key == "origin")
    assert "354 AS" in origin.text
    assert "contract" in origin.evidence[0].document_id.lower() or origin.evidence


def test_custody_is_distinguished_from_presence(investigator):
    state = investigator.investigate(QUESTION)
    assert "where it is kept" in state.answer_value


def test_the_conclusion_is_derived_not_direct(investigator):
    """No source states it; it follows from two that state the dates."""
    state = investigator.investigate(QUESTION)
    conclusion = next(c for c in state.claims if c.step_key == "temporal")
    assert conclusion.claim_type is ClaimType.INFERRED


def test_every_fact_quotes_the_line_it_was_read_from(investigator):
    """The fact store located the evidence; the archive still holds it."""
    state = investigator.investigate(QUESTION)
    direct = [c for c in state.claims if c.claim_type is ClaimType.DIRECT]
    assert direct
    for claim in direct:
        assert claim.evidence[0].excerpt, claim.text


def test_each_investigation_has_its_own_identity(investigator):
    first = investigator.investigate(QUESTION)
    second = investigator.investigate("What is the garrison strength of Gloamreach?")
    assert first.investigation_id != second.investigation_id
    assert "354" not in second.answer_value
    assert second.computation.get("kind") != "temporal"
