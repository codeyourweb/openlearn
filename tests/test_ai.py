# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""AI assistance: generation, translation and moderation.

The provider is faked at the ``_chat`` boundary so the tests exercise our own
parsing, sanitisation and state transitions without any network access.
"""

from __future__ import annotations

import json

import pytest

from app import ai as ai_module
from app.config import settings
from app.db import SessionLocal
from app.models import AiReview, Quiz
from tests.conftest import (
    create_quiz,
    csrf_headers,
    make_trusted,
    publish_quiz,
    quiz_payload,
    register_user,
)


@pytest.fixture()
def fake_ai(monkeypatch):
    """Enable AI and let the test decide what the model answers."""
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_model", "fake-model")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake-provider/v1")
    monkeypatch.setattr(settings, "ai_api_key", "")
    monkeypatch.setattr(settings, "search_base_url", "")

    def respond(payload: dict):
        monkeypatch.setattr(ai_module, "_chat", lambda *a, **k: json.dumps(payload))
        return payload

    return respond


def set_status(quiz_id: int, status: str) -> None:
    with SessionLocal() as db:
        quiz = db.get(Quiz, quiz_id)
        quiz.status = status
        quiz.is_public = status == "public"
        db.commit()


def test_ai_status_is_false_without_configuration(client):
    status = client.get("/api/v1/ai/status").json()
    assert status["available"] is False
    register_user(client)
    response = client.post(
        "/api/v1/ai/quizzes",
        json={"topic": "Splunk basics", "question_count": 3},
        headers=csrf_headers(client),
    )
    assert response.status_code == 503


def test_generation_sanitises_model_output(client, fake_ai):
    register_user(client)
    fake_ai(
        {
            "title": "Splunk generated",
            "description": "Auto generated",
            "questions": [
                {
                    "text": "<script>alert(1)</script>Which command counts events?",
                    "options": [
                        {"text": "stats", "is_correct": True},
                        {"text": "table", "is_correct": False},
                        {"text": "eval", "is_correct": False},
                        {"text": "dedup", "is_correct": False},
                    ],
                }
            ],
        }
    )
    response = client.post(
        "/api/v1/ai/quizzes",
        json={"topic": "Splunk basics", "question_count": 1, "language": "en"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    draft = response.json()["draft"]
    assert draft["title"] == "Splunk generated"
    text = draft["questions"][0]["text_html"]
    assert "<script" not in text
    assert "Which command counts events?" in text
    assert response.json()["saved"] is None


def test_generation_can_save_a_draft(client, fake_ai):
    register_user(client)
    fake_ai(
        {
            "title": "Saved by AI",
            "description": "",
            "questions": [
                {
                    "text": "Pick the aggregating command",
                    "options": [
                        {"text": "stats", "is_correct": True},
                        {"text": "table", "is_correct": False},
                    ],
                }
            ],
        }
    )
    response = client.post(
        "/api/v1/ai/quizzes",
        json={"topic": "Splunk basics", "question_count": 1, "save": True},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    saved = response.json()["saved"]
    assert saved["status"] == "draft"
    assert saved["ai_generated"] is True
    assert saved["questions"][0]["options"][0]["text"] == "stats"
    assert client.get(f"/api/v1/quizzes/{saved['id']}").status_code == 200


def test_translation_fills_questions_and_options(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    fake_ai(
        {
            "translations": {
                "fr": {
                    "title": "Quiz d'exemple",
                    "description": "Description francaise",
                    "questions": [
                        {
                            "index": 0,
                            "text": "Premiere question ?",
                            "options": [
                                {"index": 0, "text": "Bonne reponse"},
                                {"index": 1, "text": "Mauvaise reponse"},
                            ],
                        }
                    ],
                }
            }
        }
    )
    response = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/translate",
        json={"languages": ["fr"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title_translations"]["fr"] == "Quiz d'exemple"
    assert "fr" in body["languages"]
    assert body["is_multilingual"] is True
    assert body["questions"][0]["translations"]["fr"].startswith("<p>")
    assert body["questions"][0]["options"][0]["translations"]["fr"] == "Bonne reponse"


def test_translation_requires_ownership(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="other@example.com", display_name="Other")
    fake_ai({"translations": {}})
    response = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/translate",
        json={"languages": ["fr"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_safety_review_blocks_a_pending_quiz(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    client.post(
        f"/api/v1/quizzes/{quiz['id']}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    fake_ai(
        {
            "status": "blocked",
            "summary": "Contains operational harm instructions.",
            "findings": [{"question_index": 0, "severity": "high", "issue": "weapons"}],
        }
    )
    response = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/review-legal", headers=csrf_headers(client)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "blocked"

    with SessionLocal() as db:
        stored = db.get(Quiz, quiz["id"])
        assert stored.legal_status == "blocked"
        assert stored.status == "rejected"
        assert stored.is_public is False


def test_review_is_cached_until_the_quiz_changes(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    fake_ai({"status": "approved", "summary": "Fine.", "findings": []})
    first = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/review-legal", headers=csrf_headers(client)
    ).json()
    second = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/review-legal", headers=csrf_headers(client)
    ).json()
    assert first["id"] == second["id"]

    with SessionLocal() as db:
        assert db.query(AiReview).filter(AiReview.kind == "legal").count() == 1

    # Editing the quiz produces a new version, so a new review is required.
    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Changed title"),
        headers=csrf_headers(client),
    )
    with SessionLocal() as db:
        stored = db.get(Quiz, quiz["id"])
        assert stored.legal_status == ""
        assert stored.content_hash


def test_answer_review_can_be_applied(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    fake_ai(
        {
            "status": "corrected",
            "summary": "Question one was ambiguous.",
            "findings": [{"question_index": 0, "severity": "high", "issue": "ambiguous"}],
            "corrections": [
                {
                    "question_index": 0,
                    "text": "Which command aggregates events?",
                    "options": [
                        {"text": "stats", "is_correct": True},
                        {"text": "eval", "is_correct": False},
                        {"text": "rex", "is_correct": False},
                    ],
                }
            ],
        }
    )
    review = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/review-answers", headers=csrf_headers(client)
    ).json()
    assert review["status"] == "corrected"
    assert review["corrections"]

    applied = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/apply-answers", headers=csrf_headers(client)
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["applied"] == 1
    updated = body["quiz"]
    assert updated["questions"][0]["text_plain"] == "Which command aggregates events?"
    assert len(updated["questions"][0]["options"]) == 3
    assert updated["answer_status"] == "corrected"


def test_guest_can_check_answers_of_a_published_quiz(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    publish_quiz(client, quiz["id"])
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    fake_ai({"status": "ok", "summary": "All good.", "findings": [], "corrections": []})
    response = client.post(f"/api/v1/quizzes/{quiz['id']}/ai/review-answers")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    # Free-text findings stay private for a visitor.
    assert response.json()["summary"] == ""


def test_visitor_cannot_read_findings_of_a_draft(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    set_status(quiz["id"], "public")
    fake_ai({"status": "approved", "summary": "Secret note.", "findings": []})
    client.post(f"/api/v1/quizzes/{quiz['id']}/ai/review-legal", headers=csrf_headers(client))
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    reviews = client.get(f"/api/v1/quizzes/{quiz['id']}/reviews")
    assert reviews.status_code == 200
    assert reviews.json()["reviews"][0]["summary"] == ""


def test_trusted_author_publishing_after_clean_review(client, fake_ai):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    fake_ai({"status": "approved", "summary": "Fine.", "findings": []})
    client.post(f"/api/v1/quizzes/{quiz['id']}/ai/review-legal", headers=csrf_headers(client))
    published = client.post(
        f"/api/v1/quizzes/{quiz['id']}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert published.status_code == 200
    assert published.json()["status"] == "public"


def test_the_model_is_not_asked_twice_in_fifteen_seconds(client, fake_ai, monkeypatch):
    """One call per account per window: a page refresh must not become a bill."""
    from app.config import settings

    register_user(client)
    quiz = create_quiz(client)
    fake_ai(
        {
            "translations": {
                "fr": {
                    "title": "Titre",
                    "description": "Description traduite",
                    "questions": [
                        {"index": 0, "text": "Premiere ?", "options": [{"index": 0, "text": "Oui"}, {"index": 1, "text": "Non"}]},
                        {
                        "index": 1,
                        "text": "Seconde ?",
                        "options": [
                            {"index": 0, "text": "A"},
                            {"index": 1, "text": "B"},
                            {"index": 2, "text": "C"},
                            {"index": 3, "text": "D"},
                        ],
                    },
                    ],
                }
            }
        }
    )
    monkeypatch.setattr(settings, "ai_min_interval_seconds", 15)

    first = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/translate",
        json={"languages": ["fr"]},
        headers=csrf_headers(client),
    )
    assert first.status_code == 200, first.text

    # A different purpose, right after the first call: the account is on cooldown.
    second = client.post(
        "/api/v1/ai/quizzes",
        json={"topic": "Splunk basics", "question_count": 3},
        headers=csrf_headers(client),
    )
    assert second.status_code == 429, second.text
    assert "Retry-After" in second.headers


def test_an_unchanged_quiz_is_never_translated_twice(client, fake_ai, monkeypatch):
    from app import ai as ai_module
    from app.config import settings

    register_user(client)
    quiz = create_quiz(client)
    calls: list[int] = []
    monkeypatch.setattr(settings, "ai_min_interval_seconds", 0)

    payload = {
        "translations": {
            "fr": {
                "title": "Titre",
                "description": "Description traduite",
                "questions": [
                    {"index": 0, "text": "Premiere ?", "options": [{"index": 0, "text": "Oui"}, {"index": 1, "text": "Non"}]},
                    {
                        "index": 1,
                        "text": "Seconde ?",
                        "options": [
                            {"index": 0, "text": "A"},
                            {"index": 1, "text": "B"},
                            {"index": 2, "text": "C"},
                            {"index": 3, "text": "D"},
                        ],
                    },
                ],
            }
        }
    }

    def counting_chat(*args, **kwargs):
        calls.append(1)
        return json.dumps(payload)

    monkeypatch.setattr(ai_module, "_chat", counting_chat)
    first = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/translate",
        json={"languages": ["fr"]},
        headers=csrf_headers(client),
    )
    assert first.status_code == 200, first.text
    assert len(calls) == 1

    # Same document, second click: the stored hash answers, the model is spared.
    second = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/translate",
        json={"languages": ["fr"], "overwrite": True},
        headers=csrf_headers(client),
    )
    assert second.status_code == 200, second.text
    assert len(calls) == 1


def test_translating_one_question_only_spends_one_call(client, fake_ai, monkeypatch):
    from app import ai as ai_module
    from app.config import settings

    register_user(client)
    quiz = create_quiz(client)
    monkeypatch.setattr(settings, "ai_min_interval_seconds", 0)
    seen: list[dict] = []

    def capture(_system, user_prompt=None, **kwargs):
        seen.append(kwargs)
        return json.dumps(
            {
                "translations": {
                    "fr": {
                        "title": "",
                        "description": "",
                        "questions": [{"index": 0, "text": "Traduite", "options": [{"index": 0, "text": "Oui"}, {"index": 1, "text": "Non"}]}],
                    }
                }
            }
        )

    monkeypatch.setattr(ai_module, "_chat", capture)
    response = client.post(
        f"/api/v1/quizzes/{quiz['id']}/ai/translate",
        json={"languages": ["fr"], "question_index": 0},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["questions"][0]["translations"]["fr"].startswith("<p>")
    # The second question was left alone: only the requested one was rewritten.
    assert "fr" not in (body["questions"][1]["translations"] or {})
    assert len(seen) == 1


def test_a_grammar_pass_works_on_a_page_whose_id_is_not_the_wiki_id(client, fake_ai, monkeypatch):
    """Field report: "the page does not belong to that wiki", spinning for ever.

    The job carried the page id in `target_id` and the worker compared it to the
    wiki id, so every review failed — except on a wiki home page, the one page
    whose id can equal its wiki's, which is why the first tests were green.
    """
    from app import wiki_ai as wiki_ai_module

    monkeypatch.setattr(
        wiki_ai_module,
        "_chat",
        lambda *args, **kwargs: json.dumps(
            {
                "status": "warn",
                "summary": "Deux accents manquants.",
                "findings": [
                    {
                        "severity": "warn",
                        "quote": "Le resolveur",
                        "issue": "Accent manquant.",
                        "fix": "Le résolveur",
                    }
                ],
                "corrected_markdown": "# Réseau\n\nLe résolveur interroge la racine.\n",
            }
        ),
    )

    register_user(client)
    headers = csrf_headers(client)
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Réseau", "description": "Test."},
        headers=headers,
    ).json()
    # A second page: its id can never equal the wiki id, unlike the home page.
    created = client.post(
        f"/api/v1/wiki/{wiki['id']}/pages",
        json={"title": "Résolveur", "content_md": "# Reseau\n\nLe resolveur interroge la racine.\n"},
        headers=headers,
    )
    assert created.status_code in (200, 201), created.text
    page = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"]
    target = next(row for row in page if row["title"] == "Résolveur")
    assert target["id"] != wiki["id"]

    started = client.post(
        "/api/v1/wiki/ai/jobs",
        json={
            "kind": "grammar",
            "wiki_id": wiki["id"],
            "page_id": target["id"],
            "language": "fr",
        },
        headers=headers,
    )
    assert started.status_code == 202, started.text
    job = client.get(f"/api/v1/wiki/ai/jobs/{started.json()['id']}").json()
    assert job["status"] == "done", job
    assert not job["error"], job["error"]
    assert job["result"]["applied"] is True

    # The correction reached the page, through a real version.
    after = client.get(f"/api/v1/wiki/pages/{target['id']}").json()
    assert "résolveur" in after["content_md"]
    assert after["version"] >= 2


def test_a_grammar_pass_never_translates_the_page(fake_ai, monkeypatch):
    """Field report: a French page came back in English.

    The prompt announced "language of the page" but sent the wiki's default
    language, so a French page in an English-default wiki was translated — and
    the pass writes its answer back into the page.
    """
    from app import wiki_ai as wiki_ai_module

    captured = {}

    def capture(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return json.dumps({"status": "ok", "summary": "Rien à signaler."})

    monkeypatch.setattr(wiki_ai_module, "_chat", capture)
    from app.ai import _chat as _  # noqa: F401 - the patch above targets wiki_ai

    wiki_ai_module.review_page(
        {"title": "Réseau", "content_md": "# Réseau\n\nLe résolveur interroge la racine.\n"},
        language="en",
        kind="grammar",
    )
    prompt = captured["prompt"]
    assert "Never translate" in prompt
    assert "in the language it is actually written in" in prompt


def test_a_review_job_refuses_a_page_from_another_wiki(client, fake_ai, monkeypatch):
    """The check it replaced was wrong, but some check has to remain."""
    from app import wiki_ai as wiki_ai_module

    monkeypatch.setattr(wiki_ai_module, "_chat", lambda *a, **k: json.dumps({"status": "ok"}))

    register_user(client)
    headers = csrf_headers(client)
    first = client.post(
        "/api/v1/wiki", json={"title": "Premier", "description": "Premier"}, headers=headers
    ).json()
    second = client.post(
        "/api/v1/wiki", json={"title": "Second", "description": "Second"}, headers=headers
    ).json()
    target = client.get(f"/api/v1/wiki/{first['id']}").json()["pages"][0]

    from app.db import SessionLocal
    from app.models import AiJob

    with SessionLocal() as db:
        job = AiJob(
            user_id=1,
            kind="grammar",
            key="manual-test-job",
            status="running",
            target_type="wiki",
            target_id=second["id"],  # the wrong wiki on purpose
            payload={"page_id": target["id"], "wiki_id": first["id"]},
        )
        db.add(job)
        db.commit()
        job_id = job.id

    wiki_ai_module.run_job(job_id)
    with SessionLocal() as db:
        stored = db.get(AiJob, job_id)
        assert stored.status == "error"
        assert "does not belong" in (stored.error or "")


def test_a_fill_job_hands_back_the_body_and_writes_nothing(client, fake_ai, monkeypatch):
    """The editor asks for a draft of the page it is working on."""
    from app import wiki_ai as wiki_ai_module

    monkeypatch.setattr(
        wiki_ai_module,
        "_chat",
        lambda *args, **kwargs: "# Resolveur recursif\n\nUn resolveur interroge la racine.\n",
    )

    register_user(client)
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Reseau", "description": "Test."},
        headers=csrf_headers(client),
    ).json()
    home = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"][0]
    before = client.get(f"/api/v1/wiki/pages/{home['id']}").json()

    started = client.post(
        "/api/v1/wiki/ai/jobs",
        json={
            "kind": "fill",
            "wiki_id": wiki["id"],
            "page_id": home["id"],
            "topic": "Resolveur recursif",
            "research": False,
            "instructions": "Explique le role du resolveur en trois paragraphes.",
        },
        headers=csrf_headers(client),
    )
    assert started.status_code == 202, started.text
    job = client.get(f"/api/v1/wiki/ai/jobs/{started.json()['id']}").json()
    assert job["status"] == "done", job
    assert "resolveur interroge la racine" in job["result"]["content_md"]

    # Nothing was stored: the author decides what reaches the page.
    after = client.get(f"/api/v1/wiki/pages/{home['id']}").json()
    assert after["version"] == before["version"]
    assert after["content_md"] == before["content_md"]
