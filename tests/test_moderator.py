# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The moderator account: all of moderation, none of the configuration."""

from __future__ import annotations

from tests.conftest import (
    csrf_headers,
    create_quiz,
    make_admin,
    make_moderator,
    register_user,
)


def _signed_in_moderator(client):
    register_user(client, email="mod@example.com", display_name="Moderator")
    make_moderator(client)
    return csrf_headers(client)


def test_a_moderator_reaches_every_moderation_list(client):
    _signed_in_moderator(client)
    for path in (
        "/api/v1/admin/stats",
        "/api/v1/admin/quizzes",
        "/api/v1/admin/wikis",
        "/api/v1/admin/users",
        "/api/v1/admin/reviews",
        "/api/v1/admin/events",
    ):
        assert client.get(path).status_code == 200, path
    assert client.get("/api/v1/auth/me").json()["is_staff"] is True


def test_a_moderator_validates_content(client):
    register_user(client)
    quiz = create_quiz(client)
    client.post(
        f"/api/v1/quizzes/{quiz['id']}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    headers = _signed_in_moderator(client)
    pending = client.get("/api/v1/admin/quizzes", params={"status": "pending"}).json()
    assert [row["id"] for row in pending] == [quiz["id"]]
    approved = client.post(f"/api/v1/admin/quizzes/{quiz['id']}/approve", json={"note": ""}, headers=headers)
    assert approved.status_code == 200


def test_a_moderator_never_reaches_the_instance_configuration(client):
    _signed_in_moderator(client)
    for path in ("/api/v1/admin/settings", "/api/v1/admin/sso/providers", "/api/v1/admin/ai/errors"):
        assert client.get(path).status_code == 403, path
    assert client.put("/api/v1/admin/settings", json={"ai_model": "x"}, headers=csrf_headers(client)).status_code == 403
    assert client.post("/api/v1/admin/settings/ai/test").status_code == 403
    assert client.post("/api/v1/admin/settings/mail/test").status_code == 403


def test_a_moderator_vouches_but_never_promotes(client):
    register_user(client, email="member@example.com", display_name="Member")
    member = client.get("/api/v1/auth/me").json()
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    headers = _signed_in_moderator(client)
    trusted = client.patch(f"/api/v1/admin/users/{member['id']}", json={"is_trusted": True}, headers=headers)
    assert trusted.status_code == 200
    assert trusted.json()["is_trusted"] is True

    for payload in ({"is_admin": True}, {"is_moderator": True}, {"is_active": False}):
        refused = client.patch(f"/api/v1/admin/users/{member['id']}", json=payload, headers=headers)
        assert refused.status_code == 403, payload
        assert "moderator" in refused.json()["detail"].lower()


def test_a_moderator_cannot_touch_another_staff_account(client):
    register_user(client, email="peer@example.com", display_name="Peer")
    peer = client.get("/api/v1/auth/me").json()
    make_moderator(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    headers = _signed_in_moderator(client)
    refused = client.patch(f"/api/v1/admin/users/{peer['id']}", json={"is_trusted": False}, headers=headers)
    assert refused.status_code == 403
    assert client.delete(f"/api/v1/admin/users/{peer['id']}", headers=headers).status_code == 403


def test_a_moderator_cannot_delete_an_account(client):
    register_user(client, email="other@example.com", display_name="Other")
    other = client.get("/api/v1/auth/me").json()
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    headers = _signed_in_moderator(client)
    assert client.delete(f"/api/v1/admin/users/{other['id']}", headers=headers).status_code == 403


def test_an_administrator_names_a_moderator(client):
    register_user(client, email="member@example.com", display_name="Member")
    member = client.get("/api/v1/auth/me").json()
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="admin@example.com", display_name="Admin")
    make_admin(client)

    response = client.patch(
        f"/api/v1/admin/users/{member['id']}",
        json={"is_moderator": True},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    assert response.json()["is_moderator"] is True
    assert response.json()["is_admin"] is False


def test_the_moderator_flag_is_not_inherited_from_the_trusted_flag(client):
    register_user(client, email="trusted@example.com", display_name="Trusted")
    me = client.get("/api/v1/auth/me").json()
    assert me["is_moderator"] is False
    assert me["is_staff"] is False
