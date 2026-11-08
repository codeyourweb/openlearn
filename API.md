# OpenLearn — HTTP API

Version: `v1` · Base path: `/api/v1` · Content type: `application/json`
(except the image upload endpoint, which is `multipart/form-data`).

The web interface is a client of this API: anything the UI does can be
automated. The reference is rendered by the app itself at `/docs`: it reads
`/api/openapi.json` and displays every operation, so it works under the same
CSP as the rest of the interface. (`/api/docs` and `/api/redoc` redirect there;
the stock Swagger page cannot run with `unsafe-inline` disabled.)

---

## 1. Authentication

Three mechanisms are accepted on every endpoint; pick the one that fits the
caller.

| Mechanism | How to send it | Intended for |
| --- | --- | --- |
| Session cookie | `ol_session` (HttpOnly) set by register/login | The bundled SPA |
| Bearer JWT | `Authorization: Bearer <access_token>` from `POST /auth/token` | Scripts, mobile apps, short-lived integrations |
| API key | `X-API-Key: oq_…` created in **Account → API keys** | Long-lived third-party integrations |

### 1.1 CSRF for cookie authentication

A request authenticated **by cookie** and using `POST`, `PUT`, `PATCH` or
`DELETE` must carry the double-submit token:

1. `GET /api/v1/auth/csrf` sets the `ol_csrf` cookie (not HttpOnly) and returns
   the same value in the body.
2. Send `X-CSRF-Token: <value>` on every state-changing request.

Requests authenticated with `Authorization` or `X-API-Key` are exempt: the
token is not ambient, so a cross-site form cannot forge them.

### 1.2 Obtaining a JWT

```bash
curl -sX POST https://quiz.example.org/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"email":"player@example.org","password":"…"}'
```

```json
{ "access_token": "eyJhbGciOi…", "token_type": "bearer", "expires_in": 43200 }
```

### 1.3 Obtaining an API key

```bash
curl -sX POST https://quiz.example.org/api/v1/me/api-keys \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $OL_CSRF" -b cookies.txt \
  -d '{"name":"CI pipeline"}'
```

```json
{
  "id": 3,
  "name": "CI pipeline",
  "prefix": "ol_AbCdEf",
  "key": "ol_…",
  "created_at": "2026-01-01T10:00:00",
  "last_used_at": null,
  "revoked_at": null
}
```

`key` is returned **once**; only its SHA-256 hash is stored. Revoke with
`DELETE /api/v1/me/api-keys/{id}`.

---

## 2. Conventions

### Errors

```json
{ "detail": "Quiz not found." }
```

| Status | Meaning |
| --- | --- |
| `400` | Malformed request |
| `401` | Authentication required or invalid |
| `403` | Authenticated but not allowed (CSRF, wrong host token, quiz not yours) |
| `404` | Unknown resource, or private resource you cannot see |
| `409` | Conflicting state (joining a started session, duplicate answer) |
| `422` | Validation error (field-level details in `detail[]`) |
| `429` | Rate limited, see `Retry-After` |
| `413`/`415` | Upload too large / unsupported media type |

### Rate limits (per client IP)

| Bucket | Limit |
| --- | --- |
| Register, login, token | 10 / 60 s |
| Join a session | 30 / 60 s |
| Upload | 30 / 60 s |
| Account mutations (profile, password, API keys) | 10 / 60 s |

Repeated failed logins additionally lock the account for 15 minutes after five
attempts.

### Roles and tokens

| Token | Obtained from | Sent as |
| --- | --- | --- |
| Host token | `POST /quizzes/{id}/sessions` → `host_token` | `X-Host-Token` |
| Participant token | `POST /sessions/{code}/join` → `participant.token` | `X-Participant-Token` |

The host token is also implicitly granted to the authenticated owner of the
quiz (cookie/JWT/key). Participant tokens are stored hashed and are the only
way to answer, fetch your own state, or reconnect.

---

## 3. Authentication endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/auth/csrf` | Issue or refresh the CSRF cookie/token |
| `POST` | `/auth/register` | Create an account, signs the caller in |
| `POST` | `/auth/login` | Sign in, sets the session cookie |
| `POST` | `/auth/token` | Exchange credentials for a JWT |
| `POST` | `/auth/logout` | Clear cookies |
| `GET` | `/auth/me` | Current user |

**POST /auth/register**

```json
{ "email": "player@example.org", "password": "at-least-ten-chars", "display_name": "Player One" }
```

Returns `201`:

```json
{ "id": 4, "email": "player@example.org", "display_name": "Player One", "created_at": "2026-01-01T10:00:00" }
```

Password policy: 8–128 characters, at least one uppercase letter, one lowercase
letter and one digit or symbol, rejected against a common-password list. Registration and login set `ol_session` (HttpOnly,
SameSite=Lax, `Secure` behind TLS) and `ol_csrf`.

---

## 4. Account endpoints

| Method | Path | Description |
| --- | --- | --- |
| `PATCH` | `/me/profile` | `{"display_name": "…"}` |
| `POST` | `/me/password` | `{"current_password": "…", "new_password": "…"}` |
| `GET` | `/me/api-keys` | List keys (never returns the secret) |
| `POST` | `/me/api-keys` | Create a key, `{"name": "…"}` |
| `DELETE` | `/me/api-keys/{key_id}` | Revoke |
| `GET` | `/me/history` | Sessions played or hosted, newest first |

`/me/history` returns one entry per session the caller took part in — as a
participant or as the host:

```json
[{
  "id": 12, "code": "JVW7CP", "status": "finished", "is_solo": false,
  "quiz_id": 1, "quiz_title": "Splunk Power User - Practice Exam",
  "question_count": 20, "participant_count": 4, "human_count": 3,
  "score": 500, "rank": 2, "is_host": false,
  "created_at": "…", "started_at": "…", "finished_at": "…"
}]
```

`rank` is the caller's position among human players only (host-only rows are
excluded), `human_count` is the size of that field and `question_count` comes
from the session snapshot rather than the live quiz.

---

## 5. Quiz endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/quizzes` | public | List public quizzes; `?mine=true` lists your own (requires auth), `?q=` runs a full-text search, `?limit=&offset=` paginate and `X-Total-Count` carries the size of the result set |
| `POST` | `/quizzes` | cookie+CSRF / key / JWT | Create a quiz (strict: the whole document must already be valid) |
| `POST` | `/quizzes/draft` | owner | Create an autosaved working copy; unfinished documents are accepted |
| `PUT` | `/quizzes/{id}/draft` | owner | Autosave the working copy without touching the published version |
| `GET` | `/quizzes/{id}` | public if `is_public` | Full quiz; the owner reads the working copy, visitors the published version, correct answers only for the owner |
| `PUT` | `/quizzes/{id}` | owner | Replace the whole quiz (questions included); never unpublishes it |
| `DELETE` | `/quizzes/{id}` | owner | Delete the quiz; existing sessions keep their snapshot |
| `POST` | `/quizzes/{id}/duplicate` | owner | Copy a quiz into a new one |
| `POST` | `/quizzes/{id}/visibility` | owner | Move a quiz between `draft`, `private`, `pending` and `public` (publication freezes a version) |
| `POST` | `/quizzes/{id}/publish` | owner | Freeze the working copy as a new version; `{"visibility": "private"}` keeps it out of the catalogue but playable by link, `"public"` sends it to the catalogue or to moderation |
| `GET` | `/quizzes/{id}/results` | owner, or per `results_visibility` | Poll distribution: respondents per option; the author always reads it, respondents read it when the poll allows it, nobody else otherwise |
| `GET` | `/quizzes/{id}/versions` | owner | Version history, newest first |
| `GET` | `/quizzes/{id}/versions/{n}` | owner | Snapshot payload of a version |
| `POST` | `/quizzes/{id}/versions/{n}/restore` | owner | Copy a version back into the working copy; `{"publish": true}` also republishes it |
| `GET` | `/quizzes/{id}/reviews` | owner / public quiz | Safety and answer-key reviews (free text redacted for strangers) |
| `POST` | `/quizzes/{id}/ai/translate` | owner | Translate the quiz into other languages (the configured AI model) |
| `POST` | `/quizzes/{id}/ai/review-legal` | owner / public quiz | Run the safety review |
| `POST` | `/quizzes/{id}/ai/review-answers` | owner / public quiz | Fact-check the answer key |
| `POST` | `/quizzes/{id}/ai/apply-answers` | owner | Apply the latest answer-key corrections |
| `POST` | `/uploads/question-image` | auth | Upload a question image |

**Quiz payload**

```json
{
  "title": "Splunk Power User - Practice Exam",
  "description": "20 practice questions.",
  "wrong_answer_policy": "zero",
  "is_public": true,
  "mode": "qcm",
  "timer_mode": "per_question",
  "global_time_limit_seconds": 0,
  "default_language": "en",
  "languages": ["en", "fr"],
  "questions": [
    {
      "text_html": "<p>Which command aggregates events?</p>",
      "image_path": null,
      "time_limit_seconds": 30,
      "points": 100,
      "multiple_answers": false,
      "options": [
        { "text": "stats", "is_correct": true },
        { "text": "table", "is_correct": false },
        { "text": "top",   "is_correct": false },
        { "text": "dedup", "is_correct": false }
      ]
    }
  ]
}
```

Rules enforced server side:

- `title` 3–120 characters; `questions` 1–200 entries.
- 2–8 options per question, at least one correct — except in a poll, which has
  no answer key at all: `mode: "poll"`, every option `is_correct: false`, and
  `is_correct` never becomes true downstream.
- `allow_multiple` (per question) decides whether the respondent may tick
  several options; in a poll it is the only thing that does, since there is no
  key to count.
- `results_visibility` (`private`, `respondents`, `public`) governs
  `GET /quizzes/{id}/results`: the author always reads the distribution,
  respondents read it when the poll says so, everyone else only when public.
- A question with **one** correct option renders as radio buttons, a question
  with **several** renders as checkboxes (`multiple_answers` in responses).
- `text_html` is sanitised with an allowlist (`p`, `br`, `strong`, `b`, `em`,
  `i`, `u`, `s`, `ul`, `ol`, `li`, `h1`–`h4`, `blockquote`, `code`, `pre`,
  `sub`, `sup`, `span`). Attributes are dropped, so links, images, styles and
  scripts cannot survive. `text_plain` is derived for search and previews.
- `image_path` must be a `/media/…` path returned by the upload endpoint; remote
  URLs are rejected (`422`) to prevent SSRF.
- `time_limit_seconds` 5–600, `points` 0–1000.
- `timer_mode` is `per_question` (each question is timed by its own
  `time_limit_seconds`), `global` (one budget for the whole run, at least 30 s
  and at most 7 200 s in `global_time_limit_seconds`) or `none`. Per-question
  limits are ignored unless the mode is `per_question`. A session snapshots
  the setting at creation, so changing the quiz does not move a live timer.
- `mode` is `qcm` (choice grid) or `swipe` (one statement per card, answered by dragging it right or left).
- `default_language` is the authoring language; `languages` lists every
  translation available for a session.
- Editing a quiz does not affect sessions already created (they hold a
  snapshot). A `PUT` bumps the quiz `version`, which invalidates cached AI
  reviews pinned to the previous `content_hash`.

**Upload**

```bash
curl -X POST https://quiz.example.org/api/v1/uploads/question-image \
  -H "X-API-Key: $OL_KEY" -F "file=@question.png"
```

```json
{ "path": "/media/2026/01/9f3c….webp", "width": 1280, "height": 720, "bytes": 48213 }
```

Max 2 MB, formats PNG/JPEG/WEBP/GIF, longest side 1600 px. Every upload is
decoded and re-encoded to WEBP, which strips EXIF, trailing payloads and
polyglot files.

### 5.1 Publication and moderation

Quizzes start as `draft`. Publication is not self-service unless you are an
administrator or a trusted author:

```bash
curl -X POST https://quiz.example.org/api/v1/quizzes/12/visibility \
  -H "X-CSRF-Token: *** \
  -b cookies.txt -H "Content-Type: application/json" \
  -d '{"visibility": "public"}'
```

```json
{ "id": 12, "status": "pending", "is_public": false,
  "moderation_note": "", "requires_moderation": true }
```

| Requested | Ordinary author | Admin / trusted |
| --- | --- | --- |
| `draft` | `draft` | `draft` |
| `private` | `private` | `private` |
| `public` | first version queued (`pending`) | `public` immediately |

A quiz whose `legal_status` is `blocked` cannot be published (`409`); the
safety review has to pass first. `GET /quizzes/{id}/reviews` returns the
reviewer findings as `{legal_status, answer_status, reviews[], ai_available}`.

### 5.1a Creator statistics

`GET /quizzes/{id}/stats` (owner only, `403` otherwise) aggregates every session
of the quiz, whatever version it was played on:

```json
{
  "quiz_id": 1,
  "sessions": 7,
  "audience": 23,
  "questions": [
    {"source_question_id": 41, "text": "Which SPL command aggregates…",
     "answers": 21, "correct": 16, "success_rate": 76.2}
  ]
}
```

Sessions store a snapshot of the quiz, so the join happens on
`source_question_id` — never on the position, which is shuffled per session. A
question deleted from the working copy still appears, reported through its
snapshot text.

---

### 5.2 Versions, drafts and rollback

Every publication freezes the working copy into an immutable `QuizVersion`
snapshot, so editing never takes a quiz offline:

```
draft (working copy, autosaved)  ──publish──▶  v1  published
        │                                          ▲
        └──edit──▶ working copy                     │ approved by a moderator
                    └──publish──▶ v2 pending ──────┘   (v1 keeps serving visitors)
```

- `POST /quizzes/{id}/publish` validates the working copy against the strict
  schema and the story graph rules (`422` on failure) before freezing it.
- An administrator or a trusted author publishes immediately; anyone else gets
  a `pending` version while `published_version` — the one visitors read — stays
  unchanged.
- `PUT /quizzes/{id}` and `PUT /quizzes/{id}/draft` only touch the working copy.
- The public catalogue, the quiz page and every new session read the published
  snapshot. A session already running keeps its own copy as well.

```bash
# publish the working copy
curl -X POST https://quiz.example.org/api/v1/quizzes/12/publish \
  -H "X-CSRF-Token: $OL_CSRF" -b cookies.txt -H "Content-Type: application/json" -d '{"note": ""}'

# history, then rollback to v1 and put it back online
curl -b cookies.txt https://quiz.example.org/api/v1/quizzes/12/versions
curl -X POST https://quiz.example.org/api/v1/quizzes/12/versions/1/restore \
  -H "X-CSRF-Token: $OL_CSRF" -b cookies.txt -H "Content-Type: application/json" \
  -d '{"publish": true}'
```

Rolling back creates a new version from the old content, so the history stays
linear. A version that had already been approved skips moderation on restore;
an unapproved one goes back to the queue.

```json
{ "id": 12, "status": "pending", "is_public": true,
  "requires_moderation": true, "published_version": 1,
  "version": { "number": 2, "status": "pending", "question_count": 20 } }
```

A story may also carry an optional clock, inside its `adventure` object:

```json
{ "timer_mode": "per_node", "time_limit_seconds": 90,
  "timeout_effect": "penalty", "timeout_penalty": 2,
  "timeout_penalty_attribute": "confidence" }
```

`timer_mode` is `none`, `global` (one budget for the whole run, stored in
`run_deadline`) or `per_node` (a fresh budget per scene, in `node_deadline`).
`timeout_effect` decides what a missed scene costs: `penalty` lowers an
attribute (which may itself trip a death threshold) or `death` ends the run
early. When the clock runs out the client asks
`POST /adventure/runs/{token}/timeout`, but the server alone decides: it
answers `409` unless its own deadline has really passed, so a paused tab or a
hand-written request cannot skip the wait.

Autosave is deliberately permissive: empty titles, empty answer texts and an
unfinished story graph are accepted, because the point is to survive a closed
tab. `mode`, `questions` and `adventure` keep the same shape as the strict
payload, so a draft is promoted to a version without conversion.

### 5.3 AI assistance

| Endpoint | Effect |
| --- | --- |
| `POST /quizzes/{id}/ai/translate` | Body `{"languages": ["fr", "es"], "overwrite": false}`; fills the translation maps of the title, description, questions and options |
| `POST /quizzes/{id}/ai/review-legal` | Returns `{status, summary, findings[]}`; `blocked` un-publishes the quiz |
| `POST /quizzes/{id}/ai/review-answers` | Returns `{status, summary, corrections[]}`; corrections are proposals only |
| `POST /quizzes/{id}/ai/apply-answers` | Applies the proposals of the last review pinned to the current `content_hash` (`409` if none) |

Reviews are cached per `content_hash`: re-running a review on unchanged content
returns the stored result and does not spend model tokens. Every AI route is
rate limited (`ai` bucket) and answers `503` when `OL_AI_ENABLED=false`.

### 5.4 AI quiz generation

```bash
curl -X POST https://quiz.example.org/api/v1/ai/quizzes \
  -H "X-API-Key: $OL_API_KEY" -H "Content-Type: application/json" \
  -d '{"topic": "Splunk SPL commands", "question_count": 10,
       "mode": "qcm", "language": "fr", "level": "intermediate",
       "save": true}'
```

With `save: false` the draft is returned without touching the database; with
`save: true` it is created as a `draft` owned by the caller and still has to go
through moderation. Generated content is validated and sanitised exactly like
hand-written content. `GET /ai/status` reports `{available, model, languages,
web_search}`.

---

## 6. Session endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/quizzes/{id}/sessions` | auth for live, public for solo | Create a session |
| `GET` | `/join/{join_token}` | public | Resolve a share link |
| `GET` | `/sessions/{code}` | public | Session overview (no questions) |
| `POST` | `/sessions/{code}/join` | public | Join the lobby |
| `GET` | `/sessions/{code}/join-link` | host | Share link + PIN |
| `GET` | `/sessions/{code}/state` | host or participant | Full state for rendering |
| `POST` | `/sessions/{code}/start` | host | Lock the lobby and start question 1 |
| `POST` | `/sessions/{code}/reveal` | host | Show the correct answer |
| `POST` | `/sessions/{code}/next` | host | Move to the next question |
| `POST` | `/sessions/{code}/cancel` | host | Abort the session |
| `POST` | `/sessions/{code}/finish` | host | Close and compute final scores |
| `POST` | `/sessions/{code}/answers` | participant | Submit an answer |
| `GET` | `/sessions/{code}/results` | host, or participant after finish | Detailed review |

**Create a session**

```json
{ "mode": "live", "nickname": null, "language": "fr", "play_as_host": false }
```

`play_as_host: true` also enrols the host as a participant of their own live
session: the participant row and its token are created with the session, so the
lobby lists the host immediately and they can answer from the host screen.

`mode` is `live` (lobby, host must be signed in) or `solo` (starts immediately,
the creator is also a participant; `nickname` names them). `language` picks the
presentation language of the session among the quiz translations; the questions
and answer texts are served already translated, and a session never changes
language once started.

```json
{
  "session": {
    "id": 1, "code": "JVW7CP", "quiz_title": "Splunk Power User - Practice Exam",
    "status": "lobby", "phase": "idle", "is_solo": false,
    "question_count": 20, "participant_count": 0,
    "started_at": null, "finished_at": null
  },
  "host_token": "…",
  "join_url": "https://quiz.example.org/join/d5zOAIwd…",
  "join_token": "d5zOAIwd…",
  "participant": null,
  "state": { "…": "see §6.1" }
}
```

**Resolve a share link**

`GET /join/{join_token}` is public and always answers `200` with a `state`
field, so the SPA can explain why a link does not work instead of showing a
dead end:

| `state` | Meaning |
| --- | --- |
| `ok` | The lobby accepts players |
| `invalid` | Unknown or revoked link |
| `already_started` | The host already started the session |
| `full` | The session reached its player cap |

```json
{ "state": "already_started", "session": { "code": "JVW7CP", "quiz_title": "…", "…": "…" } }
```

**Join**

```json
{ "nickname": "Bob" }
```

`201`:

```json
{
  "participant": { "id": 1, "nickname": "Bob", "token": "ttNZI6yl…" },
  "session": { "code": "JVW7CP", "status": "lobby", "participant_count": 1, "…": "…" },
  "state": { "…": "…" }
}
```

- Solo sessions cannot be joined (`403`).
- Once the host starts, joins are refused with `409` — the lobby is closed.
- The share link is copied client side; on a plain-HTTP origin the SPA falls back
  to `document.execCommand("copy")` because `navigator.clipboard` only exists in
  secure contexts.
- Nicknames are 1–30 characters, trimmed, HTML-escaped on render.

**Answer**

```json
{ "question_id": 7, "option_ids": [21, 24] }
```

`201`:

```json
{
  "answer": { "id": 4, "question_id": 7, "is_correct": false, "points_awarded": 0, "response_ms": 620 },
  "score": 200
}
```

- Only the current question is accepted (`409` otherwise), one answer per
  participant per question (`409`), and nothing after the deadline.
- `option_ids` must belong to the question. Sending the full correct set is
  required for multi-answer questions: a subset, or a superset containing a
  wrong option, is scored as wrong.

### 6.1 State payload

```json
{
  "session": {
    "id": 1, "code": "JVW7CP", "status": "active", "phase": "question",
    "quiz_title": "…", "wrong_answer_policy": "zero", "is_solo": false,
    "question_count": 20, "current_index": 3,
    "started_at": "…", "finished_at": null
  },
  "participants": [{ "id": 1, "nickname": "Bob", "score": 200, "is_host": false }],
  "question": {
    "id": 7, "position": 3, "text_html": "<p>…</p>", "text_plain": "…",
    "image_path": null, "time_limit_seconds": 30, "points": 100,
    "multiple_answers": true,
    "options": [{ "id": 21, "text": "stats" }],
    "started_at": "…", "deadline": "…", "remaining_ms": 21400,
    "answered_ids": [2]
  },
  "reveal": {
    "correct_option_ids": [21, 24],
    "options": [{ "id": 21, "text": "stats", "is_correct": true, "count": 3 }],
    "results": [{ "participant_id": 1, "is_correct": true, "points_awarded": 100 }],
    "answered_count": 4, "participant_count": 5
  },
  "scoreboard": [{ "id": 1, "nickname": "Bob", "score": 200 }],
  "me": { "…": "participant-specific view" },
  "server_time": "…"
}
```

`question` is `null` in the lobby and `reveal` is `null` until the reveal phase.
Correct answers are never present before the reveal.

**Question order.** `qcm` and `swipe` sessions shuffle the question order and,
for `qcm`, the option order, once when the session starts. Every participant of
that session receives the same shuffled order, and it is stored in the session
snapshot, so the state payload is stable across reloads. A `swipe` deck keeps
its authored option order because the card's gestures are bound to "no" (left)
and "yes" (right). `adventure` runs follow the authored workflow order.

### 6.2 Results

```json
{
  "session": { "code": "JVW7CP", "status": "finished", "started_at": "…", "finished_at": "…" },
  "scoreboard": [{ "id": 1, "nickname": "Bob", "score": 200, "user_id": null }],
  "questions": [{
    "id": 1, "position": 0, "text_html": "…", "time_limit_seconds": 30, "points": 100,
    "options": [{ "id": 1, "text": "search", "is_correct": true }],
    "correct_option_ids": [1],
    "answers": [{ "participant_id": 1, "nickname": "Bob", "selected_option_ids": [1],
                  "is_correct": true, "points_awarded": 100, "response_ms": 4751 }]
  }]
}
```

Participants may read the results once the session is finished; the host can
read them at any time.

---

## 7. WebSocket

```
wss://quiz.example.org/api/v1/sessions/{code}/ws?token=<host_token|participant_token>
```

- `4401` — no valid token (host token, participant token, or owner cookie).
- `4404` — unknown session code.
- The server pushes `{"type": "state", "state": {…}}` on connect and after every
  change (join, start, answer, reveal, next, finish, timer expiry).
- The client may send the text frame `ping`, answered with `{"type": "pong"}`.
- Answers are **not** accepted over the socket: use `POST /sessions/{code}/answers`
  so validation, scoring and rate limiting always apply.

Clients should reconnect with exponential backoff and refresh state over REST
after reconnecting (`GET /sessions/{code}/state`).

---

## 8. Administration

Every route below requires an administrator (`403` otherwise). They are what the
`/admin` page of the web interface calls, so the UI and the API stay in sync.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/admin/stats` | Counts by status, users, reviews |
| `GET` | `/admin/quizzes` | All quizzes; `?status=`, `?q=`, `?limit=`, `?offset=` |
| `GET` | `/admin/quizzes/{id}` | One quiz, correct answers included |
| `PUT` | `/admin/quizzes/{id}` | Replace a quiz (`QuizIn` payload) |
| `DELETE` | `/admin/quizzes/{id}` | Delete a quiz |
| `POST` | `/admin/quizzes/{id}/approve` | Publish, body `{"note": "..."}` |
| `POST` | `/admin/quizzes/{id}/reject` | Reject, body `{"note": "..."}` |
| `GET` | `/admin/reviews` | AI reviews; `?kind=legal\|answers`, `?status=` |
| `GET` | `/admin/users` | Accounts; `?q=` on email and display name |
| `PATCH` | `/admin/users/{id}` | Set `is_admin`, `is_trusted`, `is_active` |
| `DELETE` | `/admin/users/{id}` | Delete an account (quizzes cascade) |
| `GET` | `/admin/events` | Security audit log; `?kind=`, `?limit=` |

An administrator cannot revoke their own admin rights or disable their own
account (`409`), so a single-operator instance can never lock itself out.

---

### 8.1 Wiki moderation

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/admin/wikis` | Wikis; `?status=pending\|public\|private\|draft` |
| `POST` | `/admin/wikis/{id}/approve` | Publish publicly, body `{"note": "..."}` |
| `POST` | `/admin/wikis/{id}/reject` | Send back to private, with a note |

Administrators also read every wiki and write in it as `maintainer`: editing a
page, renaming a wiki or saving its canvas answers `200`, not a `403` telling
them to file a proposal against themselves. Moderation stays available through
the two routes above.

---

## 9. Wiki endpoints

A wiki is a set of markdown pages with history, links and moderation. Reading is
open for public wikis; private wikis are invisible (`404`) to anybody without a
role in them.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/wiki` | List readable wikis; `?scope=all\|mine`, `?q=` |
| `POST` | `/wiki` | Create a wiki (`title`, `description`, `default_language`) |
| `GET` | `/wiki/{id}` | Metadata, pages, canvas, your role (`can_write`, `can_delete`), pending proposals |
| `PUT` | `/wiki/{id}` | Rename, redescription, default language |
| `DELETE` | `/wiki/{id}` | Delete the wiki and everything under it (owner or admin) |
| `POST` | `/wiki/{id}/publish` | `{"visibility": "private"\|"public"}` |
| `GET` | `/wiki/{id}/pages` | Page list with slugs and versions |
| `POST` | `/wiki/{id}/pages` | Create a page (`title`, `content_md`, `tags`) |
| `GET` | `/wiki/pages/{page_id}` | One page: markdown, rendered HTML, metadata |
| `PUT` | `/wiki/pages/{page_id}` | Save (`status: "saved"`) or file a suggestion (`status: "proposal"`) |
| `DELETE` | `/wiki/pages/{page_id}` | Delete a page (writers only). Its sub-pages move up one level, its versions, links, citations and proposals go with it |
| `GET` | `/wiki/pages/{page_id}/versions` | History, newest first |
| `GET` | `/wiki/pages/{page_id}/versions/{n}` | One version |
| `GET` | `/wiki/pages/{page_id}/diff?from=&to=` | Diff between two versions: `rows`/`stats` (unified) plus `side` — hunk, same and change rows with left/right cells and word-level `segments` — and `labels` (`from`, `to`, `page`) |
| `POST` | `/wiki/pages/{page_id}/versions/{n}/restore` | Copy that version forward as a new one |
| `GET` | `/wiki/{id}/graph` | Nodes and edges of the `[[link]]` graph |
| `GET`/`PUT` | `/wiki/{id}/canvas` | Free canvas: `{"nodes": [...], "edges": [...]}` |
| `GET` | `/wiki/{id}/export` | `text/markdown` for the wiki home page |
| `GET` | `/wiki/{id}/export.zip` | Zip of every page, links rewritten |
| `POST` | `/wiki/import` | Create a wiki from a zip: `multipart/form-data` field `file`. Obsidian vaults, Joplin notebooks and plain markdown folders are recognised; front matter, `[[wikilinks]]`, attachments and folder titles carry over. Answers the created wiki |
| `POST` | `/wiki/{id}/pages/import` | Add one page from a markdown file (field `file`, ≤ 1 MB). Answers `{"page": {...}}` |
| `GET` | `/wiki/search?q=` | Full-text search across readable wikis; `?scope=local` stays inside `wiki_id`, `scope=all` reaches every readable public wiki |
| `GET` | `/wiki/{id}/templates` | Page templates of this wiki (readable by anyone who may read the wiki) |
| `POST` | `/wiki/{id}/templates` | Create a skeleton: `name`, `description`, `keywords[]`, `content_md` (writers only) |
| `PUT` | `/wiki/{id}/templates/{tid}` | Rewrite a template; the wiki in the path must own it, else `404` |
| `DELETE` | `/wiki/{id}/templates/{tid}` | Delete a template; pages already written with it are untouched |
| `GET` | `/wiki/{id}/proposals` | Suggestions on this wiki (owner, maintainer, admin) |
| `POST` | `/wiki/{id}/proposals/{pid}/accept\|reject` | Decide on a suggestion |
| `GET`/`POST`/`DELETE` | `/wiki/{id}/members` | Roles: `maintainer` or `contributor` |
| `PUT` | `/wiki/{id}/tree` | Reorder the menu: `{"pages": [{"id", "parent_id", "position"}]}`, ≤ 500 pages, depth ≤ 6, cycles refused |
| `GET` | `/wiki/pages/{page_id}/references` | Citations of one page: `external`, `internal`, `detected`, `missing` |
| `POST` | `/wiki/pages/{page_id}/references` | Cite a source: `{"kind": "external"\|"internal", "url"\|"target_slug", "label", "note"}` |
| `DELETE` | `/wiki/pages/{page_id}/references/{ref_id}` | Drop a citation |
| `GET` | `/wiki/{id}/references` | Whole-wiki index: every source with the pages citing it, internal links, unresolved `[[links]]`, orphan pages, and `stats` |
| `WS` | `/wiki/pages/{page_id}/live` | Live co-editing (see below) |

Page detail also carries `parent_id`, `breadcrumb` (root first), the wiki `tree`
and the page's `references`, `external_links` and `missing_links`.

### Live co-editing socket

`ws(s)://…/api/v1/wiki/pages/{page_id}/live` — one socket per open page.

| Direction | Message |
|---|---|
| server → client | `{"type": "hello", "client_id", "rev", "content", "version", "can_write", "me", "users"}` |
| server → client | `{"type": "presence", "users": [...]}` when somebody joins or leaves |
| server → client | `{"type": "op", "rev", "pos", "delete", "insert", "client_id", "name", "color", "conflict"}` |
| server → client | `{"type": "reset", ...}` after a save or a restore froze a version |
| client → server | `{"type": "op", "rev": <the revision you started from>, "text": "<the whole page>"}` |
| client → server | `{"type": "cursor", "anchor": <char offset>, "head": <char offset>}` |
| server → client | `{"type": "denied", "reason": "read-only"}` — a reader may watch, not write |

The server keeps the only copy that matters: it merges the client's text with the
room's against the revision the client started from (line by line, then word by
word inside a conflicting paragraph), then broadcasts **one minimal splice** that
every screen applies in the same order. Convergence comes from that ordering, not
from the clients. A real conflict keeps both versions and sets `conflict: true`.
Live text is persisted after the typing stops, without creating a version: only
`Save` does, so history stays a record of deliberate decisions.

### Images in a page

| Method | Path | Description |
|---|---|---|
| `POST` | `/uploads/image` | Wiki image, 10 MB, re-encoded to WebP (≤2400 px) |

The editor inserts `![alt](/media/x.webp)` and lets the author size the picture
from the rich view. The width travels in the markdown itself:
`![alt](/media/x.webp){width=320}` or `{width=50%}`. The renderer turns it into a
`width` attribute and the sanitiser only accepts `\d{1,4}` with an optional `%`,
so a hand-written value can never become a style attribute.

Roles: `owner` and `maintainer` write the live page; `contributor` and any other
reader who can see the wiki produce a proposal instead; administrators act as
`maintainer` everywhere.

### 9.1 AI jobs

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/wiki/ai/jobs` | `{"kind": "generate"\|"fill"\|"review"\|"grammar"\|"compliance", ...}` — `generate` targets a wiki and writes pages, `fill` writes the body of the page open in the editor and stores nothing |
| `GET` | `/wiki/ai/jobs/{id}` | `status`, `progress`, `message`, `result` |
| `POST` | `/wiki/ai/chat` | `{"question", "chat_id", "wiki_ids", "language"}` |
| `GET` | `/wiki/ai/chats` | Your conversations |

A `generate` job takes `topic`, `style`, `audience`, `research`, `page_count`
(0 = decide from the brief), and `instructions`: up to 4000 characters of prose
saying what the pages must cover. The brief is passed to the outline *and* to
every page, so the result follows it instead of drifting back to the title.

The chat answers only from pages the caller may read, cites each extract it
used, and replies in the requested language — including its "nothing found"
message. Duplicate jobs of the same kind on the same topic answer `409` with the
running `job_id` instead of spending twice; the 15-second AI interval applies.

---

## 10. Complete example (curl)

```bash
BASE=https://quiz.example.org/api/v1
JAR=$(mktemp)

# 1. CSRF cookie
CSRF=$(curl -s -c "$JAR" "$BASE/auth/csrf" | python3 -c 'import json,sys;print(json.load(sys.stdin)["csrf_token"])')

# 2. Register (or log in)
curl -s -b "$JAR" -c "$JAR" -X POST "$BASE/auth/register" \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
  -d '{"email":"host@example.org","password":"Str0ngPassword!23","display_name":"Host"}' >/dev/null

# 3. Create a session on an existing public quiz
SESSION=$(curl -s -b "$JAR" -X POST "$BASE/quizzes/1/sessions" \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"mode":"live"}')

CODE=$(echo "$SESSION" | python3 -c 'import json,sys;print(json.load(sys.stdin)["session"]["code"])')
HOST=$(echo "$SESSION" | python3 -c 'import json,sys;print(json.load(sys.stdin)["host_token"])')

# 4. A guest joins, then the host starts
JOIN=$(curl -s -X POST "$BASE/sessions/$CODE/join" -H 'Content-Type: application/json' -d '{"nickname":"Bob"}')
PTOK=$(echo "$JOIN" | python3 -c 'import json,sys;print(json.load(sys.stdin)["participant"]["token"])')

curl -s -X POST "$BASE/sessions/$CODE/start" -H "X-Host-Token: $HOST" >/dev/null

# 5. Read the current question, answer, reveal
STATE=$(curl -s "$BASE/sessions/$CODE/state" -H "X-Participant-Token: $PTOK")
QID=$(echo "$STATE"  | python3 -c 'import json,sys;print(json.load(sys.stdin)["question"]["id"])')
OID=$(echo "$STATE"  | python3 -c 'import json,sys;print(json.load(sys.stdin)["question"]["options"][0]["id"])')

curl -s -X POST "$BASE/sessions/$CODE/answers" \
  -H 'Content-Type: application/json' -H "X-Participant-Token: $PTOK" \
  -d "{\"question_id\":$QID,\"option_ids\":[$OID]}"

curl -s -X POST "$BASE/sessions/$CODE/reveal" -H "X-Host-Token: $HOST" >/dev/null
curl -s -X POST "$BASE/sessions/$CODE/finish" -H "X-Host-Token: $HOST" >/dev/null
curl -s "$BASE/sessions/$CODE/results" -H "X-Host-Token: $HOST"
```

---

## 11. Static routes

| Path | Description |
| --- | --- |
| `/` and any unknown path | SPA shell (`index.html`) |
| `/media/{year}/{month}/{file}.webp` | Uploaded question images |
| `/api/v1/health` | `{"status":"ok","app":"OpenLearn","version":"1.0.0"}` |
| `/docs` | Reference rendered by the app from the live OpenAPI document |
| `/api/openapi.json` | OpenAPI 3.1 document of this instance |
| `/api/docs`, `/api/redoc` | `307` redirect to `/docs` |
