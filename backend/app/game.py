# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Game session domain logic (shared by the HTTP API and the WebSocket layer)."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .models import (
    Answer,
    GameSession,
    Participant,
    Quiz,
    SessionOption,
    SessionQuestion,
    User,
    utcnow,
)
from .realtime import manager
from .scoring import is_answer_correct, points_for
from .security import sha256

logger = logging.getLogger("openlearn.game")

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6

_timers: dict[str, asyncio.Task[None]] = {}


def aware(value: datetime | None) -> datetime | None:
    """SQLite drops timezone information; treat stored values as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def remaining_ms(session: GameSession) -> int:
    deadline = aware(session.question_deadline)
    if deadline is None:
        return 0
    return max(0, int((deadline - utcnow()).total_seconds() * 1000))


def run_remaining_ms(session: GameSession) -> int | None:
    """Milliseconds left on a "global" timer, None when the mode has no global clock."""
    if (session.timer_mode or "per_question") != "global":
        return None
    deadline = aware(session.run_deadline)
    if deadline is None:
        return None
    return max(0, int((deadline - utcnow()).total_seconds() * 1000))


def generate_code(db: OrmSession) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if db.scalar(select(GameSession.id).where(GameSession.code == code)) is None:
            return code
    raise HTTPException(status_code=503, detail="Could not allocate a session code, please retry.")


# ---------------------------------------------------------------------------
# Creation / join
# ---------------------------------------------------------------------------
def create_session(
    db: OrmSession,
    *,
    quiz: Quiz,
    user: User | None,
    mode: str,
    nickname: str | None = None,
    base_url: str = "",
    language: str | None = None,
    play_as_host: bool = False,
) -> tuple[GameSession, str, str, Participant | None, str | None]:
    """Create a lobby (``live``) or an immediately started solo session.

    The quiz is snapshotted in the requested language so a running game is
    immune to later edits and fully server-side.

    Returns ``(session, host_token, join_url, participant, participant_token)``.
    """
    import random

    from . import versions as version_store
    from .content import resolve_text, valid_language

    language = language if valid_language(language) else (quiz.default_language or "en")

    # A published quiz is played from its live version, never from a draft.
    published = version_store.published_payload(db, quiz)
    if published is not None:
        playable = []
        for question in version_store.payload_questions(published):
            wrapped_question = version_store.resolved_question(question, language)
            playable.append(
                {
                    "id": question["id"],
                    # The snapshot keeps the authored wording and every language
                    # beside it: the player resolves the one its reader asks for,
                    # so changing language mid-run needs no new session.
                    "text_html": resolve_text(wrapped_question, None, "text", "text_html"),
                    "translations": dict(question.get("translations") or {}),
                    "image_path": question["image_path"],
                    "time_limit_seconds": question["time_limit_seconds"],
                    "points": question["points"],
                    "multiple": bool(question.get("multiple")),
                    "options": [
                        {
                            "id": option["id"],
                            "text": resolve_text(version_store.resolved_option(option, None), None),
                            "translations": dict(option.get("translations") or {}),
                            "is_correct": option["is_correct"],
                        }
                        for option in question["options"]
                    ],
                }
            )
        source_title = published.get("title") or quiz.title
        source_policy = published.get("wrong_answer_policy") or quiz.wrong_answer_policy
        source_timer_mode = published.get("timer_mode") or quiz.timer_mode
        source_global_limit = int(published.get("global_time_limit_seconds") or 0)
        if not source_global_limit:
            source_global_limit = quiz.global_time_limit_seconds
    else:
        playable = [
            {
                "id": question.id,
                "text_html": question.text_html,
                "translations": dict(question.text_translations or {}),
                "image_path": question.image_path,
                "time_limit_seconds": question.time_limit_seconds,
                "points": question.points,
                "multiple": bool(question.multiple_answers),
                "options": [
                    {
                        "id": option.id,
                        "text": option.text,
                        "translations": dict(option.text_translations or {}),
                        "is_correct": option.is_correct,
                    }
                    for option in question.options
                ],
            }
            for question in quiz.questions
        ]
        source_title = quiz.title
        source_policy = quiz.wrong_answer_policy
        source_timer_mode = quiz.timer_mode
        source_global_limit = quiz.global_time_limit_seconds

    if not playable:
        raise HTTPException(status_code=400, detail="This quiz has no question yet.")

    # Every participant of a session sees the same order, but the order is
    # shuffled per session so a quiz is not always presented the same way.
    # Stories keep their authored graph order.
    if quiz.mode in ("qcm", "swipe", "poll"):
        random.shuffle(playable)
        if quiz.mode in ("qcm", "poll"):
            # Swipe keeps the authored option order: the card's left and right
            # gestures are bound to "no" and "yes", not to a position.
            for question in playable:
                random.shuffle(question["options"])
    host_token = secrets.token_urlsafe(32)
    join_token = secrets.token_urlsafe(24)
    session = GameSession(
        code=generate_code(db),
        join_token=join_token,
        quiz_id=quiz.id,
        host_user_id=user.id if user else None,
        host_token_hash=sha256(host_token),
        quiz_title=source_title,
        quiz_mode=quiz.mode,
        language=language,
        wrong_answer_policy=source_policy,
        timer_mode=source_timer_mode or "per_question",
        global_time_limit_seconds=int(source_global_limit or 0),
        status="lobby",
        is_solo=mode == "solo",
        phase="idle",
        current_index=-1,
    )
    for q_index, question in enumerate(playable):
        snapshot_question = SessionQuestion(
            position=q_index,
            source_question_id=question["id"],
            text_html=question["text_html"],
            text_translations=question.get("translations") or {},
            image_path=question["image_path"],
            time_limit_seconds=question["time_limit_seconds"],
            points=question["points"],
            allow_multiple=bool(question.get("multiple")),
        )
        for o_index, option in enumerate(question["options"]):
            snapshot_question.options.append(
                SessionOption(
                    position=o_index,
                    source_option_id=option["id"],
                    text=option["text"],
                    text_translations=option.get("translations") or {},
                    is_correct=option["is_correct"],
                )
            )
        session.questions.append(snapshot_question)

    db.add(session)
    db.flush()

    participant: Participant | None = None
    participant_token: str | None = None
    wants_to_play = mode == "solo" or (mode == "live" and play_as_host)
    if wants_to_play:
        participant_token = secrets.token_urlsafe(32)
        participant = Participant(
            session_id=session.id,
            user_id=user.id if user else None,
            nickname=(nickname or (user.display_name if user else "Solo player"))[:30],
            token_hash=sha256(participant_token),
            is_host=True,
        )
        db.add(participant)
        db.flush()
        if mode == "solo":
            start_question(db, session, 0)

    db.commit()
    db.refresh(session)
    join_url = f"{base_url.rstrip('/')}/join/{join_token}" if base_url else f"/join/{join_token}"
    return session, host_token, join_url, participant, participant_token


def join_session(db: OrmSession, session: GameSession, nickname: str, user: User | None) -> tuple[Participant, str]:
    if session.is_solo:
        raise HTTPException(status_code=403, detail="This is a solo session.")
    if session.status != "lobby":
        raise HTTPException(status_code=409, detail="This quiz has already started; joining is closed.")
    count = db.scalar(select(func.count(Participant.id)).where(Participant.session_id == session.id)) or 0
    from .config import settings

    if count >= settings.max_participants_per_session:
        raise HTTPException(status_code=409, detail="This session is full.")

    token = secrets.token_urlsafe(32)
    participant = Participant(
        session_id=session.id,
        user_id=user.id if user else None,
        nickname=nickname,
        token_hash=sha256(token),
        is_host=False,
    )
    db.add(participant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This nickname is already taken in this session.") from None
    db.refresh(participant)
    return participant, token


def participant_from_token(db: OrmSession, session: GameSession, token: str | None) -> Participant | None:
    if not token:
        return None
    return db.scalar(
        select(Participant).where(
            Participant.session_id == session.id,
            Participant.token_hash == sha256(token),
        )
    )


def is_host_authorized(db: OrmSession, session: GameSession, user: User | None, host_token: str | None) -> bool:
    if host_token and session.host_token_hash and secrets.compare_digest(sha256(host_token), session.host_token_hash):
        return True
    if user is None:
        return False
    if session.host_user_id == user.id:
        return True
    # The quiz owner can always drive a session built from their quiz.
    if session.quiz_id is not None:
        owner_id = db.scalar(select(Quiz.owner_id).where(Quiz.id == session.quiz_id))
        if owner_id == user.id:
            return True
    return False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def _question_deadline(
    session: GameSession, question: SessionQuestion, now: datetime, *, first: bool
) -> datetime | None:
    """Deadline for the question that just started.

    "none" never sets one, "global" clamps every question to the run deadline
    (its own limit only bounds the single answer window), "per_question" uses
    the question's own limit.
    """
    mode = session.timer_mode or "per_question"
    if mode == "none":
        return None
    if mode == "global":
        # One clock for the whole run: it is set once, on the first question, and
        # every later question inherits the same instant. Per-question limits are
        # deliberately ignored here, otherwise a 3-minute run of 30-second
        # questions could never reach its own budget.
        if session.run_deadline is None:
            budget = int(session.global_time_limit_seconds or 0)
            session.run_deadline = now + timedelta(seconds=budget) if budget > 0 else None
        return session.run_deadline
    return now + timedelta(seconds=question.time_limit_seconds)


def start_question(db: OrmSession, session: GameSession, index: int) -> SessionQuestion:
    questions = list(session.questions)
    if index < 0 or index >= len(questions):
        raise HTTPException(status_code=400, detail="Question index out of range.")
    question = questions[index]
    now = utcnow()
    session.status = "active"
    session.phase = "question"
    session.current_index = index
    session.question_started_at = now
    session.question_deadline = _question_deadline(session, question, now, first=index == 0)
    if session.started_at is None:
        session.started_at = now
    db.add(session)
    db.commit()
    return question


def start_session(db: OrmSession, session: GameSession) -> None:
    if session.status != "lobby":
        raise HTTPException(status_code=409, detail="This session cannot be started.")
    participants = db.scalar(
        select(func.count(Participant.id)).where(Participant.session_id == session.id)
    ) or 0
    if participants == 0:
        raise HTTPException(status_code=409, detail="At least one participant must join before starting.")
    start_question(db, session, 0)


def current_question(session: GameSession) -> SessionQuestion | None:
    if 0 <= session.current_index < len(session.questions):
        return session.questions[session.current_index]
    return None


def reveal_question(db: OrmSession, session: GameSession, *, force: bool = False) -> bool:
    """Move the session to the reveal phase. Returns True when it changed."""
    if session.status != "active" or session.phase != "question":
        return False
    deadline = aware(session.question_deadline)
    if not force and deadline is not None and utcnow() < deadline:
        return False
    session.phase = "reveal"
    db.add(session)
    db.commit()
    cancel_timer(session.code)
    return True


def next_question(db: OrmSession, session: GameSession) -> str:
    if session.status != "active":
        raise HTTPException(status_code=409, detail="This session is not running.")
    if session.phase == "question":
        reveal_question(db, session, force=True)
        return "reveal"
    if session.phase != "reveal":
        raise HTTPException(status_code=409, detail="Nothing to advance.")
    next_index = session.current_index + 1
    if next_index >= len(session.questions):
        finish_session(db, session)
        return "finished"
    start_question(db, session, next_index)
    return "question"


def finish_session(db: OrmSession, session: GameSession) -> None:
    session.status = "finished"
    session.phase = "finished"
    session.finished_at = utcnow()
    session.question_deadline = None
    db.add(session)
    db.commit()
    cancel_timer(session.code)


def cancel_session(db: OrmSession, session: GameSession) -> None:
    session.status = "cancelled"
    session.phase = "finished"
    session.finished_at = utcnow()
    session.question_deadline = None
    db.add(session)
    db.commit()
    cancel_timer(session.code)


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
def submit_answer(
    db: OrmSession,
    session: GameSession,
    participant: Participant,
    question_id: int,
    option_ids: list[int],
) -> Answer:
    if session.status != "active" or session.phase != "question":
        raise HTTPException(status_code=409, detail="Answers are closed.")
    question = current_question(session)
    if question is None or question.id != question_id:
        raise HTTPException(status_code=409, detail="This is not the current question.")
    # An untimed question has no deadline, and `remaining_ms()` answers 0 for
    # that case: testing the number alone locked every answer out of a quiz
    # played without a clock.
    deadline = aware(session.question_deadline)
    if deadline is not None and deadline <= utcnow():
        raise HTTPException(status_code=409, detail="Time is up for this question.")

    existing = db.scalar(
        select(Answer).where(
            Answer.participant_id == participant.id,
            Answer.session_question_id == question.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="You already answered this question.")

    valid_option_ids = {option.id for option in question.options}
    if any(option_id not in valid_option_ids for option_id in option_ids):
        raise HTTPException(status_code=400, detail="Unknown answer option.")

    if session.quiz_mode == "poll":
        # A poll measures opinion, not knowledge: nothing is scored, and the
        # flag stays false so no downstream screen can turn an opinion into a
        # right answer.
        correct = False
        awarded = 0
    else:
        correct_ids = {option.id for option in question.options if option.is_correct}
        correct = is_answer_correct(option_ids, correct_ids)
        awarded = points_for(correct, question.points, session.wrong_answer_policy)

    started = aware(session.question_started_at)
    response_ms = int((utcnow() - started).total_seconds() * 1000) if started else 0

    answer = Answer(
        participant_id=participant.id,
        session_question_id=question.id,
        selected=option_ids,
        is_correct=correct,
        points_awarded=awarded,
        response_ms=response_ms,
    )
    db.add(answer)
    participant.score += awarded
    db.add(participant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already answered this question.") from None
    db.refresh(answer)
    return answer


def all_participants_answered(db: OrmSession, session: GameSession) -> bool:
    question = current_question(session)
    if question is None:
        return False
    total = db.scalar(select(func.count(Participant.id)).where(Participant.session_id == session.id)) or 0
    answered = db.scalar(
        select(func.count(Answer.id)).where(Answer.session_question_id == question.id)
    ) or 0
    return total > 0 and answered >= total


# ---------------------------------------------------------------------------
# State serialisation
# ---------------------------------------------------------------------------
def build_state(db: OrmSession, session: GameSession) -> dict[str, Any]:
    # Safety net: if the background timer task was lost (process restart, test
    # harness, clock jump), reading the state still reveals an expired question
    # instead of leaving players stuck on a closed one.
    if (
        session.phase == "question"
        and session.question_deadline is not None
        and utcnow() >= aware(session.question_deadline)
    ):
        reveal_question(db, session)

    question = current_question(session)
    participants = list(
        db.scalars(
            select(Participant).where(Participant.session_id == session.id).order_by(Participant.id)
        )
    )
    state: dict[str, Any] = {
        "session": {
            "id": session.id,
            "code": session.code,
            "status": session.status,
            "phase": session.phase,
            "quiz_title": session.quiz_title,
            "mode": session.quiz_mode,
            "language": session.language,
            "wrong_answer_policy": session.wrong_answer_policy,
            "is_solo": session.is_solo,
            "question_count": len(session.questions),
            "current_index": session.current_index,
            "started_at": _iso(session.started_at),
            "finished_at": _iso(session.finished_at),
            "timer_mode": session.timer_mode or "per_question",
            "run_deadline": _iso(session.run_deadline),
            "run_remaining_ms": run_remaining_ms(session),
        },
        "participants": [
            {"id": p.id, "nickname": p.nickname, "score": p.score, "is_host": p.is_host}
            for p in participants
        ],
        "server_time": _iso(utcnow()),
        "question": None,
        "reveal": None,
    }

    answered_ids: set[int] = set()
    if question is not None:
        answered_ids = set(
            db.scalars(select(Answer.participant_id).where(Answer.session_question_id == question.id))
        )
        state["question"] = {
            "id": question.id,
            "position": question.position,
            "text_html": question.text_html,
            # Sent with every state so the player can repaint the question in
            # another language without asking the server for a new run.
            "translations": dict(question.text_translations or {}),
            "image_path": question.image_path,
            "time_limit_seconds": question.time_limit_seconds,
            "points": question.points,
            "multiple_answers": (
                question.allow_multiple
                if session.quiz_mode == "poll"
                else sum(1 for o in question.options if o.is_correct) > 1
            ),
            "options": [
                {"id": o.id, "text": o.text, "translations": dict(o.text_translations or {})}
                for o in question.options
            ],
            "started_at": _iso(session.question_started_at),
            "deadline": _iso(session.question_deadline),
            "remaining_ms": remaining_ms(session) if session.phase == "question" else 0,
            "answered_ids": sorted(answered_ids),
        }
        if session.phase in {"reveal", "finished"}:
            answers = list(
                db.scalars(select(Answer).where(Answer.session_question_id == question.id))
            )
            counts: dict[int, int] = {o.id: 0 for o in question.options}
            for answer in answers:
                for option_id in answer.selected or []:
                    counts[option_id] = counts.get(option_id, 0) + 1
            is_poll = session.quiz_mode == "poll"
            state["reveal"] = {
                # A poll has no answer key: an empty list tells the client to
                # render tallies instead of colouring right and wrong.
                "correct_option_ids": [] if is_poll else [o.id for o in question.options if o.is_correct],
                "is_poll": is_poll,
                "options": [
                    {
                        "id": o.id,
                        "text": o.text,
                        "translations": dict(o.text_translations or {}),
                        "is_correct": False if is_poll else o.is_correct,
                        "count": counts.get(o.id, 0),
                    }
                    for o in question.options
                ],
                "results": [
                    {
                        "participant_id": answer.participant_id,
                        "is_correct": False if is_poll else answer.is_correct,
                        "points_awarded": 0 if is_poll else answer.points_awarded,
                    }
                    for answer in answers
                ],
                "answered_count": len(answers),
                "participant_count": len(participants),
            }

    state["scoreboard"] = sorted(
        [{"id": p.id, "nickname": p.nickname, "score": p.score} for p in participants],
        key=lambda item: (-item["score"], item["nickname"].lower()),
    )
    return state


def _iso(value: datetime | None) -> str | None:
    value = aware(value)
    return value.isoformat().replace("+00:00", "Z") if value else None


def _spoken(entity: Any, value_attribute: str, language: str | None) -> str:
    """The wording a reader of ``language`` should see, authored text otherwise."""
    if language:
        translated = (getattr(entity, "text_translations", None) or {}).get(language)
        if translated:
            return translated
    return getattr(entity, value_attribute) or ""


def results_payload(
    db: OrmSession, session: GameSession, language: str | None = None
) -> dict[str, Any]:
    """Full answer matrix used by the post-game detailed view.

    The snapshot is language-neutral: the wording is resolved here, for the
    reader, in the run's language unless another one is asked for.
    """
    language = language or session.language
    participants = list(
        db.scalars(
            select(Participant).where(Participant.session_id == session.id).order_by(Participant.id)
        )
    )
    answers = list(
        db.scalars(
            select(Answer)
            .join(SessionQuestion, SessionQuestion.id == Answer.session_question_id)
            .where(SessionQuestion.session_id == session.id)
        )
    )
    by_participant_question = {(a.participant_id, a.session_question_id): a for a in answers}

    questions = []
    for question in session.questions:
        rows = []
        for participant in participants:
            answer = by_participant_question.get((participant.id, question.id))
            rows.append(
                {
                    "participant_id": participant.id,
                    "nickname": participant.nickname,
                    "answered": answer is not None,
                    "selected_option_ids": (answer.selected if answer else []) or [],
                    "selected_options": [
                        _spoken(option, "text", language)
                        for option in question.options
                        if answer and option.id in (answer.selected or [])
                    ],
                    "is_correct": bool(answer.is_correct) if answer else False,
                    "points_awarded": answer.points_awarded if answer else 0,
                    "response_ms": answer.response_ms if answer else None,
                }
            )
        questions.append(
            {
                "id": question.id,
                "position": question.position,
                "text_html": _spoken(question, "text_html", language),
                "translations": dict(question.text_translations or {}),
                "image_path": question.image_path,
                "time_limit_seconds": question.time_limit_seconds,
                "points": question.points,
                "options": [
                    {
                        "id": o.id,
                        "text": _spoken(o, "text", language),
                        "translations": dict(o.text_translations or {}),
                        "is_correct": o.is_correct,
                    }
                    for o in question.options
                ],
                "correct_option_ids": [o.id for o in question.options if o.is_correct],
                "answers": rows,
            }
        )

    return {
        "session": {
            "id": session.id,
            "code": session.code,
            "quiz_title": session.quiz_title,
            "status": session.status,
            "is_solo": session.is_solo,
            "wrong_answer_policy": session.wrong_answer_policy,
            "started_at": _iso(session.started_at),
            "finished_at": _iso(session.finished_at),
        },
        "scoreboard": sorted(
            [
                {
                    "id": p.id,
                    "nickname": p.nickname,
                    "score": p.score,
                    "user_id": p.user_id,
                }
                for p in participants
            ],
            key=lambda item: (-item["score"], item["nickname"].lower()),
        ),
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Timer tasks (single-worker asyncio)
# ---------------------------------------------------------------------------
def cancel_timer(code: str) -> None:
    task = _timers.pop(code, None)
    if task and not task.done():
        task.cancel()


def schedule_timer(code: str, deadline: datetime | None) -> None:
    cancel_timer(code)
    if deadline is None:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Called from a sync context (threadpool endpoint or a unit test):
        # the next async call for this session will reschedule the timer.
        return
    delay = max(0.0, (aware(deadline) - utcnow()).total_seconds())
    _timers[code] = asyncio.create_task(_timer_reveal(code, delay))


async def _timer_reveal(code: str, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        changed = await asyncio.to_thread(reveal_if_deadline_passed, code)
        if changed:
            state = await asyncio.to_thread(load_state, code)
            if state:
                await manager.broadcast(code, {"type": "state", "state": state})
    except asyncio.CancelledError:  # pragma: no cover - normal shutdown path
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Timer task failed for session %s", code)
    finally:
        _timers.pop(code, None)


def reveal_if_deadline_passed(code: str) -> bool:
    from .db import SessionLocal

    with SessionLocal() as db:
        session = db.scalar(select(GameSession).where(GameSession.code == code))
        if session is None:
            return False
        return reveal_question(db, session)


def load_state(code: str) -> dict[str, Any] | None:
    from .db import SessionLocal

    with SessionLocal() as db:
        session = db.scalar(select(GameSession).where(GameSession.code == code))
        if session is None:
            return None
        return build_state(db, session)


async def broadcast_state(code: str) -> None:
    state = await asyncio.to_thread(load_state, code)
    if state:
        await manager.broadcast(code, {"type": "state", "state": state})


def wait_seconds(deadline: datetime | None) -> float:
    if deadline is None:
        return 0
    return max(0.0, (aware(deadline) - utcnow()).total_seconds())


def now_ts() -> float:
    """Exposed for tests that need a monotonic-ish clock reference."""
    return time.time()
