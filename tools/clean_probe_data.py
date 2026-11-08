# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Remove every account and quiz created by the probe and E2E runs.

Only accounts the probes created themselves are deleted: their addresses are
`<prefix>-<hex>@example.com` or plain `@example.com`. A first version deleted
"everybody who is not in KEEP", which silently removed a real guest account and
the wiki she had just written. Never again: an address that does not carry the
probe signature is reported and left alone.
"""

from __future__ import annotations

import os
import re
import sys

from sqlalchemy import create_engine, text

# Accounts to spare, comma separated, from the environment: a real address has
# nothing to do in the repository.
KEEP = {
    address.strip().lower()
    for address in os.environ.get("OL_KEEP_EMAILS", "demo@example.com").split(",")
    if address.strip()
}
# `solo-1a2b3c@example.com`, `wiki-live-…@example.com`, `probe@example.com`.
PROBE_EMAIL = re.compile(r"^[a-z0-9._%+-]+@(example\.com|example\.org)$", re.I)
# The demo catalogue belongs to the seeder's own account. Its address carries
# the probe signature, so a cleanup erased it and took the demo wikis, pages and
# quizzes with it. That account is content, never a leftover: it survives on its
# address and, in case the address is configured differently, on its name.
DEMO_OWNER_EMAIL = (os.environ.get("OL_SEED_OWNER_EMAIL") or "curator@example.com").strip().lower()
DEMO_OWNER_NAME = "OpenLearn Curator"
KEEP.add(DEMO_OWNER_EMAIL)
# The path is configurable so the script can run in a throwaway container that
# mounts the data volume somewhere else than /app/data.
DB = os.environ.get("OL_DATABASE_URL") or "sqlite:////app/data/openlearn.db"

engine = create_engine(DB)
with engine.begin() as conn:
    doomed = []
    kept = []
    for user_id, email, display_name in conn.execute(
        text("select id, email, display_name from users")
    ):
        address = (email or "").lower()
        if address in KEEP or (display_name or "") == DEMO_OWNER_NAME:
            kept.append((user_id, email))
        elif PROBE_EMAIL.match(address):
            doomed.append(user_id)
        else:
            kept.append((user_id, email))
    for user_id, email in kept:
        if (email or "").lower() in KEEP:
            print(f"kept protected account #{user_id} <{email}>")
        else:
            print(f"kept real account #{user_id} <{email}>")
    marks = ",".join(str(int(uid)) for uid in doomed) or "-1"
    # Quizzes owned by an account that no longer exists are leftovers from an
    # earlier cleanup: they must go too, otherwise the catalogue keeps them.
    quiz_ids = [
        row[0]
        for row in conn.execute(
            text(
                # `owner_id not in (...)` is NULL-safe only with the explicit
                # IS NULL branch: a quiz whose owner was deleted earlier keeps a
                # NULL owner and would otherwise survive every cleanup.
                "select id from quizzes where owner_id is null or owner_id in ("
                + marks
                + ") or owner_id not in (select id from users)"
            )
        )
    ]
    # No probe account left? The orphan pass below still has work to do (a wiki
    # erased by hand leaves its templates and pages behind), so carry on.

    quiz_marks = ",".join(str(int(q)) for q in quiz_ids) or "-1"

    sessions = [
        row[0]
        for row in conn.execute(
            text(
                f"select id from game_sessions where quiz_id in ({quiz_marks}) or host_user_id in ({marks})"
            )
        )
    ]
    session_marks = ",".join(str(int(s)) for s in sessions) or "-1"

    # The wiki arrived after the quiz tables: a probe account that wrote pages
    # leaves them behind, and the catalogue keeps listing a wiki nobody owns.
    wiki_ids = [
        row[0]
        for row in conn.execute(
            text(
                "select id from wikis where owner_id is null or owner_id in ("
                + marks
                + ") or owner_id not in (select id from users)"
            )
        )
    ]
    wiki_marks = ",".join(str(int(w)) for w in wiki_ids) or "-1"

    stats = {}
    for table, where in (
        ("wiki_pages_fts", f"rowid in (select id from wiki_pages where wiki_id in ({wiki_marks}))"),
        (
            "wiki_links",
            f"wiki_id in ({wiki_marks}) or from_page_id in (select id from wiki_pages where wiki_id in ({wiki_marks}))",
        ),
        ("wiki_proposals", f"page_id in (select id from wiki_pages where wiki_id in ({wiki_marks})) or author_id in ({marks})"),
        ("wiki_page_versions", f"page_id in (select id from wiki_pages where wiki_id in ({wiki_marks}))"),
        ("wiki_pages", f"wiki_id in ({wiki_marks})"),
        ("wiki_chat_messages", f"chat_id in (select id from wiki_chats where user_id in ({marks}))"),
        ("wiki_chats", f"user_id in ({marks})"),
        ("wiki_templates", f"wiki_id in ({wiki_marks}) or author_id in ({marks})"),
        ("wiki_members", f"wiki_id in ({wiki_marks}) or user_id in ({marks})"),
        ("ai_jobs", f"user_id in ({marks})"),
        ("wikis", f"id in ({wiki_marks})"),
        (
            "answers",
            f"participant_id in (select id from participants where session_id in ({session_marks}))"
            f" or session_question_id in (select id from session_questions where session_id in ({session_marks}))",
        ),
        ("session_options", f"session_question_id in (select id from session_questions where session_id in ({session_marks}))"),
        ("session_questions", f"session_id in ({session_marks})"),
        ("participants", f"session_id in ({session_marks})"),
        ("game_sessions", f"id in ({session_marks})"),
        ("adventure_runs", f"quiz_id in ({quiz_marks}) or user_id in ({marks})"),
        ("api_keys", f"user_id in ({marks})"),
        # Evaluation grants and wiki<->quiz links arrived later: a probe run that
        # granted itself an extra attempt must not leave the row behind.
        ("quiz_attempt_grants", f"user_id in ({marks}) or quiz_id in ({quiz_marks})"),
        ("wiki_quizzes", f"wiki_id in ({wiki_marks}) or quiz_id in ({quiz_marks})"),
        ("wiki_shares", f"wiki_id in ({wiki_marks})"),
        ("quiz_versions", f"quiz_id in ({quiz_marks})"),
        ("options", f"question_id in (select id from questions where quiz_id in ({quiz_marks}))"),
        ("questions", f"quiz_id in ({quiz_marks})"),
        ("quizzes", f"id in ({quiz_marks})"),
        ("users", f"id in ({marks})"),
    ):
        try:
            result = conn.execute(text(f"delete from {table} where {where}"))
            stats[table] = result.rowcount
        except Exception as error:  # table may not exist in this build
            stats[table] = f"skipped ({error.__class__.__name__})"

    # Orphans left by earlier manual deletes. These are the dangerous ones:
    # SQLite recycles their ids, and a recycled question id makes a new quiz
    # inherit a dead quiz's answer key.
    for sql in (
        "delete from options where question_id not in (select id from questions)",
        "delete from questions where quiz_id not in (select id from quizzes)",
        "delete from quiz_versions where quiz_id not in (select id from quizzes)",
        "delete from adventure_runs where quiz_id not in (select id from quizzes)",
        "delete from answers where participant_id not in (select id from participants)",
        "delete from answers where session_question_id not in (select id from session_questions)",
        "delete from session_options where session_question_id not in (select id from session_questions)",
        "delete from session_questions where session_id not in (select id from game_sessions)",
        "delete from participants where session_id not in (select id from game_sessions)",
        "delete from wiki_page_versions where page_id not in (select id from wiki_pages)",
        "delete from wiki_proposals where page_id not in (select id from wiki_pages)",
        "delete from wiki_links where from_page_id not in (select id from wiki_pages)",
        "delete from wiki_pages where wiki_id not in (select id from wikis)",
        "delete from wiki_members where wiki_id not in (select id from wikis)",
        "delete from wiki_templates where wiki_id not in (select id from wikis)",
        "delete from wikis where owner_id not in (select id from users)",
        "delete from quiz_attempt_grants where quiz_id not in (select id from quizzes)",
        "delete from quiz_attempt_grants where user_id not in (select id from users)",
        "delete from wiki_quizzes where wiki_id not in (select id from wikis)",
        "delete from wiki_quizzes where quiz_id not in (select id from quizzes)",
    ):
        conn.execute(text(sql))

    print("deleted:", stats)
    print("users left:", [tuple(r) for r in conn.execute(text("select id, email from users"))])
    print(
        "quizzes left:",
        [tuple(r) for r in conn.execute(text("select id, title, mode from quizzes order by id"))],
    )
    print("sessions:", conn.execute(text("select count(*) from game_sessions")).scalar())
    print("participants:", conn.execute(text("select count(*) from participants")).scalar())
    print("session_questions:", conn.execute(text("select count(*) from session_questions")).scalar())
    print("answers:", conn.execute(text("select count(*) from answers")).scalar())
