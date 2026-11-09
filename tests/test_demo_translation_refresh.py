# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)

"""A demo instance installed last month must learn this month's translations.

The seeder refuses to replace a questionnaire that already exists, which is what
keeps a visitor's work alive across a deploy. That refusal used to mean a
language added to the package afterwards never reached the instance, so the
catalogue announced four languages and showed one. A revised package is merged
into the rows already there instead, and the visitor reads the result through the
published version, not through the working copy.
"""

from __future__ import annotations

import copy
import json

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.demo.seed import _author, _content_dir, _install_quiz
from app.models import Quiz
from tests.conftest import create_quiz, csrf_headers, register_user


def _package_entry(name: str = "quizzes-paired.json", index: int = 0) -> dict:
    document = json.loads((_content_dir() / name).read_text(encoding="utf-8"))
    return copy.deepcopy(document["items"][index])


def _strip_translations(entry: dict) -> dict:
    """An instance seeded before the translations were written into the package."""
    early = copy.deepcopy(entry)
    early["title_translations"] = {}
    early["description_translations"] = {}
    for question in early["questions"]:
        question.pop("translations", None)
        for option in question["options"]:
            option.pop("translations", None)
    return early


def test_a_revised_package_teaches_an_installed_quiz_its_new_languages(client):
    entry = _package_entry()
    german = entry["questions"][0]["translations"]["de"]

    with SessionLocal() as db:
        author = _author(db, settings.admin_email or "curator@example.com", "OpenLearn Curator")
        quiz = _install_quiz(db, author, _strip_translations(entry))
        db.commit()
        quiz_id = quiz.id

    # The questionnaire as a visitor meets it today: the original wording only.
    plain = client.get(f"/api/v1/quizzes/{quiz_id}?lang=de")
    assert plain.status_code == 200, plain.text
    assert plain.json()["questions"][0]["text_html"] != german

    with SessionLocal() as db:
        author = _author(db, settings.admin_email or "curator@example.com", "OpenLearn Curator")
        assert _install_quiz(db, author, entry) is None, "the quiz already exists"
        db.commit()

        stored = db.scalar(select(Quiz).where(Quiz.id == quiz_id))
        assert stored.questions[0].text_translations.get("de"), "the question learned German"
        assert stored.questions[0].options[0].text_translations.get("de"), "so did its answers"
        assert stored.title_translations.get("de"), "and the catalogue shows a German title"
        assert "de" in stored.languages
        assert stored.is_multilingual, "the page offers the languages it now speaks"

    # A translation nobody can read is a promise, not a feature: the published
    # version a visitor is served carries it too.
    translated = client.get(f"/api/v1/quizzes/{quiz_id}?lang=de")
    assert translated.status_code == 200, translated.text
    assert translated.json()["questions"][0]["text_html"] == german


def test_merging_translations_leaves_someone_else_s_quiz_alone(client):
    entry = _package_entry()
    payload = {
        "title": entry["title"],
        "description": "Mon propre questionnaire.",
        "mode": "qcm",
        "wrong_answer_policy": "penalty",
        "default_language": "fr",
        "questions": [
            {
                "text_html": "<p>Ma question à moi.</p>",
                "options": [
                    {"text": "Oui", "is_correct": True},
                    {"text": "Non", "is_correct": False},
                ],
            }
        ],
    }
    register_user(client, email="autrice@example.com", display_name="Autrice")
    mine = create_quiz(client, payload, headers=csrf_headers(client))["id"]

    with SessionLocal() as db:
        author = _author(db, settings.admin_email or "curator@example.com", "OpenLearn Curator")
        _install_quiz(db, author, entry)
        db.commit()

        quiz = db.scalar(select(Quiz).where(Quiz.id == mine))
        assert quiz.questions[0].text_translations == {}, "a visitor's quiz is never rewritten"
