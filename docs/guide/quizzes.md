---
layout: doc
title: Quizzes — create, play solo, host a live game
description: >-
  Create a quiz in OpenLearn, write questions and corrections, set the attempt rule, publish,
  play solo, host a live game with a PIN, read the statistics.
permalink: /guide/quizzes/
---

<p class="doc-eyebrow">Guide · Create, play, host</p>

# Quizzes

A quiz is a series of multiple-choice questions. It can be played alone for practice, or live,
hosted by a presenter, with a scoreboard building up question after question.

## Creating a quiz

**New quiz** (`/quizzes/new`) offers two methods:

- **Manual**: you write the questions one by one. This is the normal route for content you know.
- **Assisted**: if the instance has a model provider, a topic description produces a first draft
  of the questions. Read it: a model proposes, it does not verify.

The editor (`/quizzes/new/<mode>/<variant>` then `/quizzes/<id>/edit`) has two tabs: **Preview**
and **Questions**.

## Writing questions

For each question:

1. **Wording** — a sentence, not a fragment.
2. **Answers** — at least two. Tick the right one or ones; a question with several answers shows
   **Multiple answers** on the player's side.
3. **Explanation** — shown after the answer. This is the teaching part: without it a quiz does not
   teach, it grades.
4. **Weight** (optional) — one question can be worth more than another.

<div class="note">
<p><strong>What makes a good question.</strong> One idea per question, plausible wrong answers,
no "all of the above", and an explanation that holds even if the player guessed right. The
interface tests check the form, not the relevance: that part is your job.</p>
</div>

## Setting how it runs

| Setting | Effect |
| --- | --- |
| **Attempts per candidate** | *Unlimited (practice)* or *Single attempt (assessment)* |
| **Confidence** | The player states how sure they are; a confident mistake weighs more than a hesitant one |
| **No points on error** | Removes partial credit, for a strict marking scheme |
| **Secondary languages** | Translations of the quiz, offered to the player |

A quiz in **assessment** mode (single attempt) will not open twice for the same account: the
second attempt is refused, including in a live session.

## Publishing

Like a wiki, a quiz starts as a draft and requests its **publication**. A moderator reads it; on
approval it becomes public, appears in the `/quizzes` catalogue, and you receive an email. A
refusal leaves the quiz private, with the reason.

Every save creates a **version** (**Versions** tab) that can be restored: editing a quiz that has
already been played does not rewrite past results, which stay attached to the version that was
played. A version older than the current one is marked **outdated**.

## Playing solo

From the quiz page, **Play** starts a classic game: questions in order, correction at the end (or
as you go, depending on the setting), then a result screen with per-question detail.
**Adventures** (`/adventures/new`) builds a path chaining several quizzes, with progression.

## Hosting a live game

1. On the quiz page, **Host** creates a session and shows a **PIN** and a link (`/host/<code>` for
   the host, `/play/<code>` for players, or `/join/<token>` by direct link).
2. Players join with the PIN and choose a nickname.
3. The host starts the first question; the timer runs; answers arrive live.
4. The scoreboard shows between questions, then the podium at the end.

**You can play too**: the host may take part from their own screen. Note that a host who plays
**no longer gets** the presenter exemption from the attempt limit: the rule follows the candidate,
not the game mode.

## Reading the statistics

The **Statistics** tab gives, for a published quiz: participants, completed sessions, average
score, average time, correct answers, and the **success rate per question**. That is where you
spot the badly worded question — the one everyone gets wrong for the wrong reasons.

**Export** produces a CSV of results, ready for a spreadsheet.

## Import and export

A quiz can be exported as JSON and imported elsewhere: handy to prepare content offline, keep it
in Git, or duplicate it from one instance to another.

## Hosting tips

- Announce the confidence rule before the first question, otherwise players discover it while
  playing.
- Let the question's explanation stay on screen: it is the only moment it gets read.
- For a graded assessment, use a live session **without** the host playing: the attempt limit then
  applies to every candidate in the same way.
