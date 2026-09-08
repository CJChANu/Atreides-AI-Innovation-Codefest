#!/usr/bin/env python3
"""Ablation harness: what does each retrieval and reasoning layer actually add?

Runs the development question set through progressively more capable
configurations. Each row removes exactly one capability from the row below it, so
the difference between two rows is attributable to that capability alone.

The metric that matters is **cited** — answers whose claims carry a real
document+page citation. "Answered" is reported alongside it precisely because it
is misleading on its own: a bare keyword lookup "answers" every question, because
it always returns a passage.

    python scripts/run_eval.py
    python scripts/run_eval.py --verbose
    python scripts/run_eval.py --questions path/to/questions.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai_gateway.gateway import AIGateway  # noqa: E402
from src.common.config import SETTINGS  # noqa: E402
from src.generation.answer import PARTIAL_STOPS, headline  # noqa: E402
from src.indexes.vector import VectorIndex, load_adapter  # noqa: E402
from src.orchestration.investigator import Investigator  # noqa: E402
from src.retrieval.hybrid import HybridRetriever  # noqa: E402
from src.retrieval.keyword import KeywordIndex  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402

UNANSWERED = ("not established", "no recorded value")


def answered(text: str) -> bool:
    return not any(marker in text.lower() for marker in UNANSWERED)


def run_mode(store, questions, *, use_vector: bool, use_llm: bool,
             max_iterations: int) -> dict:
    keyword = KeywordIndex(store)
    retriever = None
    if use_vector:
        vector = VectorIndex(SETTINGS.data_dir / "vectors.npz")
        if vector.load():
            retriever = HybridRetriever(store, keyword, vector,
                                        load_adapter(SETTINGS, vector), SETTINGS.fusion)
    gateway = AIGateway(SETTINGS) if use_llm else None
    budget = replace(SETTINGS.budget, max_iterations=max_iterations)
    investigator = Investigator(store, budget, gateway=gateway, retriever=retriever)

    started = time.perf_counter()
    states = [investigator.investigate(q["question"]) for q in questions]
    elapsed = (time.perf_counter() - started) / max(len(states), 1)

    by_track: dict[str, list[int]] = {}
    for question, state in zip(questions, states, strict=True):
        track = question["track"][:2]
        cited = 1 if any(c.evidence for c in state.claims) else 0
        by_track.setdefault(track, []).append(cited)

    return {
        "answered": sum(1 for s in states if answered(headline(s))),
        "cited": sum(1 for s in states if any(c.evidence for c in s.claims)),
        "conflicts": sum(1 for s in states if s.conflicts),
        "multi_hop": sum(1 for s in states if s.graph_expansions),
        "partial": sum(1 for s in states if s.stop_reason in PARTIAL_STOPS),
        "ms": elapsed * 1000,
        "by_track": {t: (sum(v), len(v)) for t, v in sorted(by_track.items())},
        "answers": [headline(s) for s in states],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path,
                        default=SETTINGS.corpus_root / "sample_questions.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not SETTINGS.db_path.exists():
        print("no index — run scripts/ingest_archive.py first", file=sys.stderr)
        return 2

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    gateway_probe = AIGateway(SETTINGS)

    # Each configuration differs from the previous one by a single capability.
    configurations = [
        ("keyword only, 1 lookup",      dict(use_vector=False, use_llm=False, max_iterations=1)),
        ("keyword + loop",              dict(use_vector=False, use_llm=False, max_iterations=6)),
        ("hybrid (kw+vector) + loop",   dict(use_vector=True,  use_llm=False, max_iterations=6)),
    ]
    if gateway_probe.configured:
        configurations.append(
            ("hybrid + loop + LLM assist", dict(use_vector=True, use_llm=True, max_iterations=6))
        )

    print(f"{len(questions)} development questions")
    print(f"LLM: {'configured — ' + SETTINGS.llm_model if gateway_probe.configured else 'not configured (deterministic modes only)'}")
    print(f"Embeddings: {'local LSA' if not SETTINGS.embedding_api_key else SETTINGS.embedding_model}\n")

    header = (f"{'configuration':<28}{'cited':>7}{'answered':>10}{'conflicts':>11}"
              f"{'multihop':>10}{'partial':>9}{'ms/q':>8}")
    print(header)
    print("-" * len(header))

    results = {}
    with ArchiveStore(SETTINGS.db_path) as store:
        for label, kwargs in configurations:
            outcome = run_mode(store, questions, **kwargs)
            results[label] = outcome
            print(f"{label:<28}{outcome['cited']:>7}{outcome['answered']:>10}"
                  f"{outcome['conflicts']:>11}{outcome['multi_hop']:>10}"
                  f"{outcome['partial']:>9}{outcome['ms']:>8.0f}")

    best = list(results)[-1]
    print(f"\nBy sub-track ({best}) — cited answers:")
    for track, (hit, total) in results[best]["by_track"].items():
        print(f"  {track}: {hit}/{total}")

    print("\n'cited' counts answers whose claims carry a document+page citation, and is")
    print("the metric that matters. 'answered' is shown beside it because it is")
    print("misleading alone: a keyword lookup always returns a passage.")

    if args.verbose:
        for index, question in enumerate(questions):
            print(f"\n{question['qid']}  {question['question']}")
            for label in results:
                print(f"   {label:<28} {results[label]['answers'][index][:62]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
