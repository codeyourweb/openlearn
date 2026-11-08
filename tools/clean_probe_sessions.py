# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Delete the live sessions left behind by the TLS probes."""

from __future__ import annotations

import sqlite3

DB = "/app/data/openlearn.db"
KEEP_CODES = {"B46BTJ"}  # the finished demo run that feeds the stats tab

conn = sqlite3.connect(DB)
doomed = [
    row[0]
    for row in conn.execute("select id, code from game_sessions")
    if row[1] not in KEEP_CODES
]
if doomed:
    marks = ",".join(str(int(sid)) for sid in doomed)
    conn.execute(
        "delete from answers where session_question_id in "
        f"(select id from session_questions where session_id in ({marks}))"
    )
    conn.execute(
        "delete from session_options where session_question_id in "
        f"(select id from session_questions where session_id in ({marks}))"
    )
    conn.execute(f"delete from session_questions where session_id in ({marks})")
    conn.execute(f"delete from participants where session_id in ({marks})")
    conn.execute(f"delete from game_sessions where id in ({marks})")
    conn.commit()

print("deleted sessions:", len(doomed))
print("sessions left:", conn.execute("select code, status from game_sessions").fetchall())
print("participants:", conn.execute("select count(*) from participants").fetchone()[0])
print("answers:", conn.execute("select count(*) from answers").fetchone()[0])
