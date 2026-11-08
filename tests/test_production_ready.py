# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Production readiness: instance metadata, administration settings, account
recovery, MCP endpoint and single sign-on.

These cover the surface an operator touches — the one that never appears in a
quiz scenario but decides whether an instance can be handed to real users.
"""

from __future__ import annotations

import json

from tests.conftest import DEFAULT_PASSWORD, csrf_headers, login_user, make_admin, register_user

# --------------------------------------------------------------------------- #
# Instance metadata                                                            #
# --------------------------------------------------------------------------- #


def test_meta_describes_the_instance_without_authentication(client):
    payload = client.get("/api/v1/meta").json()
    for field in ("name", "version", "demo_mode", "languages", "ai", "mail", "sso", "mcp"):
        assert field in payload, field
    assert payload["languages"], "the interface languages must be declared"
    assert {"enabled", "available"} <= set(payload["ai"])
    assert payload["mcp"]["endpoint"]


def test_meta_never_leaks_a_secret(client):
    body = client.get("/api/v1/meta").text.lower()
    assert "api_key" not in body
    assert "password" not in body


# --------------------------------------------------------------------------- #
# Administration settings                                                      #
# --------------------------------------------------------------------------- #


def test_settings_require_an_administrator(client):
    register_user(client)
    assert client.get("/api/v1/admin/settings").status_code == 403
    response = client.put(
        "/api/v1/admin/settings",
        json={"values": {"ai.enabled": True}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_settings_expose_types_and_mask_secrets(client):
    register_user(client)
    make_admin(client)
    data = client.get("/api/v1/admin/settings").json()
    assert set(data["sections"]) == {"ai", "mail", "security", "instance"}

    rows = {row["key"]: row for row in data["sections"]["ai"]}
    assert rows["ai.enabled"]["type"] == "bool"
    assert rows["ai.min_interval_seconds"]["type"] == "int"
    assert rows["ai.api_key"]["secret"] is True

    client.put(
        "/api/v1/admin/settings",
        json={"values": {"ai.api_key": "sk-secret-value"}},
        headers=csrf_headers(client),
    )
    after = client.get("/api/v1/admin/settings")
    assert "sk-secret-value" not in after.text, "a stored secret must never come back"
    assert {row["key"]: row for row in after.json()["sections"]["ai"]}["ai.api_key"]["is_set"] is True


def test_a_setting_survives_and_reports_itself_as_overridden(client):
    register_user(client)
    make_admin(client)
    client.put(
        "/api/v1/admin/settings",
        json={"values": {"ai.min_interval_seconds": 42}},
        headers=csrf_headers(client),
    )
    rows = {r["key"]: r for r in client.get("/api/v1/admin/settings").json()["sections"]["ai"]}
    assert rows["ai.min_interval_seconds"]["value"] == 42
    assert rows["ai.min_interval_seconds"]["overridden"] is True


def test_an_unknown_setting_is_refused(client):
    register_user(client)
    make_admin(client)
    response = client.put(
        "/api/v1/admin/settings",
        json={"values": {"ai.not_a_setting": 1}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422


def test_the_ai_switch_is_reflected_in_the_public_metadata(client):
    register_user(client)
    make_admin(client)
    assert client.get("/api/v1/meta").json()["ai"]["enabled"] is False  # test default

    client.put("/api/v1/admin/settings", json={"values": {"ai.enabled": True}}, headers=csrf_headers(client))
    assert client.get("/api/v1/meta").json()["ai"]["enabled"] is True

    client.put("/api/v1/admin/settings", json={"values": {"ai.enabled": False}}, headers=csrf_headers(client))
    assert client.get("/api/v1/meta").json()["ai"]["enabled"] is False


def test_ai_connection_test_without_a_model_reports_a_failure(client):
    register_user(client)
    make_admin(client)
    response = client.post("/api/v1/admin/settings/ai/test", json={}, headers=csrf_headers(client))
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_ai_failures_are_logged_and_the_log_can_be_cleared(client):
    register_user(client)
    make_admin(client)
    from app import runtime

    runtime.record_ai_error(
        operation="unit-test",
        model="ghost-model",
        base_url="http://127.0.0.1:9/v1",
        status_code=503,
        detail="provider unreachable",
    )

    listing = client.get("/api/v1/admin/ai/errors").json()
    assert listing["total"] >= 1
    assert listing["items"][0]["operation"] == "unit-test"
    assert listing["items"][0]["status_code"] == 503

    assert client.delete("/api/v1/admin/ai/errors", headers=csrf_headers(client)).status_code == 204
    assert client.get("/api/v1/admin/ai/errors").json()["total"] == 0


def test_the_error_log_is_administrator_only(client):
    register_user(client)
    assert client.get("/api/v1/admin/ai/errors").status_code == 403


# --------------------------------------------------------------------------- #
# Password reset                                                               #
# --------------------------------------------------------------------------- #


def test_forgot_answers_the_same_for_an_unknown_address(client):
    response = client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    assert response.status_code == 202
    assert "nobody@example.com" not in json.dumps(response.json())


def test_reset_token_is_single_use_and_invalidates_open_sessions(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "expose_reset_token", True, raising=False)

    register_user(client, email="reset@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "reset@example.com").one()
        user_id, before = user.id, user.token_version

    issued = client.post("/api/v1/auth/password/forgot", json={"email": "reset@example.com"}).json()
    token = issued.get("token")
    assert token, issued

    assert client.get(f"/api/v1/auth/password/reset/{token}").status_code == 200
    assert client.post(
        "/api/v1/auth/password/reset", json={"token": token, "password": "BrandNewPass1!"}
    ).status_code == 204

    # The session opened before the reset died with the old password.
    assert client.get("/api/v1/auth/me").status_code == 401

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.token_version == before + 1

    # Replaying the link is refused, and only the new password opens a session.
    replay = client.post("/api/v1/auth/password/reset", json={"token": token, "password": "AnotherPass1!"})
    assert replay.status_code in (400, 404, 410), replay.text
    assert login_user(client, "reset@example.com", DEFAULT_PASSWORD).status_code == 401
    assert login_user(client, "reset@example.com", "BrandNewPass1!").status_code == 200


def test_reset_refuses_an_unknown_token(client):
    assert client.get("/api/v1/auth/password/reset/not-a-real-token").status_code == 404
    response = client.post(
        "/api/v1/auth/password/reset",
        json={"token": "not-a-real-token", "password": "Whatever1!"},
    )
    assert response.status_code in (400, 404, 410)


def test_a_new_request_invalidates_the_previous_link(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "expose_reset_token", True, raising=False)
    register_user(client, email="twice@example.com")

    first = client.post("/api/v1/auth/password/forgot", json={"email": "twice@example.com"}).json()["token"]
    second = client.post("/api/v1/auth/password/forgot", json={"email": "twice@example.com"}).json()["token"]
    assert first != second
    assert client.get(f"/api/v1/auth/password/reset/{first}").status_code == 404
    assert client.get(f"/api/v1/auth/password/reset/{second}").status_code == 200


# --------------------------------------------------------------------------- #
# MCP                                                                          #
# --------------------------------------------------------------------------- #


def mcp(client, method: str, params: dict | None = None):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={"Content-Type": "application/json"},
    )


def test_mcp_initializes_and_lists_read_only_tools(client):
    register_user(client)
    response = mcp(client, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"]

    tools = mcp(client, "tools/list").json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "openlearn_search_pages" in names
    assert "openlearn_list_wikis" in names
    # Read-only by design: a write tool would need a consent model we do not have.
    assert not [name for name in names if any(w in name for w in ("create", "update", "delete", "publish"))]


def test_mcp_search_finds_a_published_page(client):
    register_user(client)
    created = client.post(
        "/api/v1/wiki",
        json={"title": "MCP probe wiki", "description": "Probe", "language": "en", "visibility": "public"},
        headers=csrf_headers(client),
    )
    assert created.status_code == 201, created.text
    wiki_id = created.json()["id"]
    page = client.post(
        f"/api/v1/wiki/{wiki_id}/pages",
        json={"title": "Photosynthesis", "content_md": "Chlorophyll captures light."},
        headers=csrf_headers(client),
    )
    assert page.status_code == 201, page.text

    payload = mcp(
        client,
        "tools/call",
        {"name": "openlearn_search_pages", "arguments": {"query": "Photosynthesis"}},
    ).json()
    assert "result" in payload, payload
    assert "Photosynthesis" in json.dumps(payload)


def test_mcp_rejects_an_unknown_method(client):
    register_user(client)
    payload = mcp(client, "tools/nonexistent").json()
    assert payload["error"]["code"] == -32601


# --------------------------------------------------------------------------- #
# Single sign-on                                                               #
# --------------------------------------------------------------------------- #


def test_no_provider_is_offered_by_default(client):
    payload = client.get("/api/v1/auth/sso/providers").json()
    providers = payload["providers"] if isinstance(payload, dict) else payload
    assert providers == []


def test_a_declared_provider_becomes_public_without_its_secret(client):
    register_user(client)
    make_admin(client)
    created = client.post(
        "/api/v1/admin/sso/providers",
        json={
            "slug": "okta",
            "label": "Okta",
            "kind": "oidc",
            "enabled": True,
            "issuer": "https://example.okta.com",
            "client_id": "abc",
            "client_secret": "shh",
            "allowed_domains": "example.com",
        },
        headers=csrf_headers(client),
    )
    assert created.status_code == 201, created.text
    assert "client_secret" not in created.text

    payload = client.get("/api/v1/auth/sso/providers").json()
    providers = payload["providers"] if isinstance(payload, dict) else payload
    assert [row["slug"] for row in providers] == ["okta"]
    assert "client_secret" not in json.dumps(providers)


def test_an_unknown_provider_cannot_be_started(client):
    response = client.get("/api/v1/auth/sso/ghost/start", follow_redirects=False)
    assert response.status_code == 404


def test_a_provider_needs_a_slug_and_a_label(client):
    register_user(client)
    make_admin(client)
    response = client.post(
        "/api/v1/admin/sso/providers",
        json={"label": "No slug", "kind": "oidc"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
