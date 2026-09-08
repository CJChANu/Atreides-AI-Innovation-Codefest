#!/usr/bin/env python3
"""Query the keyword index directly.

A deliberately thin tool: it lets us see exactly what the retrieval layer returns
before any LLM is involved, which is how retrieval bugs get found.

    python scripts/search.py "Weeping Lurker threat rating"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.retrieval.keyword import KeywordIndex  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="+")
    parser.add_argument("-k", "--limit", type=int, default=8)
    parser.add_argument("--and", dest="mode_and", action="store_true",
                        help="require every term (precision over recall)")
    args = parser.parse_args()

    with ArchiveStore(SETTINGS.db_path) as store:
        hits = KeywordIndex(store).search(
            " ".join(args.query), limit=args.limit, mode="and" if args.mode_and else "or"
        )

    if not hits:
        print("no matches")
        return 1
    for rank, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.content.split())[:220]
        print(f"\n{rank:>2}. {hit.citation()}  score={hit.score:.3f}")
        print(f"    {hit.chunk_id}")
        print(f"    {snippet}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
