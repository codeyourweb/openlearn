# OpenLearn — Security

This document describes the threat model, the controls implemented in the code,
how each OWASP Top 10 (2021) category is addressed, and how to run the security
tests. Every claim here maps to code or to an automated test; the test name is
given so a reviewer can check it.

---

## 1. Scope and threat model

OpenLearn is a self-hosted training platform. It is assumed to run on a host
you control, behind a TLS reverse proxy, with a small number of untrusted
users: registered authors, anonymous participants, and third-party API clients.

In scope:

| # | Threat | Impact if unhandled |
| --- | --- | --- |
| T1 | Participant reads correct answers before the reveal | The quiz is worthless as an assessment |
| T2 | Participant drives the game (start/next/finish) or answers as somebody else | Corrupted scores, griefing |
| T3 | Author reads or modifies another author's private quiz | Data leak, tampering |
| T4 | Stored/reflected XSS through question text, nicknames or titles | Session theft, drive-by actions on the host account |
| T5 | Credential stuffing and brute force | Account takeover |
| T6 | Malicious upload (polyglot, oversized, decompression bomb) | RCE, disk exhaustion |
| T20 | Hostile wiki archive (zip bomb, zip slip, script payload) | Disk exhaustion, file overwrite, stored XSS |
| T7 | Injection through search or API filters | Database compromise |
| T8 | SSRF through a "remote image URL" | Access to internal metadata endpoints |
| T9 | CSRF on cookie-authenticated mutations | Actions performed on behalf of a signed-in user |
| T10 | DoS through session flooding, giant payloads or reconnect storms | Service unavailable during a session |

Out of scope (documented in §7): a compromised host, a malicious administrator
with database and filesystem access, and side-channel attacks.

---

## 2. Authentication and session management

- **Password storage**: Argon2id, `time_cost=3`, `memory_cost=65536` (64 MiB),
  `parallelism=2`, 32-byte hash, 16-byte salt; hashes are transparently upgraded
  when parameters change (`needs_rehash`).
  Test: `test_scoring.py::test_password_hashing_roundtrip`.
- **Password policy**: 8–128 characters, at least one uppercase letter, one
  lowercase letter and one digit or symbol, rejected against a common-password
  list. Eight characters with three classes clears NIST's length guidance while
  staying below the friction that pushes users towards reused passwords.
  Tests: `test_scoring.py::test_weak_passwords_are_rejected`, `test_api_auth.py::test_register_enforces_password_policy`.
- **Lockout**: five failed logins within 15 minutes lock the account; the
  failure is audited.
  Tests: `test_api_auth.py::test_account_locks_after_repeated_failures`, `test_security_owasp.py::test_failed_login_is_audited`.
- **Tokens**: HS256 JWT with `sub`, `iat`, `exp`; signing key generated once at
  first start into `data/.secret_key` (mode `0600`) or supplied by
  `OL_SECRET_KEY`. Forged and expired tokens are rejected.
  Tests: `test_security_owasp.py::test_forged_jwt_is_rejected`, `test_scoring.py::test_expired_token_is_rejected`.
- **Cookies**: `ol_session` is `HttpOnly`, `SameSite=Lax`, `Path=/`, and gains
  `Secure` when the request arrives over TLS (`X-Forwarded-Proto: https`) or
  when `OL_COOKIE_SECURE=true`.
  Tests: `test_security_owasp.py::test_session_cookie_is_hardened`, `test_secure_cookie_when_tls_terminates_upstream`.
- **API keys**: `ol_` + 32 random bytes URL-safe, shown once, stored as
  SHA-256, revocable, `last_used_at` tracked; the secret is never returned by a
  read endpoint.
  Tests: `test_security_owasp.py::test_api_key_authentication_and_revocation`, `test_api_key_cannot_be_read_back`.
- **Participant and host tokens**: random 32-byte tokens, stored hashed; they
  authorise exactly one participant (or the host) within exactly one session.
  Test: `test_security_owasp.py::test_forged_participant_token_is_rejected`.
- **No secret in responses**: user serialisation never exposes `password_hash`,
  `secret_key` or token material.
  Test: `test_security_owasp.py::test_password_material_never_leaves_the_server`.

---

## 3. Authorization

Authorization is enforced server side, per object, on every request:

| Action | Rule |
| --- | --- |
| Read a public quiz | Anyone |
| Read a private quiz | Owner only (others get `404`, not `403`, to avoid confirming existence) |
| Create/update/delete/duplicate | Owner only |
| Host a live session | Authenticated user; only the first host controls it |
| Join a live session | Anyone while `status=lobby` and not solo |
| Start / next / reveal / finish / cancel | Host token or quiz owner |
| Read session state | Host or a participant of that session |
| Submit an answer | That participant, current question only, before the deadline |
| Read results | Host anytime, participants once finished |

Correct answers are stripped from every payload served to a non-owner before the
reveal phase (`test_api_quizzes.py::test_anonymous_view_hides_correct_answers`,
`test_api_sessions.py::test_solo_session_starts_immediately_and_hides_answers`).

---

## 4. OWASP Top 10 (2021) traceability

| Category | Controls | Tests |
| --- | --- | --- |
| **A01 Broken access control** | Object-level ownership checks on every route; host/participant token scoping; results gated; 404 instead of 403 for private resources; no client-side-only checks | `test_participant_cannot_drive_the_game`, `test_anonymous_cannot_list_own_quizzes`, `test_state_requires_membership`, `test_results_access_control`, `test_other_user_cannot_modify_quiz`, `test_public_listing_hides_private_quizzes_of_others`, `test_private_quiz_is_hidden_from_anonymous` |
| **A02 Cryptographic failures** | Argon2id; HS256 JWT with a per-instance key; SHA-256 for API keys and reconnect tokens; TLS terminated at the proxy with HSTS emitted when `X-Forwarded-Proto: https`; no HTTP fallback advertised | `test_password_hashing_roundtrip`, `test_forged_jwt_is_rejected`, `test_secure_cookie_when_tls_terminates_upstream` |
| **A03 Injection** | SQLAlchemy Core/ORM with bound parameters everywhere (no string-built SQL); HTML sanitised through an `nh3` allowlist with **no attributes**; JSON schemas typed and bounded; no `eval`, no shell | `test_sql_injection_payloads_are_harmless`, `test_stored_xss_payload_is_neutralised`, `test_question_text_is_sanitised`, `test_dangerous_markup_is_removed`, `test_path_traversal_cannot_read_files` |
| **A04 Insecure design** | Server-authoritative scoring; lobby lock after start; one answer per participant per question; deadline enforced on the server; negative marking explicit in the quiz model; per-question timer in seconds; no client-trusted state | `test_no_join_after_start`, `test_answer_rules`, `test_late_answer_is_rejected`, `test_multiple_answers_require_every_correct_option`, `test_duplicate_nickname_is_rejected`, `test_forwarded_for_from_untrusted_peer_is_ignored` |
| **A05 Security misconfiguration** | Explicit security headers on every response (CSP without `unsafe-inline`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`); `no-store` on API responses; API 404 never falls back to the SPA; interactive docs disabled in production; container runs non-root with `read_only`, `cap_drop: ALL`, `no-new-privileges` | `test_security_headers_on_api_and_spa`, `test_api_cache_is_not_stored`, `test_unknown_api_route_does_not_fall_back_to_spa`, `test_security_headers_and_no_csp_violation` (E2E, asserts zero CSP violations in the console) |
| **A06 Vulnerable and outdated components** | Pinned dependencies (`backend/requirements.txt`); minimal image (python-slim, no build tools at runtime); `pip-audit -r backend/requirements.txt` in CI; Playwright base image only for tests | Run `pip-audit` (see §6) |
| **A07 Identification and authentication failures** | Rate-limited login/registration/token; account lockout; uniform error message for unknown email and wrong password; session expiry; token revocation; password change requires the current password | `test_login_is_rate_limited`, `test_account_locks_after_repeated_failures`, `test_login_rejects_bad_credentials`, `test_change_password`, `test_api_key_authentication_and_revocation` |
| **A08 Software and data integrity failures** | Uploads decoded and fully re-encoded to WEBP (strips EXIF, appended payloads and polyglots); only `/media/…` paths accepted for question images; session snapshots make results tamper-evident against later quiz edits | `test_upload_rejects_non_images`, `test_valid_image_is_reencoded`, `test_image_path_must_come_from_uploads`, `test_remote_image_reference_is_refused` |
| **A09 Security logging and monitoring failures** | `security_events` table records registration, login success/failure, lockout, session creation/join, API key lifecycle, with IP and user agent; no secrets logged | `test_failed_login_is_audited` |
| **A10 Server-side request forgery** | No outbound HTTP from the application at all; remote image URLs are rejected at validation time, so `169.254.169.254`, `file://` and `gopher://` cannot be reached | `test_remote_image_reference_is_refused` |

### Additional hardening

- **CSRF**: double-submit cookie, required for every cookie-authenticated
  mutation; requests using `Authorization`/`X-API-Key` are exempt by design.
  Test: `test_csrf_is_required_for_cookie_clients`.
- **Wiki archives are untrusted** (`backend/app/wiki_import.py`): 40 MB of
  archive, 120 MB uncompressed, 600 entries, 200 pages, 1 MB per page; paths are
  normalised with `posixpath` and rejected when they escape the archive root
  (zip slip); only `.md`/`.markdown`/`.mdown`/`.txt` and allowlisted image
  suffixes are read, tool folders (`.obsidian/`, `.joplin/`) are skipped, and
  every extracted image goes back through Pillow (`store_image`), which decodes
  and re-encodes it — front matter can change a title, never a path.
  `test_an_obsidian_vault_imports_as_a_wiki`, `test_a_zip_bomb_is_refused`.
- **Live co-editing trusts no client text** (`backend/app/collab.py`): a socket
  is only opened by an authenticated reader, and a `contributor` who may not
  write over REST is refused over the socket too (`denied`, read-only). Every
  operation carries the revision the client started from; the server merges the
  incoming text with the room against that revision and broadcasts one minimal
  splice, so a client can neither rewind the document nor push another editor's
  text away. Documents are capped at 400 000 bytes, history at 120 revisions, and
  live text is persisted without freezing a version — history remains the record
  of deliberate saves. Tests:  `test_a_reader_watches_but_cannot_type`,
  `test_two_browsers_see_each_others_typing`.
- **The menu tree is validated, not trusted** (`PUT /wiki/{id}/tree`): every id
  and every parent must exist in that wiki, cycles are refused (a page cannot
  become its own ancestor), depth is capped at 6 and the payload at 500 pages.
  Tests: `test_reordering_the_menu_changes_the_reading_order`,
  `test_a_move_that_would_close_a_loop_is_refused`.
- **Deletion is a write, and writes are scarce** (`DELETE /wiki/pages/{id}`):
  deleting a page needs the same role as editing it — `contributor` gets `403`
  and keeps its proposals. The page's children climb one level (the menu is not
  flattened), and its versions, links, citations and proposals go with it. A
  whole wiki is only erased by its owner or an administrator; the flag the UI
  reads (`can_delete`) is computed server side and never sent to anybody else.
  Tests: `test_a_contributor_cannot_delete_a_page_but_the_owner_can`,
  `test_deleting_a_page_lifts_its_children_instead_of_flattening_the_menu`.
- **Templates are content, not code** (`/wiki/{id}/templates`): they are written
  by whoever may write in the wiki and applied by anyone who may read it, so a
  template can never widen access. The wiki in the path must own the template
  (`404` otherwise), which keeps an id from one wiki from editing another's
  skeleton. Applying one only fills an empty editor: nothing is saved until the
  author saves, and a live page is never overwritten from a template silently.
  Tests: `test_a_template_is_written_once_and_reused_by_every_contributor`,
  `test_a_template_cannot_be_reached_through_another_wiki`.
- **Image sizes are data, not CSS**: the editor carries a picture's width in the
  markdown (`{width=320}`, `{width=50%}`); the renderer emits a `width`
  attribute and the sanitiser only accepts `\d{1,4}` with an optional `%`. No
  `style` attribute is ever produced, so a hand-written page cannot smuggle CSS
  past the strict CSP. Test: `test_an_image_width_survives_the_markdown_round_trip`.
- **AI output never lands on a page by itself** (`kind: "fill"`): the model
  writes a body that the server hands straight back to the open editor, with no
  page write, no version and no autosave. Generation of whole pages stays on the
  wiki screen and produces drafts. Test:
  `test_a_fill_job_hands_back_the_body_and_writes_nothing`.
- **Payload limits**: upload ≤ 2 MB, JSON body rejected above the configured
  cap, 1–200 questions per quiz, 2–8 options per question, ≤ 500 participants
  per session.
  Tests: `test_oversized_json_body_is_refused`, `test_option_count_is_bounded`,
  `test_upload_rejects_non_images`.
- **Rate limiting**: per-IP token bucket on auth (10/min), joins (30/min),
  uploads (30/min) and account mutations (10/min); `429` with `Retry-After`.
- **No inline script or style**: the SPA is loaded from `/js/*.js` and `/css/*.css`
  only, and the CSP has no `unsafe-inline`; dynamic markup goes through the same
  allowlist as the server (`frontend/js/sanitize.js`).
- **Administration**: `/admin/*` is gated by `is_admin` server side; the page
  hides itself for other users but never relies on that. An administrator cannot
  revoke their own rights or disable their own account (`409`), which keeps a
  single-operator instance recoverable.
  Tests: `test_admin_endpoints_reject_regular_users`, `test_admin_endpoints_require_authentication`, `test_admin_cannot_lock_themselves_out`.
- **Untrusted generated content**: a quiz produced by the model is validated with
  the same `QuizIn` schema, sanitised with the same allowlist, stored as a
  `draft` owned by the caller, and still has to pass moderation. AI output is
  never rendered as HTML directly.
  Tests: `test_generation_sanitises_model_output`, `test_generation_can_save_a_draft`, `test_ai_status_is_false_without_configuration`.
- **Review cache pinning**: a review is keyed by the quiz `content_hash`, so
  editing a quiz invalidates its safety verdict instead of inheriting it.
  Tests: `test_review_is_cached_until_the_quiz_changes`, `test_blocked_quiz_cannot_be_published`.
- **Search index**: the FTS5 table owns its own copy of the indexed text and is
  rebuilt at boot, so a corrupted or drifted index cannot make a query return
  another quiz's content.
  Test: `test_search_index_stays_exact_after_edits_and_deletions`.

---

## 5. Known limitations

These are deliberate trade-offs for a single-node self-hosted deployment; they
are listed so nobody assumes more than the code provides.

1. **Rate limiting and WebSocket rooms live in process memory.** A restart
   clears them, and running several uvicorn workers would give each worker its
   own counters. The shipped configuration uses one worker; move to Redis
   (pub/sub + counters) before scaling horizontally.
2. **SQLite** is a single-writer database. It is fine for a classroom or a
   company training instance, not for thousands of concurrent writers.
3. **No MFA, no email verification, no password reset by email.** Accounts are
   created by the user; an administrator can reset a password with the CLI.
4. **The host is trusted.** A host can see the questions and correct answers,
   and can start/reveal at will — that is inherent to running a live quiz.
5. **No per-question anti-cheat.** A determined participant can share answers
   out of band; the time limit and the lobby lock are the only mitigations.
6. **TLS is delegated** to the reverse proxy; the app itself speaks HTTP. Use
   the nginx example in `README.md`, keep `OL_COOKIE_SECURE=true` if the app is
   ever reachable without TLS.
7. **Moderation is not a proof of quality.** The AI safety review is a
   best-effort filter; it can be wrong in both directions, and a `public` quiz is
   still user-generated content. Administrators remain the final authority.
8. **AI calls leave the instance.** When AI assistance is enabled, quiz text is
   sent to the endpoint configured for that instance — nothing is sent anywhere
   until an administrator names an endpoint and a model. Disable it with
   `OL_AI_ENABLED=false` if content must never leave the host.

---

## 6. Running the security tests

```bash
# Whole backend suite (API, engine, scoring, OWASP)
.venv/bin/python -m pytest tests -q --ignore=tests/test_frontend_e2e.py

# OWASP suite only
.venv/bin/python -m pytest tests/test_security_owasp.py -v

# Frontend end-to-end, including zero-CSP-violation check
OL_TEST_BASE_URL=http://localhost:8080 .venv/bin/python -m pytest tests/test_frontend_e2e.py -q
# (run the app with docker-compose.dev.yml, or point at the TLS vhost)

# Dependency audit
pip install pip-audit && pip-audit -r backend/requirements.txt
```

Current result on this codebase: **83 backend tests passing** (25 of them in
`test_security_owasp.py`) plus the Playwright suite.

Manual checks worth repeating after any change:

```bash
# Security headers everywhere
curl -sI https://quiz.example.org/ | grep -Ei 'content-security|x-frame|strict-transport|referrer|permissions'

# Answers must not appear before the reveal
curl -s https://quiz.example.org/api/v1/quizzes/1 | grep -c is_correct

# Private resources answer 404 to strangers
curl -s -o /dev/null -w '%{http_code}\n' https://quiz.example.org/api/v1/quizzes/<private-id>
```

---

## 7. Reporting a vulnerability

Open a private security advisory on the GitHub repository, or email the
maintainer listed in `pyproject`/repository metadata. Please include the
affected endpoint, a reproduction, and the impact you expect. Do not open a
public issue before a fix is available.
