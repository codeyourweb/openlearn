# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Private content is shared by its address, not hidden behind a login.

A trainer sends the link of a questionnaire to a class; a colleague sends the
address of a wiki page. Neither should have to open an account to read it.
Publication to the catalogue is a separate promise: it decides whether the item
is listed and searchable — never whether the link works.

The boundary is the version, not the status: nothing is readable by its link
until it has been published once, privately or publicly, and a draft stays the
author's alone.
"""

from __future__ import annotations

from tests.conftest import (
    create_quiz,
    csrf_headers,
    login_user,
    make_trusted,
    quiz_payload,
    register_user,
)


def _logout(client) -> None:
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))


def _publish(client, quiz_id: int, visibility: str):
    return client.post(
        f"/api/v1/quizzes/{quiz_id}/visibility",
        json={"visibility": visibility},
        headers=csrf_headers(client),
    )


def _wiki(client, title="Manuel réseau"):
    response = client.post(
        "/api/v1/wiki",
        json={"title": title, "description": "Un wiki partagé par son lien", "default_language": "fr"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _page(client, wiki_id: int, title="Bases du DNS", body="# Bases du DNS\n\nUn résolveur cache."):
    response = client.post(
        f"/api/v1/wiki/{wiki_id}/pages",
        json={"title": title, "content_md": body},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Questionnaire


def test_a_private_quiz_opens_for_the_visitor_holding_its_link(client):
    register_user(client)
    quiz = create_quiz(client)
    assert _publish(client, quiz["id"], "private").json()["status"] == "private"
    _logout(client)

    # A visitor without an account, arriving from the link.
    detail = client.get(f"/api/v1/quizzes/{quiz['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["title"] == quiz["title"]
    assert detail.json()["questions"], "the questions must come with the link"
    assert "is_correct" not in str(detail.json()), "answers never travel to a player"


def test_a_private_quiz_is_absent_from_the_catalogue_and_the_search(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload(title="Rare orchid questionnaire"))
    _publish(client, quiz["id"], "private")
    _logout(client)

    assert client.get("/api/v1/quizzes").json() == []
    searched = client.get("/api/v1/quizzes", params={"q": "orchid"})
    assert searched.status_code == 200
    assert searched.json() == []


def test_a_visitor_holding_the_link_can_play_a_private_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    _publish(client, quiz["id"], "private")
    _logout(client)

    started = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "solo", "nickname": "Invité"},
        headers=csrf_headers(client),
    )
    assert started.status_code == 201, started.text
    assert started.json()["session"]["code"]


def test_a_guest_can_host_a_live_session_of_a_private_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    _publish(client, quiz["id"], "private")
    _logout(client)

    hosted = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "live"},
        headers=csrf_headers(client),
    )
    assert hosted.status_code == 201, hosted.text


def test_a_draft_has_no_link_to_share(client):
    register_user(client)
    quiz = create_quiz(client)  # never published: a draft
    _logout(client)

    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 404


def test_another_author_cannot_edit_what_a_link_only_lets_them_read(client):
    register_user(client)
    quiz = create_quiz(client)
    _publish(client, quiz["id"], "private")
    _logout(client)
    register_user(client, email="other@example.com", display_name="Other")
    make_trusted(client)

    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 200
    edited = client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload(title="Hijacked"),
        headers=csrf_headers(client),
    )
    assert edited.status_code == 403


def test_a_private_quiz_keeps_its_published_version_while_the_author_edits(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload(title="Version gelée"))
    _publish(client, quiz["id"], "private")

    payload = quiz_payload(title="Version gelée")
    payload["questions"][0]["text_html"] = "<p>Question réécrite après publication.</p>"
    assert client.put(f"/api/v1/quizzes/{quiz['id']}", json=payload, headers=csrf_headers(client)).status_code == 200
    _logout(client)

    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert "Question réécrite" not in str(detail), "a visitor must read the published version"


def test_a_quiz_awaiting_moderation_is_readable_but_never_listed(client):
    register_user(client)
    quiz = create_quiz(client)
    # An untrusted author asks for the catalogue: the request is queued, and the
    # quiz stays private — live by its link, invisible in the catalogue.
    asked = _publish(client, quiz["id"], "public")
    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "private"
    assert asked.json()["requires_moderation"] is True
    _logout(client)

    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 200
    assert client.get("/api/v1/quizzes").json() == []


# --------------------------------------------------------------------------- #
# Wiki


def test_a_private_wiki_opens_for_the_visitor_holding_its_link(client):
    register_user(client)
    wiki = _wiki(client)
    page = _page(client, wiki["id"])
    published = client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "private"},
        headers=csrf_headers(client),
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "private"
    _logout(client)

    assert client.get(f"/api/v1/wiki/{wiki['id']}").status_code == 200
    assert client.get(f"/api/v1/wiki/pages/{page['id']}").status_code == 200


def test_a_private_wiki_is_absent_from_the_listing_and_the_search(client):
    register_user(client)
    wiki = _wiki(client, title="Wiki réservé au stage")
    _page(client, wiki["id"], body="# Réservé\n\nLe protocole BGP en détail.")
    client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "private"},
        headers=csrf_headers(client),
    )
    _logout(client)

    assert client.get("/api/v1/wiki").json() == []
    hits = client.get("/api/v1/wiki/search", params={"q": "BGP"})
    assert hits.status_code == 200
    assert hits.json() == []


def test_a_draft_wiki_is_still_closed_to_visitors(client):
    register_user(client)
    wiki = _wiki(client)
    page = _page(client, wiki["id"])
    _logout(client)

    assert client.get(f"/api/v1/wiki/{wiki['id']}").status_code == 404
    assert client.get(f"/api/v1/wiki/pages/{page['id']}").status_code == 404


def test_a_stranger_may_read_a_private_wiki_without_taking_part(client):
    register_user(client)
    wiki = _wiki(client)
    _page(client, wiki["id"])
    client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "private"},
        headers=csrf_headers(client),
    )
    _logout(client)
    register_user(client, email="reader@example.com", display_name="Reader")
    login_user(client, "reader@example.com")

    detail = client.get(f"/api/v1/wiki/{wiki['id']}")
    assert detail.status_code == 200
    # Reading a shared wiki does not make anyone a member: the pen stays closed.
    assert detail.json()["role"] in (None, "reader")
    assert detail.json()["can_write"] is False
