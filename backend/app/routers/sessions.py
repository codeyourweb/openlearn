# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Live and solo game sessions: REST control plane plus a WebSocket state feed."""

from __future__ import annotations

import secrets

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import client_ip, enforce_rate_limit, external_base_url, get_optional_user, verify_csrf
from ..game import (
    all_participants_answered,
    build_state,
    cancel_session,
    create_session,
    finish_session,
    is_host_authorized,
    join_session,
    next_question,
    participant_from_token,
    results_payload,
    reveal_question,
    schedule_timer,
    start_session,
)
from ..evaluation import ensure_attempt_left
from ..models import GameSession, Participant, Quiz, SecurityEvent, User
from ..realtime import manager
from ..schemas import AnswerIn, JoinIn, SessionCreateIn
from ..security import decode_access_token, sha256

router = APIRouter(prefix="/api/v1", tags=["sessions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_session_by_code(db: OrmSession, code: str) -> GameSession:
    session = db.scalar(select(GameSession).where(GameSession.code == code.strip().upper()))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


def host_or_403(db: OrmSession, session: GameSession, request: Request) -> None:
    host_token = request.headers.get("x-host-token")
    user = get_optional_user(request, db)
    if not is_host_authorized(db, session, user, host_token):
        raise HTTPException(status_code=403, detail="Only the host can perform this action.")


def participant_or_403(db: OrmSession, session: GameSession, request: Request) -> Participant:
    token = request.headers.get("x-participant-token")
    participant = participant_from_token(db, session, token)
    if participant is None:
        raise HTTPException(status_code=403, detail="Join the session first (missing or invalid participant token).")
    return participant


def _audit(db: OrmSession, event: str, request: Request | None, user_id: int | None = None, detail: str = "") -> None:
    db.add(SecurityEvent(event=event, ip=client_ip(request) if request else None, user_id=user_id, detail=detail[:300]))
    db.commit()


def _public_session(session: GameSession, participant_count: int) -> dict:
    return {
        "id": session.id,
        "code": session.code,
        "quiz_title": session.quiz_title,
        "status": session.status,
        "phase": session.phase,
        "is_solo": session.is_solo,
        "question_count": len(session.questions),
        "participant_count": participant_count,
        "started_at": session.started_at,
        "finished_at": session.finished_at,
    }


def _count_participants(db: OrmSession, session: GameSession) -> int:
    return db.scalar(select(func.count(Participant.id)).where(Participant.session_id == session.id)) or 0


# ---------------------------------------------------------------------------
# Creation / discovery
# ---------------------------------------------------------------------------
@router.post("/quizzes/{quiz_id}/sessions", status_code=status.HTTP_201_CREATED)
async def create_game_session(
    quiz_id: int,
    payload: SessionCreateIn,
    request: Request,
    db: OrmSession = Depends(get_db),
):
    enforce_rate_limit(request, "join", settings.join_rate_limit, settings.join_rate_window_seconds)
    verify_csrf(request)
    user = get_optional_user(request, db)
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    is_owner = user is not None and (quiz.owner_id == user.id or user.is_admin)
    if quiz.status != "public" and not is_owner:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    # Anyone may host a live session of a published quiz, signed in or not;
    # a private quiz can only be driven by its owner.
    if quiz.status != "public" and user is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    # A questionnaire used as an assessment allows a limited number of runs:
    # a deferred run is refused here, before anything is written.
    if payload.mode == "solo" and not payload.play_as_host:
        ensure_attempt_left(db, quiz, user)

    session, host_token, join_url, participant, participant_token = create_session(
        db,
        quiz=quiz,
        user=user,
        mode=payload.mode,
        nickname=payload.nickname,
        base_url=external_base_url(request),
        language=payload.language,
        play_as_host=payload.play_as_host,
    )
    if session.status == "active":
        schedule_timer(session.code, session.question_deadline)
    _audit(db, "session_created", request, user.id if user else None, f"{session.code} {payload.mode}")

    return {
        "session": _public_session(session, _count_participants(db, session)),
        "host_token": host_token,
        "join_url": join_url,
        "join_token": session.join_token,
        "participant": {"id": participant.id, "nickname": participant.nickname, "token": participant_token}
        if participant
        else None,
        "state": build_state(db, session),
    }


def join_state(db: OrmSession, session: GameSession) -> str:
    """Why a shared link can or cannot be used right now.

    The SPA shows a different message for a link to a game that already started
    than for a dead link, so the resolver reports the reason instead of letting
    the join fail later with an unexplained error.
    """
    if session.is_solo:
        return "solo"
    if session.status in ("finished", "cancelled"):
        return "finished"
    if session.status != "lobby":
        return "started"
    count = _count_participants(db, session)
    if count >= settings.max_participants_per_session:
        return "full"
    return "open"


@router.get("/join/{join_token}")
def resolve_join_link(join_token: str, db: OrmSession = Depends(get_db)):
    """Resolve the shareable link so the SPA can pre-fill the join form."""
    session = db.scalar(select(GameSession).where(GameSession.join_token == join_token))
    if session is None:
        raise HTTPException(status_code=404, detail="Invalid join link.")
    payload = _public_session(session, _count_participants(db, session))
    payload["join_state"] = join_state(db, session)
    return payload


@router.get("/sessions/{code}")
def session_overview(code: str, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    return _public_session(session, _count_participants(db, session))


# ---------------------------------------------------------------------------
# Join / state
# ---------------------------------------------------------------------------
@router.post("/sessions/{code}/join", status_code=status.HTTP_201_CREATED)
async def join(code: str, payload: JoinIn, request: Request, db: OrmSession = Depends(get_db)):
    enforce_rate_limit(request, "join", settings.join_rate_limit, settings.join_rate_window_seconds)
    session = get_session_by_code(db, code)
    user = get_optional_user(request, db)
    quiz = db.get(Quiz, session.quiz_id)
    if quiz is not None:
        ensure_attempt_left(db, quiz, user, session=session)
    participant, token = join_session(db, session, payload.nickname, user)
    _audit(db, "session_join", request, user.id if user else None, session.code)
    # The lobby of every connected client (host included) must see the new
    # player immediately, not on the next manual refresh.
    await manager.broadcast(session.code, {"type": "state", "state": build_state(db, session)})
    return {
        "participant": {"id": participant.id, "nickname": participant.nickname, "token": token},
        "session": _public_session(session, _count_participants(db, session)),
        "state": build_state(db, session),
    }


@router.get("/sessions/{code}/join-link")
def session_join_link(code: str, request: Request, db: OrmSession = Depends(get_db)):
    """Shareable join URL, only exposed to the host."""
    session = get_session_by_code(db, code)
    host_or_403(db, session, request)
    base = external_base_url(request)
    return {"join_url": f"{base}/join/{session.join_token}", "join_token": session.join_token, "code": session.code}


@router.get("/sessions/{code}/state")
def session_state(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    token = request.headers.get("x-participant-token")
    participant = participant_from_token(db, session, token)
    host_token = request.headers.get("x-host-token")
    user = get_optional_user(request, db)
    if participant is None and not is_host_authorized(db, session, user, host_token):
        raise HTTPException(status_code=403, detail="Join the session to access its state.")
    if session.status == "active" and session.phase == "question":
        schedule_timer(session.code, session.question_deadline)
    state = build_state(db, session)
    state["me"] = (
        {"participant_id": participant.id, "nickname": participant.nickname, "is_host": participant.is_host}
        if participant
        else {"participant_id": None, "nickname": None, "is_host": True}
    )
    return state


# ---------------------------------------------------------------------------
# Host controls
# ---------------------------------------------------------------------------
@router.post("/sessions/{code}/start")
async def start(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    host_or_403(db, session, request)
    if session.status == "active":
        return {"status": "active", "state": build_state(db, session)}
    start_session(db, session)
    schedule_timer(session.code, session.question_deadline)
    _audit(db, "session_started", request, session.host_user_id, session.code)
    await manager.broadcast(session.code, {"type": "state", "state": build_state(db, session)})
    return {"status": session.status, "state": build_state(db, session)}


@router.post("/sessions/{code}/reveal")
async def reveal(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    host_or_403(db, session, request)
    reveal_question(db, session, force=True)
    await manager.broadcast(session.code, {"type": "state", "state": build_state(db, session)})
    return {"status": session.status, "phase": session.phase, "state": build_state(db, session)}


@router.post("/sessions/{code}/next")
async def advance(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    host_or_403(db, session, request)
    outcome = next_question(db, session)
    if outcome == "question":
        schedule_timer(session.code, session.question_deadline)
    await manager.broadcast(session.code, {"type": "state", "state": build_state(db, session)})
    if outcome == "finished":
        await manager.broadcast(session.code, {"type": "finished", "state": build_state(db, session)})
    return {"phase": session.phase, "status": session.status, "state": build_state(db, session)}


@router.post("/sessions/{code}/cancel")
async def cancel(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    host_or_403(db, session, request)
    cancel_session(db, session)
    _audit(db, "session_cancelled", request, session.host_user_id, session.code)
    await manager.broadcast(session.code, {"type": "finished", "state": build_state(db, session)})
    return {"status": session.status}


@router.post("/sessions/{code}/finish")
async def finish(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    host_or_403(db, session, request)
    finish_session(db, session)
    await manager.broadcast(session.code, {"type": "finished", "state": build_state(db, session)})
    return {"status": session.status}


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
@router.post("/sessions/{code}/answers", status_code=status.HTTP_201_CREATED)
async def answer(code: str, payload: AnswerIn, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    participant = participant_or_403(db, session, request)
    from ..game import submit_answer

    record = submit_answer(db, session, participant, payload.question_id, payload.option_ids)
    state = build_state(db, session)
    if all_participants_answered(db, session):
        reveal_question(db, session, force=True)
        state = build_state(db, session)
    await manager.broadcast(session.code, {"type": "state", "state": state})
    return {
        "answer": {
            "id": record.id,
            "question_id": record.session_question_id,
            "is_correct": record.is_correct,
            "points_awarded": record.points_awarded,
            "response_ms": record.response_ms,
        },
        "score": participant.score,
    }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@router.get("/sessions/{code}/results")
def results(code: str, request: Request, db: OrmSession = Depends(get_db)):
    session = get_session_by_code(db, code)
    host_token = request.headers.get("x-host-token")
    user = get_optional_user(request, db)
    is_host = is_host_authorized(db, session, user, host_token)
    participant = participant_from_token(db, session, request.headers.get("x-participant-token"))

    if session.status not in {"finished", "active", "cancelled"}:
        raise HTTPException(status_code=409, detail="Results are available once the quiz has started.")
    if not is_host and participant is None:
        raise HTTPException(status_code=403, detail="Access denied.")

    payload = results_payload(db, session)
    if not is_host and participant is not None:
        # Players only see their own row in the answer matrix.
        for question in payload["questions"]:
            question["answers"] = [
                row for row in question["answers"] if row["participant_id"] == participant.id
            ]
        payload["scoreboard"] = [
            row for row in payload["scoreboard"] if row["id"] == participant.id
        ]
    payload["viewer"] = {
        "role": "host" if is_host else "participant",
        "participant_id": participant.id if participant else None,
    }
    return payload


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
async def _resolve_ws_identity(db: OrmSession, session: GameSession, token: str | None, websocket: WebSocket):
    if token:
        if session.host_token_hash and secrets.compare_digest(sha256(token), session.host_token_hash):
            return "host", None
        participant = participant_from_token(db, session, token)
        if participant is not None:
            return "participant", participant
    cookie = websocket.cookies.get(settings.session_cookie_name)
    if cookie:
        payload = decode_access_token(cookie)
        if payload:
            user = db.get(User, int(payload["sub"]))
            if user is not None and is_host_authorized(db, session, user, None):
                return "host", None
    return None, None


@router.websocket("/sessions/{code}/ws")
async def session_websocket(websocket: WebSocket, code: str, token: str | None = Query(default=None)):
    db = SessionLocal()
    connection = None
    normalized = code.strip().upper()
    try:
        session = db.scalar(select(GameSession).where(GameSession.code == normalized))
        if session is None:
            await websocket.close(code=4404, reason="Session not found")
            return
        role, participant = await _resolve_ws_identity(db, session, token, websocket)
        if role is None:
            await websocket.close(code=4401, reason="Authentication required")
            return
        connection = await manager.connect(
            normalized, websocket, role, participant.id if participant else None
        )
        await manager.send_personal(connection, {"type": "state", "state": build_state(db, session)})
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await manager.send_personal(connection, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - never crash the worker on a socket error
        pass
    finally:
        if connection is not None:
            await manager.disconnect(normalized, connection)
        db.close()
