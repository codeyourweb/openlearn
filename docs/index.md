---
title: OpenLearn — a free wiki and quiz platform for learning, without tracking
description: >-
  OpenLearn brings a collaborative wiki, a quiz engine and spaced repetition into one free,
  self-hostable application, WCAG 2.2 AA accessible and translated into twelve languages.
permalink: /
---

<section class="hero">
  <h1>Learn together, without giving up freedom or accessibility.</h1>
  <p class="lead">
    OpenLearn is a self-hosted learning platform: a wiki to write knowledge down, a quiz engine
    to check it, and revision cards to keep it. No advertising tracker, no dependency on a
    platform — just a server, a browser, and the people using the software.
  </p>
  <div class="hero-actions">
    <a class="btn btn-primary" href="{{ site.demo_url }}">Try the live demo</a>
    <a class="btn" href="{{ '/guide/' | relative_url }}">Read the user guide</a>
    <a class="btn" href="https://github.com/{{ site.repository }}">Source code</a>
  </div>
  <p class="muted small" style="margin-top:1.25rem">
    AGPL-3.0-only · FastAPI + SQLite · Docker · WCAG 2.2 AA · 12 languages
  </p>
</section>

## What the software does

OpenLearn puts together three gestures that belong together: writing down what you know, having
it recited back, and coming back to it at the right moment.

<div class="grid">
  <div class="card">
    <h3>A wiki that expects cross-references</h3>
    <p>
      Markdown pages, versions, a page tree, a link graph, citations and a bibliography. A page
      always knows who changed it and what changed.
    </p>
  </div>
  <div class="card">
    <h3>A complete quiz engine</h3>
    <p>
      Single and multiple choice, confidence ratings, a live mode hosted by a presenter, solo
      games, detailed assessment and result export.
    </p>
  </div>
  <div class="card">
    <h3>Spaced repetition</h3>
    <p>
      Any wrong answer can become a card, served again after an interval that grows as it comes
      back right. It is the oldest and most solid pedagogy there is: repetition at increasing
      intervals.
    </p>
  </div>
  <div class="card">
    <h3>Room for every team</h3>
    <p>
      Accounts, avatars, roles (author, moderator, administrator), API keys and MCP access give
      an external tool or agent what it needs to read and create content without the interface.
    </p>
  </div>
  <div class="card">
    <h3>A server, not a subscription</h3>
    <p>
      One Docker image, SQLite by default, backup and restore in a single command. A modest
      server is enough for a whole class.
    </p>
  </div>
  <div class="card">
    <h3>Twelve languages, Arabic right to left</h3>
    <p>
      French, English, German, Spanish, Italian, Russian, Chinese, Japanese, Portuguese, Hindi,
      Bengali and Arabic — every screen is translated, not only the landing page.
    </p>
  </div>
</div>

## The question that decided the architecture

> Most online learning platforms charge for access to knowledge, track every click, and keep
> content locked in. We wanted the opposite: software that an association, a school, a lab or a
> family can put on its own server, leave running for ten years, and walk away from without
> losing a line.

That choice has technical consequences, accepted one by one. They are described in
[the philosophy behind the project]({{ '/philosophy/' | relative_url }}): why AGPL rather than
MIT, why an optional account, why accessibility is not an optional layer, and how the project
refuses to measure people.

## Documentation

The user guide describes every feature screen by screen, with the real paths of the
application:

<div class="grid">
  <div class="card">
    <h3><a href="{{ '/guide/getting-started/' | relative_url }}">Getting started</a></h3>
    <p>Account, email confirmation, sign-in, navigation, languages, theme.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/wiki/' | relative_url }}">The wiki</a></h3>
    <p>Write in Markdown, keep versions, restore one, cross-link pages, publish.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/quizzes/' | relative_url }}">Quizzes</a></h3>
    <p>Create, set the attempt rule, play solo, host a live game, read the statistics.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/spaced-repetition/' | relative_url }}">Revision</a></h3>
    <p>Cards, card decks, spaced repetition, printing.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/moderation/' | relative_url }}">Moderating and administering</a></h3>
    <p>Publication queue, notes to authors, accounts, mail, AI, SSO, temporary bans.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/api-mcp/' | relative_url }}">API and MCP</a></h3>
    <p>API keys, the OpenAPI reference, connecting an agent.</p>
  </div>
</div>

## Who it is for

- **A teaching team** that wants a course space without depending on a vendor.
- **An outreach association** that writes explainers and wants them revised.
- **A quiz club** that needs a live mode and a scoreboard.
- **A public body** bound by accessibility and data-sovereignty requirements.
- **A developer** looking for a readable example of a FastAPI API, a versioned wiki and
  accessible front-end components.

## Project status

The software is used in public: [openlearnproject.org]({{ site.demo_url }}) is an open
demonstration instance, filled with a catalogue of sample content. The code is complete, tested
(over 450 back-end tests plus a browser end-to-end suite), and published under AGPL-3.0-only with
a CLA for contributions.

<p class="muted small">
OpenLearn is written by <a href="{{ site.author.url }}">{{ site.author.name }}</a> and released
under AGPL-3.0-only. The OpenLearn name and the demonstration instance are not granted with the
code: see the trademark terms in the repository.
</p>
