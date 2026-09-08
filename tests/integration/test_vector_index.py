"""Local LSA embeddings and the persistent vector index."""

import numpy as np
import pytest

from src.ai_gateway.embeddings import EmbeddingAdapter, fit_local_model
from src.common.config import SETTINGS
from src.indexes.vector import VectorIndex

CORPUS = [
    "The Gravemaw Wyrm lairs in Marrowwell Abbey and is a sky hunter.",
    "Marrowwell Abbey is ruled by The Bleeding Crown and was founded in 235 AS.",
    "The Gauntlet of Sorrowfell is regalia forged at Vharencrag Fortress.",
    "Greyfell Citadel records a garrison strength of 3,095 souls under arms.",
    "The War of Drowned Light was won by The Silent Choir after a decade.",
    "A ballad of the marshes tells of lantern moths above Crookgate Keep.",
]


@pytest.fixture(scope="module")
def model():
    return fit_local_model(CORPUS, dimensions=8)


def test_embeddings_are_unit_length_or_exactly_zero(model):
    """Cosine similarity is a dot product only if the vectors are normalised.

    A document sharing no vocabulary with the fitted model embeds to zero rather
    than to an arbitrary direction — cosine 0 against everything is the honest
    representation of "no semantic signal". On the real archive this never
    happens (0 of 2,547 chunks); it only arises on a corpus too small to build a
    vocabulary from, as here.
    """
    norms = np.linalg.norm(model.embed(CORPUS), axis=1)
    assert np.all(np.isclose(norms, 1.0, atol=1e-5) | np.isclose(norms, 0.0, atol=1e-6))


def test_the_real_archive_has_no_unreachable_chunks():
    """Every indexed chunk must be findable by vector search, not just most."""
    index = VectorIndex(SETTINGS.data_dir / "vectors.npz")
    if not index.load():
        pytest.skip("no vector index built")
    norms = np.linalg.norm(index.vectors, axis=1)
    assert int((norms < 1e-6).sum()) == 0


def test_embeddings_are_deterministic(model):
    """A cited answer must reproduce for a judge on a later run."""
    assert np.array_equal(model.embed(CORPUS[:2]), model.embed(CORPUS[:2]))


def test_related_documents_are_closer_than_unrelated_ones(model):
    vectors = model.embed(CORPUS)
    wyrm_to_abbey = float(vectors[0] @ vectors[1])
    wyrm_to_ballad = float(vectors[0] @ vectors[5])
    assert wyrm_to_abbey > wyrm_to_ballad


def test_an_empty_text_does_not_crash_or_produce_nan(model):
    vector = model.embed([""])
    assert vector.shape[1] == model.dimensions
    assert not np.isnan(vector).any()


def test_the_model_round_trips_through_disk(model, tmp_path):
    from src.ai_gateway.embeddings import LocalEmbeddingModel

    path = tmp_path / "lsa.npz"
    model.save(path)
    reloaded = LocalEmbeddingModel.load(path)
    assert np.allclose(reloaded.embed(CORPUS), model.embed(CORPUS), atol=1e-6)


def test_search_returns_ranked_hits(model, tmp_path):
    index = VectorIndex(tmp_path / "vectors.npz")
    index.vectors = model.embed(CORPUS)
    index.chunk_ids = [f"chunk-{i}" for i in range(len(CORPUS))]
    index.model_name = "local-lsa"

    query = model.embed(["who rules the abbey"])[0]
    hits = index.search(query, limit=3)
    assert len(hits) == 3
    assert hits[0].score >= hits[1].score >= hits[2].score


def test_the_index_round_trips_through_disk(model, tmp_path):
    index = VectorIndex(tmp_path / "vectors.npz")
    index.vectors = model.embed(CORPUS)
    index.chunk_ids = [f"chunk-{i}" for i in range(len(CORPUS))]
    index.model_name = "local-lsa"
    index.save()

    reloaded = VectorIndex(tmp_path / "vectors.npz")
    assert reloaded.load()
    assert reloaded.ready
    assert reloaded.chunk_ids == index.chunk_ids
    assert reloaded.model_name == "local-lsa"


def test_an_unbuilt_index_searches_empty_rather_than_raising():
    index = VectorIndex(SETTINGS.data_dir / "does-not-exist.npz")
    assert not index.load()
    assert index.search(np.zeros(8, dtype=np.float32)) == []
