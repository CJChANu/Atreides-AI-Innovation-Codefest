#!/usr/bin/env python3
"""Ask the archive a question and watch the investigation.

    python scripts/ask.py "In which year was the Gauntlet of Sorrowfell actually forged?"
    python scripts/ask.py --json "Whose dominion encompasses the lair of the Gravemaw Wyrm?"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.generation.answer import render  # noqa: E402
from src.graph.fact_query import FactQuery  # noqa: E402
from src.orchestration.factory import build_system  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="+")
    parser.add_argument("--json", action="store_true", help="emit the machine-readable trace")
    parser.add_argument("--no-trace", action="store_true", help="hide the investigation trace")
    parser.add_argument("--max-iterations", type=int, help="override the iteration budget")
    args = parser.parse_args()

    if not SETTINGS.db_path.exists():
        print("no index found — run scripts/ingest_archive.py first", file=sys.stderr)
        return 2

    budget = SETTINGS.budget
    if args.max_iterations:
        from dataclasses import replace
        budget = replace(budget, max_iterations=args.max_iterations)

    with ArchiveStore(SETTINGS.db_path) as store:
        investigator, gateway, modes = build_system(store, SETTINGS, budget=budget)
        if not args.json:
            print(f"mode: {modes.label}\n")
        state = investigator.investigate(" ".join(args.question))
        title_of = FactQuery(store).title_of
        if not args.json and gateway.fallback_events:
            print(f"\nFALLBACKS\n  " + "\n  ".join(dict.fromkeys(gateway.fallback_events)))
        if args.json:
            print(json.dumps(state.to_dict(title_of), indent=2, ensure_ascii=False))
        else:
            print(render(state, title_of, show_trace=not args.no_trace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
