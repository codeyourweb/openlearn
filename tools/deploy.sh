#!/usr/bin/env bash
# Deploy this checkout to a server and rebuild the running image there.
#
# One direction only: this working copy is the source of truth, the remote
# directory is a disposable copy. Never edit files on the server, the next
# deployment overwrites them.
#
#   OL_SSH="ssh deploy@example.com" tools/deploy.sh
#   OL_SSH="ssh deploy@example.com" tools/deploy.sh --no-build
#
# Environment:
#   OL_SSH         how to reach the server (required) — any ssh command
#   OL_REMOTE_DIR  where the copy lives       (default: /srv/openlearn)
#   OL_COMPOSE     compose file that runs it  (default: $OL_REMOTE_DIR/docker-compose.yml)
#   OL_IMAGE       image tag to build         (default: openlearn:latest)
#   OL_CONTAINER   container to wait for      (default: openlearn)
#   OL_HEALTH_URL  checked from the server when the container has no healthcheck
set -euo pipefail

SSH=${OL_SSH:?set OL_SSH, e.g. OL_SSH="ssh deploy@example.com"}
REMOTE_DIR=${OL_REMOTE_DIR:-/srv/openlearn}
COMPOSE=${OL_COMPOSE:-$REMOTE_DIR/docker-compose.yml}
IMAGE=${OL_IMAGE:-openlearn:latest}
CONTAINER=${OL_CONTAINER:-openlearn}
HEALTH_URL=${OL_HEALTH_URL:-}
SKIP_BUILD=0
[[ ${1:-} == --no-build ]] && SKIP_BUILD=1

cd "$(dirname "$0")/.."
ROOT=$(pwd)
echo "source : $ROOT"

# 0. State of the checkout, so a deployment can always be traced to a commit.
if git rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n $(git status --porcelain) ]]; then
    echo "attention : modifications non validées, elles seront déployées telles quelles"
  fi
  echo "commit : $(git log -1 --format='%h %s')"
fi

# 1. Rotate the previous copy out of the way, keeping only one.
STAMP=$(date +%Y%m%d-%H%M%S)
$SSH "set -e
  mkdir -p $(dirname "$REMOTE_DIR")
  if [ -d $REMOTE_DIR ]; then mv $REMOTE_DIR ${REMOTE_DIR}.bak.$STAMP; fi
  mkdir -p $REMOTE_DIR
  ls -d ${REMOTE_DIR}.bak.* 2>/dev/null | head -n -1 | xargs -r rm -rf"

# 2. Stream the tree: no history, no virtualenv, no caches, no local data.
tar czf - \
  --exclude=./.git --exclude=./.venv --exclude=./data --exclude=./tmp \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='node_modules' \
  --exclude='*.db' --exclude='*.pyc' --exclude='*.log' \
  -C "$ROOT" . | $SSH "tar xzf - -C $REMOTE_DIR"
$SSH "printf 'installé : %s fichiers\n' \"\$(find $REMOTE_DIR -type f | wc -l)\""

# 3. Both trees must carry the same files, otherwise the copy silently differs.
LOCAL_COUNT=$(cd "$ROOT" && find . -type f \
  -not -path './.git/*' -not -path './.venv/*' -not -path '*/__pycache__/*' \
  -not -path './data/*' -not -path './tmp/*' -not -path '*/.pytest_cache/*' \
  -not -name '*.db' -not -name '*.pyc' -not -name '*.log' | wc -l)
REMOTE_COUNT=$($SSH "find $REMOTE_DIR -type f | wc -l")
echo "fichiers : source $LOCAL_COUNT, serveur $REMOTE_COUNT"
if [[ "$LOCAL_COUNT" != "$REMOTE_COUNT" ]]; then
  echo "les deux arbres diffèrent : arrêt avant de construire" >&2
  exit 1
fi

# 4. Rebuild and restart.
if [[ $SKIP_BUILD -eq 1 ]]; then
  echo "synchro seule, image non reconstruite"
  exit 0
fi

$SSH "set -e
  docker build -q -t $IMAGE $REMOTE_DIR >/dev/null
  docker compose -f $COMPOSE up -d --force-recreate >/dev/null
  printf 'image : %s\n' \"\$(docker image inspect -f '{{.Id}}' $IMAGE | cut -c8-19)\""

# 5. Wait for the container to report healthy, or for the URL to answer 200.
for _ in $(seq 1 30); do
  state=$($SSH "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $CONTAINER 2>/dev/null || echo missing")
  [[ "$state" == "healthy" ]] && { echo "santé : healthy"; exit 0; }
  if [[ "$state" == "none" && -n "$HEALTH_URL" ]]; then
    code=$($SSH "curl -fsS -o /dev/null -w '%{http_code}' --max-time 4 '$HEALTH_URL' || true")
    [[ "$code" == "200" ]] && { echo "santé : 200"; exit 0; }
  fi
  sleep 2
done

$SSH "docker logs --tail 40 $CONTAINER" >&2 || true
echo "le conteneur ne devient pas sain après 60 s" >&2
exit 1
