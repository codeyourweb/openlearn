#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
#
# Take a consistent backup of an OpenLearn instance: SQLite database, media files,
# and the secret key needed to make the archive self-sufficient.
#
# Usage:
#   OL_BACKUP_DIR=/var/backups/openlearn tools/backup.sh
#   OL_BACKUP_DIR=... OL_BACKUP_PASSPHRASE=... tools/backup.sh   # encrypted
#
# A plain `cp` of a live SQLite file can capture a half-written page, and the copy
# then fails to open exactly when you need it. This script goes through SQLite's
# own backup API inside the container instead.

set -euo pipefail

BACKUP_DIR="${OL_BACKUP_DIR:-./backups}"
CONTAINER="${OPENLEARN_CONTAINER:-openlearn}"
SERVICE="${OL_SERVICE:-app}"
COMPOSE="${COMPOSE:-docker compose}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
ARCHIVE="${BACKUP_DIR}/openlearn-${STAMP}.tar.gz"

cleanup() { rm -rf "${WORK}"; }
trap cleanup EXIT

log() { printf '%s\n' "$*" >&2; }

if [ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null || echo false)" != "true" ]; then
  log "error: container '${CONTAINER}' is not running"
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

log "==> database"
# /tmp is not writable in a hardened container: the copy goes next to the data.
DUMP="/app/data/.backup-$$.db"
${COMPOSE} exec -T -e OL_DUMP="${DUMP}" "${SERVICE}" python -c '
import os
import sqlite3

source = sqlite3.connect("/app/data/openlearn.db")
target = sqlite3.connect(os.environ["OL_DUMP"])
with target:
    source.backup(target)
source.close()
target.close()
'
docker cp "${CONTAINER}:${DUMP}" "${WORK}/openlearn.db" >/dev/null
${COMPOSE} exec -T "${SERVICE}" rm -f "${DUMP}"

if [ ! -s "${WORK}/openlearn.db" ]; then
  log "error: the database copy is empty"
  exit 1
fi

log "==> media"
docker cp "${CONTAINER}:/app/data/media" "${WORK}/media" >/dev/null

log "==> secret key"
docker cp "${CONTAINER}:/app/data/.secret_key" "${WORK}/.secret_key" >/dev/null 2>&1 || \
  log "warning: no /app/data/.secret_key; sessions will not survive a restore"

log "==> manifest"
media_count="$(find "${WORK}/media" -type f 2>/dev/null | wc -l | tr -d ' ')"
media_bytes="$(du -sk "${WORK}/media" 2>/dev/null | cut -f1)"
# The counts travel with the archive: a restore can then prove it installed what
# was saved, instead of only proving that the service starts.
counts="$(python3 - "${WORK}/openlearn.db" <<'PY'
import json
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
counts = {}
for table in ("users", "quizzes", "questions", "wiki_pages"):
    try:
        counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        counts[table] = None
connection.close()
print(json.dumps(counts))
PY
)"
printf '{\n  "created_at": "%s",\n  "database_bytes": %s,\n  "media_files": %s,\n  "media_kib": %s,\n  "counts": %s\n}\n' \
  "${STAMP}" "$(wc -c < "${WORK}/openlearn.db" | tr -d ' ')" "${media_count}" "${media_bytes:-0}" "${counts}" \
  > "${WORK}/manifest.json"
cat "${WORK}/manifest.json" >&2

log "==> archive"
tar -C "${WORK}" -czf "${ARCHIVE}" .

if [ -n "${OL_BACKUP_PASSPHRASE:-}" ]; then
  log "==> encryption"
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
    -in "${ARCHIVE}" -out "${ARCHIVE}.enc" -pass env:OL_BACKUP_PASSPHRASE
  rm -f "${ARCHIVE}"
  ARCHIVE="${ARCHIVE}.enc"
fi

# A backup nobody checked is a hope: reopen the archive and walk through it.
log "==> verify"
case "${ARCHIVE}" in
  *.enc)
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
      -in "${ARCHIVE}" -pass env:OL_BACKUP_PASSPHRASE | tar -tzf - >/dev/null
    ;;
  *)
    tar -tzf "${ARCHIVE}" >/dev/null
    ;;
esac

log "backup: ${ARCHIVE} ($(du -h "${ARCHIVE}" | cut -f1))"
