"""Assembling a fully-wired investigator.

One place that decides which optional subsystems are present, so the CLI, the API
and the tests all get an identically-configured system — and so "what mode are we
in?" has exactly one answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.ai_gateway.gateway import AIGateway
from src.common.config import Settings
from src.indexes.vector import VectorIndex, load_adapter
from src.orchestration.investigator import Investigator
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.keyword import KeywordIndex
from src.storage.db import ArchiveStore


@dataclass
class SystemModes:
    """What is actually available right now, for /health and the UI banner."""

    keyword: bool
    facts: bool
    graph: bool
    vector: bool
    llm: bool
    embedding_model: str

    @property
    def label(self) -> str:
        if self.llm and self.vector:
            return "full (hybrid retrieval + LLM-assisted)"
        if self.vector:
            return "hybrid retrieval, deterministic reasoning"
        return "deterministic fallback (keyword + facts + graph)"

    def to_dict(self) -> dict:
        return {"keyword": self.keyword, "facts": self.facts, "graph": self.graph,
                "vector": self.vector, "llm": self.llm,
                "embedding_model": self.embedding_model, "mode": self.label}


def build_system(store: ArchiveStore, settings: Settings, *, budget=None):
    """Return (investigator, gateway, modes) with whatever is available wired in."""
    gateway = AIGateway(settings)

    vector = VectorIndex(settings.data_dir / "vectors.npz")
    embedder = None
    if vector.load():
        embedder = load_adapter(settings, vector)

    keyword = KeywordIndex(store)
    retriever = HybridRetriever(store, keyword, vector if vector.ready else None,
                                embedder, settings.fusion)

    investigator = Investigator(store, budget or settings.budget,
                                gateway=gateway, retriever=retriever)

    counts = store.stats()
    modes = SystemModes(
        keyword=counts["chunks"] > 0,
        facts=store.connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0] > 0,
        graph=store.connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0] > 0,
        vector=vector.ready,
        llm=gateway.available,
        embedding_model=vector.model_name or "(none)",
    )
    return investigator, gateway, modes
