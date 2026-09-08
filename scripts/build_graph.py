#!/usr/bin/env python3
"""Build the knowledge graph from the ingested chunks.

Run after `ingest_archive.py`. Deterministic and re-runnable: the graph tables are
rebuilt from scratch every time, from evidence already stored in the index.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.graph.builder import GraphBuilder  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402


def main() -> int:
    started = time.perf_counter()
    with ArchiveStore(SETTINGS.db_path) as store:
        report = GraphBuilder(store).build()
    print(report.summary())
    print(f"elapsed  {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
