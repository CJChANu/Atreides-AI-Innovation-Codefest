"""What happens when the external provider misbehaves.

The v2 plan's fallback matrix is only worth anything if it is exercised, so each
failure mode here asserts the same contract: the system degrades and says so, and
never fabricates an answer.
"""

import pytest

from src.ai_gateway.breaker import CircuitBreaker, RetryPolicy, call_with_resilience
from src.ai_gateway.cache import ResponseCache
from src.ai_gateway.errors import CircuitOpen, InvalidRequest, RateLimited, TransientError
from src.ai_gateway.gateway import AIGateway
from src.common.config import SETTINGS


@pytest.fixture
def policy():
    return RetryPolicy(attempts=3, base_delay=0, max_delay=0, jitter=0)


def test_a_transient_failure_is_retried_then_succeeds(policy):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("boom")
        return "ok"

    assert call_with_resilience(flaky, policy=policy, breaker=CircuitBreaker(),
                                sleep=lambda _: None) == "ok"
    assert calls["n"] == 3


def test_rate_limiting_is_retryable(policy):
    calls = {"n": 0}

    def limited():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("429")
        return "ok"

    assert call_with_resilience(limited, policy=policy, breaker=CircuitBreaker(),
                                sleep=lambda _: None) == "ok"


def test_a_bad_request_is_not_retried(policy):
    """Retrying an invalid request just burns free-tier quota."""
    calls = {"n": 0}

    def rejected():
        calls["n"] += 1
        raise InvalidRequest("400")

    with pytest.raises(InvalidRequest):
        call_with_resilience(rejected, policy=policy, breaker=CircuitBreaker(),
                             sleep=lambda _: None)
    assert calls["n"] == 1


def test_repeated_failures_open_the_circuit(policy):
    """A dead provider must cost one timeout, not one per investigation step."""
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)

    def dead():
        raise TransientError("down")

    with pytest.raises(TransientError):
        call_with_resilience(dead, policy=policy, breaker=breaker, sleep=lambda _: None)
    assert breaker.is_open
    with pytest.raises(CircuitOpen):
        call_with_resilience(dead, policy=policy, breaker=breaker, sleep=lambda _: None)


def test_the_circuit_closes_again_after_its_cooldown():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0)
    breaker.record_failure()
    assert not breaker.is_open


def test_an_unconfigured_gateway_reports_a_fallback_and_returns_none():
    """No key is a normal operating mode, not an exception."""
    from dataclasses import replace
    gateway = AIGateway(replace(SETTINGS, llm_api_key=None))
    assert gateway.understand_question("who rules X?") is None
    assert gateway.status().fallback_events
    assert gateway.status().configured is False


def test_a_corrupt_cache_entry_never_breaks_a_request(tmp_path):
    cache = ResponseCache(tmp_path)
    key = cache.key(model="m", prompt_version="v1", payload={"a": 1})
    (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert cache.get(key) is None


def test_the_cache_key_changes_with_the_prompt_version():
    """Changing a prompt must not serve answers produced by the old one."""
    cache = ResponseCache.key
    assert cache(model="m", prompt_version="v1", payload={"a": 1}) != \
           cache(model="m", prompt_version="v2", payload={"a": 1})
