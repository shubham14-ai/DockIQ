"""Password hashing, API-key hashing, and JWT — stdlib + PyJWT only."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

_PBKDF2_ROUNDS = 200_000
_ALGO = "HS256"


# --- passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ROUNDS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds_s)
        ).hex()
        return hmac.compare_digest(expected, digest)
    except (ValueError, AttributeError):
        return False


# --- API keys ----------------------------------------------------------------

def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, key_hash). The full key is shown once."""
    raw = secrets.token_urlsafe(32)
    full = f"dkq_{raw}"
    prefix = full[:12]
    key_hash = hashlib.sha256(full.encode()).hexdigest()
    return full, prefix, key_hash


def hash_api_key(full: str) -> str:
    return hashlib.sha256(full.encode()).hexdigest()


# --- JWT ---------------------------------------------------------------------

def create_access_token(*, sub: str, tenant_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGO])
