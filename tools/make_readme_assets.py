#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER <dev.jp.garnier@gmail.com>
"""Regenerate the two images at the top of the README.

    python tools/make_readme_assets.py --base-url http://127.0.0.1:8000

It captures four screens of a running instance, renders `tools/readme/banner.html`
to `docs/assets/img/readme-banner.png`, and assembles `docs/assets/img/readme-demo.gif`.

The screens are public pages, read without an account: the home page, the
catalogue, a quiz in French and the same quiz in German. Nothing is written.

Needs Playwright (chromium) and Pillow, both development-only. If Manrope is
installed or passed with --font-dir, the banner is set in it; otherwise the
system sans-serif is used and the layout is unchanged.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANNER_HTML = ROOT / "tools/readme/banner.html"
IMAGES = ROOT / "docs/assets/img"

FRAMES = [
    ("home", "/", "fr", "One place: a shared wiki, quizzes, review cards and branching stories", None),
    ("catalogue", "/quizzes", "fr", "Quizzes filtered by subject, by language and by mode", None),
    ("quiz", "/quizzes/{quiz}", "fr", "Play alone, host a live session, or build review cards", None),
    ("quiz_de", "/quizzes/{quiz}", "de", "Switch language mid-question — the question follows", "#language-button"),
]
WIDTH, HEIGHT, BAR = 1000, 625, 54


def font_faces(font_dir: pathlib.Path | None) -> str:
    """Build the @font-face block, or nothing when no font directory is given."""
    if not font_dir:
        return ""
    families = {400: "Regular", 600: "SemiBold", 800: "ExtraBold"}
    rules = []
    for weight, style in families.items():
        path = next(iter(sorted(font_dir.glob(f"*{style}.ttf"))), None) or next(
            iter(sorted(font_dir.glob(f"*-{weight}.ttf"))), None
        )
        if path:
            rules.append(
                f"@font-face {{ font-family: Manrope; font-weight: {weight};"
                f" src: url('{path.as_uri()}'); }}"
            )
    return "\n  ".join(rules)


def pick_quiz(base_url: str) -> int:
    with urllib.request.urlopen(f"{base_url}/api/v1/quizzes?lang=fr&limit=50", timeout=30) as answer:
        payload = json.load(answer)
    rows = payload["items"] if isinstance(payload, dict) else payload
    chosen = rows[0] if rows else None
    if chosen is None:
        raise SystemExit("no public quiz to photograph — publish one first")
    return int(chosen["id"])


def capture(base_url: str, quiz_id: int, workdir: pathlib.Path) -> dict[str, dict]:
    boxes: dict[str, dict] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for stem, path, language, _, highlight in FRAMES:
            context = browser.new_context(
                locale="fr-FR" if language == "fr" else "de-DE",
                viewport={"width": 1440, "height": 900},
                device_scale_factor=2,
            )
            context.add_init_script(f"localStorage.setItem('ol_language','{language}')")
            page = context.new_page()
            page.goto(base_url + path.format(quiz=quiz_id), wait_until="networkidle")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(workdir / f"{stem}.png"))
            if highlight:
                element = page.query_selector(highlight)
                if element:
                    boxes[f"{stem}:{highlight}"] = element.bounding_box()
            context.close()
        browser.close()
    return boxes


def banner(workdir: pathlib.Path, font_dir: pathlib.Path | None) -> pathlib.Path:
    html = BANNER_HTML.read_text(encoding="utf-8").replace("__FONT_FACES__", font_faces(font_dir))
    page_html = workdir / "banner.html"
    page_html.write_text(html, encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 260}, device_scale_factor=2)
        page.goto(page_html.as_uri())
        page.wait_for_timeout(500)
        page.screenshot(path=str(workdir / "readme-banner.png"))
        browser.close()
    return workdir / "readme-banner.png"


def assemble(workdir: pathlib.Path, boxes: dict[str, dict], font_dir: pathlib.Path | None) -> pathlib.Path:
    regular = next(iter(sorted(font_dir.glob("*.ttf"))), None) if font_dir else None
    caption_font = ImageFont.truetype(str(regular), 19) if regular else ImageFont.load_default()
    brand_font = ImageFont.truetype(str(regular), 19) if regular else ImageFont.load_default()
    scale = WIDTH / 1440
    frames = []
    for stem, _, _, caption, highlight in FRAMES:
        crop = Image.open(workdir / f"{stem}.png").convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
        canvas = Image.new("RGB", (WIDTH, HEIGHT + BAR), "#0a0e1a")
        canvas.paste(crop, (0, BAR))
        draw = ImageDraw.Draw(canvas)
        draw.text((18, 16), "OpenLearn", font=brand_font, fill="#f4f6fb")
        draw.text((WIDTH - 18 - draw.textlength(caption, font=caption_font), 17), caption,
                  font=caption_font, fill="#9aa8c8")
        draw.rectangle([0, BAR - 2, WIDTH, BAR], fill="#1b2338")
        box = boxes.get(f"{stem}:{highlight}") if highlight else None
        if box:
            draw.rounded_rectangle(
                [(box["x"] - 6) * scale, BAR + (box["y"] - 6) * scale,
                 (box["x"] + box["width"] + 6) * scale, BAR + (box["y"] + box["height"] + 6) * scale],
                radius=9, outline="#8b5cf6", width=3,
            )
        frames.append(canvas)
    quantized = [frame.quantize(colors=200, method=Image.MEDIANCUT) for frame in frames]
    out = workdir / "readme-demo.gif"
    quantized[0].save(out, save_all=True, append_images=quantized[1:],
                      duration=[2600, 2600, 2600, 3600], loop=0, optimize=True, disposal=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--font-dir", type=pathlib.Path, default=None,
                        help="directory holding Manrope-400/600/800.ttf")
    arguments = parser.parse_args()

    IMAGES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="readme-assets-") as temporary:
        workdir = pathlib.Path(temporary)
        boxes = capture(arguments.base_url.rstrip("/"), pick_quiz(arguments.base_url.rstrip("/")), workdir)
        # copyfile, not replace: the temporary directory may sit on another mount.
        shutil.copyfile(banner(workdir, arguments.font_dir), IMAGES / "readme-banner.png")
        shutil.copyfile(assemble(workdir, boxes, arguments.font_dir), IMAGES / "readme-demo.gif")
    for name in ("readme-banner.png", "readme-demo.gif"):
        print(f"{name}: {(IMAGES / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
