---
layout: doc
title: Troubleshooting — email, expired links, common errors
description: >-
  Fix the most frequent OpenLearn problems: missing confirmation email, unusable reset link,
  429 responses, live mode not starting, AI features missing, refused uploads.
permalink: /guide/troubleshooting/
---

<p class="doc-eyebrow">Guide · Email, links, common errors</p>

# Troubleshooting

## I am not receiving the confirmation email

1. **Check the spam folder** — the most frequent cause, especially on an instance whose domain has
   not yet published its SPF, DKIM and DMARC records.
2. **Wait five minutes** before asking again: a new send is only possible after that delay, and
   clicking ten times produces a single link.
3. **Try another address** if your provider blocks the sending domain.
4. **The administrator** can check the **Mail** tab and send a test message. A test that does not
   arrive locates the problem on the server side, not the user side.

An unconfirmed address blocks nothing: you can work normally, only the publication notice will be
missing.

## My reset link does not work

- A link **expires** (duration set by the administrator) and a link **already used** no longer
  works: request a new one from `/forgot`.
- Only one link is valid at a time: requesting a new one invalidates the previous ones. If two
  emails arrived, only the most recent works.

## "Too many requests" (429)

The rate limit protects the forms. It applies per network address and per window:

- wait until the window ends (often one minute);
- behind a corporate proxy or a shared VPN you may share the address with many people — hence a
  429 that is not about you personally;
- repeated hammering may trigger a **temporary ban** of a few minutes, independent of the password.

Repeated wrong passwords lock the **account** for a while; the lock message only appears after a
correct password, so as not to reveal that the account exists.

## The live mode will not start

- The **PIN** is valid for one session: if it is refused, the session has ended or been cancelled.
  Create a new one from the quiz page.
- Players must be on the **same instance** as the host: a `/play/<code>` link from one instance does
  not work on another.
- A single-attempt quiz refuses a second participation by the same account, including in live mode,
  and including the host if they chose to play.
- If the screen freezes, reload: the session survives a reload as long as the host has not closed
  it.

## The AI features do not appear

That is expected: with no provider configured, the interface **hides** the buttons instead of
showing them failing. Ask the administrator whether a model is configured; the **Model provider**
tab says so, with a test button.

## The image upload is refused

- Accepted formats: common images (JPEG, PNG, WebP, GIF) within a size limit.
- An oversized file is refused by the server, not the browser: shrink it before dropping it.
- Instance media live in the data volume: they are backed up with the database and restored with
  it.

## My page disappeared from the history

It has not disappeared: **History** lists versions, and a restore creates a new version without
erasing the previous ones. If the whole page is gone, check you are in the right wiki space and
that your role gives access to drafts.

## Nothing displays, the page stays blank

- Clear the cache or reload without cache.
- Check the browser console: an extension blocking scripts breaks the interface.
- On an older instance, a partial deployment sometimes leaves inconsistent files: report it to the
  operator, with the time and the page.

## Reporting a problem

For a software defect: an issue on the repository, with the screen, the browser, what you expected
and what happened. For an **accessibility** problem, the `accessibility` label is treated as a
blocking defect. For anything specific to a given instance — account, content, email — see its
administrator: the project does not hold the data of each installation.
