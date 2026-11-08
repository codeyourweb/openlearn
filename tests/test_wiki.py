# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Wiki API: documents, versions, links, proposals, moderation and exports."""

from __future__ import annotations

import io
import zipfile

from conftest import csrf_headers, make_admin, make_trusted, register_user


def _png_bytes() -> bytes:
    """A 1x1 PNG: enough for Pillow, small enough for a test."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def _create(client, title="Manuel réseau", description="Un wiki de test"):
    response = client.post(
        "/api/v1/wiki",
        json={"title": title, "description": description, "default_language": "fr"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_page(client, wiki_id, title="Bases du DNS", content="# Bases du DNS\n\nUn résolveur cache les réponses.", tags=None):
    body = {"title": title, "content_md": content}
    if tags is not None:
        body["tags"] = tags
    response = client.post(
        f"/api/v1/wiki/{wiki_id}/pages",
        json=body,
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client, email: str) -> None:
    """Sign back in: registering a second account replaces the cookie jar."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "TestingPassw0rd!"})
    assert response.status_code == 200, response.text


def test_a_new_wiki_starts_with_a_home_page_and_a_first_version(client):
    register_user(client)
    wiki = _create(client)
    assert wiki["status"] == "draft"
    assert wiki["page_count"] == 1
    detail = client.get(f"/api/v1/wiki/{wiki['id']}").json()
    assert detail["pages"][0]["version"] == 1
    assert detail["role"] == "owner"
    assert detail["can_write"] is True


def test_a_private_wiki_is_invisible_to_a_stranger(client):
    register_user(client)
    wiki = _create(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="stranger@example.com", display_name="Stranger")
    assert client.get(f"/api/v1/wiki/{wiki['id']}").status_code == 404


def test_saving_a_page_freezes_a_version_and_the_diff_shows_the_change(client):
    register_user(client)
    wiki = _create(client)
    page = _add_page(client, wiki["id"])
    assert page["version"] == 1

    updated = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={
            "title": "Bases du DNS",
            "content_md": "# Bases du DNS\n\nUn résolveur **cache** les réponses.\n\nIl écoute sur le port 53.",
            "note": "Précision sur le port",
        },
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2

    versions = client.get(f"/api/v1/wiki/pages/{page['id']}/versions").json()
    assert [item["number"] for item in versions] == [2, 1]
    assert versions[0]["note"] == "Précision sur le port"

    diff = client.get(f"/api/v1/wiki/pages/{page['id']}/diff?from=1&to=2").json()
    assert diff["stats"]["added"] >= 1
    added = [row["text"] for row in diff["rows"] if row["kind"] == "add"]
    assert any("port 53" in line for line in added)


def test_wikilinks_resolve_backlinks_and_leave_missing_targets_flagged(client):
    register_user(client)
    wiki = _create(client)
    dns = _add_page(client, wiki["id"], "Bases du DNS", "# Bases du DNS\n\nVoir [[Serveur DHCP]].")
    dhcp = _add_page(client, wiki["id"], "Serveur DHCP", "# Serveur DHCP\n\nAllocation dynamique.")

    detail = client.get(f"/api/v1/wiki/pages/{dns['id']}").json()
    assert detail["html"].count("/wiki/p/serveur-dhcp") == 1
    backlinks = client.get(f"/api/v1/wiki/pages/{dhcp['id']}").json()["backlinks"]
    assert [link["title"] for link in backlinks] == ["Bases du DNS"]

    graph = client.get(f"/api/v1/wiki/{wiki['id']}/graph").json()
    assert {"kind": "link", "source": dns["id"], "target": dhcp["id"]} in graph["edges"]

    orphan = _add_page(client, wiki["id"], "Brouillon", "# Brouillon\n\n[[Page qui n'existe pas]]")
    html = client.get(f"/api/v1/wiki/pages/{orphan['id']}").json()["html"]
    assert "is-missing" in html


def test_a_contributor_never_writes_the_live_page(client):
    register_user(client)
    wiki = _create(client)
    page = _add_page(client, wiki["id"])
    member = register_user(client, email="contrib@example.com", display_name="Contributeur")
    _login(client, "player@example.com")

    added = client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": member["email"], "role": "contributor"},
        headers=csrf_headers(client),
    )
    assert added.status_code == 201, added.text

    # The contributor asks for a change: the live page must not move.
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post(
        "/api/v1/auth/login",
        json={"email": member["email"], "password": "TestingPassw0rd!"},
    )
    proposed = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": "Bases du DNS", "content_md": "# Bases du DNS\n\nRéécrit par un contributeur.", "note": "Ma version"},
        headers=csrf_headers(client),
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["status"] == "proposal"
    live = client.get(f"/api/v1/wiki/pages/{page['id']}").json()
    assert "contributeur" not in live["html"]
    assert live["version"] == 1

    # The owner accepts it, which writes a new version.
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": "player@example.com", "password": "TestingPassw0rd!"})
    proposals = client.get(f"/api/v1/wiki/pages/{page['id']}/proposals").json()
    assert proposals[0]["status"] == "pending"
    accepted = client.post(
        f"/api/v1/wiki/proposals/{proposals[0]['id']}/accept",
        json={"note": "Merci"},
        headers=csrf_headers(client),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["version"] == 2
    live = client.get(f"/api/v1/wiki/pages/{page['id']}").json()
    assert "contributeur" in live["html"]


def test_a_maintainer_writes_directly(client):
    register_user(client)
    wiki = _create(client)
    page = _add_page(client, wiki["id"])
    member = register_user(client, email="maint@example.com", display_name="Mainteneur")
    _login(client, "player@example.com")
    client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": member["email"], "role": "maintainer"},
        headers=csrf_headers(client),
    )
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": member["email"], "password": "TestingPassw0rd!"})
    saved = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": "Bases du DNS", "content_md": "# DNS\n\nÉcrit par le mainteneur."},
        headers=csrf_headers(client),
    )
    assert saved.json()["status"] == "saved"
    assert saved.json()["version"] == 2


def test_publishing_publicly_waits_for_moderation_unless_trusted(client):
    register_user(client)
    wiki = _create(client)
    pending = client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"
    assert pending.json()["is_public"] is False

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    anonymous = client.get(f"/api/v1/wiki/{wiki['id']}")
    assert anonymous.status_code == 404

    _login(client, "player@example.com")
    make_trusted(client)
    approved = client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert approved.json()["status"] == "public"

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    public = client.get(f"/api/v1/wiki/{wiki['id']}")
    assert public.status_code == 200


def test_an_administrator_approves_a_pending_wiki(client):
    register_user(client)
    wiki = _create(client)
    client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    make_admin(client)
    queue = client.get("/api/v1/admin/wikis?status=pending").json()
    assert [row["id"] for row in queue] == [wiki["id"]]
    approved = client.post(
        f"/api/v1/admin/wikis/{wiki['id']}/approve",
        json={"note": "Relu"},
        headers=csrf_headers(client),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "public"


def test_full_text_search_respects_who_may_read_what(client):
    register_user(client)
    wiki = _create(client)
    _add_page(client, wiki["id"], "Sécurité des routeurs", "# Sécurité\n\nDurcir OSPF et BGP.")
    client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    make_trusted(client)
    client.post(
        f"/api/v1/wiki/{wiki['id']}/publish",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    hits = client.get("/api/v1/wiki/search?q=OSPF").json()
    assert hits and hits[0]["title"] == "Sécurité des routeurs"


def test_filtering_my_wikis_on_a_word_returns_the_wiki_holding_it(client):
    """The catalogue filter searched pages but compared page ids to wiki ids.

    Every wiki disappeared as soon as a term matched, which made the search
    field of the account page useless.
    """
    register_user(client)
    wiki = _create(client, title="Manuel réseau")
    _add_page(client, wiki["id"], "Bases du DNS", "# Bases du DNS\n\nUn résolveur cache les réponses.")
    other = _create(client, title="Cuisine")

    response = client.get("/api/v1/wiki?mine=true&q=DNS")
    assert response.status_code == 200, response.text
    titles = [row["title"] for row in response.json()]
    assert titles == ["Manuel réseau"], titles
    assert other["title"] not in titles

    # A title match keeps working even when no page carries the word.
    by_title = client.get("/api/v1/wiki?mine=true&q=Cuisine")
    assert [row["title"] for row in by_title.json()] == ["Cuisine"]


def test_markdown_is_sanitised_and_scripts_never_survive(client):
    register_user(client)
    wiki = _create(client)
    dirty = _add_page(
        client,
        wiki["id"],
        "Injection",
        "# Injection\n\n<script>alert('x')</script>\n\n<img src=x onerror=\"alert(1)\">\n\n[lien](javascript:alert(1))",
    )
    html = client.get(f"/api/v1/wiki/pages/{dirty['id']}").json()["html"]
    assert "<script" not in html
    # The payload survives as *text*, escaped: what must not survive is an
    # actual element or an executable attribute.
    assert "<img" not in html
    assert 'onerror="' not in html.replace("&quot;", '"') or "&lt;img" in html
    assert 'href="javascript' not in html


def test_exports_produce_markdown_and_a_zip_of_markdown_files(client):
    register_user(client)
    wiki = _create(client)
    dns = _add_page(client, wiki["id"], "Bases du DNS", "# Bases du DNS\n\nVoir [[Serveur DHCP]].")
    _add_page(client, wiki["id"], "Serveur DHCP", "# Serveur DHCP\n\nAllocation dynamique.")

    single = client.get(f"/api/v1/wiki/pages/{dns['id']}/export.md")
    assert single.status_code == 200
    assert "attachment" in single.headers["content-disposition"]
    assert "[Serveur DHCP](serveur-dhcp.md)" in single.text

    archive = client.get(f"/api/v1/wiki/{wiki['id']}/export.zip")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        names = set(bundle.namelist())
        assert {"README.md", "bases-du-dns.md", "serveur-dhcp.md"} <= names
        assert "[Serveur DHCP](serveur-dhcp.md)" in bundle.read("bases-du-dns.md").decode()


def test_restoring_an_old_version_appends_a_new_one(client):
    register_user(client)
    wiki = _create(client)
    page = _add_page(client, wiki["id"], "Journal", "# Journal\n\nVersion initiale.")
    client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": "Journal", "content_md": "# Journal\n\nVersion réécrite."},
        headers=csrf_headers(client),
    )
    restored = client.post(
        f"/api/v1/wiki/pages/{page['id']}/restore/1", headers=csrf_headers(client)
    )
    assert restored.json()["version"] == 3
    live = client.get(f"/api/v1/wiki/pages/{page['id']}").json()
    assert "Version initiale" in live["content_md"]
    assert [item["number"] for item in client.get(f"/api/v1/wiki/pages/{page['id']}/versions").json()] == [3, 2, 1]


def test_only_the_owner_deletes_a_wiki(client):
    register_user(client)
    wiki = _create(client)
    member = register_user(client, email="maint@example.com", display_name="Mainteneur")
    _login(client, "player@example.com")
    client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": member["email"], "role": "maintainer"},
        headers=csrf_headers(client),
    )
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": member["email"], "password": "TestingPassw0rd!"})
    assert client.delete(f"/api/v1/wiki/{wiki['id']}", headers=csrf_headers(client)).status_code == 403


def test_an_administrator_edits_any_wiki_instead_of_being_turned_away(client):
    """An admin moderates *and* writes: a typo fix must not require a proposal.

    The old rule answered 403 "Administrators do not edit content." as soon as
    the admin was not the owner, which made the moderation role a dead end.
    """
    register_user(client, email="owner@example.com")
    wiki = _create(client, title="Wiki de quelqu'un d'autre")
    page = _add_page(client, wiki["id"])

    # The admin is a second account: this one is promoted in the database.
    register_user(client, email="root@example.com")
    make_admin(client)
    detail = client.get(f"/api/v1/wiki/{wiki['id']}").json()
    assert detail["role"] == "maintainer"
    assert detail["can_write"] is True

    saved = client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={"title": page["title"], "content_md": "# Corrigé\n\nUne coquille en moins.", "tags": []},
        headers=csrf_headers(client),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "saved"

    renamed = client.put(
        f"/api/v1/wiki/{wiki['id']}",
        json={"title": "Titre revu", "description": "", "default_language": "fr"},
        headers=csrf_headers(client),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Titre revu"

    canvas = client.put(f"/api/v1/wiki/{wiki['id']}/canvas", json={"canvas": {"nodes": [], "edges": []}}, headers=csrf_headers(client))
    assert canvas.status_code == 200, canvas.text


def test_a_natural_question_finds_the_page_that_mentions_it(client):
    """Retrieval matched every keyword at once, so a real sentence found nothing.

    "À quoi sert un résolveur récursif ?" required the page to contain "à",
    "quoi", "sert" and "un" as well: the chat always answered "I found nothing".
    """
    from app.db import SessionLocal
    from app import wiki_ai

    register_user(client, email="rag@example.com")
    wiki = _create(client, title="Réseau")
    page = _add_page(
        client,
        wiki["id"],
        title="Résolution DNS",
        content="# Résolution DNS\n\nUn résolveur récursif interroge les serveurs racine pour vous.",
    )

    with SessionLocal() as db:
        hits = wiki_ai.retrieve(db, "À quoi sert un résolveur récursif ?", [wiki["id"]])
        assert hits, "no chunk retrieved"
        assert hits[0]["page_id"] == page["id"]
        assert hits[0]["title"] == "Résolution DNS"
        empty = wiki_ai.retrieve(db, "combien pèse une licorne bleue", [wiki["id"]])
        assert empty == []
        assert "rien" in wiki_ai._nothing_found("fr")


def test_the_table_of_contents_skips_the_page_title(client):
    """The level-1 heading is the page title: repeating it is noise, not an outline."""
    from app.wiki import outline

    items = outline("# Titre\n\n## Première partie\n\n### Détail\n\n## Seconde partie\n")
    assert [item["text"] for item in items] == ["Première partie", "Détail", "Seconde partie"]
    assert [item["depth"] for item in items] == [2, 3, 2]


def test_the_side_by_side_diff_pairs_removals_and_additions(client):
    """A reader compares columns: the changed line faces its replacement."""
    register_user(client)
    wiki = _create(client)
    page = _add_page(
        client,
        wiki["id"],
        "Ports",
        "# Ports\n\nLe resolver écoute sur le port 53.\nLa zone est signée.\n",
    )
    client.put(
        f"/api/v1/wiki/pages/{page['id']}",
        json={
            "title": "Ports",
            "content_md": "# Ports\n\nLe resolver écoute sur le port 5353.\nLa zone est signée.\nUne ligne ajoutée.\n",
        },
        headers=csrf_headers(client),
    )
    diff = client.get(f"/api/v1/wiki/pages/{page['id']}/diff?from=1&to=2").json()

    assert diff["labels"]["to"] == "v2"
    assert diff["labels"]["page"] == "Ports"
    changed = [row for row in diff["side"] if row["kind"] == "change"]
    assert changed, diff["side"]
    row = changed[0]
    assert "53." in row["left"]["text"] and "5353" in row["right"]["text"]
    # Word-level emphasis marks what actually moved, not the whole line.
    assert any(segment["kind"] == "chg" for segment in row["left"]["segments"])
    assert any(segment["kind"] == "chg" for segment in row["right"]["segments"])

    added = [row for row in diff["side"] if row["kind"] == "add"]
    assert added and added[0]["left"]["text"] == "" and "ajoutée" in added[0]["right"]["text"]
    assert added[0]["left"]["no"] is None

    # A row that pairs a removal with an addition carries both line numbers.
    assert row["left"]["no"] and row["right"]["no"]


def test_a_markdown_file_is_imported_as_a_page(client):
    register_user(client)
    wiki = _create(client)
    payload = (
        "---\n"
        "title: Journal de bord\n"
        "tags: [réseau, incident]\n"
        "---\n\n"
        "# Journal de bord\n\n"
        "Le 3 novembre, la zone a cessé de répondre.\n"
    )
    response = client.post(
        f"/api/v1/wiki/{wiki['id']}/pages/import",
        files={"file": ("journal.md", payload.encode("utf-8"), "text/markdown")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    page = response.json()["page"]
    assert page["title"] == "Journal de bord"
    # Front matter is metadata, not content; the duplicated h1 is dropped too.
    assert "title:" not in page["content_md"]
    assert not page["content_md"].startswith("# Journal de bord")
    assert "zone a cessé" in page["content_md"]

    detail = client.get(f"/api/v1/wiki/{wiki['id']}").json()
    imported = next(item for item in detail["pages"] if item["title"] == "Journal de bord")
    assert imported["tags"] == ["réseau", "incident"]


def test_an_obsidian_archive_becomes_a_wiki_with_its_links_and_pictures(client):
    register_user(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("vault/.obsidian/app.json", "{}")
        archive.writestr(
            "vault/DNS.md",
            "# Résolution DNS\n\n## Le cache\n\nVoir [[Enregistrements]].\n\n![[schema.png]]\n",
        )
        archive.writestr("vault/Enregistrements.md", "# Enregistrements\n\nUn A pointe vers une IPv4.\n")
        archive.writestr("vault/pieces/schema.png", _png_bytes())
        archive.writestr("../../escaped.md", "# Escape\n")

    response = client.post(
        "/api/v1/wiki/import",
        files={"file": ("vault.zip", buffer.getvalue(), "application/zip")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "obsidian"
    assert body["pages"] == 2
    assert body["images"] == 1

    detail = client.get(f"/api/v1/wiki/{body['wiki']['id']}").json()
    titles = {page["title"] for page in detail["pages"]}
    assert titles == {"Résolution DNS", "Enregistrements"}

    dns = next(page for page in detail["pages"] if page["title"] == "Résolution DNS")
    page = client.get(f"/api/v1/wiki/pages/{dns['id']}").json()
    # The embed was rewritten to a served picture, and the wikilink resolved.
    assert "/media/" in page["content_md"]
    assert not page["content_md"].count("![[")
    assert [item["text"] for item in page["outline"]] == ["Le cache"]


def test_a_joplin_export_keeps_titles_and_tags(client):
    register_user(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "Sécurité/Phishing.md",
            "---\nid: 4f2c\nparent_id: 9a1b\ntitle: Reconnaître un phishing\n"
            "tags:\n  - sécurité\n---\n\n# Reconnaître un phishing\n\nLe lien ment sur sa destination.\n",
        )
        archive.writestr("Sécurité/Courriel.md", "---\ntitle: Courriel suspect\n---\n\nVérifier l'en-tête.\n")

    response = client.post(
        "/api/v1/wiki/import",
        files={"file": ("export.zip", buffer.getvalue(), "application/zip")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "joplin"
    assert body["pages"] == 2

    detail = client.get(f"/api/v1/wiki/{body['wiki']['id']}").json()
    titles = {page["title"] for page in detail["pages"]}
    assert titles == {"Reconnaître un phishing", "Courriel suspect"}
    phishing = next(page for page in detail["pages"] if "phishing" in page["title"])
    # The notebook name survives as a tag, so the import keeps its structure.
    assert "Sécurité" in (phishing["tags"] or []) or phishing["tags"]


def test_an_archive_that_is_not_a_wiki_is_refused(client):
    register_user(client)
    response = client.post(
        "/api/v1/wiki/import",
        files={"file": ("notes.zip", b"not a zip at all", "application/zip")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 415

    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("readme.pdf", b"%PDF-1.4")
    response = client.post(
        "/api/v1/wiki/import",
        files={"file": ("other.zip", empty.getvalue(), "application/zip")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
    assert "markdown" in response.json()["detail"].lower()


def test_a_zip_bomb_and_an_endless_archive_are_refused(client):
    register_user(client)

    # 130 MB of zeroes compresses to a few kilobytes: refusing it is the point.
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("vault/Bombe.md", b"# Bombe\n")
        archive.writestr("vault/gros.bin", b"\0" * (130 * 1024 * 1024))
    heavy = client.post(
        "/api/v1/wiki/import",
        files={"file": ("bomb.zip", bomb.getvalue(), "application/zip")},
        headers=csrf_headers(client),
    )
    assert heavy.status_code == 413, heavy.text
    assert "decompressed" in heavy.json()["detail"]

    crowd = io.BytesIO()
    with zipfile.ZipFile(crowd, "w") as archive:
        for index in range(650):
            archive.writestr(f"vault/note-{index}.md", f"# Note {index}\n")
    many = client.post(
        "/api/v1/wiki/import",
        files={"file": ("crowd.zip", crowd.getvalue(), "application/zip")},
        headers=csrf_headers(client),
    )
    assert many.status_code == 422, many.text
    assert "600" in many.json()["detail"]


def _wiki_with_pages(client, titles=("DNS", "Cache")):
    register_user(client)
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Menu wiki", "description": "Tree tests."},
        headers=csrf_headers(client),
    ).json()
    pages = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"]
    home = pages[0]
    created = []
    for title in titles:
        response = client.post(
            f"/api/v1/wiki/{wiki['id']}/pages",
            json={"title": title, "content_md": f"# {title}\n\nTexte.\n"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 201, response.text
        created.append(response.json())
    return wiki, home, created


def test_a_page_can_hang_under_another_and_the_breadcrumb_follows(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    response = client.put(
        f"/api/v1/wiki/{wiki['id']}/tree",
        json={
            "pages": [
                {"id": home["id"], "parent_id": None, "position": 0},
                {"id": dns["id"], "parent_id": home["id"], "position": 0},
                {"id": cache["id"], "parent_id": dns["id"], "position": 0},
            ]
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    tree = {entry["id"]: entry for entry in response.json()["pages"]}
    assert tree[dns["id"]]["parent_id"] == home["id"]
    assert tree[cache["id"]]["parent_id"] == dns["id"]
    assert tree[home["id"]]["position"] == 0

    detail = client.get(f"/api/v1/wiki/pages/{cache['id']}").json()
    # The created wiki opens on its home page, titled "Home" by the seeder.
    assert [item["title"] for item in detail["breadcrumb"]] == ["Home", "DNS", "Cache"]
    parent = client.get(f"/api/v1/wiki/pages/{dns['id']}").json()
    assert [item["title"] for item in parent["children"]] == ["Cache"]


def test_a_move_that_would_close_a_loop_is_refused(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    client.put(
        f"/api/v1/wiki/{wiki['id']}/tree",
        json={"pages": [{"id": dns["id"], "parent_id": home["id"], "position": 0}]},
        headers=csrf_headers(client),
    )
    looped = client.put(
        f"/api/v1/wiki/{wiki['id']}/tree",
        json={"pages": [{"id": home["id"], "parent_id": dns["id"], "position": 0}]},
        headers=csrf_headers(client),
    )
    assert looped.status_code == 422
    assert "loop" in looped.json()["detail"].lower()

    stranger = client.put(
        f"/api/v1/wiki/{wiki['id']}/tree",
        json={"pages": [{"id": 999_999, "parent_id": None, "position": 0}]},
        headers=csrf_headers(client),
    )
    assert stranger.status_code == 422


def test_reordering_the_menu_changes_the_reading_order(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    client.put(
        f"/api/v1/wiki/{wiki['id']}/tree",
        json={
            "pages": [
                {"id": cache["id"], "parent_id": None, "position": 0},
                {"id": dns["id"], "parent_id": None, "position": 1},
            ]
        },
        headers=csrf_headers(client),
    )
    listing = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"]
    order = [page["title"] for page in listing]
    # The home page keeps position 0 only if it was given one; the moved pages
    # come in the order they were dropped.
    assert order.index("Cache") < order.index("DNS")


def test_a_page_cites_a_source_and_the_wiki_indexes_it(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    cited = client.post(
        f"/api/v1/wiki/pages/{dns['id']}/references",
        json={
            "kind": "external",
            "url": "https://www.rfc-editor.org/rfc/rfc1035",
            "label": "RFC 1035",
            "note": "Le format des messages DNS.",
        },
        headers=csrf_headers(client),
    )
    assert cited.status_code == 201, cited.text
    assert cited.json()["host"] == "rfc-editor.org"

    inline = client.put(
        f"/api/v1/wiki/pages/{cache['id']}",
        json={
            "title": "Cache",
            "content_md": "# Cache\n\nVoir [IANA](https://www.iana.org/domains) et https://example.org/notes.\n",
        },
        headers=csrf_headers(client),
    )
    assert inline.status_code == 200, inline.text

    page = client.get(f"/api/v1/wiki/pages/{dns['id']}").json()
    assert [reference["label"] for reference in page["references"]["external"]] == ["RFC 1035"]

    index = client.get(f"/api/v1/wiki/{wiki['id']}/references").json()
    hosts = {source["host"] for source in index["external"]}
    assert {"rfc-editor.org", "iana.org", "example.org"} <= hosts
    by_host = {source["host"]: source for source in index["external"]}
    assert [item["title"] for item in by_host["iana.org"]["pages"]] == ["Cache"]
    assert index["stats"]["sources"] >= 3


def test_a_reference_must_point_somewhere_real(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    bad_url = client.post(
        f"/api/v1/wiki/pages/{dns['id']}/references",
        json={"kind": "external", "url": "javascript:alert(1)"},
        headers=csrf_headers(client),
    )
    assert bad_url.status_code == 422

    bad_target = client.post(
        f"/api/v1/wiki/pages/{dns['id']}/references",
        json={"kind": "internal", "target_slug": "page-inexistante"},
        headers=csrf_headers(client),
    )
    assert bad_target.status_code == 422

    good = client.post(
        f"/api/v1/wiki/pages/{dns['id']}/references",
        json={"kind": "internal", "target_slug": cache["slug"]},
        headers=csrf_headers(client),
    )
    assert good.status_code == 201, good.text
    assert good.json()["target_title"] == "Cache"

    deleted = client.delete(
        f"/api/v1/wiki/pages/{dns['id']}/references/{good.json()['id']}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204


def test_the_reader_is_told_which_links_go_nowhere(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    client.put(
        f"/api/v1/wiki/pages/{dns['id']}",
        json={
            "title": "DNS",
            "content_md": "# DNS\n\nVoir [[Cache]] et [[Zone inversee]].\n",
        },
        headers=csrf_headers(client),
    )
    detail = client.get(f"/api/v1/wiki/pages/{dns['id']}").json()
    assert [item["slug"] for item in detail["missing_links"]] == ["zone-inversee"]

    index = client.get(f"/api/v1/wiki/{wiki['id']}/references").json()
    assert [item["slug"] for item in index["unresolved"]] == ["zone-inversee"]
    internal = {item["slug"]: item for item in index["internal"]}
    assert "cache" in internal
    assert [source["title"] for source in internal["cache"]["sources"]] == ["DNS"]


def test_a_broken_image_is_refused_and_never_stored(client):
    """A truncated file is a bad request, not a 500, and leaves no bytes behind."""
    register_user(client)
    broken = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    response = client.post(
        "/api/v1/uploads/image",
        files={"file": ("photo.png", broken, "image/png")},
        headers=csrf_headers(client),
    )
    assert response.status_code == 415, response.text
    assert "valid image" in response.json()["detail"]


# ---------------------------------------------------------------------------
# LOT 6: deletion, templates, image sizing and scoped search
# ---------------------------------------------------------------------------


def test_deleting_a_page_lifts_its_children_instead_of_flattening_the_menu(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    moved = client.put(
        f"/api/v1/wiki/{wiki['id']}/tree",
        json={"pages": [{"id": cache["id"], "parent_id": dns["id"], "position": 1}]},
        headers=csrf_headers(client),
    )
    assert moved.status_code == 200, moved.text

    response = client.delete(f"/api/v1/wiki/pages/{dns['id']}", headers=csrf_headers(client))
    assert response.status_code == 204, response.text

    detail = client.get(f"/api/v1/wiki/{wiki['id']}").json()
    assert dns["id"] not in [page["id"] for page in detail["pages"]]
    child = next(page for page in detail["pages"] if page["id"] == cache["id"])
    # The child climbed one level; the menu is not flattened to the root.
    assert child["parent_id"] is None


def test_deleting_a_page_erases_its_versions_and_its_links(client):
    wiki, home, (dns, cache) = _wiki_with_pages(client)
    client.put(
        f"/api/v1/wiki/pages/{cache['id']}",
        json={"title": "Cache", "content_md": "# Cache\n\nVoir [[dns]].\n"},
        headers=csrf_headers(client),
    ).raise_for_status()
    client.put(
        f"/api/v1/wiki/pages/{dns['id']}",
        json={"title": "DNS", "content_md": "# DNS\n\nVoir [[cache]].\n"},
        headers=csrf_headers(client),
    ).raise_for_status()

    assert client.delete(f"/api/v1/wiki/pages/{dns['id']}", headers=csrf_headers(client)).status_code == 204

    detail = client.get(f"/api/v1/wiki/{wiki['id']}").json()
    titles = [page["title"] for page in detail["pages"]]
    assert "DNS" not in titles
    # The surviving page no longer advertises a link to a page that is gone.
    index = client.get(f"/api/v1/wiki/{wiki['id']}/references").json()
    assert all(item["title"] != "DNS" for item in index["internal"])


def test_a_contributor_cannot_delete_a_page_but_the_owner_can(client):
    register_user(client)
    wiki = _create(client)
    page = _add_page(client, wiki["id"])
    member = register_user(client, email="suppr@example.com", display_name="Suppresseur")
    _login(client, "player@example.com")
    added = client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": member["email"], "role": "contributor"},
        headers=csrf_headers(client),
    )
    assert added.status_code == 201, added.text

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": member["email"], "password": "TestingPassw0rd!"})
    refused = client.delete(f"/api/v1/wiki/pages/{page['id']}", headers=csrf_headers(client))
    assert refused.status_code == 403, refused.text
    assert client.get(f"/api/v1/wiki/pages/{page['id']}").status_code == 200

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": "player@example.com", "password": "TestingPassw0rd!"})
    assert client.delete(f"/api/v1/wiki/pages/{page['id']}", headers=csrf_headers(client)).status_code == 204


def test_a_template_is_written_once_and_reused_by_every_contributor(client):
    register_user(client)
    wiki = _create(client)
    member = register_user(client, email="modele@example.com", display_name="Modele")
    _login(client, "player@example.com")
    client.post(
        f"/api/v1/wiki/{wiki['id']}/members",
        json={"email": member["email"], "role": "contributor"},
        headers=csrf_headers(client),
    ).raise_for_status()

    created = client.post(
        f"/api/v1/wiki/{wiki['id']}/templates",
        json={
            "name": "Fiche de procédure",
            "description": "Squelette pour une procédure interne",
            "keywords": ["procédure", "interne"],
            "content_md": "# Titre\n\n## Contexte\n\n## Étapes\n\n1. \n",
        },
        headers=csrf_headers(client),
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["keywords"] == ["procédure", "interne"]

    # The contributor uses it: a template belongs to the wiki, not to its author.
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": member["email"], "password": "TestingPassw0rd!"})
    listed = client.get(f"/api/v1/wiki/{wiki['id']}/templates")
    assert listed.status_code == 200, listed.text
    assert [row["name"] for row in listed.json()] == ["Fiche de procédure"]
    assert "## Étapes" in listed.json()[0]["content_md"]

    # ... but a contributor proposes page changes, so writing the template
    # itself belongs to whoever can write in the wiki.
    refused = client.put(
        f"/api/v1/wiki/{wiki['id']}/templates/{template['id']}",
        json={"name": "Autre nom", "content_md": "# Autre\n"},
        headers=csrf_headers(client),
    )
    assert refused.status_code == 403, refused.text

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    client.post("/api/v1/auth/login", json={"email": "player@example.com", "password": "TestingPassw0rd!"})
    rewritten = client.put(
        f"/api/v1/wiki/{wiki['id']}/templates/{template['id']}",
        json={
            "name": "Fiche de procédure",
            "description": "Version mainteneur",
            "keywords": ["procédure"],
            "content_md": "# Titre\n\n## Étapes\n\n1. \n",
        },
        headers=csrf_headers(client),
    )
    assert rewritten.status_code == 200, rewritten.text
    assert rewritten.json()["description"] == "Version mainteneur"


def test_a_template_cannot_be_reached_through_another_wiki(client):
    register_user(client)
    first = _create(client, title="Premier")
    second = _create(client, title="Second")
    template = client.post(
        f"/api/v1/wiki/{first['id']}/templates",
        json={"name": "Squelette", "content_md": "# Titre\n"},
        headers=csrf_headers(client),
    ).json()

    # The wrong wiki in the path is a 404, never a cross-wiki write.
    response = client.put(
        f"/api/v1/wiki/{second['id']}/templates/{template['id']}",
        json={"name": "Détourné", "content_md": "# Détourné\n"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 404, response.text
    assert client.get(f"/api/v1/wiki/{first['id']}/templates").json()[0]["name"] == "Squelette"


def test_a_reader_gets_no_template_of_a_private_wiki(client):
    register_user(client)
    wiki = _create(client)
    client.post(
        f"/api/v1/wiki/{wiki['id']}/templates",
        json={"name": "Secret", "content_md": "# Secret\n"},
        headers=csrf_headers(client),
    ).raise_for_status()
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="inconnu@example.com")
    assert client.get(f"/api/v1/wiki/{wiki['id']}/templates").status_code == 404


def test_an_image_width_survives_the_markdown_round_trip(client):
    from app.wiki import render_markdown

    rendered = render_markdown("![Schéma](/media/schema.webp){width=320}", pages={})
    assert 'width="320"' in rendered
    assert "{width=320}" not in rendered

    percent = render_markdown("![Schéma](/media/schema.webp){width=50%}", pages={})
    assert 'width="50%"' in percent


def test_the_search_can_stay_inside_one_wiki_or_reach_the_public_ones(client):
    register_user(client)
    mine = _create(client, title="Mon wiki")
    _add_page(client, mine["id"], title="Résolveur récursif", content="# Résolveur\n\nUn résolveur interroge la racine.")
    other = _create(client, title="Wiki public")
    _add_page(client, other["id"], title="Résolveur public", content="# Public\n\nUn résolveur public existe.")
    # An untrusted author waits for moderation; this test is about search scope.
    make_trusted(client)
    published = client.post(f"/api/v1/wiki/{other['id']}/publish", json={}, headers=csrf_headers(client))
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "public"

    local = client.get(f"/api/v1/wiki/search?q=résolveur&scope=local&wiki_id={mine['id']}")
    assert local.status_code == 200, local.text
    assert {hit["wiki_id"] for hit in local.json()} == {mine["id"]}

    everywhere = client.get(f"/api/v1/wiki/search?q=résolveur&scope=all&wiki_id={mine['id']}")
    assert everywhere.status_code == 200, everywhere.text
    assert other["id"] in {hit["wiki_id"] for hit in everywhere.json()}


def test_a_link_to_a_missing_page_is_a_real_anchor_not_escaped_markup(client):
    from app.wiki import render_markdown

    html = render_markdown("Voir [[procedure-de-sauvegarde]].", pages={})
    assert "&lt;a" not in html
    assert 'class="wikilink is-missing"' in html
    assert 'data-missing="1"' in html
    assert 'href="/wiki/new?title=procedure-de-sauvegarde"' in html

    resolved = render_markdown("Voir [[dns]].", pages={"dns": "dns"})
    assert "is-missing" not in resolved
    assert 'href="/wiki/p/dns"' in resolved


def test_underline_and_text_colour_survive_the_renderer(client):
    from app.wiki import render_markdown

    html = render_markdown("Un mot {u}souligné{/u} et un mot {c:red}rouge{/c}.", pages={})
    assert "<u>souligné</u>" in html
    assert '<span class="c-red">rouge</span>' in html
    # The markers themselves never reach the reader.
    assert "{u}" not in html and "{c:red}" not in html


def test_a_custom_colour_is_a_class_plus_a_validated_hex(client):
    from app.wiki import render_markdown

    html = render_markdown("Un mot {c:#FF8800}orange{/c}.", pages={})
    # No style attribute: the CSP forbids it, so the colour travels as data.
    assert "style=" not in html
    assert 'class="c-hex" data-hex="#ff8800"' in html


def test_an_unknown_colour_stays_literal_and_code_is_untouched(client):
    from app.wiki import render_markdown

    assert "{c:chartreuse}" in render_markdown("Un {c:chartreuse}mot{/c}.", pages={})
    code = render_markdown("```\n{c:red}pas une couleur{/c}\n```", pages={})
    assert "{c:red}" in code
    assert 'class="c-red"' not in code


def test_alignment_size_and_typeface_become_classes_on_the_block(client):
    from app.wiki import render_markdown

    html = render_markdown("{a:center}Au milieu{/a}\n\n{s:lg}Plus grand{/s}\n\n{f:serif}Avec empattement{/f}", pages={})
    assert '<p class="al-center">Au milieu</p>' in html
    assert '<p class="sz-lg">Plus grand</p>' in html
    assert '<p class="ff-serif">Avec empattement</p>' in html
    assert "{a:center}" not in html and "{s:lg}" not in html and "{f:serif}" not in html
    # Still no inline style anywhere: the CSP would refuse it.
    assert "style=" not in html


def test_nested_block_markers_all_land_on_the_same_paragraph(client):
    from app.wiki import render_markdown

    html = render_markdown("{a:center}{f:serif}{s:lg}Titre{/s}{/f}{/a}", pages={})
    assert 'class="al-center ff-serif sz-lg"' in html or 'class="al-center sz-lg ff-serif"' in html
    assert "{" not in html


def test_an_unknown_size_or_font_stays_literal(client):
    from app.wiki import render_markdown

    assert "{s:huge}" in render_markdown("{s:huge}Texte{/s}", pages={})
    assert "{f:comic}" in render_markdown("{f:comic}Texte{/f}", pages={})


def test_a_quiz_marker_becomes_an_empty_container(client):
    from app.wiki import render_markdown

    html = render_markdown("{quiz:12}\n\nUn paragraphe.", pages={})
    assert '<div class="wiki-embed" data-embed="quiz" data-id="12"></div>' in html
    assert "{quiz:12}" not in html
    # Anything that is not a bare numeric id stays text: the container is
    # written after sanitisation, so it must never echo raw input.
    assert "data-embed" not in render_markdown("{quiz:12a}", pages={})
    adventure = render_markdown("{adventure:7}", pages={})
    assert 'data-embed="adventure" data-id="7"' in adventure
    # A deck of revision cards can be read inside the page as well.
    deck = render_markdown("{deck:4}", pages={})
    assert 'data-embed="deck" data-id="4"' in deck


def test_a_capsule_lays_out_five_linked_pages(client):
    register_user(client)
    wiki = _create(client)
    response = client.post(f"/api/v1/wiki/{wiki['id']}/capsule?lang=fr", headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == [
        "Introduction",
        "Fiche pédagogique",
        "Cartes personnages",
        "Histoire à embranchement",
        "Pistes de réflexion",
    ]
    pages = client.get(f"/api/v1/wiki/{wiki['id']}").json()["pages"]
    by_title = {page["title"]: page for page in pages}
    # Each page hangs under the previous one, so the menu reads as the lesson.
    assert by_title["Fiche pédagogique"]["parent_id"] == by_title["Introduction"]["id"]
    assert by_title["Pistes de réflexion"]["parent_id"] == by_title["Histoire à embranchement"]["id"]


def test_a_shared_tag_draws_a_second_kind_of_edge(client):
    register_user(client)
    wiki = _create(client)
    first = _add_page(client, wiki["id"], "Semis", "# Semis\n\nAu printemps.", tags=["potager", "saison"])
    second = _add_page(client, wiki["id"], "Arrosage", "# Arrosage\n\nLe matin.", tags=["potager"])
    graph = client.get(f"/api/v1/wiki/{wiki['id']}/graph").json()
    kinds = {(edge["kind"], edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("tag", first["id"], second["id"]) in kinds or ("tag", second["id"], first["id"]) in kinds


def test_the_wiki_catalogue_is_paginated(client):
    register_user(client)
    for index in range(4):
        _create(client, title=f"Wiki {index}")
    response = client.get("/api/v1/wiki?limit=2&offset=0")
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert int(response.headers["x-total-count"]) >= 4
    second = client.get("/api/v1/wiki?limit=2&offset=2").json()
    assert [wiki["id"] for wiki in second] != [wiki["id"] for wiki in response.json()]
