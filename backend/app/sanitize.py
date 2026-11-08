# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""HTML sanitisation for WYSIWYG question text (OWASP A03).

Allowed output is a very small subset of HTML: emphasis, lists, headings and
paragraphs. Links, images, styles, classes and every executable construct are
dropped. The same allowlist is implemented client side in
``frontend/js/sanitize.js`` so the editor and the renderer agree.
"""

from __future__ import annotations

import nh3

ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
    "code",
    "pre",
    "sub",
    "sup",
    "span",
}

MAX_HTML_LENGTH = 20_000


def sanitize_html(raw: str | None) -> str:
    """Return HTML restricted to the allowlist, with no attributes at all."""
    if not raw:
        return ""
    if len(raw) > MAX_HTML_LENGTH:
        raise ValueError("Question text is too long.")
    cleaned = nh3.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes={},  # no attributes: no href, no style, no event handlers
        url_schemes=set(),
        link_rel=None,
        strip_comments=True,
    )
    # nh3 keeps the text of disallowed tags; that is fine, but make sure no
    # link survived as text-less markup.
    return cleaned.strip()


def html_to_text(raw: str | None) -> str:
    """Plain text projection used for validation and search."""
    if not raw:
        return ""
    import re

    text = re.sub(r"<[^>]+>", " ", raw)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return " ".join(text.split())


def sanitize_plain(raw: str | None, *, max_length: int = 500) -> str:
    """Collapse a plain-text field (option text, title, nickname)."""
    if raw is None:
        return ""
    text = " ".join(str(raw).replace("\x00", "").split())
    if len(text) > max_length:
        raise ValueError(f"Value is longer than {max_length} characters.")
    return text
