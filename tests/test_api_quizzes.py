# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Quiz CRUD, validation and HTML sanitisation."""

from __future__ import annotations

from tests.conftest import (
    DEFAULT_PASSWORD,
    csrf_headers,
    create_quiz,
    question_payload,
    quiz_payload,
    publish_quiz,
    register_user,
)


def test_create_and_read_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    assert quiz["title"] == "Sample quiz"
    assert len(quiz["questions"]) == 2
    assert quiz["questions"][0]["options"][0]["is_correct"] is True

    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert detail["owner_name"] == "Player One"
    assert detail["question_count"] == 2


def test_anonymous_view_hides_correct_answers(client):
    register_user(client)
    quiz = create_quiz(client)
    publish_quiz(client, quiz["id"])
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    public = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    for question in public["questions"]:
        assert all("is_correct" not in option for option in question["options"])


def test_private_quiz_is_hidden_from_anonymous(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload(public=False))
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 404


def test_list_and_search(client):
    register_user(client)
    first = create_quiz(client, quiz_payload("Linux basics"))
    second = create_quiz(client, quiz_payload("Splunk advanced"))
    publish_quiz(client, first["id"])
    publish_quiz(client, second["id"])

    everything = client.get("/api/v1/quizzes").json()
    assert len(everything) == 2

    search = client.get("/api/v1/quizzes", params={"q": "splunk"}).json()
    assert len(search) == 1
    assert search[0]["title"] == "Splunk advanced"

    mine = client.get("/api/v1/quizzes/mine").json()
    assert len(mine) == 2


def test_update_quiz_replaces_questions(client):
    register_user(client)
    quiz = create_quiz(client)
    payload = quiz_payload(
        "Updated quiz",
        questions=[question_payload("Only one question now?")],
        policy="penalty",
    )
    response = client.put(f"/api/v1/quizzes/{quiz['id']}", json=payload, headers=csrf_headers(client))
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["title"] == "Updated quiz"
    assert len(updated["questions"]) == 1
    assert updated["wrong_answer_policy"] == "penalty"


def test_other_user_cannot_modify_quiz(client):
    register_user(client, email="owner@example.com")
    quiz = create_quiz(client)
    owner_headers = csrf_headers(client)
    client.post("/api/v1/auth/logout", headers=owner_headers)

    register_user(client, email="intruder@example.com", display_name="Intruder")
    headers = csrf_headers(client)
    update = client.put(f"/api/v1/quizzes/{quiz['id']}", json=quiz_payload(), headers=headers)
    assert update.status_code == 403
    delete = client.delete(f"/api/v1/quizzes/{quiz['id']}", headers=headers)
    assert delete.status_code == 403


def test_delete_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    response = client.delete(f"/api/v1/quizzes/{quiz['id']}", headers=csrf_headers(client))
    assert response.status_code == 204
    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 404


def test_duplicate_quiz_belongs_to_copier(client):
    register_user(client, email="author@example.com")
    quiz = create_quiz(client)
    publish_quiz(client, quiz["id"])
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="copier@example.com", display_name="Copier")

    copy = client.post(f"/api/v1/quizzes/{quiz['id']}/duplicate", headers=csrf_headers(client))
    assert copy.status_code == 201
    body = copy.json()
    assert body["owner_id"] != quiz["owner_id"]
    assert body["title"].endswith("(copy)")
    assert body["is_public"] is False


def test_quiz_validation_rules(client):
    register_user(client)
    headers = csrf_headers(client)

    no_correct = quiz_payload(questions=[question_payload(options=[("A", False), ("B", False)])])
    assert client.post("/api/v1/quizzes", json=no_correct, headers=headers).status_code == 422

    all_correct = quiz_payload(questions=[question_payload(options=[("A", True), ("B", True)])])
    assert client.post("/api/v1/quizzes", json=all_correct, headers=headers).status_code == 422

    too_few = quiz_payload(questions=[question_payload(options=[("A", True)])])
    assert client.post("/api/v1/quizzes", json=too_few, headers=headers).status_code == 422

    too_many = quiz_payload(
        questions=[question_payload(options=[(f"Option {i}", i == 0) for i in range(9)])]
    )
    assert client.post("/api/v1/quizzes", json=too_many, headers=headers).status_code == 422

    empty_text = quiz_payload(questions=[question_payload(text="   ")])
    assert client.post("/api/v1/quizzes", json=empty_text, headers=headers).status_code == 422

    bad_timer = quiz_payload(questions=[question_payload(time_limit=2)])
    assert client.post("/api/v1/quizzes", json=bad_timer, headers=headers).status_code == 422


def test_question_text_is_sanitised(client):
    register_user(client)
    payload = quiz_payload(
        questions=[
            {
                "text_html": (
                    "<p>Hello <script>alert('xss')</script><strong>bold</strong></p>"
                    "<a href='javascript:alert(1)'>click</a>"
                    "<img src=x onerror='alert(2)'>"
                ),
                "time_limit_seconds": 30,
                "points": 100,
                "options": [{"text": "Yes", "is_correct": True}, {"text": "No", "is_correct": False}],
            }
        ]
    )
    quiz = create_quiz(client, payload)
    html = quiz["questions"][0]["text_html"]
    assert "<script" not in html.lower()
    assert "javascript:" not in html.lower()
    assert "onerror" not in html.lower()
    assert "<a " not in html.lower()
    assert "<img" not in html.lower()
    assert "<strong>bold</strong>" in html


def test_image_path_must_come_from_uploads(client):
    register_user(client)
    headers = csrf_headers(client)
    remote = quiz_payload(questions=[question_payload(image="https://evil.example.com/x.png")])
    assert client.post("/api/v1/quizzes", json=remote, headers=headers).status_code == 422

    traversal = quiz_payload(questions=[question_payload(image="/media/../../etc/passwd")])
    assert client.post("/api/v1/quizzes", json=traversal, headers=headers).status_code == 422

    valid = quiz_payload(questions=[question_payload(image="/media/abc123.webp")])
    assert client.post("/api/v1/quizzes", json=valid, headers=headers).status_code == 201


def test_public_listing_hides_private_quizzes_of_others(client):
    register_user(client, email="owner2@example.com")
    create_quiz(client, quiz_payload("Secret quiz", public=False))
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    register_user(client, email="visitor@example.com", display_name="Visitor", password=DEFAULT_PASSWORD)
    listing = client.get("/api/v1/quizzes").json()
    assert all(item["title"] != "Secret quiz" for item in listing)
