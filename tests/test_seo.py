# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Crawlable metadata: the shell, the sitemap and robots.txt.

Search engines and chat previews read the first HTML response, not the SPA that
runs afterwards. These tests keep that response honest: a public document is
described, a private one is not, and both stay reachable.
"""

from __future__ import annotations

import re

from tests.conftest import (
    create_quiz,
    make_trusted,
    publish_quiz,
    quiz_payload,
    register_user,
    csrf_headers,
)


def _meta(html: str, name: str) -> str | None:
    match = re.search(rf'<meta (?:property|name)="{re.escape(name)}" content="([^"]*)"', html)
    return match.group(1) if match else None


def _canonical(html: str) -> str | None:
    match = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    return match.group(1) if match else None


def test_robots_points_at_the_sitemap(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    body = response.text
    assert "Sitemap: http://testserver/sitemap.xml" in body
    assert "Disallow: /admin" in body


def test_the_sitemap_is_well_formed_and_lists_the_catalogue(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<url><loc>http://testserver/quizzes</loc>" in response.text
    assert response.text.rstrip().endswith("</urlset>")


def test_a_public_quiz_is_described_in_the_first_response(client):
    register_user(client, email="seo@example.com")
    make_trusted(client)
    quiz = create_quiz(client, quiz_payload(title="The water cycle, explained"))
    publish_quiz(client, quiz["id"])

    response = client.get(f"/quizzes/{quiz['id']}/the-water-cycle-explained")
    assert response.status_code == 200
    html = response.text
    assert "<title>The water cycle, explained — a quiz on OpenLearn</title>" in html
    assert _meta(html, "og:title")
    assert _canonical(html) == f"http://testserver/quizzes/{quiz['id']}/the-water-cycle-explained"
    assert '"@type":"Quiz"' in html
    assert '"isAccessibleForFree":true' in html

    sitemap = client.get("/sitemap.xml").text
    assert f"/quizzes/{quiz['id']}/the-water-cycle-explained" in sitemap


def test_a_private_quiz_keeps_its_title_out_of_the_head(client):
    register_user(client, email="private-seo@example.com")
    quiz = create_quiz(client, quiz_payload(title="Internal onboarding check"))

    response = client.get(f"/quizzes/{quiz['id']}/internal-onboarding-check")
    assert response.status_code == 200
    html = response.text
    assert "Internal onboarding check" not in html.split("<body")[0]
    assert "Internal onboarding check" not in client.get("/sitemap.xml").text


def test_a_wiki_page_is_described_with_its_wiki(client):
    register_user(client, email="wikiseo@example.com")
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Marine biology", "description": "Life in the sea", "visibility": "public"},
        headers=csrf_headers(client),
    )
    assert wiki.status_code == 201, wiki.text
    wiki_id = wiki.json()["id"]
    page = client.post(
        f"/api/v1/wiki/{wiki_id}/pages",
        json={"title": "Coral reefs", "content_md": "Corals build reefs in warm shallow water."},
        headers=csrf_headers(client),
    )
    assert page.status_code == 201, page.text
    # A draft wiki has no public page: publish it before asking about the meta.
    make_trusted(client)
    published = client.post(
        f"/api/v1/wiki/{wiki_id}/publish", json={"public": True}, headers=csrf_headers(client)
    )
    assert published.status_code == 200, published.text

    response = client.get(f"/wiki/{wiki_id}/p/{page.json()['slug']}")
    assert response.status_code == 200
    html = response.text
    assert "Coral reefs — Marine biology" in html
    assert _canonical(html) == f"http://testserver/wiki/{wiki_id}/p/{page.json()['slug']}"
    assert '"@type":"Article"' in html
