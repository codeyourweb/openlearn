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
from collections import Counter
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


IMPORT_STATEMENT = re.compile(
    r"""^\s*import\s+(?P<clause>[\w$\s{},*]+?)\s*from\s*["'](?P<module>[^"']+)["']""",
    re.MULTILINE,
)


def imported_bindings(source: str) -> list[str]:
    """The names a module binds from its imports, `a as b` counting only as `b`."""
    names: list[str] = []
    for match in IMPORT_STATEMENT.finditer(source):
        for part in match.group("clause").split(","):
            part = part.strip().strip("{}").strip()
            if not part or part == "*":
                continue
            if part.startswith("* as "):
                names.append(part[5:].strip())
            elif " as " in part:
                names.append(part.split(" as ", 1)[1].strip())
            else:
                names.append(part)
    return [name for name in names if name]


def test_no_module_imports_the_same_binding_twice():
    """The browser refuses such a module, and nothing else in the toolchain does.

    `node --check` parses the file and stops there: it accepts two statements
    importing the same name, which the browser rejects at load time with
    "Identifier 't' has already been declared" -- the application then stays
    blank, with a message that names no file. It happens when an import block is
    edited next to an older list, so it is worth a test.
    """
    offenders = {}
    for path in modules():
        counters = Counter(imported_bindings(path.read_text(encoding="utf-8")))
        duplicates = {name: count for name, count in counters.items() if count > 1}
        if duplicates:
            offenders[str(path.relative_to(JS_ROOT))] = duplicates
    assert not offenders, (
        "A module imports the same name twice: the browser refuses the file and "
        f"the application never starts. {offenders}"
    )


def test_relative_imports_point_at_a_module_that_exists():
    """A misspelt import is a 404 the page only notices at runtime."""
    missing = []
    for path in modules():
        source = path.read_text(encoding="utf-8")
        for match in IMPORT_STATEMENT.finditer(source):
            module = match.group("module")
            if not module.startswith("."):
                continue
            if not (path.parent / module).resolve().exists():
                missing.append(f"{path.relative_to(JS_ROOT)} -> {module}")
    assert not missing, f"Imports that resolve to nothing: {missing}"


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


def test_a_module_that_calls_the_api_imports_the_client():
    """`account.js` called `api.get` without importing `api`.

    Nothing failed at load time: the page rendered, and only the history and
    API-key sections -- painted on demand -- replaced themselves with "Something
    went wrong", which is what a teacher saw. The module still has to be told
    where the client comes from.
    """
    call = re.compile(r"\bapi\.(?:get|post|put|patch|del|getMeta|request)\b")
    offenders = []
    for path in modules():
        if path.name == "api.js":
            continue
        source = path.read_text(encoding="utf-8")
        if call.search(source) and "api" not in bound_names(source):
            offenders.append(str(path.relative_to(JS_ROOT)))
    assert not offenders, (
        "These modules call the API client without importing it, so the call "
        f"throws ReferenceError the first time it runs: {offenders}"
    )
