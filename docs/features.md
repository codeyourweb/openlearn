---
title: Features — wiki, quizzes, spaced repetition, API and MCP
description: >-
  What OpenLearn does in detail: a versioned Markdown wiki, live quizzes, revision cards, roles
  and moderation, a REST API, an MCP server, import/export and backups.
permalink: /features/
---

# Features

<p class="muted small">What the software does today, with no wish list.</p>

## Collaborative wiki

- **Markdown pages**, rendered with strict sanitising (tag allow-list).
- **Versions**: every save creates a revision you can read and restore.
- **Structure**: page tree, sections, and a visual graph of links between pages.
- **References**: per-page bibliography, reusable citations, dead-link detection.
- **Full-text search** across titles and bodies, filtered by space.
- **Page templates** for recurring formats (fact sheet, procedure, notice).
- **Two-step publication**: a draft, then a publication request; the page becomes public once a
  moderator has approved it.
- **Optional AI assistant**: a discussion panel anchored on the current page, enabled only when
  the administrator has configured a provider. Otherwise it does not exist in the interface.

## Quizzes

- **Single choice** or **multiple choice** questions, any number of options, an explanation per
  option.
- **Confidence ratings**: the learner states how sure they are, which separates a careless slip
  from a real gap.
- **Live mode**: a host starts the game, players join with a PIN, questions advance, a scoreboard
  builds up. Works in a room and remotely.
- **Solo games** with an attempt limit configurable per quiz.
- **Assessment**: score, per-question detail, time per question, CSV export.
- **JSON import and export** to prepare a quiz offline and load it later.

## Spaced repetition

A wrong answer can be turned into a **revision card**. The engine serves the card again after an
interval that lengthens with each success (a simplified SM-2) and shortens on failure. Cards are
grouped in decks, by theme or by quiz.

## Accounts, roles and moderation

| Role | Can | Cannot |
| --- | --- | --- |
| Visitor | Read public content, play public quizzes | Write |
| Author | Create wikis and quizzes, request publication | Publish directly |
| Moderator | Approve or refuse publications, handle reports | Reach AI, mail or SSO settings |
| Administrator | Everything, including accounts, mail, AI, SSO, backups | — |

- **Address verification** by link sent at sign-up, resendable from the account page.
- **Password reset** limited to one message every five minutes per address.
- **Anti-spam protection**: a visitor hammering a form (sign-in, reset, sign-up) gets a temporary
  ban held in memory, with no reputation system behind it.
- **Publication notice**: an email tells the author as soon as their wiki or quiz goes public,
  with the moderator's note when there is one.

## Interface and API

- **Twelve languages**: French, English, German, Spanish, Italian, Russian, Chinese, Japanese,
  Portuguese, Hindi, Bengali and Arabic — with an automatic switch to right-to-left layout.
- **Light and dark themes**, verified contrast, respect for `prefers-reduced-motion`.
- **Full keyboard navigation**, a skip link, spoken announcements on state changes.
- **Documented REST API** (OpenAPI): everything the interface does goes through the API.
- **Per-account API keys**, with revocation.
- **MCP server**: an agent (Claude, or any compatible client) can read and create pages and
  quizzes with the rights of the account that authorises it.

## Operations

- **One Docker image**, SQLite by default, PostgreSQL possible for busy instances.
- **Backup**: consistent copy of the database (the `.backup` API), media archive, script
  included.
- **Restore**: documented and tested.
- **Safe deployment**: keeps the previous image, allows an immediate rollback, measures the
  interruption, and refuses to replace an instance whose content counters went down.
- **Health** exposed on `/api/v1/health` for simple monitoring.
- **Single sign-on** over OIDC (Keycloak, Authentik, Google Workspace…) as an option.

<p class="muted small">
A feature missing from this page does not exist yet. Requests are tracked in the repository's
issues, not in a roadmap kept secret.
</p>
