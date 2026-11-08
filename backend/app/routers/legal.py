# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Legal notices: a public page, and the administrator form behind it.

The default notice belongs to the project and ships with the interface, so it
follows the interface language. An administrator adds the paragraphs that only
their instance can write: publisher, host, contact, retention. Those are stored
per language and rendered by :mod:`app.legal` through the wiki markdown pipeline.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from .. import ai, legal
from ..db import get_db
from ..deps import enforce_ai_interval, require_admin
from ..models import SUPPORTED_LANGUAGES, User

router = APIRouter(prefix="/api/v1", tags=["legal"])


class LegalIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class TranslateIn(BaseModel):
    target: str = Field(min_length=2, max_length=5)
    text: str = Field(default="", max_length=legal.MAX_LENGTH)
    source: str | None = None


@router.get("/legal", summary="Legal notice of this instance")
def read_notice(
    lang: str = Query("en", max_length=8),
    db: OrmSession = Depends(get_db),
) -> dict[str, Any]:
    """Public: the project notice is in the interface, this is the addition.

    ``html`` comes already rendered and sanitised, so the page never has to
    trust the browser with raw markdown from an administrator.
    """
    return legal.public_notice(db, lang)


@router.get("/admin/legal", summary="Every stored notice, for the form")
def read_all(db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    notices = legal.read(db)
    return {
        "values": {language: notice["markdown"] for language, notice in notices.items()},
        "updated_at": {language: notice["updated_at"] for language, notice in notices.items()},
        "languages": list(SUPPORTED_LANGUAGES),
        "max_length": legal.MAX_LENGTH,
    }


@router.put("/admin/legal", summary="Store the notices the administrator edited")
def write_all(
    payload: LegalIn,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    if not payload.values:
        raise HTTPException(status_code=422, detail="Nothing to save.")
    unknown = [language for language in payload.values if language not in SUPPORTED_LANGUAGES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported language(s): {', '.join(sorted(unknown))}")
    try:
        saved = legal.write(db, payload.values, user_id=admin.id)
    except legal.LegalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"saved": saved, "values": {language: notice["markdown"] for language, notice in legal.read(db).items()}}


@router.post("/admin/legal/translate", summary="Ask the model for one language")
def translate(
    payload: TranslateIn,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    if payload.target not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language: {payload.target}")
    if payload.source and payload.source not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language: {payload.source}")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="There is nothing to translate.")
    enforce_ai_interval(admin)
    if not ai.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI features are disabled on this instance.",
        )
    try:
        translated = ai.translate_markdown(text, payload.target)
    except ai.AiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"target": payload.target, "markdown": translated}
