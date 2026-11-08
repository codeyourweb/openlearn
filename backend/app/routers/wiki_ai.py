# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Wiki AI endpoints: background jobs and the grounded chat."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from .. import wiki_ai
from ..db import get_db
from ..deps import enforce_ai_interval, get_optional_user, require_user
from ..models import AiJob, User, Wiki, WikiChat, WikiChatMessage, WikiMember, WikiPage
from ..schemas import WikiAiJobIn, WikiChatIn
from .wiki import _member_role, _readable, _require_read, _writable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])


def _job_out(job: AiJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "target_type": job.target_type,
        "target_id": job.target_id,
        "result": job.result or {},
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@router.post("/ai/jobs", status_code=202, summary="Start a sourced generation or a review")
def start_job(
    payload: WikiAiJobIn,
    tasks: BackgroundTasks,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    if not wiki_ai.is_configured():
        raise HTTPException(status_code=503, detail="AI assistance is not configured on this instance.")
    enforce_ai_interval(user)

    wiki: Wiki | None = None
    page: WikiPage | None = None
    if payload.page_id:
        page = db.get(WikiPage, payload.page_id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found.")
        wiki = db.get(Wiki, page.wiki_id)
    elif payload.wiki_id:
        wiki = db.get(Wiki, payload.wiki_id)
    if wiki is None:
        raise HTTPException(status_code=404, detail="Wiki not found.")

    role = _member_role(db, wiki, user)
    if not _readable(wiki, role):
        raise HTTPException(status_code=404, detail="Wiki not found.")
    if payload.kind in {"generate", "expand", "grammar", "fill"} and not _writable(role):
        raise HTTPException(status_code=403, detail="You cannot write in this wiki.")
    if payload.kind == "generate" and payload.page_id:
        raise HTTPException(status_code=422, detail="Generation targets a wiki, not a page.")
    # "fill" writes the body of the page being created: it exists before the page does.
    if payload.kind not in {"generate", "fill"} and page is None:
        raise HTTPException(status_code=422, detail="A page is required for this job.")

    key_parts = [str(wiki.id), payload.kind, str(payload.page_id or 0)]
    if payload.kind in {"generate", "expand", "fill"}:
        # Same topic, same options, no duplicate spend. A different topic is a
        # different job and is allowed.
        key_parts += [payload.topic.strip().lower(), payload.style, str(payload.page_count)]
    digest = hashlib.sha256("|".join(key_parts).encode("utf-8")).hexdigest()[:32]
    key = f"wiki:{payload.kind}:{digest}"

    payload_dict = {
        "topic": payload.topic,
        "style": payload.style,
        "audience": payload.audience,
        "research": payload.research,
        "page_count": payload.page_count,
        "outline": payload.outline,
        "language": payload.language,
        "instructions": payload.instructions,
        "page_id": payload.page_id,
        "wiki_id": wiki.id,
    }
    try:
        job = wiki_ai.claim_job(
            db,
            user=user,
            kind=payload.kind,
            key=key,
            target_type="page" if page else "wiki",
            target_id=page.id if page else wiki.id,
            payload=payload_dict,
        )
    except wiki_ai.JobConflict as conflict:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The same task is already running.",
                "job_id": conflict.job_id,
            },
        )
    tasks.add_task(wiki_ai.run_job, job.id)
    return _job_out(job)


@router.get("/ai/jobs/{job_id}", summary="Poll one job")
def get_job(
    job_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.get(AiJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="This job belongs to somebody else.")
    return _job_out(job)


@router.get("/ai/jobs", summary="Recent jobs of a wiki")
def list_jobs(
    wiki_id: int | None = None,
    page_id: int | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    statement = select(AiJob).where(AiJob.user_id == user.id)
    if wiki_id is not None:
        wiki = db.get(Wiki, wiki_id)
        if wiki is None:
            raise HTTPException(status_code=404, detail="Wiki not found.")
        _require_read(db, wiki, user)
        statement = statement.where(AiJob.target_id == wiki_id, AiJob.target_type == "wiki")
    if page_id is not None:
        statement = statement.where(AiJob.target_id == page_id, AiJob.target_type == "page")
    rows = db.scalars(statement.order_by(AiJob.created_at.desc()).limit(limit)).all()
    return [_job_out(job) for job in rows]


# ---------------------------------------------------------------------------
# Chat (RAG)
# ---------------------------------------------------------------------------
def _readable_wiki_ids(db: OrmSession, user: User | None, requested: list[int]) -> list[int]:
    clauses = [Wiki.status == "public"]
    if user is not None:
        clauses.append(Wiki.owner_id == user.id)
        member_ids = list(
            db.scalars(select(WikiMember.wiki_id).where(WikiMember.user_id == user.id)).all()
        )
        if member_ids:
            clauses.append(Wiki.id.in_(member_ids))
    allowed = set(db.scalars(select(Wiki.id).where(or_(*clauses))).all())
    if requested:
        allowed &= set(requested)
    return sorted(allowed)


@router.post("/ai/chat", summary="Answer a question from the wikis you can read")
def chat(
    payload: WikiChatIn,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    if not wiki_ai.is_configured():
        raise HTTPException(status_code=503, detail="AI assistance is not configured on this instance.")
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to ask the wiki.")
    enforce_ai_interval(user)

    wiki_ids = _readable_wiki_ids(db, user, payload.wiki_ids)
    if not wiki_ids:
        raise HTTPException(status_code=403, detail="You cannot read any wiki yet.")

    thread = None
    if payload.chat_id:
        thread = db.get(WikiChat, payload.chat_id)
        if thread is None or thread.user_id != user.id:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    answer, sources = wiki_ai.answer_question(
        db, question=payload.question, wiki_ids=wiki_ids, language=payload.language
    )
    if thread is None:
        thread = WikiChat(user_id=user.id, title=payload.question[:120])
        db.add(thread)
        db.flush()
    db.add(WikiChatMessage(chat_id=thread.id, role="user", content=payload.question))
    db.add(WikiChatMessage(chat_id=thread.id, role="assistant", content=answer, sources=sources))
    db.commit()
    return {
        "chat_id": thread.id,
        "answer": answer,
        "sources": sources,
        "scope": {"wiki_ids": wiki_ids},
    }


@router.get("/ai/chats", summary="Your conversations")
def list_chats(
    limit: int = Query(default=20, ge=1, le=100),
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    rows = db.scalars(
        select(WikiChat)
        .where(WikiChat.user_id == user.id)
        .order_by(WikiChat.updated_at.desc())
        .limit(limit)
    ).all()
    return [
        {"id": chat.id, "title": chat.title, "updated_at": chat.updated_at} for chat in rows
    ]


@router.get("/ai/chats/{chat_id}", summary="One conversation with its sources")
def get_chat(
    chat_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
):
    thread = db.get(WikiChat, chat_id)
    if thread is None or thread.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    messages = db.scalars(
        select(WikiChatMessage)
        .where(WikiChatMessage.chat_id == thread.id)
        .order_by(WikiChatMessage.id)
    ).all()
    return {
        "id": thread.id,
        "title": thread.title,
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "sources": message.sources or [],
                "created_at": message.created_at,
            }
            for message in messages
        ],
    }
