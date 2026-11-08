# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Cryptography, credentials and rate limiting helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import settings

# OWASP recommended Argon2id parameters (RFC 9106 low-memory profile tuned up).
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "1234567890",
    "qwerty12345",
    "motdepasse",
    "azerty12345",
    "letmein123",
    "admin12345",
    "changeme123",
    "iloveyou123",
}


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters long.")
    if password.lower() in COMMON_PASSWORDS:
        raise PasswordPolicyError("This password is too common.")
    # Lower friction than a length-and-classes matrix, still above the guessable
    # floor: upper, lower, and either a digit or a special character.
    if not any(c.isupper() for c in password):
        raise PasswordPolicyError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise PasswordPolicyError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() or not c.isalnum() for c in password):
        raise PasswordPolicyError("Password must contain at least one digit or special character.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def create_access_token(
    user_id: int,
    *,
    ttl_minutes: int | None = None,
    token_type: str = "session",
    token_version: int = 0,
) -> str:
    now = datetime.now(timezone.utc)
    ttl = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": token_type,
        # Bumped on password reset: a token minted before the change no longer
        # matches the account and is refused, without a session table.
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") not in {"session", "api"}:
        return None
    return payload


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(plain_key, prefix, sha256_hash)``."""
    plain = "ol_" + secrets.token_urlsafe(32)
    return plain, plain[:10], sha256(plain)


class RateLimiter:
    """Fixed-window limiter kept in process memory.

    A single-worker deployment is the documented model (see README); for
    multi-worker setups put a shared limiter (Redis) behind the same interface.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        window_start = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            if len(self._hits) > 10_000:  # keep memory bounded
                self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v})
            return True, 0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


rate_limiter = RateLimiter()
