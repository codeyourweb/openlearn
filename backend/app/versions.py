# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Version snapshots: freezing, publishing and serving a quiz.

The regular tables always hold the *working copy* being edited. A
:class:`QuizVersion` stores the same content as a JSON payload in the shape
accepted by ``QuizIn``, so it can be published, served to the public, restored
into the working copy, or handed to a game session without duplicating any
serialisation logic.

Public behaviour with versions in place:

* A quiz keeps serving its last published version while the author edits.
* Publishing is explicit: it freezes a new version and either goes live (admins,
  trusted authors) or waits for moderation.
* Restoring an already-approved version may republish it without moderation.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from .content import FALLBACK_LANGUAGE, compute_content_hash
from .models import Quiz, QuizVersion, User, utcnow

# Statuses that keep serving the catalogue.
LIVE_STATUSES = ("published",)


# --------------------------------------------------------------------------- #
# Working copy -> payload                                                     #
# --------------------------------------------------------------------------- #
def adventure_payload(quiz: Quiz) -> dict:
    """The story graph of ``quiz`` in ``AdventureIn`` shape."""
    settings = quiz.adventure_settings or {}
    return {
        "start": quiz.adventure_start_key or "",
        "death_text_html": settings.get("death_text_html", ""),
        "victory_text_html": settings.get("victory_text_html", ""),
        "death_translations": settings.get("death_translations", {}),
        "victory_translations": settings.get("victory_translations", {}),
        "timer_mode": settings.get("timer_mode", "none"),
        "time_limit_seconds": settings.get("time_limit_seconds", 0),
        "timeout_effect": settings.get("timeout_effect", "penalty"),
        "timeout_penalty": settings.get("timeout_penalty", 1),
        "timeout_penalty_attribute": settings.get("timeout_penalty_attribute", ""),
        "attributes": [
            {
                "key": attribute.key,
                "label": attribute.label,
                "translations": attribute.label_translations or {},
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
                "translations": node.text_translations or {},
                "image_path": node.image_path,
                "background_path": node.background_path,
                "pos_x": node.pos_x,
                "pos_y": node.pos_y,
                "choices": [
                    {
                        "key": choice.key,
                        "text": choice.text,
                        "translations": choice.text_translations or {},
                        "target": choice.target_key,
                        "effects": [
                            {"attribute": effect.attribute_key, "delta": effect.delta}
                            for effect in choice.effects
                        ],
                    }
                    for choice in sorted(node.choices, key=lambda item: item.position)
                ],
                "outcomes": [
                    {
                        "kind": outcome.kind,
                        "attribute": outcome.attribute_key,
                        "range_min": outcome.range_min,
                        "range_max": outcome.range_max,
                        "text_html": outcome.text_html,
                        "translations": outcome.text_translations or {},
                        "priority": outcome.priority,
                    }
                    for outcome in sorted(node.outcomes, key=lambda item: item.priority)
                ],
            }
            for node in sorted(quiz.adventure_nodes, key=lambda item: item.position)
        ],
    }


def snapshot_payload(quiz: Quiz) -> dict:
    """Freeze the working copy into a payload that ``QuizIn`` accepts."""
    payload = {
        "title": quiz.title,
        "description": quiz.description or "",
        "wrong_answer_policy": quiz.wrong_answer_policy,
        "mode": quiz.mode,
        "timer_mode": quiz.timer_mode or "per_question",
        "global_time_limit_seconds": quiz.global_time_limit_seconds or 0,
        "results_visibility": quiz.results_visibility or "respondents",
        "default_language": quiz.default_language or FALLBACK_LANGUAGE,
        "title_translations": quiz.title_translations or {},
        "description_translations": quiz.description_translations or {},
        "questions": [],
        "adventure": None,
    }
    if quiz.mode == "adventure":
        payload["adventure"] = adventure_payload(quiz)
        return payload
    payload["questions"] = [
        {
            "text_html": question.text_html,
            "translations": question.text_translations or {},
            "image_path": question.image_path,
            "time_limit_seconds": question.time_limit_seconds,
            "points": question.points,
            "allow_multiple": bool(question.allow_multiple),
            "multiple": bool(question.allow_multiple),
            "options": [
                {
                    "text": option.text,
                    "is_correct": option.is_correct,
                    "translations": option.text_translations or {},
                }
                for option in sorted(question.options, key=lambda item: item.position)
            ],
        }
        for question in sorted(quiz.questions, key=lambda item: item.position)
    ]
    return payload


# --------------------------------------------------------------------------- #
# Payload -> playable content                                                 #
# --------------------------------------------------------------------------- #
def payload_questions(payload: dict) -> list[dict]:
    """Normalise a payload into question dicts with stable fake ids.

    Session snapshots need an id to remember which source question an answer
    refers to; payloads carry none, so the position is used.
    """
    questions: list[dict] = []
    for index, question in enumerate(payload.get("questions") or []):
        options = []
        for option_index, option in enumerate(question.get("options") or []):
            options.append(
                {
                    "id": option.get("id") or option_index + 1,
                    "text": option.get("text") or "",
                    "translations": option.get("translations") or option.get("text_translations") or {},
                    "is_correct": bool(option.get("is_correct")),
                }
            )
        questions.append(
            {
                "id": question.get("id") or index + 1,
                "text_html": question.get("text_html") or "",
                "translations": question.get("translations") or question.get("text_translations") or {},
                "image_path": question.get("image_path"),
                "time_limit_seconds": int(question.get("time_limit_seconds") or 30),
                "points": int(question.get("points") or 100),
                "multiple": bool(question.get("allow_multiple") or question.get("multiple")),
                "options": options,
            }
        )
    return questions


def resolved_question(question: dict, language: str) -> SimpleNamespace:
    """Wrap a question dict so ``content.resolve_text`` can read it."""
    return SimpleNamespace(
        text_html=question["text_html"],
        text_translations=question.get("translations") or {},
    )


def resolved_option(option: dict, language: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=option["text"],
        text_translations=option.get("translations") or {},
    )


def payload_summary_counts(payload: dict) -> dict:
    """Counts used by the catalogue cards, without loading the ORM graph."""
    if payload.get("mode") == "adventure":
        nodes = (payload.get("adventure") or {}).get("nodes") or []
        return {
            "question_count": sum(1 for node in nodes if node.get("kind") == "question"),
            "node_count": len(nodes),
        }
    return {"question_count": len(payload.get("questions") or []), "node_count": 0}


# --------------------------------------------------------------------------- #
# Lookups                                                                     #
# --------------------------------------------------------------------------- #
def published_version(db: OrmSession, quiz: Quiz) -> QuizVersion | None:
    number = quiz.published_version_number or 0
    if not number:
        return None
    return db.scalar(
        select(QuizVersion).where(QuizVersion.quiz_id == quiz.id, QuizVersion.number == number)
    )


def published_payload(db: OrmSession, quiz: Quiz) -> dict | None:
    """The payload the public currently sees, if any version is live."""
    if quiz.status != "public":
        return None
    version = published_version(db, quiz)
    return version.payload if version else None


def version_payload(db: OrmSession, quiz: Quiz, number: int) -> QuizVersion | None:
    return db.scalar(
        select(QuizVersion).where(QuizVersion.quiz_id == quiz.id, QuizVersion.number == number)
    )


def next_version_number(db: OrmSession, quiz: Quiz) -> int:
    highest = db.scalar(
        select(func.max(QuizVersion.number)).where(QuizVersion.quiz_id == quiz.id)
    )
    return int(highest or 0) + 1


# --------------------------------------------------------------------------- #
# Writing versions                                                            #
# --------------------------------------------------------------------------- #
def freeze(
    db: OrmSession,
    quiz: Quiz,
    *,
    user: User | None,
    payload: dict | None = None,
    publish: bool = False,
    auto_publish: bool = False,
    note: str = "",
    private: bool = False,
) -> QuizVersion:
    """Store a new version of ``quiz``.

    ``publish`` requests a publication; ``auto_publish`` says moderation can be
    skipped (admin or trusted author, or a re-approved rollback). ``private``
    freezes the version as the live one while keeping the quiz unlisted: the
    author gets a stable, playable document without asking a moderator.
    """
    payload = payload if payload is not None else snapshot_payload(quiz)
    version = QuizVersion(
        quiz_id=quiz.id,
        number=next_version_number(db, quiz),
        payload=payload,
        content_hash=compute_content_hash(quiz),
        created_by_id=user.id if user else None,
        note=note[:300],
    )
    if publish and private:
        version.status = "published"
        version.published_at = utcnow()
        quiz.status = "private"
        quiz.is_public = False
        quiz.published_at = None
        quiz.published_version_number = version.number
        db.query(QuizVersion).filter(
            QuizVersion.quiz_id == quiz.id, QuizVersion.status == "published"
        ).update({"status": "superseded"})
        version.status = "published"
    elif publish and auto_publish:
        version.status = "published"
        version.published_at = utcnow()
        version.approved_at = utcnow()
        version.approved_by_id = user.id if user else None
        quiz.status = "public"
        quiz.is_public = True
        quiz.published_at = version.published_at
        quiz.approved_by_id = user.id if user else None
        quiz.published_version_number = version.number
        # Everything older stops being live but stays in the history.
        db.query(QuizVersion).filter(
            QuizVersion.quiz_id == quiz.id, QuizVersion.status == "published"
        ).update({"status": "superseded"})
        version.status = "published"
    elif publish:
        version.status = "pending"
        if not quiz.published_version_number:
            # First publication: nothing is live yet. The quiz waits in the
            # queue but stays private, so the author can already play it and
            # share the link while a moderator decides.
            quiz.status = "private"
            quiz.is_public = False
            quiz.published_at = None
        # On a later version the quiz stays public: the previous validated
        # version keeps serving visitors until a moderator approves this one.
        quiz.moderation_note = ""
    else:
        version.status = "draft"
    db.add(version)
    db.flush()
    return version


def publish_existing(
    db: OrmSession, quiz: Quiz, version: QuizVersion, *, approver: User | None
) -> QuizVersion:
    """Make ``version`` the live one (moderation accepted)."""
    db.query(QuizVersion).filter(
        QuizVersion.quiz_id == quiz.id, QuizVersion.status == "published"
    ).update({"status": "superseded"})
    version.status = "published"
    version.published_at = utcnow()
    version.approved_at = version.approved_at or utcnow()
    version.approved_by_id = approver.id if approver else version.approved_by_id
    quiz.status = "public"
    quiz.is_public = True
    quiz.published_at = version.published_at
    quiz.approved_by_id = approver.id if approver else None
    quiz.published_version_number = version.number
    quiz.moderation_note = ""
    db.add(version)
    db.add(quiz)
    db.flush()
    return version


def version_summary(version: QuizVersion) -> dict:
    counts = payload_summary_counts(version.payload or {})
    return {
        "number": version.number,
        "status": version.status,
        "created_at": version.created_at,
        "published_at": version.published_at,
        "approved_at": version.approved_at,
        "note": version.note,
        "content_hash": version.content_hash,
        "question_count": counts["question_count"],
        "node_count": counts["node_count"],
        "title": (version.payload or {}).get("title", ""),
    }
