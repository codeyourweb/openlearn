# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The cleanup script deletes accounts; it has to know what it must never touch.

The demo catalogue is written by the seeder's own account, and that account's
address looks exactly like a probe leftover (`curator@example.com`). A cleanup
therefore erased it and took the demo wikis, their pages and the demo quizzes
with it. These tests run the real script against a throwaway database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Quiz, User, Wiki, WikiPage

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "clean_probe_data.py"
PROBE_EMAIL = "wiki-links-9f3c1a@example.com"


def _prepare(db_path: Path, curator_email: str = "curator@example.com", curator_name: str = "OpenLearn Curator") -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        curator = User(email=curator_email, password_hash="x", display_name=curator_name)
        probe = User(email=PROBE_EMAIL, password_hash="x", display_name="Link Tester")
        session.add_all([curator, probe])
        session.flush()

        demo = Wiki(
            owner_id=curator.id,
            title="Climate and resources",
            slug="environment",
            status="public",
            is_public=True,
        )
        leftover = Wiki(owner_id=probe.id, title="Probe wiki", slug="probe-wiki", status="private")
        session.add_all([demo, leftover])
        session.flush()

        session.add(
            WikiPage(
                wiki_id=demo.id,
                slug="the-greenhouse-effect",
                title="The greenhouse effect",
                content_md="# The greenhouse effect",
                position=0,
            )
        )
        # A quiz owned by the curator: the demo catalogue is more than wikis.
        session.add(Quiz(owner_id=curator.id, title="Demo quiz", mode="qcm"))
        session.commit()
    engine.dispose()


def _run_cleanup(db_path: Path) -> subprocess.CompletedProcess:
    environment = {
        **os.environ,
        "OL_DATABASE_URL": f"sqlite:///{db_path}",
        "OL_KEEP_EMAILS": "",
        "OL_SEED_OWNER_EMAIL": "",
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _state(db_path: Path) -> tuple[set[str], set[str], set[str], int, int]:
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        emails = {user.email for user in session.scalars(select(User))}
        wikis = {wiki.slug for wiki in session.scalars(select(Wiki))}
        pages = {page.slug for page in session.scalars(select(WikiPage))}
        quizzes = session.scalar(select(func.count()).select_from(Quiz)) or 0
        users = session.scalar(select(func.count()).select_from(User)) or 0
    engine.dispose()
    return emails, wikis, pages, quizzes, users


def test_the_cleanup_spares_the_account_that_owns_the_demo_catalogue(tmp_path):
    db_path = tmp_path / "cleanup.db"
    _prepare(db_path)

    result = _run_cleanup(db_path)
    assert result.returncode == 0, result.stderr
    assert "kept protected account" in result.stdout, result.stdout

    emails, wikis, pages, quizzes, users = _state(db_path)
    assert "curator@example.com" in emails, "the seeder account was deleted"
    assert PROBE_EMAIL not in emails, "the probe account survived"
    assert "environment" in wikis, "the demo wiki went with the account"
    assert "the-greenhouse-effect" in pages, "the demo pages went with the wiki"
    assert quizzes == 1, "the demo quiz went with the account"
    assert users == 1, (users, emails)


def test_the_cleanup_also_recognises_the_seeder_by_its_name(tmp_path):
    """A deployment may configure another address for the demo owner."""
    db_path = tmp_path / "cleanup-name.db"
    _prepare(db_path, curator_email="catalogue@example.org")

    result = _run_cleanup(db_path)
    assert result.returncode == 0, result.stderr

    emails, wikis, _, quizzes, _ = _state(db_path)
    assert "catalogue@example.org" in emails
    assert "environment" in wikis
    assert quizzes == 1


def test_the_cleanup_still_removes_what_the_probes_created(tmp_path):
    db_path = tmp_path / "cleanup-probe.db"
    _prepare(db_path)

    assert _run_cleanup(db_path).returncode == 0

    emails, wikis, _, _, _ = _state(db_path)
    assert PROBE_EMAIL not in emails
    assert "probe-wiki" not in wikis
