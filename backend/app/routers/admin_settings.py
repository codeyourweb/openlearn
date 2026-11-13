# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Administration of the instance itself: AI provider, mail, SSO, audit log.

Everything here is behind :func:`require_admin`. Secrets are write-only: the
form learns whether a key is set, never its value, and clearing is explicit.
"""

from __future__ import annotations

import re
import time
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as OrmSession

from .. import audit, log_forward, mailer, runtime, sso
from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..models import AiErrorLog, LogTarget, SsoProvider, User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


class SettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class LogTargetIn(BaseModel):
    """One collector.

    Both shapes travel in the same body so the interface can post one object
    without deciding the kind first; the unused half is simply ignored.
    """

    label: str = Field(default="", max_length=80)
    kind: Literal["syslog", "http"] = "http"
    enabled: bool = True
    # syslog
    host: str = Field(default="", max_length=200)
    port: int = Field(default=514, ge=1, le=65535)
    protocol: Literal["udp", "tcp", "tls"] = "udp"
    facility: int = Field(default=13, ge=0, le=23)
    hostname: str = Field(default="", max_length=80)
    tls_verify: bool = True
    # http
    url: str = Field(default="", max_length=500)
    timeout_seconds: int = Field(default=5, ge=1, le=60)
    verify_tls: bool = True
    # ``intake-key`` for Sekoia, ``Authorization: Splunk …`` for a HEC, nothing
    # for a plain webhook: a collector's credentials are the operator's business.
    headers: dict[str, str] = Field(default_factory=dict)


class MailTestIn(BaseModel):
    to: str = Field(min_length=3, max_length=254)


class ProviderIn(BaseModel):
    slug: str = Field(min_length=2, max_length=40)
    label: str = Field(min_length=2, max_length=80)
    kind: str = "oidc"
    enabled: bool = True
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = "openid email profile"
    metadata_url: str = ""
    entity_id: str = ""
    sso_url: str = ""
    x509_cert: str = ""
    auto_create_users: bool = True
    allowed_domains: str = ""


class ProviderPatch(BaseModel):
    label: str | None = None
    kind: str | None = None
    enabled: bool | None = None
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: str | None = None
    metadata_url: str | None = None
    entity_id: str | None = None
    sso_url: str | None = None
    x509_cert: str | None = None
    auto_create_users: bool | None = None
    allowed_domains: str | None = None


def _public_base(request: Request | None) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request is None:
        return ""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


def _provider_out(provider: SsoProvider, base: str = "") -> dict[str, Any]:
    return {
        "id": provider.id,
        "slug": provider.slug,
        "label": provider.label,
        "kind": provider.kind,
        "enabled": provider.enabled,
        # The client secret never leaves the server: the form only learns if
        # one is stored, and can replace it.
        "has_secret": bool(provider.client_secret),
        "issuer": provider.issuer,
        "client_id": provider.client_id,
        "scopes": provider.scopes,
        "metadata_url_setting": provider.metadata_url,
        "entity_id": provider.entity_id,
        "sso_url": provider.sso_url,
        "has_certificate": bool(provider.x509_cert),
        "auto_create_users": provider.auto_create_users,
        "allowed_domains": provider.allowed_domains,
        "ready": sso.provider_is_ready(provider),
        "callback_url": f"{base}/api/v1/auth/sso/{provider.slug}/callback",
        "metadata_url": f"{base}/api/v1/auth/sso/{provider.slug}/metadata",
        "acs_url": f"{base}/api/v1/auth/sso/{provider.slug}/acs",
    }


@router.get("/settings", summary="Effective settings, secrets masked")
def read_settings(db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    return {
        "sections": runtime.describe(db),
        "environment": {
            "demo_mode": settings.demo_mode,
            "ai_bootstrap_enabled": settings.ai_enabled,
            "mail_bootstrap_enabled": settings.mail_enabled,
            "sso_enabled": settings.sso_enabled,
            "mcp_enabled": settings.mcp_enabled,
            "tls_enabled": bool(settings.tls_cert_file and settings.tls_key_file),
            "database": "sqlite" if settings.is_sqlite else ("postgresql" if settings.is_postgres else "mysql"),
        },
    }


@router.put("/settings", summary="Update one or more settings")
def write_settings(
    payload: SettingsIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    unknown = [key for key in payload.values if key not in runtime.SPEC]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown setting(s): {', '.join(sorted(unknown))}")
    try:
        applied = runtime.set_many(db, payload.values, user_id=admin.id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Which keys an administrator changed, never what they are worth: the value
    # of `log.http_token` or `ai.api_key` must not reach the collector.
    audit.record(
        db,
        "settings_changed",
        request,
        None,
        ",".join(sorted(applied))[:300],
        user=admin,
        target={"type": "settings", "id": ",".join(sorted({k.split(".")[0] for k in applied}))},
        source="admin",
    )
    return {"applied": sorted(applied), "sections": runtime.describe(db)}


@router.get("/log/status", summary="Audit forwarding: targets, counters, last error")
def log_status(_admin: User = Depends(require_admin)) -> dict[str, Any]:
    return log_forward.status()


@router.post("/log/test", summary="Send one test event to the collector")
def log_test(
    request: Request,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Prove the wiring now rather than during an incident.

    The event is delivered synchronously (an administrator is waiting for the
    answer) and is itself recorded: a test that leaves a trace at the collector
    and in the local trail is the whole point.
    """
    result = log_forward.send_test()
    audit.record(
        db,
        "audit_test_sent",
        request,
        None,
        "ok" if result.get("ok") else str(result.get("targets") or result.get("error"))[:300],
        user=admin,
        source="admin",
    )
    return result


# --------------------------------------------------------------------------- #
# Audit forwarding targets: a fan-out, not a pair of settings

_HEADER_NAME = log_forward.HEADER_NAME


def _clean_headers(raw: dict[str, str], previous: dict[str, str] | None = None) -> dict[str, str]:
    """Validate header names and values; keep a stored secret left blank.

    The interface never receives the value of a credential header, so a blank
    field means "unchanged", exactly like the password fields of the settings
    form. A blank non-secret header is a removal.
    """
    previous = previous or {}
    out: dict[str, str] = {}
    for name, value in raw.items():
        name = str(name).strip()
        if not name:
            continue
        if not _HEADER_NAME.match(name):
            raise HTTPException(status_code=422, detail=f"Invalid header name: {name[:60]}")
        text = str(value or "")
        # A newline inside a header is a request-splitting attempt.
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise HTTPException(status_code=422, detail=f"Header {name[:60]} contains control characters.")
        if not text:
            if log_forward.SECRET_HEADER.search(name) and previous.get(name):
                out[name] = previous[name]
            continue
        out[name] = text[:500]
    return out


def _target_values(payload: LogTargetIn, previous: LogTarget | None = None) -> dict[str, Any]:
    if payload.kind == "syslog":
        host = payload.host.strip()
        if not host:
            raise HTTPException(status_code=422, detail="A syslog target needs a host.")
        if any(char in host for char in "\r\n <>\"'"):
            raise HTTPException(status_code=422, detail="That host name is not acceptable.")
        return {
            "label": payload.label.strip() or host[:80],
            "kind": "syslog",
            "enabled": payload.enabled,
            "host": host,
            "port": payload.port,
            "protocol": payload.protocol,
            "facility": payload.facility,
            "hostname": payload.hostname.strip()[:80],
            "tls_verify": payload.tls_verify,
        }
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        # Only a webhook: no file://, no gopher://, nothing httpx would open.
        raise HTTPException(status_code=422, detail="An HTTP target needs an http(s) URL.")
    return {
        "label": payload.label.strip() or url.split("//", 1)[-1][:80],
        "kind": "http",
        "enabled": payload.enabled,
        "url": url,
        "timeout_seconds": payload.timeout_seconds,
        "verify_tls": payload.verify_tls,
        "headers": _clean_headers(payload.headers, (previous.headers or {}) if previous else None),
    }


def _target_out(row: LogTarget) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "kind": row.kind,
        "enabled": row.enabled,
        "host": row.host,
        "port": row.port,
        "protocol": row.protocol,
        "facility": row.facility,
        "hostname": row.hostname,
        "tls_verify": row.tls_verify,
        "url": row.url,
        "timeout_seconds": row.timeout_seconds,
        "verify_tls": row.verify_tls,
        "headers": log_forward.mask_headers(row.headers or {}),
        "updated_at": row.updated_at,
    }


@router.get("/log/targets", summary="Every destination of the audit trail")
def list_log_targets(
    db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    rows = db.scalars(select(LogTarget).order_by(LogTarget.kind, LogTarget.id)).all()
    legacy = not rows
    return {
        "items": [_target_out(row) for row in rows],
        # While the table is empty, the bootstrap settings are what actually
        # forwards: saying so avoids an empty page that hides a live collector.
        "using_environment": legacy,
        "legacy": {
            "syslog": bool(runtime.log_config(db).syslog_host),
            "http": bool(runtime.log_config(db).http_url),
        },
    }


@router.post("/log/targets", status_code=status.HTTP_201_CREATED, summary="Add a destination")
def create_log_target(
    payload: LogTargetIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    values = _target_values(payload)
    row = LogTarget(**values)
    db.add(row)
    db.commit()
    db.refresh(row)
    runtime.invalidate()
    audit.record(
        db, "log_target_created", request, None, f"{row.kind}:{row.label}"[:300],
        user=admin, target={"type": "log_target", "id": row.id}, source="admin",
    )
    return _target_out(row)


@router.put("/log/targets/{target_id}", summary="Change a destination")
def update_log_target(
    target_id: int,
    payload: LogTargetIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    row = db.get(LogTarget, target_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    values = _target_values(payload, row)
    # Switching kind leaves the other half's columns behind; clear them so a
    # syslog row cannot keep a stale URL that a later read would report.
    cleared = (
        {"url": "", "headers": {}, "timeout_seconds": 5, "verify_tls": True}
        if values["kind"] == "syslog"
        else {"host": "", "port": 514, "protocol": "udp", "hostname": "", "tls_verify": True}
    )
    for key, value in {**cleared, **values}.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    runtime.invalidate()
    audit.record(
        db, "log_target_updated", request, None, f"{row.kind}:{row.label}"[:300],
        user=admin, target={"type": "log_target", "id": row.id}, source="admin",
    )
    return _target_out(row)


@router.delete("/log/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log_target(
    target_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    row = db.get(LogTarget, target_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    label = f"{row.kind}:{row.label}"
    db.delete(row)
    db.commit()
    runtime.invalidate()
    audit.record(
        db, "log_target_deleted", request, None, label[:300],
        user=admin, target={"type": "log_target", "id": target_id}, source="admin",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/log/targets/{target_id}/test", summary="Send one test event to that destination")
def test_log_target(
    target_id: int,
    request: Request,
    db: OrmSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    row = db.get(LogTarget, target_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    target = next(
        (item for item in runtime.log_targets(db) if item.id == target_id), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found.")
    if not target.ready:
        return {"ok": False, "detail": "This destination is disabled or incomplete.", "targets": {}}
    result = log_forward.send_test(target=target)
    audit.record(
        db, "audit_test_sent", request, None,
        f"{target.key}:{'ok' if result.get('ok') else 'failed'}"[:300],
        user=admin,
        target={"type": "log_target", "id": target_id},
        source="admin",
    )
    return result


# --------------------------------------------------------------------------- #
# The environment, read-only

#: A field whose name says it holds a credential is shown as "set", never printed.
_SECRET_FIELD = re.compile(r"(password|secret|token|key|credential)", re.IGNORECASE)
_URL_CREDENTIALS = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


def _environment_rows() -> list[dict[str, Any]]:
    """Every ``OL_*`` the process reads, with the value it actually runs with.

    The point is not to edit them — that is the settings page — but to answer the
    question an operator asks at 2 a.m.: what is this instance really configured
    with? Values come from the loaded settings object, so a variable set in the
    compose file but ignored by the process shows as it is used, not as declared.
    """
    rows: list[dict[str, Any]] = []
    fields = type(settings).model_fields
    for name, declared in fields.items():
        env = f"OL_{name.upper()}"
        raw = getattr(settings, name, None)
        secret = bool(_SECRET_FIELD.search(name))
        if secret:
            shown = "set" if raw else ""
        elif isinstance(raw, (bool, int, float)) or raw is None:
            shown = raw
        else:
            shown = _URL_CREDENTIALS.sub(r"\1***@", str(raw))
        rows.append(
            {
                "name": name,
                "env": env,
                "type": declared.annotation.__name__ if hasattr(declared.annotation, "__name__") else "str",
                "secret": secret,
                "value": shown,
                "is_default": raw == declared.default,
                "section": name.split("_")[0],
                # GitHub keeps underscores in a heading anchor, so the link and
                # the generated documentation agree by construction.
                "doc": f"{settings.github_url.rstrip('/')}/blob/main/docs/ENVIRONMENT.md#{env.lower()}",
            }
        )
    return rows


@router.get("/environment", summary="The OL_* variables this instance runs with (read-only)")
def read_environment(_admin: User = Depends(require_admin)) -> dict[str, Any]:
    rows = _environment_rows()
    return {
        "items": rows,
        "docs": f"{settings.github_url.rstrip('/')}/blob/main/docs/ENVIRONMENT.md",
        "count": len(rows),
    }


@router.post("/settings/ai/test", summary="Call the configured model once")
def test_ai(db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict[str, Any]:
    config = runtime.ai_config(db)
    if not config.configured:
        return {"ok": False, "detail": "The provider is not configured yet."}
    started = time.monotonic()
    try:
        with httpx.Client(timeout=min(config.timeout_seconds, 60)) as client:
            response = client.post(
                config.base_url + "/chat/completions",
                json={
                    "model": config.model,
                    "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
                    # 8 tokens was enough for a plain model and empty for a
                    # reasoning one, which spent them all thinking.
                    "max_tokens": 200,
                    "temperature": 0,
                },
                headers={"Authorization": f"Bearer {config.api_key}"} if config.api_key else {},
            )
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            runtime.record_ai_error(
                operation="admin-test",
                model=config.model,
                base_url=config.base_url,
                status_code=response.status_code,
                detail=response.text[:2000],
            )
            return {
                "ok": False,
                "status": response.status_code,
                "latency_ms": latency,
                "detail": "The provider rejected the request. See the AI error log.",
            }
        try:
            message = response.json()["choices"][0]["message"]
            answer = (message.get("content") or message.get("reasoning_content") or "")
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            answer = ""
        return {
            "ok": True,
            "status": response.status_code,
            "latency_ms": latency,
            "model": config.model,
            "answer": str(answer)[:120],
        }
    except httpx.HTTPError as exc:
        latency = int((time.monotonic() - started) * 1000)
        runtime.record_ai_error(
            operation="admin-test",
            model=config.model,
            base_url=config.base_url,
            status_code=None,
            detail=str(exc),
        )
        return {"ok": False, "latency_ms": latency, "detail": "The provider is unreachable."}


@router.post("/settings/mail/test", summary="Send a test message")
def test_mail(
    payload: MailTestIn,
    db: OrmSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    if not mailer.is_configured():
        return {"ok": False, "detail": "No SMTP server is configured."}
    try:
        mailer.send(mailer.test_message(to=payload.to, instance=runtime.instance_name(db)))
    except mailer.MailError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": f"Test message sent to {payload.to}."}


@router.get("/ai/errors", summary="Model provider failures, newest first")
def ai_errors(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: OrmSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(AiErrorLog)) or 0
    rows = db.scalars(
        select(AiErrorLog).order_by(AiErrorLog.created_at.desc(), AiErrorLog.id.desc()).limit(limit).offset(offset)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "created_at": row.created_at,
                "operation": row.operation,
                "model": row.model,
                "base_url": row.base_url,
                "status_code": row.status_code,
                "detail": row.detail,
                "user_id": row.user_id,
            }
            for row in rows
        ],
    }


@router.delete("/ai/errors", status_code=status.HTTP_204_NO_CONTENT)
def clear_ai_errors(db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)):
    db.execute(delete(AiErrorLog))
    db.commit()


@router.get("/sso/providers", summary="Identity providers")
def list_providers(
    request: Request, db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict[str, Any]]:
    rows = db.scalars(select(SsoProvider).order_by(SsoProvider.label)).all()
    base = _public_base(request)
    return [_provider_out(row, base) for row in rows]


@router.post("/sso/providers", status_code=status.HTTP_201_CREATED, summary="Add an identity provider")
def create_provider(
    payload: ProviderIn,
    request: Request,
    db: OrmSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    slug = payload.slug.strip().lower()
    if not SLUG.match(slug):
        raise HTTPException(status_code=422, detail="Slug must use lowercase letters, digits and dashes.")
    if payload.kind not in {"oidc", "saml"}:
        raise HTTPException(status_code=422, detail="kind must be 'oidc' or 'saml'.")
    if db.scalar(select(SsoProvider).where(SsoProvider.slug == slug)) is not None:
        raise HTTPException(status_code=409, detail="Another provider already uses this slug.")
    values = payload.model_dump()
    values["slug"] = slug
    provider = SsoProvider(**values)
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _provider_out(provider, _public_base(request))


@router.patch("/sso/providers/{provider_id}", summary="Update an identity provider")
def update_provider(
    provider_id: int,
    payload: ProviderPatch,
    request: Request,
    db: OrmSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    provider = db.get(SsoProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    for key, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(provider, key, value)
    if provider.kind not in {"oidc", "saml"}:
        raise HTTPException(status_code=422, detail="kind must be 'oidc' or 'saml'.")
    db.add(provider)
    db.commit()
    db.refresh(provider)
    # A changed issuer invalidates the cached discovery document.
    sso.discovery_cache_clear()
    return _provider_out(provider, _public_base(request))


@router.delete("/sso/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider_id: int, db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)
):
    provider = db.get(SsoProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    db.delete(provider)
    db.commit()


@router.post("/sso/providers/{provider_id}/test", summary="Check that a provider is reachable")
def test_provider(
    provider_id: int, db: OrmSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> dict[str, Any]:
    provider = db.get(SsoProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    if provider.kind == "saml":
        return {"ok": sso.provider_is_ready(provider), "detail": "SAML configuration is complete." if sso.provider_is_ready(provider) else "SSO URL, entity ID and certificate are required."}
    if not sso.provider_is_ready(provider):
        return {"ok": False, "detail": "Issuer and client ID are required."}
    try:
        document = sso.discovery(provider)
    except sso.SsoError as exc:
        return {"ok": False, "detail": str(exc)}
    return {
        "ok": True,
        "issuer": document.get("issuer"),
        "authorization_endpoint": document.get("authorization_endpoint"),
        "scopes_supported": document.get("scopes_supported", [])[:10],
    }
