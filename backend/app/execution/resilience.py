"""Exchange-call resilience: retry with backoff + a circuit breaker (doc §9.2).

Live venues fail in two shapes: *transient* (network blips, rate limits — retry and
they clear) and *sustained* (the venue is down or rejecting — retrying just makes it
worse and stalls the bot). This module wraps a single exchange call with:

* **Retry with exponential backoff** for the transient class only.
* **A circuit breaker** that counts consecutive failures; after ``threshold`` it
  *opens* and every call fails fast for ``cooldown`` seconds instead of hammering
  the exchange. A single success closes it again.

The bot treats an open breaker as "cannot reach the exchange" and simply does not
place orders that tick — safer than blocking or leaving partial state. The execution
adapter is synchronous (it implements the same sync ``ExecutionAdapter`` surface as
the paper sim, so the risk wall is unchanged), so this helper is synchronous too.
Kept dependency-free and deterministic (injectable clock + sleep) for unit tests.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ccxt error classes are matched by name so importing ccxt is not required to test.
_TRANSIENT_NAMES = frozenset(
    {
        "NetworkError", "RequestTimeout", "RateLimitExceeded",
        "DDoSProtection", "ExchangeNotAvailable",
    }
)


class CircuitOpenError(RuntimeError):
    """Raised when the breaker is open — the exchange is presumed unreachable."""


def is_transient(exc: BaseException) -> bool:
    """Whether an error is worth retrying (network/rate-limit, not a bad request)."""
    names = {c.__name__ for c in type(exc).__mro__}
    return bool(names & _TRANSIENT_NAMES)


@dataclass
class CircuitBreaker:
    """Consecutive-failure breaker with a timed cooldown (doc §9.2)."""

    threshold: int = 5
    cooldown_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic

    failures: int = 0
    opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """Open until the cooldown elapses, then half-open (one trial allowed)."""
        if self.opened_at is None:
            return False
        if self.clock() - self.opened_at >= self.cooldown_seconds:
            return False  # half-open: allow a trial call
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = self.clock()
            logger.warning(
                "circuit breaker OPEN after %d consecutive failures (cooldown %.0fs)",
                self.failures, self.cooldown_seconds,
            )


def call_resilient[T](
    fn: Callable[[], T],
    *,
    breaker: CircuitBreaker,
    max_retries: int = 3,
    backoff_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    label: str = "exchange call",
) -> T:
    """Run ``fn`` with retry + breaker. Raises :class:`CircuitOpenError` when open."""
    if breaker.is_open:
        raise CircuitOpenError(f"{label}: circuit open")

    attempt = 0
    while True:
        try:
            result = fn()
            breaker.record_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:  # noqa: BLE001 - classify then re-raise
            transient = is_transient(exc)
            if not transient or attempt >= max_retries:
                breaker.record_failure()
                logger.warning(
                    "%s failed (%s, attempt %d/%d): %s",
                    label, type(exc).__name__, attempt + 1, max_retries + 1, exc,
                )
                raise
            delay = backoff_seconds * (2**attempt)
            logger.info(
                "%s transient error (%s); retry %d in %.2fs",
                label, type(exc).__name__, attempt + 1, delay,
            )
            sleep(delay)
            attempt += 1
