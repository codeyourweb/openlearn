# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Printable revision cards: an A4 sheet a teacher can cut up.

Two cards per row, four rows per page, so one sheet holds eight cards. The
verso page repeats the same grid with the columns mirrored, which is what makes
a duplex print come out front-to-back. Cut marks sit between the cells.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from .cards import plain
from .pdf_export import _fonts, _sanitize

MARGIN = 14 * mm
COLUMNS = 2
ROWS = 4
GUTTER = 6 * mm


def _wrapped(text: str, font: str, size: float, width: float) -> list[str]:
    """Greedy word wrap, because Paragraph would need a full stylesheet here."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_cell(
    pdf: pdf_canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    body: str,
    bold: str,
    image: str | None,
    number: int | None,
) -> None:
    pdf.setStrokeColorRGB(0.72, 0.72, 0.75)
    pdf.setLineWidth(0.6)
    pdf.roundRect(x, y, width, height, 4 * mm, stroke=1, fill=0)

    cursor_y = y + height - 7 * mm
    if number is not None:
        pdf.setFont(body, 7)
        pdf.setFillColorRGB(0.55, 0.55, 0.6)
        pdf.drawString(x + 4 * mm, y + height - 5.5 * mm, f"{number}")
        pdf.setFillColorRGB(0, 0, 0)

    if image:
        # The picture takes the top half of the card, like a playing card — and
        # the whole cell when there is no text, since an image-only card is the
        # common case for character cards.
        try:
            picture = ImageReader(image)
            img_width, img_height = picture.getSize()
            box_w = width - 8 * mm
            box_h = (height - 12 * mm) if not text.strip() else height * 0.46
            scale = min(box_w / img_width, box_h / img_height)
            draw_w, draw_h = img_width * scale, img_height * scale
            pdf.drawImage(
                picture,
                x + (width - draw_w) / 2,
                cursor_y - draw_h,
                width=draw_w,
                height=draw_h,
                mask="auto",
            )
            cursor_y -= draw_h + 4 * mm
        except Exception:  # noqa: BLE001 - a broken file must not stop the sheet
            pass

    size = 11
    font = bold
    if len(text) > 120:
        size, font = 9.5, body
    for line in _wrapped(_sanitize(text), font, size, width - 8 * mm)[:12]:
        pdf.setFont(font, size)
        pdf.drawString(x + 4 * mm, cursor_y, line)
        cursor_y -= size * 1.35
        if cursor_y < y + 4 * mm:
            break


def sheet_pdf(*, title: str, cards: list[dict[str, object]], footer: str = "") -> bytes:
    """Build the two-sided sheet.

    ``cards`` items: ``{"front", "back", "image_path", "back_image_path"}``, each
    picture being either a path or ``None``.
    """
    buffer = io.BytesIO()
    body, bold, _italic, _mono = _fonts()
    pdf = pdf_canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4

    cell_w = (page_w - 2 * MARGIN - (COLUMNS - 1) * GUTTER) / COLUMNS
    cell_h = (page_h - 2 * MARGIN - 30 * mm - (ROWS - 1) * GUTTER) / ROWS
    per_sheet = COLUMNS * ROWS

    def header(text: str, subtitle: str) -> None:
        pdf.setFont(bold, 12)
        pdf.drawString(MARGIN, page_h - MARGIN - 4 * mm, _sanitize(text)[:90])
        pdf.setFont(body, 7.5)
        pdf.setFillColorRGB(0.45, 0.45, 0.5)
        pdf.drawString(MARGIN, page_h - MARGIN - 9 * mm, _sanitize(subtitle)[:120])
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setStrokeColorRGB(0.85, 0.85, 0.88)
        pdf.line(MARGIN, page_h - MARGIN - 12 * mm, page_w - MARGIN, page_h - MARGIN - 12 * mm)

    sheet_index = 0
    for start in range(0, max(len(cards), 1), per_sheet):
        chunk = cards[start : start + per_sheet]
        sheet_index += 1
        header(title, f"Recto — planche {sheet_index}")
        for offset, card in enumerate(chunk):
            column = offset % COLUMNS
            row = offset // COLUMNS
            x = MARGIN + column * (cell_w + GUTTER)
            y = page_h - MARGIN - 18 * mm - (row + 1) * cell_h - row * GUTTER
            _draw_cell(
                pdf,
                x=x,
                y=y,
                width=cell_w,
                height=cell_h,
                text=str(card.get("front") or ""),
                body=body,
                bold=bold,
                image=str(card["image_path"]) if card.get("image_path") else None,
                number=start + offset + 1,
            )
        pdf.setFont(body, 7)
        pdf.setFillColorRGB(0.45, 0.45, 0.5)
        pdf.drawString(MARGIN, MARGIN - 4 * mm, _sanitize(footer)[:110])
        pdf.setFillColorRGB(0, 0, 0)
        pdf.showPage()

        header(title, f"Verso — planche {sheet_index}")
        for offset, card in enumerate(chunk):
            column = offset % COLUMNS
            row = offset // COLUMNS
            # Mirrored columns so a duplex print lines the backs up with the fronts.
            mirrored = COLUMNS - 1 - column
            x = MARGIN + mirrored * (cell_w + GUTTER)
            y = page_h - MARGIN - 18 * mm - (row + 1) * cell_h - row * GUTTER
            _draw_cell(
                pdf,
                x=x,
                y=y,
                width=cell_w,
                height=cell_h,
                text=str(card.get("back") or ""),
                body=body,
                bold=bold,
                image=str(card["back_image_path"]) if card.get("back_image_path") else None,
                number=None,
            )
        pdf.setFont(body, 7)
        pdf.setFillColorRGB(0.45, 0.45, 0.5)
        pdf.drawString(MARGIN, MARGIN - 4 * mm, _sanitize(footer)[:110])
        pdf.setFillColorRGB(0, 0, 0)
        pdf.showPage()

    pdf.save()
    return buffer.getvalue()


def card_back_text(card) -> str:
    """The verso as plain text, for the HTML preview and the PDF alike."""
    return plain(card.back_md or "")
