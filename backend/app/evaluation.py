# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Attempt quotas for a questionnaire used as an assessment.

A ceiling is counted from the sessions themselves, so nothing in the history is
ever rewritten: an attempt is a participant row on a session that left the
lobby. Extra runs are explicit grant rows, one per run, which keeps the reason
for every allowance auditable.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from .models import GameSession, Participant, Quiz, QuizAttemptGrant, User


# ---------------------------------------------------------------------------
# Quotas
# ---------------------------------------------------------------------------
def attempts_used(db: OrmSession, quiz_id: int, user_id: int) -> int:
    """Runs this candidate already started on this questionnaire.

    A run counts as soon as it leaves the lobby: an abandoned solo session is
    still an attempt, otherwise refreshing the page would give a free retry.
    """
    return (
        db.scalar(
            select(func.count(Participant.id))
            .join(GameSession, GameSession.id == Participant.session_id)
            .where(
                GameSession.quiz_id == quiz_id,
                Participant.user_id == user_id,
                # In a live session the host presents; in a deferred run the
                # player is technically the host of their own session and is
                # the candidate we are counting.
                or_(Participant.is_host.is_(False), GameSession.is_solo.is_(True)),
                GameSession.status.in_(("active", "finished")),
            )
        )
        or 0
    )


def grants_given(db: OrmSession, quiz_id: int, user_id: int) -> int:
    return (
        db.scalar(
            select(func.count(QuizAttemptGrant.id)).where(
                QuizAttemptGrant.quiz_id == quiz_id, QuizAttemptGrant.user_id == user_id
            )
        )
        or 0
    )


def allowed_attempts(db: OrmSession, quiz: Quiz, user_id: int) -> int:
    """Total runs, or 0 when the questionnaire sets no ceiling."""
    if not quiz.max_attempts:
        return 0
    return quiz.max_attempts + grants_given(db, quiz.id, user_id)


def remaining_attempts(db: OrmSession, quiz: Quiz, user_id: int) -> int | None:
    total = allowed_attempts(db, quiz, user_id)
    if not total:
        return None
    return max(total - attempts_used(db, quiz.id, user_id), 0)


def ensure_attempt_left(db: OrmSession, quiz: Quiz, user: User | None, *, session: GameSession | None = None) -> None:
    """Refuse a run that would exceed the candidate's ceiling.

    Unauthenticated players cannot be counted, so a quiz with a ceiling can
    only be played signed in — that is what makes the rule enforceable.
    """
    if not quiz.max_attempts:
        return
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This questionnaire is limited to one run per candidate: sign in to take it.",
        )
    total = allowed_attempts(db, quiz, user.id)
    used = attempts_used(db, quiz.id, user.id)
    if session is not None and session.quiz_id == quiz.id and session.status in ("active", "finished"):
        # The session being joined is itself one of the counted attempts only
        # once it leaves the lobby; joining it must not count twice.
        pass
    if used >= total:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already taken this questionnaire; ask its author for another attempt.",
        )


