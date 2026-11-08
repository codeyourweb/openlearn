# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Account endpoints: profile, password, API keys and participation history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..deps import client_ip, enforce_rate_limit, require_user
from ..models import ApiKey, GameSession, Participant, SecurityEvent, SessionQuestion, User, utcnow
from ..schemas import ApiKeyCreatedOut, ApiKeyIn, ApiKeyOut, SessionSummaryOut
import json
from ..security import (
    PasswordPolicyError,
    generate_api_key,
    hash_password,
    sha256,
    validate_password,
    verify_password,
)
from ..sanitize import sanitize_plain

router = APIRouter(prefix="/api/v1/me", tags=["account"])


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=60)

    @field_validator("display_name")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = sanitize_plain(value, max_length=60)
        if len(cleaned) < 2:
            raise ValueError("Display name is too short.")
        return cleaned


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


@router.patch("/profile")
def update_profile(payload: ProfileIn, user: User = Depends(require_user), db: OrmSession = Depends(get_db)):
    user.display_name = payload.display_name
    db.add(user)
    db.commit()
    return {"id": user.id, "display_name": user.display_name, "email": user.email}


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordIn,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    enforce_rate_limit(request, "auth", 10, 60)
    if not verify_password(payload.current_password, user.password_hash):
        db.add(SecurityEvent(event="password_change_failed", ip=client_ip(request), user_id=user.id))
        db.commit()
        raise HTTPException(status_code=403, detail="Current password is incorrect.")
    try:
        validate_password(payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    db.add(SecurityEvent(event="password_change_success", ip=client_ip(request), user_id=user.id))
    db.commit()


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(user: User = Depends(require_user), db: OrmSession = Depends(get_db)):
    return list(
        db.scalars(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
        )
    )


@router.post("/api-keys", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyIn,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    enforce_rate_limit(request, "api_keys", 10, 60)
    active = db.scalar(
        select(func.count(ApiKey.id)).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
    ) or 0
    if active >= 20:
        raise HTTPException(status_code=409, detail="Too many active API keys (max 20).")
    plain, prefix, key_hash = generate_api_key()
    record = ApiKey(user_id=user.id, name=payload.name, prefix=prefix, key_hash=key_hash)
    db.add(record)
    db.commit()
    db.refresh(record)
    db.add(SecurityEvent(event="api_key_created", ip=client_ip(request), user_id=user.id, detail=prefix))
    db.commit()
    return ApiKeyCreatedOut(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        key=plain,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    record = db.get(ApiKey, key_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found.")
    record.revoked_at = utcnow()
    db.add(record)
    db.add(SecurityEvent(event="api_key_revoked", ip=client_ip(request), user_id=user.id, detail=record.prefix))
    db.commit()


@router.get("/history", summary="Sessions you played or hosted, one page at a time")
def participation_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=120),
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Every session the user played or hosted, most recent first.

    Played sessions carry the user's own score and their rank among the human
    players (the host row of a solo game never competes). Hosted sessions carry
    the best score so the entry is never empty.
    """

    def question_count(session: GameSession) -> int:
        return db.scalar(
            select(func.count(SessionQuestion.id)).where(SessionQuestion.session_id == session.id)
        ) or 0

    def human_count(session: GameSession) -> int:
        return db.scalar(
            select(func.count(Participant.id))
            .where(Participant.session_id == session.id)
            .where(Participant.is_host.is_(False))
        ) or 0

    def rank_of(session: GameSession, score: int | None) -> int | None:
        if score is None:
            return None
        better = db.scalar(
            select(func.count(Participant.id))
            .where(Participant.session_id == session.id)
            .where(Participant.score > score)
        ) or 0
        return better + 1

    played = db.execute(
        select(GameSession, Participant.score)
        .join(Participant, Participant.session_id == GameSession.id)
        .where(Participant.user_id == user.id)
        .order_by(GameSession.created_at.desc())
        .limit(500)
    ).all()
    hosted = db.scalars(
        select(GameSession).where(GameSession.host_user_id == user.id).order_by(GameSession.created_at.desc()).limit(500)
    ).all()

    seen: dict[int, SessionSummaryOut] = {}
    for session, score in played:
        seen[session.id] = SessionSummaryOut(
            id=session.id,
            code=session.code,
            status=session.status,
            is_solo=session.is_solo,
            quiz_title=session.quiz_title,
            quiz_id=session.quiz_id,
            quiz_mode=session.quiz_mode,
            question_count=question_count(session),
            participant_count=human_count(session),
            created_at=session.created_at,
            started_at=session.started_at,
            finished_at=session.finished_at,
            best_score=score,
            rank=rank_of(session, score),
        )
    for session in hosted:
        if session.id in seen:
            continue
        best = db.scalar(
            select(func.max(Participant.score))
            .where(Participant.session_id == session.id)
            .where(Participant.is_host.is_(False))
        )
        seen[session.id] = SessionSummaryOut(
            id=session.id,
            code=session.code,
            status=session.status,
            is_solo=session.is_solo,
            quiz_title=session.quiz_title,
            quiz_id=session.quiz_id,
            quiz_mode=session.quiz_mode,
            question_count=question_count(session),
            participant_count=human_count(session),
            created_at=session.created_at,
            started_at=session.started_at,
            finished_at=session.finished_at,
            best_score=best,
            rank=None,
        )
    # The two lists are merged before sorting, so the page is cut after the
    # merge: a session played and hosted must not appear twice, or be counted
    # twice against the total.
    rows = sorted(seen.values(), key=lambda item: item.created_at, reverse=True)
    if q.strip():
        needle = q.strip().lower()
        rows = [item for item in rows if needle in (item.quiz_title or "").lower()]
    page = rows[offset : offset + limit]
    return Response(
        content=json.dumps([jsonable(item) for item in page]),
        media_type="application/json",
        headers={"X-Total-Count": str(len(rows))},
    )


def jsonable(item: SessionSummaryOut) -> dict:
    return json.loads(item.model_dump_json())
