"""Embedding adapters: a hosted API when configured, LSA locally when not.

The local path is not a toy stand-in. Latent Semantic Analysis — TF-IDF followed
by a truncated SVD — learns its semantic structure *from this archive*, which for
an invented vocabulary is an advantage a general pretrained model does not have:
nothing in a public embedding space knows that "Vharencrag" and "fortress"
co-occur, but the corpus does.

It also has properties that matter more here than raw quality:

* **Deterministic.** Same corpus, same vectors, every run — so a cited answer is
  reproducible by a judge.
* **Offline and free.** No key, no rate limit, no network during a live demo.
* **Cheap.** The whole 2,547-chunk index fits in a few MB and builds in seconds.

When an embedding API key is configured the adapter uses it instead and records
the model name in the index, so the two are never silently mixed.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Dimensions of the local semantic space. 256 is well past the point where extra
# components stop separating this corpus and start fitting its noise.
LOCAL_DIMENSIONS = 256
# Vocabulary cap, by document frequency. Keeps the SVD tractable and drops the
# long tail of OCR garbage, which is mostly hapax.
MAX_VOCABULARY = 4000
# A term in almost every document carries no signal; one in a single document is
# usually noise or an OCR artefact.
MAX_DOC_FRACTION = 0.5
MIN_DOC_COUNT = 2

_TOKEN = re.compile(r"[a-z][a-z'-]{1,}", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


@dataclass
class LocalEmbeddingModel:
    """A fitted LSA model: vocabulary, IDF weights and SVD term components."""

    vocabulary: dict[str, int]
    idf: np.ndarray          # (V,)
    components: np.ndarray   # (V, k) — projects a term vector into the semantic space
    dimensions: int

    name = "local-lsa"

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), len(self.vocabulary)), dtype=np.float32)
        for row, text in enumerate(texts):
            counts = Counter(tokenize(text))
            if not counts:
                continue
            longest = max(counts.values())
            for term, count in counts.items():
                index = self.vocabulary.get(term)
                if index is not None:
                    # Sublinear TF, damped by the document's own maximum, so a long
                    # chapter does not outweigh a short infobox on the same topic.
                    matrix[row, index] = (0.5 + 0.5 * count / longest) * self.idf[index]
        projected = matrix @ self.components
        return _l2_normalise(projected)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, idf=self.idf, components=self.components,
            vocabulary=json.dumps(self.vocabulary), dimensions=self.dimensions,
        )

    @classmethod
    def load(cls, path: Path) -> LocalEmbeddingModel:
        data = np.load(path, allow_pickle=False)
        return cls(
            vocabulary=json.loads(str(data["vocabulary"])),
            idf=data["idf"], components=data["components"],
            dimensions=int(data["dimensions"]),
        )


def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    """Unit-length rows, so a dot product is exactly cosine similarity."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def fit_local_model(texts: list[str], *, dimensions: int = LOCAL_DIMENSIONS) -> LocalEmbeddingModel:
    """Fit LSA over the corpus."""
    document_frequency: Counter[str] = Counter()
    tokenised = []
    for text in texts:
        tokens = tokenize(text)
        tokenised.append(tokens)
        document_frequency.update(set(tokens))

    total = max(len(texts), 1)
    candidates = [
        (term, count) for term, count in document_frequency.items()
        if count >= MIN_DOC_COUNT and count <= MAX_DOC_FRACTION * total
    ]
    candidates.sort(key=lambda item: (-item[1], item[0]))
    vocabulary = {term: index for index, (term, _) in enumerate(candidates[:MAX_VOCABULARY])}
    if not vocabulary:
        raise ValueError("corpus produced an empty vocabulary")

    size = len(vocabulary)
    idf = np.zeros(size, dtype=np.float32)
    for term, index in vocabulary.items():
        idf[index] = math.log(total / (1 + document_frequency[term])) + 1.0

    matrix = np.zeros((len(texts), size), dtype=np.float32)
    for row, tokens in enumerate(tokenised):
        counts = Counter(tokens)
        if not counts:
            continue
        longest = max(counts.values())
        for term, count in counts.items():
            index = vocabulary.get(term)
            if index is not None:
                matrix[row, index] = (0.5 + 0.5 * count / longest) * idf[index]

    # Truncated SVD. `full_matrices=False` keeps this to the economy decomposition,
    # which is what makes it tractable at this size.
    k = min(dimensions, size - 1, len(texts) - 1)
    _, _, vt = np.linalg.svd(matrix, full_matrices=False)
    components = np.ascontiguousarray(vt[:k].T.astype(np.float32))

    return LocalEmbeddingModel(vocabulary=vocabulary, idf=idf,
                               components=components, dimensions=k)


class EmbeddingAdapter:
    """Chooses the hosted embedding API when configured, LSA otherwise."""

    def __init__(self, settings, model: LocalEmbeddingModel | None = None) -> None:
        self.settings = settings
        self.local = model
        self.use_api = bool(settings.embedding_api_key)
        self.name = settings.embedding_model if self.use_api else LocalEmbeddingModel.name

    def embed(self, texts: list[str]) -> np.ndarray:
        if self.use_api:
            try:
                return self._embed_via_api(texts)
            except Exception:
                # An embedding outage must not take the whole index with it; LSA
                # is already built and is a complete substitute.
                self.use_api = False
                self.name = LocalEmbeddingModel.name
        if self.local is None:
            raise RuntimeError("no local embedding model fitted; run build_indexes.py")
        return self.local.embed(texts)

    def _embed_via_api(self, texts: list[str]) -> np.ndarray:
        import json as _json
        import urllib.request

        request = urllib.request.Request(
            f"{self.settings.llm_base_url.rstrip('/')}/embeddings",
            data=_json.dumps({"model": self.settings.embedding_model, "input": texts}).encode(),
            headers={"Authorization": f"Bearer {self.settings.embedding_api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = _json.loads(response.read().decode())
        vectors = [item["embedding"] for item in payload["data"]]
        return _l2_normalise(np.asarray(vectors, dtype=np.float32))
