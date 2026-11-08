# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Public instance description used by the interface before anyone signs in.

The single-page app needs to know what this instance is before it can render:
whether it is a demo (the landing page is the presentation) or a private
deployment (the wiki listing is the entry point), whether AI is on, and which
identity providers to offer. None of this is sensitive; all of it would
otherwise require a second round-trip per feature flag.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import runtime
from ..config import settings
from ..db import get_db
from ..models import SUPPORTED_LANGUAGES, SsoProvider
from ..sso import public_providers

router = APIRouter(prefix="/api/v1", tags=["system"])

VERSION = "3.0.0"


@router.get("/meta", summary="Public instance description and feature flags")
def meta(db: OrmSession = Depends(get_db)) -> dict:
    config = runtime.ai_config(db)
    providers = db.scalars(
        select(SsoProvider).where(SsoProvider.enabled.is_(True)).order_by(SsoProvider.label)
    ).all()
    return {
        "name": runtime.instance_name(db),
        "version": VERSION,
        "demo_mode": bool(settings.demo_mode),
        "github_url": settings.github_url,
        "registration_open": runtime.registration_open(db),
        "languages": list(SUPPORTED_LANGUAGES),
        "ai": {
            "enabled": bool(config.enabled),
            # Configured but enabled is not enough: a provider without a model
            # name would fail every call, and the interface must not offer it.
            "available": bool(config.enabled and config.configured),
            "model": config.model if config.configured else "",
            "min_interval_seconds": config.min_interval_seconds,
        },
        "mail": {"configured": runtime.mail_config(db).configured},
        "sso": public_providers(providers) if settings.sso_enabled else [],
        "mcp": {
            "enabled": bool(settings.mcp_enabled),
            "endpoint": "/mcp",
            "requires_auth": bool(settings.mcp_require_auth),
        },
        "uploads": {"max_bytes": settings.max_upload_bytes},
    }
