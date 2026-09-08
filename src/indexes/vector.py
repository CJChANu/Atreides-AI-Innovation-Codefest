"""Persistent vector index over archive chunks.

Stored as a single compressed ``.npz`` beside the SQLite database: a matrix of
unit-length vectors plus the chunk IDs they belong to, and the embedding model
name so a query is never compared against vectors from a different model.

Search is exact brute-force cosine. At 2,547 chunks × 256 dimensions that is one
small matrix multiply — under a millisecond — and an approximate index (HNSW,
IVF) would add a dependency, a tuning surface and a recall cliff to solve a
problem this corpus does not have.

What gets embedded matters as much as how: table text, figure captions and OCR
output are embedded alongside prose, because in this archive the answer is
frequently in a table or on a plate rather than in a sentence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.ai_gateway.embeddings import (
    API_BATCH_SIZE,
    EmbeddingAdapter,
    LocalEmbeddingModel,
    fit_local_model,
)
from src.storage.db import ArchiveStore

# Long chunks are truncated before embedding: the first part of a chunk carries
# its heading and topic, and the tail mostly dilutes the vector.
MAX_EMBED_CHARS = 2000
# Refuse a hosted embedding build slower than this and use LSA instead. Two
# minutes is generous for 2,547 chunks on a paid tier and impossible on a
# rate-limited free one, which is exactly the distinction we want to draw.
MAX_HOSTED_BUILD_SECONDS = 120.0


@dataclass
class VectorHit:
    chunk_id: str
    score: float


class VectorIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.chunk_ids: list[str] = []
        self.vectors: np.ndarray | None = None
        self.model_name: str = ""

    # -- lifecycle ----------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self.vectors is not None and len(self.chunk_ids) > 0

    def load(self) -> bool:
        if not self.path.is_file():
            return False
        data = np.load(self.path, allow_pickle=False)
        self.vectors = data["vectors"]
        self.chunk_ids = [str(c) for c in data["chunk_ids"]]
        self.model_name = str(data["model_name"])
        return True

    def save(self) -> None:
        assert self.vectors is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.path, vectors=self.vectors,
                            chunk_ids=np.array(self.chunk_ids), model_name=self.model_name)

    # -- build --------------------------------------------------------------

    def build(self, store: ArchiveStore, settings) -> dict[str, object]:
        """Fit the local model if needed, embed every chunk, and persist."""
        rows = store.connection.execute(
            """SELECT c.chunk_id, c.content
               FROM chunks c JOIN documents d ON d.document_id = c.document_id
               WHERE d.superseded_by IS NULL AND length(trim(c.content)) > 0
               ORDER BY c.chunk_id"""
        ).fetchall()
        if not rows:
            raise RuntimeError("no chunks to embed — run ingest_archive.py first")

        chunk_ids = [r["chunk_id"] for r in rows]
        texts = [r["content"][:MAX_EMBED_CHARS] for r in rows]

        model_path = settings.data_dir / "lsa_model.npz"
        note = ""

        # LSA is fitted unconditionally, and first. It costs seven seconds, and it
        # means every later failure has a complete substitute already in hand —
        # rather than discovering at chunk 2,000 that there is nothing to fall
        # back to and leaving a half-built index behind.
        local = fit_local_model(texts)
        local.save(model_path)
        adapter = EmbeddingAdapter(settings, local, force_local=True)

        hosted = EmbeddingAdapter(settings, local)
        if hosted.use_api:
            feasible, note = self._hosted_is_feasible(hosted, texts)
            if feasible:
                adapter = hosted

        self.vectors = adapter.embed(texts)
        if adapter.use_api is False and adapter.api_error:
            note = f"hosted embeddings failed mid-build ({adapter.api_error}); used local LSA"
        self.chunk_ids = chunk_ids
        self.model_name = adapter.name
        self.save()
        return {
            "chunks_embedded": len(chunk_ids),
            "dimensions": int(self.vectors.shape[1]),
            "model": self.model_name,
            "index_bytes": self.path.stat().st_size,
            **({"note": note} if note else {}),
        }

    @staticmethod
    def _hosted_is_feasible(adapter, texts: list[str]) -> tuple[bool, str]:
        """Time one batch and refuse a hosted build that would take too long.

        A single successful call proves the key works; it says nothing about the
        provider's *rate* limit, which is what actually decides whether a build is
        possible. Voyage without a payment method allows 3 requests/minute and
        10,000 tokens/minute — around two hours for this corpus — so we measure
        throughput and fall back rather than hang.
        """
        started = time.perf_counter()
        try:
            adapter._embed_via_api(texts[:API_BATCH_SIZE])
        except Exception as error:
            return False, (f"hosted embeddings unavailable "
                           f"({type(error).__name__}: {str(error)[:120]}); used local LSA")

        per_batch = time.perf_counter() - started
        batches = (len(texts) + API_BATCH_SIZE - 1) // API_BATCH_SIZE
        estimate = per_batch * batches
        if estimate > MAX_HOSTED_BUILD_SECONDS:
            return False, (f"hosted build estimated at {estimate / 60:.0f} min "
                           f"({per_batch:.1f}s per {API_BATCH_SIZE} chunks — free-tier "
                           f"rate limit); used local LSA instead")
        return True, ""

    # -- search -------------------------------------------------------------

    def search(self, query_vector: np.ndarray, *, limit: int = 20) -> list[VectorHit]:
        if not self.ready:
            return []
        assert self.vectors is not None
        # A dimension mismatch means the query was embedded by a different model
        # than the index. Failing loudly beats a silent broadcast error that the
        # caller swallows and reports as "no semantic results".
        if query_vector.reshape(-1).shape[0] != self.vectors.shape[1]:
            raise ValueError(
                f"query vector has {query_vector.reshape(-1).shape[0]} dimensions but "
                f"the index was built with {self.vectors.shape[1]} by model "
                f"'{self.model_name}' — rebuild with scripts/build_indexes.py"
            )
        # Both sides are unit-length, so the dot product *is* the cosine.
        scores = self.vectors @ query_vector.reshape(-1)
        count = min(limit, scores.shape[0])
        top = np.argpartition(-scores, count - 1)[:count]
        top = top[np.argsort(-scores[top])]
        return [VectorHit(self.chunk_ids[i], float(scores[i])) for i in top]


def load_adapter(settings, index: VectorIndex) -> EmbeddingAdapter:
    """Rebuild the adapter that matches a persisted index."""
    if index.model_name == LocalEmbeddingModel.name:
        model_path = settings.data_dir / "lsa_model.npz"
        if model_path.is_file():
            return EmbeddingAdapter(settings, LocalEmbeddingModel.load(model_path),
                                force_local=True)
    return EmbeddingAdapter(settings)
