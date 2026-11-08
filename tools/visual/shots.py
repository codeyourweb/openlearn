#!/usr/bin/env python3
"""Capture the read paths and compare them with a reference run.

The accessibility work must not move anything for people who do not need it.
A screenshot diff is the only way to say "nothing changed" instead of "I did not
see anything change", so this script takes a fixed set of views at two widths in
both themes, then reports every differing region of a later run.

    python tools/visual/shots.py --base-url http://172.18.0.19:8000 --out .shots/ref
    python tools/visual/shots.py --base-url http://172.18.0.19:8000 \
        --out .shots/after --compare .shots/ref

Run it against a *seeded private* instance: the demo catalogue is deterministic,
whereas a live instance drifts as people add content.

Requires playwright (installed in `open-quizz-tests:latest`) and Pillow for the
comparison step.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

VIEWS = [
    ("home", "/"),
    ("catalogue", "/quizzes"),
    ("wiki", "/wiki"),
    ("about", "/about"),
    ("legal", "/legal"),
    ("api", "/docs"),
    ("mcp", "/docs/mcp"),
    ("login", "/login"),
    ("register", "/register"),
]

WIDTHS = {"desktop": (1440, 900), "phone": (390, 844)}
THEMES = ("dark", "light")

# Freeze what would otherwise differ between two runs of the same code.
FREEZE = """
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
  html { scroll-behavior: auto !important; }
"""


def capture(base_url: str, out: pathlib.Path) -> dict:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    manifest = {"base_url": base_url, "shots": []}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        # Reduced motion: the interface already honours it, so the animated
        # rotator and the studio hold a stable frame instead of a random one.
        # bypass_csp: the instance sends `style-src 'self'`, which refuses the
        # injected freeze stylesheet. This is a measurement run, not a visit.
        context = browser.new_context(
            reduced_motion="reduce", device_scale_factor=1, bypass_csp=True
        )
        page = context.new_page()

        def settle() -> None:
            page.wait_for_load_state("networkidle")
            page.add_style_tag(content=FREEZE)
            page.wait_for_timeout(350)

        # Content ids come from the instance, so the same view is captured.
        meta = page.request.get(f"{base_url}/api/v1/meta").json()
        manifest["meta"] = {"name": meta.get("name"), "languages": len(meta.get("languages", []))}
        def first(path: str) -> dict | None:
            payload = page.request.get(f"{base_url}{path}").json()
            # Some listings answer a bare array, others a page object.
            items = payload if isinstance(payload, list) else payload.get("items") or []
            return items[0] if items else None

        extra = []
        quiz = first("/api/v1/quizzes?limit=1")
        if quiz:
            extra.append(("quiz", f"/quizzes/{quiz['id']}"))
        wiki = first("/api/v1/wiki?limit=1")
        if wiki:
            extra.append(("wiki-page", f"/wiki/{wiki['id']}/{wiki.get('slug') or 'wiki'}"))

        for theme in THEMES:
            for width_name, (width, height) in WIDTHS.items():
                page.set_viewport_size({"width": width, "height": height})
                page.goto(f"{base_url}/", wait_until="domcontentloaded")
                page.evaluate(
                    """([theme]) => {
                      localStorage.setItem('ol_theme', theme);
                      localStorage.setItem('ol_language', 'fr');
                    }""",
                    [theme],
                )
                for name, path in VIEWS + extra:
                    page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
                    settle()
                    file = out / f"{name}-{theme}-{width_name}.png"
                    page.screenshot(path=str(file), full_page=True)
                    manifest["shots"].append(
                        {"name": name, "path": path, "theme": theme, "width": width_name, "file": file.name}
                    )
                    print(f"  {file.name}")

        browser.close()

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def compare(reference: pathlib.Path, candidate: pathlib.Path, report: pathlib.Path) -> int:
    from PIL import Image, ImageChops

    report.mkdir(parents=True, exist_ok=True)
    ref = json.loads((reference / "manifest.json").read_text(encoding="utf-8"))
    new = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    old_files = {shot["file"] for shot in ref["shots"]}
    new_files = {shot["file"] for shot in new["shots"]}

    missing = sorted(old_files - new_files)
    added = sorted(new_files - old_files)
    if missing:
        print(f"missing shots: {', '.join(missing)}")

    changed = 0
    rows = []
    for shot in new["shots"]:
        name = shot["file"]
        if name not in old_files:
            continue
        left = Image.open(reference / name).convert("RGB")
        right = Image.open(candidate / name).convert("RGB")
        if left.size != right.size:
            rows.append((name, "size", f"{left.size} -> {right.size}", 100.0))
            changed += 1
            continue
        diff = ImageChops.difference(left, right)
        box = diff.getbbox()
        if box is None:
            continue
        # A couple of pixels of antialiasing is noise; a real change covers area.
        changed_px = sum(1 for pixel in diff.getdata() if max(pixel) > 12)
        share = 100.0 * changed_px / (left.size[0] * left.size[1])
        diff.convert("L").point(lambda value: 255 if value > 12 else 0).save(report / name)
        rows.append((name, "pixels", f"{box[2] - box[0]}x{box[3] - box[1]} at {box[0]},{box[1]}", share))
        changed += 1

    rows.sort(key=lambda row: -row[3])
    for name, kind, detail, share in rows:
        print(f"  {name:34s} {share:6.3f}%  {detail}")

    print(f"\n{changed} view(s) differ, {len(missing)} gone, {len(added)} new")
    print(f"diff images: {report}")
    return 1 if changed or missing else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=".shots/latest")
    parser.add_argument("--compare", default=None, help="reference directory")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    capture(args.base_url, out)
    if not args.compare:
        return 0
    return compare(pathlib.Path(args.compare), out, pathlib.Path(".shots/diff"))


if __name__ == "__main__":
    sys.exit(main())
