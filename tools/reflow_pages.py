#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Reflow the paragraphs of existing wiki pages.

Text written before the reflow existed — an aged import, a demo seed, a model
answer — carries the line breaks of whatever wrapped it at 70 columns. This
walks every page, reports what would change, and with ``--apply`` saves the
normalised text as a new version, so the history keeps both the old and the new
state instead of rewriting it.

    python tools/reflow_pages.py            # dry run
    python tools/reflow_pages.py --apply    # write a new version per changed page
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import WikiPage  # noqa: E402
from app.wiki import reflow_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="save the changes as new versions")
    parser.add_argument("--wiki", type=int, default=None, help="limit to one wiki id")
    options = parser.parse_args()

    from sqlalchemy import select

    from app.models import User
    from app.routers.wiki import _freeze

    changed = total = 0
    with SessionLocal() as db:
        statement = select(WikiPage)
        if options.wiki:
            statement = statement.where(WikiPage.wiki_id == options.wiki)
        pages = db.scalars(statement).all()
        total = len(pages)

        for page in pages:
            before = page.content_md or ""
            after = reflow_markdown(before)
            if after == before:
                continue
            changed += 1
            freed = len(before) - len(after)
            print(f"#{page.id} {page.title!r}: {freed} caractères de coupure en moins")
            if not options.apply:
                continue
            author = db.get(User, page.author_id) if page.author_id else None
            page.content_md = after
            _freeze(db, page, author, note="Reflow paragraphs")
            db.commit()

    verb = "réécrites" if options.apply else "à réécrire"
    print(f"pages: {total} | {verb}: {changed}")
    if changed and not options.apply:
        print("relancer avec --apply pour enregistrer une nouvelle version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
