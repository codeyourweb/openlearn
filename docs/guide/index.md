---
layout: doc
title: User guide — getting to grips with OpenLearn
description: >-
  The OpenLearn user guide, feature by feature: writing in the wiki, creating and hosting
  quizzes, revising with cards, managing your account, moderating publications.
permalink: /guide/
---

<p class="doc-eyebrow">User guide</p>

# Getting to grips with OpenLearn

This guide describes the software as it is today, screen by screen. It assumes no technical
knowledge: if you can use a browser, you can write a wiki page and run a quiz.

Every page follows the same logic: **what it is for**, **where to find it**, **how to use it**,
and **the ordinary pitfalls**. The paths given (`/wiki/new`, `/quizzes/new`…) are those of the
demonstration instance; they are identical on any instance of the software.

## Where to start

<ol class="steps">
  <li><strong>Create an account</strong> on the instance, then open the confirmation link you
  receive by email. Until the address is confirmed the application works normally, but shows a
  reminder banner.</li>
  <li><strong>Open the dashboard</strong> (<code>/dashboard</code>): it lists your wikis, your
  quizzes and your cards, and every new creation starts from there.</li>
  <li><strong>Write a first page</strong> in a wiki space, or <strong>create a quiz</strong> of
  five questions to try the live mode.</li>
  <li><strong>Request publication</strong>: your content becomes public once a moderator has
  approved it, and you then receive an email.</li>
</ol>

## The three objects of the software

<div class="grid">
  <div class="card">
    <h3>The wiki</h3>
    <p>A space of Markdown pages, versioned, structured and publishable. This is where knowledge
    gets written. <a href="{{ '/guide/wiki/' | relative_url }}">Wiki guide</a></p>
  </div>
  <div class="card">
    <h3>The quiz</h3>
    <p>A series of multiple-choice questions, playable alone, with friends, or hosted in a room.
    <a href="{{ '/guide/quizzes/' | relative_url }}">Quiz guide</a></p>
  </div>
  <div class="card">
    <h3>The revision card</h3>
    <p>The quiz's memory: a question, an answer, and an interval that grows as you get it right.
    <a href="{{ '/guide/spaced-repetition/' | relative_url }}">Revision guide</a></p>
  </div>
</div>

## Depending on who you are

| You are | Start with | Then |
| --- | --- | --- |
| Visitor | Reading public wikis, playing public quizzes | Create an account to write |
| Author | [Getting started]({{ '/guide/getting-started/' | relative_url }}) | [Write in the wiki]({{ '/guide/wiki/' | relative_url }}), [create a quiz]({{ '/guide/quizzes/' | relative_url }}) |
| Moderator | [Moderating]({{ '/guide/moderation/' | relative_url }}) | Approving publications, handling reports |
| Administrator | [Administering]({{ '/guide/moderation/' | relative_url }}) | Settings, accounts, mail, AI, SSO, backups |
| Developer | [API and MCP]({{ '/guide/api-mcp/' | relative_url }}) | Automating, connecting an agent |
| Operator | [Self-hosting]({{ '/self-hosting/' | relative_url }}) | Backup, restore, upgrades |

## What is not in this guide

Installation, backup and upgrades belong to the operator: they are described in
[Self-hosting OpenLearn]({{ '/self-hosting/' | relative_url }}). The complete reference of HTTP
endpoints is built into the software, at `/docs` on your instance, and summarised in
[API and MCP]({{ '/guide/api-mcp/' | relative_url }}).

<div class="note">
<p><strong>One instance, one behaviour.</strong> An administrator may disable registration, the
AI assistant, single sign-on or mail delivery. If a screen described here does not exist on your
instance, the feature is probably switched off server-side — the page usually says so.</p>
</div>
