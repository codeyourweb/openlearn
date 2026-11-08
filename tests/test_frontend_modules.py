# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Static checks on the browser modules.

A missing named import does not fail the build: the module loads, the page
renders, and the handler that needs the helper dies at click time with
"X is not defined". That is exactly how the story editor lost its delete
confirmation while every other screen kept working, so the imports are checked
here rather than discovered by a 30-second Playwright timeout.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

JS_ROOT = Path(__file__).resolve().parents[1] / "frontend" / "js"

# Helpers that live in a shared module: calling one without importing it is a
# runtime error waiting for a click.
SHARED = {
    "ui.js": {
        "confirmDialog",
        "copyToClipboard",
        "escapeHtml",
        "showBusyOverlay",
        "showUploadProgress",
        "toast",
    },
    "i18n.js": {"currentLanguage", "setLanguage", "t", "tp"},
    "router.js": {"navigate"},
}


def modules() -> list[Path]:
    return sorted(JS_ROOT.rglob("*.js"))


def bound_names(source: str) -> set[str]:
    """Everything the module can call by name: imports, declarations, parameters."""
    names: set[str] = set()
    for match in re.finditer(r'import\s*\{([^}]+)\}\s*from\s*"[^"]+"', source):
        names |= {part.strip().split(" as ")[-1].strip() for part in match.group(1).split(",")}
    names |= set(re.findall(r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", source))
    for match in re.finditer(r"function\s+[\w$]*\s*\(([^)]*)\)", source):
        names |= {part.strip().split("=")[0].strip() for part in match.group(1).split(",") if part.strip()}
    for match in re.finditer(r"\(([^)]*)\)\s*=>", source):
        names |= {part.strip().split("=")[0].strip() for part in match.group(1).split(",") if part.strip()}
    return names


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_every_shared_helper_is_defined_or_imported(path: Path):
    source = path.read_text(encoding="utf-8")
    available = bound_names(source)
    for owner, helpers in SHARED.items():
        if path.name == owner:
            continue
        used = {helper for helper in helpers if re.search(rf"(?<![\w.]){helper}\(", source)}
        missing = used - available
        assert not missing, f"{path.name} calls {sorted(missing)} without importing it"


def test_pages_never_build_markup_with_css_text():
    """The CSP forbids inline styles, so the UI must go through the CSSOM."""
    offenders = [
        path.name
        for path in modules()
        if re.search(r'\.style\.cssText\s*=\s*"', path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


def test_html_carries_no_inline_style_or_script():
    html = (JS_ROOT.parent / "index.html").read_text(encoding="utf-8")
    assert "<style" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\sstyle=\"", html)
