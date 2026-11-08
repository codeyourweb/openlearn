# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Wiki domain helpers: slugs, markdown rendering, links, diffs and exports.

Markdown is the canonical storage format. Authors may type markdown directly or
use the WYSIWYG surface of the editor, which converts back to markdown before it
saves: keeping a single source of truth is what makes versioning, diffs and the
markdown export trustworthy.

Rendering happens server side so every reader sees the same HTML, and the result
is sanitised by an allowlist tuned for documents (links, images, tables,
footnotes) rather than for the question fields of a quiz.
"""

from __future__ import annotations

import difflib
import io
import re
import unicodedata
import zipfile
from urllib.parse import quote, urlsplit

import nh3
from markdown_it import MarkdownIt

MAX_PAGE_MD = 400_000
MAX_TITLE = 200


# --------------------------------------------------------------------------- #
# Reflow                                                                       #
# --------------------------------------------------------------------------- #

# A line that starts a new block: heading, list item, quote, table row, fence,
# rule, image or wikilink on its own line. Everything else is prose that may have
# been wrapped at some fixed width by an editor, a language model or an import.
_BLOCK_START = re.compile(
    r"^\s{0,3}(?:#{1,6}\s|[-*+]\s|\d{1,3}[.)]\s|>|\||```|~~~|---|\*\*\*|___|!\[|\[\[)"
)
_FENCE = re.compile(r"^\s*(?:```|~~~)")


def reflow_markdown(markdown: str) -> str:
    """Join the wrapped lines of a paragraph, keep the paragraph breaks.

    Text that arrives wrapped at 70 or 80 columns carries the wrapping forever:
    it shows up in the editor and in every diff, and it re-wraps badly on a
    phone. The reader's browser is what wraps text, so the source should only
    carry the structure an author meant — blank lines between paragraphs, list
    items on their own lines, code as it was written.

    Idempotent: running it twice changes nothing, which is what lets it sit on
    the save path as well as on the import path.
    """
    lines = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        if buffer:
            out.append(" ".join(buffer))
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        if _FENCE.match(line):
            flush()
            in_fence = not in_fence
            out.append(line.rstrip())
            continue
        if in_fence:
            out.append(line.rstrip())
            continue
        if not stripped:
            flush()
            out.append("")
            continue
        # An indented line is a code block or a continuation of a list item as
        # the author laid it out; leave it exactly as it is.
        if line.startswith(("    ", "\t")):
            flush()
            out.append(line.rstrip())
            continue
        if _BLOCK_START.match(line):
            flush()
            out.append(line.rstrip())
            continue
        buffer.append(stripped)
    flush()

    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text)

# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(raw: str, *, fallback: str = "page") -> str:
    """ASCII slug: accents folded, everything else collapsed to a dash."""
    text = unicodedata.normalize("NFKD", raw or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = _SLUG_STRIP.sub("-", text).strip("-")
    return (text or fallback)[:120]


def unique_slug(base: str, taken: set[str]) -> str:
    """Append -2, -3... until the slug is free inside one wiki."""
    if base not in taken:
        return base
    index = 2
    while f"{base}-{index}" in taken:
        index += 1
    return f"{base}-{index}"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def _build_markdown() -> MarkdownIt:
    from mdit_py_plugins.footnote import footnote_plugin

    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])
    md.use(footnote_plugin)
    return md


_MD = _build_markdown()

WIKI_ALLOWED_TAGS = {
    "p", "br", "hr", "strong", "b", "em", "i", "u", "s", "del", "mark",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "code", "pre", "sub", "sup", "span", "div",
    "a", "img", "figure", "figcaption",
    "table", "thead", "tbody", "tr", "th", "td",
    "section", "input",
}

WIKI_ALLOWED_ATTRIBUTES = {
    # `rel` is deliberately absent: nh3 owns it through `link_rel`, and refuses
    # to run when both are given.
    "a": {"href", "title", "class", "target", "data-missing", "id"},
    "img": {"src", "alt", "title", "width", "height", "loading", "class"},
    "span": {"class", "id", "data-line"},
    "div": {"class", "id"},
    "section": {"class"},
    "code": {"class"},
    "th": {"style", "colspan", "rowspan"},
    "td": {"style", "colspan", "rowspan"},
    # Markdown-it renders task list checkboxes as inputs; they are inert.
    "input": {"type", "checked", "disabled"},
    "li": {"class", "id"},
    "h1": {"id"}, "h2": {"id"}, "h3": {"id"}, "h4": {"id"}, "h5": {"id"}, "h6": {"id"},
    "sup": {"class", "id"},
}

_WIKILINK = re.compile(r"\[\[([^\]\|]{1,180})(?:\|([^\]]{1,180}))?\]\]")
# Citation markers produced by the AI pipeline: [1], [2] ...
_CITATION = re.compile(r"\[(\d{1,2})\]")

# Inline decoration set from the rich editor. Markdown has no underline and no
# colour, so the editor writes {u}…{/u} and {c:red}…{/c}; the renderer turns the
# markers into tags once the sanitiser has run, which keeps the writer's raw HTML
# out of the pipeline.
_PALETTE = {"red", "orange", "amber", "green", "teal", "blue", "violet", "pink", "muted"}
_UNDERLINE = re.compile(r"\{u\}(.*?)\{/u\}", re.S)
_TEXT_COLOR = re.compile(r"\{c:(#[0-9a-fA-F]{6}|[a-z]{3,10})\}(.*?)\{/c\}", re.S)
# Size and typeface have no markdown either: {s:lg}…{/s} and {f:serif}…{/f}.
_TEXT_SIZE = re.compile(r"\{s:(sm|lg|xl)\}(.*?)\{/s\}", re.S)
_TEXT_FONT = re.compile(r"\{f:(serif|sans|mono|script)\}(.*?)\{/f\}", re.S)
# Alignment, size and typeface belong to the paragraph, so the marker wraps the
# whole block and becomes a class, not a span.
_ALIGN_BLOCK = re.compile(r"<p(?P<attrs>[^>]*)>\s*\{a:(left|center|right|justify)\}(.*?)\{/a\}\s*</p>", re.S)
# An embedded questionnaire, adventure or deck: `{quiz:12}` alone on its line. The
# container is written after sanitisation, so the id cannot smuggle markup.
_EMBED_BLOCK = re.compile(r"<p>\s*\{(quiz|adventure|deck):(\d{1,9})\}\s*</p>")
_SIZE_BLOCK = re.compile(r"<p(?P<attrs>[^>]*)>\s*\{s:(sm|lg|xl)\}(.*?)\{/s\}\s*</p>", re.S)
_FONT_BLOCK = re.compile(r"<p(?P<attrs>[^>]*)>\s*\{f:(serif|sans|mono|script)\}(.*?)\{/f\}\s*</p>", re.S)
# The capturing group is deliberate: `re.split` keeps what it captures, and the
# code blocks must survive the pass untouched.
_CODE_BLOCK = re.compile(r"(<pre.*?</pre>|<code.*?</code>)", re.S)

# `![alt](/media/x.webp){width=320}` — a size the author dragged in the editor.
_IMAGE_SIZE = re.compile(r"(!\[[^\]]*\]\([^)\s]+)\)\{width=(\d{1,4})(%?)\}")
_IMAGE_SIZED = re.compile(r'<img\b([^>]*?)title="=w(\d{1,4})(%?)"([^>]*?)>')


def _apply_image_sizes(text: str) -> str:
    """Carry an image size through markdown-it as a title, then unwrap it."""
    return _IMAGE_SIZE.sub(lambda m: f'{m.group(1)} "=w{m.group(2)}{m.group(3)}")', text)


def _unwrap_image_sizes(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        before, value, percent, after = match.groups()
        before = before.replace(' title="', "").strip()
        after = after.replace(' title="', "").strip()
        pieces = [piece for piece in (before, f'width="{value}{percent}"', after) if piece]
        return f"<img {' '.join(pieces)}>"

    return _IMAGE_SIZED.sub(replace, html)


def resolve_wikilinks(markdown: str, pages: dict[str, str]) -> tuple[str, list[str]]:
    """Turn ``[[Page]]`` into a link, and return the slugs it points at.

    ``pages`` maps a normalised title/slug to the real slug. A target that does
    not exist yet still becomes a link, flagged ``data-missing`` so the reader
    can create it, exactly like a red link in a wiki.
    """
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        raw_target = match.group(1).strip()
        label = (match.group(2) or raw_target).strip()
        key = raw_target.lower()
        slug = pages.get(key) or pages.get(slugify(raw_target))
        if slug:
            return f'[{label}](/wiki/p/{slug} "[[{raw_target}]]")'
        missing.append(slugify(raw_target))
        # A broken link is still a markdown link here: raw HTML would be
        # escaped by the renderer. `_mark_missing` adds the red-link class once
        # the sanitiser has done its work.
        return f"[{label}](/wiki/new?title={quote(label)})"

    return _WIKILINK.sub(replace, markdown), missing


def _apply_inline_styles(html: str) -> str:
    """Turn the rich editor's underline/colour markers into tags.

    Runs after sanitisation: the tags come from a closed set here, so a page
    still cannot smuggle an arbitrary tag or attribute through the editor. Code
    blocks are left alone — a marker inside a snippet is code, not decoration.
    """
    parts = _CODE_BLOCK.split(html)
    for position in range(0, len(parts), 2):  # even indexes are outside code
        chunk = _UNDERLINE.sub(lambda m: f"<u>{m.group(1)}</u>", parts[position])

        def colour(match: re.Match[str]) -> str:
            value, inner = match.group(1), match.group(2)
            if "</p>" in inner:  # a span cannot straddle two blocks
                return match.group(0)
            if value.startswith("#"):
                return f'<span class="c-hex" data-hex="{value.lower()}">{inner}</span>'
            if value.lower() not in _PALETTE:
                return match.group(0)
            return f'<span class="c-{value.lower()}">{inner}</span>'

        parts[position] = _TEXT_COLOR.sub(colour, chunk)
        parts[position] = _TEXT_SIZE.sub(lambda m: f'<span class="sz-{m.group(1)}">{m.group(2)}</span>', parts[position])
        parts[position] = _TEXT_FONT.sub(lambda m: f'<span class="ff-{m.group(1)}">{m.group(2)}</span>', parts[position])
    return "".join(parts)


def _apply_embeds(html: str) -> str:
    """Turn a bare ``{quiz:12}`` line into an empty container for the SPA."""
    return _EMBED_BLOCK.sub(
        lambda m: f'<div class="wiki-embed" data-embed="{m.group(1)}" data-id="{m.group(2)}"></div>',
        html,
    )


def _add_class(attrs: str, name: str) -> str:
    """Add one class to the attributes of an opening tag, keeping the others."""
    match = re.search(r'class="([^"]*)"', attrs)
    if match:
        return f'{attrs[:match.start(1)]}{match.group(1)} {name}{attrs[match.end(1):]}'
    return f'{attrs} class="{name}"'


def _apply_block_styles(html: str) -> str:
    """Turn the block markers of a paragraph into classes on the block itself.

    The markers nest (`{a:center}{s:lg}…{/s}{/a}`), so each pass accepts a
    paragraph that already carries a class and merges into it.
    """
    # A marker can sit inside another one, in any order: repeat full rounds
    # until nothing moves.
    for _ in range(4):
        before = html
        for pattern, prefix in ((_ALIGN_BLOCK, "al"), (_SIZE_BLOCK, "sz"), (_FONT_BLOCK, "ff")):
            def wrap(match: re.Match[str], prefix: str = prefix) -> str:
                attrs = _add_class(match.group("attrs"), f"{prefix}-{match.group(2)}")
                return f"<p{attrs}>{match.group(3)}</p>"

            html = pattern.sub(wrap, html)
        if html == before:
            break
    return html


def render_markdown(markdown: str, *, pages: dict[str, str] | None = None) -> str:
    """Markdown -> sanitised HTML, with wiki links resolved when ``pages`` given."""
    text = markdown or ""
    if len(text) > MAX_PAGE_MD:
        raise ValueError("Page is too long.")
    if pages is not None:
        text, _ = resolve_wikilinks(text, pages)
    html = _MD.render(_apply_image_sizes(text))
    html = _unwrap_image_sizes(html)
    cleaned = nh3.clean(
        html,
        tags=WIKI_ALLOWED_TAGS,
        attributes=WIKI_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
    # Blocks first: the inline pass would otherwise turn a size marker nested
    # in a paragraph into a span before the block rule could see it.
    return _mark_missing(
        _apply_inline_styles(_apply_block_styles(_apply_embeds(_finalise_links(cleaned))))
    )


_MISSING_START = re.compile(r'<a\s+(?=[^>]*href="/wiki/new\?title=)', re.IGNORECASE)


def _mark_missing(html: str) -> str:
    """Flag links to pages that do not exist yet, after sanitisation."""
    def add(match: re.Match[str]) -> str:
        return '<a class="wikilink is-missing" data-missing="1" '

    return _MISSING_START.sub(add, html)


def _finalise_links(html: str) -> str:
    """Harden external links, keep internal ones in the SPA."""

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        href_match = re.search(r'href="([^"]*)"', tag)
        if not href_match:
            return tag
        href = href_match.group(1)
        parts = urlsplit(href)
        if parts.scheme in {"http", "https"} and parts.netloc:
            # nh3 already wrote rel="noopener noreferrer"; only the target is ours.
            if "target=" not in tag:
                tag = tag[:-1] + ' target="_blank">'
        elif href.startswith("/"):
            if "data-link" not in tag:
                tag = tag[:-1] + " data-link>"
        return tag

    return re.sub(r"<a\s[^>]*>", replace, html)


def extract_links(markdown: str) -> list[str]:
    """Every internal target of a document: wikilinks, relative hrefs, media."""
    targets: list[str] = []
    for match in _WIKILINK.finditer(markdown or ""):
        targets.append(match.group(1).strip())
    for match in re.finditer(r"\]\((/[^)\s]+|\.{0,2}/[^)\s]+)\)", markdown or ""):
        targets.append(match.group(1))
    return targets


def outline(markdown: str) -> list[dict[str, object]]:
    """Headings of a page, for the table of contents of the reader."""
    items: list[dict[str, object]] = []
    for line in (markdown or "").splitlines():
        match = re.match(r"^(#{1,4})\s+(.*)$", line.strip())
        if not match:
            continue
        depth = len(match.group(1))
        if depth == 1:
            # The level-1 heading repeats the page title shown above the article:
            # a one-line table of contents saying the same thing is noise.
            continue
        title = re.sub(r"[`*_]", "", match.group(2)).strip()
        items.append({"depth": depth, "text": title, "anchor": slugify(title, fallback="section")})
    return items


def excerpt(markdown: str, limit: int = 180) -> str:
    """First meaningful sentence of a page, for lists and search results."""
    text = re.sub(r"```.*?```", " ", markdown or "", flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[\[([^\]\|]+)(\|[^\]]+)?\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_`]", "", text)
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


# ---------------------------------------------------------------------------
# References and links
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"(?<![\w/])((?:https?://)[^\s<>()\[\]`]+)", re.IGNORECASE)
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]{1,180})(?:\|[^\]]{1,180})?\]\]")
_WIKI_HREF_RE = re.compile(r"\]\(/wiki/p/([a-z0-9\-]+)\)")


def host_of(url: str) -> str:
    """Bare host of an external URL, for grouping sources in the index."""
    match = re.match(r"^(?:https?:)?//([^/?#]+)", url or "", re.IGNORECASE)
    host = match.group(1).lower() if match else ""
    return host[4:] if host.startswith("www.") else host


def extract_external_links(markdown: str) -> list[dict[str, str]]:
    """External URLs written in a page, with the link text when there is one.

    Only ``http(s)`` counts: a mail link or an anchor is not a source you can
    cite, and a bare ``/media/...`` is a picture, not a reference.
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"\[([^\]]{1,200})\]\(((?:https?)://[^)\s]+)\)", markdown or ""):
        url = match.group(2).strip()
        if url in seen:
            continue
        seen.add(url)
        found.append({"url": url, "label": match.group(1).strip(), "host": host_of(url)})
    for match in _URL_RE.finditer(markdown or ""):
        url = match.group(1).rstrip(".,;:")
        if url in seen:
            continue
        seen.add(url)
        found.append({"url": url, "label": "", "host": host_of(url)})
    return found


def page_breadcrumb(page_id: int, by_id: dict[int, dict]) -> list[dict]:
    """Ancestors of a page, root first, for the reader's breadcrumb."""
    trail: list[dict] = []
    seen: set[int] = set()
    current = by_id.get(page_id)
    guard = 0
    while current is not None and guard < 12:
        guard += 1
        if current["id"] in seen:
            break
        seen.add(current["id"])
        trail.append({"id": current["id"], "title": current["title"], "slug": current["slug"]})
        parent = current.get("parent_id")
        current = by_id.get(parent) if parent else None
    return list(reversed(trail))


def descendants(page_id: int, pages: list[dict]) -> set[int]:
    """Every page below ``page_id``, so a move can never create a cycle."""
    children: dict[int, list[int]] = {}
    for page in pages:
        children.setdefault(page.get("parent_id") or 0, []).append(page["id"])
    found: set[int] = set()
    stack = list(children.get(page_id, ()))
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(children.get(current, ()))
    return found


def rebuild_links(db, page) -> None:
    """Recompute the outgoing edges of a page: wikilinks and ``/wiki/p/slug``."""
    from sqlalchemy import delete, select

    from .models import WikiLink, WikiPage

    db.execute(delete(WikiLink).where(WikiLink.from_page_id == page.id))
    siblings = db.scalars(select(WikiPage).where(WikiPage.wiki_id == page.wiki_id)).all()
    slugs = {sibling.slug: sibling.id for sibling in siblings}
    titles = {sibling.title.lower(): sibling.slug for sibling in siblings}
    targets: list[str] = []
    for match in _WIKILINK_RE.finditer(page.content_md or ""):
        raw = match.group(1).strip()
        targets.append(titles.get(raw.lower()) or slugify(raw))
    for match in _WIKI_HREF_RE.finditer(page.content_md or ""):
        targets.append(match.group(1))
    seen: set[str] = set()
    for slug in targets:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        db.add(
            WikiLink(
                wiki_id=page.wiki_id,
                from_page_id=page.id,
                target_slug=slug,
                to_page_id=slugs.get(slug),
            )
        )


# ---------------------------------------------------------------------------
# Versions and diffs
# ---------------------------------------------------------------------------
def unified_diff(old: str, new: str, *, from_label: str = "a", to_label: str = "b") -> list[dict]:
    """Structured line diff: one entry per hunk line, ready for the viewer."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    rows: list[dict] = []
    for group in matcher.get_grouped_opcodes(3):
        old_start = group[0][1] + 1
        new_start = group[0][3] + 1
        rows.append({"kind": "hunk", "text": f"@@ -{old_start} +{new_start} @@"})
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in old_lines[i1:i2]:
                    rows.append({"kind": "equal", "text": line})
                continue
            if tag in {"replace", "delete"}:
                for line in old_lines[i1:i2]:
                    rows.append({"kind": "del", "text": line})
            if tag in {"replace", "insert"}:
                for line in new_lines[j1:j2]:
                    rows.append({"kind": "add", "text": line})
    return rows


def _word_segments(left: str, right: str) -> tuple[list[dict], list[dict]]:
    """Split a changed line pair into same/changed runs, for inline emphasis."""
    old_tokens = re.findall(r"\S+\s*|\s+", left)
    new_tokens = re.findall(r"\S+\s*|\s+", right)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)

    def build(side: str) -> list[dict]:
        segments: list[dict] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                tokens = old_tokens[i1:i2] if side == "left" else new_tokens[j1:j2]
                if tokens:
                    segments.append({"kind": "same", "text": "".join(tokens)})
                continue
            if side == "left" and tag in {"replace", "delete"}:
                chunk = "".join(old_tokens[i1:i2])
                if chunk:
                    segments.append({"kind": "chg", "text": chunk})
            if side == "right" and tag in {"replace", "insert"}:
                chunk = "".join(new_tokens[j1:j2])
                if chunk:
                    segments.append({"kind": "chg", "text": chunk})
        return segments

    return build("left"), build("right")


def side_by_side_diff(old: str, new: str, *, context: int = 3) -> list[dict]:
    """Aligned two-column diff: one row per line, additions and removals faced.

    A reader compares two versions by scanning columns, not by reconstructing a
    unified patch in their head. Changed lines that pair up share a row and get
    word-level emphasis, so a typo fix lights up three words, not a whole line.
    """
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    rows: list[dict] = []

    def blank(number: int | None = None) -> dict:
        return {"no": number, "text": "", "segments": []}

    for group in matcher.get_grouped_opcodes(context):
        rows.append(
            {
                "kind": "hunk",
                "left": blank(),
                "right": blank(),
                "text": f"@@ -{group[0][1] + 1} , +{group[0][3] + 1} @@",
            }
        )
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for offset in range(i2 - i1):
                    rows.append(
                        {
                            "kind": "equal",
                            "left": {"no": i1 + offset + 1, "text": old_lines[i1 + offset], "segments": []},
                            "right": {"no": j1 + offset + 1, "text": new_lines[j1 + offset], "segments": []},
                        }
                    )
                continue
            if tag == "replace":
                pairs = min(i2 - i1, j2 - j1)
                for offset in range(pairs):
                    left_text = old_lines[i1 + offset]
                    right_text = new_lines[j1 + offset]
                    left_segments, right_segments = _word_segments(left_text, right_text)
                    rows.append(
                        {
                            "kind": "change",
                            "left": {"no": i1 + offset + 1, "text": left_text, "segments": left_segments},
                            "right": {"no": j1 + offset + 1, "text": right_text, "segments": right_segments},
                        }
                    )
                for offset in range(pairs, i2 - i1):
                    rows.append(
                        {
                            "kind": "del",
                            "left": {"no": i1 + offset + 1, "text": old_lines[i1 + offset], "segments": []},
                            "right": blank(),
                        }
                    )
                for offset in range(pairs, j2 - j1):
                    rows.append(
                        {
                            "kind": "add",
                            "left": blank(),
                            "right": {"no": j1 + offset + 1, "text": new_lines[j1 + offset], "segments": []},
                        }
                    )
                continue
            if tag == "delete":
                for offset in range(i2 - i1):
                    rows.append(
                        {
                            "kind": "del",
                            "left": {"no": i1 + offset + 1, "text": old_lines[i1 + offset], "segments": []},
                            "right": blank(),
                        }
                    )
            if tag == "insert":
                for offset in range(j2 - j1):
                    rows.append(
                        {
                            "kind": "add",
                            "left": blank(),
                            "right": {"no": j1 + offset + 1, "text": new_lines[j1 + offset], "segments": []},
                        }
                    )
    return rows


def diff_stats(rows: list[dict]) -> dict[str, int]:
    return {
        "added": sum(1 for row in rows if row["kind"] == "add"),
        "removed": sum(1 for row in rows if row["kind"] == "del"),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def rewrite_links_for_export(markdown: str, slug_by_title: dict[str, str]) -> str:
    """Point every internal link at a sibling ``.md`` file of the archive.

    A wiki exported as a folder must stay navigable on a laptop: absolute
    ``/wiki/p/slug`` routes mean nothing outside the application.
    """

    def replace(match: re.Match[str]) -> str:
        raw_target = match.group(1).strip()
        label = (match.group(2) or raw_target).strip()
        slug = slug_by_title.get(raw_target.lower()) or slug_by_title.get(slugify(raw_target))
        if not slug:
            return f"**{label}**"
        return f"[{label}]({slug}.md)"

    markdown = _WIKILINK.sub(replace, markdown or "")
    return re.sub(
        r"\]\(/wiki/p/([a-z0-9\-]+)\)",
        lambda m: f"]({m.group(1)}.md)",
        markdown,
    )


def build_zip(pages: list[tuple[str, str, str]], index_md: str, media: dict[str, bytes] | None = None) -> bytes:
    """Zip of ``slug.md`` files plus an index, and any attached media."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", index_md)
        for slug, title, markdown in pages:
            front = f"# {title}\n\n" if title else ""
            archive.writestr(f"{slug}.md", front + (markdown or ""))
        for name, payload in (media or {}).items():
            archive.writestr(f"media/{name}", payload)
    return buffer.getvalue()
