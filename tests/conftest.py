# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Shared pytest fixtures: isolated database, API client and helpers."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

# Environment must be configured before the application package is imported.
TEST_ROOT = Path(tempfile.mkdtemp(prefix="openlearn-tests-"))
os.environ["OL_ENVIRONMENT"] = "test"
os.environ["OL_DATABASE_URL"] = f"sqlite:///{TEST_ROOT}/test.db"
os.environ["OL_MEDIA_DIR"] = str(TEST_ROOT / "media")
os.environ["OL_SEED_DEMO_DATA"] = "false"
os.environ["OL_SECRET_KEY"] = "unit-test-secret-key-do-not-use-in-production"
os.environ["OL_COOKIE_SECURE"] = "false"
# A production .env sitting in the checkout must never leak into a test run:
# it would bootstrap a real administrator, point share links at the live host,
# and turn on a model provider that no test asked for.
os.environ["OL_PUBLIC_BASE_URL"] = ""
os.environ["OL_AI_ENABLED"] = "false"
os.environ["OL_ADMIN_EMAIL"] = ""
os.environ["OL_ADMIN_PASSWORD"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.security import rate_limiter  # noqa: E402

DEFAULT_PASSWORD = "TestingPassw0rd!"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


def _fresh_database_file() -> None:
    """Empty the test database, even when a connection outlived its test.

    A websocket handler or a reveal timer cancelled at loop shutdown can leave a
    session checked out of the pool; SQLite then refuses the DDL of the next test
    with "database table is locked" and no amount of retrying helps. Deleting the
    file is deterministic: the stale connection keeps writing to an unlinked
    inode, and the new file starts empty.
    """
    from app import collab

    collab.reset_all()
    engine.dispose()
    try:
        Base.metadata.drop_all(bind=engine)
        return
    except OperationalError:
        engine.dispose()
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{settings.database_url.removeprefix('sqlite:///')}{suffix}").unlink(
                missing_ok=True
            )


@pytest.fixture(autouse=True)
def clean_setting_cache():
    """Settings are cached for three seconds, tests must not depend on wall time.

    A test that patches ``settings`` right after another test read the same key
    used to keep the stale entry for up to three seconds and then fail with
    "AI assistance is not configured" — which only happened on a fast machine.
    """
    from app import runtime

    runtime.invalidate()
    yield
    runtime.invalidate()


@pytest.fixture()
def client():
    """Fresh application + empty database for every test."""
    _fresh_database_file()
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    # The 15-second AI spacing is a production guard; keeping it here would make
    # every test that asks twice in a row wait or fail for the wrong reason.
    settings.ai_min_interval_seconds = 0
    with TestClient(app) as test_client:
        test_client.headers.update({"user-agent": "pytest"})
        yield test_client
    # Sockets opened by the test must not leave an autosave pointing at a
    # database that the next test is about to drop.
    from app import collab

    collab.reset_all()


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("ol_csrf") or ""
    return {"X-CSRF-Token": token} if token else {}


def register_user(
    client: TestClient,
    email: str = "player@example.com",
    password: str = DEFAULT_PASSWORD,
    display_name: str = "Player One",
):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login_user(client: TestClient, email: str, password: str = DEFAULT_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def question_payload(
    text: str = "What is the answer?",
    options: list[tuple[str, bool]] | None = None,
    *,
    time_limit: int = 30,
    points: int = 100,
    image: str | None = None,
):
    options = options or [("Correct answer", True), ("Wrong answer", False)]
    return {
        "text_html": f"<p>{text}</p>",
        "image_path": image,
        "time_limit_seconds": time_limit,
        "points": points,
        "options": [{"text": text_value, "is_correct": correct} for text_value, correct in options],
    }


def quiz_payload(
    title: str = "Sample quiz",
    *,
    questions: list[dict] | None = None,
    policy: str = "zero",
    public: bool = True,
    description: str = "A quiz used by the test suite.",
):
    return {
        "title": title,
        "description": description,
        "wrong_answer_policy": policy,
        "is_public": public,
        "questions": questions
        or [
            question_payload("Question one?"),
            question_payload(
                "Question two?",
                [("A", True), ("B", True), ("C", False), ("D", False)],
            ),
        ],
    }


def make_trusted(client: TestClient) -> None:
    """Grant the signed-in user the trusted author flag (test shortcut).

    Moderation itself is covered by tests/test_admin.py; most test modules only
    need a published quiz without driving the whole workflow.
    """
    from app.db import SessionLocal
    from app.models import User

    me = client.get("/api/v1/auth/me").json()
    with SessionLocal() as db:
        user = db.get(User, me["id"])
        assert user is not None
        user.is_trusted = True
        db.commit()


def make_admin(client: TestClient) -> None:
    """Grant the signed-in user administrator rights (test shortcut)."""
    from app.db import SessionLocal
    from app.models import User

    me = client.get("/api/v1/auth/me").json()
    with SessionLocal() as db:
        user = db.get(User, me["id"])
        assert user is not None
        user.is_admin = True
        user.is_trusted = True
        db.commit()


def publish_quiz(client: TestClient, quiz_id: int, *, trusted: bool = True) -> dict:
    if trusted:
        make_trusted(client)
    response = client.post(
        f"/api/v1/quizzes/{quiz_id}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def answer_key(state_question: dict, quiz: dict) -> dict:
    """Map a shuffled session question back to the quiz answer key.

    Session questions and options are shuffled per session, so the position of a
    correct option in the state payload says nothing. Matching on the question
    and option text recovers the intent of the authored quiz.
    """
    source = next(
        question
        for question in quiz["questions"]
        if question["text_html"] == state_question["text_html"]
    )
    correct_texts = {option["text"] for option in source["options"] if option["is_correct"]}
    wrong_texts = {option["text"] for option in source["options"] if not option["is_correct"]}
    return {
        "correct": [option["id"] for option in state_question["options"] if option["text"] in correct_texts],
        "wrong": [option["id"] for option in state_question["options"] if option["text"] in wrong_texts],
    }


def create_quiz(client: TestClient, payload: dict | None = None, *, headers: dict | None = None) -> dict:
    response = client.post(
        "/api/v1/quizzes",
        json=payload or quiz_payload(),
        headers=headers if headers is not None else csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()
