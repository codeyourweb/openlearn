# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Single sign-on: OpenID Connect and SAML 2.0 service provider.

Two protocols, one idea: an administrator declares an identity provider in the
interface, and users land on it from the login page. Nothing here trusts the
provider blindly — the ID token signature, issuer, audience and nonce are all
verified, and the SAML assertion is validated by the OneLogin toolkit in strict
mode. An SSO login only ever yields an email address; the local account and its
roles stay ours.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from .config import settings
from .models import SsoProvider

logger = logging.getLogger(__name__)

_DISCOVERY_TTL = 3600
_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_clients: dict[str, tuple[float, jwt.PyJWKClient]] = {}


class SsoError(RuntimeError):
    """Raised when the provider cannot be reached or its answer is rejected."""


@dataclass(frozen=True)
class ProviderInfo:
    id: int
    slug: str
    label: str
    kind: str


def discovery_cache_clear() -> None:
    _discovery_cache.clear()
    _jwks_clients.clear()


def public_providers(providers: list[SsoProvider]) -> list[dict[str, str]]:
    return [
        {"slug": p.slug, "label": p.label, "kind": p.kind}
        for p in providers
        if p.enabled and provider_is_ready(p)
    ]


def provider_is_ready(provider: SsoProvider) -> bool:
    if provider.kind == "saml":
        return bool(provider.sso_url and provider.entity_id and provider.x509_cert)
    return bool(provider.issuer and provider.client_id)


def base_url(request_base: str) -> str:
    """Public base URL used to build callback URLs the IdP will call back."""
    return (settings.public_base_url or request_base).rstrip("/")


# --------------------------------------------------------------------------- #
# OpenID Connect


def discovery(provider: SsoProvider) -> dict:
    issuer = provider.issuer.rstrip("/")
    cached = _discovery_cache.get(issuer)
    now = time.monotonic()
    if cached and now - cached[0] < _DISCOVERY_TTL:
        return cached[1]
    url = issuer + "/.well-known/openid-configuration"
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            document = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError(f"Provider discovery failed: {exc}") from exc
    if not document.get("authorization_endpoint") or not document.get("token_endpoint"):
        raise SsoError("Provider discovery document is incomplete.")
    _discovery_cache[issuer] = (time.monotonic(), document)
    return document


def _jwks_client(provider: SsoProvider, document: dict) -> jwt.PyJWKClient:
    uri = document.get("jwks_uri") or ""
    if not uri:
        raise SsoError("Provider publishes no JWKS endpoint.")
    cached = _jwks_clients.get(uri)
    if cached and time.monotonic() - cached[0] < _DISCOVERY_TTL:
        return cached[1]
    client = jwt.PyJWKClient(uri, cache_keys=True, lifespan=_DISCOVERY_TTL)
    _jwks_clients[uri] = (time.monotonic(), client)
    return client


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    provider: SsoProvider, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
) -> str:
    document = discovery(provider)
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": provider.scopes or "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Ask the IdP to show the account picker instead of silently reusing a
        # session: shared computers are the norm in classrooms.
        "prompt": "select_account",
    }
    separator = "&" if "?" in document["authorization_endpoint"] else "?"
    return document["authorization_endpoint"] + separator + urlencode(params)


def exchange_code(
    provider: SsoProvider, *, code: str, redirect_uri: str, code_verifier: str, nonce: str
) -> dict:
    document = discovery(provider)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "code_verifier": code_verifier,
    }
    if provider.client_secret:
        data["client_secret"] = provider.client_secret
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(document["token_endpoint"], data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise SsoError(f"Token exchange failed: {exc}") from exc
    if response.status_code >= 400:
        raise SsoError(f"Token exchange rejected ({response.status_code}).")
    try:
        tokens = response.json()
    except ValueError as exc:
        raise SsoError("Token endpoint did not answer with JSON.") from exc

    claims: dict = {}
    id_token = tokens.get("id_token")
    if id_token:
        claims = decode_id_token(provider, id_token, nonce=nonce)
    if not claims.get("email"):
        # Some providers only expose the profile through userinfo.
        access_token = tokens.get("access_token")
        if access_token:
            endpoint = document.get("userinfo_endpoint")
            if endpoint:
                with httpx.Client(timeout=15) as client:
                    info = client.get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
                if info.status_code < 400:
                    claims.update(info.json())
    if not claims.get("email"):
        raise SsoError("The provider returned no email address.")
    return claims


def decode_id_token(provider: SsoProvider, id_token: str, *, nonce: str) -> dict:
    document = discovery(provider)
    try:
        key = _jwks_client(provider, document).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=document.get("id_token_signing_alg_values_supported") or ["RS256"],
            audience=provider.client_id,
            issuer=provider.issuer.rstrip("/"),
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise SsoError(f"ID token rejected: {exc}") from exc
    token_nonce = claims.get("nonce")
    if token_nonce and nonce and not secrets.compare_digest(str(token_nonce), nonce):
        raise SsoError("ID token nonce mismatch.")
    return claims


# --------------------------------------------------------------------------- #
# SAML 2.0


def saml_settings(provider: SsoProvider, *, acs_url: str, metadata_url: str) -> dict:
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": metadata_url.replace("/metadata", ""),
            "assertionConsumerService": {
                "url": acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": "",
            "privateKey": "",
        },
        "idp": {
            "entityId": provider.entity_id,
            "singleSignOnService": {
                "url": provider.sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": provider.x509_cert,
        },
        "security": {
            "authnRequestsSigned": False,
            "logoutRequestSigned": False,
            "logoutResponseSigned": False,
            "signMetadata": False,
            "wantMessagesSigned": False,
            "wantAssertionsSigned": True,
            "wantAssertionsEncrypted": False,
            "wantNameId": True,
            "wantNameIdEncrypted": False,
            "requestedAuthnContext": False,
            "rejectUnsolicitedResponsesWithInResponseTo": True,
        },
    }


def _saml_auth(provider: SsoProvider, request_data: dict, *, acs_url: str, metadata_url: str):
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    return OneLogin_Saml2_Auth(request_data, saml_settings(provider, acs_url=acs_url, metadata_url=metadata_url))


def saml_request_data(*, public_url: str, post_data: dict | None = None) -> dict:
    from urllib.parse import urlsplit

    parts = urlsplit(public_url)
    secure = parts.scheme == "https"
    return {
        "https": "on" if secure else "off",
        "http_host": parts.hostname or "localhost",
        "server_port": str(parts.port or (443 if secure else 80)),
        "script_name": parts.path or "/",
        "get_data": {},
        "post_data": post_data or {},
    }


def saml_login_url(provider: SsoProvider, *, public_url: str, acs_url: str, metadata_url: str, relay_state: str) -> str:
    auth = _saml_auth(provider, saml_request_data(public_url=public_url), acs_url=acs_url, metadata_url=metadata_url)
    return auth.login(return_to=relay_state, stay=True)


def saml_consume(
    provider: SsoProvider, *, public_url: str, acs_url: str, metadata_url: str, post_data: dict
) -> dict:
    auth = _saml_auth(
        provider,
        saml_request_data(public_url=public_url, post_data=post_data),
        acs_url=acs_url,
        metadata_url=metadata_url,
    )
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        raise SsoError("SAML assertion rejected: " + ", ".join(errors))
    if not auth.is_authenticated():
        raise SsoError("SAML assertion is not authenticated.")
    attributes = auth.get_attributes() or {}
    email = ""
    for key in ("email", "mail", "emailaddress", "urn:oid:0.9.2342.19200300.100.1.3"):
        values = attributes.get(key) or []
        if values:
            email = values[0]
            break
    if not email:
        name_id = auth.get_nameid() or ""
        if "@" in name_id:
            email = name_id
    if not email:
        raise SsoError("The SAML assertion carries no email address.")
    return {
        "email": email,
        "name": (attributes.get("displayName") or attributes.get("cn") or [""])[0],
        "subject": auth.get_nameid() or email,
    }


def sp_metadata(provider: SsoProvider, *, acs_url: str, metadata_url: str) -> str:
    auth = _saml_auth(provider, saml_request_data(public_url=metadata_url), acs_url=acs_url, metadata_url=metadata_url)
    return auth.get_settings().get_sp_metadata()


def dump(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"))
