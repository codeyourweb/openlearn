# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The rules that keep a run and a sign-in honest.

Three properties are checked here, each one because it was found broken:

* an attempt ceiling is about the candidate, not about the way of playing, so a
  live session cannot buy a free extra run;
* a sign-in answers in the same time whether or not the address has an account;
* a lock is only announced to someone who typed the right password, so nobody
  can lock a stranger out by guessing an address.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app import security
from app.db import SessionLocal
from app.models import User
from app.routers import auth as auth_module
from tests.conftest import DEFAULT_PASSWORD, csrf_headers, login_user, register_user

from .test_assessment import _publish, _quiz


def test_a_live_session_is_not_a_second_free_run(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=1)
    _publish(client, quiz["id"])

    register_user(client, "candidate@example.com", display_name="Candidate")
    first = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert first.status_code == 201, first.text

    # The same candidate, the same questionnaire, another way of playing: the
    # ceiling has to hold, otherwise it only forbids the honest path.
    second = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "live", "play_as_host": True},
        headers=csrf_headers(client),
    )
    assert second.status_code == 409, second.text
    assert "already taken" in second.json()["detail"].lower()


def test_a_host_who_only_presents_keeps_a_full_allowance(client):
    """Presenting a session is not taking it: a teacher must be able to host.

    Otherwise a trainer with a one-run questionnaire could never run it in front
    of a class, because hosting would be counted as an attempt.
    """
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=1)
    _publish(client, quiz["id"])

    register_user(client, "candidate@example.com", display_name="Candidate")
    assert (
        client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client)).status_code
        == 201
    )

    register_user(client, "teacher@example.com", display_name="Teacher")
    hosting = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "live"}, headers=csrf_headers(client))
    assert hosting.status_code == 201, hosting.text


def test_an_unknown_address_is_verified_against_a_dummy_hash(client, monkeypatch):
    """Without an account the hash must still be computed.

    The timing difference was the bug; the observable proxy here is that
    ``verify_password`` is reached at all, which is what costs the time.
    """
    register_user(client, "known@example.com")
    seen: list[str] = []
    real = auth_module.verify_password

    def spy(password: str, password_hash: str) -> bool:
        seen.append(password_hash)
        return real(password, password_hash)

    monkeypatch.setattr(auth_module, "verify_password", spy)

    assert login_user(client, "nobody@example.com", "WrongPassword1").status_code == 401
    assert seen == [security.DUMMY_PASSWORD_HASH]

    seen.clear()
    assert login_user(client, "known@example.com", "WrongPassword1").status_code == 401
    assert seen and seen[0] != security.DUMMY_PASSWORD_HASH


def test_the_dummy_hash_is_a_real_argon2_hash(client):
    """A malformed placeholder would fail fast and defeat its own purpose."""
    assert security.DUMMY_PASSWORD_HASH.startswith("$argon2id$")
    assert security.verify_password("anything", security.DUMMY_PASSWORD_HASH) is False
    assert security.hash_to_compare(False, "$argon2id$whatever") == security.DUMMY_PASSWORD_HASH
    assert security.hash_to_compare(True, "$argon2id$whatever") == "$argon2id$whatever"


def _locked_user(email: str) -> User:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.email == email))


def _lock(client, email: str) -> None:
    for _ in range(5):
        assert login_user(client, email, "WrongPassword1").status_code == 401
    assert _locked_user(email).locked_until is not None


def test_a_wrong_password_on_a_locked_account_still_answers_401(client):
    """423 before the password check revealed the account and allowed a lockout."""
    register_user(client, "victim@example.com")
    _lock(client, "victim@example.com")

    response = login_user(client, "victim@example.com", "WrongPassword1")
    assert response.status_code == 401, response.text
    assert "locked" not in response.text.lower()


def test_the_right_password_learns_that_the_account_is_locked(client):
    register_user(client, "victim@example.com")
    _lock(client, "victim@example.com")

    response = login_user(client, "victim@example.com", DEFAULT_PASSWORD)
    assert response.status_code == 423, response.text

    # And the lock does expire.
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "victim@example.com"))
        user.locked_until = user.locked_until - timedelta(days=1)
        db.add(user)
        db.commit()
    assert login_user(client, "victim@example.com", DEFAULT_PASSWORD).status_code == 200
