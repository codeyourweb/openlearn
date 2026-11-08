# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Full text search over quizzes.

SQLite ships FTS5 in the standard build, but not every distribution compiles it
in. ``ensure_index`` creates the virtual table and its triggers once; when that
is impossible the search helpers return ``None`` and callers fall back to a
``LIKE`` scan, so the feature degrades instead of breaking the deployment.

The index owns its own copy of the text (plain FTS5 table, no ``content=``
option). An external-content table has to be kept byte-for-byte in sync with
the base table: any row whose stored values drifted makes the index match the
wrong document, which silently corrupts results. Copying the text keeps the
index self-consistent, and it is rebuilt from scratch at every boot so a
previous crash or an older schema can never leave stale hits behind.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

logger = logging.getLogger(__name__)

_DROP_TABLE = "DROP TABLE IF EXISTS quizzes_fts"

_CREATE_TABLE = """
CREATE VIRTUAL TABLE quizzes_fts USING fts5(
    title,
    description,
    tokenize='unicode61 remove_diacritics 2'
)
"""

_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS quizzes_fts_ai AFTER INSERT ON quizzes BEGIN
        INSERT INTO quizzes_fts(rowid, title, description)
        VALUES (new.id, new.title, coalesce(new.description, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS quizzes_fts_ad AFTER DELETE ON quizzes BEGIN
        DELETE FROM quizzes_fts WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS quizzes_fts_au AFTER UPDATE ON quizzes BEGIN
        DELETE FROM quizzes_fts WHERE rowid = old.id;
        INSERT INTO quizzes_fts(rowid, title, description)
        VALUES (new.id, new.title, coalesce(new.description, ''));
    END
    """,
)

_REINDEX = """
INSERT INTO quizzes_fts(rowid, title, description)
SELECT id, title, coalesce(description, '') FROM quizzes
"""


def _is_sqlite(db: OrmSession) -> bool:
    """FTS5 exists in SQLite only: other engines fall back to LIKE.

    Trying the DDL on PostgreSQL or MariaDB raises a syntax error that the
    operator reads as a failure, while it only means "this engine has no FTS5".
    """
    bind = db.get_bind()
    return bind is not None and bind.dialect.name == "sqlite"


def ensure_index(db: OrmSession) -> bool:
    """(Re)build the FTS table and its triggers. True when search is available."""
    if not _is_sqlite(db):
        logger.info("Full-text search needs SQLite FTS5: using LIKE on %s", db.get_bind().dialect.name)
        return False
    try:
        # Start from a clean slate: the table is rebuilt from the base rows, and
        # the triggers are recreated so an older definition cannot survive.
        db.execute(text(_DROP_TABLE))
        db.execute(text("DROP TRIGGER IF EXISTS quizzes_fts_ai"))
        db.execute(text("DROP TRIGGER IF EXISTS quizzes_fts_ad"))
        db.execute(text("DROP TRIGGER IF EXISTS quizzes_fts_au"))
        db.execute(text(_CREATE_TABLE))
        for statement in _TRIGGERS:
            db.execute(text(statement))
        db.execute(text(_REINDEX))
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - any driver error means "no FTS"
        db.rollback()
        logger.info("FTS5 unavailable, falling back to LIKE search: %s", exc)
        return False


def refresh_quiz(db: OrmSession, quiz) -> None:
    """Point the index entry at what visitors actually see.

    The triggers keep the row in sync with the working copy, which is what an
    author searches for in their own dashboard. For a published quiz the live
    version is what the catalogue advertises, so the row is rewritten from the
    frozen payload: a word that only exists in an unpublished draft must never
    make a quiz show up in the public search.
    """
    if not _is_sqlite(db):
        return  # no FTS table on this engine: nothing to keep in sync
    from . import versions

    payload = versions.published_payload(db, quiz) if quiz.status == "public" else None
    title = (payload or {}).get("title") or quiz.title
    description = (payload or {}).get("description") or (quiz.description if payload is None else "")
    try:
        db.execute(text("DELETE FROM quizzes_fts WHERE rowid = :id"), {"id": quiz.id})
        db.execute(
            text("INSERT INTO quizzes_fts(rowid, title, description) VALUES (:id, :title, :description)"),
            {"id": quiz.id, "title": title, "description": description or ""},
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - no FTS build: nothing to refresh
        db.rollback()
        logger.info("FTS refresh skipped: %s", exc)


def fts_query(raw: str) -> str:
    """Turn user input into a safe FTS5 expression (tokens AND-ed, prefix match)."""
    tokens = [token for token in "".join(ch if ch.isalnum() else " " for ch in raw).split() if token]
    if not tokens:
        return ""
    return " ".join(f'"{token}"*' for token in tokens[:8])


# Words that carry no signal in a question: keeping them made the wiki chat
# require every one of them in the same page, so "À quoi sert un résolveur
# récursif ?" matched nothing at all.
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was",
    "what", "which", "who", "how", "why", "does", "do", "did", "with", "from", "that",
    "le", "la", "les", "un", "une", "des", "du", "de", "au", "aux", "et", "ou", "est",
    "sont", "que", "qui", "quoi", "quel", "quelle", "quels", "quelles", "comment",
    "pourquoi", "dans", "sur", "pour", "avec", "par", "ce", "cette", "ces", "il",
    "elle", "se", "sa", "son", "ses", "à", "en", "y",
}


def keywords(raw: str, limit: int = 8) -> list[str]:
    """Content words of a question, longest first."""
    tokens = [
        token
        for token in "".join(ch if ch.isalnum() else " " for ch in raw).split()
        if len(token) > 2 and token.lower() not in _STOPWORDS
    ]
    return sorted(dict.fromkeys(tokens), key=len, reverse=True)[:limit]


def fts_any_query(raw: str) -> str:
    """FTS5 expression matching *any* keyword, so bm25 can rank the best page.

    AND-ing every token (the old behaviour) found nothing as soon as the
    question contained one word absent from the page.
    """
    tokens = keywords(raw)
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"*' for token in tokens)


def search_ids(db: OrmSession, raw: str, limit: int = 100) -> list[int] | None:
    """Return quiz ids ranked by relevance, or None when FTS5 is unavailable."""
    expression = fts_query(raw)
    if not expression:
        return []
    # Asking for an FTS table on an engine that has none aborts the transaction:
    # PostgreSQL then refuses every later statement until a rollback, which is
    # how a search ended in a 500 instead of the LIKE fallback.
    if not _is_sqlite(db):
        return None
    try:
        rows = db.execute(
            text(
                "SELECT rowid FROM quizzes_fts WHERE quizzes_fts MATCH :q "
                "ORDER BY bm25(quizzes_fts, 2.0, 1.0) LIMIT :limit"
            ),
            {"q": expression, "limit": limit},
        ).all()
    except Exception as exc:  # noqa: BLE001 - table missing or malformed query
        logger.info("FTS query failed, falling back to LIKE: %s", exc)
        db.rollback()
        return None
    return [int(row[0]) for row in rows]


# ---------------------------------------------------------------------------
# Wiki pages
# ---------------------------------------------------------------------------
_WIKI_DROP = "DROP TABLE IF EXISTS wiki_pages_fts"

_WIKI_CREATE = """
CREATE VIRTUAL TABLE wiki_pages_fts USING fts5(
    title,
    content,
    tokenize='unicode61 remove_diacritics 2'
)
"""

_WIKI_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS wiki_pages_fts_ai AFTER INSERT ON wiki_pages BEGIN
        INSERT INTO wiki_pages_fts(rowid, title, content)
        VALUES (new.id, new.title, coalesce(new.content_md, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS wiki_pages_fts_ad AFTER DELETE ON wiki_pages BEGIN
        DELETE FROM wiki_pages_fts WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS wiki_pages_fts_au AFTER UPDATE ON wiki_pages BEGIN
        DELETE FROM wiki_pages_fts WHERE rowid = old.id;
        INSERT INTO wiki_pages_fts(rowid, title, content)
        VALUES (new.id, new.title, coalesce(new.content_md, ''));
    END
    """,
)


def ensure_wiki_index(db: OrmSession) -> bool:
    """Create the page index. Returns False when SQLite has no FTS5."""
    if not _is_sqlite(db):
        logger.info("Wiki search needs SQLite FTS5: using LIKE on %s", db.get_bind().dialect.name)
        return False
    try:
        db.execute(text(_WIKI_DROP))
        for trigger in ("wiki_pages_fts_ai", "wiki_pages_fts_ad", "wiki_pages_fts_au"):
            db.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db.execute(text(_WIKI_CREATE))
        for statement in _WIKI_TRIGGERS:
            db.execute(text(statement))
        db.execute(
            text(
                "INSERT INTO wiki_pages_fts(rowid, title, content) "
                "SELECT id, title, coalesce(content_md, '') FROM wiki_pages"
            )
        )
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - any driver error means "no FTS"
        db.rollback()
        logger.info("Wiki FTS5 unavailable, falling back to LIKE: %s", exc)
        return False


def search_wiki_pages(
    db: OrmSession, raw: str, *, wiki_ids: list[int] | None = None, limit: int = 60
) -> list[tuple[int, float]] | None:
    """Rid of matching pages, best first, or None when FTS5 is unavailable."""
    expression = fts_query(raw)
    if not expression:
        return []
    if not _is_sqlite(db):
        return None
    scope = ""
    params: dict[str, object] = {"q": expression, "limit": limit}
    if wiki_ids is not None:
        if not wiki_ids:
            return []
        placeholders = ",".join(str(int(wiki_id)) for wiki_id in wiki_ids[:200])
        scope = f" AND wiki_id IN ({placeholders})"
        params = {"q": expression, "limit": limit}
    try:
        rows = db.execute(
            text(
                "SELECT p.id, bm25(wiki_pages_fts, 3.0, 1.0) AS score "
                "FROM wiki_pages_fts f JOIN wiki_pages p ON p.id = f.rowid "
                "WHERE wiki_pages_fts MATCH :q" + scope + " ORDER BY score LIMIT :limit"
            ),
            params,
        ).all()
    except Exception as exc:  # noqa: BLE001 - table missing or malformed query
        logger.info("Wiki FTS query failed, falling back to LIKE: %s", exc)
        db.rollback()
        return None
    return [(int(row[0]), float(row[1])) for row in rows]
