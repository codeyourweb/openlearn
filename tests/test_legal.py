# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Legal notices: the instance addition, its rendering and its guards."""

from __future__ import annotations

import pytest

from app import ai, legal
from tests.conftest import csrf_headers, make_admin, make_moderator, register_user

NOTICE = """## Éditeur

Ce site est publié par **Association Exemple**, 12 rue du Test, 35000 Rennes.

- Directeur de la publication : Camille Exemple
- Contact : contact@example.org
"""


def test_a_fresh_instance_publishes_no_addition(client):
    response = client.get("/api/v1/legal?lang=fr")
    assert response.status_code == 200
    body = response.json()
    assert body["has_notice"] is False
    assert body["html"] == ""
    assert set(body["languages"]) == set(legal.SUPPORTED_LANGUAGES)
    assert not any(body["languages"].values())


def test_an_administrator_stores_a_notice_and_the_public_page_gets_html(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    saved = client.put("/api/v1/admin/legal", json={"values": {"fr": NOTICE}}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] == ["fr"]

    public = client.get("/api/v1/legal?lang=fr").json()
    assert public["has_notice"] is True
    assert "<h2>" in public["html"] and "<li>" in public["html"]
    assert "Association Exemple" in public["html"]
    assert public["markdown"].strip().startswith("## Éditeur")


def test_script_and_event_handlers_never_reach_the_page(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    hostile = (
        "## Titre\n\n"
        "<script>alert(1)</script>\n\n"
        '<img src=x onerror="alert(2)">\n\n'
        '<a href="javascript:alert(3)">lien</a>\n\n'
        "Texte normal.\n"
    )
    assert client.put("/api/v1/admin/legal", json={"values": {"en": hostile}}, headers=headers).status_code == 200
    html = client.get("/api/v1/legal?lang=en").json()["html"]
    # No element the browser would build, and no attribute it would honour.
    assert "<script" not in html
    assert "<img" not in html
    assert "<a " not in html
    # Everything that looked like markup arrived as text, tag and handler
    # included, so nothing in it can be clicked or executed.
    assert "&lt;img src=x onerror=" in html
    assert '&lt;a href="javascript:alert(3)"&gt;' in html
    # The prose survives; only the executable part is gone. What looked like
    # markup reaches the page as text, which is the point.
    assert "Texte normal." in html
    assert "&lt;a href=" in html


def test_the_stored_notice_keeps_natural_paragraphs(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    wrapped = "## Titre\n\nUne phrase\ncoupée\ntous les trois mots.\n\nSecond paragraphe.\n"
    assert client.put("/api/v1/admin/legal", json={"values": {"en": wrapped}}, headers=headers).status_code == 200
    stored = client.get("/api/v1/admin/legal").json()["values"]["en"]
    assert "Une phrase\ncoupée" not in stored
    assert "Une phrase coupée tous les trois mots." in stored


def test_only_an_administrator_may_write_it(client):
    register_user(client)
    headers = csrf_headers(client)
    # A moderator validates content; the instance's legal pages are not content.
    make_moderator(client)
    headers = csrf_headers(client)
    assert client.put("/api/v1/admin/legal", json={"values": {"fr": NOTICE}}, headers=headers).status_code == 403
    assert client.get("/api/v1/admin/legal").status_code == 403
    assert client.post("/api/v1/admin/legal/translate", json={"target": "en", "text": "x"}, headers=headers).status_code == 403


def test_an_unknown_language_is_refused(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    response = client.put("/api/v1/admin/legal", json={"values": {"xx": NOTICE}}, headers=headers)
    assert response.status_code == 422
    assert "xx" in response.json()["detail"]


def test_a_notice_that_is_too_long_is_refused(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    response = client.put(
        "/api/v1/admin/legal",
        json={"values": {"fr": "a " * (legal.MAX_LENGTH // 2 + 10)}},
        headers=headers,
    )
    assert response.status_code == 422
    assert "too long" in response.json()["detail"]


def test_an_empty_value_clears_the_notice(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    client.put("/api/v1/admin/legal", json={"values": {"fr": NOTICE}}, headers=headers)
    assert client.put("/api/v1/admin/legal", json={"values": {"fr": ""}}, headers=headers).status_code == 200
    assert client.get("/api/v1/legal?lang=fr").json()["has_notice"] is False


def test_a_language_nobody_filled_in_falls_back_to_english(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    client.put("/api/v1/admin/legal", json={"values": {"en": NOTICE}}, headers=headers)
    body = client.get("/api/v1/legal?lang=ja").json()
    assert body["language"] == "ja"
    assert "Association Exemple" in body["html"]
    assert body["languages"]["en"] is True
    assert body["languages"]["ja"] is False


def test_translation_is_refused_when_no_model_is_configured(client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    response = client.post(
        "/api/v1/admin/legal/translate",
        json={"target": "en", "text": NOTICE},
        headers=headers,
    )
    assert response.status_code == 503


def test_translation_returns_markdown_the_form_can_store(client, monkeypatch):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)

    seen: dict[str, str] = {}

    def fake_translate(text: str, target: str) -> str:
        seen["target"] = target
        seen["text"] = text
        return "## Publisher\n\nThe site is published by **Association Exemple**.\n"

    monkeypatch.setattr(ai, "is_configured", lambda: True)
    monkeypatch.setattr(ai, "translate_markdown", fake_translate)

    response = client.post(
        "/api/v1/admin/legal/translate",
        json={"target": "en", "text": NOTICE, "source": "fr"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["markdown"].startswith("## Publisher")
    assert seen["target"] == "en"
    assert "Association Exemple" in seen["text"]


def test_a_translation_without_text_is_refused(client, monkeypatch):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    response = client.post("/api/v1/admin/legal/translate", json={"target": "en", "text": "  "}, headers=headers)
    assert response.status_code == 422


@pytest.mark.parametrize("language", ["pt", "hi", "bn", "ar"])
def test_every_new_language_is_accepted(language, client):
    register_user(client)
    make_admin(client)
    headers = csrf_headers(client)
    response = client.put("/api/v1/admin/legal", json={"values": {language: NOTICE}}, headers=headers)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/legal?lang={language}").json()["has_notice"] is True
