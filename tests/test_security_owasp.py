# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""OWASP Top 10 (2021) oriented security tests.

Each test is mapped to the category it exercises so the traceability matrix in
SECURITY.md stays honest.
"""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import SecurityEvent
from tests.conftest import create_quiz, csrf_headers, question_payload, quiz_payload, register_user


# A01 ---------------------------------------------------------------- access control
def test_participant_cannot_drive_the_game(client):
    register_user(client)
    quiz = create_quiz(client)
    created = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "live"}, headers=csrf_headers(client)
    ).json()
    code = created["session"]["code"]
    guest = TestClient(client.app)
    joined = guest.post(f"/api/v1/sessions/{code}/join", json={"nickname": "Alice"}).json()

    headers = {"X-Participant-Token": joined["participant"]["token"]}
    assert guest.post(f"/api/v1/sessions/{code}/start", headers=headers).status_code == 403
    assert guest.post(f"/api/v1/sessions/{code}/next", headers=headers).status_code == 403
    assert guest.post(f"/api/v1/sessions/{code}/cancel", headers=headers).status_code == 403


def test_anonymous_cannot_list_own_quizzes(client):
    assert client.get("/api/v1/quizzes/mine").status_code == 401


# A02 ------------------------------------------------------ cryptographic failures
def test_password_material_never_leaves_the_server(client):
    user = register_user(client)
    assert "password" not in json.dumps(user).lower()
    assert "hash" not in json.dumps(user).lower()
    me = client.get("/api/v1/auth/me").json()
    assert set(me) == {
        "id",
        "email",
        "display_name",
        "created_at",
        "is_admin",
        "is_moderator",
        "is_staff",
        "is_trusted",
    }
    assert me["is_admin"] is False


def test_session_cookie_is_hardened(client):
    register_user(client)
    cookie_header = client.cookies.jar
    session_cookie = next(c for c in cookie_header if c.name == "ol_session")
    assert session_cookie.secure is False  # OL_COOKIE_SECURE=false in tests
    # HttpOnly/SameSite are set on the response header itself:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "player@example.com", "password": "TestingPassw0rd!"},
    )
    set_cookie = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_forged_jwt_is_rejected(client):
    forged = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.invalidsignature"
    response = TestClient(client.app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_forged_participant_token_is_rejected(client):
    register_user(client)
    quiz = create_quiz(client)
    created = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client)
    ).json()
    code = created["session"]["code"]
    forged = "x" * 40
    # Use an anonymous client: the owner's cookie would legitimately grant host access.
    anonymous = TestClient(client.app)
    response = anonymous.get(f"/api/v1/sessions/{code}/state", headers={"X-Participant-Token": forged})
    assert response.status_code == 403


# A03 ------------------------------------------------------------ injection / XSS
def test_sql_injection_payloads_are_harmless(client):
    register_user(client)
    create_quiz(client)
    for payload in ("' OR 1=1--", "'; DROP TABLE quizzes;--", "%' UNION SELECT password_hash FROM users--"):
        response = client.get("/api/v1/quizzes", params={"q": payload})
        assert response.status_code == 200
        assert response.json() == [] or isinstance(response.json(), list)
    # The schema is still intact after the attempts.
    assert client.get("/api/v1/quizzes").status_code == 200


def test_stored_xss_payload_is_neutralised(client):
    register_user(client)
    payload = quiz_payload(
        questions=[
            {
                "text_html": "<p>Q</p><script>alert(document.cookie)</script><svg onload=alert(1)>",
                "time_limit_seconds": 20,
                "points": 100,
                "options": [{"text": "Yes", "is_correct": True}, {"text": "No", "is_correct": False}],
            }
        ]
    )
    quiz = create_quiz(client, payload)
    stored = quiz["questions"][0]["text_html"].lower()
    assert "<script" not in stored and "<svg" not in stored and "onload" not in stored


def test_path_traversal_cannot_read_files(client):
    for path in ("/..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/etc/passwd", "/media/../../etc/passwd"):
        response = client.get(path)
        assert response.status_code in (200, 404)
        assert "root:x:0:0" not in response.text


# A04 -------------------------------------------------------- insecure design
def test_login_is_rate_limited(client):
    assert client.get("/api/v1/auth/csrf").status_code == 200
    statuses = []
    for index in range(12):
        response = client.post(
            "/api/v1/auth/login", json={"email": f"nobody{index}@example.com", "password": "Whatever12345"}
        )
        statuses.append(response.status_code)
    assert 429 in statuses
    assert statuses[-1] == 429


def test_oversized_json_body_is_refused(client):
    big = {"email": "a@example.com", "password": "x" * (3 * 1024 * 1024)}
    response = client.post("/api/v1/auth/login", json=big)
    assert response.status_code == 413


def test_option_count_is_bounded(client):
    register_user(client)
    too_many = quiz_payload(
        questions=[question_payload(options=[(f"Opt {index}", index == 0) for index in range(9)])]
    )
    assert client.post("/api/v1/quizzes", json=too_many, headers=csrf_headers(client)).status_code == 422


# A05 ---------------------------------------------------- security misconfiguration
def test_security_headers_on_api_and_spa(client):
    for path in ("/", "/api/v1/health"):
        response = client.get(path)
        headers = {key.lower(): value for key, value in response.headers.items()}
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "content-security-policy" in headers
        csp = headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
        assert "frame-ancestors 'none'" in csp


def test_api_cache_is_not_stored(client):
    response = client.get("/api/v1/health")
    assert response.headers.get("cache-control") == "no-store"


def test_unknown_api_route_does_not_fall_back_to_spa(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


# A07 ------------------------------------------- identification / auth failures
def test_csrf_is_required_for_cookie_clients(client):
    register_user(client)
    payload = quiz_payload()
    without_token = client.post("/api/v1/quizzes", json=payload)
    assert without_token.status_code == 403
    with_token = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert with_token.status_code == 201


def test_api_key_authentication_and_revocation(client):
    register_user(client)
    created = client.post("/api/v1/me/api-keys", json={"name": "cli"}, headers=csrf_headers(client)).json()

    api_client = TestClient(client.app)
    headers = {"X-API-Key": created["key"]}
    assert api_client.get("/api/v1/auth/me", headers=headers).status_code == 200
    # API-key clients are not cookie clients: no CSRF token required.
    assert api_client.post("/api/v1/quizzes", json=quiz_payload(), headers=headers).status_code == 201

    revoke = client.delete(f"/api/v1/me/api-keys/{created['id']}", headers=csrf_headers(client))
    assert revoke.status_code == 204
    assert api_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_api_key_cannot_be_read_back(client):
    register_user(client)
    created = client.post("/api/v1/me/api-keys", json={"name": "cli"}, headers=csrf_headers(client)).json()
    listing = client.get("/api/v1/me/api-keys").json()
    assert listing and "key" not in listing[0]
    assert listing[0]["prefix"] == created["key"][:10]


# A09 ------------------------------------------------ logging and monitoring
def test_failed_login_is_audited(client):
    register_user(client, email="audit@example.com")
    client.post("/api/v1/auth/login", json={"email": "audit@example.com", "password": "WrongPassw0rd1"})
    with SessionLocal() as db:
        events = list(db.scalars(select(SecurityEvent).where(SecurityEvent.event == "login_failure")))
    assert events, "a failed login must produce a security event"


# A10 --------------------------------------------------------- SSRF / uploads
def test_upload_rejects_non_images(client):
    register_user(client)
    response = client.post(
        "/api/v1/uploads/question-image",
        files={"file": ("evil.png", io.BytesIO(b"<html><script>alert(1)</script></html>"), "image/png")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 415


def test_upload_requires_authentication(client):
    response = client.post(
        "/api/v1/uploads/question-image",
        files={"file": ("x.png", io.BytesIO(b"data"), "image/png")},
    )
    assert response.status_code == 401


def test_valid_image_is_reencoded(client):
    register_user(client)
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (120, 20, 200)).save(buffer, format="PNG")
    buffer.seek(0)
    response = client.post(
        "/api/v1/uploads/question-image",
        files={"file": ("logo.png", buffer, "image/png")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["path"].startswith("/media/")
    assert body["path"].endswith(".webp")


def test_remote_image_reference_is_refused(client):
    register_user(client)
    payload = quiz_payload(questions=[question_payload(image="http://169.254.169.254/latest/meta-data/")])
    assert client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client)).status_code == 422


# A04/A07 ------------------------------------------- forwarded headers and cookies
def _scope(peer: str, forwarded_for: str | None) -> dict:
    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for else []
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "scheme": "http",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 12345),
        "server": ("testserver", 80),
    }


def test_forwarded_for_from_untrusted_peer_is_ignored():
    """A direct caller must not be able to pick its own rate-limit identity."""
    from starlette.requests import Request

    from app.deps import client_ip

    spoofed = Request(_scope("203.0.113.7", "198.51.100.1"))
    assert client_ip(spoofed) == "203.0.113.7"

    through_proxy = Request(_scope("10.1.2.3", "198.51.100.1, 10.1.2.3"))
    assert client_ip(through_proxy) == "198.51.100.1"


def test_secure_cookie_when_tls_terminates_upstream(client):
    """Behind the TLS reverse proxy the session cookie must be flagged Secure."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "tls-cookie@example.com",
            "password": "Str0ngPassword!23",
            "display_name": "TLS Cookie",
        },
        headers={"X-Forwarded-Proto": "https"},
    )
    assert response.status_code == 201
    set_cookie = [value for value in response.headers.get_list("set-cookie") if "ol_session=" in value]
    assert set_cookie, "session cookie missing"
    assert "Secure" in set_cookie[0]
    assert "HttpOnly" in set_cookie[0]
