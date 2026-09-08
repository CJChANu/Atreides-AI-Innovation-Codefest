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

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.ai_gateway.embeddings import EmbeddingAdapter, LocalEmbeddingModel, fit_local_model
from src.storage.db import ArchiveStore

# Long chunks are truncated before embedding: the first part of a chunk carries
# its heading and topic, and the tail mostly dilutes the vector.
MAX_EMBED_CHARS = 2000


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

        adapter = EmbeddingAdapter(settings)
        if not adapter.use_api:
            model_path = settings.data_dir / "lsa_model.npz"
            model = fit_local_model(texts)
            model.save(model_path)
            adapter = EmbeddingAdapter(settings, model)

        self.vectors = adapter.embed(texts)
        self.chunk_ids = chunk_ids
        self.model_name = adapter.name
        self.save()
        return {
            "chunks_embedded": len(chunk_ids),
            "dimensions": int(self.vectors.shape[1]),
            "model": self.model_name,
            "index_bytes": self.path.stat().st_size,
        }

    # -- search -------------------------------------------------------------

    def search(self, query_vector: np.ndarray, *, limit: int = 20) -> list[VectorHit]:
        if not self.ready:
            return []
        assert self.vectors is not None
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
            return EmbeddingAdapter(settings, LocalEmbeddingModel.load(model_path))
    return EmbeddingAdapter(settings)
