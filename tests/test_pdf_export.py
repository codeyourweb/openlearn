# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""PDF export: one page, and a whole wiki with its menu kept."""

from __future__ import annotations

import io

from pypdf import PdfReader

from conftest import csrf_headers, register_user


def _wiki(client, title="Réseau et DNS") -> dict:
    response = client.post(
        "/api/v1/wiki",
        json={"title": title, "description": "Tout ce qu'il faut savoir sur le DNS."},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _page(client, wiki_id: int, title: str, content: str, parent_id: int | None = None) -> dict:
    body = {"title": title, "content_md": content}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = client.post(f"/api/v1/wiki/{wiki_id}/pages", json=body, headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    return response.json()


def _text(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_a_page_exports_as_pdf_with_its_formatting(client):
    register_user(client)
    wiki = _wiki(client)
    page = _page(
        client,
        wiki["id"],
        "Résolution",
        "# Résolution\n\nLe résolveur **cache** les réponses.\n\n- premier point\n- second point\n\n"
        "```\nresolveur: 192.0.2.53\n```",
    )
    response = client.get(f"/api/v1/wiki/pages/{page['id']}/export.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    text = _text(response.content)
    assert "Résolution" in text
    assert "premier point" in text and "second point" in text
    assert "resolveur: 192.0.2.53" in text


def test_a_whole_wiki_exports_with_a_table_of_contents_in_menu_order(client):
    register_user(client)
    wiki = _wiki(client)
    parent = _page(client, wiki["id"], "Bases", "# Bases\n\nLe DNS traduit des noms.")
    _page(client, wiki["id"], "Cache", "# Cache\n\nUne réponse gardée.", parent_id=parent["id"])

    response = client.get(f"/api/v1/wiki/{wiki['id']}/export.pdf?lang=fr")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")

    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) >= 2
    text = _text(response.content)
    assert "Sommaire" in text
    assert "Bases" in text and "Cache" in text
    # The parent comes before the page that hangs under it.
    assert text.index("Bases") < text.index("Cache")


def test_a_broken_image_never_breaks_the_export(client):
    register_user(client)
    wiki = _wiki(client)
    page = _page(client, wiki["id"], "Illustration", "# Illustration\n\n![schéma](/media/absent.png)\n")
    response = client.get(f"/api/v1/wiki/pages/{page['id']}/export.pdf")
    assert response.status_code == 200, response.text
    assert "schéma" in _text(response.content)


def test_exporting_a_private_wiki_requires_access(client):
    register_user(client, "owner@example.com")
    wiki = _wiki(client, title="Notes privées")
    client.cookies.clear()
    response = client.get(f"/api/v1/wiki/{wiki['id']}/export.pdf")
    assert response.status_code in (401, 403, 404)


def test_a_page_starting_with_a_deep_heading_still_exports(client):
    """A PDF outline cannot jump from level 0 to level 2: the export flattens it."""
    register_user(client)
    wiki = _wiki(client, title="Plan de cours")
    page = _page(client, wiki["id"], "Objectifs", "# Objectifs\n\n### Détail sans sous-titre\n\nTexte.")
    single = client.get(f"/api/v1/wiki/pages/{page['id']}/export.pdf")
    assert single.status_code == 200, single.text
    whole = client.get(f"/api/v1/wiki/{wiki['id']}/export.pdf")
    assert whole.status_code == 200, whole.text
    assert "Détail sans sous-titre" in _text(whole.content)


def test_an_emoji_in_a_title_neither_breaks_nor_duplicates_the_export(client):
    """ReportLab draws a missing glyph as an empty square; the export drops it."""
    register_user(client)
    wiki = _wiki(client, title="Sentinel 🛡️")
    _page(client, wiki["id"], "🛡️ Sentinel Kit", "🛡️ Sentinel Kit\n\nLe SOC et le DFIR.")
    response = client.get(f"/api/v1/wiki/{wiki['id']}/export.pdf")
    assert response.status_code == 200, response.text
    text = _text(response.content)
    assert "Sentinel Kit" in text
    assert "\ufffd" not in text
    assert text.count("Sentinel Kit") >= 1
