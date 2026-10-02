from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10
SESSION_TOKEN_BYTES = 32
SESSION_TTL_DAYS = 14
SESSION_RENEW_THRESHOLD_DAYS = 7

SESSION_COOKIE = "crm_session"
CSRF_COOKIE = "crm_csrf"
CSRF_HEADER = "X-CSRF-Token"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# Precomputed once at import: verifying against it burns the same argon2
# cost as a real check, so unknown/inactive accounts take as long as real
# ones (no user-enumeration via timing). The password is random and
# discarded — verification always fails.
DUMMY_PASSWORD_HASH: str = _password_hasher.hash(secrets.token_urlsafe(32))


def needs_rehash(password_hash: str) -> bool:
    return _password_hasher.check_needs_rehash(password_hash)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def new_session_token() -> bytes:
    return secrets.token_bytes(SESSION_TOKEN_BYTES)


def token_cookie_value(raw: bytes) -> str:
    return raw.hex()


def token_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def hash_token_value(value: str) -> str:
    return hashlib.sha256(bytes.fromhex(value)).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
