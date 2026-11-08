# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The wiki URL is a contract between the catalogue, the router and the server.

A wiki lives at ``/wiki/<id>/<wiki slug>``. The catalogue used to build that
last segment from the *title*, which gave ``/wiki/34/climate-and-resources``
while the wiki's own slug was ``environment``; the reader then resolved no page
and told the visitor the wiki was empty, although it had four pages.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "js"

# `/wiki/${wiki.id}/${titleSlug(wiki.title)}` and its variants.
TITLE_SLUG_IN_WIKI_URL = re.compile(r"/wiki/\$\{[^}]*\}/\$\{\s*titleSlug\(")


def test_no_page_builds_a_wiki_url_from_its_title():
    offenders = []
    for path in sorted(FRONTEND.rglob("*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if TITLE_SLUG_IN_WIKI_URL.search(line):
                offenders.append(f"{path.relative_to(FRONTEND)}:{number}: {line.strip()[:90]}")
    assert offenders == [], "\n".join(offenders)


def test_every_wiki_link_goes_through_the_canonical_helper():
    source = (FRONTEND / "pages" / "wiki.js").read_text(encoding="utf-8")
    assert "function wikiPath(wiki)" in source, "wiki.js must keep one canonical builder"
    # Catalogue title, catalogue button, sidebar title.
    assert len(re.findall(r'href="\$\{wikiPath\(wiki\)\}"', source)) >= 3


def test_the_canonical_helper_uses_the_wiki_slug():
    source = (FRONTEND / "pages" / "wiki.js").read_text(encoding="utf-8")
    match = re.search(r"function wikiPath\(wiki\) \{(.*?)\n\}", source, re.S)
    assert match, "wikiPath is missing"
    body = match.group(1)
    assert "wiki.slug" in body, body
    assert "titleSlug(wiki.title" in body, "the helper may only fall back to the title"


def test_the_server_indexes_the_same_url():
    seo = (ROOT / "backend" / "app" / "seo.py").read_text(encoding="utf-8")
    assert 'canonical = f"/wiki/{wiki.id}/{wiki_slug}"' in seo


def test_the_reader_still_falls_back_to_the_first_page():
    """An unknown slug on the canonical route must not look like an empty wiki."""
    source = (FRONTEND / "pages" / "wiki.js").read_text(encoding="utf-8")
    assert 'location.pathname.includes("/p/")' in source
    assert "isPageLink ? null : wiki.pages[0]" in source
