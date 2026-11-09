# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Quiz CRUD, publication workflow, translations and AI review endpoints.

Ownership and moderation rules (OWASP A01) are enforced on every mutating
endpoint. A quiz is only readable by someone else when it is published.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.orm import Session as OrmSession

from .. import ai, runtime, search, versions
from ..adventure import AdventureError, validate_adventure_graph
from ..config import settings
from ..content import (
    FALLBACK_LANGUAGE,
    available_languages,
    compute_content_hash,
    quiz_to_ai_dict,
    resolve_text,
    valid_language,
)
from ..db import get_db
from ..deps import enforce_ai_interval, enforce_rate_limit, get_optional_user, require_user
from ..models import (
    AdventureAttribute,
    AdventureChoice,
    AdventureEffect,
    AdventureNode,
    AdventureOutcome,
    AiReview,
    Option,
    Question,
    Quiz,
    QuizVersion,
    User,
    Wiki,
    WikiPage,
    WikiQuizLink,
    utcnow,
)
from ..sanitize import html_to_text, sanitize_html
from ..schemas import (
    AiTranslateIn,
    QuizDraftIn,
    QuizIn,
    QuizPublishIn,
    QuizSummaryOut,
    QuizVersionOut,
    QuizVisibilityIn,
)
from ..search import search_ids

router = APIRouter(prefix="/api/v1/quizzes", tags=["quizzes"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sync_public_flag(quiz: Quiz) -> None:
    quiz.is_public = quiz.status == "public"


def _sync_languages(quiz: Quiz) -> None:
    quiz.languages = available_languages(quiz)
    quiz.is_multilingual = len(quiz.languages) > 1


def _refresh_hash(quiz: Quiz) -> None:
    quiz.content_hash = compute_content_hash(quiz)


def _summary(
    db: OrmSession,
    quiz: Quiz,
    *,
    viewer: User | None = None,
    published: bool = False,
    language: str | None = None,
) -> QuizSummaryOut:
    count = db.scalar(select(func.count(Question.id)).where(Question.quiz_id == quiz.id)) or 0
    if quiz.mode == "adventure" and not count:
        count = int(
            db.scalar(
                select(func.count(AdventureNode.id)).where(
                    AdventureNode.quiz_id == quiz.id, AdventureNode.kind == "question"
                )
            )
            or 0
        )
    title, description, policy = quiz.title, quiz.description, quiz.wrong_answer_policy
    title_translations = quiz.title_translations or {}
    description_translations = quiz.description_translations or {}
    languages = quiz.languages or [quiz.default_language or FALLBACK_LANGUAGE]
    if published:
        # The catalogue advertises what is actually live, not the working copy.
        payload = versions.published_payload(db, quiz)
        if payload is not None:
            count = versions.payload_summary_counts(payload)["question_count"]
            title = payload.get("title") or title
            description = payload.get("description", description) or ""
            policy = payload.get("wrong_answer_policy") or policy
            title_translations = payload.get("title_translations") or title_translations
            description_translations = (
                payload.get("description_translations") or description_translations
            )
            languages = payload.get("title_translations") and list(
                {FALLBACK_LANGUAGE, *(payload.get("title_translations") or {})}
            ) or languages
    if language:
        # A card carries the words the reader can read: a German catalogue entry
        # opening an English page is the same broken promise as untranslated text.
        title = title_translations.get(language) or title
        description = description_translations.get(language) or description
    return QuizSummaryOut(
        id=quiz.id,
        title=title,
        description=description,
        question_count=count,
        wrong_answer_policy=policy,
        mode=quiz.mode,
        status=quiz.status,
        is_public=quiz.is_public,
        languages=languages,
        default_language=quiz.default_language or FALLBACK_LANGUAGE,
        owner_id=quiz.owner_id,
        owner_name=quiz.owner.display_name if quiz.owner else "",
        created_at=quiz.created_at,
        updated_at=quiz.updated_at,
    )


def serialise_quiz(
    quiz: Quiz,
    *,
    include_answers: bool,
    language: str | None = None,
    viewer: User | None = None,
) -> dict:
    language = language if valid_language(language) else None
    questions = []
    for question in sorted(quiz.questions, key=lambda item: item.position):
        options = []
        for option in sorted(question.options, key=lambda item: item.position):
            payload = {
                "id": option.id,
                "text": resolve_text(option, language or quiz.default_language) if language else option.text,
                "position": option.position,
                "translations": option.text_translations or {},
            }
            if include_answers:
                payload["is_correct"] = option.is_correct
            options.append(payload)
        questions.append(
            {
                "id": question.id,
                "position": question.position,
                "text_html": resolve_text(question, language or quiz.default_language, "text", "text_html")
                if language
                else question.text_html,
                "text_plain": html_to_text(question.text_html),
                "translations": question.text_translations or {},
                "image_path": question.image_path,
                "time_limit_seconds": question.time_limit_seconds,
                "points": question.points,
                "multiple_answers": bool(question.allow_multiple)
                if quiz.mode == "poll"
                else sum(1 for option in question.options if option.is_correct) > 1,
                "allow_multiple": bool(question.allow_multiple),
                "options": options,
            }
        )
    adventure = None
    if quiz.mode == "adventure":
        adventure = {
            "start": quiz.adventure_start_key or "",
            "death_text_html": (quiz.adventure_settings or {}).get("death_text_html", ""),
            "death_translations": (quiz.adventure_settings or {}).get("death_translations", {}),
            "death_background_path": (quiz.adventure_settings or {}).get("death_background_path"),
            "victory_text_html": (quiz.adventure_settings or {}).get("victory_text_html", ""),
            "victory_translations": (quiz.adventure_settings or {}).get("victory_translations", {}),
            "victory_background_path": (quiz.adventure_settings or {}).get("victory_background_path"),
            "timer_mode": (quiz.adventure_settings or {}).get("timer_mode", "none"),
            "time_limit_seconds": (quiz.adventure_settings or {}).get("time_limit_seconds", 0),
            "timeout_effect": (quiz.adventure_settings or {}).get("timeout_effect", "penalty"),
            "timeout_penalty": (quiz.adventure_settings or {}).get("timeout_penalty", 1),
            "timeout_penalty_attribute": (quiz.adventure_settings or {}).get(
                "timeout_penalty_attribute", ""
            ),
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
                    "text_plain": html_to_text(node.text_html),
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
                            "target": choice.target_key or "",
                            # Effects are the story's hidden engine: only the
                            # author (and administrators) may read them.
                            "effects": (
                                [
                                    {"attribute": effect.attribute_key, "delta": effect.delta}
                                    for effect in choice.effects
                                ]
                                if include_answers
                                else []
                            ),
                        }
                        for choice in node.choices
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
                        for outcome in node.outcomes
                    ],
                }
                for node in sorted(quiz.adventure_nodes, key=lambda item: item.position)
            ],
        }

    title = quiz.title
    description = quiz.description
    if language and valid_language(language):
        title = (quiz.title_translations or {}).get(language) or title
        description = (quiz.description_translations or {}).get(language) or description
    return {
        "id": quiz.id,
        "title": title,
        "description": description,
        "wrong_answer_policy": quiz.wrong_answer_policy,
        "mode": quiz.mode,
        "timer_mode": quiz.timer_mode or "per_question",
        "global_time_limit_seconds": quiz.global_time_limit_seconds or 0,
        "results_visibility": quiz.results_visibility or "respondents",
        "max_attempts": quiz.max_attempts or 0,
        # The private evaluation link is only meaningful to its author.
        "share_token": quiz.share_token if (viewer and (viewer.id == quiz.owner_id or viewer.is_staff)) else None,
        # Drives the publish tab: a plain author may not go public on their own.
        "can_publish_publicly": bool(viewer and (viewer.is_staff or viewer.is_trusted)),
        "status": quiz.status,
        "is_public": quiz.is_public,
        "moderation_note": quiz.moderation_note,
        "default_language": quiz.default_language or FALLBACK_LANGUAGE,
        "is_multilingual": quiz.is_multilingual,
        "languages": quiz.languages or [quiz.default_language or FALLBACK_LANGUAGE],
        "title_translations": quiz.title_translations or {},
        "description_translations": quiz.description_translations or {},
        "ai_generated": quiz.ai_generated,
        "content_hash": quiz.content_hash,
        "legal_status": quiz.legal_status,
        "legal_checked_at": quiz.legal_checked_at,
        "answer_status": quiz.answer_status,
        "answer_checked_at": quiz.answer_checked_at,
        "owner_id": quiz.owner_id,
        "owner_name": quiz.owner.display_name if quiz.owner else "",
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
        "published_at": quiz.published_at,
        "published_version": quiz.published_version_number or 0,
        # Visitors read the frozen version; the owner reads the working copy.
        "version_live": bool(quiz.published_version_number),
        "question_count": len(questions),
        "questions": questions,
        "adventure": adventure,
    }


def serialise_payload(
    quiz: Quiz, payload: dict, *, include_answers: bool = False, language: str | None = None
) -> dict:
    """Render a frozen payload with the shape ``serialise_quiz`` returns.

    Used to serve the last published version to visitors while the author keeps
    editing the working copy.
    """
    lang = language if valid_language(language) else (payload.get("default_language") or FALLBACK_LANGUAGE)
    questions = []
    for index, question in enumerate(versions.payload_questions(payload)):
        wrapped_question = versions.resolved_question(question, lang)
        options = []
        for option in question["options"]:
            wrapped_option = versions.resolved_option(option, lang)
            item = {
                "id": option["id"],
                "text": resolve_text(wrapped_option, lang),
                "position": option["id"] - 1,
                "translations": option["translations"],
            }
            if include_answers:
                item["is_correct"] = option["is_correct"]
            options.append(item)
        questions.append(
            {
                "id": question["id"],
                "position": index,
                "text_html": resolve_text(wrapped_question, lang, "text", "text_html"),
                "text_plain": html_to_text(question["text_html"]),
                "translations": question["translations"],
                "image_path": question["image_path"],
                "time_limit_seconds": question["time_limit_seconds"],
                "points": question["points"],
                "multiple_answers": sum(1 for option in question["options"] if option["is_correct"]) > 1,
                "options": options,
            }
        )

    adventure = None
    if payload.get("mode") == "adventure" and payload.get("adventure"):
        story = payload["adventure"]
        adventure = {
            "start": story.get("start", ""),
            "death_text_html": story.get("death_text_html", ""),
            "death_translations": story.get("death_translations", {}),
            "death_background_path": story.get("death_background_path"),
            "victory_text_html": story.get("victory_text_html", ""),
            "victory_translations": story.get("victory_translations", {}),
            "victory_background_path": story.get("victory_background_path"),
            "attributes": [
                {
                    "key": attribute["key"],
                    "label": attribute["label"],
                    "translations": attribute.get("translations", {}),
                    "initial_value": attribute.get("initial_value", 0),
                    "min_value": attribute.get("min_value"),
                    "max_value": attribute.get("max_value"),
                    "death_at_or_below": attribute.get("death_at_or_below"),
                    "victory_at_or_above": attribute.get("victory_at_or_above"),
                }
                for attribute in story.get("attributes") or []
            ],
            "nodes": [
                {
                    "key": node["key"],
                    "kind": node.get("kind", "question"),
                    "text_html": node.get("text_html", ""),
                    "text_plain": html_to_text(node.get("text_html", "")),
                    "translations": node.get("translations", {}),
                    "image_path": node.get("image_path"),
                    "background_path": node.get("background_path"),
                    "pos_x": node.get("pos_x", 0),
                    "pos_y": node.get("pos_y", 0),
                    "choices": [
                        {
                            "key": choice["key"],
                            "text": choice.get("text", ""),
                            "translations": choice.get("translations", {}),
                            "target": choice.get("target") or "",
                            "effects": (choice.get("effects") or []) if include_answers else [],
                        }
                        for choice in node.get("choices") or []
                    ],
                    "outcomes": [
                        {
                            "kind": outcome.get("kind", "highest"),
                            "attribute": outcome.get("attribute"),
                            "range_min": outcome.get("range_min"),
                            "range_max": outcome.get("range_max"),
                            "text_html": outcome.get("text_html", ""),
                            "translations": outcome.get("translations", {}),
                            "priority": outcome.get("priority", 0),
                        }
                        for outcome in node.get("outcomes") or []
                    ],
                }
                for node in story.get("nodes") or []
            ],
        }

    title_translations = payload.get("title_translations") or {}
    description_translations = payload.get("description_translations") or {}
    return {
        "id": quiz.id,
        "title": title_translations.get(lang) or payload.get("title", quiz.title),
        "description": description_translations.get(lang) or payload.get("description", ""),
        "wrong_answer_policy": payload.get("wrong_answer_policy", "zero"),
        "mode": payload.get("mode", quiz.mode),
        "timer_mode": payload.get("timer_mode", quiz.timer_mode or "per_question"),
        "global_time_limit_seconds": payload.get("global_time_limit_seconds", 0),
        "status": quiz.status,
        "is_public": quiz.is_public,
        "moderation_note": quiz.moderation_note,
        "default_language": lang,
        "is_multilingual": bool(quiz.is_multilingual),
        "languages": quiz.languages or [lang],
        "title_translations": payload.get("title_translations", {}),
        "description_translations": payload.get("description_translations", {}),
        "ai_generated": quiz.ai_generated,
        "content_hash": quiz.content_hash,
        "legal_status": quiz.legal_status,
        "legal_checked_at": quiz.legal_checked_at,
        "answer_status": quiz.answer_status,
        "answer_checked_at": quiz.answer_checked_at,
        "owner_id": quiz.owner_id,
        "owner_name": quiz.owner.display_name if quiz.owner else "",
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
        "published_at": quiz.published_at,
        "published_version": quiz.published_version_number or 0,
        "version_live": True,
        "question_count": len(questions),
        "questions": questions,
        "adventure": adventure,
    }


def _apply_quiz(db: OrmSession, quiz: Quiz, payload: QuizIn) -> Quiz:
    quiz.title = payload.title
    quiz.description = payload.description
    quiz.wrong_answer_policy = payload.wrong_answer_policy
    quiz.mode = payload.mode
    quiz.timer_mode = payload.timer_mode
    quiz.global_time_limit_seconds = payload.global_time_limit_seconds
    quiz.results_visibility = getattr(payload, "results_visibility", "respondents")
    quiz.max_attempts = getattr(payload, "max_attempts", quiz.max_attempts or 0)
    quiz.default_language = payload.default_language
    quiz.title_translations = payload.title_translations
    quiz.description_translations = payload.description_translations
    quiz.updated_at = utcnow()

    # Replace the whole document: linear questions or the story graph.
    quiz.questions.clear()
    quiz.adventure_nodes.clear()
    db.flush()
    quiz.adventure_nodes.clear()
    quiz.adventure_attributes.clear()
    db.flush()

    if payload.mode == "adventure" and payload.adventure is not None:
        story = payload.adventure
        quiz.adventure_start_key = story.start
        quiz.adventure_settings = {
            "death_text_html": story.death_text_html,
            "death_translations": story.death_translations,
            "death_background_path": story.death_background_path,
            "victory_text_html": story.victory_text_html,
            "victory_translations": story.victory_translations,
            "victory_background_path": story.victory_background_path,
            "timer_mode": story.timer_mode,
            "time_limit_seconds": story.time_limit_seconds,
            "timeout_effect": story.timeout_effect,
            "timeout_penalty": story.timeout_penalty,
            "timeout_penalty_attribute": story.timeout_penalty_attribute,
        }
        for position, attribute_in in enumerate(story.attributes):
            quiz.adventure_attributes.append(
                AdventureAttribute(
                    key=attribute_in.key,
                    label=attribute_in.label,
                    label_translations=attribute_in.translations,
                    initial_value=attribute_in.initial_value,
                    min_value=attribute_in.min_value,
                    max_value=attribute_in.max_value,
                    death_at_or_below=attribute_in.death_at_or_below,
                    victory_at_or_above=attribute_in.victory_at_or_above,
                    position=position,
                )
            )
        db.flush()
        for position, node_in in enumerate(story.nodes):
            node = AdventureNode(
                quiz_id=quiz.id,
                key=node_in.key,
                kind=node_in.kind,
                text_html=node_in.text_html,
                text_translations=node_in.translations,
                image_path=node_in.image_path,
                background_path=node_in.background_path,
                pos_x=node_in.pos_x,
                pos_y=node_in.pos_y,
                position=position,
            )
            for choice_position, choice_in in enumerate(node_in.choices):
                node.choices.append(
                    AdventureChoice(
                        key=choice_in.key,
                        text=choice_in.text,
                        text_translations=choice_in.translations,
                        target_key=choice_in.target or None,
                        position=choice_position,
                        effects=[
                            AdventureEffect(attribute_key=effect.attribute, delta=effect.delta)
                            for effect in choice_in.effects
                            if effect.delta
                        ],
                    )
                )
            for outcome_in in node_in.outcomes:
                node.outcomes.append(
                    AdventureOutcome(
                        kind=outcome_in.kind,
                        attribute_key=outcome_in.attribute,
                        range_min=outcome_in.range_min,
                        range_max=outcome_in.range_max,
                        text_html=outcome_in.text_html,
                        text_translations=outcome_in.translations,
                        priority=outcome_in.priority,
                    )
                )
            quiz.adventure_nodes.append(node)
        db.flush()

    for position, question_in in enumerate(payload.questions):
        question = Question(
            quiz_id=quiz.id,
            position=position,
            text_html=question_in.text_html,
            text_translations=question_in.translations,
            image_path=question_in.image_path,
            time_limit_seconds=question_in.time_limit_seconds,
            points=0 if payload.mode == "poll" else question_in.points,
            allow_multiple=bool(getattr(question_in, "allow_multiple", False)),
        )
        quiz.questions.append(question)
        # SQLite recycles the id of a deleted row. If an earlier raw delete left
        # its options behind, the freshly inserted question would inherit them
        # and the answer key of a dead quiz would score this one. Flush to get
        # the id, then drop anything already sitting under it before we append.
        db.flush()
        db.execute(delete(Option).where(Option.question_id == question.id))
        for option_position, option_in in enumerate(question_in.options):
            text = option_in.text
            translations = option_in.translations
            if payload.mode == "swipe":
                # Canonical yes/no markers: the client renders localised labels.
                text = "Yes" if option_position == 0 else "No"
                translations = {}
            question.options.append(
                Option(
                    position=option_position,
                    text=text,
                    text_translations=translations,
                    # A poll has no answer key: never store a stale flag that a
                    # later scoring pass could read as "right".
                    is_correct=False if payload.mode == "poll" else option_in.is_correct,
                )
            )

    _sync_languages(quiz)
    _refresh_hash(quiz)
    # Any edit invalidates the previous reviews.
    quiz.legal_status = ""
    quiz.legal_hash = ""
    quiz.answer_status = ""
    quiz.answer_hash = ""
    db.add(quiz)
    db.flush()
    _refresh_hash(quiz)
    db.commit()
    db.refresh(quiz)
    return quiz


def _translations_are_complete(
    quiz: Quiz, targets: list[str], questions: list, scope: int | None
) -> bool:
    """True when every requested language is already filled for the scope."""
    if scope is None:
        for language in targets:
            if not (quiz.title_translations or {}).get(language):
                return False
            if quiz.description and not (quiz.description_translations or {}).get(language):
                return False
    selected = questions if scope is None else [questions[scope]]
    for question in selected:
        for language in targets:
            if not (question.text_translations or {}).get(language):
                return False
            for option in question.options:
                if not (option.text_translations or {}).get(language):
                    return False
    return True


def _can_view(quiz: Quiz, user: User | None) -> bool:
    if quiz.status == "public":
        return True
    if user is None:
        return False
    return quiz.owner_id == user.id or user.is_staff


def _can_edit(quiz: Quiz, user: User) -> bool:
    return quiz.owner_id == user.id or user.is_staff


def _get_quiz_or_404(db: OrmSession, quiz_id: int) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    return quiz


def _record_review(
    db: OrmSession,
    quiz: Quiz,
    *,
    kind: str,
    status_value: str,
    summary: str,
    findings: list[dict] | None = None,
    corrections: list[dict] | None = None,
    user: User | None,
    ip: str | None,
) -> AiReview:
    review = AiReview(
        quiz_id=quiz.id,
        kind=kind,
        status=status_value,
        model=runtime.ai_config(db).model,
        summary=summary,
        findings=findings or [],
        corrections=corrections or [],
        content_hash=quiz.content_hash,
        requested_by_id=user.id if user else None,
        requested_ip=ip,
    )
    db.add(review)
    db.flush()
    return review


def _review_payload(review: AiReview, quiz: Quiz, *, redact: bool = False) -> dict:
    if redact:
        return {
            "id": review.id,
            "kind": review.kind,
            "status": review.status,
            "summary": "",
            "findings": [],
            "corrections": [],
            "model": review.model,
            "created_at": review.created_at,
            "stale": review.content_hash != quiz.content_hash,
        }
    return {
        "id": review.id,
        "kind": review.kind,
        "status": review.status,
        "summary": review.summary,
        "findings": review.findings or [],
        "corrections": review.corrections or [],
        "model": review.model,
        "created_at": review.created_at,
        "stale": review.content_hash != quiz.content_hash,
    }


def _ai_guard() -> None:
    if not ai.is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI assistance is not configured on this instance.",
        )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
QUIZ_MODES = ("qcm", "swipe", "poll", "adventure")


def language_clause(lang: str):
    """Rows a reader asking for ``lang`` expects to find.

    A quiz carries its own language plus, when it was translated, the list of
    languages it was translated into. Casting that JSON array to text is the one
    form of "contains" that SQLite, PostgreSQL, MySQL and MariaDB all accept;
    the pattern quotes the code so ``fr`` never matches ``fr-CA``.
    """
    return or_(
        Quiz.default_language == lang,
        cast(Quiz.languages, String).like(f'%"{lang}"%'),
    )


@router.get("", response_model=list[QuizSummaryOut])
def list_quizzes(
    response: Response,
    q: str | None = Query(default=None, max_length=100),
    mode: str | None = Query(default=None, pattern="^(qcm|swipe|poll|adventure)$"),
    lang: str | None = Query(default=None, min_length=2, max_length=5),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: OrmSession = Depends(get_db),
):
    """Public catalogue, optionally filtered by a search, a type and a language.

    ``X-Total-Count`` carries the size of the whole result set so the client can
    paginate without guessing; it counts the filtered set, so the pager never
    promises pages the filters emptied.
    """
    stmt = select(Quiz).where(Quiz.status == "public")
    if mode:
        stmt = stmt.where(Quiz.mode == mode)
    if lang:
        stmt = stmt.where(language_clause(lang))
    if q and q.strip():
        ranked = search_ids(db, q)
        if ranked is None:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(or_(Quiz.title.ilike(pattern), Quiz.description.ilike(pattern)))
        elif ranked:
            # Keep the FTS ranking order.
            order = {quiz_id: index for index, quiz_id in enumerate(ranked)}
            rows = list(db.scalars(stmt.where(Quiz.id.in_(ranked))))
            rows.sort(key=lambda item: order.get(item.id, len(order)))
            response.headers["X-Total-Count"] = str(len(rows))
            return [
                _summary(db, quiz, published=True, language=lang)
                for quiz in rows[offset : offset + limit]
            ]
        else:
            response.headers["X-Total-Count"] = "0"
            return []
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    # MySQL and MariaDB have no NULLS LAST: sort on the predicate instead.
    stmt = stmt.order_by(
        Quiz.published_at.is_(None), Quiz.published_at.desc(), Quiz.updated_at.desc()
    )
    stmt = stmt.limit(limit).offset(offset)
    return [
        _summary(db, quiz, published=True, language=lang) for quiz in db.scalars(stmt).unique()
    ]


@router.get("/mine", response_model=list[QuizSummaryOut])
def list_my_quizzes(
    response: Response,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """The author's own questionnaires, one page at a time, newest first.

    Same contract as the catalogue: ``X-Total-Count`` carries the size of the
    whole result set so a client can paginate without guessing.
    """
    stmt = select(Quiz).where(Quiz.owner_id == user.id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Quiz.title.ilike(pattern), Quiz.description.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    stmt = stmt.order_by(Quiz.updated_at.desc()).limit(limit).offset(offset)
    return [_summary(db, quiz) for quiz in db.scalars(stmt).unique()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_quiz(payload: QuizIn, user: User = Depends(require_user), db: OrmSession = Depends(get_db)):
    quiz = Quiz(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        wrong_answer_policy=payload.wrong_answer_policy,
        mode=payload.mode,
        timer_mode=payload.timer_mode,
        global_time_limit_seconds=payload.global_time_limit_seconds,
        results_visibility=getattr(payload, "results_visibility", "respondents"),
        max_attempts=getattr(payload, "max_attempts", 0),
        status="draft",
        is_public=False,
    )
    db.add(quiz)
    db.flush()
    _apply_quiz(db, quiz, payload)
    return serialise_quiz(quiz, include_answers=True, viewer=user)


@router.get("/{quiz_id}")
def get_quiz(
    quiz_id: int,
    lang: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: OrmSession = Depends(get_db),
):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_view(quiz, user):
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if user is not None and _can_edit(quiz, user):
        # The author edits the working copy, with the answer key — in its own
        # language, never in the translation the reader happens to speak.
        return serialise_quiz(quiz, include_answers=True, viewer=user)
    # A visitor reads the questions in their own language, translated where a
    # translation exists and falling back to the original where it does not.
    language = lang if valid_language(lang) else None
    payload = versions.published_payload(db, quiz)
    if payload is not None:
        # Visitors keep seeing the last validated version, even mid-edit.
        return serialise_payload(quiz, payload, include_answers=False, language=language)
    return serialise_quiz(quiz, include_answers=False, language=language, viewer=user)


@router.put("/{quiz_id}")
def update_quiz(
    quiz_id: int,
    payload: QuizIn,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    _apply_quiz(db, quiz, payload)
    # Editing only touches the working copy: the published version keeps
    # serving visitors until the author publishes again.
    search.refresh_quiz(db, quiz)
    return serialise_quiz(quiz, include_answers=True, viewer=user)


@router.post("/draft", status_code=status.HTTP_201_CREATED)
def create_draft(
    payload: QuizDraftIn,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Create the first autosaved working copy of a new quiz.

    A draft is allowed to be unfinished: no answer key, empty questions, an
    incomplete story graph. Publication still requires ``QuizIn``.
    """
    quiz = Quiz(
        owner_id=user.id,
        title=payload.title or "Untitled quiz",  # replaced below by the payload when set
        description=payload.description,
        wrong_answer_policy=payload.wrong_answer_policy,
        mode=payload.mode,
        timer_mode=payload.timer_mode,
        global_time_limit_seconds=payload.global_time_limit_seconds,
        results_visibility=getattr(payload, "results_visibility", "respondents"),
        max_attempts=getattr(payload, "max_attempts", 0),
        status="draft",
        is_public=False,
    )
    db.add(quiz)
    db.flush()
    _apply_quiz(db, quiz, payload)
    if not quiz.title:
        # An untitled autosave still needs a name in the dashboard list.
        quiz.title = "Untitled quiz"
        db.add(quiz)
        db.commit()
        db.refresh(quiz)
    return serialise_quiz(quiz, include_answers=True, viewer=user)


@router.put("/{quiz_id}/draft")
def update_draft(
    quiz_id: int,
    payload: QuizDraftIn,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Autosave the working copy without disturbing the published version."""
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    _apply_quiz(db, quiz, payload)
    search.refresh_quiz(db, quiz)
    return serialise_quiz(quiz, include_answers=True, viewer=user)


@router.delete("/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quiz(quiz_id: int, user: User = Depends(require_user), db: OrmSession = Depends(get_db)):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    db.delete(quiz)
    db.commit()



def _adventure_payload(quiz: Quiz) -> dict:
    """ORM story -> payload accepted by ``QuizIn`` (used by duplication)."""
    settings = quiz.adventure_settings or {}
    return {
        "start": quiz.adventure_start_key or "",
        "death_text_html": settings.get("death_text_html", ""),
        "death_translations": settings.get("death_translations", {}),
        "death_background_path": settings.get("death_background_path"),
        "victory_text_html": settings.get("victory_text_html", ""),
        "victory_translations": settings.get("victory_translations", {}),
        "victory_background_path": settings.get("victory_background_path"),
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
                        "target": choice.target_key or None,
                        "effects": [
                            {"attribute": effect.attribute_key, "delta": effect.delta}
                            for effect in choice.effects
                        ],
                    }
                    for choice in node.choices
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
                    for outcome in node.outcomes
                ],
            }
            for node in sorted(quiz.adventure_nodes, key=lambda item: item.position)
        ],
    }


@router.post("/{quiz_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_quiz(quiz_id: int, user: User = Depends(require_user), db: OrmSession = Depends(get_db)):
    source = _get_quiz_or_404(db, quiz_id)
    if not _can_view(source, user):
        raise HTTPException(status_code=404, detail="Quiz not found.")
    payload = QuizIn(
        title=f"{source.title} (copy)"[:120],
        description=source.description,
        wrong_answer_policy=source.wrong_answer_policy,
        timer_mode=source.timer_mode or "per_question",
        global_time_limit_seconds=source.global_time_limit_seconds or 0,
        mode=source.mode,
        is_public=False,
        default_language=source.default_language,
        title_translations=source.title_translations or {},
        description_translations=source.description_translations or {},
        questions=[
            {
                "text_html": question.text_html,
                "translations": question.text_translations or {},
                "image_path": question.image_path,
                "time_limit_seconds": question.time_limit_seconds,
                "points": question.points,
                "options": [
                    {
                        "text": option.text,
                        "is_correct": option.is_correct,
                        "translations": option.text_translations or {},
                    }
                    for option in sorted(question.options, key=lambda item: item.position)
                ],
            }
            for question in sorted(source.questions, key=lambda item: item.position)
        ],
        adventure=_adventure_payload(source) if source.mode == "adventure" else None,
    )
    quiz = Quiz(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        wrong_answer_policy=payload.wrong_answer_policy,
        mode=payload.mode,
        timer_mode=payload.timer_mode,
        global_time_limit_seconds=payload.global_time_limit_seconds,
        status="draft",
        is_public=False,
        ai_generated=source.ai_generated,
    )
    db.add(quiz)
    db.flush()
    _apply_quiz(db, quiz, payload)
    return serialise_quiz(quiz, include_answers=True, viewer=user)


# ---------------------------------------------------------------------------
# Publication workflow
# ---------------------------------------------------------------------------
def _validate_for_publication(quiz: Quiz) -> dict:
    """Freeze-check the working copy: what would be published must be valid."""
    payload = versions.snapshot_payload(quiz)
    try:
        QuizIn.model_validate(payload)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()[:4]
        )
        raise HTTPException(status_code=422, detail=problems or "Invalid quiz.") from error
    if quiz.mode == "adventure":
        # A story must be finishable before it can go live, even though a draft
        # is allowed to be incomplete while it is edited.
        try:
            validate_adventure_graph(payload["adventure"], strict=True)
        except AdventureError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return payload


def _publish_working_copy(
    db: OrmSession, quiz: Quiz, user: User, *, note: str = "", visibility: str = "public"
) -> versions.QuizVersion:
    if quiz.legal_status == "blocked":
        raise HTTPException(
            status_code=409,
            detail="This quiz was blocked by the safety review and cannot be published.",
        )
    payload = _validate_for_publication(quiz)
    version = versions.freeze(
        db,
        quiz,
        user=user,
        payload=payload,
        publish=True,
        auto_publish=bool(user.is_staff or user.is_trusted),
        note=note,
        private=visibility == "private",
    )
    _sync_public_flag(quiz)
    quiz.updated_at = utcnow()
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    search.refresh_quiz(db, quiz)
    return version


@router.post("/{quiz_id}/publish")
def publish_quiz(
    quiz_id: int,
    user: User = Depends(require_user),
    body: QuizPublishIn | None = None,
    db: OrmSession = Depends(get_db),
):
    """Freeze the working copy and publish it, privately or publicly.

    ``visibility="private"`` makes the version live for the author alone: the
    document is playable and shareable by link, it just stays out of the
    catalogue. ``visibility="public"`` asks for the catalogue: an administrator
    or a trusted author goes live at once, anyone else waits in the moderation
    queue — and gets a private quiz in the meantime rather than nothing.
    """
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    request = body or QuizPublishIn()
    version = _publish_working_copy(
        db, quiz, user, note=request.note, visibility=request.visibility
    )
    return {
        "id": quiz.id,
        "status": quiz.status,
        "is_public": quiz.is_public,
        "moderation_note": quiz.moderation_note,
        # A pending version on a live quiz still needs a moderator.
        "requires_moderation": version.status == "pending",
        "can_publish_publicly": bool(user.is_staff or user.is_trusted),
        "version": versions.version_summary(version),
        "published_version": quiz.published_version_number,
    }


@router.post("/{quiz_id}/visibility")
def set_visibility(
    quiz_id: int,
    payload: QuizVisibilityIn,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    version = None
    if payload.visibility in ("public", "pending"):
        version = _publish_working_copy(db, quiz, user)
    else:
        quiz.status = payload.visibility
        quiz.published_at = None
        quiz.approved_by_id = None
        _sync_public_flag(quiz)
        quiz.updated_at = utcnow()
        db.add(quiz)
        db.commit()
        db.refresh(quiz)
        search.refresh_quiz(db, quiz)
    return {
        "id": quiz.id,
        "status": quiz.status,
        "is_public": quiz.is_public,
        "moderation_note": quiz.moderation_note,
        "requires_moderation": bool(version is not None and version.status == "pending"),
        "version": versions.version_summary(version) if version else None,
        "published_version": quiz.published_version_number,
    }


# ---------------------------------------------------------------------------
# Creator statistics
# ---------------------------------------------------------------------------
@router.get("/{quiz_id}/stats")
def quiz_stats(
    quiz_id: int,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Aggregate participation for the author: audience size and per-question success.

    Sessions are snapshots, so questions are matched on ``source_question_id``
    rather than on their position (the order is shuffled per session). Rows whose
    source question no longer exists are still reported, using the snapshot text
    captured at play time, so deleting a question never rewrites history.
    """
    from ..models import Answer, GameSession, Participant, SessionQuestion

    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")

    session_ids = db.scalars(select(GameSession.id).where(GameSession.quiz_id == quiz.id)).all()
    if not session_ids:
        return {
            "sessions": 0,
            "participants": 0,
            "answers": 0,
            "correct_rate": 0.0,
            "average_score": 0,
            "average_seconds": 0.0,
            "finished_sessions": 0,
            "total_questions": len(quiz.questions),
            "questions": [],
        }

    rows = db.execute(
        select(
            Answer.is_correct,
            Answer.response_ms,
            SessionQuestion.source_question_id,
            SessionQuestion.position,
            SessionQuestion.text_html,
            SessionQuestion.session_id,
        )
        .join(SessionQuestion, SessionQuestion.id == Answer.session_question_id)
        .where(SessionQuestion.session_id.in_(session_ids))
    ).all()

    scores = db.execute(
        select(Participant.score, Participant.session_id)
        .where(Participant.session_id.in_(session_ids))
        .where(Participant.is_host.is_(False))
    ).all()
    audience = db.scalar(
        select(func.count(Participant.id))
        .where(Participant.session_id.in_(session_ids))
        .where(Participant.is_host.is_(False))
    ) or 0
    finished = db.scalar(
        select(func.count(GameSession.id))
        .where(GameSession.quiz_id == quiz.id)
        .where(GameSession.status == "finished")
    ) or 0

    # Index the authored order so the report follows the quiz, not the sessions.
    order: list[int] = []
    labels: dict[int, str] = {}
    for question in quiz.questions:
        order.append(question.id)
        labels[question.id] = question.text_html
    for row in rows:
        key = row.source_question_id
        if key is not None and key not in labels:
            labels[key] = row.text_html
        if key is not None and key not in order:
            order.append(key)

    buckets: dict[int, dict] = {}
    for row in rows:
        key = row.source_question_id if row.source_question_id is not None else -(row.position + 1)
        bucket = buckets.setdefault(
            key,
            {"answered": 0, "correct": 0, "response_ms": 0, "text_html": row.text_html},
        )
        bucket["answered"] += 1
        bucket["correct"] += 1 if row.is_correct else 0
        bucket["response_ms"] += row.response_ms or 0
        if key not in labels:
            labels[key] = row.text_html
            order.append(key)

    questions = []
    for key in order:
        bucket = buckets.get(key)
        if bucket is None:
            continue
        answered = bucket["answered"]
        questions.append(
            {
                # Report rows are numbered as they are listed, not by their
                # authored position: only answered questions appear here.
                "index": len(questions) + 1,
                "source_question_id": key if key > 0 else None,
                "text_html": labels.get(key, bucket["text_html"]),
                "answered": answered,
                "correct": bucket["correct"],
                "correct_rate": round(bucket["correct"] / answered, 4) if answered else 0.0,
                "average_seconds": round(bucket["response_ms"] / answered / 1000, 1) if answered else 0.0,
            }
        )
    for bucket_key, bucket in buckets.items():
        if bucket_key not in order:
            answered = bucket["answered"]
            questions.append(
                {
                    "index": len(questions) + 1,
                    "source_question_id": bucket_key if bucket_key > 0 else None,
                    "text_html": bucket["text_html"],
                    "answered": answered,
                    "correct": bucket["correct"],
                    "correct_rate": round(bucket["correct"] / answered, 4) if answered else 0.0,
                    "average_seconds": round(bucket["response_ms"] / answered / 1000, 1) if answered else 0.0,
                }
            )

    answers = sum(item["answered"] for item in questions)
    correct = sum(item["correct"] for item in questions)
    total_ms = sum(item["average_seconds"] * item["answered"] for item in questions)
    return {
        "sessions": len(session_ids),
        "finished_sessions": finished,
        "participants": audience,
        "answers": answers,
        "correct_rate": round(correct / answers, 4) if answers else 0.0,
        "average_score": round(sum(score for score, _ in scores) / len(scores)) if scores else 0,
        "average_seconds": round(total_ms / answers, 1) if answers else 0.0,
        "total_questions": len(quiz.questions),
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Poll tallies
# ---------------------------------------------------------------------------
@router.get("/{quiz_id}/results")
def poll_results(
    quiz_id: int,
    user: User | None = Depends(get_optional_user),
    db: OrmSession = Depends(get_db),
):
    """Answer distribution for a poll, filtered by the author's own policy.

    A poll is only worth answering if the shape of the answers is visible, so
    the author decides who reads it: themselves (``private``), the people who
    took part (``respondents``), or anyone who can open the quiz (``public``).
    """
    from ..models import Answer, GameSession, Participant, SessionOption, SessionQuestion

    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_view(quiz, user):
        raise HTTPException(status_code=404, detail="Quiz not found.")

    is_author = user is not None and _can_edit(quiz, user)
    participated = False
    if user is not None:
        participated = (
            db.scalar(
                select(Participant.id)
                .join(GameSession, GameSession.id == Participant.session_id)
                .where(GameSession.quiz_id == quiz.id, Participant.user_id == user.id)
                .limit(1)
            )
            is not None
        )

    visibility = quiz.results_visibility or "respondents"
    allowed = is_author or visibility == "public" or (visibility == "respondents" and participated)
    if not allowed:
        detail = (
            "The author keeps the answers private."
            if visibility == "private"
            else "Only the people who answered this poll can see the results."
        )
        raise HTTPException(status_code=403, detail=detail)

    session_ids = list(db.scalars(select(GameSession.id).where(GameSession.quiz_id == quiz.id)).all())
    respondents = 0
    counts: dict[int, int] = {}
    answered: dict[int, int] = {}
    if session_ids:
        respondents = (
            db.scalar(
                select(func.count(Participant.id))
                .where(Participant.session_id.in_(session_ids))
                .where(Participant.is_host.is_(False))
            )
            or 0
        )
        # Answers point at the session's copy of the options it picked, and the
        # selection is a JSON list, so the tally is done in Python: walk each
        # answer's chosen ids back to the authored option. Counting in SQL on
        # (answer, option) alone would credit every option of the question with
        # every answer.
        session_question_ids = list(
            db.scalars(
                select(SessionQuestion.id).where(SessionQuestion.session_id.in_(session_ids))
            ).all()
        )
        authored_of: dict[int, int] = {}
        source_question_of: dict[int, int] = {}
        if session_question_ids:
            for session_question in db.scalars(
                select(SessionQuestion).where(SessionQuestion.id.in_(session_question_ids))
            ):
                if session_question.source_question_id is not None:
                    source_question_of[session_question.id] = session_question.source_question_id
            for session_option in db.scalars(
                select(SessionOption).where(SessionOption.session_question_id.in_(session_question_ids))
            ):
                if session_option.source_option_id is not None:
                    authored_of[session_option.id] = session_option.source_option_id
            for answer in db.scalars(
                select(Answer).where(Answer.session_question_id.in_(session_question_ids))
            ):
                source_question_id = source_question_of.get(answer.session_question_id)
                if source_question_id is not None:
                    answered[source_question_id] = answered.get(source_question_id, 0) + 1
                for chosen in answer.selected or []:
                    authored = authored_of.get(int(chosen))
                    if authored is not None:
                        counts[authored] = counts.get(authored, 0) + 1

    questions = []
    for position, question in enumerate(sorted(quiz.questions, key=lambda item: item.position)):
        options = []
        for option in sorted(question.options, key=lambda item: item.position):
            count = counts.get(option.id, 0)
            options.append(
                {
                    "id": option.id,
                    "text": option.text,
                    "translations": option.text_translations or {},
                    "count": count,
                }
            )
        total = answered.get(question.id, 0)
        questions.append(
            {
                "id": question.id,
                "index": position + 1,
                "text_html": question.text_html,
                "translations": question.text_translations or {},
                "allow_multiple": bool(question.allow_multiple),
                "respondents": total,
                "options": [
                    {**entry, "share": round(entry["count"] / total, 4) if total else 0.0}
                    for entry in options
                ],
            }
        )

    return {
        "quiz_id": quiz.id,
        "title": quiz.title,
        "mode": quiz.mode,
        "results_visibility": visibility,
        "respondents": respondents,
        "questions": questions,
    }


@router.get("/{quiz_id}/versions", response_model=list[QuizVersionOut])
def list_versions(
    quiz_id: int,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    rows = db.scalars(
        select(QuizVersion).where(QuizVersion.quiz_id == quiz.id).order_by(QuizVersion.number.desc())
    ).all()
    return [QuizVersionOut(**versions.version_summary(row)) for row in rows]


@router.get("/{quiz_id}/versions/{number}")
def get_version(
    quiz_id: int,
    number: int,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    version = versions.version_payload(db, quiz, number)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return {
        **versions.version_summary(version),
        "payload": version.payload,
        "is_live": version.number == (quiz.published_version_number or 0),
    }


@router.post("/{quiz_id}/versions/{number}/restore")
def restore_version(
    quiz_id: int,
    number: int,
    user: User = Depends(require_user),
    body: dict | None = None,
    db: OrmSession = Depends(get_db),
):
    """Copy an old version back into the working copy.

    With ``{"publish": true}`` the restored content also goes live: instantly
    when that version was already approved, through moderation otherwise.
    """
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    version = versions.version_payload(db, quiz, number)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    payload = QuizIn.model_validate(version.payload)
    _apply_quiz(db, quiz, payload)

    published = None
    if bool((body or {}).get("publish")):
        if quiz.legal_status == "blocked":
            raise HTTPException(
                status_code=409,
                detail="This quiz was blocked by the safety review and cannot be published.",
            )
        # A rollback to an already approved version skips moderation.
        published = versions.freeze(
            db,
            quiz,
            user=user,
            payload=versions.snapshot_payload(quiz),
            publish=True,
            auto_publish=bool(version.approved_at or user.is_staff or user.is_trusted),
            note=f"Rollback to version {number}",
        )
        _sync_public_flag(quiz)
        db.add(quiz)
        db.commit()
        db.refresh(quiz)

    return {
        "restored": number,
        "quiz": serialise_quiz(quiz, include_answers=True, viewer=user),
        "status": quiz.status,
        "published_version": quiz.published_version_number,
        "version": versions.version_summary(published) if published else None,
    }


@router.get("/{quiz_id}/reviews")
def get_reviews(
    quiz_id: int,
    user: User | None = Depends(get_optional_user),
    db: OrmSession = Depends(get_db),
):
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_view(quiz, user):
        raise HTTPException(status_code=404, detail="Quiz not found.")
    is_editor = user is not None and _can_edit(quiz, user)
    reviews = sorted(quiz.reviews, key=lambda item: item.created_at, reverse=True)
    # Reviewers' free-text findings stay private to the author and admins.
    payload = [_review_payload(review, quiz, redact=not is_editor) for review in reviews[:20]]
    return {
        "legal_status": quiz.legal_status,
        "legal_checked_at": quiz.legal_checked_at,
        "answer_status": quiz.answer_status,
        "answer_checked_at": quiz.answer_checked_at,
        "reviews": payload,
        "ai_available": ai.is_configured(),
    }


# ---------------------------------------------------------------------------
# AI: translation
# ---------------------------------------------------------------------------
@router.post("/{quiz_id}/ai/translate")
def translate_quiz(
    quiz_id: int,
    payload: AiTranslateIn,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    _ai_guard()
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    enforce_rate_limit(request, "ai", settings.ai_rate_limit, settings.ai_rate_window_seconds)

    source_language = quiz.default_language or FALLBACK_LANGUAGE
    targets = [lang for lang in payload.languages if lang != source_language]
    if not targets:
        raise HTTPException(status_code=400, detail="Pick at least one other language.")

    ordered_questions = sorted(quiz.questions, key=lambda item: item.position)
    scoped = payload.question_index is not None
    if scoped and not 0 <= payload.question_index < len(ordered_questions):
        raise HTTPException(status_code=404, detail="Question not found.")

    # Nothing changed since the last successful translation of the same scope:
    # asking the model again would burn a call for an identical answer.
    if quiz.translation_hash == quiz.content_hash:
        if _translations_are_complete(quiz, targets, ordered_questions, payload.question_index):
            return serialise_quiz(quiz, include_answers=True, viewer=user)

    enforce_ai_interval(user)

    source = quiz_to_ai_dict(quiz, quiz.default_language)
    if scoped:
        # Send one question with the whole document's indices rebuilt, so the
        # model sees the same shape as for a full translation.
        source = {
            **source,
            "title": "",
            "description": "",
            "questions": [source["questions"][payload.question_index]],
        }
    try:
        translations = ai.translate_quiz(source, targets)
    except ai.AiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    applied: list[str] = []
    for language, block in translations.items():
        if block.get("title") and (payload.overwrite or not (quiz.title_translations or {}).get(language)):
            quiz.title_translations = {**(quiz.title_translations or {}), language: block["title"]}
        if block.get("description") and (
            payload.overwrite or not (quiz.description_translations or {}).get(language)
        ):
            quiz.description_translations = {
                **(quiz.description_translations or {}),
                language: block["description"],
            }
        for entry in block.get("questions", []):
            index = entry.get("index")
            if not isinstance(index, int) or not 0 <= index < len(ordered_questions):
                continue
            question = ordered_questions[index]
            if entry.get("text") and (
                payload.overwrite or not (question.text_translations or {}).get(language)
            ):
                question.text_translations = {
                    **(question.text_translations or {}),
                    language: sanitize_html(f"<p>{entry['text']}</p>"),
                }
            options = sorted(question.options, key=lambda item: item.position)
            for option_entry in entry.get("options", []):
                option_index = option_entry.get("index")
                if not isinstance(option_index, int) or not 0 <= option_index < len(options):
                    continue
                option = options[option_index]
                if option_entry.get("text") and (
                    payload.overwrite or not (option.text_translations or {}).get(language)
                ):
                    option.text_translations = {
                        **(option.text_translations or {}),
                        language: option_entry["text"],
                    }
        applied.append(language)

    _sync_languages(quiz)
    quiz.updated_at = utcnow()
    _record_review(
        db,
        quiz,
        kind="translate",
        status_value="ok",
        summary=f"Translated into {', '.join(sorted(applied))}.",
        user=user,
        ip=request.client.host if request.client else None,
    )
    db.add(quiz)
    db.flush()
    # The hash covers the translations themselves, so it has to be recomputed
    # once they are in place; otherwise the stamp describes the untranslated
    # document and the next click would pay for the same call again.
    _refresh_hash(quiz)
    quiz.translation_hash = quiz.content_hash
    db.commit()
    db.refresh(quiz)
    return serialise_quiz(quiz, include_answers=True, viewer=user)


# ---------------------------------------------------------------------------
# AI: reviews
# ---------------------------------------------------------------------------
@router.post("/{quiz_id}/ai/review-legal")
def review_legal(
    quiz_id: int,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: OrmSession = Depends(get_db),
):
    """Safety review required before publication. Cheap enough to be public."""
    _ai_guard()
    quiz = _get_quiz_or_404(db, quiz_id)
    if user is None or not _can_edit(quiz, user):
        if quiz.status != "public":
            raise HTTPException(status_code=404, detail="Quiz not found.")
    enforce_rate_limit(request, "ai", settings.ai_rate_limit, settings.ai_rate_window_seconds)

    cached = next(
        (
            review
            for review in quiz.reviews
            if review.kind == "legal" and review.content_hash == quiz.content_hash
        ),
        None,
    )
    if cached is None:
        if user is not None:
            enforce_ai_interval(user)
        try:
            result = ai.review_safety(quiz_to_ai_dict(quiz))
        except ai.AiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        cached = _record_review(
            db,
            quiz,
            kind="legal",
            status_value=result["status"],
            summary=result["summary"],
            findings=result["findings"],
            user=user,
            ip=request.client.host if request.client else None,
        )
        quiz.legal_status = result["status"]
        quiz.legal_hash = quiz.content_hash
        quiz.legal_checked_at = utcnow()
        if result["status"] == "blocked" and quiz.status in {"public", "pending", "private"}:
            # Pull a blocked quiz out of the catalogue immediately.
            quiz.status = "rejected"
            quiz.moderation_note = "Blocked by the AI safety review."
            _sync_public_flag(quiz)
        db.add(quiz)
        db.commit()
        db.refresh(quiz)
    return _review_payload(cached, quiz, redact=not (user is not None and _can_edit(quiz, user)))


@router.post("/{quiz_id}/ai/review-answers")
def review_answers(
    quiz_id: int,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: OrmSession = Depends(get_db),
):
    """Fact-check the answer key. Any visitor may run it on a public quiz."""
    _ai_guard()
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_view(quiz, user):
        raise HTTPException(status_code=404, detail="Quiz not found.")
    enforce_rate_limit(request, "ai", settings.ai_rate_limit, settings.ai_rate_window_seconds)

    cached = next(
        (
            review
            for review in quiz.reviews
            if review.kind == "answers" and review.content_hash == quiz.content_hash
        ),
        None,
    )
    if cached is None:
        if user is not None:
            enforce_ai_interval(user)
        try:
            result = ai.review_answers(quiz_to_ai_dict(quiz))
        except ai.AiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        cached = _record_review(
            db,
            quiz,
            kind="answers",
            status_value=result["status"],
            summary=result["summary"],
            findings=result["findings"],
            corrections=result["corrections"],
            user=user,
            ip=request.client.host if request.client else None,
        )
        if user is not None and _can_edit(quiz, user):
            quiz.answer_status = "corrected" if result["corrections"] else "ok"
            quiz.answer_hash = quiz.content_hash
            quiz.answer_checked_at = utcnow()
            db.add(quiz)
        db.commit()
        db.refresh(quiz)
    return _review_payload(cached, quiz, redact=not (user is not None and _can_edit(quiz, user)))


@router.post("/{quiz_id}/ai/apply-answers")
def apply_answer_corrections(
    quiz_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
):
    """Apply the latest answer-key corrections to the quiz (new version)."""
    quiz = _get_quiz_or_404(db, quiz_id)
    if not _can_edit(quiz, user):
        raise HTTPException(status_code=403, detail="You do not own this quiz.")
    review = next(
        (
            entry
            for entry in sorted(quiz.reviews, key=lambda item: item.created_at, reverse=True)
            if entry.kind == "answers" and entry.content_hash == quiz.content_hash
        ),
        None,
    )
    if review is None or not review.corrections:
        raise HTTPException(status_code=409, detail="No correction is available for this version.")

    ordered = sorted(quiz.questions, key=lambda item: item.position)
    applied = 0
    for correction in review.corrections:
        index = correction.get("question_index")
        if not isinstance(index, int) or not 0 <= index < len(ordered):
            continue
        question = ordered[index]
        text = correction.get("text")
        options = correction.get("options") or []
        if not isinstance(text, str) or len(options) < 2:
            continue
        if not any(option.get("is_correct") for option in options):
            continue
        if all(option.get("is_correct") for option in options):
            continue
        question.text_html = sanitize_html(f"<p>{text}</p>")
        question.options.clear()
        db.flush()
        for position, option in enumerate(options[:8]):
            question.options.append(
                Option(
                    position=position,
                    text=str(option.get("text") or "")[:500],
                    is_correct=bool(option.get("is_correct")),
                )
            )
        applied += 1
    if not applied:
        raise HTTPException(status_code=409, detail="The corrections could not be applied.")

    quiz.answer_status = "corrected"
    quiz.answer_checked_at = utcnow()
    quiz.updated_at = utcnow()
    _sync_languages(quiz)
    db.add(quiz)
    db.flush()
    _refresh_hash(quiz)
    quiz.answer_hash = quiz.content_hash
    db.commit()
    db.refresh(quiz)
    return {"applied": applied, "quiz": serialise_quiz(quiz, include_answers=True, viewer=user)}


# ---------------------------------------------------------------------------
# Wikis that present this questionnaire
# ---------------------------------------------------------------------------

@router.get("/{quiz_id}/wikis", summary="Wikis linked to this questionnaire")
def quiz_wikis(
    quiz_id: int,
    db: OrmSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if quiz.status != "public" and (user is None or (quiz.owner_id != user.id and not user.is_staff)):
        raise HTTPException(status_code=404, detail="Quiz not found.")
    from .wiki import _member_role, _readable

    rows = db.execute(
        select(Wiki, WikiQuizLink, WikiPage)
        .join(WikiQuizLink, WikiQuizLink.wiki_id == Wiki.id)
        .join(WikiPage, (WikiPage.wiki_id == Wiki.id) & (WikiPage.parent_id.is_(None)))
        .where(WikiQuizLink.quiz_id == quiz.id)
    ).all()
    items = []
    seen: set[int] = set()
    for wiki, _link, home in rows:
        if wiki.id in seen:
            continue
        role = _member_role(db, wiki, user)
        if not _readable(wiki, role):
            continue
        seen.add(wiki.id)
        items.append(
            {
                "id": wiki.id,
                "title": wiki.title,
                "slug": home.slug,
                "description": wiki.description or "",
                "status": wiki.status,
                "is_public": bool(wiki.is_public),
            }
        )
    return {"items": items}
