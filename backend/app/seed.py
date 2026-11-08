# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Demo content: a 20 question Splunk Power User practice quiz.

Seeded once, on an empty database. Set ``OL_SEED_DEMO_DATA=false`` to disable
and ``OL_DEMO_PASSWORD`` to change the demo account password.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select

from .content import compute_content_hash
from .db import SessionLocal
from .models import Option, Question, Quiz, User, utcnow
from .security import PasswordPolicyError, hash_password, validate_password

logger = logging.getLogger("openlearn.seed")

# Reserved TLDs such as .local are rejected by the email validator, so the
# demo account uses a domain that can actually sign in.
DEMO_EMAIL = os.environ.get("OL_DEMO_EMAIL", "demo@example.com")
DEMO_PASSWORD = os.environ.get("OL_DEMO_PASSWORD", "DemoPassw0rd!")
DEMO_NAME = "OpenLearn Demo"
QUIZ_TITLE = "Splunk Power User - Practice Exam"

# (question, [(option, is_correct), ...], time_limit_seconds)
QUESTIONS: list[tuple[str, list[tuple[str, bool]], int]] = [
    (
        "Which SPL command aggregates events into statistics such as count, average or sum?",
        [
            ("stats", True),
            ("table", False),
            ("eval", False),
            ("dedup", False),
        ],
        30,
    ),
    (
        "What is the purpose of the <b>eval</b> command?",
        [
            ("Create or modify fields by evaluating an expression for each event", True),
            ("Extract fields with a regular expression", False),
            ("Merge related events into a single transaction", False),
            ("Accelerate a data model", False),
        ],
        30,
    ),
    (
        "Which command removes duplicate results based on one or more fields?",
        [
            ("dedup", True),
            ("uniq", False),
            ("sort", False),
            ("uniqify", False),
        ],
        30,
    ),
    (
        "Which command groups related events (for example all events of a single user session) into one result?",
        [
            ("transaction", True),
            ("stats", False),
            ("collect", False),
            ("append", False),
        ],
        30,
    ),
    (
        "Which knowledge object enriches events with data coming from a CSV file or the KV Store?",
        [
            ("Lookup", True),
            ("Tag", False),
            ("Event type", False),
            ("Macro", False),
        ],
        30,
    ),
    (
        "In which configuration file is a lookup <i>definition</i> declared?",
        [
            ("transforms.conf", True),
            ("props.conf", False),
            ("macros.conf", False),
            ("savedsearches.conf", False),
        ],
        30,
    ),
    (
        "Which command queries accelerated data model summaries instead of raw events?",
        [
            ("tstats", True),
            ("datamodel", False),
            ("mstats", False),
            ("dbinspect", False),
        ],
        30,
    ),
    (
        "What must be enabled before <b>tstats</b> can return results for a data model?",
        [
            ("Data model acceleration", True),
            ("Index replication", False),
            ("A scheduled report", False),
            ("Smart mode search", False),
        ],
        30,
    ),
    (
        "Which command adds aggregated values to <i>every</i> event instead of collapsing events into rows?",
        [
            ("eventstats", True),
            ("stats", False),
            ("tstats", False),
            ("top", False),
        ],
        30,
    ),
    (
        "Which eval function returns the first non-null value among its arguments?",
        [
            ("coalesce", True),
            ("ifnull", False),
            ("first", False),
            ("case", False),
        ],
        30,
    ),
    (
        "Which command renames a field in the results?",
        [
            ("rename", True),
            ("alias", False),
            ("fields", False),
            ("eval", False),
        ],
        30,
    ),
    (
        "Which default field holds the timestamp of an event?",
        [
            ("_time", True),
            ("_timestamp", False),
            ("date", False),
            ("_raw", False),
        ],
        30,
    ),
    (
        "Which search mode returns the fields used by the search without returning all event data, and is the fastest?",
        [
            ("Fast", True),
            ("Verbose", False),
            ("Smart", False),
            ("Realtime", False),
        ],
        30,
    ),
    (
        "Which command keeps only the listed fields (or removes the listed fields) from the results?",
        [
            ("fields", True),
            ("table", False),
            ("rename", False),
            ("where", False),
        ],
        30,
    ),
    (
        "Which of the following are knowledge objects? <i>Select all that apply.</i>",
        [
            ("A saved report", True),
            ("A field extraction", True),
            ("A lookup definition", True),
            ("An index", False),
        ],
        45,
    ),
    (
        "Which statements about <b>stats</b> and <b>eventstats</b> are true? <i>Select all that apply.</i>",
        [
            ("stats replaces events with one row per group", True),
            ("eventstats keeps every event and adds the computed values to it", True),
            ("Both commands require data model acceleration", False),
            ("eventstats can only be used with tstats", False),
        ],
        45,
    ),
    (
        "Which commands can compute aggregate statistics? <i>Select all that apply.</i>",
        [
            ("stats", True),
            ("eventstats", True),
            ("tstats", True),
            ("rex", False),
        ],
        45,
    ),
    (
        "A search macro is defined in which configuration file?",
        [
            ("macros.conf", True),
            ("props.conf", False),
            ("transforms.conf", False),
            ("alert_actions.conf", False),
        ],
        30,
    ),
    (
        "What does the <b>fillnull</b> command do?",
        [
            ("Replace null values in specified fields with a default value", True),
            ("Drop events where a field is null", False),
            ("Convert a field to a numeric type", False),
            ("Fill missing timestamps with the current time", False),
        ],
        30,
    ),
    (
        "Which command filters results using a boolean expression evaluated <i>after</i> an aggregation?",
        [
            ("where", True),
            ("search", False),
            ("filter", False),
            ("eval", False),
        ],
        30,
    ),
]


def ensure_admin() -> None:
    """Create or promote the bootstrap administrator declared in the env.

    ``OL_ADMIN_EMAIL``/``OL_ADMIN_PASSWORD`` are the only way to obtain the
    first administrator account without manual SQL.
    """
    from .config import settings

    email = (settings.admin_email or "").strip().lower()
    if not email:
        return
    password = settings.admin_password or ""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            if not password:
                logger.warning("OL_ADMIN_EMAIL set without OL_ADMIN_PASSWORD: admin not created")
                return
            try:
                validate_password(password)
            except PasswordPolicyError as problem:
                logger.warning("Admin password rejected by policy: %s", problem)
                return
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name="Administrator",
                is_admin=True,
                is_trusted=True,
            )
            db.add(user)
            db.commit()
            logger.info("Created bootstrap administrator %s", email)
            return
        if not user.is_admin:
            user.is_admin = True
            user.is_trusted = True
            db.add(user)
            db.commit()
            logger.info("Promoted %s to administrator", email)


def seed_demo_content() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Quiz.id).where(Quiz.title == QUIZ_TITLE)) is not None:
            return

        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name=DEMO_NAME,
            )
            db.add(user)
            db.flush()

        quiz = Quiz(
            owner_id=user.id,
            title=QUIZ_TITLE,
            description=(
                "20 practice questions covering Splunk Core Certified Power User (SPLK-1002) "
                "fundamentals: SPL commands, knowledge objects, data models and acceleration. "
                "Some questions accept several correct answers."
            ),
            wrong_answer_policy="zero",
            mode="qcm",
            status="public",
            is_public=True,
            default_language="en",
            languages=["en"],
            published_at=utcnow(),
        )
        db.add(quiz)
        db.flush()

        for position, (text_html, options, time_limit) in enumerate(QUESTIONS):
            question = Question(
                quiz_id=quiz.id,
                position=position,
                text_html=text_html,
                time_limit_seconds=time_limit,
                points=100,
            )
            for option_position, (option_text, is_correct) in enumerate(options):
                question.options.append(
                    Option(position=option_position, text=option_text, is_correct=is_correct)
                )
            db.add(question)

        db.flush()
        db.refresh(quiz)
        quiz.content_hash = compute_content_hash(quiz)
        db.commit()
        logger.info("Seeded demo quiz '%s' with %d questions", QUIZ_TITLE, len(QUESTIONS))
