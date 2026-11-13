# Environment variables

Every variable this instance reads, with the value it falls back to when it is
not set. Values in the environment are the bootstrap: anything the
administration page can change wins over them, and the **Settings → Environment**
page shows what the process is *actually* running with.

Copy the file next to your `docker-compose.yml` as `.env`, or pass the values
with `-e`. Nothing here is required for a local trial: the defaults are a
working instance.

| Group | Variables |
| --- | --- |
| [Application](#application) | 11 |
| [Security](#security) | 26 |
| [Artificial intelligence](#artificial-intelligence) | 10 |
| [Web search](#web-search) | 1 |
| [Audit forwarding](#audit-forwarding) | 11 |
| [Speech](#speech) | 10 |
| [Email](#email) | 10 |
| [Single sign-on](#single-sign-on) | 2 |
| [MCP](#mcp) | 4 |
| [Demo instance](#demo-instance) | 6 |

## Application

Identity, storage and the shape of the content the instance accepts.

### OL_APP_NAME

Name shown in the interface and in outgoing mail.

- Type: `str`
- Default: `'OpenLearn'`
- Read as: `settings.app_name`

### OL_DATABASE_URL

SQLAlchemy URL: SQLite by default, or a PostgreSQL/MySQL server.

- Type: `str`
- Default: `f'sqlite:///{BASE_DIR / 'data' / 'openlearn.db'}'`
- Read as: `settings.database_url`

### OL_DEBUG

Verbose logging and tracebacks. Never enable this on a public instance.

- Type: `bool`
- Default: `False`
- Read as: `settings.debug`

### OL_ENVIRONMENT

Free-form label for the deployment (`production`, `staging`, …).

- Type: `str`
- Default: `'production'`
- Read as: `settings.environment`

### OL_GITHUB_URL

Project address, used by the About page and the documentation links.

- Type: `str`
- Default: `'https://github.com/codeyourweb/openlearn'`
- Read as: `settings.github_url`

### OL_INSTANCE_NAME

Displayed name of the instance.

- Type: `str`
- Default: `'OpenLearn'`
- Read as: `settings.instance_name`

### OL_MAX_OPTIONS_PER_QUESTION

Upper bound on the answers offered by one question.

- Type: `int`
- Default: `8`
- Read as: `settings.max_options_per_question`

### OL_MAX_PARTICIPANTS_PER_SESSION

Upper bound on the players of one live session.

- Type: `int`
- Default: `500`
- Read as: `settings.max_participants_per_session`

### OL_MAX_QUESTIONS_PER_QUIZ

Upper bound on the questions of one quiz.

- Type: `int`
- Default: `200`
- Read as: `settings.max_questions_per_quiz`

### OL_MEDIA_DIR

Directory holding uploaded images and generated audio.

- Type: `Path`
- Default: `BASE_DIR / 'data' / 'media'`
- Read as: `settings.media_dir`

### OL_MIN_OPTIONS_PER_QUESTION

Lower bound on the answers offered by one question.

- Type: `int`
- Default: `2`
- Read as: `settings.min_options_per_question`

## Security

Sessions, rate limits and the temporary ban of a form spammer.

### OL_ACCESS_TOKEN_TTL_MINUTES

Lifetime of a session before it must be renewed by signing in again.

- Type: `int`
- Default: `12 * 60`
- Read as: `settings.access_token_ttl_minutes`

### OL_API_RATE_LIMIT

API calls allowed per window, per account or address.

- Type: `int`
- Default: `600`
- Read as: `settings.api_rate_limit`

### OL_API_RATE_WINDOW_SECONDS

Length of that window.

- Type: `int`
- Default: `60`
- Read as: `settings.api_rate_window_seconds`

### OL_AUTH_RATE_LIMIT

Sign-in and registration attempts allowed per window, per address.

- Type: `int`
- Default: `10`
- Read as: `settings.auth_rate_limit`

### OL_AUTH_RATE_WINDOW_SECONDS

Length of that window.

- Type: `int`
- Default: `60`
- Read as: `settings.auth_rate_window_seconds`

### OL_COOKIE_DOMAIN

Cookie domain, for an instance served from a sub-domain.

- Type: `str | None`
- Default: `None`
- Read as: `settings.cookie_domain`

### OL_COOKIE_SECURE

Restrict cookies to HTTPS. Set it behind a TLS proxy.

- Type: `bool`
- Default: `False`
- Read as: `settings.cookie_secure`

### OL_CSRF_COOKIE_NAME

Name of the cookie carrying the CSRF token.

- Type: `str`
- Default: `'ol_csrf'`
- Read as: `settings.csrf_cookie_name`

### OL_EMAIL_VERIFICATION_INTERVAL_SECONDS

Minimum delay between two confirmation messages.

- Type: `int`
- Default: `300`
- Read as: `settings.email_verification_interval_seconds`

### OL_EMAIL_VERIFICATION_TTL_MINUTES

Lifetime of an address confirmation link.

- Type: `int`
- Default: `60 * 48`
- Read as: `settings.email_verification_ttl_minutes`

### OL_EXPOSE_RESET_TOKEN

Return the reset token in the API answer. For tests only: never on a public instance.

- Type: `bool`
- Default: `False`
- Read as: `settings.expose_reset_token`

### OL_FORM_BAN_ALLOWLIST

Comma-separated addresses, or CIDR blocks, never banned.

- Type: `str`
- Default: `''`
- Read as: `settings.form_ban_allowlist`

### OL_FORM_BAN_ENABLED

Temporarily ban an address that keeps submitting forms it should not.

- Type: `bool`
- Default: `True`
- Read as: `settings.form_ban_enabled`

### OL_FORM_BAN_SECONDS

How long the ban lasts.

- Type: `int`
- Default: `1800`
- Read as: `settings.form_ban_seconds`

### OL_FORM_BAN_STRIKES

How many rejected submissions before the ban.

- Type: `int`
- Default: `8`
- Read as: `settings.form_ban_strikes`

### OL_FORM_BAN_WINDOW_SECONDS

Window in which those strikes are counted.

- Type: `int`
- Default: `600`
- Read as: `settings.form_ban_window_seconds`

### OL_JOIN_RATE_LIMIT

Join attempts allowed per window, per address.

- Type: `int`
- Default: `30`
- Read as: `settings.join_rate_limit`

### OL_JOIN_RATE_WINDOW_SECONDS

Length of that window.

- Type: `int`
- Default: `60`
- Read as: `settings.join_rate_window_seconds`

### OL_MAX_UPLOAD_BYTES

Largest image an author may upload.

- Type: `int`
- Default: `10 * 1024 * 1024`
- Read as: `settings.max_upload_bytes`

### OL_PASSWORD_RESET_INTERVAL_SECONDS

Minimum delay between two reset messages to the same account.

- Type: `int`
- Default: `300`
- Read as: `settings.password_reset_interval_seconds`

### OL_PASSWORD_RESET_TTL_MINUTES

Lifetime of a password reset link.

- Type: `int`
- Default: `60`
- Read as: `settings.password_reset_ttl_minutes`

### OL_SECRET_KEY

Signs session cookies and reset tokens. Changing it signs everybody out.

- Type: `str`
- Default: `''`
- Read as: `settings.secret_key`

### OL_SESSION_COOKIE_NAME

Name of the session cookie.

- Type: `str`
- Default: `'ol_session'`
- Read as: `settings.session_cookie_name`

### OL_TLS_CERT_FILE

Certificate used when the application serves HTTPS itself.

- Type: `str`
- Default: `''`
- Read as: `settings.tls_cert_file`

### OL_TLS_KEY_FILE

Private key for that certificate.

- Type: `str`
- Default: `''`
- Read as: `settings.tls_key_file`

### OL_TLS_PORT

Port the application listens on when it terminates TLS.

- Type: `int`
- Default: `8443`
- Read as: `settings.tls_port`

## Artificial intelligence

The optional model provider used for reviews, translations and generation.

### OL_AI_API_KEY

Bearer token sent to that endpoint.

- Type: `str`
- Default: `''`
- Read as: `settings.ai_api_key`

### OL_AI_BASE_URL

OpenAI-compatible endpoint, for example `http://litellm:4000/v1`.

- Type: `str`
- Default: `''`
- Read as: `settings.ai_base_url`

### OL_AI_ENABLED

Turn the AI features on. Off hides every AI control in the interface.

- Type: `bool`
- Default: `False`
- Read as: `settings.ai_enabled`

### OL_AI_MAX_QUESTIONS

Upper bound on the questions generated in one call.

- Type: `int`
- Default: `50`
- Read as: `settings.ai_max_questions`

### OL_AI_MIN_INTERVAL_SECONDS

Minimum delay between two model calls from the same account.

- Type: `int`
- Default: `15`
- Read as: `settings.ai_min_interval_seconds`

### OL_AI_MODEL

Model used for quizzes and general work.

- Type: `str`
- Default: `''`
- Read as: `settings.ai_model`

### OL_AI_RATE_LIMIT

Model calls allowed per window, per account. Reviews are expensive.

- Type: `int`
- Default: `6`
- Read as: `settings.ai_rate_limit`

### OL_AI_RATE_WINDOW_SECONDS

Length of that window.

- Type: `int`
- Default: `3600`
- Read as: `settings.ai_rate_window_seconds`

### OL_AI_TIMEOUT_SECONDS

How long one model call may take.

- Type: `int`
- Default: `180`
- Read as: `settings.ai_timeout_seconds`

### OL_AI_WIKI_MODEL

Model used for wiki work, when it differs from the general one.

- Type: `str`
- Default: `''`
- Read as: `settings.ai_wiki_model`

## Web search

The self-hosted search engine the wiki assistant uses when a question needs the web.

### OL_SEARCH_BASE_URL

SearXNG instance the wiki assistant queries for web questions.

- Type: `str`
- Default: `''`
- Read as: `settings.search_base_url`

## Audit forwarding

Bootstrap values for the syslog and HTTP POST destinations. The administration page can define destinations instead; these apply only while that list is empty.

### OL_LOG_ENABLED

Bootstrap switch for audit forwarding, used only while no destination is defined.

- Type: `bool`
- Default: `False`
- Read as: `settings.log_enabled`

### OL_LOG_HTTP_TIMEOUT_SECONDS

How long one delivery may take before it is counted as failed.

- Type: `int`
- Default: `5`
- Read as: `settings.log_http_timeout_seconds`

### OL_LOG_HTTP_TOKEN

Bootstrap bearer token for that endpoint.

- Type: `str`
- Default: `''`
- Read as: `settings.log_http_token`

### OL_LOG_HTTP_URL

Bootstrap HTTP POST endpoint.

- Type: `str`
- Default: `''`
- Read as: `settings.log_http_url`

### OL_LOG_HTTP_VERIFY_TLS

Verify the endpoint's certificate.

- Type: `bool`
- Default: `True`
- Read as: `settings.log_http_verify_tls`

### OL_LOG_SYSLOG_FACILITY

Bootstrap syslog facility (13 is `log audit`).

- Type: `int`
- Default: `13`
- Read as: `settings.log_syslog_facility`

### OL_LOG_SYSLOG_HOST

Bootstrap syslog collector host.

- Type: `str`
- Default: `''`
- Read as: `settings.log_syslog_host`

### OL_LOG_SYSLOG_HOSTNAME

Hostname written in the syslog header. Defaults to `openlearn`.

- Type: `str`
- Default: `''`
- Read as: `settings.log_syslog_hostname`

### OL_LOG_SYSLOG_PORT

Bootstrap syslog port.

- Type: `int`
- Default: `514`
- Read as: `settings.log_syslog_port`

### OL_LOG_SYSLOG_PROTOCOL

Bootstrap syslog transport: `udp`, `tcp` or `tls`.

- Type: `str`
- Default: `'udp'`
- Read as: `settings.log_syslog_protocol`

### OL_LOG_SYSLOG_TLS_VERIFY

Verify the collector's certificate over TLS.

- Type: `bool`
- Default: `True`
- Read as: `settings.log_syslog_tls_verify`

## Speech

The optional speech engine that reads a wiki page or an adventure scene aloud.

### OL_AUDIO_CHUNK_CHARS

Length of the pieces the document is split into before caching.

- Type: `int`
- Default: `900`
- Read as: `settings.audio_chunk_chars`

### OL_AUDIO_CONCURRENCY

Synthesis jobs allowed to run at once.

- Type: `int`
- Default: `1`
- Read as: `settings.audio_concurrency`

### OL_AUDIO_ENABLED

Turn speech synthesis on. Off hides the transcript controls.

- Type: `bool`
- Default: `False`
- Read as: `settings.audio_enabled`

### OL_AUDIO_LANGUAGES

Comma-separated languages the engine is allowed to read.

- Type: `str`
- Default: `'en,fr,de,es,it,pt,ru,zh,ja'`
- Read as: `settings.audio_languages`

### OL_AUDIO_MAX_CHARS

Longest document that may be read aloud.

- Type: `int`
- Default: `12000`
- Read as: `settings.audio_max_chars`

### OL_AUDIO_MODEL

Model name sent to the engine.

- Type: `str`
- Default: `'qwen3-tts'`
- Read as: `settings.audio_model`

### OL_AUDIO_SERVICE_URL

Speech engine endpoint, for example `http://qwen-tts:8000`.

- Type: `str`
- Default: `''`
- Read as: `settings.audio_service_url`

### OL_AUDIO_TIMEOUT_SECONDS

How long one synthesis may take.

- Type: `int`
- Default: `1800`
- Read as: `settings.audio_timeout_seconds`

### OL_AUDIO_VOICE_FEMALE

Engine voice used for the female narrator.

- Type: `str`
- Default: `'Serena'`
- Read as: `settings.audio_voice_female`

### OL_AUDIO_VOICE_MALE

Engine voice used for the male narrator.

- Type: `str`
- Default: `'Aiden'`
- Read as: `settings.audio_voice_male`

## Email

The SMTP relay used for address confirmation and password reset.

### OL_MAIL_ENABLED

Send mail. Off skips the message and logs it instead.

- Type: `bool`
- Default: `False`
- Read as: `settings.mail_enabled`

### OL_MAIL_FROM_ADDRESS

Sender address.

- Type: `str`
- Default: `''`
- Read as: `settings.mail_from_address`

### OL_MAIL_FROM_NAME

Sender name.

- Type: `str`
- Default: `'OpenLearn'`
- Read as: `settings.mail_from_name`

### OL_MAIL_HOST

SMTP server.

- Type: `str`
- Default: `''`
- Read as: `settings.mail_host`

### OL_MAIL_PASSWORD

SMTP password.

- Type: `str`
- Default: `''`
- Read as: `settings.mail_password`

### OL_MAIL_PORT

SMTP port.

- Type: `int`
- Default: `587`
- Read as: `settings.mail_port`

### OL_MAIL_SSL

Connect over implicit TLS.

- Type: `bool`
- Default: `False`
- Read as: `settings.mail_ssl`

### OL_MAIL_STARTTLS

Upgrade the connection with STARTTLS.

- Type: `bool`
- Default: `True`
- Read as: `settings.mail_starttls`

### OL_MAIL_TIMEOUT_SECONDS

How long one SMTP exchange may take.

- Type: `int`
- Default: `15`
- Read as: `settings.mail_timeout_seconds`

### OL_MAIL_USERNAME

SMTP account.

- Type: `str`
- Default: `''`
- Read as: `settings.mail_username`

## Single sign-on

OpenID Connect and SAML providers configured from the administration page.

### OL_SSO_AUTO_CREATE_USERS

Create the account on first sign-in, instead of refusing an unknown address.

- Type: `bool`
- Default: `True`
- Read as: `settings.sso_auto_create_users`

### OL_SSO_ENABLED

Allow single sign-on. Providers themselves are configured in the interface.

- Type: `bool`
- Default: `True`
- Read as: `settings.sso_enabled`

## MCP

The Model Context Protocol endpoint that lets an external agent read wikis and quizzes.

### OL_MCP_ENABLED

Expose the MCP endpoint.

- Type: `bool`
- Default: `True`
- Read as: `settings.mcp_enabled`

### OL_MCP_RATE_LIMIT

MCP calls allowed per window.

- Type: `int`
- Default: `120`
- Read as: `settings.mcp_rate_limit`

### OL_MCP_RATE_WINDOW_SECONDS

Length of that window.

- Type: `int`
- Default: `60`
- Read as: `settings.mcp_rate_window_seconds`

### OL_MCP_REQUIRE_AUTH

Require an account token for MCP calls.

- Type: `bool`
- Default: `True`
- Read as: `settings.mcp_require_auth`

## Demo instance

Seed data and the bootstrap administrator, for a public demonstration instance.

### OL_ADMIN_EMAIL

Bootstrap administrator address, created at first start.

- Type: `str`
- Default: `''`
- Read as: `settings.admin_email`

### OL_ADMIN_PASSWORD

Bootstrap administrator password. Remove it once the account exists.

- Type: `str`
- Default: `''`
- Read as: `settings.admin_password`

### OL_DEMO_CONTENT_DIR

Directory holding the demonstration content.

- Type: `Path`
- Default: `BASE_DIR / 'demo'`
- Read as: `settings.demo_content_dir`

### OL_DEMO_MODE

Show the About page as the home page and mark the instance as a demonstration.

- Type: `bool`
- Default: `False`
- Read as: `settings.demo_mode`

### OL_PUBLIC_BASE_URL

Public address used to build share links and QR codes.

- Type: `str`
- Default: `''`
- Read as: `settings.public_base_url`

### OL_SEED_DEMO_DATA

Load the demonstration wikis, quizzes and adventures at start.

- Type: `bool`
- Default: `True`
- Read as: `settings.seed_demo_data`

---

Generated from `backend/app/config.py` by `tools/env_docs.py`.
