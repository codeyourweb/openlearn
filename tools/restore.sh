#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
#
# Restore an OpenLearn instance from an archive produced by tools/backup.sh.
#
# Usage:
#   tools/restore.sh /var/backups/openlearn/openlearn-20261108T031500Z.tar.gz
#   OL_RESTORE_FORCE=1 tools/restore.sh ...   # skip the confirmation prompt
#
# This is destructive: the current database and media are replaced. The script
# keeps a copy of the previous state first, so a mistaken restore can itself be
# undone, but nothing else protects a running instance from an operator in a
# hurry.
#
# The files are installed through a throw-away container mounted on the same
# volume, because the application container is stopped at that moment and
# `docker compose exec` needs it running.

set -euo pipefail

ARCHIVE="${1:-}"
CONTAINER="${OPENLEARN_CONTAINER:-openlearn}"
SERVICE="${OL_SERVICE:-app}"
COMPOSE="${COMPOSE:-docker compose}"
SAFETY_DIR="${OL_SAFETY_DIR:-./backups/pre-restore}"

log() { printf '%s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

[ -n "${ARCHIVE}" ] || { log "usage: $0 <archive.tar.gz>"; exit 2; }
[ -f "${ARCHIVE}" ] || die "no such archive: ${ARCHIVE}"

WORK="$(mktemp -d)"
# shellcheck disable=SC2329  # invoked through the trap below
cleanup() { rm -rf "${WORK}"; }
trap cleanup EXIT

log "==> unpacking ${ARCHIVE}"
case "${ARCHIVE}" in
  *.enc)
    : "${OL_BACKUP_PASSPHRASE:?set OL_BACKUP_PASSPHRASE to open this archive}"
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "${ARCHIVE}" \
      -pass env:OL_BACKUP_PASSPHRASE | tar -C "${WORK}" -xzf -
    ;;
  *)
    tar -C "${WORK}" -xzf "${ARCHIVE}"
    ;;
esac

for needed in openlearn.db manifest.json; do
  [ -f "${WORK}/${needed}" ] || die "${needed} is missing from the archive"
done

# The archive must at least be a readable SQLite database with the expected tables.
if ! python3 - "${WORK}/openlearn.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
try:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
finally:
    connection.close()
missing = {"users", "quizzes", "wiki_pages"} - tables
if missing:
    print(f"missing tables: {sorted(missing)}", file=sys.stderr)
    raise SystemExit(1)
PY
then
  die "the database in the archive is not an OpenLearn database"
fi

cat "${WORK}/manifest.json" >&2

if [ "${OL_RESTORE_FORCE:-0}" != "1" ]; then
  printf 'Replace the contents of container %s with this archive? [y/N] ' "${CONTAINER}" >&2
  read -r answer
  case "${answer}" in
    y|Y|yes|YES) ;;
    *) log "aborted"; exit 1 ;;
  esac
fi

if [ "$(docker inspect -f '{{.State.Status}}' "${CONTAINER}" 2>/dev/null || echo missing)" = "missing" ]; then
  die "no container named ${CONTAINER}"
fi

IMAGE="$(docker inspect -f '{{.Config.Image}}' "${CONTAINER}")"
VOLUME="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/data"}}{{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "${CONTAINER}")"
[ -n "${VOLUME}" ] || die "container ${CONTAINER} has no mount at /app/data"

# Root inside the helper: /src comes from a 0700 mktemp directory, and /safety
# from the operator's home. Ownership is handed back to the application user
# right after the copy.
run_helper() {
  docker run --rm -i --user 0:0 \
    -v "${VOLUME}:/data" \
    -v "${WORK}:/src:ro" \
    -v "${SAFETY_DIR}:/safety" \
    --entrypoint sh "${IMAGE}" -c "$1"
}

mkdir -p "${SAFETY_DIR}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

log "==> stopping the application"
${COMPOSE} stop "${SERVICE}"

log "==> safety copy of the current state"
run_helper "set -e
  cp -a /data/openlearn.db /safety/openlearn-${stamp}.db 2>/dev/null || true
  mkdir -p /safety/media-${stamp}
  cp -a /data/media/. /safety/media-${stamp}/ 2>/dev/null || true
  echo saved" >&2 || log "warning: the safety copy is incomplete"
log "safety copy: ${SAFETY_DIR}"

log "==> installing the archive"
cat > "${WORK}/counts.py" <<'PY'
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

run_helper "set -e
  owner=\$(stat -c '%u:%g' /data)
  cp /src/openlearn.db /data/openlearn.db
  # The archive carries a checkpointed database. A write-ahead log left behind by
  # the previous contents is replayed on top of the restored file by SQLite and
  # silently brings the old rows back — this is not a theoretical risk, it is how
  # a restore once reported success while showing one quiz instead of a hundred.
  rm -f /data/openlearn.db-wal /data/openlearn.db-shm
  rm -rf /data/media
  if [ -d /src/media ]; then cp -a /src/media /data/media; fi
  if [ -f /src/.secret_key ]; then
    cp /src/.secret_key /data/.secret_key
    chmod 600 /data/.secret_key
  fi
  chown -R \"\$owner\" /data/openlearn.db /data/media /data/.secret_key 2>/dev/null || true
  echo installed" >&2

log "==> checking what was installed"
INSTALLED="$(run_helper "python /src/counts.py /data/openlearn.db")"
printf '%s\n' "${INSTALLED}" >&2
if ! INSTALLED="${INSTALLED}" python3 - "${WORK}/manifest.json" <<'PY'
import json
import os
import sys

manifest = json.load(open(sys.argv[1]))
saved = manifest.get("counts") or {}
installed = json.loads(os.environ["INSTALLED"])
differences = []
for table, expected in saved.items():
    actual = installed.get(table)
    if expected is None or actual is None:
        continue
    if expected != actual:
        differences.append(f"{table}: {expected} saved, {actual} installed")
if differences:
    print("mismatch: " + "; ".join(differences), file=sys.stderr)
    raise SystemExit(1)
print("contents match the archive")
PY
then
  log "error: the restored contents differ from the archive; the application was left stopped"
  exit 1
fi

log "==> starting"
${COMPOSE} start "${SERVICE}"

log "==> health"
for _ in $(seq 1 60); do
  if ${COMPOSE} exec -T "${SERVICE}" python -c '
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=3) as response:
    payload = json.load(response)
print(payload)
raise SystemExit(0 if payload.get("status") in ("ok", "healthy") else 1)
' 2>/dev/null; then
    log "restore complete"
    exit 0
  fi
  sleep 2
done

log "error: the instance did not become healthy; check '${COMPOSE} logs ${SERVICE}'"
exit 1
