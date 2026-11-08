# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The test image and the test requirements must describe the same toolchain.

The end-to-end suite runs from `Dockerfile.test`, whose base image ships the
browser binaries, while the version that *drives* them comes from
`requirements-dev.txt`. Raising one without the other is invisible until the whole
browser job fails at `BrowserType.launch`, with a path nobody reads:

    Executable doesn't exist at /ms-playwright/chromium_headless_shell-1248/...

Comparing the two versions here turns a 20-minute CI run into a failing unit test.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pinned(requirements: str, package: str) -> str | None:
    match = re.search(rf"^{package}==([\w.]+)$", requirements, re.MULTILINE | re.IGNORECASE)
    return match.group(1) if match else None


def test_the_playwright_image_and_package_are_the_same_version():
    dockerfile = (ROOT / "Dockerfile.test").read_text(encoding="utf-8")
    image = re.search(r"mcr\.microsoft\.com/playwright/python:v([\w.]+)-", dockerfile)
    assert image, "Dockerfile.test no longer starts from an official Playwright image"

    requirements = (ROOT / "backend" / "requirements-dev.txt").read_text(encoding="utf-8")
    package = _pinned(requirements, "playwright")
    assert package, "requirements-dev.txt no longer pins playwright"

    assert image.group(1) == package, (
        "The Playwright image ships browsers for its own version: "
        f"image {image.group(1)} against package {package} fails every browser "
        "test with \"Executable doesn't exist\"."
    )


def test_the_application_image_python_matches_what_ci_runs():
    """`ruff` in CI and `python` in the image should describe the same language."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    found = re.search(r"^FROM\s+python:(\d+)\.(\d+)", dockerfile, re.MULTILINE)
    assert found, "Dockerfile no longer starts from an official python image"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    target = re.search(r'target-version\s*=\s*"py(\d)(\d+)"', pyproject)
    assert target, "pyproject.toml no longer declares a ruff target-version"
    assert (found.group(1), found.group(2)) == (target.group(1), target.group(2)), (
        "The image and the lint target disagree about the Python version, so a "
        "syntax the image accepts can pass lint on a newer interpreter."
    )
