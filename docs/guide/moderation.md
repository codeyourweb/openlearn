---
layout: doc
title: Moderating and administering — publications, accounts, settings
description: >-
  Approve or refuse a publication, notify the author, manage accounts and roles, configure mail,
  AI and single sign-on, review temporary bans.
permalink: /guide/moderation/
---

<p class="doc-eyebrow">Guide · Publications, accounts, settings</p>

# Moderating and administering

This page covers two distinct roles. A **moderator** sees the publication queue and the reports;
they reach neither the mail configuration, nor the AI configuration, nor the creation of
administrator accounts. An **administrator** has access to everything.

## The publication queue

A wiki or a quiz requested for publication arrives with the status **Pending review**. The queue is
found in the administration area, on the publications tab.

For each item the screen shows: the title, the author, the status, the date of the request, and a
preview of the content. Two actions:

- **Approve** — the item becomes **public** immediately.
- **Refuse** — the item goes back to **private**, with a note that is required in practice: that
  is what explains the decision to the author.

A **note** accompanies every decision. It is sent to the author in the notification email, and
stays visible in the item's history.

<div class="note">
<p><strong>The author is told, once.</strong> On approval, an email goes automatically to the
author's address: title, link to the content, moderator's note. If a moderator approves their own
content, no email is sent — nobody needs to be told about their own action. A refusal sends no
email: the reason is shown in the interface, and the author sees it on returning to their
content.</p>
</div>

### What a moderator should look at

- Is the content understandable without its author sitting next to you?
- Are sources cited, where the subject calls for it?
- Does the title match the content, or does it promise something else?
- For a quiz: are the corrections right? A factual error in a correction is more serious than a
  typo.

The role is to say **yes or no with a reason**, not to rewrite someone's work.

## Managing accounts

The administration area lists accounts with their roles:

| Role | Scope |
| --- | --- |
| **Author** | Writes, requests publication |
| **Moderator** | Approves publications, does not touch sensitive settings |
| **Administrator** | Everything: accounts, mail, AI, SSO, legal notices |

The usual actions: promote or demote an account, disable an account (without deleting it), reset a
password in an emergency.

## Instance settings

The **Settings** tab groups four blocks:

- **Instance** — the name shown in the header and in emails, the default language, registration
  open or closed.
- **Mail** — SMTP server, port, credentials, sender address, with a **Send a test message**
  button. A test email that does not arrive is the first symptom of an incomplete setting; check
  SPF, DKIM and DMARC on the domain next.
- **Registration and security** — sign-in attempt ceiling, validity of reset links, minimum
  interval between two requests.
- **Model provider** — OpenAI-compatible URL, model, key. A **Test the connection** button reports
  the model and the response time. Without a provider, the AI features disappear from the
  interface instead of failing at the point of use.

Values fixed by the deployment (demo mode, database, TLS, MCP server) are shown read-only: they
come from the environment, not from the screen.

## Single sign-on

The **Single sign-on** tab: add an OIDC provider (Keycloak, Authentik, Google Workspace…) or SAML.
Fields needed: issuer URL, client identifier, secret, allowed domains, and the callback URL to
declare at the provider (shown by the screen). The state reads **Ready**, **Incomplete** or
**Disabled**.

The **Create unknown accounts** option decides whether someone authenticated by the provider gets
an account automatically. When disabled, only existing accounts can sign in that way.

## Bans and abuse

A visitor hammering a form (sign-in, sign-up, forgotten password) receives warnings, then a
**temporary ban** — held in memory, with an expiry. The administration screen lists the addresses
concerned, the reason and the deadline, and lets you lift a ban.

Private networks and trusted proxies are exempt: without that, a reverse proxy would give every
visitor the same address, and the first spammer would ban everyone.

## AI error log

When a call to the model fails, the error is recorded (**AI error log** tab) with the date, the
entry point and the message. It is the first place to look when "translation stopped working" or
"the AI draft does not answer".

## Legal notices

The **Legal notices** tab: publisher, host, contact, and the texts shown on `/legal`. A public
instance must fill them in; the demonstration fills them as an example.

## Good practice

- An administrator does not moderate their own content: hand validation to another account.
- Test mail **after every change** to the SMTP configuration.
- Before an upgrade, take a backup and verify the restore: see
  [Self-hosting]({{ '/self-hosting/' | relative_url }}).
