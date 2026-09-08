"""Content-addressed disk cache for AI responses.

The challenge appendix is explicit that free tiers are rate-limited and that
caching is expected engineering. Caching is also what makes a live demo safe: a
question asked during the recording that was asked during rehearsal costs nothing
and cannot 429.

The key includes the model and a prompt version, so changing either invalidates
the cache rather than silently serving a stale answer from a different prompt.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class ResponseCache:
    def __init__(self, directory: Path, *, enabled: bool = True) -> None:
        self.directory = directory
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if enabled:
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(*, model: str, prompt_version: str, payload: Any) -> str:
        seed = json.dumps(
            {"model": model, "prompt_version": prompt_version, "payload": payload},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self.directory / f"{key}.json"
        if not path.is_file():
            self.misses += 1
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt cache entry must never break a request.
            self.misses += 1
            return None
        self.hits += 1
        return record.get("value")

    def put(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        path = self.directory / f"{key}.json"
        try:
            path.write_text(
                json.dumps({"cached_at": time.time(), "value": value}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # a cache write failure is never worth failing a request for

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
