"""API-key vault + log redaction — the key-leak acceptance (doc §13 rule 7, Faz-7).

Proves: (1) keys round-trip through Fernet and the masked view never carries plaintext;
(2) the vault refuses to operate without a master key (no plaintext fallback);
(3) the log-redaction filter scrubs a registered secret from any log record — the
"anahtar izi yok" scan.
"""

from __future__ import annotations

import io
import logging

import pytest

from app.core import secrets as vault
from app.core.config import settings
from app.core.logging import (
    SecretRedactionFilter,
    clear_secrets,
    register_secret,
)

KEY = "AKIExampleKeyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef0123456789"
SECRET = "SEChiddenSecretABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef01234567"


@pytest.fixture
def with_master_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "secrets_key", "unit-test-master-passphrase")
    yield


def test_encrypt_decrypt_roundtrip(with_master_key) -> None:
    token = vault.encrypt(SECRET)
    assert token != SECRET  # ciphertext, not plaintext
    assert vault.decrypt(token) == SECRET


async def test_store_and_load_keys(db_session, with_master_key) -> None:
    masked = await vault.store_api_keys(db_session, KEY, SECRET, testnet=True)
    await db_session.commit()

    # Masked view: recognisable, but no plaintext anywhere in it.
    assert masked["configured"] is True
    assert masked["testnet"] is True
    assert KEY not in str(masked) and SECRET not in str(masked)
    assert masked["key_mask"].endswith(KEY[-4:])

    loaded = await vault.load_api_keys(db_session)
    assert loaded is not None
    assert loaded.api_key == KEY and loaded.api_secret == SECRET
    assert loaded.testnet is True


async def test_stored_row_has_no_plaintext(db_session, with_master_key) -> None:
    await vault.store_api_keys(db_session, KEY, SECRET, testnet=True)
    await db_session.commit()
    from app.core.settings_store import KEY_API_KEYS, get_setting

    row = await get_setting(db_session, KEY_API_KEYS)
    blob = str(row)
    assert KEY not in blob and SECRET not in blob  # only ciphertext is stored


async def test_vault_refuses_without_master_key(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "secrets_key", "")
    with pytest.raises(vault.VaultError):
        await vault.store_api_keys(db_session, KEY, SECRET, testnet=True)


def test_log_redaction_scrubs_registered_secret() -> None:
    clear_secrets()
    register_secret(KEY, SECRET)
    logger = logging.getLogger("test.redaction")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False

    logger.info("connecting with key=%s secret=%s", KEY, SECRET)
    logger.error("ccxt AuthenticationError for %s", KEY)

    out = stream.getvalue()
    assert KEY not in out
    assert SECRET not in out
    assert "redacted" in out
    clear_secrets()


def _redacting_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    """A logger wired to an in-memory stream through the redaction filter."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger, stream


def test_log_redaction_scrubs_exception_traceback() -> None:
    """A ccxt error carrying the key in its message must not escape via the traceback.

    ``logger.exception`` renders ``exc_info`` *after* filters run, so this is the
    leak vector the "hata mesajları taranır" acceptance is really about.
    """
    clear_secrets()
    register_secret(KEY, SECRET)
    logger, stream = _redacting_logger("test.redaction.traceback")

    try:
        raise ValueError(f"ccxt AuthenticationError: apiKey={KEY} secret={SECRET}")
    except ValueError:
        logger.exception("exchange call failed")

    out = stream.getvalue()
    assert KEY not in out
    assert SECRET not in out
    assert "Traceback" in out  # the traceback is still there — just scrubbed
    assert "redacted" in out
    clear_secrets()


def test_log_redaction_scrubs_exception_passed_as_message() -> None:
    """``logger.error(exc)`` stores the exception object; str() must not leak it."""
    clear_secrets()
    register_secret(KEY)
    logger, stream = _redacting_logger("test.redaction.objmsg")

    logger.error(ValueError(f"bad request with apiKey={KEY}"))
    logger.warning("wrapped: %s", ValueError(f"apiKey={KEY}"))

    out = stream.getvalue()
    assert KEY not in out
    assert out.count("redacted") >= 2
    clear_secrets()


def test_masked_view_of_unset() -> None:
    assert vault.masked_view(None) == {"configured": False, "key_mask": None, "testnet": None}
