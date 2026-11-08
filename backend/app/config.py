# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Application configuration.

All settings can be overridden through environment variables prefixed with
``OL_`` (for example ``OL_DATABASE_URL``). Defaults target a self-hosted
single-node deployment.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


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
