"""Retry + circuit breaker resilience (doc §9.2 borsa hata/ratelimit dayanıklılığı)."""

from __future__ import annotations

import pytest

from app.execution.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    call_resilient,
    is_transient,
)


class NetworkError(Exception):
    """Stand-in for ccxt.NetworkError (matched by class name)."""


class BadRequest(Exception):
    """A non-transient error — must not be retried."""


def _no_sleep(_seconds: float) -> None:
    return None


def test_transient_classification() -> None:
    assert is_transient(NetworkError("blip"))
    assert not is_transient(BadRequest("nope"))


def test_retries_transient_then_succeeds() -> None:
    breaker = CircuitBreaker()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise NetworkError("temporary")
        return "ok"

    out = call_resilient(flaky, breaker=breaker, max_retries=3, sleep=_no_sleep)
    assert out == "ok"
    assert calls["n"] == 3
    assert breaker.failures == 0  # success resets the streak


def test_non_transient_not_retried() -> None:
    breaker = CircuitBreaker()
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise BadRequest("reduceOnly rejected")

    with pytest.raises(BadRequest):
        call_resilient(bad, breaker=breaker, max_retries=5, sleep=_no_sleep)
    assert calls["n"] == 1  # tried exactly once
    assert breaker.failures == 1


def test_breaker_opens_after_threshold_and_fails_fast() -> None:
    clock = {"t": 0.0}
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=60, clock=lambda: clock["t"])

    def always_fail():
        raise NetworkError("down")

    for _ in range(3):
        with pytest.raises(NetworkError):
            call_resilient(always_fail, breaker=breaker, max_retries=0, sleep=_no_sleep)
    assert breaker.is_open

    # Now open: the next call fails fast without ever invoking fn.
    invoked = {"n": 0}

    def spy():
        invoked["n"] += 1
        return "unreached"

    with pytest.raises(CircuitOpenError):
        call_resilient(spy, breaker=breaker, sleep=_no_sleep)
    assert invoked["n"] == 0

    # After the cooldown the breaker half-opens and a success closes it.
    clock["t"] = 61.0
    assert not breaker.is_open
    out = call_resilient(spy, breaker=breaker, sleep=_no_sleep)
    assert out == "unreached" and breaker.failures == 0
