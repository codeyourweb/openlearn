# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Every interface string exists in every language, and no language invents one.

A missing key does not crash the interface: `t()` falls back to the key itself,
so the screen shows `account.tab_wikis` to a German reader instead of a label.
That is the failure this test catches — in both directions, because a key that
exists only in a translation means the code looks for a string nobody wrote.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
LOCALES = FRONTEND / "js" / "locales"
I18N = FRONTEND / "js" / "i18n.js"
LANGUAGES = ("fr", "it", "es", "de", "ru", "zh", "ja")
LINE = re.compile(r'^\s*"([^"]+)":\s*"(.*)",\s*$')


def _keys(path: Path, marker: str) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.startswith(f"export const {marker} = {{")
    )
    found: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("};"):
            break
        match = LINE.match(line)
        if match:
            found.append(match.group(1))
    return found


def test_english_is_the_reference_dictionary():
    english = _keys(I18N, "en")
    assert len(english) > 1000
    assert len(set(english)) == len(english), "duplicate key in the English dictionary"


def test_every_language_carries_every_english_key():
    english = _keys(I18N, "en")
    problems = {}
    for code in LANGUAGES:
        keys = set(_keys(LOCALES / f"{code}.js", code))
        missing = [key for key in english if key not in keys]
        if missing:
            problems[code] = missing[:5]
    assert not problems, problems


def test_no_language_carries_a_key_english_does_not_have():
    english = set(_keys(I18N, "en"))
    problems = {}
    for code in LANGUAGES:
        extra = [key for key in _keys(LOCALES / f"{code}.js", code) if key not in english]
        if extra:
            problems[code] = extra[:5]
    assert not problems, problems


def test_translations_keep_their_placeholders():
    """A translator dropping `{n}` silently breaks the sentence at runtime."""
    english = {}
    lines = I18N.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("export const en = {"))
    for line in lines[start + 1 :]:
        if line.startswith("};"):
            break
        match = LINE.match(line)
        if match:
            english[match.group(1)] = match.group(2)

    problems = {}
    for code in LANGUAGES:
        source = (LOCALES / f"{code}.js").read_text(encoding="utf-8")
        for key, value in english.items():
            wanted = set(re.findall(r"\{[a-z0-9_]+\}", value))
            if not wanted:
                continue
            translated = re.search(rf'"{re.escape(key)}":\s*"(.*)",', source)
            if not translated:
                continue
            missing = wanted - set(re.findall(r"\{[a-z0-9_]+\}", translated.group(1)))
            if missing:
                problems.setdefault(code, []).append((key, sorted(missing)))
    assert not problems, problems


def _used_keys() -> set[str]:
    """Keys the interface actually asks for, gathered from the sources."""
    used: set[str] = set()
    for path in [*FRONTEND.rglob("*.js"), *FRONTEND.rglob("*.html")]:
        text = path.read_text(encoding="utf-8")
        used |= {m.group(1) for m in re.finditer(r'\bt\(\s*["\']([\w.\-]+)["\']', text)}
        used |= {m.group(1) for m in re.finditer(r'data-i18n="([\w.\-]+)"', text)}
    return used


def test_every_key_the_interface_asks_for_exists():
    """A key nobody wrote does not crash: it shows up as `action.open` on screen.

    That is how a button ends up labelled with its own identifier in one view,
    and the dictionaries still look complete because the key is missing from all
    of them. The dictionary has to be checked against the code, not against
    itself.
    """
    english = set(_keys(I18N, "en"))
    missing = sorted(_used_keys() - english)
    assert not missing, missing


def test_every_language_in_the_picker_has_its_own_flag():
    """A language without a flag used to borrow the English one.

    Russian was missing from the table, so the picker showed the Union Jack next
    to "Русский". A missing entry now renders a blank chip, and this test keeps
    the table in step with the languages the interface offers.
    """
    flags_source = (FRONTEND / "js" / "flags.js").read_text(encoding="utf-8")
    table = flags_source.split("const FLAGS = {", 1)[1].split("\n};", 1)[0]
    drawn = set(re.findall(r"^\s{2}([a-z]{2}):\s*`", table, re.M))

    i18n_source = I18N.read_text(encoding="utf-8")
    offered = set(re.findall(r'\{ code: "([a-z]{2})"', i18n_source.split("export const LANGUAGES = [", 1)[1]))

    assert offered, "no language found in LANGUAGES"
    assert offered - drawn == set(), sorted(offered - drawn)
    # Two languages sharing one flag is the same bug wearing a different hat.
    bodies: dict[str, str] = {}
    for code in sorted(drawn):
        block = re.search(rf"^\s{{2}}{code}:\s*`(.*?)`,?$", table, re.M | re.S)
        bodies.setdefault(block.group(1).strip() if block else "", []).append(code)
    duplicated = {body: codes for body, codes in bodies.items() if len(codes) > 1}
    assert not duplicated, duplicated
