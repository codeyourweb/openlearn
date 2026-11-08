# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Authentication and account lifecycle."""

from __future__ import annotations

from tests.conftest import DEFAULT_PASSWORD, csrf_headers, login_user, register_user


def test_register_creates_session_and_returns_no_secret(client):
    user = register_user(client)
    assert user["email"] == "player@example.com"
    assert "password" not in user and "password_hash" not in user
    assert client.cookies.get("ol_session")
    assert client.cookies.get("ol_csrf")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == user["id"]


def test_register_rejects_duplicate_email(client):
    register_user(client, email="dup@example.com")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "DUP@example.com", "password": DEFAULT_PASSWORD, "display_name": "Other"},
    )
    assert response.status_code == 409


def test_register_enforces_password_policy(client):
    weak = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short", "display_name": "Weak"},
    )
    assert weak.status_code == 422
    no_digit = client.post(
        "/api/v1/auth/register",
        json={"email": "weak2@example.com", "password": "onlylettershere", "display_name": "Weak"},
    )
    assert no_digit.status_code == 422

    # Eight characters are enough when the three classes are there.
    eight = client.post(
        "/api/v1/auth/register",
        json={"email": "eight@example.com", "password": "Abcdefg1", "display_name": "Eight"},
    )
    assert eight.status_code == 201

    seven = client.post(
        "/api/v1/auth/register",
        json={"email": "seven@example.com", "password": "Abcdef1", "display_name": "Seven"},
    )
    assert seven.status_code == 422

    no_upper = client.post(
        "/api/v1/auth/register",
        json={"email": "noupper@example.com", "password": "abcdefg1", "display_name": "NoUpper"},
    )
    assert no_upper.status_code == 422


def test_login_and_logout(client):
    register_user(client, email="login@example.com")
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert client.get("/api/v1/auth/me").status_code == 401

    success = login_user(client, "login@example.com")
    assert success.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rejects_bad_credentials(client):
    register_user(client, email="bad@example.com")
    assert login_user(client, "bad@example.com", "WrongPassw0rd!").status_code == 401
    assert login_user(client, "unknown@example.com").status_code == 401


def test_account_locks_after_repeated_failures(client):
    register_user(client, email="lock@example.com")
    for _ in range(5):
        login_user(client, "lock@example.com", "WrongPassw0rd!")
    locked = login_user(client, "lock@example.com")
    assert locked.status_code == 423


def test_api_token_works_without_cookies(client):
    register_user(client, email="token@example.com")
    token_response = client.post(
        "/api/v1/auth/token",
        json={"email": "token@example.com", "password": DEFAULT_PASSWORD},
    )
    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]

    fresh = client.__class__(client.app)  # new cookie jar
    with fresh:
        response = fresh.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert response.status_code == 200


def test_change_password(client):
    register_user(client, email="change@example.com")
    headers = csrf_headers(client)
    wrong = client.post(
        "/api/v1/me/password",
        json={"current_password": "Nope1234567", "new_password": "NewPassw0rd!"},
        headers=headers,
    )
    assert wrong.status_code == 403

    ok = client.post(
        "/api/v1/me/password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "NewPassw0rd!"},
        headers=headers,
    )
    assert ok.status_code == 204
    assert login_user(client, "change@example.com", "NewPassw0rd!").status_code == 200
