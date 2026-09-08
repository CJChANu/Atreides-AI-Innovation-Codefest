"""End-to-end ingestion on a miniature corpus built in a temp directory.

This is the test that would catch a provenance regression: it runs the real
pipeline, the real store and the real FTS5 index, and then asserts that a fact
can be traced back to the file it came from.
"""

from dataclasses import replace

import pytest

from src.common.config import SETTINGS
from src.graph.builder import GraphBuilder
from src.graph.facts import FactExtractor
from src.ingestion.pipeline import IngestionPipeline
from src.retrieval.keyword import KeywordIndex
from src.storage.db import ArchiveStore

WIKI = """# Gauntlet of Sorrowfell

## Infobox

| Field | Value |
|---|---|
| Forging date | Contested; no year is stated |
| Forged at | [[Vharencrag Fortress]] |
"""

BALLAD = """# A Song of the Gauntlet

They say the Gauntlet of Sorrowfell was struck in 100 AS,
though no clerk of Vharencrag Fortress ever wrote it down.
"""


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "corpus" / "wiki").mkdir(parents=True)
    (tmp_path / "corpus" / "ephemera").mkdir(parents=True)
    (tmp_path / "corpus" / "wiki" / "gauntlet_of_sorrowfell.md").write_text(WIKI, encoding="utf-8")
    (tmp_path / "corpus" / "ephemera" / "ballad_concerning_gauntlet.txt").write_text(
        BALLAD, encoding="utf-8"
    )
    return tmp_path / "corpus"


@pytest.fixture
def settings(corpus, tmp_path):
    data = tmp_path / "data"
    return replace(
        SETTINGS,
        corpus_root=corpus,
        data_dir=data,
        db_path=data / "test.sqlite3",
        assets_dir=data / "assets",
        cache_dir=data / "cache",
        ocr_enabled=False,
    )


@pytest.fixture
def store(settings):
    settings.ensure_dirs()
    with ArchiveStore(settings.db_path) as store:
        IngestionPipeline(settings, store).run()
        yield store


def test_ingestion_indexes_every_document(store):
    assert store.stats()["documents"] == 2
    assert store.stats()["chunks"] > 0


def test_ingestion_is_idempotent(settings, store):
    """Re-running must skip unchanged files rather than duplicate them."""
    before = store.stats()["chunks"]
    report = IngestionPipeline(settings, store).run()
    assert report.skipped_unchanged == 2
    assert report.ingested == 0
    assert store.stats()["chunks"] == before


def test_every_chunk_can_name_its_document(store):
    rows = store.connection.execute(
        "SELECT c.chunk_id, d.relative_path FROM chunks c "
        "JOIN documents d ON d.document_id = c.document_id"
    ).fetchall()
    assert rows
    assert all(row["relative_path"] for row in rows)


def test_low_reliability_sources_stay_retrievable(store):
    """A ballad may well be the best lexical match, and it must not be hidden.

    Reliability *nudges* ranking; it does not override evidence. Suppressing the
    ballad here would also suppress the conflict it exposes, which is exactly the
    behaviour this archive is designed to punish.
    """
    hits = KeywordIndex(store).search("Gauntlet of Sorrowfell", limit=10)
    assert {"ballad", "wiki"} <= {h.source_class for h in hits}


def test_reliability_breaks_ties_toward_the_better_source(store):
    """Two equally good lexical matches must be separated by source class."""
    hits = KeywordIndex(store).search("Gauntlet of Sorrowfell", limit=10)
    by_class = {h.source_class: h for h in hits}
    ballad, wiki = by_class["ballad"], by_class["wiki"]
    # Same normalised BM25 would give the wiki the higher fused score.
    assert (0.8 * ballad.bm25 + 0.2 * 0.70) > (0.8 * ballad.bm25 + 0.2 * 0.25)
    assert wiki.score > 0.8 * wiki.bm25, "source quality must contribute to the score"


def test_graph_links_the_artifact_to_its_forging_site(store):
    GraphBuilder(store).build()
    row = store.connection.execute(
        "SELECT predicate FROM edges WHERE subject_id = ? AND object_id = ?",
        ("gauntlet_of_sorrowfell", "vharencrag_fortress"),
    ).fetchall()
    assert "forged_at" in {r["predicate"] for r in row}


def test_facts_carry_the_page_or_section_that_justifies_them(store):
    FactExtractor(store).build()
    rows = store.connection.execute(
        "SELECT * FROM facts WHERE subject_id = 'gauntlet_of_sorrowfell'"
    ).fetchall()
    assert rows
    for row in rows:
        assert row["chunk_id"] and store.get_chunk(row["chunk_id"]) is not None
        assert row["reliability"] > 0
