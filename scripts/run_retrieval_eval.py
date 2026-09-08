#!/usr/bin/env python3
"""Measure what semantic retrieval adds, on questions phrased to need it.

The 20 supplied development questions reuse the archive's own vocabulary almost
verbatim, so BM25 alone answers them and the vector index looks redundant. That
is a property of the question set, not evidence that embeddings do not help — and
reporting "hybrid changed nothing" without testing paraphrases would be the kind
of unvalidated claim this competition explicitly penalises.

This probe asks the same facts in words the archive does not use, and measures
recall@k of the document that actually holds the answer.

    python scripts/run_retrieval_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS  # noqa: E402
from src.indexes.vector import VectorIndex, load_adapter  # noqa: E402
from src.retrieval.hybrid import HybridRetriever  # noqa: E402
from src.retrieval.keyword import KeywordIndex  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402

PROBE = Path(__file__).resolve().parents[1] / "tests/evaluation/paraphrase_probe.json"
DEPTHS = (1, 3, 5)


def recall_at(hits, expected: str, depth: int) -> bool:
    return any(expected in h.relative_path.lower() for h in hits[:depth])


def main() -> int:
    if not SETTINGS.db_path.exists():
        print("no index — run scripts/ingest_archive.py first", file=sys.stderr)
        return 2

    probes = json.loads(PROBE.read_text(encoding="utf-8"))["probes"]

    with ArchiveStore(SETTINGS.db_path) as store:
        keyword = KeywordIndex(store)
        vector = VectorIndex(SETTINGS.data_dir / "vectors.npz")
        if not vector.load():
            print("no vector index — run scripts/build_indexes.py", file=sys.stderr)
            return 2
        embedder = load_adapter(SETTINGS, vector)

        lexical_only = HybridRetriever(store, keyword, None, None, SETTINGS.fusion)
        hybrid = HybridRetriever(store, keyword, vector, embedder, SETTINGS.fusion)

        print(f"{len(probes)} paraphrased questions "
              f"(worded to avoid the archive's own vocabulary)\n")
        header = f"{'configuration':<24}" + "".join(f"{'R@'+str(d):>8}" for d in DEPTHS)
        print(header)
        print("-" * len(header))

        rows = {}
        for label, retriever in (("keyword only", lexical_only), ("hybrid + vector", hybrid)):
            counts = {d: 0 for d in DEPTHS}
            misses = []
            for probe in probes:
                hits = retriever.search(probe["q"], limit=max(DEPTHS))
                for depth in DEPTHS:
                    if recall_at(hits, probe["expect_doc_contains"], depth):
                        counts[depth] += 1
                if not recall_at(hits, probe["expect_doc_contains"], max(DEPTHS)):
                    misses.append(probe["q"])
            rows[label] = (counts, misses)
            cells = "".join(f"{counts[d]}/{len(probes)}".rjust(8) for d in DEPTHS)
            print(f"{label:<24}{cells}")

        print("\nRecall@k = the document holding the answer appears in the top k hits.")
        for label, (_, misses) in rows.items():
            if misses:
                print(f"\n{label} still misses:")
                for miss in misses:
                    print(f"  - {miss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
