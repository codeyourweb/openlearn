# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Unit tests for scoring, sanitisation and cryptographic helpers."""

from __future__ import annotations

import pytest

from app.sanitize import html_to_text, sanitize_html, sanitize_plain
from app.scoring import is_answer_correct, points_for
from app.security import (
    PasswordPolicyError,
    RateLimiter,
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password,
    verify_password,
)


# --- scoring ---------------------------------------------------------------
def test_exact_match_is_correct():
    assert is_answer_correct([1, 2], [1, 2]) is True
    assert is_answer_correct([2, 1], [1, 2]) is True


def test_partial_or_extra_selection_is_wrong():
    assert is_answer_correct([1], [1, 2]) is False
    assert is_answer_correct([1, 2, 3], [1, 2]) is False
    assert is_answer_correct([], [1]) is False
    assert is_answer_correct([1], []) is False


def test_points_policies():
    assert points_for(True, 100, "zero") == 100
    assert points_for(False, 100, "zero") == 0
    assert points_for(False, 100, "penalty") == -100
    assert points_for(True, 50, "penalty") == 50


# --- sanitisation ----------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)></svg>",
        "<iframe src='https://evil.example'></iframe>",
        "<a href='javascript:alert(1)'>click</a>",
        "<p style='background:url(javascript:alert(1))'>x</p>",
        "<div onmouseover='alert(1)'>hover</div>",
        "<!-- comment --><p>ok</p>",
    ],
)
def test_dangerous_markup_is_removed(payload):
    cleaned = sanitize_html(payload)
    lowered = cleaned.lower()
    for forbidden in ("<script", "onerror", "onload", "onmouseover", "javascript:", "<iframe", "style=", "<!--"):
        assert forbidden not in lowered


def test_allowed_formatting_is_kept():
    cleaned = sanitize_html("<p><strong>bold</strong> <em>it</em></p><ul><li>one</li></ul>")
    assert "<strong>bold</strong>" in cleaned
    assert "<em>it</em>" in cleaned
    assert "<li>one</li>" in cleaned


def test_html_to_text_projection():
    assert html_to_text("<p>Hello <strong>world</strong></p>") == "Hello world"
    assert html_to_text("") == ""


def test_sanitize_plain_collapses_and_strips_nul():
    assert sanitize_plain("  a\x00  b  ") == "a b"
    with pytest.raises(ValueError):
        sanitize_plain("x" * 600, max_length=500)


# --- passwords -------------------------------------------------------------
def test_password_hashing_roundtrip():
    hashed = hash_password("S3curePassword!")
    assert hashed != "S3curePassword!"
    assert hashed.startswith("$argon2")
    assert verify_password("S3curePassword!", hashed) is True
    assert verify_password("WrongPassword1!", hashed) is False


@pytest.mark.parametrize("password", ["short1", "alllettersonly", "12345678901", "password"])
def test_weak_passwords_are_rejected(password):
    with pytest.raises(PasswordPolicyError):
        validate_password(password)


def test_strong_password_is_accepted():
    validate_password("Str0ngEnoughPassword")


# --- tokens ----------------------------------------------------------------
def test_jwt_roundtrip_and_rejection():
    token = create_access_token(42)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert decode_access_token(token + "tampered") is None
    assert decode_access_token("not-a-token") is None


def test_expired_token_is_rejected():
    token = create_access_token(42, ttl_minutes=-1)
    assert decode_access_token(token) is None


# --- rate limiter ----------------------------------------------------------
def test_rate_limiter_blocks_after_limit():
    limiter = RateLimiter()
    for _ in range(3):
        allowed, _ = limiter.check("ip", 3, 60)
        assert allowed is True
    allowed, retry_after = limiter.check("ip", 3, 60)
    assert allowed is False
    assert retry_after > 0
    limiter.reset()
    assert limiter.check("ip", 3, 60)[0] is True
