# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Stories drafted by the model.

The provider is faked at the ``_chat`` boundary. What is under test is our own
coercion: a story the model answers with dangling targets, unknown attributes and
no ending must still come back walkable, or the author receives a draft they
cannot play.
"""

from __future__ import annotations

import json

import pytest

from app import ai as ai_module
from app.config import settings
from tests.conftest import csrf_headers, register_user

MESSY_STORY = {
    "title": "La forêt de Brocéliande",
    "description": "Une promenade qui tourne mal.",
    "start": "intro",
    "victory_text": "Vous rentrez avec la fée.",
    "death_text": "La brume vous garde.",
    "attributes": [
        {"key": "Courage Équestre", "label": "Courage équestre", "initial_value": 0},
        {"key": "courage-equestre", "label": "Doublon", "initial_value": 0},
        {"key": "savoir", "label": "Savoir", "initial_value": 1},
    ],
    "nodes": [
        {
            "key": "intro",
            "kind": "question",
            "text": "Un chemin se sépare sous les arbres.",
            "choices": [
                {
                    "text": "Prendre le sentier de gauche",
                    "target": "clairiere",
                    "effects": [{"attribute": "courage équestre", "delta": 2}],
                },
                {"text": "Suivre la lumière", "target": "nulle-part", "effects": []},
            ],
        },
        {
            "key": "clairiere",
            "kind": "question",
            "text": "Une clairière, et un choix de plus.",
            "choices": [
                {"text": "Appeler", "target": "fin-bonne"},
                {"text": "Se taire", "target": "fin-mauvaise", "effects": [{"attribute": "inconnu", "delta": 1}]},
            ],
        },
        {"key": "fin-bonne", "kind": "question", "text": "La fée apparaît."},
        {"key": "fin-mauvaise", "kind": "ending", "text": "La brume se referme."},
    ],
}


@pytest.fixture()
def fake_ai(monkeypatch):
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_model", "fake-model")
    monkeypatch.setattr(settings, "ai_base_url", "http://fake-provider/v1")
    monkeypatch.setattr(settings, "ai_api_key", "")
    monkeypatch.setattr(settings, "search_base_url", "")
    monkeypatch.setattr(settings, "ai_min_interval_seconds", 0)
    monkeypatch.setattr(settings, "ai_rate_limit", 1000)

    def respond(payload: dict):
        monkeypatch.setattr(ai_module, "_chat", lambda *a, **k: json.dumps(payload))
        return payload

    return respond


def test_a_generated_story_comes_back_walkable(client, fake_ai):
    register_user(client, email="author@example.org")
    fake_ai(MESSY_STORY)

    response = client.post(
        "/api/v1/ai/adventures",
        json={"topic": "Une balade en forêt de Brocéliande", "language": "fr", "scene_count": 4},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    graph = body["draft"]
    quiz = body["quiz"]

    assert quiz["mode"] == "adventure"
    keys = {node["key"] for node in graph["nodes"]}
    assert graph["start"] in keys
    # The model announced no ending scene for the good path and pointed a choice
    # at a scene that does not exist: both have to be repaired, not rejected.
    assert any(node["kind"] == "ending" for node in graph["nodes"])
    for node in graph["nodes"]:
        for choice in node.get("choices", []):
            assert choice["target"] in keys

    # Two labels for the same attribute must not collapse into one key, and a
    # reference written with an accent and a space still has to be understood.
    attribute_keys = [attribute["key"] for attribute in graph["attributes"]]
    assert len(set(attribute_keys)) == len(attribute_keys)
    assert "courage-equestre" in attribute_keys
    intro = next(node for node in graph["nodes"] if node["key"] == "intro")
    assert intro["choices"][0]["effects"][0]["attribute"] in attribute_keys
    # An effect on an attribute that was never declared is dropped, not stored.
    clairiere = next(node for node in graph["nodes"] if node["key"] == "clairiere")
    assert clairiere["choices"][1]["effects"] == []


def test_generation_is_refused_when_no_provider_is_configured(client, monkeypatch):
    register_user(client, email="author@example.org")
    monkeypatch.setattr(settings, "ai_enabled", False)
    response = client.post(
        "/api/v1/ai/adventures",
        json={"topic": "Une balade en forêt", "language": "fr"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 503


def test_a_revision_leaves_the_stored_story_alone(client, fake_ai):
    register_user(client, email="author@example.org")
    fake_ai(MESSY_STORY)
    created = client.post(
        "/api/v1/ai/adventures",
        json={"topic": "Une balade en forêt de Brocéliande", "language": "fr", "scene_count": 4},
        headers=csrf_headers(client),
    ).json()
    quiz_id = created["quiz"]["id"]
    before = created["quiz"]["adventure"]["nodes"]

    revised = json.loads(json.dumps(MESSY_STORY))
    revised["nodes"][0]["text"] = "Un chemin se sépare, et la nuit tombe."
    fake_ai(revised)

    response = client.post(
        f"/api/v1/ai/adventures/{quiz_id}/revise",
        json={"instruction": "Rends la première scène plus sombre."},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["quiz"] is None
    assert "nuit tombe" in json.dumps(response.json()["draft"], ensure_ascii=False)

    stored = client.get(f"/api/v1/quizzes/{quiz_id}").json()
    assert stored["adventure"]["nodes"] == before


def test_a_revision_can_be_written_back(client, fake_ai):
    register_user(client, email="author@example.org")
    fake_ai(MESSY_STORY)
    quiz_id = client.post(
        "/api/v1/ai/adventures",
        json={"topic": "Une balade en forêt de Brocéliande", "language": "fr", "scene_count": 4},
        headers=csrf_headers(client),
    ).json()["quiz"]["id"]

    revised = json.loads(json.dumps(MESSY_STORY))
    revised["nodes"][0]["text"] = "Un chemin se sépare, et la nuit tombe."
    fake_ai(revised)

    response = client.post(
        f"/api/v1/ai/adventures/{quiz_id}/revise",
        json={"instruction": "Rends la première scène plus sombre.", "save": True},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    assert "nuit tombe" in json.dumps(response.json()["quiz"]["adventure"], ensure_ascii=False)


def test_a_stranger_cannot_revise_someone_elses_story(client, fake_ai):
    register_user(client, email="author@example.org")
    fake_ai(MESSY_STORY)
    quiz_id = client.post(
        "/api/v1/ai/adventures",
        json={"topic": "Une balade en forêt de Brocéliande", "language": "fr", "scene_count": 4},
        headers=csrf_headers(client),
    ).json()["quiz"]["id"]

    client.cookies.clear()
    register_user(client, email="intruder@example.org")
    fake_ai(MESSY_STORY)
    response = client.post(
        f"/api/v1/ai/adventures/{quiz_id}/revise",
        json={"instruction": "Change tout."},
        headers=csrf_headers(client),
    )
    assert response.status_code == 403
