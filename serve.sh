#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
# Single entry point for every deployment shape: bare server, container, or
# behind a reverse proxy with or without TLS terminated elsewhere.
#
#   ./serve.sh                            # http://0.0.0.0:8000
#   PORT=8080 ./serve.sh                 # another port
#   OL_TLS_CERT_FILE=... OL_TLS_KEY_FILE=... ./serve.sh   # https on 8443
#
# When TLS is configured the server terminates it itself: no proxy needed.
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"
CERT="${OL_TLS_CERT_FILE:-}"
KEY="${OL_TLS_KEY_FILE:-}"

args=()
port_was_set="${PORT:+yes}"

if [ -n "$CERT" ] || [ -n "$KEY" ]; then
  if [ -z "$CERT" ] || [ -z "$KEY" ]; then
    echo "serve.sh: OL_TLS_CERT_FILE and OL_TLS_KEY_FILE must be set together." >&2
    exit 2
  fi
  for file in "$CERT" "$KEY"; do
    if [ ! -r "$file" ]; then
      echo "serve.sh: cannot read $file (it must be readable by the user" \
           "running the server: a 0600 key owned by root is invisible to a" \
           "container running as an unprivileged user)" >&2
      exit 2
    fi
  done
  args+=(--ssl-certfile "$CERT" --ssl-keyfile "$KEY")
fi

if [ -n "${port_was_set}" ]; then
  PORT="${PORT}"
elif [ ${#args[@]} -gt 0 ]; then
  PORT="${OL_TLS_PORT:-8443}"
else
  PORT=8000
fi

exec uvicorn app.main:app \
  --app-dir "$APP_DIR/backend" \
  --host "$HOST" \
  --port "$PORT" \
  --workers "$WORKERS" \
  --proxy-headers \
  "${args[@]}"
