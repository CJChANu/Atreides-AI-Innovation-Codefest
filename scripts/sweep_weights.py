#!/usr/bin/env python3
"""Sweep the retrieval fusion weights against the paraphrase probe.

The point of this script is that the weights in `src/common/config.py` are a
*measurement*, not a guess. Anyone can re-run it and see why they are what they
are — and see them change if the corpus or the probe changes.

    python scripts/sweep_weights.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import SETTINGS, FusionWeights  # noqa: E402
from src.indexes.vector import VectorIndex, load_adapter  # noqa: E402
from src.retrieval.hybrid import HybridRetriever  # noqa: E402
from src.retrieval.keyword import KeywordIndex  # noqa: E402
from src.storage.db import ArchiveStore  # noqa: E402

PROBE = Path(__file__).resolve().parents[1] / "tests/evaluation/paraphrase_probe.json"
DEPTHS = (1, 3, 5)
# Lexical/semantic splits to try. Entity overlap and source quality stay at 0.10:
# they are tie-breakers, and raising them starts ranking by source rather than by
# relevance, which is not what they are for.
SPLITS = [(0.35, 0.45), (0.40, 0.40), (0.45, 0.35), (0.50, 0.30),
          (0.55, 0.25), (0.60, 0.20), (0.70, 0.10)]


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

        def measure(retriever) -> dict[int, int]:
            counts = {d: 0 for d in DEPTHS}
            for probe in probes:
                hits = retriever.search(probe["q"], limit=max(DEPTHS))
                for depth in DEPTHS:
                    if any(probe["expect_doc_contains"] in h.relative_path.lower()
                           for h in hits[:depth]):
                        counts[depth] += 1
            return counts

        total = len(probes)
        print(f"{total} paraphrased probes\n")
        header = f"{'bm25 / vector':<18}" + "".join(f"{'R@'+str(d):>8}" for d in DEPTHS)
        print(header)
        print("-" * len(header))

        baseline = measure(HybridRetriever(store, keyword, None, None, SETTINGS.fusion))
        print(f"{'keyword only':<18}" + "".join(f"{baseline[d]}/{total}".rjust(8) for d in DEPTHS))

        for bm25, vector_weight in SPLITS:
            weights = FusionWeights(bm25=bm25, vector=vector_weight,
                                    entity_overlap=0.10, source_quality=0.10)
            counts = measure(HybridRetriever(store, keyword, vector, embedder, weights))
            marker = "  ← current" if (bm25, vector_weight) == (
                SETTINGS.fusion.bm25, SETTINGS.fusion.vector) else ""
            print(f"{f'{bm25:.2f} / {vector_weight:.2f}':<18}"
                  + "".join(f"{counts[d]}/{total}".rjust(8) for d in DEPTHS) + marker)

    print("\nPick the split that beats keyword-only at depth 5 without losing depth 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
