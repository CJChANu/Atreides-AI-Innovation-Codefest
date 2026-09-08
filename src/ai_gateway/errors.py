"""Failure taxonomy for external AI calls.

The distinction that matters is *retryable vs not*. A 429 or a timeout should be
retried with backoff; a malformed schema or a 400 should not, because retrying an
invalid request just burns free-tier quota.
"""

from __future__ import annotations


class GatewayError(Exception):
    """Base for every AI-gateway failure. Carries whether a retry could help."""

    retryable = False

    def __init__(self, message: str, *, provider: str = "", status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status = status


class NotConfigured(GatewayError):
    """No API key. Expected, not exceptional — the deterministic path handles it."""


class RateLimited(GatewayError):
    retryable = True


class TransientError(GatewayError):
    """Timeout, 5xx, connection reset."""

    retryable = True


class InvalidRequest(GatewayError):
    """4xx other than 429. Retrying will not help."""


class SchemaViolation(GatewayError):
    """The model returned JSON that does not match the contract we require."""


class CircuitOpen(GatewayError):
    """Too many recent failures; we are not calling the provider right now."""
