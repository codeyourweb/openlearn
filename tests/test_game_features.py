# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Quiz modes, multilingual sessions, timer safety net and search."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text

from app.db import SessionLocal
from app.models import GameSession, utcnow
from tests.conftest import (
    csrf_headers,
    create_quiz,
    publish_quiz,
    question_payload,
    quiz_payload,
    register_user,
)


def create_session(client, quiz_id: int, **payload) -> dict:
    response = client.post(
        f"/api/v1/quizzes/{quiz_id}/sessions",
        json={"mode": "solo", **payload},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Swipe mode
# ---------------------------------------------------------------------------
def test_swipe_quiz_rejects_more_than_two_answers(client):
    register_user(client)
    payload = quiz_payload(
        "Yes or no?",
        questions=[question_payload(options=[("A", True), ("B", False), ("C", False)])],
    )
    payload["mode"] = "swipe"
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422


def test_swipe_quiz_is_snapshotted_with_canonical_labels(client):
    register_user(client)
    payload = quiz_payload(
        "Swipe deck",
        questions=[
            question_payload(options=[("Oui", True), ("Non", False)]),
            question_payload(options=[("Nope", True), ("Yep", False)]),
        ],
    )
    payload["mode"] = "swipe"
    quiz = create_quiz(client, payload)
    assert quiz["mode"] == "swipe"
    assert [option["text"] for option in quiz["questions"][0]["options"]] == ["Yes", "No"]
    assert quiz["questions"][1]["options"][0]["is_correct"] is True

    state = create_session(client, quiz["id"])["state"]
    assert state["session"]["mode"] == "swipe"
    assert [option["text"] for option in state["question"]["options"]] == ["Yes", "No"]
    # Scoring still uses the canonical option ids.
    assert state["question"]["multiple_answers"] is False


# ---------------------------------------------------------------------------
# Multilingual sessions
# ---------------------------------------------------------------------------
def test_session_uses_the_requested_language(client):
    register_user(client)
    # A single question keeps the assertion independent from the shuffled order.
    payload = quiz_payload("Quiz bilingue", questions=[question_payload("What is the answer?")])
    payload["default_language"] = "en"
    payload["title_translations"] = {"fr": "Quiz bilingue"}
    payload["questions"][0]["translations"] = {"fr": "<p>Quelle est la reponse ?</p>"}
    payload["questions"][0]["options"][0]["translations"] = {"fr": "Bonne reponse"}
    payload["questions"][0]["options"][1]["translations"] = {"fr": "Mauvaise reponse"}
    quiz = create_quiz(client, payload)
    assert "fr" in quiz["languages"]
    assert quiz["is_multilingual"] is True

    state = create_session(client, quiz["id"], language="fr")["state"]
    assert state["session"]["language"] == "fr"
    assert "Quelle est la reponse" in state["question"]["text_html"]
    # Options are shuffled per session, so look the text up rather than trusting a position.
    assert "Bonne reponse" in [option["text"] for option in state["question"]["options"]]

    english = create_session(client, quiz["id"], language="en")["state"]
    assert "What is the answer" in english["question"]["text_html"]


def test_invalid_language_falls_back_to_the_default(client):
    register_user(client)
    quiz = create_quiz(client)
    response = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "solo", "language": "xx"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422  # rejected by the schema


def test_question_translations_are_sanitised(client):
    register_user(client)
    payload = quiz_payload()
    payload["questions"][0]["translations"] = {"fr": "<p>Bonjour</p><script>alert(1)</script>"}
    quiz = create_quiz(client, payload)
    translated = quiz["questions"][0]["translations"]["fr"]
    assert "<script" not in translated


# ---------------------------------------------------------------------------
# Timer safety net
# ---------------------------------------------------------------------------
def test_expired_question_is_revealed_when_the_state_is_read(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_session(client, quiz["id"])
    code = created["session"]["code"]
    assert created["state"]["session"]["phase"] == "question"

    # Simulate a lost timer task: the deadline is in the past but the phase
    # was never switched by the background task.
    with SessionLocal() as db:
        session = db.query(GameSession).filter(GameSession.code == code).one()
        session.question_deadline = utcnow() - timedelta(seconds=5)
        session.phase = "question"
        db.commit()

    state = client.get(
        f"/api/v1/sessions/{code}/state", headers={"X-Participant-Token": created["participant"]["token"]}
    ).json()
    assert state["session"]["phase"] == "reveal"
    assert state["reveal"] is not None
    assert state["reveal"]["correct_option_ids"]


def test_answering_after_the_deadline_is_refused(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_session(client, quiz["id"])
    code = created["session"]["code"]
    question_id = created["state"]["question"]["id"]
    option_id = created["state"]["question"]["options"][0]["id"]

    with SessionLocal() as db:
        session = db.query(GameSession).filter(GameSession.code == code).one()
        session.question_deadline = utcnow() - timedelta(seconds=1)
        db.commit()

    response = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question_id, "option_ids": [option_id]},
        headers={
            **csrf_headers(client),
            "X-Participant-Token": created["participant"]["token"],
        },
    )
    assert response.status_code == 409
    # The session is not stuck: the state now shows the reveal.
    state = client.get(
        f"/api/v1/sessions/{code}/state", headers={"X-Participant-Token": created["participant"]["token"]}
    ).json()
    assert state["session"]["phase"] == "reveal"


def test_an_untimed_quiz_accepts_an_answer(client):
    """No clock means no deadline, and no deadline must never read as expired.

    `remaining_ms()` answers 0 when the session has none, so the submission guard
    used to reject every answer with "Time is up for this question."
    """
    register_user(client)
    payload = quiz_payload("No clock", questions=[question_payload()])
    payload["timer_mode"] = "none"
    quiz = create_quiz(client, payload)
    assert quiz["timer_mode"] == "none"

    created = create_session(client, quiz["id"])
    code = created["session"]["code"]
    question = created["state"]["question"]
    assert question["deadline"] is None
    assert question["remaining_ms"] == 0

    response = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [question["options"][0]["id"]]},
        headers={**csrf_headers(client), "X-Participant-Token": created["participant"]["token"]},
    )
    assert response.status_code in (200, 201), response.text
    state = client.get(
        f"/api/v1/sessions/{code}/state",
        headers={"X-Participant-Token": created["participant"]["token"]},
    ).json()
    assert state["reveal"] is not None


# ---------------------------------------------------------------------------
# Recycled ids
# ---------------------------------------------------------------------------
def test_a_new_quiz_never_inherits_the_options_of_a_deleted_one(client):
    """A raw delete leaves options behind; SQLite then recycles the question id.

    That is how a brand-new quiz ends up with a dead quiz's answer key: the
    right answer scores zero because the scoring compares against ghosts.
    """
    register_user(client)
    ghost = create_quiz(
        client,
        quiz_payload(
            "Ghost source",
            questions=[question_payload("Old question", options=[("Ghost A", True), ("Ghost B", False)])],
        ),
    )
    with SessionLocal() as db:
        # Delete the parents only, exactly like a hand-written maintenance script
        # that forgets the children.
        db.execute(text("delete from questions where quiz_id = :qid"), {"qid": ghost["id"]})
        db.execute(text("delete from quizzes where id = :qid"), {"qid": ghost["id"]})
        db.commit()

    fresh = create_quiz(client, quiz_payload("Fresh quiz", questions=[question_payload("New question")]))
    options = [option["text"] for option in fresh["questions"][0]["options"]]
    assert options == ["Correct answer", "Wrong answer"]
    assert fresh["questions"][0]["options"][0]["is_correct"] is True


def test_purging_orphans_removes_children_of_a_missing_parent(client, tmp_path):
    from sqlalchemy import create_engine

    from app.migrate import purge_orphans

    engine = create_engine(f"sqlite:///{tmp_path / 'orphans.db'}")
    with engine.begin() as connection:
        connection.execute(text("create table quizzes (id integer primary key)"))
        connection.execute(text("create table questions (id integer primary key, quiz_id integer)"))
        connection.execute(text("create table options (id integer primary key, question_id integer)"))
        connection.execute(text("insert into quizzes (id) values (1)"))
        connection.execute(text("insert into questions (id, quiz_id) values (1, 1), (2, 99)"))
        connection.execute(text("insert into options (id, question_id) values (1, 1), (2, 2)"))
    purge_orphans(engine)
    with engine.begin() as connection:
        assert [row[0] for row in connection.execute(text("select id from questions"))] == [1]
        assert [row[0] for row in connection.execute(text("select id from options"))] == [1]


# ---------------------------------------------------------------------------
# Quiz timers
# ---------------------------------------------------------------------------
def timed_quiz(client, mode: str, *, budget: int = 0, limit: int = 30, count: int = 2) -> dict:
    payload = quiz_payload(
        f"Timed quiz ({mode})",
        questions=[question_payload(f"Question {index}", time_limit=limit) for index in range(count)],
    )
    payload["timer_mode"] = mode
    payload["global_time_limit_seconds"] = budget
    return create_quiz(client, payload)


def advance(client, created: dict, index: int) -> dict:
    """Move the session to another question, the way the host's next button does."""
    from app.game import start_question

    with SessionLocal() as db:
        session = db.query(GameSession).filter(GameSession.code == created["session"]["code"]).one()
        start_question(db, session, index)
    return client.get(
        f"/api/v1/sessions/{created['session']['code']}/state",
        headers={"X-Participant-Token": created["participant"]["token"]},
    ).json()


def test_a_quiz_can_run_without_any_clock(client):
    register_user(client)
    quiz = timed_quiz(client, "none")
    state = create_session(client, quiz["id"])["state"]
    assert state["session"]["timer_mode"] == "none"
    assert state["question"]["deadline"] is None
    assert state["question"]["remaining_ms"] == 0
    assert state["session"]["run_deadline"] is None
    assert state["session"]["run_remaining_ms"] is None


def test_per_question_mode_restarts_the_clock_on_the_next_question(client):
    register_user(client)
    quiz = timed_quiz(client, "per_question", limit=30)
    created = create_session(client, quiz["id"])
    first = datetime.fromisoformat(created["state"]["question"]["deadline"])
    second = datetime.fromisoformat(advance(client, created, 1)["question"]["deadline"])
    assert first > utcnow()
    assert second > first  # a fresh window, not the previous one
    assert created["state"]["session"]["run_deadline"] is None


def test_global_mode_keeps_one_deadline_for_the_whole_run(client):
    register_user(client)
    quiz = timed_quiz(client, "global", budget=600, limit=30)
    created = create_session(client, quiz["id"])
    run_deadline = created["state"]["session"]["run_deadline"]
    assert run_deadline is not None
    # The run clock replaces the per-question one, it does not shorten it.
    assert created["state"]["question"]["deadline"] == run_deadline
    assert created["state"]["session"]["run_remaining_ms"] > 590_000

    later = advance(client, created, 1)
    assert later["session"]["run_deadline"] == run_deadline
    assert later["question"]["deadline"] == run_deadline


def test_a_global_clock_needs_a_real_budget(client):
    register_user(client)
    payload = quiz_payload("No budget", questions=[question_payload()])
    payload["timer_mode"] = "global"
    payload["global_time_limit_seconds"] = 0
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422
    assert "30 seconds" in response.text


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def test_search_matches_titles_and_description_words(client):
    register_user(client)
    first = create_quiz(client, quiz_payload("Splunk advanced"))
    second = create_quiz(client, quiz_payload("Linux basics", description="Networking and firewall"))
    third = create_quiz(client, quiz_payload("Reseau et pare-feu", description="Routage"))
    for quiz in (first, second, third):
        publish_quiz(client, quiz["id"])

    splunk = client.get("/api/v1/quizzes", params={"q": "splunk"}).json()
    assert [row["title"] for row in splunk] == ["Splunk advanced"]

    desc = client.get("/api/v1/quizzes", params={"q": "firewall"}).json()
    assert [row["title"] for row in desc] == ["Linux basics"]

    # Prefix search, and diacritics folding.
    prefix = client.get("/api/v1/quizzes", params={"q": "splu"}).json()
    assert [row["title"] for row in prefix] == ["Splunk advanced"]
    folded = client.get("/api/v1/quizzes", params={"q": "reseau"}).json()
    assert [row["title"] for row in folded] == ["Reseau et pare-feu"]

    assert client.get("/api/v1/quizzes", params={"q": "nothing-matches"}).json() == []
    # Search input is treated as data, never as an FTS expression.
    assert client.get("/api/v1/quizzes", params={"q": 'x" OR "y'}).status_code == 200


def test_search_index_stays_exact_after_edits_and_deletions(client):
    """The index must never match a quiz whose text it no longer holds."""
    register_user(client)
    keep = create_quiz(client, quiz_payload("Splunk advanced", description="Search commands"))
    gone = create_quiz(client, quiz_payload("Kubernetes basics", description="Pods and services"))
    publish_quiz(client, keep["id"])
    publish_quiz(client, gone["id"])

    # Renaming a quiz must remove the old words from the index.
    renamed = quiz_payload("Splunk expert", description="Search commands")
    renamed["questions"] = [question_payload()]
    response = client.put(
        f"/api/v1/quizzes/{keep['id']}", json=renamed, headers=csrf_headers(client)
    )
    assert response.status_code in (200, 204), response.text

    # A rename only touches the working copy: the live version still owns the
    # public index, so neither the old nor the new wording leaks from the draft.
    assert [row["title"] for row in client.get("/api/v1/quizzes", params={"q": "advanced"}).json()] == [
        "Splunk advanced"
    ]
    assert client.get("/api/v1/quizzes", params={"q": "expert"}).json() == []

    # Deleting one quiz must not shift the other one's indexed row id.
    assert client.delete(
        f"/api/v1/quizzes/{gone['id']}", headers=csrf_headers(client)
    ).status_code in (200, 204)
    hits = client.get("/api/v1/quizzes", params={"q": "splunk"}).json()
    assert [row["title"] for row in hits] == ["Splunk advanced"]
    assert client.get("/api/v1/quizzes", params={"q": "kubernetes"}).json() == []
