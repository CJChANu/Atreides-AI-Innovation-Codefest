#!/usr/bin/env python3
"""Measure general capability against held-out questions.

The development set tells us whether the system still does what it did
yesterday. It cannot tell us whether it will handle a question nobody wrote a
rule for — and since the judge's questions are unseen by definition, that is the
number that actually matters.

So this runs a set written *after* the rules, grouped by the reasoning operation
each question needs, and reports per-category scores. A category at 0/3 says a
whole capability is missing; the aggregate alone would hide that.

    python scripts/run_unseen_eval.py
    python scripts/run_unseen_eval.py --verbose
    python scripts/run_unseen_eval.py --no-llm      # deterministic path only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.generation.answer import headline  # noqa: E402
from src.orchestration.factory import build_system  # noqa: E402
from src.orchestration.status import evaluate  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402

DEFAULT_SET = Path(__file__).resolve().parents[1] / "tests/evaluation/unseen_questions.json"

# Statuses that count as an honest "the archive cannot support this".
REFUSAL_STATUSES = {"insufficient_evidence", "no_entity", "partial_visual"}


def judge(question: dict, answer: str, status: str) -> tuple[bool, str]:
    """Did this question pass, and why."""
    lowered = answer.lower()

    if question.get("expect_none"):
        refused = (status in REFUSAL_STATUSES
                   or "not established" in lowered
                   or "no recorded value" in lowered
                   or "does not record" in lowered)
        return refused, "honest refusal" if refused else f"answered anyway: {answer[:60]}"

    if "expect_status" in question:
        ok = status in set(question["expect_status"])
        return ok, f"status {status}" + ("" if ok else " (unexpected)")

    expected = str(question["expect"]).lower()
    # Numbers are written both ways in the archive ("64617" and "64,617"), so a
    # comma difference must not read as a wrong answer.
    if expected.replace(",", "") in lowered.replace(",", ""):
        return True, "expected value present"
    return False, f"expected {question['expect']!r}, got: {answer[:70]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=DEFAULT_SET)
    parser.add_argument("--verbose", action="store_true", help="show every result")
    parser.add_argument("--no-llm", action="store_true",
                        help="run the deterministic path only")
    args = parser.parse_args()

    if not SETTINGS.db_path.exists():
        print("no index found — run scripts/ingest_archive.py first", file=sys.stderr)
        return 2

    questions = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
    per_category: dict[str, list[bool]] = defaultdict(list)
    failures: list[tuple[str, str, str]] = []

    with ArchiveStore(SETTINGS.db_path) as store:
        investigator, gateway, _ = build_system(store, SETTINGS)
        if args.no_llm:
            investigator.gateway = None

        print(f"{len(questions)} held-out questions "
              f"({'deterministic only' if args.no_llm else 'full system'})\n")

        for question in questions:
            state = investigator.investigate(question["q"])
            report = evaluate(state, gateway.fallback_events if gateway else [])
            answer = headline(state)
            passed, why = judge(question, answer, report.status.value)
            per_category[question["category"]].append(passed)
            if not passed:
                failures.append((question["id"], question["q"], why))
            if args.verbose:
                mark = "PASS" if passed else "FAIL"
                print(f"  {mark}  [{question['category']}] {question['q'][:58]}")
                print(f"        {why}")

    total = sum(len(v) for v in per_category.values())
    correct = sum(sum(v) for v in per_category.values())

    print(f"\n{'category':<26} {'score':>7}")
    print("-" * 36)
    for category in sorted(per_category):
        results = per_category[category]
        print(f"{category:<26} {sum(results):>3}/{len(results):<3}")
    print("-" * 36)
    print(f"{'TOTAL':<26} {correct:>3}/{total:<3}  ({correct / max(total, 1):.0%})")

    if failures:
        print("\nfailures:")
        for identifier, text, why in failures:
            print(f"  {identifier}: {text}")
            print(f"      {why}")

    print("\nA category scoring 0 means a whole capability is missing; the "
          "aggregate alone would hide that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
