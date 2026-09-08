#!/usr/bin/env python3
"""Run a question set and explain *why* each miss happened.

`run_eval.py` measures how many questions are answered. This answers the more
useful question during development: when one is not, where did it break? It
classifies each failure by the stage that let it down, so effort goes to the
stage that is actually costing answers rather than to whichever one is easiest to
change.

    python scripts/diagnose.py                       # team question set
    python scripts/diagnose.py --sample              # the 20 supplied questions
    python scripts/diagnose.py --only-failures       # just the misses
    python scripts/diagnose.py --id h04              # one question, verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.generation.answer import headline, is_partial, render  # noqa: E402
from src.graph.fact_query import FactQuery  # noqa: E402
from src.orchestration.factory import build_system  # noqa: E402
from src.orchestration.state import ClaimType, Intent, StopReason  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402

TEAM_SET = Path(__file__).resolve().parents[1] / "tests/evaluation/archive_questions.json"

NO_ANSWER_MARKERS = ("not established", "no recorded value", "does not record")


def looks_unanswered(text: str) -> bool:
    return any(m in text.lower() for m in NO_ANSWER_MARKERS)


def diagnose(state, answer: str) -> str:
    """Name the stage that cost us the answer.

    The order matters: each check rules out an earlier stage, so the first one
    that fires is the earliest point the investigation went wrong.
    """
    question = state.question

    if state.stop_reason is StopReason.NO_ENTITY:
        return "UNDERSTANDING · no entity in the question matched the archive index"

    if not question.entities:
        return "UNDERSTANDING · question parsed without a subject"

    if question.attribute is None and question.intent is Intent.OPEN_QUESTION:
        return "UNDERSTANDING · no attribute phrase matched; fell through to text search"

    subject = question.primary[0] if question.primary else ""
    if question.attribute:
        # Did the fact store simply not have it?
        from src.graph.fact_query import FactQuery as _FQ  # local: needs the open store
        return _fact_stage(state, subject, question.attribute)

    return "RETRIEVAL · no structured value and no passage carried the answer"


def _fact_stage(state, subject, attribute) -> str:
    recorded = state.__dict__.get("_recorded_attributes", [])
    if attribute in recorded:
        return "VERIFICATION · the value was found but produced no citable claim"
    if recorded:
        return (f"INGESTION · '{attribute}' is not recorded for this subject "
                f"(has: {', '.join(recorded[:6])})")
    return "INGESTION · nothing structured recorded for this subject"


def run(questions, *, only_failures: bool, verbose_id: str | None, show_trace: bool) -> int:
    with ArchiveStore(SETTINGS.db_path) as store:
        investigator, gateway, modes = build_system(store, SETTINGS)
        facts = FactQuery(store)
        title_of = facts.title_of

        print(f"mode: {modes.label}\n")
        header = f"{'id':<6}{'kind':<14}{'':<3}{'answer':<44}{'why it failed'}"
        print(header)
        print("-" * 118)

        passed = failed = honest = 0
        misses: list[tuple[str, str, str, str]] = []

        for item in questions:
            qid = item.get("id") or item.get("qid", "?")
            if verbose_id and qid != verbose_id:
                continue
            text = item.get("q") or item["question"]
            kind = item.get("kind", item.get("track", "")[:12])

            state = investigator.investigate(text)
            answer = headline(state)
            # The loop records what it saw; reuse it rather than re-querying.
            state._recorded_attributes = facts.attributes_of(
                state.question.primary[0]) if state.question.primary else []

            unanswered = looks_unanswered(answer) or all(
                c.claim_type is ClaimType.UNSUPPORTED for c in state.claims)

            if item.get("expect_none"):
                ok = unanswered
                mark = "✓" if ok else "✗"
                reason = "" if ok else "ANSWERED A QUESTION THE ARCHIVE CANNOT SUPPORT"
                honest += ok
            elif unanswered:
                ok, mark = False, "✗"
                reason = diagnose(state, answer)
            else:
                expected = item.get("expect", "")
                ok = expected.lower() in answer.lower() if expected else True
                mark = "✓" if ok else "≈"
                reason = "" if ok else f"expected {expected!r}"

            passed += ok
            failed += not ok
            if not ok:
                misses.append((qid, kind, text, reason))

            if only_failures and ok:
                continue
            shown = " ".join(answer.split())[:42]
            print(f"{qid:<6}{kind:<14}{mark:<3}{shown:<44}{reason}")

            if verbose_id:
                print()
                print(render(state, title_of, show_trace=show_trace))

        total = passed + failed
        print("-" * 118)
        print(f"{passed}/{total} as expected · {failed} to look at")
        if honest:
            print(f"{honest} unanswerable question(s) correctly declined")

        if misses and not verbose_id:
            print("\nfailures grouped by stage:")
            groups: dict[str, list[str]] = {}
            for qid, _, text, reason in misses:
                stage = reason.split(" · ")[0] if " · " in reason else "OTHER"
                groups.setdefault(stage, []).append(f"{qid}  {text[:66]}")
            for stage, items in sorted(groups.items()):
                print(f"\n  {stage} ({len(items)})")
                for line in items:
                    print(f"    {line}")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", action="store_true",
                        help="use the corpus's own sample_questions.json")
    parser.add_argument("--questions", type=Path, help="a custom question file")
    parser.add_argument("--only-failures", action="store_true")
    parser.add_argument("--id", dest="verbose_id", help="run one question and print its full trace")
    parser.add_argument("--no-trace", action="store_true")
    args = parser.parse_args()

    if not SETTINGS.db_path.exists():
        print("no index — run scripts/ingest_archive.py first", file=sys.stderr)
        return 2

    if args.questions:
        payload = json.loads(args.questions.read_text(encoding="utf-8"))
        questions = payload["questions"] if isinstance(payload, dict) else payload
    elif args.sample:
        questions = json.loads(
            (SETTINGS.corpus_root / "sample_questions.json").read_text(encoding="utf-8"))
    else:
        questions = json.loads(TEAM_SET.read_text(encoding="utf-8"))["questions"]

    return run(questions, only_failures=args.only_failures,
               verbose_id=args.verbose_id, show_trace=not args.no_trace)


if __name__ == "__main__":
    raise SystemExit(main())
