# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Routes for speech transcripts: ask for one, list the ready ones, drop one.

The list route is public because the player is public: a transcript is only ever
returned for a document the caller may already read, and it is only returned
when it was made from the text currently on the page.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import audio, audit, wiki_ai
from ..config import settings
from ..db import get_db
from ..deps import get_optional_user, require_user
from ..models import AiJob, AudioRendition, Quiz, User, WikiPage
from ..schemas import AudioRenderIn

router = APIRouter(prefix="/api/v1", tags=["audio"])


def _wiki_role(db: OrmSession, wiki_id: int, user: User | None) -> str:
    from ..models import Wiki
    from .wiki import _member_role

    return _member_role(db, db.get(Wiki, wiki_id), user)


def _writable(role: str) -> bool:
    from .wiki import _writable as wiki_writable

    return wiki_writable(role)


def _resolve(db: OrmSession, owner_type: str, owner_id: int, user: User | None) -> tuple[Quiz | WikiPage, bool, bool, str]:
    """Return the document, whether it is readable, whether it is writable, and its language."""
    if owner_type == "page":
        page = db.get(WikiPage, owner_id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found.")
        role = _wiki_role(db, page.wiki_id, user)
        from ..models import Wiki
        from .wiki import _readable

        wiki = db.get(Wiki, page.wiki_id)
        return page, _readable(wiki, role), _writable(role), (wiki.default_language if wiki else "en")

    if owner_type == "node":
        from ..models import AdventureNode
        from .quizzes import _can_view

        node = db.get(AdventureNode, owner_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Scene not found.")
        quiz = db.get(Quiz, node.quiz_id)
        if quiz is None:
            raise HTTPException(status_code=404, detail="Scene not found.")
        visible = _can_view(quiz, user)
        writable = user is not None and (quiz.owner_id == user.id or bool(user.is_admin))
        return node, visible, writable, quiz.default_language or "en"

    raise HTTPException(status_code=422, detail="owner_type must be page or node.")


def _document_language(document, fallback: str) -> str:
    code = getattr(document, "default_language", None) or fallback
    return audio.normalise_language(code, "en")


@router.get("/audio/status", summary="Is speech available, and in which languages")
def status() -> dict:
    enabled = audio.is_enabled()
    return {
        "enabled": enabled,
        "languages": audio.languages() if enabled else [],
        "voices": list(audio.VOICES) if enabled else [],
        "max_chars": settings.audio_max_chars if enabled else 0,
        "chars_per_second": audio.CHARS_PER_AUDIO_SECOND,
        "cpu_factor": audio.CPU_SECONDS_PER_AUDIO_SECOND,
    }


@router.post("/audio/render", status_code=202, summary="Ask for a transcript of one document")
def render(
    payload: AudioRenderIn,
    tasks: BackgroundTasks,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    if not audio.is_enabled():
        raise HTTPException(status_code=503, detail="Audio is not enabled on this instance.")

    document, visible, writable, fallback = _resolve(db, payload.owner_type, payload.owner_id, user)
    if not visible:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not writable:
        raise HTTPException(status_code=403, detail="You cannot generate audio for this document.")
    if payload.voice not in audio.VOICES:
        raise HTTPException(status_code=422, detail="voice must be female or male.")

    # An explicit language is honoured or refused; it is never quietly replaced
    # by the document's language, which would produce audio nobody can use.
    requested = (payload.language or "").strip().lower().split("-")[0]
    if requested and requested not in audio.languages():
        raise HTTPException(
            status_code=422,
            detail={
                "message": "This instance has no voice for that language.",
                "languages": audio.languages(),
            },
        )
    language = requested or audio.normalise_language(fallback, "en")

    try:
        chunks, digest, chars = audio.script_for(db, payload.owner_type, payload.owner_id, language)
    except audio.AudioUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    key = hashlib.sha256(
        f"{payload.owner_type}:{payload.owner_id}:{language}:{payload.voice}:{digest}".encode()
    ).hexdigest()[:32]
    try:
        job = wiki_ai.claim_job(
            db,
            user=user,
            kind="audio",
            key=f"audio:{key}",
            target_type=payload.owner_type,
            target_id=payload.owner_id,
            payload={
                "owner_type": payload.owner_type,
                "owner_id": payload.owner_id,
                "voice": payload.voice,
                "language": language,
                "fallback": fallback,
                "segments": len(chunks),
                "chars": chars,
            },
        )
    except wiki_ai.JobConflict as conflict:
        raise HTTPException(
            status_code=409,
            detail={"message": "This transcript is already being generated.", "job_id": conflict.job_id},
        ) from conflict

    audit.record(db, "audio.render", user=user, detail=f"{payload.owner_type}:{payload.owner_id} {language}/{payload.voice}")
    tasks.add_task(wiki_ai.run_job, job.id)
    return {
        "job_id": job.id,
        "segments": len(chunks),
        "chars": chars,
        **audio.estimate(chars),
    }


@router.get("/audio/renditions", summary="The ready transcripts of one document")
def renditions(
    owner_type: str,
    owner_id: int,
    language: str | None = None,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> dict:
    if not audio.is_enabled():
        return {"enabled": False, "renditions": []}
    document, visible, _, fallback = _resolve(db, owner_type, owner_id, user)
    if not visible:
        return {"enabled": True, "renditions": []}

    query = select(AudioRendition).where(
        AudioRendition.owner_type == owner_type, AudioRendition.owner_id == owner_id
    )
    if language:
        query = query.where(AudioRendition.language == audio.normalise_language(language, fallback))
    rows = db.scalars(query.order_by(AudioRendition.created_at.desc())).all()

    out = []
    for row in rows:
        # An edited document must not play yesterday's text: the hash of the
        # script as it stands now decides whether this rendition still counts.
        stale = audio.current_hash(db, owner_type, owner_id, row.language) != row.content_hash
        if stale:
            continue
        out.append(
            {
                "id": row.id,
                "language": row.language,
                "voice": row.voice,
                "title": row.title,
                "seconds": row.total_seconds,
                "segments": row.segments,
                "created_at": row.created_at,
            }
        )
    return {"enabled": True, "renditions": out}


@router.delete("/audio/renditions/{rendition_id}", status_code=204, summary="Remove one transcript")
def delete_rendition(
    rendition_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    row = db.get(AudioRendition, rendition_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    _, visible, writable, _ = _resolve(db, row.owner_type, row.owner_id, user)
    if not visible:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    if not writable:
        raise HTTPException(status_code=403, detail="You cannot remove this transcript.")
    db.delete(row)
    db.commit()
    audit.record(db, "audio.delete", user=user, detail=f"{row.owner_type}:{row.owner_id}")


@router.get("/audio/jobs/{job_id}", summary="Progress of a transcript request")
def job_status(
    job_id: int,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    job = db.get(AiJob, job_id)
    if job is None or (job.user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "result": job.result or {},
    }
