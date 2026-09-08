"""Retry with exponential backoff, and a circuit breaker around the provider.

Two different jobs that are easy to conflate:

* **Retry** handles a single call hitting a transient failure.
* **The breaker** handles the provider being *down*. After a run of failures it
  stops calling for a cooldown, so a dead provider costs one timeout rather than
  one timeout per iteration of every investigation.

Without the breaker, a six-iteration investigation against a dead endpoint takes
six timeouts and the demo stalls. With it, the first failure trips the circuit and
every later call falls back instantly.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from src.ai_gateway.errors import CircuitOpen, GatewayError

T = TypeVar("T")


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0
    # Jitter stops several parallel calls retrying in lockstep after a 429.
    jitter: float = 0.25

    def delay_for(self, attempt: int) -> float:
        raw = min(self.base_delay * (2 ** attempt), self.max_delay)
        return raw + random.uniform(0, self.jitter * raw)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            # Cooldown elapsed: allow one probe through.
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()

    def state(self) -> str:
        return "open" if self.is_open else "closed"


def call_with_resilience(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    breaker: CircuitBreaker,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `operation`, retrying retryable failures and honouring the breaker."""
    if breaker.is_open:
        raise CircuitOpen("provider circuit is open; not calling")

    last: GatewayError | None = None
    for attempt in range(policy.attempts):
        try:
            result = operation()
        except GatewayError as error:
            last = error
            if not error.retryable:
                # A 400 or a schema violation will fail identically next time.
                breaker.record_failure()
                raise
            if attempt == policy.attempts - 1:
                break
            sleep(policy.delay_for(attempt))
        else:
            breaker.record_success()
            return result

    breaker.record_failure()
    assert last is not None
    raise last
