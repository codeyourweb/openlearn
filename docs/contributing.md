---
title: Contributing to OpenLearn — code, content, translations, accessibility
description: >-
  How to contribute to the OpenLearn project: report a defect, propose a translation, write demo
  content, send a pull request, sign the CLA.
permalink: /contributing/
---

# Contributing

<p class="muted small">The project accepts contributions of code, translations, content and
reports. Here is how, from the most useful to the most involved.</p>

## Reporting a defect

A well-written issue is worth more than a patch written without context. Say:

- what you were doing, what you expected, what happened;
- the page or endpoint concerned;
- the version (footer of the instance) and the browser;
- for a visual defect, a screenshot; for an accessibility defect, the assistive technology you
  use.

Accessibility defects carry the `accessibility` label and are treated as blocking.

## Translating

The twelve languages live in `frontend/js/locales/`. A translation contribution must:

- cover **every** key (a test checks it, continuous integration fails otherwise);
- match the tone of the product: short sentences, no jargon, no needless anglicisms;
- keep variables (`{n}`, `{total}`) intact;
- for Arabic, never force text direction inside the string: the layout handles it.

## Writing content

There is a demonstration catalogue (`backend/app/demo_content.py` and the associated data). A
content contribution must be **true**, sourced when the subject calls for it, and short: a demo
page exists to show the product, not to teach a field.

## Proposing code

1. Open an issue to discuss the intent, especially for a new feature.
2. Fork the repository and create a branch with an explicit name.
3. Write the code **and** the tests; style follows `pyproject.toml` (ruff) for Python.
4. Check locally: `pytest -m "not e2e"`, `ruff check backend tests`, `shellcheck`.
5. Open a pull request; continuous integration requires lint, unit tests, end-to-end tests and
   the accessibility check.
6. Sign the CLA (see `CLA.md`) — it lets the project distribute your contribution under
   AGPL-3.0-only without taking your copyright away.

## What we turn down

- A dependency that collects data or loads a third-party script.
- An inaccessible interface component "for now".
- A feature whose need cannot be stated in one sentence.
- A wholesale rewrite without prior discussion: the code has a history, and it matters.

## Trademark terms

The code is free; the **OpenLearn** name and the demonstration instance are not granted with the
licence. A derived deployment must use another name and must not present itself as the official
instance. See `TRADEMARK.md` in the repository.

## Contact

`developper@openlearnproject.org` for anything that cannot go through GitHub (personal data,
licensing question, sensitive report).
