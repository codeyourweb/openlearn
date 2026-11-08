#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
# Start OpenLearn without Docker (self-hosted / development).
#
#   ./run.sh                 # serve on 0.0.0.0:8000
#   PORT=8080 ./run.sh      # custom port
#   ./run.sh --reload        # development mode with auto-reload
#
# Requirements: Python 3.11+ (3.12 recommended) and network access on first run.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
VENV_DIR="${VENV_DIR:-.venv}"
RELOAD=""

for arg in "$@"; do
  case "$arg" in
    --reload) RELOAD="--reload" ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating virtual environment in $VENV_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV_DIR"
  else
    python3 -m venv "$VENV_DIR"
  fi
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Installing dependencies"
if command -v uv >/dev/null 2>&1; then
  uv pip install -r backend/requirements.txt
else
  pip install -r backend/requirements.txt
fi

mkdir -p data/media
export OL_MEDIA_DIR="${OL_MEDIA_DIR:-$(pwd)/data/media}"
export OL_DATABASE_URL="${OL_DATABASE_URL:-sqlite:///$(pwd)/data/openlearn.db}"

if [ -z "${OL_SECRET_KEY:-}" ] && [ ! -f data/.secret_key ]; then
  echo "==> Generating a signing key in data/.secret_key"
fi

if [ -n "$RELOAD" ]; then
  echo "==> Serving OpenLearn on http://${HOST}:${PORT} (auto-reload)"
  exec uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT" --workers 1 $RELOAD
fi

echo "==> Serving OpenLearn (TLS: ${OL_TLS_CERT_FILE:-disabled})"
exec ./serve.sh
