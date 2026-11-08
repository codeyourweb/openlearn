# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Branching ("adventure") quizzes: graph validation, runs and endings."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from hashlib import sha256

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AdventureRun, utcnow
from tests.conftest import (
    csrf_headers,
    publish_quiz,
    register_user,
)


def story_payload(title: str = "The stress test") -> dict:
    """A small but complete story.

    start --(calm: +2 composure)--> calm   (question)
    start --(panic: -3 composure, +1 stress)--> ending_fail
    calm  --(delegate)--> ending_lead   (highest composure)
    calm  --(alone)--> ending_lead      (same ending, different path)
    """
    return {
        "title": title,
        "description": "A branching scenario about handling pressure.",
        "mode": "adventure",
        "is_public": False,
        "adventure": {
            "start": "start",
            "death_text_html": "<p>You burned out.</p>",
            "victory_text_html": "<p>You thrive under pressure.</p>",
            "attributes": [
                {
                    "key": "composure",
                    "label": "Composure",
                    "initial_value": 5,
                    "min_value": 0,
                    "max_value": 20,
                    "death_at_or_below": 1,
                    "victory_at_or_above": 15,
                },
                {
                    "key": "stress",
                    "label": "Stress",
                    "initial_value": 0,
                    "min_value": 0,
                    "max_value": 20,
                },
            ],
            "nodes": [
                {
                    "key": "start",
                    "kind": "question",
                    "text_html": "<p>An incident drops at 2am. What do you do?</p>",
                    "pos_x": 0,
                    "pos_y": 0,
                    "choices": [
                        {
                            "key": "calm",
                            "text": "Breathe, then triage",
                            "target": "calm",
                            "effects": [{"attribute": "composure", "delta": 2}],
                        },
                        {
                            "key": "panic",
                            "text": "Panic and promise everything",
                            "target": "ending_fail",
                            "effects": [
                                {"attribute": "composure", "delta": -4},
                                {"attribute": "stress", "delta": 3},
                            ],
                        },
                    ],
                },
                {
                    "key": "calm",
                    "kind": "question",
                    "text_html": "<p>The team looks at you. Next?</p>",
                    "pos_x": 300,
                    "pos_y": 0,
                    "choices": [
                        {
                            "key": "delegate",
                            "text": "Split the work and check in",
                            "target": "ending_lead",
                            "effects": [{"attribute": "composure", "delta": 3}],
                        },
                        {
                            "key": "alone",
                            "text": "Do everything yourself",
                            "target": "ending_lead",
                            "effects": [{"attribute": "stress", "delta": 4}],
                        },
                    ],
                },
                {
                    "key": "ending_lead",
                    "kind": "ending",
                    "text_html": "<p>You lead the response.</p>",
                    "background_path": "/media/endings/lead.jpg",
                    "outcomes": [
                        {
                            "kind": "highest",
                            "attribute": "stress",
                            "text_html": "<p>Calm on the outside, tense inside.</p>",
                            "priority": 0,
                        },
                        {
                            "kind": "highest",
                            "attribute": "composure",
                            "text_html": "<p>A composed leader.</p>",
                            "priority": 1,
                        },
                        {
                            "kind": "default",
                            "text_html": "<p>You made it through.</p>",
                            "priority": 9,
                        },
                    ],
                    "choices": [],
                },
                {
                    "key": "ending_fail",
                    "kind": "ending",
                    "text_html": "<p>The night went badly.</p>",
                    "outcomes": [
                        {
                            "kind": "range",
                            "attribute": "stress",
                            "range_min": 3,
                            "range_max": 20,
                            "text_html": "<p>Stress took over.</p>",
                            "priority": 0,
                        }
                    ],
                    "choices": [],
                },
            ],
        },
    }


def create_adventure(client, payload: dict | None = None) -> dict:
    response = client.post(
        "/api/v1/quizzes",
        json=payload or story_payload(),
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def start_run(client, quiz_id: int, **body) -> dict:
    response = client.post(f"/api/v1/adventure/quizzes/{quiz_id}/runs", json=body or {})
    assert response.status_code == 201, response.text
    return response.json()


def choose(client, token: str, choice: str) -> dict:
    response = client.post(f"/api/v1/adventure/runs/{token}/choose", json={"choice": choice})
    return response


# ---------------------------------------------------------------------------
# Authoring and validation
# ---------------------------------------------------------------------------

def test_create_and_read_adventure_graph(client):
    register_user(client)
    quiz = create_adventure(client)
    assert quiz["mode"] == "adventure"
    assert quiz["question_count"] == 0

    graph = quiz["adventure"]
    assert graph["start"] == "start"
    assert [attribute["key"] for attribute in graph["attributes"]] == ["composure", "stress"]
    keys = [node["key"] for node in graph["nodes"]]
    assert keys == ["start", "calm", "ending_lead", "ending_fail"]
    start = graph["nodes"][0]
    assert [choice["key"] for choice in start["choices"]] == ["calm", "panic"]
    assert start["choices"][1]["effects"] == [
        {"attribute": "composure", "delta": -4},
        {"attribute": "stress", "delta": 3},
    ]

    # The editor round-trips: saving the graph again keeps it identical.
    saved = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    replay = copy.deepcopy(story_payload())
    replay["adventure"] = saved["adventure"]
    replay["adventure"].pop("death_plain", None)
    response = client.put(
        f"/api/v1/quizzes/{quiz['id']}", json=replay, headers=csrf_headers(client)
    )
    assert response.status_code == 200, response.text
    assert response.json()["adventure"]["start"] == "start"


def test_linear_quiz_cannot_carry_a_story(client):
    register_user(client)
    payload = story_payload()
    payload["mode"] = "qcm"
    payload["questions"] = [
        {
            "text_html": "<p>Q</p>",
            "options": [
                {"text": "A", "is_correct": True},
                {"text": "B", "is_correct": False},
            ],
        }
    ]
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422


def test_adventure_without_graph_is_rejected(client):
    register_user(client)
    payload = story_payload()
    payload.pop("adventure")
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422


def test_choice_pointing_to_unknown_node_is_rejected(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][0]["choices"][0]["target"] = "ghost"
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422
    assert "unknown node" in response.text.lower()


def test_unreachable_node_blocks_publication_not_drafts(client):
    """An unfinished story must stay editable, but never become public."""
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"].append(
        {
            "key": "orphan",
            "kind": "question",
            "text_html": "<p>Nobody comes here.</p>",
            "choices": [
                {"key": "a", "text": "A", "target": "ending_lead", "effects": []},
                {"key": "b", "text": "B", "target": "ending_lead", "effects": []},
            ],
            "outcomes": [],
        }
    )
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 201
    quiz_id = response.json()["id"]

    published = client.post(
        f"/api/v1/quizzes/{quiz_id}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert published.status_code == 422
    assert "unreachable" in published.text.lower()


def test_question_needs_two_to_eight_choices(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][0]["choices"] = payload["adventure"]["nodes"][0]["choices"][:1]
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422


def test_ending_needs_a_text(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][2]["outcomes"] = []
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422
    assert "ending text" in response.text.lower()


def test_effect_on_unknown_attribute_is_rejected(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][0]["choices"][0]["effects"][0]["attribute"] = "luck"
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422


def test_script_in_story_text_is_stripped(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][0]["text_html"] = (
        '<p onclick="steal()">An incident drops</p><script>alert(1)</script>'
    )
    payload["adventure"]["nodes"][2]["outcomes"][0]["text_html"] = (
        '<p>Composed</p><a href="https://evil.example">click</a>'
    )
    quiz = create_adventure(client, payload)
    node_text = quiz["adventure"]["nodes"][0]["text_html"]
    assert "<script" not in node_text and "onclick" not in node_text
    outcome_text = quiz["adventure"]["nodes"][2]["outcomes"][0]["text_html"]
    assert "<a" not in outcome_text and "evil.example" not in outcome_text


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

def test_effects_are_hidden_from_anonymous_visitors(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    public = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    for node in public["adventure"]["nodes"]:
        for choice in node["choices"]:
            assert choice["effects"] == []
    # The story itself stays readable, otherwise nobody could play it.
    assert public["adventure"]["nodes"][0]["choices"][0]["text"] == "Breathe, then triage"


def test_private_adventure_cannot_be_played_by_a_stranger(client):
    register_user(client)
    quiz = create_adventure(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    response = client.post(f"/api/v1/adventure/quizzes/{quiz['id']}/runs", json={})
    assert response.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Playing
# ---------------------------------------------------------------------------

def test_run_walks_the_story_and_applies_effects(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])

    started = start_run(client, quiz["id"])
    token = started["run_token"]
    state = started["state"]
    assert state["node"]["key"] == "start"
    assert state["attributes"][0]["value"] == 5

    step = choose(client, token, "calm")
    assert step.status_code == 200, step.text
    payload = step.json()
    assert payload["node"]["key"] == "calm"
    assert payload["finished"] is False
    values = {attribute["key"]: attribute["value"] for attribute in payload["attributes"]}
    assert values == {"composure": 7, "stress": 0}

    final = choose(client, token, "delegate").json()
    assert final["finished"] is True
    values = {attribute["key"]: attribute["value"] for attribute in final["attributes"]}
    assert values == {"composure": 10, "stress": 0}
    # "stress" is the highest attribute only when it overtakes; here composure
    # wins over stress=0, and the priority-1 outcome matches.
    assert "composed leader" in final["ending"]["text_html"]


def test_highest_attribute_selects_the_ending_text(client):
    """The ending text follows whichever attribute ended up on top."""
    register_user(client)

    # Composure wins: the calm path keeps stress at zero.
    calm_quiz = create_adventure(client)
    publish_quiz(client, calm_quiz["id"])
    token = start_run(client, calm_quiz["id"])["run_token"]
    choose(client, token, "calm")
    calm_ending = choose(client, token, "delegate").json()
    assert "composed leader" in calm_ending["ending"]["text_html"]

    # Stress wins: the same ending, but the branch raises stress above composure.
    payload = story_payload("Stress wins")
    payload["adventure"]["nodes"][1]["choices"][1]["effects"] = [
        {"attribute": "stress", "delta": 9}
    ]
    stress_quiz = create_adventure(client, payload)
    publish_quiz(client, stress_quiz["id"])
    token = start_run(client, stress_quiz["id"])["run_token"]
    choose(client, token, "calm")
    stress_ending = choose(client, token, "alone").json()
    values = {attribute["key"]: attribute["value"] for attribute in stress_ending["attributes"]}
    assert values == {"composure": 7, "stress": 9}
    assert "tense inside" in stress_ending["ending"]["text_html"]


def test_premature_death_stops_the_run(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]

    final = choose(client, token, "panic").json()
    assert final["finished"] is True
    assert final["ending"]["kind"] == "death"
    assert "burned out" in final["ending"]["text_html"]


def test_premature_victory_stops_the_run(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["attributes"][0]["victory_at_or_above"] = 7
    quiz = create_adventure(client, payload)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]

    final = choose(client, token, "calm").json()
    assert final["finished"] is True
    assert final["ending"]["kind"] == "victory"
    assert "thrive under pressure" in final["ending"]["text_html"]


def test_exit_branch_ends_without_an_ending_node(client):
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][1]["choices"][0]["target"] = None
    quiz = create_adventure(client, payload)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]
    choose(client, token, "calm")

    final = choose(client, token, "delegate").json()
    assert final["finished"] is True
    assert final["ending"]["kind"] == "exit"


def test_exit_branch_borrows_the_failure_backdrop(client):
    """An abrupt exit has no artwork of its own, so it reuses the failure one."""
    register_user(client)
    payload = story_payload()
    payload["adventure"]["nodes"][1]["choices"][0]["target"] = None
    payload["adventure"]["death_background_path"] = "/media/chair.webp"
    quiz = create_adventure(client, payload)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]
    choose(client, token, "calm")

    final = choose(client, token, "delegate").json()
    assert final["ending"]["kind"] == "exit"
    assert final["ending"]["background_path"] == "/media/chair.webp"


def test_unknown_choice_is_refused(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]
    assert choose(client, token, "teleport").status_code == 422


def test_finished_run_is_immutable(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]
    choose(client, token, "panic")
    assert choose(client, token, "calm").status_code == 409


def timed_story_payload(**overrides) -> dict:
    payload = story_payload("A story on the clock")
    payload["adventure"].update(
        {
            "timer_mode": "per_node",
            "time_limit_seconds": 30,
            "timeout_effect": "penalty",
            "timeout_penalty": 2,
            "timeout_penalty_attribute": "composure",
        }
    )
    payload["adventure"].update(overrides)
    return payload


def run_the_clock_out(token: str) -> None:
    """Move the scene deadline into the past instead of waiting for it."""
    with SessionLocal() as db:
        run = db.scalar(
            select(AdventureRun).where(AdventureRun.token_hash == sha256(token.encode()).hexdigest())
        )
        run.node_deadline = utcnow() - timedelta(seconds=1)
        db.commit()


def test_a_scene_clock_arms_when_the_run_starts(client):
    register_user(client)
    quiz = client.post(
        "/api/v1/quizzes", json=timed_story_payload(), headers=csrf_headers(client)
    ).json()
    publish_quiz(client, quiz["id"])

    started = start_run(client, quiz["id"])
    assert started["state"]["run"]["node_deadline"], "a timed story must expose its deadline"
    assert started["state"]["run"]["timer_mode"] == "per_node"

    # The next scene gets a fresh deadline of its own.
    first = started["state"]["run"]["node_deadline"]
    played = choose(client, started["run_token"], "calm").json()
    assert played["run"]["node_deadline"] and played["run"]["node_deadline"] != first


def test_a_timeout_before_the_deadline_is_refused(client):
    register_user(client)
    quiz = client.post(
        "/api/v1/quizzes", json=timed_story_payload(), headers=csrf_headers(client)
    ).json()
    publish_quiz(client, quiz["id"])
    started = start_run(client, quiz["id"])

    response = client.post(
        f"/api/v1/adventure/runs/{started['run_token']}/timeout", headers=csrf_headers(client)
    )
    assert response.status_code == 409


def test_the_server_applies_the_penalty_once_the_deadline_has_passed(client):
    register_user(client)
    quiz = client.post(
        "/api/v1/quizzes", json=timed_story_payload(), headers=csrf_headers(client)
    ).json()
    publish_quiz(client, quiz["id"])
    started = start_run(client, quiz["id"])

    run_the_clock_out(started["run_token"])

    before = {entry["key"]: entry["value"] for entry in started["state"]["attributes"]}["composure"]
    expired = client.post(
        f"/api/v1/adventure/runs/{started['run_token']}/timeout", headers=csrf_headers(client)
    )
    assert expired.status_code == 200, expired.text
    body = expired.json()
    assert {entry["key"]: entry["value"] for entry in body["attributes"]}["composure"] == before - 2
    assert body["run"]["steps"] == 1
    assert body["node"]["key"] == "start"


def test_a_timed_story_with_a_death_effect_ends_on_the_spot(client):
    register_user(client)
    payload = timed_story_payload(timeout_effect="death")
    quiz = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client)).json()
    publish_quiz(client, quiz["id"])
    started = start_run(client, quiz["id"])

    run_the_clock_out(started["run_token"])

    ended = client.post(
        f"/api/v1/adventure/runs/{started['run_token']}/timeout", headers=csrf_headers(client)
    ).json()
    assert ended["finished"] is True
    assert ended["ending"]["kind"] == "death"
    assert "burned out" in ended["ending"]["text_plain"]


def test_an_untimed_story_has_no_clock_and_refuses_timeouts(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    started = start_run(client, quiz["id"])

    assert started["state"]["run"]["node_deadline"] is None
    response = client.post(
        f"/api/v1/adventure/runs/{started['run_token']}/timeout", headers=csrf_headers(client)
    )
    assert response.status_code == 409


def test_unknown_run_token_is_a_404(client):
    register_user(client)
    assert client.get("/api/v1/adventure/runs/not-a-real-token").status_code == 404


def test_run_survives_a_quiz_edit(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]
    choose(client, token, "calm")

    # Rewrite the story: the run keeps playing the snapshot it started with.
    edited = story_payload("Renamed story")
    edited["adventure"]["nodes"][1]["text_html"] = "<p>Rewritten middle.</p>"
    response = client.put(
        f"/api/v1/quizzes/{quiz['id']}", json=edited, headers=csrf_headers(client)
    )
    assert response.status_code == 200, response.text

    played = choose(client, token, "delegate").json()
    assert played["finished"] is True


def test_run_history_is_listed_for_the_owner_of_the_run(client):
    register_user(client)
    quiz = create_adventure(client)
    publish_quiz(client, quiz["id"])
    token = start_run(client, quiz["id"])["run_token"]
    choose(client, token, "panic")

    runs = client.get(f"/api/v1/adventure/quizzes/{quiz['id']}/runs").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "finished"
    assert runs[0]["ending_kind"] == "death"

def test_attribute_keys_are_derived_from_what_the_author_wrote(client):
    """An attribute is named "Points forts", not "points_forts".

    The key is an internal identifier, but it used to be typed by the author and
    validated by an English regex: a French label was answered with "Attribute
    keys may only contain letters, digits, '-' and '_'". The words a teacher
    writes are now turned into a key instead of being refused.
    """
    register_user(client)
    # The same rename the editor performs: the references follow the key.
    payload = json.loads(json.dumps(story_payload()).replace("composure", "Sang-froid"))
    for attribute in payload["adventure"]["attributes"]:
        if attribute["key"] == "Sang-froid":
            attribute["label"] = "Sang-froid"
            break
    payload["adventure"]["attributes"].append(
        {
            "key": "confiance en soi",
            "label": "Confiance en soi",
            "initial_value": 2,
            "min_value": 0,
            "max_value": 10,
        }
    )

    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code in (200, 201), response.text

    stored = client.get(f"/api/v1/quizzes/{response.json()['id']}").json()
    keys = [attribute["key"] for attribute in stored["adventure"]["attributes"]]
    assert "sang-froid" in keys
    assert "confiance-en-soi" in keys
    assert len(keys) == len(payload["adventure"]["attributes"])

