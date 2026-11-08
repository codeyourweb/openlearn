# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Revision cards: turning existing content into cards, and printing them.

The point of the feature is that nobody fills a deck by hand. Two generators
sit here:

* ``pairs_from_markdown`` reads a wiki page and pairs each heading with the
  paragraph underneath it — that covers "term/definition" pages, but also a
  well-written lesson, where the headings are the questions a learner would ask.
* ``pairs_from_quiz`` reads a questionnaire and pairs each question with its
  correct answer(s), which is exactly what a learner needs to revise.

Both stay deliberately dumb: no model, no AI call, no network. A teacher who
reads the result must recognise their own words.
"""

from __future__ import annotations

import html
import re

_MAX_FRONT = 400
_MAX_BACK = 3000

# Inline markers the wiki understands and that would clutter a card.
_MARKUP = re.compile(
    r"\{/?(?:u|c(?::[^}]*)?|a:[^}]*|s:[^}]*|f:[^}]*|width=\d{1,4}%?|quiz:\d+|adventure:\d+)\}"
)
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|\{\{image:[^}]*\}\}")
_TAGS = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
# Only the explicit bold form counts as a definition. Guessing on "Profil : …"
# produced junk cards out of ordinary sentences, and a learner who opens a card
# titled "Profil" learns nothing.
_DEFINITION = re.compile(r"^\*\*([^*]{2,120})\*\*\s*[:—–]\s*(.+)$")


def plain(text: str) -> str:
    """Strip the wiki markdown a card does not need, keep the words."""
    value = _IMAGE.sub("", text or "")
    value = _WIKILINK.sub(lambda found: found.group(2) or found.group(1), value)
    value = _MARKUP.sub("", value)
    value = _TAGS.sub("", value)
    value = _INLINE_CODE.sub(r"\1", value)
    value = _BOLD.sub(r"\1", value)
    value = _ITALIC.sub(r"\1", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _trim(text: str, limit: int) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    cut = value[:limit]
    # Cut on a sentence boundary when one is close enough.
    for mark in (". ", "! ", "? ", "\n"):
        index = cut.rfind(mark)
        if index > limit * 0.6:
            return cut[: index + len(mark)].strip() + " […]"
    return cut.strip() + " […]"


def pairs_from_markdown(markdown: str) -> list[tuple[str, str]]:
    """Pair each heading (or bolded lead-in) with what follows it."""
    lines = (markdown or "").splitlines()
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def keep(front: str, back: str) -> None:
        front, back = plain(front), _trim(plain(back), _MAX_BACK)
        if not front or not back or len(front) > _MAX_FRONT:
            return
        key = front.casefold()
        if key in seen:
            return
        seen.add(key)
        pairs.append((front, back))

    index = 0
    while index < len(lines):
        heading = _HEADING.match(lines[index].strip())
        if heading:
            front = heading.group(2)
            body: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                stripped = lines[cursor].strip()
                if _HEADING.match(stripped):
                    break
                if stripped.startswith("```"):
                    # Skip a code fence: it belongs to the page, not to a card.
                    cursor += 1
                    while cursor < len(lines) and not lines[cursor].strip().startswith("```"):
                        cursor += 1
                    cursor += 1
                    continue
                if stripped:
                    body.append(stripped)
                elif body:
                    break
                cursor += 1
            if body:
                keep(front, " ".join(body))
            index = cursor
            continue
        index += 1

    # Second pass: "**Term** : definition" lines, the way many lessons are typed.
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|") or line.startswith(">"):
            continue
        found = _DEFINITION.match(line)
        if not found:
            continue
        keep(found.group(1), found.group(2))
    return pairs


def _question_text(text_html: str) -> str:
    return plain(re.sub(r"<br\s*/?>", " ", text_html or ""))


def pairs_from_questionnaire(quiz, questions) -> list[tuple[str, str, str | None]]:
    """Pair each question with its answer key: (front, back, image_path)."""
    cards: list[tuple[str, str, str | None]] = []
    for question in questions:
        if getattr(quiz, "mode", "qcm") == "poll":
            continue  # a poll has no answer to revise
        correct = [option for option in question.options if getattr(option, "is_correct", False)]
        if not correct:
            continue
        front = _question_text(question.text_html)
        if not front:
            continue
        back = "\n".join(f"• {plain(option.text)}" for option in correct)
        cards.append((_trim(front, _MAX_FRONT), back, getattr(question, "image_path", None)))
    return cards
