#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
# Install the demo catalogue into a running instance.
#
#   ./tools/demo-seed.sh                    # seed the container "openlearn"
#   ./tools/demo-seed.sh my-container       # seed another container
#
# The catalogue is data (demo/content/*.json). This script forces a reinstall
# even when the fingerprint stored in the database has not changed, which is
# what you want after editing a file: the seeder skips work it has already done.
set -eu

CONTAINER="${1:-openlearn}"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Container '$CONTAINER' not found." >&2
  exit 1
fi

echo "Installing the demo catalogue into $CONTAINER…"
# `-i` feeds the heredoc: without it `docker exec` closes stdin at once and
# python runs an empty script that still exits 0 — the seed then reports success
# without touching the database. `-w /app/backend` puts `import app` on the path
# (serve.sh starts uvicorn with `--app-dir`).
docker exec -i -w /app/backend -e OL_DEMO_MODE=true "$CONTAINER" python - <<'PY'
import json

from app.db import SessionLocal
from app.demo.seed import seed_showcase, validate_content

problems = validate_content()
if problems:
    raise SystemExit("Invalid demo content:\n" + "\n".join(problems[:10]))

stats = seed_showcase(force=True)
print(json.dumps(stats))

with SessionLocal() as db:
    from sqlalchemy import func, select

    from app.models import Quiz, Wiki

    wikis = db.scalar(select(func.count()).select_from(Wiki))
    quizzes = db.scalar(select(func.count()).select_from(Quiz))
print(f"Now holding {wikis} wikis and {quizzes} questionnaires.")
PY

echo "Done. Open the site, the catalogue should be there."
