# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The read-only environment page must point at documentation that exists.

An operator who reads a variable name and follows its link must land on the
heading that explains it: a dead anchor is worse than no link, because it looks
like the answer is one click away.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
from conftest import csrf_headers, make_admin, register_user

from app.config import Settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ENVIRONMENT.md"

if not DOC.exists():  # pragma: no cover - a broken test image, not a broken app
    raise RuntimeError(
        f"{DOC} is missing: the test image copies backend, frontend, tests, demo and "
        "tools but must also copy docs (see COPY docs in Dockerfile.test)."
    )


@pytest.fixture()
def admin(client):
    register_user(client, "env@example.com", display_name="Env")
    make_admin(client)
    return client


def test_every_setting_has_a_heading_in_the_documentation():
    text = DOC.read_text()
    missing = [name for name in Settings.model_fields if f"### OL_{name.upper()}\n" not in text]
    assert missing == [], f"undocumented settings: {missing}"


def test_the_documentation_is_generated_from_the_current_settings():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "env_docs.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_administration_links_each_heading_github_actually_creates(admin):
    """GitHub turns ``### OL_SECRET_KEY`` into ``#ol_secret_key``: underscores kept."""
    body = admin.get("/api/v1/admin/environment").json()
    assert body["items"], "the page would be empty"
    text = DOC.read_text()
    for row in body["items"]:
        assert row["env"] == f"OL_{row['name'].upper()}"
        assert row["doc"].endswith(f"#ol_{row['name'].lower()}"), row
        assert f"### {row['env']}\n" in text


def test_a_secret_is_never_printed_only_declared_as_set(admin):
    rows = {row["name"]: row for row in admin.get("/api/v1/admin/environment").json()["items"]}
    secret = rows["secret_key"]
    assert secret["secret"] is True
    assert secret["value"] in ("", "set")


def test_a_visitor_cannot_read_the_environment(client):
    assert client.get("/api/v1/admin/environment").status_code in (401, 403)


def test_the_environment_is_read_only(client, admin):
    """There is no write route: the page documents, the settings page configures."""
    response = admin.put(
        "/api/v1/admin/environment", json={"values": {}}, headers=csrf_headers(client)
    )
    assert response.status_code in (404, 405)
