#!/usr/bin/env bash
# Deploy this checkout to a server and rebuild the running image there.
#
# One direction only: this working copy is the source of truth, the remote
# directory is a disposable copy. Never edit files on the server, the next
# deployment overwrites them.
#
#   OL_SSH="ssh deploy@example.com" tools/deploy.sh
#   OL_SSH="ssh deploy@example.com" tools/deploy.sh --no-build
#   OL_SSH="ssh deploy@example.com" tools/deploy.sh --rollback
#
# Environment:
#   OL_SSH         how to reach the server (required) — any ssh command
#   OL_REMOTE_DIR  where the copy lives       (default: /srv/openlearn)
#   OL_COMPOSE     compose file that runs it  (default: $OL_REMOTE_DIR/docker-compose.yml)
#   OL_ENV_FILE    compose --env-file, when the stack needs one
#   OL_IMAGE       image tag to build         (default: openlearn:latest)
#   OL_CONTAINER   container to wait for      (default: openlearn)
#   OL_HEALTH_URL  checked from the server when the container has no healthcheck
#   OL_PRE_DEPLOY  command run on the server before the swap (backup, baseline)
#
# The image serving right now is kept as $OL_IMAGE-previous, so --rollback needs
# nothing but this script and a few seconds of restart.
set -euo pipefail

SSH=${OL_SSH:?set OL_SSH, e.g. OL_SSH="ssh deploy@example.com"}
REMOTE_DIR=${OL_REMOTE_DIR:-/srv/openlearn}
COMPOSE=${OL_COMPOSE:-$REMOTE_DIR/docker-compose.yml}
ENV_FILE=${OL_ENV_FILE:-}
IMAGE=${OL_IMAGE:-openlearn:latest}
CONTAINER=${OL_CONTAINER:-openlearn}
HEALTH_URL=${OL_HEALTH_URL:-}
PRE_DEPLOY=${OL_PRE_DEPLOY:-}
COMPOSE_ARGS="-f $COMPOSE"
[[ -n $ENV_FILE ]] && COMPOSE_ARGS="$COMPOSE_ARGS --env-file $ENV_FILE"
SKIP_BUILD=0
ROLLBACK=0
case ${1:-} in
  --no-build) SKIP_BUILD=1 ;;
  --rollback) ROLLBACK=1 ;;
esac

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

# 0b. Refuse to build a stack the running container does not belong to.
#     Compose names its project after the file's directory, so a compose file
#     sitting elsewhere creates a second container and collides on the name.
if docker inspect "$CONTAINER" >/dev/null 2>&1 || $SSH "docker inspect $CONTAINER >/dev/null 2>&1"; then
  owner=$($SSH "docker inspect -f '{{index .Config.Labels \"com.docker.compose.project.config_files\"}}' $CONTAINER 2>/dev/null" || true)
  if [[ -n $owner && $owner != "$COMPOSE" ]]; then
    echo "arrêt : $CONTAINER appartient à $owner, pas à $COMPOSE" >&2
    echo "relancer avec OL_COMPOSE=$owner" >&2
    exit 1
  fi
fi

if [[ $ROLLBACK -eq 0 ]]; then

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

fi  # fin de la synchronisation

# 4. Build and swap.
if [[ $SKIP_BUILD -eq 1 && $ROLLBACK -eq 0 ]]; then
  echo "synchro seule, image non reconstruite"
  exit 0
fi

BLIND_START=$SECONDS
if [[ $ROLLBACK -eq 1 ]]; then
  echo "retour arrière vers $IMAGE-previous"
  $SSH "set -e
    docker image inspect $IMAGE-previous >/dev/null
    docker tag $IMAGE-previous $IMAGE
    docker compose $COMPOSE_ARGS up -d --force-recreate --no-build >/dev/null"
else
  # 4a. Keep what is serving now: a bad build is then one retag away.
  $SSH "docker image inspect $IMAGE >/dev/null 2>&1 && docker tag $IMAGE $IMAGE-previous || true"
  # 4b. Host hook, before anything is rebuilt: snapshot, baseline counts.
  [[ -n $PRE_DEPLOY ]] && $SSH "set -e; $PRE_DEPLOY"
  # 4c. Build while the old container keeps serving, then swap.
  $SSH "docker build -q -t $IMAGE $REMOTE_DIR >/dev/null"
  $SSH "docker compose $COMPOSE_ARGS up -d --force-recreate --no-build >/dev/null"
fi
$SSH "printf 'image : %s\n' \"\$(docker image inspect -f '{{.Id}}' $IMAGE | cut -c8-19)\""

# 5. Wait for the container to report healthy, or for the URL to answer 200.
for _ in $(seq 1 30); do
  state=$($SSH "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $CONTAINER 2>/dev/null || echo missing")
  if [[ "$state" == "healthy" ]]; then
    echo "santé : healthy, interruption : $((SECONDS - BLIND_START)) s"
    exit 0
  fi
  if [[ "$state" == "none" && -n "$HEALTH_URL" ]]; then
    code=$($SSH "curl -fsS -o /dev/null -w '%{http_code}' --max-time 4 '$HEALTH_URL' || true")
    if [[ "$code" == "200" ]]; then
      echo "santé : 200, interruption : $((SECONDS - BLIND_START)) s"
      exit 0
    fi
  fi
  sleep 2
done

$SSH "docker logs --tail 40 $CONTAINER" >&2 || true
echo "le conteneur ne devient pas sain après 60 s" >&2
echo "l'image précédente est conservée : relancer avec --rollback" >&2
exit 1
