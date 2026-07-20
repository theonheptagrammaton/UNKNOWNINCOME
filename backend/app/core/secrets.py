"""Fernet-encrypted API-key vault (doc §13, rule 7: keys never leak).

Exchange API keys are the one secret the app must persist. They are stored **only**
encrypted (Fernet, AES-128-CBC + HMAC) under a master key that lives in the
environment (``SECRETS_KEY``), never in the database. The DB row keeps only the
ciphertext plus non-sensitive metadata (a ``····last4`` mask and the testnet flag)
so the UI and API can show *that* a key is set without ever seeing it.

Two invariants make the leak test (Phase 7 acceptance) pass:

1. Plaintext key/secret never crosses the API boundary — :func:`masked_view` is the
   only thing an endpoint may return.
2. Decryption happens server-side, on demand, right before an adapter is built —
   the plaintext is never logged (the log-redaction filter in ``core.logging`` is
   the belt-and-braces second line).

Without a configured ``secrets_key`` the vault refuses to store or read — there is
no plaintext fallback, by design.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.settings_store import KEY_API_KEYS, get_setting, set_setting


class VaultError(RuntimeError):
    """Raised when the vault cannot operate (no master key, bad token)."""


@dataclass(frozen=True)
class ApiKeys:
    """Decrypted exchange credentials — held only transiently, never persisted raw."""

    api_key: str
    api_secret: str
    testnet: bool


def _fernet() -> Fernet:
    """Build the Fernet cipher from the configured master key (or raise)."""
    raw = settings.secrets_key.strip()
    if not raw:
        raise VaultError(
            "SECRETS_KEY is not configured — the API-key vault is disabled "
            "(no plaintext fallback, by design)."
        )
    # Accept either a real 32-byte urlsafe-base64 Fernet key or any passphrase
    # (which we widen to a valid key by hashing — convenient for a personal tool).
    try:
        Fernet(raw.encode())
        key = raw.encode()
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt one secret to a URL-safe token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt` (raises on tamper/wrong key)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise VaultError("could not decrypt API keys (wrong SECRETS_KEY?)") from exc


def _mask(secret: str) -> str:
    """``····`` + last 4 chars — enough to recognise, useless to an attacker."""
    tail = secret[-4:] if len(secret) >= 4 else ""
    return f"····{tail}" if tail else "····"


def masked_view(record: dict | None) -> dict:
    """The only key info an endpoint may return: set?/mask/testnet — never plaintext."""
    if not record:
        return {"configured": False, "key_mask": None, "testnet": None}
    return {
        "configured": True,
        "key_mask": record.get("key_mask"),
        "testnet": bool(record.get("testnet", True)),
    }


async def store_api_keys(
    session: AsyncSession, api_key: str, api_secret: str, *, testnet: bool
) -> dict:
    """Encrypt + persist exchange credentials; return the masked view. Caller commits."""
    if not api_key or not api_secret:
        raise VaultError("both api_key and api_secret are required")
    record = {
        "api_key_enc": encrypt(api_key),
        "api_secret_enc": encrypt(api_secret),
        "key_mask": _mask(api_key),
        "testnet": bool(testnet),
    }
    await set_setting(session, KEY_API_KEYS, record)
    return masked_view(record)


async def load_api_keys(session: AsyncSession) -> ApiKeys | None:
    """Decrypt stored credentials for building a live adapter (``None`` if unset)."""
    record = await get_setting(session, KEY_API_KEYS)
    if not record or "api_key_enc" not in record:
        return None
    return ApiKeys(
        api_key=decrypt(record["api_key_enc"]),
        api_secret=decrypt(record["api_secret_enc"]),
        testnet=bool(record.get("testnet", True)),
    )


async def get_masked(session: AsyncSession) -> dict:
    """Masked view for the Settings UI (never plaintext)."""
    return masked_view(await get_setting(session, KEY_API_KEYS))
