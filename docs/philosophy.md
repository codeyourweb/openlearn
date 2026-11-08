---
title: The philosophy behind OpenLearn — free software, common knowledge, restraint
description: >-
  Why OpenLearn is AGPL-licensed, tracker-free, WCAG 2.2 AA accessible, free of intrusive
  analytics, and designed to run for ten years on a modest server.
permalink: /philosophy/
---

<p class="muted small">Philosophy · about a seven-minute read</p>

# The philosophy behind OpenLearn

Software always says something about the people who wrote it. This one starts from four
convictions, and every technical decision below follows from them. They are not slogans pasted at
the top of a repository: they are constraints that cost time, occasionally features, and that
explain what the code looks like today.

## 1. Knowledge does not belong under lock and key

A modern learning platform often works like a ticket window: you pay, you enter, you consume,
you leave. The content teachers produce stays in the vendor's database; so does the student's
progress; and the day the institution changes its mind, it takes nothing with it.

OpenLearn goes the other way: content is written in Markdown, stored in a SQLite database that
copies as a single file, exportable on demand and readable by any tool. A wiki is not a product
you rent, it is a memory you keep.

> Nothing you write here depends on our server. That is exactly why we encourage you to host
> your own.

This is what justifies **AGPL-3.0-only** rather than a permissive licence: anyone offering
OpenLearn as a service must release the source of their version — and therefore their fixes — to
the community. A permissive licence would have allowed a company to take the work, add a tracker,
and close the door behind it.

## 2. Restraint is not a constraint, it is a choice

The software fits in one container, talks to SQLite by default, serves pages whose JavaScript
loads as native modules, with no build step and no multi-megabyte framework. A Raspberry Pi 4 is
enough to run an instance for a class. A municipal instance fits on the smallest server an
association host offers.

That restraint has a cost: no "universal" server-side rendering, no exotic full-text search out
of the box, no distributed job queue. We will add them the day a real use case demands them — not
because tutorials are excited about them.

Restraint also applies over time: an installation should not require a painful migration every
six months. Migrations are additive and tested, and a deployment refuses to start if the content
count went down. A project that can die cleanly is a project you dare trust with real data.

## 3. Accessibility is not a module, it is the floor

OpenLearn aimed at **WCAG 2.2 AA** from the first line of interface, not after an audit. That
means: full keyboard navigation, contrast verified in both light and dark themes, explicit form
labels, spoken announcements on state changes, respect for `prefers-reduced-motion`, touch
targets large enough to hit, and a skip link at the top of every page.

The check runs automatically in continuous integration (axe-core on the main screens, plus static
markup checks), and it fails the build. A screen that regresses is not shipped.

Accessibility meets restraint here: an interface that works without elaborate JavaScript, without
animation and without a mouse is also an interface that works on an old laptop, on 3G, and with a
screen reader.

## 4. Do not measure people

There is no advertising network, no social pixel, no third-party analytics script. Server access
logs exist to diagnose a failure and ban a spammer, not to build a profile. An instance may enable
local aggregate counting (page views, no persistent identifier) if its administrator wants it; the
public demo does nothing of the sort that would let it follow you.

That refusal has a price: we will never know precisely how many people use OpenLearn. We would
rather not know than learn it by spying on our visitors.

## What this changes in the product

| Decision | Reason |
| --- | --- |
| Account optional to read a public wiki | Public knowledge must not require signing up. |
| Address confirmed by link, not blocking | Nobody is refused access because an SMTP server is late. |
| One password-reset email every five minutes | A public form must not be usable to harass someone. |
| Temporary bans on spammed forms | Protect the instance without building a reputation system. |
| Email to the author when their publication is approved | Work deserves an answer, even an automatic one. |
| Human moderation of public publications | A filter judges badly; a moderator judges, and signs. |
| No private student grade kept without need | Data you do not keep cannot leak. |
| Dual licensing and trademark terms | The code stays free; the name and the demo stay identifiable. |

## How we work

Contributions go through reviewed pull requests, a signed CLA, and continuous integration that
requires: lint with no errors, unit tests green, browser end-to-end tests, and an accessibility
check. Git history is signed. Structural decisions are written in the repository rather than in a
private thread, so that whoever picks the project up in five years understands the why, not only
the what.

We refuse three things on principle: adding a dependency that collects data, introducing an
inaccessible interface component "for now", and merging a feature whose need we cannot explain in
one sentence.

## And if you disagree

That is what free software means: the philosophy binds only those who share it. The code is
there, the licence lets you modify it, redistribute it, make a different version of it — provided
you release your changes. If you think one of these four convictions is a mistake, open a
discussion: we have changed our minds on technical points before, and we prefer a reasoned
disagreement to polite silence.

<p class="muted small">
This page describes a project, not a legal entity. It has no contractual value; the AGPL-3.0-only
licence does.
</p>
