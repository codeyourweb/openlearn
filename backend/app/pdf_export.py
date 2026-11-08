# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Render a wiki page, or a whole wiki, as a PDF document.

The PDF is produced on the server with ReportLab: the reader gets the same
headings, emphasis, colours, code blocks, lists, quotes and images as the HTML
view. A whole-wiki export keeps the menu tree — the table of contents follows
the parent/child order and each page starts a new section — so an exported wiki
still reads like the wiki it came from.

Remote images are named but not fetched: the export must never turn a document
download into an outbound request from this instance.
"""

from __future__ import annotations

import io
import os
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus.tableofcontents import TableOfContents
from markdown_it import MarkdownIt

from .config import settings
from .wiki import _apply_image_sizes

#: The palette the editor offers, as concrete colours the PDF can print.
PALETTE = {
    "red": "#d64545",
    "orange": "#e07b39",
    "amber": "#c99a15",
    "green": "#2f9e60",
    "teal": "#1f8f8f",
    "blue": "#2f6fb5",
    "violet": "#7a4fbd",
    "pink": "#cf4f8a",
    "muted": "#6b7280",
}

_UNDERLINE = re.compile(r"\{u\}(.*?)\{/u\}", re.S)
_TEXT_COLOR = re.compile(r"\{c:(#[0-9a-fA-F]{6}|[a-z]{3,10})\}(.*?)\{/c\}", re.S)
_IMAGE_SIZE_TITLE = re.compile(r"^=w(\d{1,4})(%?)$")

#: Markdown is parsed once; tables and strikethrough are part of the dialect the
#: editor writes, so the PDF understands them too.
_PARSER = MarkdownIt("commonmark").enable(["table", "strikethrough"])

_CONTENT_WIDTH = A4[0] - 40 * mm

#: ReportLab's built-in fonts only cover Latin-1. When DejaVu is installed the
#: document uses it, so Cyrillic, Greek and Hebrew titles keep their glyphs
#: instead of turning into empty boxes.
_DEJAVU = Path("/usr/share/fonts/truetype/dejavu")
_REGISTERED = False


_FACES = {
    "DejaVu": "DejaVuSans.ttf",
    "DejaVu-Bold": "DejaVuSans-Bold.ttf",
    "DejaVu-Oblique": "DejaVuSans-Oblique.ttf",
    "DejaVu-Mono": "DejaVuSansMono.ttf",
}


def _fonts() -> tuple[str, str, str, str]:
    """Pick the widest font set the image actually ships.

    A Debian image may carry only the core faces (no oblique), so each file is
    checked before it is registered: a missing style degrades to the regular
    face instead of failing the whole export.
    """
    global _REGISTERED
    if _DEJAVU.is_dir() and (_DEJAVU / "DejaVuSans.ttf").is_file():
        if not _REGISTERED:
            for name, filename in _FACES.items():
                path = _DEJAVU / filename
                if not path.is_file():
                    continue
                try:
                    pdfmetrics.registerFont(TTFont(name, str(path)))
                except Exception:  # noqa: BLE001 - a damaged file must not break export
                    continue
            if "DejaVu-Bold" in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFontFamily(
                    "DejaVu",
                    normal="DejaVu",
                    bold="DejaVu-Bold",
                    italic="DejaVu-Oblique"
                    if "DejaVu-Oblique" in pdfmetrics.getRegisteredFontNames()
                    else "DejaVu",
                )
            _REGISTERED = True
        registered = set(pdfmetrics.getRegisteredFontNames())
        body = "DejaVu" if "DejaVu" in registered else "Helvetica"
        return (
            body,
            "DejaVu-Bold" if "DejaVu-Bold" in registered else body,
            "DejaVu-Oblique" if "DejaVu-Oblique" in registered else body,
            "DejaVu-Mono" if "DejaVu-Mono" in registered else "Courier",
        )
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body_font, bold_font, italic_font, mono_font = _fonts()
    styles: dict[str, ParagraphStyle] = {
        "body": ParagraphStyle(
            "OLBody",
            parent=base["BodyText"],
            fontName=body_font,
            fontSize=10,
            leading=15,
            spaceAfter=6,
            alignment=TA_LEFT,
        ),
        "quote": ParagraphStyle(
            "OLQuote",
            parent=base["BodyText"],
            fontName=italic_font,
            fontSize=10,
            leading=14,
            leftIndent=12,
            textColor=colors.HexColor("#4b5563"),
            spaceBefore=4,
            spaceAfter=8,
        ),
        "code": ParagraphStyle(
            "OLCode",
            parent=base["Code"],
            fontName=mono_font,
            fontSize=8.5,
            leading=11.5,
            backColor=colors.HexColor("#f3f4f6"),
            borderPadding=6,
            leftIndent=6,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "title": ParagraphStyle(
            "OLTitle",
            parent=base["Title"],
            fontName=bold_font,
            fontSize=22,
            leading=26,
            spaceAfter=10,
        ),
        "cover_title": ParagraphStyle(
            "OLCoverTitle",
            parent=base["Title"],
            fontName=bold_font,
            fontSize=28,
            leading=34,
            spaceAfter=14,
        ),
        "lede": ParagraphStyle(
            "OLLede",
            parent=base["BodyText"],
            fontName=body_font,
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#374151"),
            spaceAfter=12,
        ),
        "caption": ParagraphStyle(
            "OLCaption",
            parent=base["BodyText"],
            fontName=italic_font,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            "OLMeta",
            parent=base["BodyText"],
            fontName=body_font,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#6b7280"),
        ),
    }
    # Headings are named so the document template can tell the table of contents
    # what level each one belongs to.
    for level, size, before, after in ((1, 17, 14, 6), (2, 14, 12, 5), (3, 12, 10, 4), (4, 11, 8, 3)):
        styles[f"h{level}"] = ParagraphStyle(
            f"OLHeading{level}",
            parent=base["Heading1"],
            fontName=bold_font,
            fontSize=size,
            leading=size * 1.25,
            spaceBefore=before,
            spaceAfter=after,
            textColor=colors.HexColor("#111827"),
        )
    return styles


# ---------------------------------------------------------------------------
# Inline content
# ---------------------------------------------------------------------------
def _colour(value: str) -> str | None:
    """Return a printable colour for a `{c:…}` marker, or None if unknown."""
    lowered = value.strip().lower()
    if lowered in PALETTE:
        return PALETTE[lowered]
    if re.fullmatch(r"#[0-9a-f]{6}", lowered):
        return lowered
    return None


def _markers(text: str) -> str:
    """Turn the editor's `{u}` / `{c:…}` markers into paragraph markup."""
    text = _UNDERLINE.sub(lambda m: f"<u>{m.group(1)}</u>", text)

    def colour(match: re.Match[str]) -> str:
        value = _colour(match.group(1))
        if value is None:
            return match.group(0)
        return f'<font color="{value}">{match.group(2)}</font>'

    return _TEXT_COLOR.sub(colour, text)


def _inline(tokens: list) -> str:
    """Render markdown inline tokens as ReportLab paragraph markup."""
    parts: list[str] = []
    for token in tokens or []:
        kind = token.type
        if kind == "text":
            parts.append(_markers(escape(token.content)))
        elif kind == "code_inline":
            parts.append(
                f'<font name="{_fonts()[3]}" backColor="#f3f4f6" size="9">{escape(token.content)}</font>'
            )
        elif kind in ("strong_open", "em_open", "u_open"):
            parts.append({"strong_open": "<b>", "em_open": "<i>", "u_open": "<u>"}[kind])
        elif kind in ("strong_close", "em_close", "u_close"):
            parts.append({"strong_close": "</b>", "em_close": "</i>", "u_close": "</u>"}[kind])
        elif kind == "s_open":
            parts.append('<strike>')
        elif kind == "s_close":
            parts.append("</strike>")
        elif kind == "link_open":
            href = escape(token.attrGet("href") or "", {'"': "&quot;"})
            parts.append(f'<a href="{href}" color="#2f6fb5">')
        elif kind == "link_close":
            parts.append("</a>")
        elif kind in ("softbreak", "hardbreak"):
            parts.append("<br/>")
        elif kind == "image":
            alt = token.content or token.attrGet("alt") or "image"
            parts.append(f"<i>[{escape(alt)}]</i>")
        elif kind == "html_inline":
            continue  # raw HTML stays out of the PDF
        else:
            if token.content:
                parts.append(_markers(escape(token.content)))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def _media_file(src: str) -> Path | None:
    """Resolve `/media/<name>` to a file inside the media directory, safely."""
    match = re.fullmatch(r"/media/([A-Za-z0-9_.\-]+)", src or "")
    if not match:
        return None
    candidate = (settings.media_dir / match.group(1)).resolve()
    try:
        candidate.relative_to(settings.media_dir.resolve())
    except ValueError:  # pragma: no cover - defensive
        return None
    return candidate if candidate.is_file() else None


def _image_flowable(token) -> list:
    """An uploaded image, scaled to the frame; anything else becomes a caption."""
    src = token.attrGet("src") or ""
    alt = token.content or token.attrGet("alt") or ""
    path = _media_file(src)
    if path is None:
        label = alt or src
        return [Paragraph(f"[image] {escape(label)}", _styles()["caption"])]
    width = None
    title = token.attrGet("title") or ""
    match = _IMAGE_SIZE_TITLE.match(title.strip())
    if match:
        value = int(match.group(1))
        width = _CONTENT_WIDTH * value / 100 if match.group(2) else min(value, _CONTENT_WIDTH)
    try:
        image = Image(str(path))
    except Exception:  # noqa: BLE001 - a broken file must not break the export
        return [Paragraph(f"[image] {escape(alt or src)}", _styles()["caption"])]
    natural = image.imageWidth or _CONTENT_WIDTH
    target = width or natural
    if target > _CONTENT_WIDTH:
        target = _CONTENT_WIDTH
    image.drawWidth = target
    image.drawHeight = natural and (image.imageHeight * target / natural) or target
    out = [image]
    if alt:
        out.append(Paragraph(escape(alt), _styles()["caption"]))
    return out


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------
class _Builder:
    def __init__(self, heading_offset: int = 0) -> None:
        self.styles = _styles()
        #: A page inside a whole-wiki export starts at its own depth, so the
        #: headings it contains sit one level below its title.
        self.heading_offset = heading_offset

    def flowables(self, tokens: list, depth: int = 0) -> list:
        out: list = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            kind = token.type

            if kind == "heading_open":
                level = min(max(int(token.tag[1]) + self.heading_offset, 1), 4)
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                text = _inline(inline.children if inline else [])
                if text.strip():
                    out.append(Paragraph(text, self.styles[f"h{level}"]))
                index += 3 if index + 2 < len(tokens) and tokens[index + 2].type == "heading_close" else 2
                continue

            if kind == "paragraph_open":
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                children = inline.children if inline else []
                only_image = [
                    child for child in children if child.type not in ("text",) or child.content.strip()
                ]
                if len(only_image) == 1 and only_image[0].type == "image":
                    out.extend(_image_flowable(only_image[0]))
                else:
                    text = _inline(children)
                    if text.strip():
                        out.append(Paragraph(text, self.styles["body"]))
                index += 3 if index + 2 < len(tokens) and tokens[index + 2].type == "paragraph_close" else 2
                continue

            if kind in ("bullet_list_open", "ordered_list_open"):
                block, index = self._list(tokens, index, ordered=kind == "ordered_list_open")
                out.append(block)
                continue

            if kind == "blockquote_open":
                close = self._matching(tokens, index, "blockquote_open", "blockquote_close")
                inner = self.flowables(tokens[index + 1 : close], depth + 1)
                for item in inner:
                    if isinstance(item, Paragraph):
                        item.style = self.styles["quote"]
                out.extend(inner)
                index = close + 1
                continue

            if kind in ("fence", "code_block"):
                code = token.content.rstrip("\n")
                if code:
                    out.append(Preformatted(code, self.styles["code"]))
                index += 1
                continue

            if kind == "hr":
                out.append(Spacer(1, 4))
                out.append(HRFlowable(width="100%", color=colors.HexColor("#d1d5db"), thickness=0.6))
                out.append(Spacer(1, 6))
                index += 1
                continue

            if kind == "table_open":
                table, index = self._table(tokens, index)
                if table is not None:
                    out.append(table)
                continue

            if kind == "image":
                out.extend(_image_flowable(token))
                index += 1
                continue

            index += 1
        return out

    @staticmethod
    def _matching(tokens: list, start: int, open_type: str, close_type: str) -> int:
        depth = 0
        for position in range(start, len(tokens)):
            if tokens[position].type == open_type:
                depth += 1
            elif tokens[position].type == close_type:
                depth -= 1
                if depth == 0:
                    return position
        return len(tokens) - 1

    def _list(self, tokens: list, start: int, *, ordered: bool) -> tuple:
        close = self._matching(
            tokens, start, "ordered_list_open" if ordered else "bullet_list_open",
            "ordered_list_close" if ordered else "bullet_list_close",
        )
        items: list = []
        position = start + 1
        while position < close:
            if tokens[position].type == "list_item_open":
                end = self._matching(tokens, position, "list_item_open", "list_item_close")
                inner = self.flowables(tokens[position + 1 : end], depth=1)
                if inner:
                    items.append(ListItem(inner, leftIndent=14))
                position = end + 1
                continue
            position += 1
        options = {
            "leftIndent": 16,
            "bulletFontSize": 9,
            "spaceAfter": 6,
        }
        if ordered:
            options["bulletType"] = "1"
            options["start"] = "1"
        else:
            options["bulletType"] = "bullet"
            options["bulletChar"] = "•"
        return ListFlowable(items, **options), close + 1

    def _table(self, tokens: list, start: int):
        close = self._matching(tokens, start, "table_open", "table_close")
        rows: list[list[str]] = []
        header_rows = 0
        in_head = False
        position = start + 1
        while position < close:
            token = tokens[position]
            if token.type == "thead_open":
                in_head = True
            elif token.type == "thead_close":
                in_head = False
            elif token.type == "tr_open":
                cells: list[str] = []
                position += 1
                while position < close and tokens[position].type != "tr_close":
                    if tokens[position].type in ("th_open", "td_open"):
                        inline = tokens[position + 1] if position + 1 < len(tokens) else None
                        cells.append(_inline(inline.children if inline else []))
                        position += 2
                        continue
                    position += 1
                rows.append(cells)
                if in_head:
                    header_rows += 1
            position += 1
        if not rows:
            return None, close + 1
        table = Table(rows, hAlign="LEFT", repeatRows=header_rows)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if header_rows:
            style.append(("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#f3f4f6")))
        table.setStyle(TableStyle(style))
        return table, close + 1


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class _WikiDoc(BaseDocTemplate):
    """A4 document that feeds its table of contents from the page headings."""

    def __init__(self, buffer: io.BytesIO, *, title: str, subtitle: str) -> None:
        super().__init__(
            buffer,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title=title,
            author=subtitle or "OpenLearn",
            subject="Wiki export",
        )
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._decorate)])
        self.doc_title = title
        # PDF bookmarks cannot skip a level: a page may start with an h3, so the
        # outline is flattened to "one deeper than the previous entry at most".
        self._outline_level = -1

    def _decorate(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(_fonts()[0], 7.5)
        canvas.setFillColor(colors.HexColor("#9ca3af"))
        canvas.drawString(20 * mm, A4[1] - 12 * mm, self.doc_title[:90])
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"{doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        if isinstance(flowable, Paragraph) and flowable.style.name.startswith("OLHeading"):
            level = int(flowable.style.name[-1])
            wanted = max(level - 1, 0)
            outline = min(wanted, self._outline_level + 1)
            self._outline_level = outline
            text = flowable.getPlainText()
            key = f"h{self.page}-{id(flowable)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, outline, 0)
            self.notify("TOCEntry", (wanted, text, self.page, key))


_CHARMAP: set[int] | None = None


def _charmap() -> set[int]:
    """Code points the body font can actually draw."""
    global _CHARMAP
    if _CHARMAP is not None:
        return _CHARMAP
    body, *_ = _fonts()
    printable = set(range(0x20, 0x7F)) | set(range(0xA0, 0x100))
    if body == "DejaVu":
        try:
            face = pdfmetrics.getFont("DejaVu").face  # type: ignore[attr-defined]
            printable |= {code for code in face.charToGlyph}
        except Exception:  # noqa: BLE001 - fall back to Latin-1
            pass
    _CHARMAP = printable
    return _CHARMAP


def _sanitize(text: str) -> str:
    """Drop glyphs no embedded font can draw (emoji head a wiki title here).

    Without this, a decorated title such as "🛡️ Sentinel Kit" prints an empty
    square and stops matching its own heading, which then appears twice.
    """
    if not text:
        return text
    allowed = _charmap()
    lines = []
    for line in text.split("\n"):
        kept = "".join(ch for ch in line if ch in "\t" or ord(ch) in allowed)
        if kept != line:
            indent = line[: len(line) - len(line.lstrip())]
            kept = indent + " ".join(kept.strip(" ").split())
        lines.append(kept.rstrip())
    return "\n".join(lines)


def _strip_title_heading(markdown: str, title: str) -> str:
    """Drop a leading `# Title` that repeats the page's own heading."""
    lines = markdown.lstrip("\n").splitlines()
    if not lines:
        return markdown
    first = lines[0].strip()
    if first.startswith("# ") and first[2:].strip().lower() == (title or "").strip().lower():
        return "\n".join(lines[1:]).lstrip("\n")
    return markdown


def page_pdf(*, wiki_title: str, page_title: str, markdown: str, footer: str = "") -> bytes:
    """One page as a standalone PDF, without a table of contents."""
    buffer = io.BytesIO()
    builder = _Builder()
    page_title, wiki_title = _sanitize(page_title), _sanitize(wiki_title)
    doc = _WikiDoc(buffer, title=page_title or wiki_title, subtitle=footer)
    story: list = [Paragraph(escape(page_title), builder.styles["title"])]
    if wiki_title:
        story.append(Paragraph(escape(wiki_title), builder.styles["meta"]))
    story.append(Spacer(1, 6))
    body = _strip_title_heading(_sanitize(markdown or ""), page_title)
    story.extend(builder.flowables(_PARSER.parse(_apply_image_sizes(body))))
    doc.build(story)
    return buffer.getvalue()


#: Four words decide the whole reading experience of an export; they follow the
#: interface language the caller asks for.
PDF_LABELS: dict[str, dict[str, str]] = {
    "en": {"contents": "Contents", "pages": "{n} page(s)", "exported": "exported on {date}", "empty": "This page is empty."},
    "fr": {"contents": "Sommaire", "pages": "{n} page(s)", "exported": "exporté le {date}", "empty": "Cette fiche est vide."},
    "de": {"contents": "Inhalt", "pages": "{n} Seite(n)", "exported": "exportiert am {date}", "empty": "Diese Seite ist leer."},
    "es": {"contents": "Índice", "pages": "{n} página(s)", "exported": "exportado el {date}", "empty": "Esta página está vacía."},
    "it": {"contents": "Indice", "pages": "{n} pagina/pagine", "exported": "esportato il {date}", "empty": "Questa pagina è vuota."},
    "ru": {"contents": "Содержание", "pages": "Страниц: {n}", "exported": "экспортировано {date}", "empty": "Эта страница пуста."},
    "ja": {"contents": "目次", "pages": "{n} ページ", "exported": "{date} に書き出し", "empty": "このページは空です。"},
    "zh": {"contents": "目录", "pages": "{n} 页", "exported": "{date} 导出", "empty": "此页面为空。"},
    "pt": {"contents": "Índice", "pages": "{n} página(s)", "exported": "exportado em {date}", "empty": "Esta página está vazia."},
    "hi": {"contents": "विषय-सूची", "pages": "{n} पृष्ठ", "exported": "{date} को निर्यात", "empty": "यह पृष्ठ खाली है।"},
    "bn": {"contents": "সূচিপত্র", "pages": "{n} পৃষ্ঠা", "exported": "{date} তারিখে রপ্তানি", "empty": "এই পৃষ্ঠাটি খালি।"},
    "ar": {"contents": "المحتويات", "pages": "{n} صفحة", "exported": "تم التصدير في {date}", "empty": "هذه الصفحة فارغة."},
}


def wiki_pdf(
    *,
    wiki_title: str,
    description: str = "",
    pages: list[dict],
    footer: str = "",
    language: str = "en",
) -> bytes:
    """A whole wiki: cover, table of contents in menu order, then every page.

    ``pages`` arrives already ordered as the menu shows them, each entry with
    ``title``, ``markdown`` and ``depth`` — depth drives both the heading level
    and the indentation of the table of contents.
    """
    buffer = io.BytesIO()
    builder = _Builder()
    wiki_title, description = _sanitize(wiki_title), _sanitize(description)
    pages = [{**page, "title": _sanitize(page.get("title") or ""), "markdown": _sanitize(page.get("markdown") or "")} for page in pages]
    doc = _WikiDoc(buffer, title=wiki_title, subtitle=footer)
    story: list = [Paragraph(escape(wiki_title), builder.styles["cover_title"])]
    if description:
        story.append(Paragraph(_markers(escape(description)), builder.styles["lede"]))
    labels = PDF_LABELS.get((language or "en")[:2], PDF_LABELS["en"])
    counter = labels["pages"].format(n=len(pages))
    exported = labels["exported"].format(date=date.today().isoformat())
    story.append(Paragraph(f"{counter} · {exported}", builder.styles["meta"]))
    story.append(Spacer(1, 10))
    body_font, bold_font, italic_font, _mono = _fonts()
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("TOC1", fontName=bold_font, fontSize=10, leading=15, leftIndent=0),
        ParagraphStyle("TOC2", fontName=body_font, fontSize=9.5, leading=14, leftIndent=14),
        ParagraphStyle("TOC3", fontName=body_font, fontSize=9, leading=13, leftIndent=28),
        ParagraphStyle("TOC4", fontName=italic_font, fontSize=8.5, leading=12, leftIndent=42),
    ]
    toc_title = ParagraphStyle(
        "OLTocTitle",
        parent=builder.styles["h1"],
        spaceBefore=18,
        textColor=colors.HexColor("#111827"),
    )
    story.append(Paragraph(labels["contents"], toc_title))
    story.append(Spacer(1, 4))
    story.append(toc)
    story.append(PageBreak())

    for position, page in enumerate(pages):
        depth = min(max(int(page.get("depth") or 0), 0), 3)
        heading = ParagraphStyle(
            f"OLHeading{depth + 1}",
            parent=builder.styles[f"h{depth + 1}"],
            spaceBefore=0 if position else 0,
        )
        story.append(Paragraph(escape(page.get("title") or "Untitled"), heading))
        page_builder = _Builder(heading_offset=depth + 1)
        content = _strip_title_heading(page.get("markdown") or "", page.get("title") or "")
        body = page_builder.flowables(_PARSER.parse(_apply_image_sizes(content)))
        story.extend(body or [Paragraph(f'<i>{escape(labels["empty"])}</i>', builder.styles["meta"])])
        if position < len(pages) - 1:
            story.append(PageBreak())

    doc.multiBuild(story)
    return buffer.getvalue()
