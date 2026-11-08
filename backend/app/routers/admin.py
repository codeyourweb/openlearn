# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Administration: quiz moderation, account management and AI audit trail."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from .. import abuse, mailer, runtime, verification, versions
from ..config import settings
from ..db import get_db
from ..deps import client_ip, require_admin, require_staff
from ..models import (
    AdventureNode,
    AiReview,
    Question,
    Quiz,
    QuizVersion,
    SecurityEvent,
    User,
    Wiki,
    WikiPage,
    utcnow,
)
from ..schemas import AdminUserOut, AdminUserPatch, ModerationIn, QuizIn
from .quizzes import _apply_quiz, _sync_public_flag, serialise_quiz

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _notify_author(
    db: OrmSession,
    request: Request,
    *,
    owner: User | None,
    staff: User,
    title: str,
    kind: str,
    path: str,
    note: str = "",
) -> None:
    """Mail the author once their queued content is public.

    Skipped when the moderator approves their own work (they already know), and
    never fatal: a missing SMTP server must not make a moderation fail.
    """
    if owner is None or owner.id == staff.id:
        return
    base = verification.public_base(request)
    if not base:
        return
    mailer.send_safely(
        mailer.publication_approved_message(
            to=owner.email,
            title=title,
            kind=kind,
            link=f"{base}{path}",
            instance=runtime.instance_name(db),
            note=note or "",
            name=owner.display_name,
        )
    )


def _quiz_row(db: OrmSession, quiz: Quiz) -> dict:
    count = db.scalar(select(func.count(Question.id)).where(Question.quiz_id == quiz.id))
    if quiz.mode == "adventure" and not count:
        count = db.scalar(
            select(func.count(AdventureNode.id)).where(
                AdventureNode.quiz_id == quiz.id, AdventureNode.kind == "question"
            )
        )
    pending_version = db.scalar(
        select(QuizVersion)
        .where(QuizVersion.quiz_id == quiz.id, QuizVersion.status == "pending")
        .order_by(QuizVersion.number.desc())
    )
    return {
        "id": quiz.id,
        "title": quiz.title,
        "description": quiz.description,
        "status": quiz.status,
        "mode": quiz.mode,
        "is_public": quiz.is_public,
        "question_count": count or 0,
        "owner_id": quiz.owner_id,
        "owner_name": quiz.owner.display_name if quiz.owner else "",
        "owner_email": quiz.owner.email if quiz.owner else "",
        "ai_generated": quiz.ai_generated,
        "legal_status": quiz.legal_status,
        "answer_status": quiz.answer_status,
        "moderation_note": quiz.moderation_note,
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
        "published_at": quiz.published_at,
        "published_version": quiz.published_version_number or 0,
        "pending_version": pending_version.number if pending_version else None,
    }


@router.get("/stats")
def stats(staff: User = Depends(require_staff), db: OrmSession = Depends(get_db)):
    by_status = {
        row[0]: row[1]
        for row in db.execute(select(Quiz.status, func.count(Quiz.id)).group_by(Quiz.status)).all()
    }
    # The moderation queue is counted on versions, since a queued quiz keeps its
    # private status while the author can still play it.
    by_status["pending"] = db.scalar(
        select(func.count(func.distinct(QuizVersion.quiz_id))).where(
            QuizVersion.status == "pending"
        )
    ) or 0
    return {
        "quizzes": {
            "total": db.scalar(select(func.count(Quiz.id))) or 0,
            "by_status": by_status,
        },
        "users": {
            "total": db.scalar(select(func.count(User.id))) or 0,
            "admins": db.scalar(select(func.count(User.id)).where(User.is_admin.is_(True))) or 0,
        },
        "wikis": {
            "total": db.scalar(select(func.count(Wiki.id))) or 0,
            "pending": db.scalar(
                select(func.count(Wiki.id)).where(Wiki.status == "pending")
            )
            or 0,
        },
        "reviews": {
            "total": db.scalar(select(func.count(AiReview.id))) or 0,
            "blocked": db.scalar(
                select(func.count(AiReview.id)).where(AiReview.status == "blocked")
            )
            or 0,
        },
    }


@router.get("/quizzes")
def list_quizzes(
    status_filter: str | None = Query(default=None, alias="status", max_length=12),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    stmt = select(Quiz)
    if status_filter == "pending":
        # The queue lives on versions: a quiz waiting for review stays private
        # so its author can keep playing it by link meanwhile.
        stmt = stmt.where(
            Quiz.id.in_(select(QuizVersion.quiz_id).where(QuizVersion.status == "pending"))
        )
    elif status_filter:
        stmt = stmt.where(Quiz.status == status_filter)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(Quiz.title.ilike(pattern))
    stmt = stmt.order_by(Quiz.updated_at.desc()).limit(limit).offset(offset)
    return [_quiz_row(db, quiz) for quiz in db.scalars(stmt).unique()]


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: int, staff: User = Depends(require_staff), db: OrmSession = Depends(get_db)):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    return serialise_quiz(quiz, include_answers=True)


@router.put("/quizzes/{quiz_id}")
def update_quiz(
    quiz_id: int,
    payload: QuizIn,
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    _apply_quiz(db, quiz, payload)
    return serialise_quiz(quiz, include_answers=True)


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quiz(quiz_id: int, staff: User = Depends(require_staff), db: OrmSession = Depends(get_db)):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    db.delete(quiz)
    db.commit()


@router.post("/quizzes/{quiz_id}/approve")
def approve_quiz(
    quiz_id: int,
    payload: ModerationIn,
    request: Request,
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if quiz.legal_status == "blocked":
        raise HTTPException(
            status_code=409,
            detail="The AI safety review blocked this quiz; fix the content first.",
        )
    pending = db.scalar(
        select(QuizVersion)
        .where(QuizVersion.quiz_id == quiz.id, QuizVersion.status == "pending")
        .order_by(QuizVersion.number.desc())
    )
    if pending is not None:
        # Approving a version publishes exactly what the author submitted.
        versions.publish_existing(db, quiz, pending, approver=staff)
        quiz.moderation_note = payload.note
    else:
        quiz.status = "public"
        quiz.published_at = utcnow()
        quiz.approved_by_id = staff.id
        quiz.moderation_note = payload.note
    _sync_public_flag(quiz)
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    _notify_author(
        db,
        request,
        owner=db.get(User, quiz.owner_id),
        staff=staff,
        title=quiz.title,
        kind="quiz",
        path=f"/quizzes/{quiz.id}",
        note=payload.note or "",
    )
    return _quiz_row(db, quiz)


@router.post("/quizzes/{quiz_id}/reject")
def reject_quiz(
    quiz_id: int,
    payload: ModerationIn,
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    quiz.status = "rejected"
    quiz.published_at = None
    quiz.moderation_note = payload.note or "Rejected by an administrator."
    db.query(QuizVersion).filter(
        QuizVersion.quiz_id == quiz.id, QuizVersion.status == "pending"
    ).update({"status": "rejected"})
    _sync_public_flag(quiz)
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return _quiz_row(db, quiz)


@router.get("/reviews")
def list_reviews(
    response: Response,
    kind: str | None = Query(default=None, max_length=12),
    status_filter: str | None = Query(default=None, alias="status", max_length=12),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    stmt = select(AiReview)
    if kind:
        stmt = stmt.where(AiReview.kind == kind)
    if status_filter:
        stmt = stmt.where(AiReview.status == status_filter)
    if q and q.strip():
        # The review carries no title of its own: search the questionnaire it
        # examined, which is what an administrator looks for.
        matches = select(Quiz.id).where(Quiz.title.ilike(f"%{q.strip()}%"))
        stmt = stmt.where(AiReview.quiz_id.in_(matches))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(AiReview.created_at.desc()).limit(limit).offset(offset)
    rows = []
    for review in db.scalars(stmt):
        quiz = db.get(Quiz, review.quiz_id)
        rows.append(
            {
                "id": review.id,
                "quiz_id": review.quiz_id,
                "quiz_title": quiz.title if quiz else "",
                "kind": review.kind,
                "status": review.status,
                "summary": review.summary,
                "findings": review.findings or [],
                "model": review.model,
                "requested_by_id": review.requested_by_id,
                "requested_ip": review.requested_ip,
                "created_at": review.created_at,
            }
        )
    return rows


@router.get("/users", summary="Accounts, one page at a time")
def list_users(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    where = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        where.append(User.email.ilike(pattern) | User.display_name.ilike(pattern))
    total = db.scalar(select(func.count(User.id)).where(*where)) or 0
    stmt = select(User).where(*where).order_by(User.created_at.desc()).limit(limit).offset(offset)
    rows = []
    for user in db.scalars(stmt):
        quiz_count = db.scalar(select(func.count(Quiz.id)).where(Quiz.owner_id == user.id)) or 0
        rows.append(
            AdminUserOut(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_admin=user.is_admin,
                is_moderator=user.is_moderator,
                is_trusted=user.is_trusted,
                is_active=user.is_active,
                created_at=user.created_at,
                last_login_at=user.last_login_at,
                quiz_count=quiz_count,
            )
        )
    return Response(
        content=json.dumps([json.loads(row.model_dump_json()) for row in rows]),
        media_type="application/json",
        headers={"X-Total-Count": str(total)},
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def patch_user(
    user_id: int,
    payload: AdminUserPatch,
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    # A moderator only vouches for people ("trusted"). Roles and account
    # suspension stay with the administrator, and no one below the
    # administrator may touch another staff account.
    if not staff.is_admin:
        if payload.is_admin is not None or payload.is_moderator is not None or payload.is_active is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A moderator only grants or revokes the trusted flag.",
            )
        if user.is_staff:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A moderator cannot change another moderator's account.",
            )

    if user.id == staff.id and payload.is_admin is False:
        raise HTTPException(status_code=409, detail="You cannot revoke your own admin rights.")
    if user.id == staff.id and payload.is_moderator is False:
        raise HTTPException(status_code=409, detail="You cannot revoke your own moderator rights.")
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_moderator is not None:
        user.is_moderator = payload.is_moderator
    if payload.is_trusted is not None:
        user.is_trusted = payload.is_trusted
    if payload.is_active is not None:
        if user.id == staff.id and payload.is_active is False:
            raise HTTPException(status_code=409, detail="You cannot disable your own account.")
        user.is_active = payload.is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    quiz_count = db.scalar(select(func.count(Quiz.id)).where(Quiz.owner_id == user.id)) or 0
    return AdminUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_moderator=user.is_moderator,
        is_trusted=user.is_trusted,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        quiz_count=quiz_count,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, staff: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == staff.id:
        raise HTTPException(status_code=409, detail="You cannot delete your own account.")
    db.delete(user)
    db.commit()


@router.get("/events")
def recent_events(
    response: Response,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    """Authentication and moderation audit trail (OWASP A09)."""
    stmt = select(SecurityEvent)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                SecurityEvent.event.ilike(pattern),
                SecurityEvent.detail.ilike(pattern),
                SecurityEvent.ip.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(SecurityEvent.created_at.desc()).limit(limit).offset(offset)
    return [
        {
            "id": event.id,
            "event": event.event,
            "ip": event.ip,
            "user_id": event.user_id,
            "detail": event.detail,
            "created_at": event.created_at,
        }
        for event in db.scalars(stmt)
    ]


# ---------------------------------------------------------------------------
# Wiki moderation
# ---------------------------------------------------------------------------
def _wiki_row(db: OrmSession, wiki: Wiki) -> dict:
    owner = db.get(User, wiki.owner_id)
    page_count = db.scalar(select(func.count(WikiPage.id)).where(WikiPage.wiki_id == wiki.id)) or 0
    return {
        "id": wiki.id,
        "title": wiki.title,
        "description": wiki.description[:300],
        "status": wiki.status,
        "is_public": wiki.is_public,
        "owner": {"id": owner.id, "email": owner.email, "display_name": owner.display_name}
        if owner
        else None,
        "page_count": page_count,
        "moderation_note": wiki.moderation_note,
        "updated_at": wiki.updated_at,
    }


@router.get("/wikis")
def list_wikis_admin(
    status_filter: str | None = Query(default=None, alias="status", max_length=12),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    statement = select(Wiki)
    if status_filter:
        statement = statement.where(Wiki.status == status_filter)
    if q and q.strip():
        statement = statement.where(Wiki.title.ilike(f"%{q.strip()}%"))
    rows = db.scalars(statement.order_by(Wiki.updated_at.desc()).limit(limit).offset(offset)).all()
    return [_wiki_row(db, wiki) for wiki in rows]


@router.post("/wikis/{wiki_id}/approve")
def approve_wiki(
    wiki_id: int,
    payload: ModerationIn,
    request: Request,
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    wiki = db.get(Wiki, wiki_id)
    if wiki is None:
        raise HTTPException(status_code=404, detail="Wiki not found.")
    wiki.status = "public"
    wiki.is_public = True
    wiki.published_at = utcnow()
    wiki.approved_by_id = staff.id
    wiki.moderation_note = payload.note
    db.commit()
    db.refresh(wiki)
    _notify_author(
        db,
        request,
        owner=db.get(User, wiki.owner_id),
        staff=staff,
        title=wiki.title,
        kind="wiki",
        path=f"/wiki/{wiki.id}",
        note=payload.note or "",
    )
    return _wiki_row(db, wiki)


@router.get("/security/bans")
def list_bans(admin: User = Depends(require_admin)) -> dict[str, object]:
    """Who is currently kept away from the forms, and the rule that put them there."""
    return {
        "enabled": settings.form_ban_enabled,
        "threshold": settings.form_ban_strikes,
        "window_seconds": settings.form_ban_window_seconds,
        "ban_seconds": settings.form_ban_seconds,
        "entries": abuse.BANS.entries(),
    }


@router.delete("/security/bans/{ip}", status_code=status.HTTP_204_NO_CONTENT)
def lift_ban(
    ip: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
) -> Response:
    """Let an address back in before its ban expires (a shared office, a mistake)."""
    abuse.BANS.lift(ip)
    db.add(
        SecurityEvent(
            event="ip_ban_lifted",
            ip=client_ip(request),
            user_id=admin.id,
            detail=ip[:300],
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/wikis/{wiki_id}/reject")
def reject_wiki(
    wiki_id: int,
    payload: ModerationIn,
    staff: User = Depends(require_staff),
    db: OrmSession = Depends(get_db),
):
    wiki = db.get(Wiki, wiki_id)
    if wiki is None:
        raise HTTPException(status_code=404, detail="Wiki not found.")
    wiki.status = "rejected"
    wiki.is_public = False
    wiki.published_at = None
    wiki.moderation_note = payload.note or "Rejected by an administrator."
    db.commit()
    db.refresh(wiki)
    return _wiki_row(db, wiki)
