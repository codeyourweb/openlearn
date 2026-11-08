# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Wiki AI endpoints: background jobs and the grounded chat."""

from __future__ import annotations

import hashlib
import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from .. import wiki_ai
from ..db import get_db
from ..deps import enforce_ai_interval, get_optional_user, require_user
from ..models import (
    AiJob,
    User,
    Wiki,
    WikiChat,
    WikiChatMessage,
    WikiMember,
    WikiPage,
    WikiPageVersion,
)
from ..schemas import WikiAiJobIn, WikiChatIn
from .wiki import _member_role, _readable, _require_read, _writable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])

# Headings that say nothing about the subject: a question built on "See also"
# would be noise. Compared case-insensitively, in the languages we ship.
_HEADING = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_HEADING_NOISE = {
    "introduction", "overview", "summary", "see also", "references", "sources",
    "external links", "notes", "further reading", "conclusion", "contents",
    "introduction générale", "résumé", "références", "voir aussi", "sommaire",
    "quellen", "siehe auch", "weiterführendes", "zusammenfassung",
    "referencias", "véase también", "riferimenti", "vedi anche",
    "источники", "см. также", "参考文献", "参见", "参考",
}

# One template set per interface language; unknown languages fall back to English.
SUGGESTION_TEMPLATES: dict[str, list[str]] = {
    "en": [
        "What does this wiki say about {topic}?",
        "Can you sum up {topic}?",
        "What is worth remembering about {topic}?",
        "How does {topic} work?",
    ],
    "fr": [
        "Que dit ce wiki sur {topic} ?",
        "Peux-tu résumer {topic} ?",
        "Que faut-il retenir de {topic} ?",
        "Comment fonctionne {topic} ?",
    ],
    "de": [
        "Was sagt dieses Wiki über {topic}?",
        "Kannst du {topic} zusammenfassen?",
        "Was sollte man sich zu {topic} merken?",
        "Wie funktioniert {topic}?",
    ],
    "es": [
        "¿Qué dice este wiki sobre {topic}?",
        "¿Puedes resumir {topic}?",
        "¿Qué hay que recordar de {topic}?",
        "¿Cómo funciona {topic}?",
    ],
    "it": [
        "Cosa dice questo wiki su {topic}?",
        "Puoi riassumere {topic}?",
        "Cosa c'è da ricordare su {topic}?",
        "Come funziona {topic}?",
    ],
    "ru": [
        "Что этот вики говорит о {topic}?",
        "Можешь кратко пересказать {topic}?",
        "Что важно запомнить о {topic}?",
        "Как работает {topic}?",
    ],
    "ja": [
        "このウィキでは{topic}について何と書かれていますか？",
        "{topic}を要約できますか？",
        "{topic}で覚えておくべきことは？",
        "{topic}はどのように働きますか？",
    ],
    "zh": [
        "这个维基对{topic}是怎么说的？",
        "能概括一下{topic}吗？",
        "{topic}有什么需要记住的？",
        "{topic}是如何运作的？",
    ],
}


def _clean_topic(text: str) -> str:
    """Strip the markdown a heading may carry, keep the words."""
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    return " ".join(text.split()).strip(" .:")


def _topics(db: OrmSession, wiki: Wiki, limit: int = 8) -> list[str]:
    """Section titles of the published pages, in reading order.

    ``content_md`` on a page is the working copy; a published page has an
    immutable snapshot at its current version number, and that is the text the
    reader sees. Fall back to the working copy for a page never saved since
    versioning existed.
    """
    pages = db.scalars(
        select(WikiPage).where(WikiPage.wiki_id == wiki.id).order_by(WikiPage.position, WikiPage.id)
    ).all()

    topics: list[str] = []
    seen: set[str] = set()
    for page in pages:
        body = page.content_md or ""
        if page.current_version_number:
            version = db.scalar(
                select(WikiPageVersion).where(
                    WikiPageVersion.page_id == page.id,
                    WikiPageVersion.number == page.current_version_number,
                )
            )
            if version is not None and version.content_md:
                body = version.content_md
        for match in _HEADING.finditer(body):
            heading = _clean_topic(match.group(2))
            key = heading.casefold()
            if not heading or len(heading) > 80 or key in _HEADING_NOISE or key in seen:
                continue
            seen.add(key)
            topics.append(heading)
            if len(topics) >= limit:
                return topics

    if not topics:
        for page in pages:
            title = _clean_topic(page.title or "")
            if title and title.casefold() not in seen:
                seen.add(title.casefold())
                topics.append(title)
            if len(topics) >= limit:
                break
    return topics


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
    if job.user_id != user.id and not user.is_staff:
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


@router.get("/ai/suggestions", summary="Questions drawn from a wiki's published pages")
def suggestions(
    wiki_id: int = Query(..., ge=1),
    language: str = Query(default="en", max_length=8),
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Starter questions for a single wiki, read from what it actually contains.

    The chat used to open on three hard-coded DNS questions whatever the wiki
    was about, which told the reader nothing about the page in front of them.
    These come from the headings of its published pages: no model call, no
    cost, and the same wiki always offers the same questions.
    """
    wiki = db.get(Wiki, wiki_id)
    if wiki is None:
        raise HTTPException(status_code=404, detail="Wiki not found.")
    _require_read(db, wiki, user)

    topics = _topics(db, wiki)
    templates = SUGGESTION_TEMPLATES.get((language or "en")[:2].lower(), SUGGESTION_TEMPLATES["en"])
    questions = [templates[index % len(templates)].format(topic=topic) for index, topic in enumerate(topics[:4])]
    return {"wiki_id": wiki.id, "suggestions": questions}


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
