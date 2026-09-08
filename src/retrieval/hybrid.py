"""Hybrid retrieval: lexical, semantic, entity overlap and source quality fused.

Each channel fails where another succeeds, and this archive exercises both
failures constantly:

* **BM25** nails "Vharencrag Fortress" and "391 AS" — invented proper nouns and
  exact numbers — and misses "who came out on top" for a page that says "the
  victor was".
* **Vectors** catch that paraphrase and blur exactly the rare names BM25 is best
  at, because a name that appears in four documents has little to separate it.

Fusion is a transparent weighted sum with every component preserved on the hit,
so a trace can show *why* a passage was selected rather than just that it was.
Reciprocal-rank fusion was the alternative; we kept the weighted sum because the
components stay interpretable and the weights are configuration we can defend
against the evaluation set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from src.ai_gateway.embeddings import EmbeddingAdapter
from src.common.config import FusionWeights
from src.common.provenance import reliability_of
from src.indexes.vector import VectorIndex
from src.retrieval.keyword import KeywordIndex
from src.storage.db import ArchiveStore

_WORD = re.compile(r"[A-Za-z][\w'-]+")
# Candidates pulled from each channel before fusion. Wider than the final result
# so a passage ranked 15th lexically can still win on the combined score.
CANDIDATE_DEPTH = 30


@dataclass
class FusedHit:
    chunk_id: str
    document_id: str
    content: str
    page_start: int | None
    section_path: str
    source_class: str
    title: str
    relative_path: str
    # Component scores, kept for the trace.
    lexical: float = 0.0
    semantic: float = 0.0
    entity_overlap: float = 0.0
    source_quality: float = 0.0
    score: float = 0.0
    channels: list[str] = field(default_factory=list)

    def citation(self) -> str:
        where = f"p.{self.page_start}" if self.page_start else (self.section_path or "—")
        return f"{self.title} ({self.source_class}, {where})"

    def explain(self) -> str:
        return (f"lex {self.lexical:.2f} · vec {self.semantic:.2f} · "
                f"ent {self.entity_overlap:.2f} · src {self.source_quality:.2f} "
                f"→ {self.score:.3f} [{'+'.join(self.channels)}]")


class HybridRetriever:
    def __init__(self, store: ArchiveStore, keyword: KeywordIndex,
                 vector: VectorIndex | None, embedder: EmbeddingAdapter | None,
                 weights: FusionWeights) -> None:
        self.store = store
        self.keyword = keyword
        self.vector = vector
        self.embedder = embedder
        self.weights = weights

    @property
    def semantic_available(self) -> bool:
        return bool(self.vector and self.vector.ready and self.embedder)

    def search(self, query: str, *, limit: int = 8,
               entities: list[str] | None = None) -> list[FusedHit]:
        candidates: dict[str, FusedHit] = {}

        for hit in self.keyword.search(query, limit=CANDIDATE_DEPTH):
            fused = candidates.setdefault(hit.chunk_id, self._blank(hit.chunk_id))
            self._fill_from_row(fused, hit)
            fused.lexical = hit.bm25
            fused.channels.append("bm25")

        if self.semantic_available:
            try:
                vector = self.embedder.embed([query])[0]
                for hit in self.vector.search(vector, limit=CANDIDATE_DEPTH):
                    fused = candidates.get(hit.chunk_id)
                    if fused is None:
                        fused = self._blank(hit.chunk_id)
                        if not self._hydrate(fused):
                            continue
                        candidates[hit.chunk_id] = fused
                    # Cosine over LSA runs slightly negative for unrelated text;
                    # clamping keeps the fused score interpretable as 0..1.
                    fused.semantic = max(0.0, hit.score)
                    fused.channels.append("vector")
            except Exception:
                # Semantic retrieval is an enhancement. Losing it degrades recall,
                # never correctness, so the lexical result still stands.
                pass

        wanted = {e.lower() for e in (entities or [])}
        for fused in candidates.values():
            fused.entity_overlap = self._overlap(fused.content, wanted)
            fused.source_quality = reliability_of(fused.source_class)
            fused.score = (
                self.weights.bm25 * fused.lexical
                + self.weights.vector * fused.semantic
                + self.weights.entity_overlap * fused.entity_overlap
                + self.weights.source_quality * fused.source_quality
            )

        ranked = sorted(candidates.values(), key=lambda h: h.score, reverse=True)
        return ranked[:limit]

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _blank(chunk_id: str) -> FusedHit:
        return FusedHit(chunk_id=chunk_id, document_id="", content="", page_start=None,
                        section_path="", source_class="unknown", title="", relative_path="")

    @staticmethod
    def _fill_from_row(fused: FusedHit, hit) -> None:
        fused.document_id = hit.document_id
        fused.content = hit.content
        fused.page_start = hit.page_start
        fused.section_path = hit.section_path
        fused.source_class = hit.source_class
        fused.title = hit.title
        fused.relative_path = hit.relative_path

    def _hydrate(self, fused: FusedHit) -> bool:
        """Load metadata for a chunk the lexical channel did not return."""
        row = self.store.connection.execute(
            """SELECT c.document_id, c.content, c.page_start, c.section_path,
                      c.source_class, d.title, d.relative_path
               FROM chunks c JOIN documents d ON d.document_id = c.document_id
               WHERE c.chunk_id = ?""",
            (fused.chunk_id,),
        ).fetchone()
        if row is None:
            return False
        fused.document_id = row["document_id"]
        fused.content = row["content"]
        fused.page_start = row["page_start"]
        fused.section_path = row["section_path"]
        fused.source_class = row["source_class"]
        fused.title = row["title"]
        fused.relative_path = row["relative_path"]
        return True

    @staticmethod
    def _overlap(content: str, wanted: set[str]) -> float:
        """Fraction of the question's known entities that appear in the passage.

        Cheap, but it is what stops a semantically similar passage about a
        *different* fortress outranking the one actually asked about.
        """
        if not wanted:
            return 0.0
        lowered = content.lower()
        return sum(1 for name in wanted if name in lowered) / len(wanted)
