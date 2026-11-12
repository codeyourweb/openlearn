# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Two switches for a classroom that has no Internet.

A trainer on a closed network projects a page: a QR code pointing at an internal
host is useless there, and links to X or LinkedIn lead nowhere. The administrator
gets two independent switches — because a school may still want the code without
the networks, and a conference may want the opposite.

`/api/v1/meta` is what every page reads, so the switches have to travel there:
a setting nobody can see is a setting that does nothing.
"""

from __future__ import annotations

from tests.conftest import csrf_headers, make_admin, register_user


def test_both_switches_are_on_by_default(client):
    meta = client.get("/api/v1/meta").json()
    # An instance that never touched the setting behaves as it always did.
    assert meta["sharing"] == {"qr": True, "social": True}


def test_the_two_switches_are_independent(client):
    register_user(client)
    make_admin(client)

    response = client.put(
        "/api/v1/admin/settings",
        json={"values": {"sharing.qr_enabled": False}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text

    # Disabling the code must not take the networks with it.
    assert client.get("/api/v1/meta").json()["sharing"] == {"qr": False, "social": True}

    client.put(
        "/api/v1/admin/settings",
        json={"values": {"sharing.social_enabled": False}},
        headers=csrf_headers(client),
    )
    assert client.get("/api/v1/meta").json()["sharing"] == {"qr": False, "social": False}

    # And both come back on their own.
    client.put(
        "/api/v1/admin/settings",
        json={"values": {"sharing.qr_enabled": True}},
        headers=csrf_headers(client),
    )
    assert client.get("/api/v1/meta").json()["sharing"] == {"qr": True, "social": False}


def test_the_switches_appear_in_their_own_section(client):
    register_user(client)
    make_admin(client)

    sections = client.get("/api/v1/admin/settings").json()["sections"]
    assert "sharing" in sections
    rows = {row["key"]: row for row in sections["sharing"]}
    assert set(rows) == {"sharing.qr_enabled", "sharing.social_enabled"}
    assert all(row["type"] == "bool" for row in rows.values())
    # Readable values, so the form can paint two checkboxes and no free text.
    assert all(row["value"] is True for row in rows.values())


def test_a_reader_without_rights_cannot_turn_them_off(client):
    register_user(client)
    response = client.put(
        "/api/v1/admin/settings",
        json={"values": {"sharing.qr_enabled": False}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403
    assert client.get("/api/v1/meta").json()["sharing"]["qr"] is True


def test_an_unknown_sharing_key_is_refused(client):
    register_user(client)
    make_admin(client)
    response = client.put(
        "/api/v1/admin/settings",
        json={"values": {"sharing.everything": True}},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
