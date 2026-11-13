# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Generate ``docs/ENVIRONMENT.md`` from the settings model.

The administration page links every variable to a heading in that file, so the
file cannot be written once and forgotten: this reads ``backend/app/config.py``,
takes the real defaults, and pairs them with the one-line description below. A
new setting without a description fails the build rather than shipping an
undocumented switch.

    python tools/env_docs.py          # writes docs/ENVIRONMENT.md
    python tools/env_docs.py --check  # fails if the file is out of date
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "backend" / "app" / "config.py"
OUTPUT = ROOT / "docs" / "ENVIRONMENT.md"

GROUPS = {
    "app": ("Application", "Identity, storage and the shape of the content the instance accepts."),
    "security": ("Security", "Sessions, rate limits and the temporary ban of a form spammer."),
    "ai": ("Artificial intelligence", "The optional model provider used for reviews, translations and generation."),
    "search": ("Web search", "The self-hosted search engine the wiki assistant uses when a question needs the web."),
    "log": ("Audit forwarding", "Bootstrap values for the syslog and HTTP POST destinations. The administration page can define destinations instead; these apply only while that list is empty."),
    "audio": ("Speech", "The optional speech engine that reads a wiki page or an adventure scene aloud."),
    "mail": ("Email", "The SMTP relay used for address confirmation and password reset."),
    "sso": ("Single sign-on", "OpenID Connect and SAML providers configured from the administration page."),
    "mcp": ("MCP", "The Model Context Protocol endpoint that lets an external agent read wikis and quizzes."),
    "demo": ("Demo instance", "Seed data and the bootstrap administrator, for a public demonstration instance."),
    "other": ("Other", "Settings that do not belong to one of the groups above."),
}

DESCRIPTIONS = {
    "app_name": "Name shown in the interface and in outgoing mail.",
    "environment": "Free-form label for the deployment (`production`, `staging`, …).",
    "debug": "Verbose logging and tracebacks. Never enable this on a public instance.",
    "database_url": "SQLAlchemy URL: SQLite by default, or a PostgreSQL/MySQL server.",
    "media_dir": "Directory holding uploaded images and generated audio.",
    "secret_key": "Signs session cookies and reset tokens. Changing it signs everybody out.",
    "access_token_ttl_minutes": "Lifetime of a session before it must be renewed by signing in again.",
    "session_cookie_name": "Name of the session cookie.",
    "csrf_cookie_name": "Name of the cookie carrying the CSRF token.",
    "cookie_secure": "Restrict cookies to HTTPS. Set it behind a TLS proxy.",
    "cookie_domain": "Cookie domain, for an instance served from a sub-domain.",
    "max_upload_bytes": "Largest image an author may upload.",
    "max_questions_per_quiz": "Upper bound on the questions of one quiz.",
    "max_options_per_question": "Upper bound on the answers offered by one question.",
    "min_options_per_question": "Lower bound on the answers offered by one question.",
    "max_participants_per_session": "Upper bound on the players of one live session.",
    "auth_rate_limit": "Sign-in and registration attempts allowed per window, per address.",
    "auth_rate_window_seconds": "Length of that window.",
    "form_ban_enabled": "Temporarily ban an address that keeps submitting forms it should not.",
    "form_ban_strikes": "How many rejected submissions before the ban.",
    "form_ban_window_seconds": "Window in which those strikes are counted.",
    "form_ban_seconds": "How long the ban lasts.",
    "form_ban_allowlist": "Comma-separated addresses, or CIDR blocks, never banned.",
    "join_rate_limit": "Join attempts allowed per window, per address.",
    "join_rate_window_seconds": "Length of that window.",
    "api_rate_limit": "API calls allowed per window, per account or address.",
    "api_rate_window_seconds": "Length of that window.",
    "ai_rate_limit": "Model calls allowed per window, per account. Reviews are expensive.",
    "ai_rate_window_seconds": "Length of that window.",
    "ai_min_interval_seconds": "Minimum delay between two model calls from the same account.",
    "ai_enabled": "Turn the AI features on. Off hides every AI control in the interface.",
    "ai_base_url": "OpenAI-compatible endpoint, for example `http://litellm:4000/v1`.",
    "ai_api_key": "Bearer token sent to that endpoint.",
    "ai_model": "Model used for quizzes and general work.",
    "ai_timeout_seconds": "How long one model call may take.",
    "ai_max_questions": "Upper bound on the questions generated in one call.",
    "ai_wiki_model": "Model used for wiki work, when it differs from the general one.",
    "search_base_url": "SearXNG instance the wiki assistant queries for web questions.",
    "log_enabled": "Bootstrap switch for audit forwarding, used only while no destination is defined.",
    "log_syslog_host": "Bootstrap syslog collector host.",
    "log_syslog_port": "Bootstrap syslog port.",
    "log_syslog_protocol": "Bootstrap syslog transport: `udp`, `tcp` or `tls`.",
    "log_syslog_facility": "Bootstrap syslog facility (13 is `log audit`).",
    "log_syslog_hostname": "Hostname written in the syslog header. Defaults to `openlearn`.",
    "log_syslog_tls_verify": "Verify the collector's certificate over TLS.",
    "log_http_url": "Bootstrap HTTP POST endpoint.",
    "log_http_token": "Bootstrap bearer token for that endpoint.",
    "log_http_verify_tls": "Verify the endpoint's certificate.",
    "log_http_timeout_seconds": "How long one delivery may take before it is counted as failed.",
    "audio_enabled": "Turn speech synthesis on. Off hides the transcript controls.",
    "audio_service_url": "Speech engine endpoint, for example `http://qwen-tts:8000`.",
    "audio_model": "Model name sent to the engine.",
    "audio_timeout_seconds": "How long one synthesis may take.",
    "audio_concurrency": "Synthesis jobs allowed to run at once.",
    "audio_voice_female": "Engine voice used for the female narrator.",
    "audio_voice_male": "Engine voice used for the male narrator.",
    "audio_max_chars": "Longest document that may be read aloud.",
    "audio_chunk_chars": "Length of the pieces the document is split into before caching.",
    "audio_languages": "Comma-separated languages the engine is allowed to read.",
    "admin_email": "Bootstrap administrator address, created at first start.",
    "admin_password": "Bootstrap administrator password. Remove it once the account exists.",
    "seed_demo_data": "Load the demonstration wikis, quizzes and adventures at start.",
    "public_base_url": "Public address used to build share links and QR codes.",
    "instance_name": "Displayed name of the instance.",
    "github_url": "Project address, used by the About page and the documentation links.",
    "demo_mode": "Show the About page as the home page and mark the instance as a demonstration.",
    "demo_content_dir": "Directory holding the demonstration content.",
    "mail_enabled": "Send mail. Off skips the message and logs it instead.",
    "mail_host": "SMTP server.",
    "mail_port": "SMTP port.",
    "mail_username": "SMTP account.",
    "mail_password": "SMTP password.",
    "mail_from_address": "Sender address.",
    "mail_from_name": "Sender name.",
    "mail_starttls": "Upgrade the connection with STARTTLS.",
    "mail_ssl": "Connect over implicit TLS.",
    "mail_timeout_seconds": "How long one SMTP exchange may take.",
    "password_reset_ttl_minutes": "Lifetime of a password reset link.",
    "expose_reset_token": "Return the reset token in the API answer. For tests only: never on a public instance.",
    "password_reset_interval_seconds": "Minimum delay between two reset messages to the same account.",
    "email_verification_ttl_minutes": "Lifetime of an address confirmation link.",
    "email_verification_interval_seconds": "Minimum delay between two confirmation messages.",
    "sso_enabled": "Allow single sign-on. Providers themselves are configured in the interface.",
    "sso_auto_create_users": "Create the account on first sign-in, instead of refusing an unknown address.",
    "tls_cert_file": "Certificate used when the application serves HTTPS itself.",
    "tls_key_file": "Private key for that certificate.",
    "tls_port": "Port the application listens on when it terminates TLS.",
    "mcp_enabled": "Expose the MCP endpoint.",
    "mcp_require_auth": "Require an account token for MCP calls.",
    "mcp_rate_limit": "MCP calls allowed per window.",
    "mcp_rate_window_seconds": "Length of that window.",
}


def _normalise(text: str) -> str:
    """Compare two renderings without their quoting style.

    ``ast.unparse`` picks the quote style of a string literal, and that choice
    changed between Python 3.12 and 3.14: the same f-string comes out as
    ``f"sqlite:///{BASE_DIR}"`` or ``f'sqlite:///{BASE_DIR}'``. The documentation
    must not say "out of date" because the checker runs on another interpreter,
    so the comparison ignores quotes; the file itself is generated with the
    interpreter of the application image.
    """
    return text.replace('"', "'")


def settings_fields() -> list[tuple[str, str, str]]:
    tree = ast.parse(CONFIG.read_text())
    body = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    rows: list[tuple[str, str, str]] = []
    for node in body.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id
        annotation = ast.unparse(node.annotation)
        default = ast.unparse(node.value) if node.value is not None else ""
        rows.append((name, annotation, default))
    return rows


def group_of(name: str) -> str:
    for prefix in ("ai_", "log_", "audio_", "mail_", "mcp_", "sso_", "search_"):
        if name.startswith(prefix):
            return prefix.rstrip("_")
    if name.startswith(("demo", "seed_", "admin_", "public_base_url")):
        return "demo"
    if name.startswith(
        (
            "auth_",
            "api_rate",
            "join_rate",
            "form_ban",
            "secret_key",
            "access_token",
            "session_cookie",
            "csrf_cookie",
            "cookie_",
            "max_upload",
            "password_reset",
            "email_verification",
            "expose_reset",
            "tls_",
        )
    ):
        return "security"
    if name.startswith(("app_name", "environment", "debug", "database_url", "media_dir", "instance_name", "github_url", "max_questions", "max_options", "min_options", "max_participants")):
        return "app"
    return "other"


def render() -> str:
    rows = settings_fields()
    missing = [name for name, _t, _d in rows if name not in DESCRIPTIONS]
    if missing:
        raise SystemExit(f"missing descriptions: {', '.join(missing)}")

    grouped: dict[str, list[tuple[str, str, str]]] = {key: [] for key in GROUPS}
    for row in rows:
        grouped[group_of(row[0])].append(row)

    lines = [
        "# Environment variables",
        "",
        "Every variable this instance reads, with the value it falls back to when it is",
        "not set. Values in the environment are the bootstrap: anything the",
        "administration page can change wins over them, and the **Settings → Environment**",
        "page shows what the process is *actually* running with.",
        "",
        "Copy the file next to your `docker-compose.yml` as `.env`, or pass the values",
        "with `-e`. Nothing here is required for a local trial: the defaults are a",
        "working instance.",
        "",
        "| Group | Variables |",
        "| --- | --- |",
    ]
    for key, (title, _lead) in GROUPS.items():
        if grouped[key]:
            lines.append(f"| [{title}](#{title.lower().replace(' ', '-')}) | {len(grouped[key])} |")
    lines.append("")

    for key, (title, lead) in GROUPS.items():
        if not grouped[key]:
            continue
        lines += [f"## {title}", "", lead, ""]
        for name, annotation, default in sorted(grouped[key]):
            env = f"OL_{name.upper()}"
            shown = default if default else "*(empty)*"
            lines += [
                f"### {env}",
                "",
                DESCRIPTIONS[name],
                "",
                f"- Type: `{annotation}`",
                f"- Default: `{shown}`",
                f"- Read as: `settings.{name}`",
                "",
            ]
    lines += [
        "---",
        "",
        "Generated from `backend/app/config.py` by `tools/env_docs.py`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if _normalise(current) != _normalise(text):
            print("docs/ENVIRONMENT.md is out of date: run python tools/env_docs.py")
            return 1
        print("docs/ENVIRONMENT.md is up to date")
        return 0
    OUTPUT.write_text(text)
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
