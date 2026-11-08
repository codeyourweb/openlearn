---
layout: doc
title: Revision — cards, decks, spaced repetition
description: >-
  Build a card deck in OpenLearn from a wiki page, a quiz or by hand; revise with spaced
  repetition; print a card; publish a deck.
permalink: /guide/spaced-repetition/
---

<p class="doc-eyebrow">Guide · Cards and spaced repetition</p>

# Revision

A quiz records what you know at a given moment. A revision card does the opposite: it comes back
at the right time so that knowledge stays. OpenLearn connects the two — any wrong answer can
become a card.

## What a card deck is

A **deck** holds **cards**, each with a front (the question) and a back (the answer), optionally an
image on the back. A deck can belong to a wiki, which makes it visible from that space's pages.

## Creating a deck

**New deck** (`/cards`) offers three sources:

1. **From a wiki page** — the page text is split into cards (headings and definitions, lists,
   tables). Read them over: automatic splitting produces noise, it does not understand meaning.
2. **From a quiz** — each question becomes a card. This is the most reliable route: the question
   already has a written answer.
3. **By hand** — you write front and back, in the card format you want.

## Revising

**Revise** (`/cards/<id>/study`) opens the session. For each card:

1. the front is shown; you answer mentally (or out loud);
2. you turn the card over;
3. you say whether it was **easy**, **right** or **to review**.

Those three answers decide the interval before the next showing: a card you know returns in
several days, a card you missed returns within the session or the next day. The algorithm is
deliberately simple — a stripped-down SM-2 — because an opaque scheduler teaches nothing to the
person using it.

<div class="note">
<p><strong>What honesty changes.</strong> Answering "easy" on a card you half-forgot lengthens
the interval and will cost you time three weeks from now. The machine cannot check: the quality of
revision depends entirely on how truthful the answer is.</p>
</div>

## Publishing a deck

A deck is private by default. **Publish** makes it visible in the **Published** tab; **Make
private** removes it. Unlike wikis and quizzes, publishing a deck does not go through moderation:
a card is a working tool, not an editorial publication.

## Printing

**Print the card** produces a paper version of the deck, front and back, to be cut out. It is
still the fastest way to revise on a train.

## Seeing your progress

From `/cards`, the **My decks** tab shows the number of cards and the state of each (new, in
progress, known). A deck whose cards are all "known" remains revisable: forgetting is normal, and
the interval will lengthen again.
