---
layout: doc
title: API and MCP — automate OpenLearn, connect an agent
description: >-
  Use the OpenLearn HTTP API with a personal key, browse the OpenAPI reference, and connect an
  agent to the MCP server with the rights of an account.
permalink: /guide/api-mcp/
---

<p class="doc-eyebrow">Guide · Automate, connect an agent</p>

# API and MCP

Everything the interface does goes through an HTTP API: there is no privileged path. That is what
makes automation possible, and it is also why an API key must be treated like a password.

## Getting a key

1. **Account** → **API keys** → **Create a key**.
2. Name it after its use ("card import", "backup robot").
3. Copy the value: it is not shown again.
4. Revoke it as soon as it is no longer useful.

Every key acts **with the rights of the account that created it**. There is no finer scope: if you
want a read-only key, create a dedicated account.

## Calling the API

```bash
curl -H "Authorization: Bearer $OPENLEARN_KEY" \
     https://your-instance.example/api/v1/auth/me
```

Resources follow the objects of the product: `/api/v1/wiki`, `/api/v1/quizzes`, `/api/v1/cards`,
`/api/v1/auth`, `/api/v1/admin`. Failures come back with an explicit HTTP code — 401
unauthenticated, 403 forbidden, 404 missing, 409 conflict, 422 validation, 429 too many requests.

Two practical rules:

- Writes expect a CSRF token when you use a browser session; with an API key, the
  `Authorization` header is enough.
- Lists are paginated. A script that ignores pagination will believe there is only the first page.

## The full reference

Every instance publishes its own reference, generated from the code:

- `/docs` — the OpenAPI explorer, with a search filter;
- `/api/openapi.json` — the raw document, to load into Postman, Insomnia, or generate a typed
  client from.

An instance's reference reflects exactly its version: that is more reliable than documentation
copied out by hand.

## The MCP server

OpenLearn embeds an **MCP** (Model Context Protocol) server. An agent — a desktop assistant, an MCP
client, an orchestration script — can therefore read and create wiki pages or quizzes with the
rights of the account that authorises it.

- Activation is server-side (`OL_MCP_ENABLED`); the **Environment** tab of the administration area
  says whether it is on.
- The instance's `/docs/mcp` screen gives the endpoint URL and the tools exposed.
- Authentication uses an API key: an agent never has more rights than the key it is given.

<div class="note">
<p><strong>An agent writes, it does not check.</strong> A model drafting a wiki page produces a
plausible page, not a true one. In a teaching context, have it reviewed: editorial responsibility
is not delegated to an API key.</p>
</div>

## Reasonable use cases

| Goal | Means |
| --- | --- |
| Import a question bank prepared elsewhere | `POST /api/v1/quizzes`, then add the questions |
| Back up a wiki's pages as Markdown | `GET /api/v1/wiki`, then export each page |
| Feed a results dashboard | CSV export from the interface, or the statistics endpoints |
| Have an agent draft a card | Dedicated key, then human review before publication |
| Sync with an LMS or another wiki | JSON import/export, or scheduled API calls |

## Limits to know

- **Rate limits** apply to keys too: a bulk import must slow down or stagger its calls.
- **Rights follow the account**: an author's key cannot publish, it can only request publication.
- A **deletion** is a deletion, even through the API: there is no general recycle bin. Back up
  before writing a script that erases.
