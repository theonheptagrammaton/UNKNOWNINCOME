"""Application logging setup + secret redaction (doc §5.5, §13 rule 7).

Uvicorn only configures its own loggers, so ``app.*`` INFO logs (indicator cache
HIT/MISS, registry sync, data sync) never reach stdout by default. This attaches
a stream handler to the ``app`` logger at ``settings.log_level`` — making the
cache-hit logging (doc §5.5 acceptance) observable in production, not just tests.

Phase 7 adds a **redaction filter** attached to every handler: API keys and
secrets registered via :func:`register_secret` (the vault does this the moment it
decrypts credentials to build a live adapter) are scrubbed from every log record
before it is emitted. This is the second line behind "never return plaintext" —
even a stray ``logger.exception`` that captured a ccxt error carrying a key comes
out redacted. The key-leak acceptance test drives this path directly.
"""

from __future__ import annotations

import logging

from app.core.config import settings

_CONFIGURED = False
_REDACTION = "····redacted····"
# Registered secret substrings to scrub. Short values are ignored (a 3-char
# "secret" would redact half the log); real exchange keys are 32+ chars.
_SECRETS: set[str] = set()
_MIN_SECRET_LEN = 8


def register_secret(*values: str) -> None:
    """Register secret substrings the redaction filter must scrub from all logs."""
    for v in values:
        if v and len(v) >= _MIN_SECRET_LEN:
            _SECRETS.add(v)


def clear_secrets() -> None:
    """Drop all registered secrets (tests)."""
    _SECRETS.clear()


def _scrub(text: str) -> str:
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, _REDACTION)
    return text


class SecretRedactionFilter(logging.Filter):
    """Scrubs registered secrets from the message and its args (doc §13 rule 7)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _SECRETS:
            return True
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub_arg(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub_arg(a) for a in record.args)
        return True

    @staticmethod
    def _scrub_arg(arg: object) -> object:
        return _scrub(arg) if isinstance(arg, str) else arg


def install_redaction(logger: logging.Logger) -> None:
    """Attach the redaction filter to a logger's handlers (idempotent)."""
    for handler in logger.handlers:
        if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            handler.addFilter(SecretRedactionFilter())


def configure_logging() -> None:
    """Route ``app.*`` logs to stdout at the configured level (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        handler.addFilter(SecretRedactionFilter())
        app_logger.addHandler(handler)
    else:
        install_redaction(app_logger)
    # Also guard the root handlers (uvicorn/ccxt log through the root) so a secret
    # cannot escape via a logger we do not own.
    install_redaction(logging.getLogger())
    # Leave propagate=True: the root logger has no INFO handler under uvicorn, so
    # there is no double-emission, and pytest's caplog still captures via the root.
    _CONFIGURED = True
