# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Forward-only schema migrations.

The project ships without a migration framework on purpose: a self-hosted
single-node deployment only needs to move an existing SQLite file forward.
``add_missing_columns`` reads ``PRAGMA table_info`` and adds whatever the ORM
expects but the file lacks, so an existing installation keeps its data.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# table -> column -> DDL fragment (SQLite accepts defaults on ADD COLUMN)
_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
        "is_moderator": "BOOLEAN NOT NULL DEFAULT 0",
        "is_trusted": "BOOLEAN NOT NULL DEFAULT 0",
        # Existing accounts predate the confirmation link: they are treated as
        # confirmed, otherwise an upgrade would flag every one of them.
        "email_verified": "BOOLEAN NOT NULL DEFAULT 1",
        "email_verified_at": "TIMESTAMP",
        # Bumped when a password is reset: every token issued before carries the
        # old value and stops being accepted, without a session table.
        "token_version": "INTEGER NOT NULL DEFAULT 0",
    },
    "quizzes": {
        "mode": "VARCHAR(10) NOT NULL DEFAULT 'qcm'",
        "status": "VARCHAR(12) NOT NULL DEFAULT 'draft'",
        "moderation_note": "VARCHAR(300) NOT NULL DEFAULT ''",
        "is_multilingual": "BOOLEAN NOT NULL DEFAULT 0",
        "default_language": "VARCHAR(5) NOT NULL DEFAULT 'en'",
        "languages": "JSON",
        "title_translations": "JSON",
        "description_translations": "JSON",
        "ai_generated": "BOOLEAN NOT NULL DEFAULT 0",
        "content_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        "legal_status": "VARCHAR(12) NOT NULL DEFAULT ''",
        "legal_checked_at": "DATETIME",
        "legal_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        "answer_status": "VARCHAR(12) NOT NULL DEFAULT ''",
        "answer_checked_at": "DATETIME",
        "answer_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        "published_at": "DATETIME",
        "approved_by_id": "INTEGER",
        "adventure_start_key": "VARCHAR(60) NOT NULL DEFAULT ''",
        "adventure_settings": "JSON",
        "published_version_number": "INTEGER NOT NULL DEFAULT 0",
        "timer_mode": "VARCHAR(14) NOT NULL DEFAULT 'per_question'",
        "global_time_limit_seconds": "INTEGER NOT NULL DEFAULT 0",
        "results_visibility": "VARCHAR(12) NOT NULL DEFAULT 'respondents'",
        "translation_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        "max_attempts": "INTEGER NOT NULL DEFAULT 0",
        "share_token": "VARCHAR(48)",
    },
    "questions": {
        "text_translations": "JSON",
        "allow_multiple": "BOOLEAN NOT NULL DEFAULT 0",
        # {"x", "y", "zoom"}: how the author framed the picture in its frame.
        "image_framing": "JSON",
    },
    "options": {"text_translations": "JSON"},
    "session_questions": {
        "allow_multiple": "BOOLEAN NOT NULL DEFAULT 0",
        # Frozen with the wording: a run keeps the framing it started with.
        "image_framing": "JSON",
        # Translations frozen with the snapshot, so a run can change language
        # without restarting.
        "text_translations": "JSON",
    },
    "session_options": {"text_translations": "JSON"},
    "game_sessions": {
        "quiz_mode": "VARCHAR(10) NOT NULL DEFAULT 'qcm'",
        "language": "VARCHAR(5) NOT NULL DEFAULT 'en'",
        "run_deadline": "DATETIME",
        "timer_mode": "VARCHAR(14) NOT NULL DEFAULT 'per_question'",
        "global_time_limit_seconds": "INTEGER NOT NULL DEFAULT 0",
    },
    "adventure_runs": {
        "node_deadline": "DATETIME",
        "run_deadline": "DATETIME",
    },
    "wiki_pages": {
        # Menu tree: a page hangs under another one, or nowhere (top level).
        "parent_id": "INTEGER",
        # Subject tags: they draw extra edges in the wiki graph.
        "tags": "JSON",
    },
    "revision_decks": {
        # Shape of the cards, "width:height". Portrait by default.
        "aspect": "VARCHAR(5) NOT NULL DEFAULT '2:3'",
    },
    "revision_cards": {
        # A picture on the back as well: some decks are two-sided illustrations.
        "back_image_path": "VARCHAR(200)",
        # How the author framed each face: {"x": 0-100, "y": 0-100, "zoom": 1-3}.
        "image_framing": "JSON",
        "back_image_framing": "JSON",
    },
    "adventure_nodes": {
        # The same framing, on the scene illustration.
        "image_framing": "JSON",
    },
}


def _existing_columns(connection, table: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table})")).all()
    return {row[1] for row in rows}


def add_missing_columns(engine: Engine) -> list[str]:
    """Add columns missing from an older database. Returns what was added."""
    added: list[str] = []
    with engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).all()
        }
        for table, columns in _COLUMNS.items():
            if table not in tables:
                continue  # create_all already created it in full
            present = _existing_columns(connection, table)
            for column, ddl in columns.items():
                if column in present:
                    continue
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
                added.append(f"{table}.{column}")
    if added:
        logger.info("Schema upgraded: %s", ", ".join(added))
    return added


def backfill_publication(engine: Engine) -> None:
    """Existing public quizzes predate the moderation workflow."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE quizzes SET status = 'public' "
                "WHERE is_public = 1 AND status IN ('draft', '')"
            )
        )
        connection.execute(
            text(
                "UPDATE quizzes SET published_at = updated_at "
                "WHERE status = 'public' AND published_at IS NULL"
            )
        )


def purge_orphans(engine: Engine) -> None:
    """Delete child rows whose parent is gone.

    SQLite does not cascade on its own: a quiz removed with a raw DELETE (a
    maintenance script, a manual fix) leaves its questions and options behind.
    Those rows are invisible until SQLite reuses their ids, at which point a
    brand-new quiz inherits a dead quiz's answers — exactly the kind of ghost
    that makes a correct answer score zero. Cheap enough to run on every boot.
    """
    statements = (
        "DELETE FROM options WHERE question_id NOT IN (SELECT id FROM questions)",
        "DELETE FROM questions WHERE quiz_id NOT IN (SELECT id FROM quizzes)",
        # Second pass: removing a question just orphaned its options.
        "DELETE FROM options WHERE question_id NOT IN (SELECT id FROM questions)",
        "DELETE FROM session_options WHERE session_question_id NOT IN (SELECT id FROM session_questions)",
        "DELETE FROM answers WHERE session_question_id NOT IN (SELECT id FROM session_questions)",
        "DELETE FROM answers WHERE participant_id NOT IN (SELECT id FROM participants)",
        "DELETE FROM session_questions WHERE session_id NOT IN (SELECT id FROM game_sessions)",
        "DELETE FROM participants WHERE session_id NOT IN (SELECT id FROM game_sessions)",
        "DELETE FROM quiz_versions WHERE quiz_id NOT IN (SELECT id FROM quizzes)",
        "DELETE FROM adventure_runs WHERE quiz_id NOT IN (SELECT id FROM quizzes)",
    )
    removed = 0
    with engine.begin() as connection:
        for statement in statements:
            try:
                removed += connection.execute(text(statement)).rowcount or 0
            except Exception as error:  # a table may be absent in an older build
                logger.debug("Orphan purge skipped: %s (%s)", statement, error)
    if removed:
        logger.warning("Removed %s orphan rows left by an earlier delete.", removed)
