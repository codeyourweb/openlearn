# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Live co-editing: the three-way merge, the room, presence and the socket."""

from __future__ import annotations

import time

import pytest
from conftest import csrf_headers, register_user
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import collab
from app.collab import apply_splice, merge_text, minimal_splice


# ---------------------------------------------------------------------------
# The merge: nobody's paragraph is lost
# ---------------------------------------------------------------------------
def test_two_people_editing_different_paragraphs_keep_both_edits():
    base = "# Titre\n\nPremier paragraphe.\n\nSecond paragraphe.\n"
    mine = "# Titre\n\nPremier paragraphe, corrige.\n\nSecond paragraphe.\n"
    theirs = "# Titre\n\nPremier paragraphe.\n\nSecond paragraphe, allonge.\n"
    merged, conflicted = merge_text(base, mine, theirs)
    assert not conflicted
    assert "corrige" in merged and "allonge" in merged


def test_two_people_editing_the_same_line_on_different_words_keep_both():
    base = "Le resolver ecoute sur le port 53 depuis 1987.\n"
    mine = "Le resolver ecoute sur le port 53 TCP depuis 1987.\n"
    theirs = "Le resolver ecoute normalement sur le port 53 depuis 1987.\n"
    merged, conflicted = merge_text(base, mine, theirs)
    assert not conflicted
    assert "TCP" in merged and "normalement" in merged


def test_two_people_rewriting_the_same_passage_do_not_duplicate_it():
    base = "Le port est 53.\n"
    mine = "Le port est 5353.\n"
    theirs = "Le port est 1053.\n"
    merged, conflicted = merge_text(base, mine, theirs)
    assert conflicted
    # The server's text wins: one version of the line, never both.
    assert merged == theirs


def test_an_untouched_side_is_adopted_verbatim():
    base = "a\nb\n"
    assert merge_text(base, "a\nB\n", base) == ("a\nB\n", False)
    assert merge_text(base, base, "A\nb\n") == ("A\nb\n", False)
    assert merge_text(base, "x", "x") == ("x", False)


def test_a_long_document_merges_without_blowing_up():
    base = "".join(f"Ligne {index} du document.\n" for index in range(400))
    mine = base.replace("Ligne 10 ", "Ligne dix ")
    theirs = base.replace("Ligne 300 ", "Ligne trois cents ")
    merged, conflicted = merge_text(base, mine, theirs)
    assert not conflicted
    assert "Ligne dix " in merged and "Ligne trois cents " in merged


def test_the_minimal_splice_describes_the_change_and_nothing_else():
    before = "Le port est 53.\n"
    after = "Le port est 5353.\n"
    pos, delete, insert = minimal_splice(before, after)
    assert apply_splice(before, pos, delete, insert) == after
    # Only the digits that actually move are in the change.
    assert (pos, delete, insert) == (14, 0, "53")


# ---------------------------------------------------------------------------
# The room
# ---------------------------------------------------------------------------
def test_the_room_merges_against_the_revision_the_client_started_from():
    room = collab.CollabRoom(page_id=1, content="un\ndeux\ntrois\n")
    first = room.apply_text(0, "un\ndeux\ntrois\nquatre\n")
    assert first is not None and first[0] == 1
    # A client still holding revision 0 sends its own, different change.
    second = room.apply_text(0, "zero\nun\ndeux\ntrois\n")
    assert second is not None
    assert room.content.startswith("zero")
    assert room.content.rstrip().endswith("quatre")


def test_a_revision_outside_the_history_asks_for_a_resync():
    room = collab.CollabRoom(page_id=1, content="a\n")
    for index in range(collab.MAX_HISTORY + 3):
        room.apply_text(room.rev, f"{room.content}ligne {index}\n")
    assert room.apply_text(0, "autre chose") is None


def test_an_unchanged_text_produces_no_op():
    """The room answers nothing at all: a resync would rebuild the client's surface."""
    room = collab.CollabRoom(page_id=1, content="stable\n")
    assert room.apply_text(0, "stable\n") == collab.NO_CHANGE


def test_reset_adopts_the_saved_text_and_forgets_older_revisions():
    room = collab.CollabRoom(page_id=1, content="brouillon\n")
    room.apply_text(0, "brouillon en cours\n")
    rev = room.reset("version enregistree\n")
    assert rev == 2
    assert room.content == "version enregistree\n"
    assert room.apply_text(0, "encore autre chose") is None


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------
def _app_client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _wiki_with_two_writers(client: TestClient):
    register_user(client, "writer-a@example.com", display_name="Alice")
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Live wiki", "description": "Two people, one page."},
        headers=csrf_headers(client),
    ).json()
    page = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"][0]

    other = _app_client()
    register_user(other, "writer-b@example.com", display_name="Bob")
    added = client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": "writer-b@example.com", "role": "maintainer"},
        headers=csrf_headers(client),
    )
    assert added.status_code in {200, 201}, added.text
    return wiki, page, other


def test_two_browsers_see_each_others_typing(client):
    wiki, page, other = _wiki_with_two_writers(client)
    url = f"/api/v1/wiki/pages/{page['id']}/live"

    with client.websocket_connect(url) as alice, other.websocket_connect(url) as bob:
        hello_a = alice.receive_json()
        assert hello_a["type"] == "hello"
        assert hello_a["can_write"] is True
        assert hello_a["content"] == page["content_md"]
        assert hello_a["users"] and hello_a["users"][0]["name"] == "Alice"

        hello_b = bob.receive_json()
        assert hello_b["type"] == "hello"
        seen = alice.receive_json()  # Alice learns that Bob joined
        assert seen["type"] == "presence" and len(seen["users"]) == 2

        alice.send_json({"type": "op", "rev": hello_a["rev"], "text": hello_a["content"] + " A"})
        applied = bob.receive_json()
        assert applied["type"] == "op"
        assert applied["insert"] == " A"
        assert applied["name"] == "Alice"
        assert applied["rev"] == hello_a["rev"] + 1
        alice.receive_json()  # the author gets the same op back, for revision sync

        bob.send_json({"type": "op", "rev": applied["rev"], "text": "B" + room_text(applied, hello_b)})
        echoed = alice.receive_json()
        assert echoed["type"] == "op" and echoed["pos"] == 0
        bob.receive_json()

    room = collab.peek(page["id"])
    assert room is not None
    assert room.content.startswith("B")
    assert room.content.rstrip().endswith("A")


def room_text(applied: dict, hello: dict) -> str:
    """Rebuild what Bob's screen shows after Alice's op."""
    return apply_splice(hello["content"] + " A", applied["pos"], applied["delete"], applied["insert"])


def test_cursors_are_broadcast_with_a_colour_and_a_name(client):
    wiki, page, other = _wiki_with_two_writers(client)
    url = f"/api/v1/wiki/pages/{page['id']}/live"
    with client.websocket_connect(url) as alice, other.websocket_connect(url) as bob:
        alice.receive_json()  # hello
        bob.receive_json()  # hello
        alice.receive_json()  # presence: Bob joined

        bob.send_json({"type": "cursor", "anchor": 4, "head": 9})
        cursor = alice.receive_json()
        assert cursor["type"] == "cursor"
        assert cursor["name"] == "Bob"
        assert cursor["anchor"] == 4 and cursor["head"] == 9
        assert cursor["color"].startswith("#")


def test_a_reader_watches_but_cannot_type(client):
    wiki, page, other = _wiki_with_two_writers(client)
    reader = _app_client()
    register_user(reader, "reader@example.com", display_name="Carol")
    # A contributor reads everything and writes nothing: their edit is a
    # suggestion, so the socket must refuse their keystrokes.
    added = client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": "reader@example.com", "role": "contributor"},
        headers=csrf_headers(client),
    )
    assert added.status_code in {200, 201}, added.text

    url = f"/api/v1/wiki/pages/{page['id']}/live"
    with reader.websocket_connect(url) as watch:
        hello = watch.receive_json()
        assert hello["type"] == "hello"
        assert hello["can_write"] is False
        watch.send_json({"type": "op", "rev": hello["rev"], "text": "x"})
        assert watch.receive_json()["type"] == "denied"


def test_a_private_wiki_refuses_an_unknown_socket(client):
    register_user(client, "owner@example.com", display_name="Owner")
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Secret wiki", "description": "Private."},
        headers=csrf_headers(client),
    ).json()
    page = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"][0]

    stranger = _app_client()
    with pytest.raises(WebSocketDisconnect):
        with stranger.websocket_connect(f"/api/v1/wiki/pages/{page['id']}/live"):
            pass


def test_the_live_text_waits_in_a_draft_and_never_touches_the_page(client):
    """Autosave parks the text: the published page keeps its last saved version.

    Writing straight into the page meant that pausing long enough while typing
    published whatever was on screen — colours, half-finished links and all.
    """
    wiki, page, other = _wiki_with_two_writers(client)
    url = f"/api/v1/wiki/pages/{page['id']}/live"
    with client.websocket_connect(url) as alice:
        hello = alice.receive_json()
        alice.send_json(
            {
                "type": "op",
                "rev": hello["rev"],
                "text": hello["content"] + "\n\nLive line.\n",
            }
        )
        alice.receive_json()

    deadline = time.time() + 10
    detail = {}
    while time.time() < deadline:
        detail = client.get(f"/api/v1/wiki/pages/{page['id']}").json()
        if detail.get("draft"):
            break
        time.sleep(0.4)
    assert detail.get("draft"), "the autosave never reached the draft"
    assert "Live line." not in detail["content_md"], "an unsaved edit must not be published"
    assert detail["version"] == page["version"], "a live edit must not freeze a version"

    # Opening the page again hands the working copy back to its author.
    with client.websocket_connect(url) as alice:
        hello = alice.receive_json()
        assert "Live line." in hello["content"]

    # Saving publishes it, freezes a version, and empties the draft.
    saved = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": page["title"], "content_md": hello["content"], "tags": []},
        headers=csrf_headers(client),
    )
    assert saved.status_code == 200, saved.text
    detail = client.get(f"/api/v1/wiki/pages/{page['id']}").json()
    assert "Live line." in detail["content_md"]
    assert detail["draft"] is None
    assert detail["version"] == page["version"] + 1
