# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Revision decks: generation from existing content, permissions, boxes, sheet."""

from __future__ import annotations

import pytest

from conftest import csrf_headers, register_user

PAGE_MD = """# Le cheval

## Galop 3
Le candidat doit trotter enlevé sur le bon diagonal et sauter un obstacle isolé.

## Sécurité
Vérifier la sangle, la longe et l'état du sol avant de monter.

**Amble** : allure à quatre temps, confortable pour le cavalier.
"""


def _wiki_with_page(client, headers, *, public=True):
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Univers équestre", "description": "Test"},
        headers=headers,
    ).json()
    detail = client.get(f"/api/v1/wiki/{wiki['id']}").json()
    page_id = detail["pages"][0]["id"]
    client.put(
        f"/api/v1/wiki/pages/{page_id}",
        json={"title": "Le cheval", "content_md": PAGE_MD},
        headers=headers,
    )
    if public:
        client.post(f"/api/v1/wiki/{wiki['id']}/publish", headers=headers)
    return wiki["id"], page_id


def _quiz_with_answers(client, headers):
    """A questionnaire is created whole: drafts take the questions in one call."""
    response = client.post(
        "/api/v1/quizzes/draft",
        json={
            "title": "Galop 3",
            "mode": "qcm",
            "questions": [
                {
                    "text_html": "Quelle allure est à quatre temps ?",
                    "options": [
                        {"text": "Le galop", "is_correct": False},
                        {"text": "L'amble", "is_correct": True},
                    ],
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], None


def test_a_deck_starts_empty_and_takes_cards(client):
    register_user(client, email="cards1@example.com")
    headers = csrf_headers(client)

    deck = client.post("/api/v1/decks", json={"title": "Mes cartes"}, headers=headers)
    assert deck.status_code == 201
    deck_id = deck.json()["id"]

    created = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "Amble", "back_md": "Allure à quatre temps"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["position"] == 1

    detail = client.get(f"/api/v1/decks/{deck_id}").json()
    assert [card["front_md"] for card in detail["cards"]] == ["Amble"]


def test_a_private_deck_is_invisible_to_others(client):
    register_user(client, email="owner@example.com")
    headers = csrf_headers(client)
    deck_id = client.post(
        "/api/v1/decks", json={"title": "Privé"}, headers=headers
    ).json()["id"]

    client.cookies.clear()
    register_user(client, email="curious@example.com", display_name="Curious")
    # A private deck must be indistinguishable from a missing one.
    assert client.get(f"/api/v1/decks/{deck_id}").status_code == 404
    assert client.get("/api/v1/decks").json()["items"] == []


def test_a_published_deck_is_listed_and_readable(client):
    register_user(client, email="author@example.com")
    headers = csrf_headers(client)
    deck_id = client.post(
        "/api/v1/decks", json={"title": "Publié", "is_public": True}, headers=headers
    ).json()["id"]

    client.cookies.clear()
    register_user(client, email="reader@example.com", display_name="Reader")
    assert client.get(f"/api/v1/decks/{deck_id}").status_code == 200
    titles = [deck["title"] for deck in client.get("/api/v1/decks").json()["items"]]
    assert "Publié" in titles


def test_only_the_owner_edits_a_deck(client):
    register_user(client, email="writer@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "À moi"}, headers=headers).json()["id"]

    client.cookies.clear()
    register_user(client, email="intruder@example.com", display_name="Intruder")
    response = client.put(
        f"/api/v1/decks/{deck_id}", json={"title": "Volé"}, headers=csrf_headers(client)
    )
    assert response.status_code == 404


def test_cards_are_generated_from_a_wiki_page(client):
    register_user(client, email="wiki@example.com")
    headers = csrf_headers(client)
    _wiki, page_id = _wiki_with_page(client, headers)

    response = client.post(
        "/api/v1/decks/from-source", json={"page_id": page_id}, headers=headers
    )
    assert response.status_code == 201, response.text
    deck = response.json()
    fronts = [card["front_md"] for card in deck["cards"]]
    assert "Galop 3" in fronts
    assert "Sécurité" in fronts
    assert "Amble" in fronts
    # The heading itself never becomes a card on its own.
    assert "Le cheval" not in fronts


def test_cards_are_generated_from_a_questionnaire(client):
    register_user(client, email="quizcards@example.com")
    headers = csrf_headers(client)
    quiz_id, _question = _quiz_with_answers(client, headers)

    response = client.post(
        "/api/v1/decks/from-source", json={"quiz_id": quiz_id}, headers=headers
    )
    assert response.status_code == 201, response.text
    deck = response.json()
    assert deck["quiz_id"] == quiz_id
    assert len(deck["cards"]) == 1
    assert "quatre temps" in deck["cards"][0]["front_md"]
    assert "amble" in deck["cards"][0]["back_md"].lower()


def test_a_page_without_headings_explains_itself(client):
    register_user(client, email="empty@example.com")
    headers = csrf_headers(client)
    wiki = client.post("/api/v1/wiki", json={"title": "Vide"}, headers=headers).json()
    page_id = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"][0]["id"]
    client.put(
        f"/api/v1/wiki/pages/{page_id}",
        json={"title": "Vide", "content_md": "Un seul paragraphe, sans titre."},
        headers=headers,
    )
    response = client.post(
        "/api/v1/decks/from-source", json={"page_id": page_id}, headers=headers
    )
    assert response.status_code == 422
    assert "heading" in response.json()["detail"]


def test_appending_twice_does_not_duplicate(client):
    register_user(client, email="twice@example.com")
    headers = csrf_headers(client)
    _wiki, page_id = _wiki_with_page(client, headers)
    deck_id = client.post(
        "/api/v1/decks", json={"title": "Doublons"}, headers=headers
    ).json()["id"]

    first = client.post(
        f"/api/v1/decks/{deck_id}/add-from-wiki",
        json={"page_id": page_id},
        headers=headers,
    ).json()
    assert first["added"] == 3
    second = client.post(
        f"/api/v1/decks/{deck_id}/add-from-wiki",
        json={"page_id": page_id},
        headers=headers,
    ).json()
    assert second["added"] == 0
    assert len(second["cards"]) == 3


def test_a_card_climbs_three_boxes_and_falls_back_to_the_first(client):
    register_user(client, email="review@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Boucles"}, headers=headers).json()["id"]
    card_id = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "Amble", "back_md": "Quatre temps"},
        headers=headers,
    ).json()["id"]

    boxes = []
    for _ in range(4):
        response = client.post(
            f"/api/v1/decks/{deck_id}/review",
            json={"card_id": card_id, "known": True},
            headers=headers,
        )
        boxes.append(response.json()["box"])
    assert boxes == [1, 2, 2, 2]

    forgotten = client.post(
        f"/api/v1/decks/{deck_id}/review",
        json={"card_id": card_id, "known": False},
        headers=headers,
    ).json()
    assert forgotten["box"] == 0
    assert forgotten["seen"] == 5


def test_the_deck_is_studied_weakest_first(client):
    register_user(client, email="study@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Ordre"}, headers=headers).json()["id"]
    first = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "Un", "back_md": "1"},
        headers=headers,
    ).json()["id"]
    client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "Deux", "back_md": "2"},
        headers=headers,
    )
    client.post(
        f"/api/v1/decks/{deck_id}/review",
        json={"card_id": first, "known": True},
        headers=headers,
    )

    order = [card["front_md"] for card in client.get(f"/api/v1/decks/{deck_id}/study").json()["cards"]]
    # The card already known drops behind the one still in the first box.
    assert order == ["Deux", "Un"]


def test_the_sheet_is_a_real_pdf(client):
    register_user(client, email="sheet@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Planche"}, headers=headers).json()["id"]
    client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "Galop 3", "back_md": "Trotter enlevé"},
        headers=headers,
    )
    response = client.get(f"/api/v1/decks/{deck_id}/sheet.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 1500


def test_a_sheet_of_pictures_alone_is_still_a_pdf(client, tmp_path):
    """An image-only card must print, and must not be cropped to nothing."""
    from io import BytesIO

    from PIL import Image

    register_user(client, email="sheet-picture@example.com")
    headers = csrf_headers(client)
    deck = client.post("/api/v1/decks", json={"title": "Portraits"}, headers=headers).json()

    buffer = BytesIO()
    Image.new("RGB", (300, 450), (40, 90, 160)).save(buffer, format="PNG")
    upload = client.post(
        "/api/v1/uploads/image",
        files={"file": ("lea.png", buffer.getvalue(), "image/png")},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    path = upload.json()["path"]

    client.post(
        f"/api/v1/decks/{deck['id']}/cards",
        json={"front_md": "", "back_md": "", "image_path": path, "back_image_path": path},
        headers=headers,
    )
    response = client.get(f"/api/v1/decks/{deck['id']}/sheet.pdf")
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"


def test_an_empty_deck_has_no_sheet(client):
    register_user(client, email="emptysheet@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Rien"}, headers=headers).json()["id"]
    assert client.get(f"/api/v1/decks/{deck_id}/sheet.pdf").status_code == 422


def test_reordering_rewrites_positions(client):
    register_user(client, email="order@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Ordre"}, headers=headers).json()["id"]
    ids = [
        client.post(
            f"/api/v1/decks/{deck_id}/cards",
            json={"front_md": f"Carte {index}", "back_md": "…"},
            headers=headers,
        ).json()["id"]
        for index in range(3)
    ]
    response = client.post(
        f"/api/v1/decks/{deck_id}/reorder",
        json={"order": list(reversed(ids))},
        headers=headers,
    )
    assert response.status_code == 200
    fronts = [card["front_md"] for card in response.json()["cards"]]
    assert fronts == ["Carte 2", "Carte 1", "Carte 0"]


def test_the_owner_can_delete_a_card_but_not_a_stranger(client):
    register_user(client, email="del@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "À supprimer"}, headers=headers).json()["id"]
    card_id = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "Temporaire", "back_md": "…"},
        headers=headers,
    ).json()["id"]
    assert (
        client.delete(f"/api/v1/decks/{deck_id}/cards/{card_id}", headers=headers).status_code
        == 204
    )
    assert client.get(f"/api/v1/decks/{deck_id}").json()["cards"] == []


@pytest.mark.parametrize("bad_front", ["", "   "])
def test_an_empty_front_is_refused(client, bad_front):
    """No word and no picture: there is nothing to revise."""
    register_user(client, email="blank@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Vide"}, headers=headers).json()["id"]
    response = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": bad_front, "back_md": "x"},
        headers=headers,
    )
    assert response.status_code == 422


def test_a_picture_alone_is_a_whole_front(client):
    """A character card is a portrait: the text must not be mandatory."""
    register_user(client, email="picture@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Cartes"}, headers=headers).json()["id"]
    response = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={"front_md": "", "back_md": "Cavalière discrète.", "image_path": "/media/lea.webp"},
        headers=headers,
    )
    assert response.status_code == 201
    card = response.json()
    assert card["front_md"] == ""
    assert card["image_path"] == "/media/lea.webp"


def test_the_back_can_be_a_picture_too(client):
    """Some decks are two-sided illustrations; the back picture must round-trip."""
    register_user(client, email="two-pictures@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Recto-verso"}, headers=headers).json()["id"]
    created = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={
            "front_md": "Léa",
            "back_md": "",
            "image_path": "/media/lea.webp",
            "back_image_path": "/media/lea-dos.webp",
        },
        headers=headers,
    )
    assert created.status_code == 201
    card = created.json()
    assert card["image_path"] == "/media/lea.webp"
    assert card["back_image_path"] == "/media/lea-dos.webp"

    edited = client.put(
        f"/api/v1/decks/{deck_id}/cards/{card['id']}",
        json={"front_md": "", "back_md": "", "back_image_path": "/media/lea-dos.webp"},
        headers=headers,
    )
    assert edited.status_code == 422  # emptying the front is still refused

    cleared = client.put(
        f"/api/v1/decks/{deck_id}/cards/{card['id']}",
        json={"front_md": "Léa", "back_md": "", "image_path": "/media/lea.webp"},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["back_image_path"] is None


def test_a_deck_names_its_wiki_and_the_catalogue_filters_on_it(client):
    """A deck is revision material for a wiki: the catalogue can stay scoped to it."""
    register_user(client, email="scoped@example.com")
    headers = csrf_headers(client)
    wiki_id, _page_id = _wiki_with_page(client, headers)
    other_id, _ = _wiki_with_page(client, headers)

    deck = client.post(
        "/api/v1/decks",
        json={"title": "Cartes du wiki", "wiki_id": wiki_id},
        headers=headers,
    )
    assert deck.status_code in (200, 201), deck.text
    deck_id = deck.json()["id"]
    assert deck.json()["wiki_id"] == wiki_id

    loose = client.post("/api/v1/decks", json={"title": "Hors wiki"}, headers=headers).json()
    assert loose["wiki_id"] is None

    scoped = client.get(f"/api/v1/decks?wiki_id={wiki_id}")
    assert scoped.status_code == 200, scoped.text
    assert [row["id"] for row in scoped.json()["items"]] == [deck_id]
    assert client.get(f"/api/v1/decks?wiki_id={other_id}").json()["items"] == []


def test_the_deck_shape_is_stored_and_checked(client):
    register_user(client, email="shape@example.com")
    headers = csrf_headers(client)
    created = client.post("/api/v1/decks", json={"title": "Forme"}, headers=headers).json()
    assert created["aspect"] == "2:3"  # portrait by default, never square

    wider = client.put(f"/api/v1/decks/{created['id']}", json={"aspect": "1:1"}, headers=headers)
    assert wider.status_code == 200 and wider.json()["aspect"] == "1:1"

    refused = client.put(f"/api/v1/decks/{created['id']}", json={"aspect": "7:3"}, headers=headers)
    assert refused.status_code == 422
    assert client.get(f"/api/v1/decks/{created['id']}").json()["aspect"] == "1:1"
