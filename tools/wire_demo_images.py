# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Attach the illustration set to the two demo quizzes through the public API.

Runs inside the openlearn container (has httpx and the app's env). Every image
goes through POST /uploads/question-image so the app keeps doing its own
validation, downscale and WEBP re-encode.
"""

from __future__ import annotations

import os
import pathlib
import sys

import httpx

BASE = "http://127.0.0.1:8000"
SRC = pathlib.Path("/app/data/illus")

SWIPE_ORDER = [
    "swipe-password",
    "swipe-usb",
    "swipe-2fa",
    "swipe-phishing",
    "swipe-disk",
    "swipe-patch",
    "swipe-logs",
    "swipe-backup",
]

NODE_IMAGES = {
    "start": "story-start",
    "analyse": "story-analyse",
    "astreinte": "story-escalation",
    "surveillance": "story-surveillance",
}

ENDING_BACKGROUNDS = {
    "isolement": "ending-contained",
    "rapport": "ending-report",
    "surveillance_fin": "ending-exfiltration",
}

# The demo story needs real thresholds, otherwise "raccrocher" would fall through
# to an empty exit branch instead of the failure screen.
DEMO_ATTRIBUTES = [
    {
        "key": "sang_froid",
        "label": "Sang-froid",
        "translations": {},
        "initial_value": 5,
        "min_value": 0,
        "max_value": 10,
        "death_at_or_below": 0,
        "victory_at_or_above": None,
    },
    {
        "key": "preuves",
        "label": "Preuves",
        "translations": {},
        "initial_value": 0,
        "min_value": 0,
        "max_value": 10,
        "death_at_or_below": None,
        "victory_at_or_above": 7,
    },
]

GLOBAL_BACKGROUNDS = {
    "death_background_path": "ending-death",
    "victory_background_path": "ending-victory",
}


def login() -> httpx.Client:
    client = httpx.Client(base_url=BASE, timeout=60)
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": os.environ["OL_ADMIN_EMAIL"],
            "password": os.environ["OL_ADMIN_PASSWORD"],
        },
    )
    response.raise_for_status()
    csrf = client.cookies.get("ol_csrf")
    client.headers["X-CSRF-Token"] = csrf or ""
    return client


def upload(client: httpx.Client, name: str) -> str:
    path = SRC / f"{name}.jpg"
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/uploads/question-image",
            files={"file": (path.name, handle, "image/jpeg")},
        )
    if response.status_code != 201:
        print(f"upload {name}: {response.status_code} {response.text[:200]}")
        sys.exit(1)
    body = response.json()
    print(f"upload {name:22} -> {body['path']} {body['width']}x{body['height']} {body['bytes'] // 1024} KB")
    return body["path"]


def question_payload(question: dict, image_path: str | None) -> dict:
    return {
        "text_html": question["text_html"],
        "translations": question.get("translations") or {},
        "image_path": image_path,
        "time_limit_seconds": question.get("time_limit_seconds", 30),
        "points": question.get("points", 100),
        "options": [
            {
                "text": option["text"],
                "translations": option.get("translations") or {},
                "is_correct": bool(option.get("is_correct")),
            }
            for option in question["options"]
        ],
    }


def quiz_shell(quiz: dict) -> dict:
    return {
        "title": quiz["title"],
        "description": quiz.get("description") or "",
        "wrong_answer_policy": quiz.get("wrong_answer_policy", "zero"),
        "mode": quiz["mode"],
        "is_public": quiz.get("status") == "public",
        "default_language": quiz.get("default_language") or "fr",
        "title_translations": quiz.get("title_translations") or {},
        "description_translations": quiz.get("description_translations") or {},
    }


def wire_swipe(client: httpx.Client, quiz_id: int, uploads: dict[str, str]) -> None:
    quiz = client.get(f"/api/v1/quizzes/{quiz_id}").json()
    questions = quiz["questions"]
    assert len(questions) == len(SWIPE_ORDER), f"expected {len(SWIPE_ORDER)} cards, got {len(questions)}"
    payload = quiz_shell(quiz)
    payload["questions"] = [
        question_payload(question, uploads[name]) for question, name in zip(questions, SWIPE_ORDER)
    ]
    payload["adventure"] = None
    response = client.put(f"/api/v1/quizzes/{quiz_id}", json=payload)
    print("PUT swipe", response.status_code, response.text[:300] if response.status_code >= 300 else "ok")


def wire_adventure(client: httpx.Client, quiz_id: int, uploads: dict[str, str]) -> None:
    quiz = client.get(f"/api/v1/quizzes/{quiz_id}").json()
    adventure = quiz["adventure"]
    payload = quiz_shell(quiz)
    payload["questions"] = []

    graph = {
        "start": adventure["start"],
        "attributes": [attribute for attribute in DEMO_ATTRIBUTES],
        "death_text_html": adventure.get("death_text_html") or "",
        "death_translations": adventure.get("death_translations") or {},
        "victory_text_html": adventure.get("victory_text_html") or "",
        "victory_translations": adventure.get("victory_translations") or {},
    }
    for field, name in GLOBAL_BACKGROUNDS.items():
        graph[field] = uploads.get(name)

    nodes = []
    for node in adventure["nodes"]:
        key = node["key"]
        entry = {
            "key": key,
            "kind": node["kind"],
            "text_html": node["text_html"],
            "translations": node.get("translations") or {},
            "pos_x": node.get("pos_x", 0),
            "pos_y": node.get("pos_y", 0),
            "image_path": uploads.get(NODE_IMAGES.get(key, "")),
            "background_path": uploads.get(ENDING_BACKGROUNDS.get(key, "")),
            "choices": [
                {
                    "key": choice["key"],
                    "text": choice.get("text") or "",
                    "translations": choice.get("translations") or {},
                    "target": choice.get("target") or "",
                    "effects": [
                        {"attribute": effect["attribute"], "delta": effect["delta"]}
                        for effect in choice.get("effects") or []
                    ],
                }
                for choice in node.get("choices") or []
            ],
            "outcomes": [
                {
                    "kind": outcome["kind"],
                    "attribute": outcome.get("attribute") or "",
                    "range_min": outcome.get("range_min"),
                    "range_max": outcome.get("range_max"),
                    "text_html": outcome.get("text_html") or "",
                    "translations": outcome.get("translations") or {},
                    "priority": outcome.get("priority", 0),
                }
                for outcome in node.get("outcomes") or []
            ],
        }
        if key in ENDING_BACKGROUNDS:
            print(f"ending {key:16} image={entry['image_path']} background={entry['background_path']}")
        nodes.append(entry)

    graph["nodes"] = nodes
    payload["adventure"] = graph
    response = client.put(f"/api/v1/quizzes/{quiz_id}", json=payload)
    print("PUT story", response.status_code, response.text[:300] if response.status_code >= 300 else "ok")


def main() -> None:
    client = login()
    uploads = {name: upload(client, name) for name in sorted({*SWIPE_ORDER, *NODE_IMAGES.values(),
                                                              *ENDING_BACKGROUNDS.values(),
                                                              *GLOBAL_BACKGROUNDS.values()})}
    wire_swipe(client, 6, uploads)
    wire_adventure(client, 7, uploads)


if __name__ == "__main__":
    main()
