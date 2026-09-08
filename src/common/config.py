"""Central configuration.

Every tunable lives here so that the retrieval fusion weights, the investigation
budget and the corpus location can be changed without touching logic. Values are
read from the environment (or a .env file) exactly once, at import time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader.

    We deliberately avoid a dependency here: the file format we need is
    ``KEY=value`` with ``#`` comments, and nothing in the project benefits from
    python-dotenv's extra features. Existing environment variables always win,
    so a shell export can override the file.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


REPO_ROOT = Path(__file__).resolve().parents[2]
_load_dotenv(REPO_ROOT / ".env")


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class FusionWeights:
    """Weights for merging the retrieval channels into one candidate score.

    These are configuration, not universal truths. They start at the values from
    the technical plan and are only changed when the evaluation harness shows a
    consistent improvement across the development question set.
    """

    bm25: float = 0.35
    vector: float = 0.45
    entity_overlap: float = 0.10
    source_quality: float = 0.10


@dataclass(frozen=True)
class InvestigationBudget:
    """Hard limits on the 1C investigation loop.

    The loop is a bounded state machine, not an open-ended agent: it must always
    terminate, and it must be able to say which limit stopped it.
    """

    max_iterations: int = 6
    max_queries: int = 24
    max_graph_hops: int = 3
    stale_rounds_before_stop: int = 2
    max_seconds: float = 120.0


@dataclass(frozen=True)
class Settings:
    corpus_root: Path
    data_dir: Path
    db_path: Path
    assets_dir: Path
    cache_dir: Path
    fusion: FusionWeights = field(default_factory=FusionWeights)
    budget: InvestigationBudget = field(default_factory=InvestigationBudget)

    # --- LLM / embeddings (OpenAI-compatible gateway, see docs/decisions.md) ---
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    llm_api_key: str | None = None
    embedding_model: str = "voyage-4-lite"
    embedding_api_key: str | None = None

    # --- ingestion ---
    chunk_target_chars: int = 1200
    chunk_overlap_chars: int = 180
    ocr_enabled: bool = True

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.assets_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    data_dir = _env_path("AEA_DATA_DIR", REPO_ROOT / "data")
    return Settings(
        corpus_root=_env_path("AEA_CORPUS_ROOT", REPO_ROOT.parent / "Ashen_Era_Archive"),
        data_dir=data_dir,
        db_path=_env_path("AEA_DB_PATH", data_dir / "archive.sqlite3"),
        assets_dir=_env_path("AEA_ASSETS_DIR", data_dir / "assets"),
        cache_dir=_env_path("AEA_CACHE_DIR", data_dir / "cache"),
        fusion=FusionWeights(
            bm25=_env_float("AEA_W_BM25", 0.35),
            vector=_env_float("AEA_W_VECTOR", 0.45),
            entity_overlap=_env_float("AEA_W_ENTITY", 0.10),
            source_quality=_env_float("AEA_W_SOURCE", 0.10),
        ),
        budget=InvestigationBudget(
            max_iterations=_env_int("AEA_MAX_ITERATIONS", 6),
            max_queries=_env_int("AEA_MAX_QUERIES", 24),
            max_graph_hops=_env_int("AEA_MAX_GRAPH_HOPS", 3),
            stale_rounds_before_stop=_env_int("AEA_STALE_ROUNDS", 2),
            max_seconds=_env_float("AEA_MAX_SECONDS", 120.0),
        ),
        llm_base_url=os.environ.get("AEA_LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_model=os.environ.get("AEA_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        llm_api_key=os.environ.get("AEA_LLM_API_KEY"),
        embedding_model=os.environ.get("AEA_EMBEDDING_MODEL", "voyage-4-lite"),
        embedding_api_key=os.environ.get("AEA_EMBEDDING_API_KEY"),
        chunk_target_chars=_env_int("AEA_CHUNK_TARGET_CHARS", 1200),
        chunk_overlap_chars=_env_int("AEA_CHUNK_OVERLAP_CHARS", 180),
        ocr_enabled=os.environ.get("AEA_OCR_ENABLED", "1") not in {"0", "false", "False"},
    )


SETTINGS = load_settings()
