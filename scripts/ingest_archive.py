#!/usr/bin/env python3
"""Build the archive index from the read-only corpus.

    python scripts/ingest_archive.py                  # full archive
    python scripts/ingest_archive.py --only wiki      # one directory
    python scripts/ingest_archive.py --reset --force  # rebuild from scratch
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.ingestion.pipeline import IngestionPipeline  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="ingest only paths starting with this prefix, e.g. 'codex'")
    parser.add_argument("--limit", type=int, help="stop after N files (smoke testing)")
    parser.add_argument("--reset", action="store_true", help="drop all derived data first")
    parser.add_argument("--force", action="store_true", help="re-ingest even if unchanged")
    args = parser.parse_args()

    if not SETTINGS.corpus_root.is_dir():
        print(f"corpus not found: {SETTINGS.corpus_root}\n"
              f"set AEA_CORPUS_ROOT in .env (see configuration-example/)", file=sys.stderr)
        return 2

    SETTINGS.ensure_dirs()
    print(f"corpus : {SETTINGS.corpus_root}")
    print(f"index  : {SETTINGS.db_path}\n")

    started = time.perf_counter()
    with ArchiveStore(SETTINGS.db_path) as store:
        if args.reset:
            store.reset()
            print("derived data cleared (the corpus itself is untouched)\n")
        report = IngestionPipeline(SETTINGS, store).run(
            limit=args.limit, only=args.only, force=args.force
        )
        stats = store.stats()

    print(report.summary())
    print(f"\nelapsed               {time.perf_counter() - started:.1f}s")
    print("\nindex totals:")
    for key, value in stats.items():
        print(f"  {key:<20} {value}")

    if report.errors:
        print(f"\n{len(report.errors)} file(s) failed:")
        for error in report.errors[:10]:
            print(f"  - {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
