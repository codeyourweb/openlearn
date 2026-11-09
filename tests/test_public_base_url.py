# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The public address quoted in outgoing mail must be reachable by its reader."""

from __future__ import annotations

import logging

import pytest

from app.config import public_base_url_problem


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://openlearnproject.org",
        "https://openlearnproject.org/",
        "https://learn.example.edu:8443",
        "https://2001:db8::1",
    ],
)
def test_a_reachable_value_is_accepted(value: str) -> None:
    # An empty value means "derive it from the request", which is always usable.
    assert public_base_url_problem(value) is None


def test_a_plain_http_address_is_reported() -> None:
    problem = public_base_url_problem("http://openlearnproject.org")
    assert problem and "plain http" in problem


def test_a_loopback_address_is_reported() -> None:
    problem = public_base_url_problem("https://localhost:8000")
    assert problem and "only this machine" in problem


def test_a_private_address_is_reported() -> None:
    problem = public_base_url_problem("https://10.0.0.4")
    assert problem and "private address" in problem


def test_a_hostname_without_scheme_is_reported() -> None:
    problem = public_base_url_problem("openlearnproject.org")
    assert problem and "scheme" in problem


def test_the_problem_is_logged_at_startup(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from app import main
    from app.config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://frhb104957ds.example.net:17230")
    with caplog.at_level(logging.INFO, logger="openlearn"):
        # The warning is emitted once, at startup, before the app serves.
        main.warn_about_unreachable_public_base()
    assert any("Public links will use" in record.message for record in caplog.records)
