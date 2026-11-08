# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Paragraph reflow: the browser wraps, the source keeps only the structure."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.wiki import reflow_markdown

DEMO = Path(__file__).resolve().parents[1] / "demo" / "content"
BLOCK = re.compile(r"^\s{0,3}(?:#{1,6}\s|[-*+]\s|\d{1,3}[.)]\s|>|\||```|---|\*\*\*|___)")


def test_a_paragraph_wrapped_at_seventy_columns_becomes_one_line():
    wrapped = (
        "A wiki is written by several people at once.\n"
        "Each edit keeps the previous version, so a mistake\n"
        "never costs the paragraph it replaced."
    )
    assert reflow_markdown(wrapped) == (
        "A wiki is written by several people at once. "
        "Each edit keeps the previous version, so a mistake "
        "never costs the paragraph it replaced."
    )


def test_paragraph_breaks_survive():
    text = "First paragraph\nover two lines.\n\nSecond paragraph."
    assert reflow_markdown(text) == "First paragraph over two lines.\n\nSecond paragraph."


def test_headings_lists_quotes_and_tables_keep_their_own_lines():
    text = (
        "## Origins\n"
        "- first item\n"
        "- second item\n"
        "> quoted line\n"
        "| a | b |\n"
        "| - | - |"
    )
    assert reflow_markdown(text) == text


def test_a_code_fence_is_never_touched():
    text = "```python\ndef f():\n    return 1\n```"
    assert reflow_markdown(text) == text


def test_an_indented_continuation_keeps_its_layout():
    text = "- item\n    continued on purpose"
    assert reflow_markdown(text) == text


def test_reflow_is_idempotent():
    text = "One line\nbroken in two.\n\nAnother\nparagraph here."
    once = reflow_markdown(text)
    assert reflow_markdown(once) == once


def test_carriage_returns_are_normalised():
    assert reflow_markdown("a\r\nb\r\n\r\nc") == "a b\n\nc"


def _hard_wrapped_prose(markdown: str) -> int:
    """Single line breaks that sit inside prose, not between block elements.

    A fenced block is code the author laid out on purpose: its lines are not
    prose and never count, however short they are.
    """
    count = 0
    in_fence = False
    lines = (markdown or "").split("\n")
    for index, line in enumerate(lines[:-1]):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        following = lines[index + 1]
        if not line.strip() or not following.strip() or following.strip().startswith("```"):
            continue
        if line.startswith(("    ", "\t")):
            continue
        if not BLOCK.match(line) and not BLOCK.match(following):
            count += 1
    return count


def test_the_demo_catalogue_carries_no_hard_wrapped_prose():
    offenders = []
    for path in sorted(DEMO.glob("wikis*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for wiki in document.get("items", []):
            for page in wiki.get("pages", []):
                found = _hard_wrapped_prose(page.get("markdown", ""))
                if found:
                    offenders.append(f"{wiki.get('slug')}/{page.get('slug')}: {found}")
    assert offenders == [], offenders
