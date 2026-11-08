# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""AI quiz generation endpoint.

A generated quiz is untrusted content: it is validated, sanitised and stored as
a draft owned by the caller, then follows the normal moderation workflow.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as OrmSession

from .. import ai, runtime
from ..config import settings
from ..content import FALLBACK_LANGUAGE
from ..db import get_db
from ..deps import enforce_ai_interval, enforce_rate_limit, require_user
from ..models import Quiz, User
from ..schemas import AiAdventureIn, AiAdventureReviseIn, AiGenerateIn, QuizIn
from .quizzes import _apply_quiz, serialise_quiz

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.get("/status")
def ai_status():
    """Whether AI assistance is available, and with which model."""
    config = runtime.ai_config()
    return {
        "available": config.configured,
        "model": config.model if config.configured else "",
        "languages": list(ai.LANGUAGE_NAMES),
        "web_search": bool(settings.search_base_url),
        # The interface hides its AI entry points when this is false.
        "enabled": bool(config.enabled),
    }


@router.post("/quizzes")
def generate_quiz(
    payload: AiGenerateIn,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    if not ai.is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI assistance is not configured on this instance.",
        )
    enforce_rate_limit(request, "ai-generate", settings.ai_rate_limit, settings.ai_rate_window_seconds)
    enforce_ai_interval(user)
    try:
        generated = ai.generate_quiz(
            topic=payload.topic,
            question_count=payload.question_count,
            mode=payload.mode,
            language=payload.language,
            level=payload.level,
        )
    except ai.AiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    generated["wrong_answer_policy"] = "zero"
    generated["mode"] = payload.mode
    generated["default_language"] = payload.language or FALLBACK_LANGUAGE

    if not payload.save:
        return {"draft": generated, "saved": None}

    quiz_in = QuizIn(
        title=generated["title"],
        description=generated.get("description", ""),
        wrong_answer_policy="zero",
        mode=payload.mode,
        default_language=payload.language,
        questions=generated["questions"],
    )
    quiz = Quiz(
        owner_id=user.id,
        title=quiz_in.title,
        description=quiz_in.description,
        wrong_answer_policy=quiz_in.wrong_answer_policy,
        mode=quiz_in.mode,
        status="draft",
        is_public=False,
        default_language=quiz_in.default_language,
        ai_generated=True,
    )
    db.add(quiz)
    db.flush()
    _apply_quiz(db, quiz, quiz_in)
    return {"draft": generated, "saved": serialise_quiz(quiz, include_answers=True)}


def _persist_adventure(db: OrmSession, user: User, generated: dict) -> Quiz:
    """Store a generated story as a draft owned by the caller."""
    quiz_in = QuizIn(
        title=generated["title"],
        description=generated.get("description", ""),
        mode="adventure",
        default_language=generated.get("default_language") or FALLBACK_LANGUAGE,
        adventure=generated["adventure"],
    )
    quiz = Quiz(
        owner_id=user.id,
        title=quiz_in.title,
        description=quiz_in.description,
        wrong_answer_policy="zero",
        mode="adventure",
        status="draft",
        is_public=False,
        default_language=quiz_in.default_language,
        ai_generated=True,
    )
    db.add(quiz)
    db.flush()
    _apply_quiz(db, quiz, quiz_in)
    db.commit()
    return quiz


@router.post("/adventures")
def generate_adventure(
    payload: AiAdventureIn,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Draft a whole branching story from a topic.

    The story is generated as one document -- scenes, choices, attributes,
    endings -- so the author reviews a playable draft instead of filling a
    template. It is stored as an ordinary draft quiz: editable, playable, and
    still subject to publication rules.
    """
    if not ai.is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI assistance is not configured on this instance.",
        )
    enforce_rate_limit(request, "ai-adventure", settings.ai_rate_limit, settings.ai_rate_window_seconds)
    enforce_ai_interval(user)
    try:
        generated = ai.generate_adventure(
            topic=payload.topic,
            brief=payload.brief,
            scene_count=payload.scene_count,
            language=payload.language,
            level=payload.level,
        )
    except ai.AiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not payload.save:
        return {"draft": generated["adventure"], "quiz": None}
    try:
        quiz = _persist_adventure(db, user, generated)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"The generated story was rejected: {exc}") from exc
    return {"draft": generated["adventure"], "quiz": serialise_quiz(quiz, include_answers=True)}


@router.post("/adventures/{quiz_id}/revise")
def revise_adventure(
    quiz_id: int,
    payload: AiAdventureReviseIn,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Rewrite an existing story from one instruction.

    The model returns the whole graph, which is normalised exactly like a fresh
    draft: keys that need no change are kept, and the result still has to be
    walkable. Nothing is written unless the author asks for it.
    """
    if not ai.is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI assistance is not configured on this instance.",
        )
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.mode != "adventure":
        raise HTTPException(status_code=404, detail="Story not found.")
    if quiz.owner_id != user.id and not user.is_staff:
        raise HTTPException(status_code=403, detail="You do not own this story.")
    enforce_rate_limit(request, "ai-adventure", settings.ai_rate_limit, settings.ai_rate_window_seconds)
    enforce_ai_interval(user)

    current = serialise_quiz(quiz, include_answers=True).get("adventure") or {}
    if not current.get("nodes"):
        raise HTTPException(status_code=409, detail="This story has no scene to revise yet.")
    try:
        revised = ai.revise_adventure(
            current,
            payload.instruction,
            language=payload.language or quiz.default_language,
        )
    except ai.AiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not payload.save:
        return {"draft": revised["adventure"], "quiz": None}
    quiz_in = QuizIn(
        title=quiz.title,
        description=quiz.description,
        mode="adventure",
        default_language=revised.get("default_language") or quiz.default_language,
        adventure=revised["adventure"],
    )
    try:
        _apply_quiz(db, quiz, quiz_in)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"The revised story was rejected: {exc}") from exc
    return {"draft": revised["adventure"], "quiz": serialise_quiz(quiz, include_answers=True, viewer=user)}
