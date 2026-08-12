#!/usr/bin/env bash
# Sync apps/prototype-description-service/docker-compose.env.yml to the OCI host
# for an environment and apply with `docker compose up -d` so structural changes
# (volumes, env vars, services, networks) take effect. The image-only deploy
# (`scripts/deploy/recognition-service.sh`) does NOT update the compose file on
# the VM, so use this whenever docker-compose.env.yml itself changes.
#
# Usage:
#   ENV=dev     scripts/deploy/sync-compose.sh
#   ENV=staging scripts/deploy/sync-compose.sh
#   ENV=prod    CONFIRM=PROD scripts/deploy/sync-compose.sh

set -euo pipefail

ENV="${ENV:?ENV must be set (dev|dev-fir|staging|prod)}"
OCI_HOST="${OCI_HOST:-129.213.40.111}"
OCI_USER="${OCI_USER:-ubuntu}"
SOURCE="${SOURCE:-apps/prototype-description-service/docker-compose.env.yml}"
ADMIN_SOURCE="${ADMIN_SOURCE:-apps/prototype-description-service/docker-compose.admin.yml}"

case "$ENV" in
  dev|dev-fir|staging|prod) COMPOSE_DIR="/opt/acx-backend/$ENV" ;;
  *) echo "ERROR: ENV must be dev|dev-fir|staging|prod (got: $ENV)" >&2; exit 2 ;;
esac

if [[ "$ENV" == "prod" && "${CONFIRM:-}" != "PROD" ]]; then
  echo "ERROR: prod compose sync requires CONFIRM=PROD" >&2
  exit 2
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "ERROR: source file not found: $SOURCE" >&2
  exit 2
fi
if [[ "$ENV" == "prod" && ! -f "$ADMIN_SOURCE" ]]; then
  echo "ERROR: admin overlay source file not found: $ADMIN_SOURCE" >&2
  exit 2
fi

REMOTE_PATH="$COMPOSE_DIR/docker-compose.env.yml"
SSH="ssh ${OCI_USER}@${OCI_HOST}"

echo "==> Target: ENV=$ENV  HOST=$OCI_HOST  REMOTE=$REMOTE_PATH"
echo "==> scp $SOURCE -> ${OCI_HOST}:${REMOTE_PATH}.new"
scp "$SOURCE" "${OCI_USER}@${OCI_HOST}:${REMOTE_PATH}.new"
if [[ "$ENV" == "prod" ]]; then
  scp "$ADMIN_SOURCE" "${OCI_USER}@${OCI_HOST}:${COMPOSE_DIR}/docker-compose.admin.yml.new"
fi

echo "==> Diff (remote current vs new)"
$SSH "diff -u '$REMOTE_PATH' '${REMOTE_PATH}.new' || true"
if [[ "$ENV" == "prod" ]]; then
  $SSH "diff -u '$COMPOSE_DIR/docker-compose.admin.yml' '$COMPOSE_DIR/docker-compose.admin.yml.new' || true"
fi

echo "==> Promote .new -> live and apply via 'docker compose up -d'"
$SSH bash -se "$COMPOSE_DIR" "$ENV" <<'EOF'
set -euo pipefail
COMPOSE_DIR="$1"
ENV="$2"
cd "$COMPOSE_DIR"
mv docker-compose.env.yml docker-compose.env.yml.bak.$(date +%s)
mv docker-compose.env.yml.new docker-compose.env.yml
COMPOSE_ARGS="-f docker-compose.env.yml"
if [[ "$ENV" == "prod" ]]; then
  if [[ -f docker-compose.admin.yml ]]; then
    mv docker-compose.admin.yml docker-compose.admin.yml.bak.$(date +%s)
  fi
  mv docker-compose.admin.yml.new docker-compose.admin.yml
  COMPOSE_ARGS="-f docker-compose.env.yml -f docker-compose.admin.yml"
fi
docker compose $COMPOSE_ARGS up -d
docker compose $COMPOSE_ARGS ps
EOF

echo "==> Done."
