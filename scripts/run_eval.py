#!/usr/bin/env python3
"""Ablation harness over the development question set.

Answers each question four ways and reports what each stage adds. This is the
evidence for the central claim of sub-track 1C — that iterating beats a single
lookup — and it is deliberately run on general behaviour rather than tuned to
individual questions, because final judging uses an unpublished set.

    python scripts/run_eval.py
    python scripts/run_eval.py --questions path/to/questions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.generation.answer import headline  # noqa: E402
from src.orchestration.investigator import Investigator  # noqa: E402
from src.orchestration.state import ClaimType, StopReason  # noqa: E402
from src.retrieval.keyword import KeywordIndex  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402

UNANSWERED = ("not established", "no recorded value")


def answered(text: str) -> bool:
    return not any(marker in text.lower() for marker in UNANSWERED)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path,
                        default=SETTINGS.corpus_root / "sample_questions.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))

    with ArchiveStore(SETTINGS.db_path) as store:
        keyword = KeywordIndex(store)
        # Each configuration removes one capability, so the difference between
        # rows is attributable to that capability alone.
        configurations = {
            "keyword only (1 lookup)": None,
            "loop, 1 iteration": replace(SETTINGS.budget, max_iterations=1),
            "loop, 2 iterations": replace(SETTINGS.budget, max_iterations=2),
            "full loop": SETTINGS.budget,
        }

        print(f"{len(questions)} development questions\n")
        header = f"{'configuration':<26}{'answered':>10}{'cited':>8}{'partial':>9}"
        print(header)
        print("-" * len(header))

        rows = {}
        for label, budget in configurations.items():
            if budget is None:
                hits = [keyword.search(q["question"], limit=1) for q in questions]
                count = sum(1 for h in hits if h)
                print(f"{label:<26}{count:>10}{count:>8}{'—':>9}")
                rows[label] = [(" ".join(h[0].content.split())[:60] if h else "—") for h in hits]
                continue

            investigator = Investigator(store, budget)
            states = [investigator.investigate(q["question"]) for q in questions]
            count = sum(1 for s in states if answered(headline(s)))
            cited = sum(1 for s in states
                        if any(c.evidence for c in s.claims))
            partial = sum(1 for s in states if s.stop_reason in {
                StopReason.ITERATION_BUDGET, StopReason.INSUFFICIENT_EVIDENCE,
                StopReason.NO_NEW_EVIDENCE, StopReason.NO_ENTITY})
            print(f"{label:<26}{count:>10}{cited:>8}{partial:>9}")
            rows[label] = [headline(s)[:60] for s in states]

        print("\n'answered' counts a concrete value; 'cited' counts answers whose "
              "claims carry\nat least one document+page citation. A keyword lookup "
              "always returns\nsomething, which is exactly why 'answered' alone is a "
              "misleading metric.\n")

        if args.verbose:
            for index, question in enumerate(questions):
                print(f"\n{question['qid']}  {question['question']}")
                for label in configurations:
                    print(f"   {label:<26} {rows[label][index]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
