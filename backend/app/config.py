# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Application configuration.

All settings can be overridden through environment variables prefixed with
``OL_`` (for example ``OL_DATABASE_URL``). Defaults target a self-hosted
single-node deployment.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def public_base_url_problem(value: str) -> str | None:
    """Why the configured public address will not work from outside, if it won't.

    Every mail this instance sends — verification, password reset — carries a
    link built from ``public_base_url``. A link to the server's own hostname, to
    a loopback address or to a plain-http port is dead for the person reading
    the message, and nothing else in the application notices. Returned as a
    sentence so it can be logged as-is; ``None`` means the value looks usable.
    """
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return f"{value} has no http(s) scheme: browsers will not open the links built from it"
    host = (parsed.hostname or "").lower()
    if not host:
        return f"{value} has no host"
    if parsed.scheme == "http":
        return (
            f"{value} uses plain http: reset links sent by mail will be downgraded "
            "or refused by mail clients and browsers"
        )
    if host in _LOOPBACK_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        return (
            f"{value} points at {host}, a name only this machine resolves: reset and "
            "share links will not open anywhere else"
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return (
            f"{value} points at {host}, a private address: reset and share links will "
            "not open anywhere else"
        )
    return None



class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OL_", env_file=".env", extra="ignore")

    app_name: str = "OpenLearn"
    environment: str = "production"
    debug: bool = False

    # Persistence
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'openlearn.db'}"
    media_dir: Path = BASE_DIR / "data" / "media"

    # Authentication
    secret_key: str = ""
    access_token_ttl_minutes: int = 12 * 60
    session_cookie_name: str = "ol_session"
    csrf_cookie_name: str = "ol_csrf"
    cookie_secure: bool = False  # set OL_COOKIE_SECURE=true behind TLS
    cookie_domain: str | None = None

    # Limits
    # 10 MB per file, for both wiki illustrations and quiz images.
    max_upload_bytes: int = 10 * 1024 * 1024
    max_questions_per_quiz: int = 200
    max_options_per_question: int = 8
    min_options_per_question: int = 2
    max_participants_per_session: int = 500

    # Rate limiting (requests per window per client IP)
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60
    # A visitor who keeps hitting a rate limit is banned from the forms for a
    # while. Eight rejections inside ten minutes is not a person mistyping; it is
    # a script, and a public demo should stop answering it.
    form_ban_enabled: bool = True
    form_ban_strikes: int = 8
    form_ban_window_seconds: int = 600
    form_ban_seconds: int = 1800
    # Addresses that are never banned: the operator's own probes, a monitoring
    # service, anything reaching the app over the bridge network.
    form_ban_allowlist: str = ""
    join_rate_limit: int = 30
    join_rate_window_seconds: int = 60
    api_rate_limit: int = 600
    api_rate_window_seconds: int = 60
    ai_rate_limit: int = 6  # AI reviews are expensive: 6 per hour per IP
    ai_rate_window_seconds: int = 3600
    # One model call per account per window: the provider saturates quickly when
    # a page lets the same author fire several translations in a row.
    ai_min_interval_seconds: int = 15

    # AI assistance (any OpenAI-compatible chat completion endpoint).
    ai_enabled: bool = False
    # Empty on purpose: an instance names the endpoint it trusts, the way it
    # names its model. A default pointing at someone else's gateway would send
    # a school's text to a host it never chose.
    ai_base_url: str = ""
    ai_api_key: str = ""
    # Left empty on purpose: an instance that turns AI on names its own model.
    ai_model: str = ""
    ai_timeout_seconds: int = 180
    ai_max_questions: int = 50
    # SearXNG instance used to ground generated content in real web results.
    # Empty by default: the feature is off until someone points it at a search
    # engine they run, and no hostname of ours belongs in a default value.
    search_base_url: str = ""
    # Wiki generation may use a larger, slower model than the quiz helper.
    ai_wiki_model: str = ""

    # Audit forwarding to an XDR/SIEM. Off by default: nothing leaves the
    # instance until an administrator names a collector.
    log_enabled: bool = False
    log_syslog_host: str = ""
    log_syslog_port: int = 514
    log_syslog_protocol: str = "udp"  # udp | tcp | tls
    log_syslog_facility: int = 13  # "log audit"
    log_syslog_hostname: str = ""
    log_syslog_tls_verify: bool = True
    log_http_url: str = ""
    log_http_token: str = ""
    log_http_verify_tls: bool = True
    log_http_timeout_seconds: int = 5

    # Moderation bootstrap: the first administrator is created from these values.
    admin_email: str = ""
    admin_password: str = ""

    # Behaviour
    seed_demo_data: bool = True
    public_base_url: str = ""  # used to build share links when set

    # Instance identity
    instance_name: str = "OpenLearn"
    github_url: str = "https://github.com/codeyourweb/openlearn"
    # Demo instances publish showcase content and keep the "About" landing page.
    # Private deployments start on the wiki listing instead.
    demo_mode: bool = False
    demo_content_dir: Path = BASE_DIR / "demo"

    # Outgoing mail (password reset, invitations). Settings entered by an
    # administrator in the UI take precedence over these bootstrap values.
    mail_enabled: bool = False
    mail_host: str = ""
    mail_port: int = 587
    mail_username: str = ""
    mail_password: str = ""
    mail_from_address: str = ""
    mail_from_name: str = "OpenLearn"
    mail_starttls: bool = True
    mail_ssl: bool = False
    mail_timeout_seconds: int = 15
    # Password reset links stay valid for one hour and a token is single use.
    password_reset_ttl_minutes: int = 60
    # Tests and demo instances may read the reset token from the API response
    # instead of a mailbox. Never enable this on a public instance.
    expose_reset_token: bool = False
    # A reset mail must not be usable as a way to flood someone's inbox: one
    # message per address per interval, whatever the visitor tries.
    password_reset_interval_seconds: int = 300
    # How long an address-confirmation link stays usable, and how often one
    # address may ask for a new one: the same flood protection as a reset.
    email_verification_ttl_minutes: int = 60 * 48
    email_verification_interval_seconds: int = 300

    # Single-sign-on (OIDC providers are configured in the admin UI; this only
    # switches the feature on for the instance).
    sso_enabled: bool = True
    sso_auto_create_users: bool = True

    # Embedded TLS: when both files are set the server serves HTTPS itself
    # instead of delegating to a reverse proxy.
    tls_cert_file: str = ""
    tls_key_file: str = ""
    tls_port: int = 8443

    # MCP endpoint (agent interoperability). Disabled by default: an MCP tool
    # surface should be an explicit decision, not an accidental one.
    mcp_enabled: bool = True
    mcp_require_auth: bool = True
    mcp_rate_limit: int = 120
    mcp_rate_window_seconds: int = 60

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def is_mysql(self) -> bool:
        return self.database_url.startswith(("mysql", "mariadb"))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        # Derive a stable key from a file so restarts keep sessions valid
        # without shipping a hardcoded secret.
        key_file = BASE_DIR / "data" / ".secret_key"
        if key_file.exists():
            settings.secret_key = key_file.read_text().strip()
        else:
            key_file.parent.mkdir(parents=True, exist_ok=True)
            settings.secret_key = secrets.token_urlsafe(48)
            key_file.write_text(settings.secret_key)
            os.chmod(key_file, 0o600)
    return settings


settings = get_settings()
