# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The set of supported languages is declared in four places; they must agree.

A language added to the interface but missing from the server's tuple is not
"half translated": Russian was live in the interface, in the PDF export and in
the AI prompt vocabulary, while ``SUPPORTED_LANGUAGES`` still stopped at seven
codes, so the API rejected a Russian translation of a question and the AI
translation job silently dropped it from its target list.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models import SUPPORTED_LANGUAGES
from app.schemas import LanguageCode

ROOT = Path(__file__).resolve().parents[1]


def _frontend_languages() -> list[str]:
    source = (ROOT / "frontend/js/i18n.js").read_text(encoding="utf-8")
    block = re.search(r"export const LANGUAGES = \[(.*?)\];", source, re.S)
    assert block, "LANGUAGES not found in frontend/js/i18n.js"
    return re.findall(r'code:\s*"([a-z]{2})"', block.group(1))


def _pdf_languages() -> list[str]:
    source = (ROOT / "backend/app/pdf_export.py").read_text(encoding="utf-8")
    block = re.search(r"PDF_LABELS[^=]*=\s*\{(.*?)\n\}", source, re.S)
    assert block, "PDF string table not found"
    return re.findall(r'^\s{4}"([a-z]{2})":', block.group(1), re.M)


def test_every_layer_declares_the_same_languages() -> None:
    front = _frontend_languages()
    pdf = _pdf_languages()
    literal = list(LanguageCode.__args__)

    # The menu opens on French and the server tuple opens on English: same set,
    # different reading order.
    assert sorted(front) == sorted(SUPPORTED_LANGUAGES), (front, SUPPORTED_LANGUAGES)
    assert literal == list(SUPPORTED_LANGUAGES), (literal, SUPPORTED_LANGUAGES)
    assert sorted(pdf) == sorted(SUPPORTED_LANGUAGES), (pdf, SUPPORTED_LANGUAGES)


def test_the_ai_prompt_names_every_declared_language() -> None:
    """A language missing here makes the model answer in English.

    The translation job filters its targets against the server tuple and then
    looks the name up in this table: a code present in one and absent from the
    other is dropped without an error.
    """
    from app.ai import LANGUAGE_NAMES

    assert sorted(LANGUAGE_NAMES) == sorted(SUPPORTED_LANGUAGES), LANGUAGE_NAMES


def test_russian_sits_sixth_everywhere() -> None:
    assert list(SUPPORTED_LANGUAGES).index("ru") == 5
    assert _frontend_languages().index("ru") == 5
