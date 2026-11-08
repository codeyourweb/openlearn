# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Runtime configuration: administrator-editable settings on top of the environment.

The ``OL_*`` environment stays the bootstrap and the fallback. Anything an
administrator changes in the interface is stored in ``app_settings`` and wins
over the environment, so an instance can be reconfigured without a redeploy.

Two rules keep this module safe:

* secrets are written but never read back through the API — the admin UI only
  learns *whether* a secret is set, and can clear it;
* every value is typed and validated here, not in the routers, because a bad
  ``ai.timeout_seconds`` would otherwise reach ``httpx`` as a string.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .config import settings
from .db import SessionLocal
from .models import AppSetting

logger = logging.getLogger(__name__)

# key -> (type, attribute on Settings, secret)
SPEC: dict[str, tuple[type, str, bool]] = {
    "ai.enabled": (bool, "ai_enabled", False),
    "ai.base_url": (str, "ai_base_url", False),
    "ai.api_key": (str, "ai_api_key", True),
    "ai.model": (str, "ai_model", False),
    "ai.wiki_model": (str, "ai_wiki_model", False),
    "ai.timeout_seconds": (int, "ai_timeout_seconds", False),
    "ai.min_interval_seconds": (int, "ai_min_interval_seconds", False),
    "mail.enabled": (bool, "mail_enabled", False),
    "mail.host": (str, "mail_host", False),
    "mail.port": (int, "mail_port", False),
    "mail.username": (str, "mail_username", False),
    "mail.password": (str, "mail_password", True),
    "mail.from_address": (str, "mail_from_address", False),
    "mail.from_name": (str, "mail_from_name", False),
    "mail.starttls": (bool, "mail_starttls", False),
    "mail.ssl": (bool, "mail_ssl", False),
    "security.registration_open": (bool, None, False),
    "security.password_reset_ttl_minutes": (int, "password_reset_ttl_minutes", False),
    "instance.name": (str, "instance_name", False),
}

# Defaults for keys that have no ``Settings`` attribute.
_FALLBACK: dict[str, Any] = {
    "security.registration_open": True,
}

SECTIONS: dict[str, tuple[str, ...]] = {
    "ai": tuple(k for k in SPEC if k.startswith("ai.")),
    "mail": tuple(k for k in SPEC if k.startswith("mail.")),
    "security": tuple(k for k in SPEC if k.startswith("security.")),
    "instance": tuple(k for k in SPEC if k.startswith("instance.")),
}

_LIMITS: dict[str, tuple[int | None, int | None]] = {
    "ai.timeout_seconds": (5, 900),
    "ai.min_interval_seconds": (0, 3600),
    "mail.port": (1, 65535),
    "security.password_reset_ttl_minutes": (5, 24 * 60),
}

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 3.0


def _coerce(key: str, raw: Any) -> Any:
    kind, _attr, _secret = SPEC[key]
    if kind is bool:
        if isinstance(raw, bool):
            value = raw
        elif isinstance(raw, str):
            value = raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            value = bool(raw)
        return value
    if kind is int:
        value = int(raw)
        low, high = _LIMITS.get(key, (None, None))
        if low is not None and value < low:
            raise ValueError(f"{key} must be at least {low}.")
        if high is not None and value > high:
            raise ValueError(f"{key} must be at most {high}.")
        return value
    text = "" if raw is None else str(raw).strip()
    if key in {"ai.base_url", "mail.host"} and text and "://" not in text and key == "ai.base_url":
        raise ValueError(f"{key} must be an http(s) URL.")
    return text


def _env_value(key: str) -> Any:
    _kind, attr, _secret = SPEC[key]
    if attr is None:
        return _FALLBACK.get(key)
    return getattr(settings, attr, None)


def _cached(key: str) -> tuple[bool, Any]:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return True, hit[1]
    return False, None


def _store(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


def invalidate() -> None:
    with _cache_lock:
        _cache.clear()


def get(db: OrmSession | None = None, key: str = "") -> Any:
    """Effective value: database override, else environment, else fallback."""
    if key not in SPEC:
        raise KeyError(key)
    fresh, value = _cached(key)
    if fresh:
        return value
    row = None
    if db is not None:
        row = db.get(AppSetting, key)
    else:
        with SessionLocal() as session:
            row = session.get(AppSetting, key)
    if row is not None and row.value != "":
        try:
            value = _coerce(key, json.loads(row.value))
            _store(key, value)
            return value
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid stored setting %s", key)
    value = _env_value(key)
    _store(key, value)
    return value


def set_many(db: OrmSession, values: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any]:
    """Store overrides. ``None`` clears a key back to its environment value."""
    applied: dict[str, Any] = {}
    for key, raw in values.items():
        if key not in SPEC:
            continue
        if raw is None:
            row = db.get(AppSetting, key)
            if row is not None:
                db.delete(row)
            applied[key] = None
            continue
        value = _coerce(key, raw)
        row = db.get(AppSetting, key)
        encoded = json.dumps(value)
        if row is None:
            db.add(AppSetting(key=key, value=encoded, updated_by_id=user_id))
        else:
            row.value = encoded
            row.updated_by_id = user_id
        applied[key] = value
    db.commit()
    invalidate()
    return applied


def describe(db: OrmSession) -> dict[str, Any]:
    """Values for the admin form: secrets are reduced to a boolean."""
    stored = {row.key: row for row in db.scalars(select(AppSetting)).all()}
    sections: dict[str, list[dict[str, Any]]] = {}
    for section, keys in SECTIONS.items():
        rows = []
        for key in keys:
            kind, _attr, secret = SPEC[key]
            row = stored.get(key)
            overridden = row is not None and row.value != ""
            raw = row.value if overridden else None
            value = get(db, key)
            if secret:
                shown: Any = None
                is_set = bool(value)
            else:
                shown = value
                is_set = bool(value) if isinstance(value, str) else value is not None
            rows.append(
                {
                    "key": key,
                    "type": kind.__name__,
                    "secret": secret,
                    "value": shown,
                    "is_set": is_set,
                    "overridden": overridden,
                    "env_value": None if secret else _env_value(key),
                    "stored": None if secret else (json.loads(raw) if raw else None),
                }
            )
        sections[section] = rows
    return sections


# --------------------------------------------------------------------------- #
# Typed views


@dataclass(frozen=True)
class AiConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    wiki_model: str
    timeout_seconds: int
    min_interval_seconds: int

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.model)

    @property
    def wiki_model_or_default(self) -> str:
        return self.wiki_model or self.model


def ai_config(db: OrmSession | None = None) -> AiConfig:
    return AiConfig(
        enabled=get(db, "ai.enabled"),
        base_url=(get(db, "ai.base_url") or "").rstrip("/"),
        api_key=get(db, "ai.api_key") or "",
        model=get(db, "ai.model") or "",
        wiki_model=get(db, "ai.wiki_model") or "",
        timeout_seconds=int(get(db, "ai.timeout_seconds")),
        min_interval_seconds=int(get(db, "ai.min_interval_seconds")),
    )


@dataclass(frozen=True)
class MailConfig:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    from_address: str
    from_name: str
    starttls: bool
    ssl: bool

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.host and self.from_address)


def mail_config(db: OrmSession | None = None) -> MailConfig:
    return MailConfig(
        enabled=get(db, "mail.enabled"),
        host=get(db, "mail.host") or "",
        port=int(get(db, "mail.port")),
        username=get(db, "mail.username") or "",
        password=get(db, "mail.password") or "",
        from_address=get(db, "mail.from_address") or "",
        from_name=get(db, "mail.from_name") or "OpenLearn",
        starttls=get(db, "mail.starttls"),
        ssl=get(db, "mail.ssl"),
    )


def registration_open(db: OrmSession | None = None) -> bool:
    return bool(get(db, "security.registration_open"))


def instance_name(db: OrmSession | None = None) -> str:
    return get(db, "instance.name") or "OpenLearn"


def record_ai_error(
    *,
    operation: str,
    model: str,
    base_url: str,
    status_code: int | None,
    detail: str,
    user_id: int | None = None,
) -> None:
    """Persist a provider failure for the admin log, never raising."""
    from .models import AiErrorLog  # local import keeps startup order simple

    try:
        with SessionLocal() as db:
            db.add(
                AiErrorLog(
                    operation=operation[:40],
                    model=(model or "")[:120],
                    base_url=(base_url or "")[:200],
                    status_code=status_code,
                    detail=(detail or "")[:4000],
                    user_id=user_id,
                )
            )
            db.commit()
    except Exception:  # pragma: no cover - logging must never break a request
        logger.exception("Could not record an AI error")
