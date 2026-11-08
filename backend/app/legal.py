# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Instance-specific legal notices.

The project ships a default legal notice with the interface, translated like
every other string. An administrator who publishes an instance usually has to
add its own: publisher, hosting, contact, retention rules. Those additions are
markdown, stored one row per language in ``app_settings``, and rendered through
the same pipeline as wiki pages: :func:`app.wiki.render_markdown` converts the
markdown and then drops everything outside the wiki allowlist with ``nh3``.

That shared pipeline is the security boundary. No raw HTML is ever stored, and
the allowlist has no ``script``, no ``iframe``, no event handler and no
``style`` attribute, so an administrator cannot turn the notice into a way to
run code, and a compromised admin session cannot be used to plant one.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .models import AppSetting, SUPPORTED_LANGUAGES
from .wiki import reflow_markdown, render_markdown

PREFIX = "legal.instance."
# Generous for a notice, small enough that the setting cannot be used as a file
# store. The rendered document is bounded by the same figure.
MAX_LENGTH = 24_000


class LegalError(ValueError):
    """The submitted notice cannot be stored as-is."""


def key_for(language: str) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise LegalError(f"Unsupported language: {language}")
    return f"{PREFIX}{language}"


def _decode(raw: str | None) -> str:
    """Settings store JSON; tolerate a plain string written by an older tool."""
    if not raw:
        return ""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return str(raw)
    return value if isinstance(value, str) else ""


def _normalise(language: str, text: str) -> str:
    """Validate one notice: markdown only, no executable construct survives."""
    value = reflow_markdown(str(text or "")).strip()
    if len(value) > MAX_LENGTH:
        raise LegalError(f"The notice for {language} is too long (max {MAX_LENGTH} characters).")
    if not value:
        return ""
    # Render once here: a document that the renderer refuses would otherwise be
    # stored and fail on every page view afterwards.
    try:
        render_markdown(value)
    except ValueError as exc:
        raise LegalError(f"The notice for {language} cannot be rendered: {exc}") from exc
    return value


def read(db: OrmSession) -> dict[str, dict[str, Any]]:
    """Every stored notice, by language, markdown only (never rendered here)."""
    rows = db.scalars(select(AppSetting).where(AppSetting.key.like(f"{PREFIX}%"))).all()
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        language = row.key[len(PREFIX) :]
        if language not in SUPPORTED_LANGUAGES:
            continue
        text = _decode(row.value)
        if not text:
            continue
        found[language] = {
            "markdown": text,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    return found


def write(db: OrmSession, values: dict[str, str], *, user_id: int | None = None) -> list[str]:
    """Store the notices given, one language each. An empty string clears it."""
    cleaned: dict[str, str] = {}
    for language, text in values.items():
        key = key_for(language)
        cleaned[key] = _normalise(language, text)

    for key, value in cleaned.items():
        row = db.get(AppSetting, key)
        payload = json.dumps(value, ensure_ascii=False)
        if row is None:
            db.add(AppSetting(key=key, value=payload, updated_by_id=user_id))
        else:
            row.value = payload
            row.updated_by_id = user_id
    db.commit()
    return sorted(key[len(PREFIX) :] for key in cleaned)


def public_notice(db: OrmSession, language: str) -> dict[str, Any]:
    """What the public page needs: the rendered addition, or nothing."""
    language = language if language in SUPPORTED_LANGUAGES else "en"
    notices = read(db)
    chosen = notices.get(language) or {}
    markdown = chosen.get("markdown", "")
    if not markdown:
        # Fall back to the nearest notice the administrator did write, so a
        # visitor reading in a language nobody filled in still sees something
        # rather than an empty page.
        for candidate in ("en", "fr"):
            alternate = notices.get(candidate) or {}
            if alternate.get("markdown"):
                chosen = alternate
                markdown = alternate["markdown"]
                break
    return {
        "language": language,
        "markdown": markdown,
        "html": render_markdown(markdown) if markdown else "",
        "updated_at": chosen.get("updated_at"),
        "has_notice": bool(markdown),
        "languages": {code: bool((notices.get(code) or {}).get("markdown")) for code in SUPPORTED_LANGUAGES},
    }
