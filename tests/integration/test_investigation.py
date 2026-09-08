"""The investigation loop, end to end on a miniature corpus.

These tests exist to protect two properties that are easy to break and dangerous
to lose: the loop must terminate with a truthful stop reason, and it must never
report an answer it cannot cite.
"""

from dataclasses import replace

import pytest

from src.common.config import SETTINGS, InvestigationBudget
from src.generation.answer import headline, render
from src.graph.builder import GraphBuilder
from src.graph.fact_query import FactQuery
from src.graph.facts import FactExtractor
from src.ingestion.pipeline import IngestionPipeline
from src.orchestration.investigator import Investigator
from src.orchestration.state import ClaimType, StopReason
from src.storage.db import ArchiveStore

WYRM = """# Gravemaw Wyrm

## Infobox

| Field | Value |
|---|---|
| Lair | [[Marrowwell Abbey]] |
| Threat rating | 8 |
"""

ABBEY = """# Marrowwell Abbey

## Infobox

| Field | Value |
|---|---|
| Ruled by | [[The Bleeding Crown]] |
| Founded | Contested; no year is stated |
"""

CODEX = """# Marrowwell Abbey

## Classification

| Classification | Record |
|---|---|
| Founded | 235 AS |
| Ruling power | The Bleeding Crown |
"""


@pytest.fixture
def store(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "wiki").mkdir(parents=True)
    (corpus / "codex").mkdir(parents=True)
    (corpus / "wiki" / "gravemaw_wyrm.md").write_text(WYRM, encoding="utf-8")
    (corpus / "wiki" / "marrowwell_abbey.md").write_text(ABBEY, encoding="utf-8")
    (corpus / "codex" / "gazetteer.md").write_text(CODEX, encoding="utf-8")

    data = tmp_path / "data"
    settings = replace(SETTINGS, corpus_root=corpus, data_dir=data,
                       db_path=data / "t.sqlite3", assets_dir=data / "assets",
                       cache_dir=data / "cache", ocr_enabled=False)
    settings.ensure_dirs()
    with ArchiveStore(settings.db_path) as store:
        IngestionPipeline(settings, store).run()
        GraphBuilder(store).build()
        FactExtractor(store).build()
        yield store


@pytest.fixture
def investigator(store):
    return Investigator(store, InvestigationBudget(max_iterations=6))


def test_multi_hop_question_follows_the_discovered_link(investigator):
    state = investigator.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    assert headline(state) == "The Bleeding Crown"
    assert state.graph_expansions >= 1
    # The second query must name what the first one discovered.
    queries = [i.query for i in state.iterations]
    assert any("Marrowwell Abbey" in q for q in queries), queries


def test_the_hop_claim_is_inferred_not_direct(investigator):
    """No single source says the Wyrm's lair is ruled by the Bleeding Crown."""
    state = investigator.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    kinds = {c.claim_type for c in state.claims}
    assert ClaimType.INFERRED in kinds


def test_conflicting_sources_are_reported_and_ranked(investigator):
    state = investigator.investigate("What is the true founding year of Marrowwell Abbey?")
    assert state.conflicts, "a codex/wiki disagreement should be surfaced"
    conflict = state.conflicts[0]
    assert conflict["positions"][0]["source_class"] == "codex"
    assert headline(state) == "235 AS"


def test_a_conflicting_claim_is_never_reported_as_high_confidence(investigator):
    state = investigator.investigate("What is the true founding year of Marrowwell Abbey?")
    for claim in state.claims:
        if claim.claim_type is ClaimType.CONFLICTING:
            assert claim.confidence <= 0.6


def test_every_claim_can_name_a_chunk_that_exists(store, investigator):
    state = investigator.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    for claim in state.claims:
        for evidence in claim.evidence:
            assert store.get_chunk(evidence.chunk_id) is not None


def test_an_unanswerable_question_is_not_reported_as_supported(investigator):
    """The failure this guards against: 'not established' above 'all supported'."""
    state = investigator.investigate("What is the attunement cost of the Gravemaw Wyrm?")
    assert state.stop_reason is not StopReason.ALL_SUPPORTED
    assert all(c.claim_type is ClaimType.UNSUPPORTED for c in state.claims)


def test_an_unknown_entity_stops_immediately_and_says_why(investigator):
    state = investigator.investigate("Who commands the Fleet of Nowhere?")
    assert state.stop_reason is StopReason.NO_ENTITY
    assert len(state.iterations) == 1


def test_the_loop_respects_its_iteration_budget(store):
    tight = Investigator(store, InvestigationBudget(max_iterations=2))
    state = tight.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    assert len(state.iterations) <= 2
    assert state.stop_reason is StopReason.ITERATION_BUDGET


def test_a_budget_stop_is_rendered_as_partial(store):
    tight = Investigator(store, InvestigationBudget(max_iterations=2))
    state = tight.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    assert "PARTIAL" in render(state, FactQuery(store).title_of)


def test_the_trace_records_a_reason_for_every_step(investigator):
    state = investigator.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    assert state.iterations
    for iteration in state.iterations:
        assert iteration.reason, f"iteration {iteration.number} has no recorded reason"
        assert iteration.action


def test_the_serialised_trace_is_self_contained(store, investigator):
    state = investigator.investigate("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    payload = state.to_dict(FactQuery(store).title_of)
    assert payload["answer"] == "The Bleeding Crown"
    assert payload["investigation"]["stop_reason"]
    assert payload["trace"] and payload["evidence_chain"]


def test_an_answer_with_no_supported_claim_is_marked_partial(investigator):
    """A clean stop is not the same as a grounded answer.

    An open question can satisfy every sub-question ('relevant passages
    retrieved') and still ground nothing. Before this was fixed, such an answer
    reached the user with no PARTIAL warning at all.
    """
    from src.generation.answer import is_partial

    state = investigator.investigate("What colour is the Gravemaw Wyrm's left eye?")
    if any(c.claim_type is not ClaimType.UNSUPPORTED for c in state.claims):
        pytest.skip("this question grounded a claim on the fixture corpus")
    assert is_partial(state)
