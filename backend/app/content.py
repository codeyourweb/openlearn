# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Quiz content helpers: canonical hashing, translation resolution and the
compact representation handed to the AI provider.

The content hash pins every review to the exact version of a quiz that was
examined. Any edit (text, options, answers, timings, translations) changes the
hash, which invalidates earlier AI reviews and forces a new moderation pass.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import SUPPORTED_LANGUAGES, Option, Quiz, Question
from .sanitize import html_to_text

FALLBACK_LANGUAGE = "en"


def valid_language(code: str | None) -> bool:
    return bool(code) and code in SUPPORTED_LANGUAGES


def resolve_text(
    entity: Any,
    language: str,
    attribute: str = "text",
    value_attribute: str | None = None,
) -> str:
    """Return the best available localisation for a translatable attribute.

    ``attribute`` names the ``*_translations`` JSON column, ``value_attribute``
    the canonical column holding the fallback text (they differ for questions,
    whose canonical text lives in ``text_html``).
    """
    value_attribute = value_attribute or attribute
    translations = getattr(entity, f"{attribute}_translations", None) or {}
    if language and language != FALLBACK_LANGUAGE:
        value = translations.get(language)
        if value:
            return value
    return getattr(entity, value_attribute) or ""


def available_languages(quiz: Quiz) -> list[str]:
    languages = {quiz.default_language or FALLBACK_LANGUAGE}
    for question in quiz.questions:
        languages.update((question.text_translations or {}).keys())
        for option in question.options:
            languages.update((option.text_translations or {}).keys())
    languages.update(quiz.title_translations or {})
    for attribute in quiz.adventure_attributes:
        languages.update((attribute.label_translations or {}).keys())
    for node in quiz.adventure_nodes:
        languages.update((node.text_translations or {}).keys())
        for choice in node.choices:
            languages.update((choice.text_translations or {}).keys())
        for outcome in node.outcomes:
            languages.update((outcome.text_translations or {}).keys())
    for key in ("death_translations", "victory_translations"):
        value = (quiz.adventure_settings or {}).get(key)
        if isinstance(value, dict):
            languages.update(value.keys())
    return sorted(lang for lang in languages if valid_language(lang))


def compute_content_hash(quiz: Quiz) -> str:
    """Stable SHA-256 over everything that defines the quiz's content."""
    payload = {
        "title": quiz.title,
        "description": quiz.description,
        "mode": quiz.mode,
        "wrong_answer_policy": quiz.wrong_answer_policy,
        "timer_mode": quiz.timer_mode,
        "global_time_limit_seconds": quiz.global_time_limit_seconds,
        "results_visibility": quiz.results_visibility,
        "default_language": quiz.default_language,
        "title_translations": _sorted_map(quiz.title_translations),
        "description_translations": _sorted_map(quiz.description_translations),
        "questions": [
            {
                "text_html": question.text_html,
                "text_translations": _sorted_map(question.text_translations),
                "image_path": question.image_path,
                "time_limit_seconds": question.time_limit_seconds,
                "points": question.points,
                "allow_multiple": bool(question.allow_multiple),
                "options": [
                    {
                        "text": option.text,
                        "text_translations": _sorted_map(option.text_translations),
                        "is_correct": bool(option.is_correct),
                    }
                    for option in sorted(question.options, key=lambda item: item.position)
                ],
            }
            for question in sorted(quiz.questions, key=lambda item: item.position)
        ],
        "adventure": _adventure_fingerprint(quiz) if quiz.mode == "adventure" else None,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _adventure_fingerprint(quiz: Quiz) -> dict:
    """Everything that defines a story, in a stable order."""
    settings = quiz.adventure_settings or {}
    return {
        "start": quiz.adventure_start_key or "",
        "death_text_html": settings.get("death_text_html") or "",
        "death_translations": _sorted_map(settings.get("death_translations")),
        "victory_text_html": settings.get("victory_text_html") or "",
        "victory_translations": _sorted_map(settings.get("victory_translations")),
        "attributes": [
            {
                "key": attribute.key,
                "label": attribute.label,
                "label_translations": _sorted_map(attribute.label_translations),
                "initial_value": attribute.initial_value,
                "min_value": attribute.min_value,
                "max_value": attribute.max_value,
                "death_at_or_below": attribute.death_at_or_below,
                "victory_at_or_above": attribute.victory_at_or_above,
            }
            for attribute in sorted(quiz.adventure_attributes, key=lambda item: item.position)
        ],
        "nodes": [
            {
                "key": node.key,
                "kind": node.kind,
                "text_html": node.text_html,
                "text_translations": _sorted_map(node.text_translations),
                "image_path": node.image_path,
                "background_path": node.background_path,
                "choices": [
                    {
                        "key": choice.key,
                        "text": choice.text,
                        "text_translations": _sorted_map(choice.text_translations),
                        "target_key": choice.target_key or "",
                        "effects": {
                            effect.attribute_key: effect.delta for effect in choice.effects
                        },
                    }
                    for choice in node.choices
                ],
                "outcomes": [
                    {
                        "kind": outcome.kind,
                        "attribute_key": outcome.attribute_key,
                        "range_min": outcome.range_min,
                        "range_max": outcome.range_max,
                        "text_html": outcome.text_html,
                        "text_translations": _sorted_map(outcome.text_translations),
                        "priority": outcome.priority,
                    }
                    for outcome in node.outcomes
                ],
            }
            for node in sorted(quiz.adventure_nodes, key=lambda item: item.position)
        ],
    }


def _sorted_map(value: dict | None) -> dict:
    if not value:
        return {}
    return {key: value[key] for key in sorted(value)}


def quiz_to_ai_dict(quiz: Quiz, language: str | None = None) -> dict:
    """Full quiz as plain JSON, used by the review and translation prompts."""
    language = language or quiz.default_language or FALLBACK_LANGUAGE
    return {
        "title": resolve_text(quiz, language, "title"),
        "description": resolve_text(quiz, language, "description"),
        "mode": quiz.mode,
        "wrong_answer_policy": quiz.wrong_answer_policy,
        "language": language,
        "questions": [
            {
                "index": position,
                "text": html_to_text(resolve_text(question, language, "text", "text_html")),
                "time_limit_seconds": question.time_limit_seconds,
                "points": question.points,
                "allow_multiple": bool(question.allow_multiple),
                "options": [
                    {
                        "index": option_position,
                        "text": resolve_text(option, language),
                        "is_correct": bool(option.is_correct),
                    }
                    for option_position, option in enumerate(
                        sorted(question.options, key=lambda item: item.position)
                    )
                ],
            }
            for position, question in enumerate(sorted(quiz.questions, key=lambda item: item.position))
        ],
        "adventure": _adventure_ai_dict(quiz, language) if quiz.mode == "adventure" else None,
    }


def _adventure_ai_dict(quiz: Quiz, language: str) -> dict:
    """Story view handed to the moderation and translation prompts."""
    settings = quiz.adventure_settings or {}

    def localised(entity: Any, translations: dict | None, canonical: str) -> str:
        if language and language != FALLBACK_LANGUAGE:
            value = (translations or {}).get(language)
            if value:
                return value
        return canonical or ""

    return {
        "start": quiz.adventure_start_key or "",
        "attributes": [
            {
                "key": attribute.key,
                "label": localised(attribute, attribute.label_translations, attribute.label),
                "initial_value": attribute.initial_value,
                "death_at_or_below": attribute.death_at_or_below,
                "victory_at_or_above": attribute.victory_at_or_above,
            }
            for attribute in quiz.adventure_attributes
        ],
        "nodes": [
            {
                "key": node.key,
                "kind": node.kind,
                "text": html_to_text(
                    localised(node, node.text_translations, node.text_html)
                ),
                "choices": [
                    {
                        "key": choice.key,
                        "text": localised(choice, choice.text_translations, choice.text),
                        "target": choice.target_key or "",
                        "effects": {
                            effect.attribute_key: effect.delta for effect in choice.effects
                        },
                    }
                    for choice in node.choices
                ],
                "outcomes": [
                    {
                        "kind": outcome.kind,
                        "attribute": outcome.attribute_key,
                        "text": html_to_text(
                            localised(outcome, outcome.text_translations, outcome.text_html)
                        ),
                    }
                    for outcome in node.outcomes
                ],
            }
            for node in quiz.adventure_nodes
        ],
        "death_text": html_to_text(
            localised(None, settings.get("death_translations"), settings.get("death_text_html"))
        ),
        "victory_text": html_to_text(
            localised(None, settings.get("victory_translations"), settings.get("victory_text_html"))
        ),
    }


def question_plain_text(question: Question, language: str = FALLBACK_LANGUAGE) -> str:
    return html_to_text(resolve_text(question, language))


def option_plain_text(option: Option, language: str = FALLBACK_LANGUAGE) -> str:
    return resolve_text(option, language)


def snapshot_text(quiz: Quiz, question: Question, option: Option | None, language: str) -> str:
    """Text captured into a game session for the chosen language."""
    if option is None:
        return resolve_text(question, language)
    return resolve_text(option, language)
