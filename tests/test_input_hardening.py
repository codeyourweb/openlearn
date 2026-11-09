# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Regressions for what the code-scanning pass reported.

Each test pins a property that a future refactor could quietly lose: a cookie
value is never echoed back, a page body cannot make the renderer work for
minutes, and a failed discovery keeps its transport detail in the log.
"""

from __future__ import annotations

import re
import time

import pytest

from app import wiki
from app.db import SessionLocal
from app.models import SsoProvider

CSRF_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,64}")


def test_a_forged_csrf_cookie_is_replaced_rather_than_echoed(client):
    forged = 'value"; Domain=attacker.example; Path=/'
    client.cookies.set("ol_csrf", forged)

    response = client.get("/api/v1/auth/csrf")

    token = response.json()["csrf_token"]
    assert token != forged
    assert CSRF_SHAPE.fullmatch(token)
    assert "attacker.example" not in response.headers.get("set-cookie", "")


def test_a_well_formed_csrf_cookie_is_kept(client):
    token = "a" * 32
    client.cookies.set("ol_csrf", token)

    response = client.get("/api/v1/auth/csrf")

    assert response.json()["csrf_token"] == token
    assert "set-cookie" not in {key.lower() for key in response.headers}


@pytest.mark.parametrize(
    "unit, count",
    [
        ("![", 60_000),
        ("[[", 60_000),
        ("[a](", 60_000),
        ("#", 200_000),
        ("# " + " " * 40, 5_000),
    ],
)
def test_a_hostile_page_body_is_parsed_in_linear_time(unit, count):
    """Every gap in these patterns is bounded, so the cost grows with the input.

    Wall time alone says nothing on a shared runner: a slow machine makes a
    linear parser look quadratic. What distinguishes the two is the *growth*
    — four times the input costs about four times the work, not sixteen.
    """

    def cost(repeats: int) -> tuple[float, list, str]:
        body = unit * repeats
        started = time.perf_counter()
        outlined = wiki.outline(body)
        summarized = wiki.excerpt(body, limit=180)
        return time.perf_counter() - started, outlined, summarized

    small, _, _ = cost(count // 4)
    large, outlined, summarized = cost(count)

    assert large < 15.0, f"took {large:.1f}s on {len(unit) * count} characters"
    assert large <= max(small, 0.02) * 9, (
        f"cost grew from {small:.2f}s to {large:.2f}s when the body quadrupled "
        f"({len(unit) * count} characters): that is closer to quadratic than linear"
    )
    assert isinstance(outlined, list)
    assert len(summarized) <= 181


def test_outline_still_reads_headings_the_way_markdown_does():
    page = "\n".join(
        [
            "# The title repeats the page name",
            "## Getting started",
            "### `dns` and **routing**",
            "#### Deep",
            "##### Too deep",
            "#hashtag is not a heading",
            "## ",
        ]
    )

    items = wiki.outline(page)

    assert [item["depth"] for item in items] == [2, 3, 4]
    assert items[1]["text"] == "dns and routing"
    assert items[1]["anchor"] == "dns-and-routing"


def test_excerpt_still_removes_images_links_and_wikilinks():
    page = "Le **DNS** du [[relais|relais]] reste ![une image](/media/x.webp){width=320} puis [un lien](https://example.org)."

    summary = wiki.excerpt(page)

    assert "une image" not in summary
    assert "un lien" in summary
    assert "relais" in summary
    assert "https://example.org" not in summary


def test_a_failed_discovery_does_not_quote_the_provider_url(client, monkeypatch):
    with SessionLocal() as session:
        session.add(
            SsoProvider(
                slug="idp",
                label="Internal IdP",
                kind="oidc",
                issuer="https://idp.internal.example",
                client_id="openlearn",
            )
        )
        session.commit()

    from app.routers import sso_auth

    def unreachable(provider):  # noqa: ARG001
        raise sso_auth.sso.SsoError(
            "Provider discovery failed: http://10.1.2.3/.well-known/openid-configuration"
        )

    monkeypatch.setattr(sso_auth.sso, "discovery", unreachable)

    response = client.get("/api/v1/auth/sso/idp/ping")

    assert response.status_code == 200
    assert response.json() == {"kind": "oidc", "ready": False, "detail": "Discovery failed."}
    assert "10.1.2.3" not in response.text
