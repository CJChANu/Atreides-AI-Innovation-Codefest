#!/usr/bin/env python3
"""Build every derived index on top of an ingested archive.

Keyword search is built during ingestion (FTS5 is populated as chunks are
written); this script builds the graph and the attribute-fact store, both of
which are deterministic and safe to re-run.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.graph.builder import GraphBuilder  # noqa: E402
from src.graph.facts import FactExtractor  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402


def main() -> int:
    started = time.perf_counter()
    with ArchiveStore(SETTINGS.db_path) as store:
        print("— knowledge graph —")
        print(GraphBuilder(store).build().summary())
        print("\n— attribute facts —")
        print(FactExtractor(store).build().summary())
    print(f"\nelapsed   {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
