# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Administration: access control, moderation queue, account management."""

from __future__ import annotations

from tests.conftest import (
    csrf_headers,
    create_quiz,
    make_admin,
    make_trusted,
    quiz_payload,
    register_user,
)


def test_admin_endpoints_reject_regular_users(client):
    register_user(client)
    headers = csrf_headers(client)
    for path in ("/api/v1/admin/stats", "/api/v1/admin/quizzes", "/api/v1/admin/users"):
        assert client.get(path).status_code == 403
    assert client.patch("/api/v1/admin/users/1", json={"is_admin": True}, headers=headers).status_code == 403


def test_admin_endpoints_require_authentication(client):
    assert client.get("/api/v1/admin/stats").status_code == 401


def test_moderation_queue_lists_pending_quizzes(client):
    register_user(client)
    quiz = create_quiz(client)
    client.post(
        f"/api/v1/quizzes/{quiz['id']}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    make_admin(client)

    pending = client.get("/api/v1/admin/quizzes", params={"status": "pending"}).json()
    assert [row["id"] for row in pending] == [quiz["id"]]
    assert pending[0]["owner_email"] == "player@example.com"

    stats = client.get("/api/v1/admin/stats").json()
    assert stats["quizzes"]["by_status"]["pending"] == 1


def test_admin_can_read_and_edit_any_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="admin@example.com", display_name="Admin")
    make_admin(client)

    details = client.get(f"/api/v1/admin/quizzes/{quiz['id']}")
    assert details.status_code == 200
    assert len(details.json()["questions"]) == 2

    updated = client.put(
        f"/api/v1/admin/quizzes/{quiz['id']}",
        json=quiz_payload("Moderated title"),
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Moderated title"


def test_admin_manages_users(client):
    register_user(client, email="admin@example.com", display_name="Admin")
    make_admin(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    author = register_user(client, email="author@example.com", display_name="Author")

    client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "TestingPassw0rd!"})
    users = client.get("/api/v1/admin/users").json()
    assert {row["email"] for row in users} == {"admin@example.com", "author@example.com"}

    promoted = client.patch(
        f"/api/v1/admin/users/{author['id']}",
        json={"is_trusted": True},
        headers=csrf_headers(client),
    )
    assert promoted.status_code == 200
    assert promoted.json()["is_trusted"] is True
    assert promoted.json()["is_admin"] is False


def test_admin_cannot_lock_themselves_out(client):
    user = register_user(client, email="admin@example.com", display_name="Admin")
    make_admin(client)
    headers = csrf_headers(client)
    assert client.patch(
        f"/api/v1/admin/users/{user['id']}", json={"is_admin": False}, headers=headers
    ).status_code == 409
    assert client.patch(
        f"/api/v1/admin/users/{user['id']}", json={"is_active": False}, headers=headers
    ).status_code == 409
    assert client.delete(f"/api/v1/admin/users/{user['id']}", headers=headers).status_code == 409


def test_deleting_a_user_removes_their_quizzes(client):
    register_user(client, email="admin@example.com", display_name="Admin")
    make_admin(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    author = register_user(client, email="author@example.com", display_name="Author")
    quiz = create_quiz(client)

    client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "TestingPassw0rd!"})
    assert client.delete(
        f"/api/v1/admin/users/{author['id']}", headers=csrf_headers(client)
    ).status_code == 204
    assert client.get(f"/api/v1/admin/quizzes/{quiz['id']}").status_code == 404


def test_disabled_account_cannot_use_its_token(client):
    register_user(client, email="admin@example.com", display_name="Admin")
    make_admin(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    victim = register_user(client, email="victim@example.com", display_name="Victim")
    token = client.cookies.get("ol_session")
    assert client.get("/api/v1/quizzes/mine").status_code == 200

    client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "TestingPassw0rd!"})
    patched = client.patch(
        f"/api/v1/admin/users/{victim['id']}", json={"is_active": False}, headers=csrf_headers(client)
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False

    # The disabled account's still-valid cookie no longer works.
    assert client.get("/api/v1/quizzes/mine", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_trusted_flag_survives_re_reading(client):
    register_user(client)
    make_trusted(client)
    quiz = create_quiz(client)
    response = client.post(
        f"/api/v1/quizzes/{quiz['id']}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert response.json()["status"] == "public"
    assert client.get("/api/v1/auth/me").json()["is_trusted"] is True
