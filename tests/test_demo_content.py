# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The demo catalogue is data: it must stay valid, and it must stay rich enough
to look like a real platform rather than a placeholder.
"""

from __future__ import annotations

import json

from app.demo.seed import content_files, validate_content


def test_every_demo_file_parses_and_validates():
    problems = validate_content()
    assert problems == [], problems[:10]


def test_the_catalogue_covers_several_formats_and_languages():
    inventory: dict[str, int] = {}
    languages: set[str] = set()
    for path in content_files():
        document = json.loads(path.read_text(encoding="utf-8"))
        kind = document.get("kind") or path.stem
        items = document.get("items") or []
        inventory[kind] = inventory.get(kind, 0) + len(items)
        for item in items:
            code = item.get("language") or item.get("lang")
            if code:
                languages.add(code)

    # The demo instance is the shop window: it has to look like a platform that
    # has been used for a while, not like a fixture.
    assert inventory.get("wikis", 0) >= 30, inventory
    assert inventory.get("quizzes", 0) >= 100, inventory
    assert inventory.get("decks", 0) >= 10, inventory
    assert inventory.get("adventures", 0) >= 3, inventory
    assert {"en", "fr"} <= languages, languages
    assert len(languages) >= 4, languages


def test_a_wiki_has_pages_with_a_title_and_a_body():
    for path in content_files():
        document = json.loads(path.read_text(encoding="utf-8"))
        if (document.get("kind") or path.stem) != "wikis":
            continue
        for wiki in document["items"]:
            assert wiki["pages"], wiki["slug"]
            for page in wiki["pages"]:
                assert page["title"].strip()
                body = page.get("markdown") or page.get("content_md") or ""
                assert body.strip(), f"{wiki['slug']}/{page['slug']} is empty"
