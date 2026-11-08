# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Single sign-on endpoints: start, callback, SAML assertion consumer.

The flow keeps its state in a short-lived signed cookie rather than in server
memory, so several workers can serve the same login. Nothing in the callback is
trusted before the signature, issuer, audience and nonce checks of
:mod:`app.sso` have run.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import runtime, sso
from ..config import settings
from ..db import get_db
from ..deps import client_ip
from ..models import ExternalIdentity, SecurityEvent, SsoProvider, User, utcnow
from ..security import hash_password, new_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/sso", tags=["auth"])

_STATE_COOKIE = "ol_sso_state"
_STATE_TTL_SECONDS = 600


def _audit(db: OrmSession, event: str, request: Request, user_id: int | None = None, detail: str = "") -> None:
    db.add(SecurityEvent(event=event, ip=client_ip(request), user_id=user_id, detail=detail[:300]))
    db.commit()


def _public_base(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


def _provider(db: OrmSession, slug: str) -> SsoProvider:
    provider = db.scalar(select(SsoProvider).where(SsoProvider.slug == slug, SsoProvider.enabled.is_(True)))
    if provider is None or not sso.provider_is_ready(provider):
        raise HTTPException(status_code=404, detail="Unknown identity provider.")
    return provider


def _sign_state(payload: dict) -> str:
    claims = dict(payload)
    claims["exp"] = utcnow() + timedelta(seconds=_STATE_TTL_SECONDS)
    claims["iat"] = utcnow()
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")


def _read_state(request: Request, slug: str) -> dict | None:
    raw = request.cookies.get(_STATE_COOKIE)
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("provider") != slug:
        return None
    return payload


def _cookie_secure(request: Request) -> bool:
    if settings.cookie_secure:
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


@router.get("/providers", summary="Identity providers offered on the login page")
def providers(db: OrmSession = Depends(get_db)) -> list[dict[str, str]]:
    """The sign-in buttons a visitor may see, and nothing they should not.

    A provider appears once it is enabled and complete enough to run a login;
    secrets stay on the server. With single sign-on switched off the list is
    empty rather than absent: the page then simply shows no button.
    """
    if not settings.sso_enabled:
        return []
    rows = db.scalars(select(SsoProvider).where(SsoProvider.enabled.is_(True)).order_by(SsoProvider.label)).all()
    return sso.public_providers(rows)


@router.get("/{slug}/start", include_in_schema=False)
def start(slug: str, request: Request, next: str = "/", db: OrmSession = Depends(get_db)) -> Response:
    provider = _provider(db, slug)
    base = _public_base(request)
    # Only same-site paths are honoured as a destination: an absolute URL here
    # would turn the login endpoint into an open redirect.
    target = next if next.startswith("/") and not next.startswith("//") else "/"

    if provider.kind == "saml":
        acs = f"{base}/api/v1/auth/sso/{provider.slug}/acs"
        metadata = f"{base}/api/v1/auth/sso/{provider.slug}/metadata"
        url = sso.saml_login_url(
            provider, public_url=base + request.url.path, acs_url=acs, metadata_url=metadata, relay_state=target
        )
        response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            _STATE_COOKIE,
            _sign_state({"provider": slug, "next": target}),
            max_age=_STATE_TTL_SECONDS,
            httponly=True,
            secure=_cookie_secure(request),
            samesite="lax",
            path="/",
        )
        return response

    state = new_secret(24)
    nonce = new_secret(24)
    verifier, challenge = sso.pkce_pair()
    redirect_uri = f"{base}/api/v1/auth/sso/{provider.slug}/callback"
    try:
        url = sso.authorization_url(
            provider, redirect_uri=redirect_uri, state=state, nonce=nonce, code_challenge=challenge
        )
    except sso.SsoError as exc:
        logger.warning("SSO discovery failed for %s: %s", slug, exc)
        raise HTTPException(status_code=502, detail="This identity provider is unreachable.") from exc

    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        _STATE_COOKIE,
        _sign_state(
            {"provider": slug, "state": state, "nonce": nonce, "verifier": verifier, "next": target}
        ),
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )
    return response


def _login_user(db: OrmSession, request: Request, provider: SsoProvider, claims: dict, next_path: str) -> RedirectResponse:
    email = str(claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="The identity provider returned no email address.")

    allowed = [d.strip().lower() for d in (provider.allowed_domains or "").split(",") if d.strip()]
    if allowed and email.rsplit("@", 1)[-1] not in allowed:
        _audit(db, "sso_domain_rejected", request, None, email)
        raise HTTPException(status_code=403, detail="This account is not allowed on this instance.")

    subject = str(claims.get("sub") or claims.get("subject") or email)
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider_id == provider.id, ExternalIdentity.subject == subject
        )
    )
    user: User | None = None
    if identity is not None:
        user = db.get(User, identity.user_id)

    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            auto = provider.auto_create_users and settings.sso_auto_create_users
            if not auto:
                raise HTTPException(status_code=403, detail="No account matches this identity.")
            display = str(claims.get("name") or claims.get("preferred_username") or email.split("@")[0])[:60]
            user = User(
                email=email,
                # A random password nobody knows: the account is usable through
                # the provider, or through a password reset.
                password_hash=hash_password(new_secret(32)),
                display_name=display or "Member",
                is_active=True,
            )
            db.add(user)
            db.flush()
        if identity is None:
            db.add(
                ExternalIdentity(
                    user_id=user.id, provider_id=provider.id, subject=subject, email=email, last_login_at=utcnow()
                )
            )
    else:
        identity.last_login_at = utcnow()

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled.")

    user.last_login_at = utcnow()
    db.add(user)
    db.commit()
    _audit(db, "sso_login", request, user.id, provider.slug)

    # Import here: the cookie helpers live in auth.py and import settings only.
    from .auth import set_auth_cookies

    response = RedirectResponse(next_path or "/", status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(response, user, request)
    response.delete_cookie(_STATE_COOKIE, path="/")
    return response


@router.get("/{slug}/callback", include_in_schema=False)
def callback(
    slug: str,
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: OrmSession = Depends(get_db),
) -> Response:
    provider = _provider(db, slug)
    if error:
        raise HTTPException(status_code=400, detail="The identity provider refused the login.")
    stored = _read_state(request, slug)
    if stored is None or not state or not secrets.compare_digest(state, str(stored.get("state") or "")):
        raise HTTPException(status_code=400, detail="This login attempt expired. Please try again.")
    base = _public_base(request)
    redirect_uri = f"{base}/api/v1/auth/sso/{provider.slug}/callback"
    try:
        claims = sso.exchange_code(
            provider,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=str(stored.get("verifier") or ""),
            nonce=str(stored.get("nonce") or ""),
        )
    except sso.SsoError as exc:
        logger.warning("SSO callback rejected for %s: %s", slug, exc)
        _audit(db, "sso_failure", request, None, f"{slug}: {exc}"[:200])
        raise HTTPException(status_code=401, detail="Single sign-on failed. Please try again.") from exc
    return _login_user(db, request, provider, claims, str(stored.get("next") or "/"))


@router.post("/{slug}/acs", include_in_schema=False)
async def assertion_consumer_service(slug: str, request: Request, db: OrmSession = Depends(get_db)) -> Response:
    provider = _provider(db, slug)
    form = await request.form()
    post_data = {key: str(value) for key, value in form.items()}
    base = _public_base(request)
    acs = f"{base}/api/v1/auth/sso/{provider.slug}/acs"
    metadata = f"{base}/api/v1/auth/sso/{provider.slug}/metadata"
    stored = _read_state(request, slug)
    target = str(stored.get("next") or "/") if stored else "/"
    try:
        claims = sso.saml_consume(
            provider, public_url=base + request.url.path, acs_url=acs, metadata_url=metadata, post_data=post_data
        )
    except sso.SsoError as exc:
        logger.warning("SAML assertion rejected for %s: %s", slug, exc)
        _audit(db, "sso_failure", request, None, f"{slug}: {exc}"[:200])
        raise HTTPException(status_code=401, detail="Single sign-on failed. Please try again.") from exc
    return _login_user(db, request, provider, claims, target)


@router.get("/{slug}/metadata", include_in_schema=False)
def metadata(slug: str, request: Request, db: OrmSession = Depends(get_db)) -> Response:
    provider = _provider(db, slug)
    if provider.kind != "saml":
        raise HTTPException(status_code=404, detail="This provider is not SAML.")
    base = _public_base(request)
    acs = f"{base}/api/v1/auth/sso/{provider.slug}/acs"
    meta_url = f"{base}/api/v1/auth/sso/{provider.slug}/metadata"
    try:
        xml = sso.sp_metadata(provider, acs_url=acs, metadata_url=meta_url)
    except Exception as exc:  # pragma: no cover - depends on the toolkit
        logger.warning("Could not render SAML metadata: %s", exc)
        raise HTTPException(status_code=500, detail="SAML is not available on this instance.") from exc
    return Response(content=xml, media_type="application/samlmetadata+xml")


@router.get("/{slug}/ping", include_in_schema=False)
def ping(slug: str, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    provider = _provider(db, slug)
    if provider.kind == "saml":
        return {"kind": "saml", "ready": True}
    try:
        document = sso.discovery(provider)
    except sso.SsoError as exc:
        return {"kind": "oidc", "ready": False, "detail": str(exc)}
    return {
        "kind": "oidc",
        "ready": True,
        "issuer": document.get("issuer"),
        "authorization_endpoint": document.get("authorization_endpoint"),
    }
