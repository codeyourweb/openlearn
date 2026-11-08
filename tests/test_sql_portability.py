# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""SQL that has to run on SQLite, PostgreSQL and MariaDB alike.

Each engine has its own dialect, and two of them reject syntax that the third
accepts happily. ``NULLS LAST`` is the classic example: PostgreSQL and SQLite
understand it, MySQL and MariaDB answer with a syntax error at the very query
the catalogue runs on every visit. Tests here keep the ordering portable instead
of relying on whichever database the developer happens to have running.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import mysql, postgresql, sqlite

from app.models import Quiz

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_no_nulls_last_anywhere_in_the_queries():
    """Sort nulls with a predicate, not with a clause two engines reject."""
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if "nullslast" in path.read_text(encoding="utf-8").lower()
        or "nulls last" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], offenders


def test_the_newest_first_ordering_compiles_for_every_engine():
    """The catalogue order must be valid SQL on all three engines."""
    statement = (
        select(Quiz.id)
        .order_by(Quiz.published_at.is_(None), Quiz.published_at.desc(), Quiz.updated_at.desc())
        .limit(3)
    )
    for dialect in (sqlite.dialect(), postgresql.dialect(), mysql.dialect()):
        sql = str(statement.compile(dialect=dialect)).upper()
        assert "NULLS LAST" not in sql
        assert "ORDER BY" in sql
        # "published_at IS NULL" sorts false (0) before true (1): live first.
        assert "IS NULL" in sql
