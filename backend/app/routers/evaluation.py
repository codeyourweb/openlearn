# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Assessment mode: one run per candidate, and the author's result book.

A questionnaire can be used to *evaluate* people rather than to entertain a
room. Two things are needed for that, and they live here:

* a ceiling on the number of runs one signed-in candidate may take — counted
  from the sessions themselves, so nothing in the history is ever rewritten,
  and raised one run at a time by an explicit grant from the author;
* a private link that opens the questionnaire to candidates who hold it, plus
  the author's view of every attempt: who, when, what score, and which answers.

Live sessions and deferred (solo) runs share the same rows, so a candidate who
played in a room and later retried from the link is counted once per attempt.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..deps import enforce_rate_limit, external_base_url, get_optional_user, require_user, verify_csrf
from ..evaluation import (
    ensure_attempt_left,
    grants_given,
    remaining_attempts,
)
from ..game import create_session
from ..models import (
    Answer,
    GameSession,
    Participant,
    Question,
    Quiz,
    QuizAttemptGrant,
    SessionQuestion,
    User,
)
from ..schemas import AttemptPolicyIn, SessionCreateIn

router = APIRouter(prefix="/api/v1", tags=["assessment"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _owner_quiz(db: OrmSession, quiz_id: int, user: User) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if quiz.owner_id != user.id and not user.is_staff:
        raise HTTPException(status_code=403, detail="Only the author can read these results.")
    return quiz


def _max_score(db: OrmSession, session: GameSession) -> int:
    return db.scalar(select(func.coalesce(func.sum(SessionQuestion.points), 0)).where(SessionQuestion.session_id == session.id)) or 0


def _answered(db: OrmSession, participant_id: int) -> int:
    return db.scalar(select(func.count(Answer.id)).where(Answer.participant_id == participant_id)) or 0


def _user_label(user: User | None, nickname: str) -> str:
    if user is None:
        return nickname
    return user.display_name or user.email


# ---------------------------------------------------------------------------
# Private evaluation link
# ---------------------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/share", summary="Create or rotate the private evaluation link")
def create_share_link(quiz_id: int, request: Request, db: OrmSession = Depends(get_db), user: User = Depends(require_user)):
    verify_csrf(request)
    quiz = _owner_quiz(db, quiz_id, user)
    if not quiz.share_token:
        quiz.share_token = secrets.token_urlsafe(18)
        db.commit()
    base = external_base_url(request)
    return {"token": quiz.share_token, "url": f"{base}/e/{quiz.share_token}"}


@router.delete("/quizzes/{quiz_id}/share", summary="Revoke the private evaluation link")
def revoke_share_link(quiz_id: int, request: Request, db: OrmSession = Depends(get_db), user: User = Depends(require_user)):
    verify_csrf(request)
    quiz = _owner_quiz(db, quiz_id, user)
    quiz.share_token = None
    db.commit()
    return {"token": None, "url": None}


def _quiz_by_token(db: OrmSession, token: str) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.share_token == token.strip()))
    if quiz is None:
        raise HTTPException(status_code=404, detail="This evaluation link is not valid any more.")
    if quiz.mode not in ("qcm", "swipe", "poll"):
        raise HTTPException(status_code=422, detail="Only multiple choice, swipe and poll questionnaires can be shared.")
    return quiz


@router.get("/eval/{token}", summary="What a candidate sees before starting")
def eval_overview(token: str, db: OrmSession = Depends(get_db), user: User | None = Depends(get_optional_user)):
    quiz = _quiz_by_token(db, token)
    questions = db.scalar(select(func.count(Question.id)).where(Question.quiz_id == quiz.id)) or 0
    remaining = remaining_attempts(db, quiz, user.id) if user is not None else None
    return {
        "title": quiz.title,
        "description": quiz.description or "",
        "mode": quiz.mode,
        "question_count": questions,
        "max_attempts": quiz.max_attempts,
        "signed_in": user is not None,
        "remaining_attempts": remaining,
        "can_start": bool(questions) and (remaining is None or remaining > 0),
        "owner": "",
    }


@router.post("/eval/{token}/sessions", status_code=status.HTTP_201_CREATED, summary="Start a deferred run")
async def eval_start(
    token: str,
    payload: SessionCreateIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    verify_csrf(request)
    enforce_rate_limit(request, "join", 20, 60)
    quiz = _quiz_by_token(db, token)
    ensure_attempt_left(db, quiz, user)
    session, host_token, join_url, participant, participant_token = create_session(
        db,
        quiz=quiz,
        user=user,
        mode="solo",
        nickname=payload.nickname,
        base_url=external_base_url(request),
        language=payload.language,
    )
    return {
        "session": {
            "id": session.id,
            "code": session.code,
            "quiz_title": session.quiz_title,
            "status": session.status,
            "phase": session.phase,
            "is_solo": session.is_solo,
        },
        "host_token": host_token,
        "join_url": join_url,
        "participant": (
            {"id": participant.id, "nickname": participant.nickname, "token": participant_token}
            if participant
            else None
        ),
        "remaining_attempts": remaining_attempts(db, quiz, user.id),
    }


# ---------------------------------------------------------------------------
# The author's result book
# ---------------------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/attempts-policy", summary="Set how many runs a candidate gets")
def set_attempt_policy(
    quiz_id: int,
    payload: AttemptPolicyIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    verify_csrf(request)
    quiz = _owner_quiz(db, quiz_id, user)
    if quiz.mode == "adventure":
        raise HTTPException(status_code=422, detail="A story is not an assessment.")
    quiz.max_attempts = payload.max_attempts
    db.commit()
    return {"max_attempts": quiz.max_attempts}


@router.get("/quizzes/{quiz_id}/attempts", summary="Every attempt on a questionnaire")
def list_attempts(
    quiz_id: int,
    limit: int = 100,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    quiz = _owner_quiz(db, quiz_id, user)
    rows = db.execute(
        select(GameSession, Participant, User)
        .join(Participant, Participant.session_id == GameSession.id)
        .outerjoin(User, User.id == Participant.user_id)
        .where(
            GameSession.quiz_id == quiz.id,
            or_(Participant.is_host.is_(False), GameSession.is_solo.is_(True)),
        )
        .order_by(GameSession.created_at.desc())
        .limit(max(1, min(limit, 300)))
    ).all()

    attempts = []
    totals: dict[str, dict] = {}
    for session, participant, owner in rows:
        max_score = _max_score(db, session)
        entry = {
            "participant_id": participant.id,
            "session_code": session.code,
            "session_id": session.id,
            "mode": "solo" if session.is_solo else "live",
            "status": session.status,
            "user_id": participant.user_id,
            "candidate": _user_label(owner, participant.nickname),
            "nickname": participant.nickname,
            "email": owner.email if owner else "",
            "score": participant.score,
            "max_score": max_score,
            "answered": _answered(db, participant.id),
            "started_at": session.started_at or session.created_at,
            "finished_at": session.finished_at,
        }
        attempts.append(entry)
        key = str(participant.user_id or f"guest-{participant.id}")
        bucket = totals.setdefault(
            key,
            {
                "candidate": entry["candidate"],
                "email": entry["email"],
                "user_id": entry["user_id"],
                "runs": 0,
                "best_score": 0,
                "max_score": max_score,
                "last_at": entry["started_at"],
                "last_participant_id": participant.id,
            },
        )
        bucket["runs"] += 1
        bucket["best_score"] = max(bucket["best_score"], entry["score"])
        bucket["max_score"] = max(bucket["max_score"], max_score)
        if entry["started_at"] and (bucket["last_at"] is None or entry["started_at"] > bucket["last_at"]):
            bucket["last_at"] = entry["started_at"]
            bucket["last_participant_id"] = participant.id

    candidates = []
    for _key, bucket in totals.items():
        user_id = bucket["user_id"]
        candidates.append(
            {
                **bucket,
                "remaining_attempts": remaining_attempts(db, quiz, user_id) if user_id else None,
                "grants": grants_given(db, quiz.id, user_id) if user_id else 0,
            }
        )
    candidates.sort(key=lambda item: (-item["best_score"], item["candidate"].lower()))
    return {
        "quiz": {
            "id": quiz.id,
            "title": quiz.title,
            "mode": quiz.mode,
            "max_attempts": quiz.max_attempts,
            "share_token": quiz.share_token,
        },
        "candidates": candidates,
        "attempts": attempts,
    }


@router.get("/quizzes/{quiz_id}/attempts/{participant_id}", summary="One attempt, question by question")
def attempt_detail(
    quiz_id: int,
    participant_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    quiz = _owner_quiz(db, quiz_id, user)
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    session = db.get(GameSession, participant.session_id)
    if session is None or session.quiz_id != quiz.id:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    reveal = session.status == "finished" or session.phase in ("reveal", "results")
    candidate = db.get(User, participant.user_id) if participant.user_id else None

    items = []
    questions = db.scalars(
        select(SessionQuestion).where(SessionQuestion.session_id == session.id).order_by(SessionQuestion.position)
    ).all()
    answers = {
        answer.session_question_id: answer
        for answer in db.scalars(select(Answer).where(Answer.participant_id == participant.id)).all()
    }
    for question in questions:
        answer = answers.get(question.id)
        chosen: list[str] = []
        if answer is not None:
            from ..models import SessionOption  # local import: only this view needs it

            selected = set(answer.selected or [])
            for option in db.scalars(select(SessionOption).where(SessionOption.session_question_id == question.id)).all():
                if option.position in selected:
                    chosen.append(option.text)
        items.append(
            {
                "position": question.position + 1,
                "question": question.text_html,
                "answer": chosen,
                "answered": answer is not None,
                "is_correct": bool(answer.is_correct) if (answer is not None and reveal) else None,
                "points": answer.points_awarded if answer is not None else 0,
                "response_ms": answer.response_ms if answer is not None else None,
            }
        )
    return {
        "participant": {
            "id": participant.id,
            "candidate": _user_label(candidate, participant.nickname),
            "email": candidate.email if candidate else "",
            "score": participant.score,
            "max_score": _max_score(db, session),
            "mode": "solo" if session.is_solo else "live",
            "status": session.status,
            "started_at": session.started_at or session.created_at,
            "finished_at": session.finished_at,
            "session_code": session.code,
        },
        "items": items,
        "reveal": reveal,
    }


@router.post("/quizzes/{quiz_id}/attempts/{user_id}/grant", summary="Allow one more run")
def grant_attempt(
    quiz_id: int,
    user_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    verify_csrf(request)
    quiz = _owner_quiz(db, quiz_id, user)
    if not quiz.max_attempts:
        raise HTTPException(status_code=422, detail="This questionnaire has no attempt limit.")
    candidate = db.get(User, user_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    db.add(QuizAttemptGrant(quiz_id=quiz.id, user_id=user_id, granted_by=user.id))
    db.commit()
    return {"remaining_attempts": remaining_attempts(db, quiz, user_id), "grants": grants_given(db, quiz.id, user_id)}


@router.delete("/quizzes/{quiz_id}/attempts/{user_id}/grant", summary="Take back the last extra run")
def revoke_grant(
    quiz_id: int,
    user_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    verify_csrf(request)
    quiz = _owner_quiz(db, quiz_id, user)
    grant = db.scalars(
        select(QuizAttemptGrant)
        .where(QuizAttemptGrant.quiz_id == quiz.id, QuizAttemptGrant.user_id == user_id)
        .order_by(QuizAttemptGrant.id.desc())
    ).first()
    if grant is None:
        raise HTTPException(status_code=404, detail="No grant to take back.")
    db.delete(grant)
    db.commit()
    return {"remaining_attempts": remaining_attempts(db, quiz, user_id), "grants": grants_given(db, quiz.id, user_id)}
