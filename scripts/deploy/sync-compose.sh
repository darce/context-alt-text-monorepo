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

ENV="${ENV:?ENV must be set (dev|staging|prod)}"
OCI_HOST="${OCI_HOST:-129.213.40.111}"
OCI_USER="${OCI_USER:-ubuntu}"
SOURCE="${SOURCE:-apps/prototype-description-service/docker-compose.env.yml}"

case "$ENV" in
  dev|staging|prod) COMPOSE_DIR="/opt/acx-backend/$ENV" ;;
  *) echo "ERROR: ENV must be dev|staging|prod (got: $ENV)" >&2; exit 2 ;;
esac

if [[ "$ENV" == "prod" && "${CONFIRM:-}" != "PROD" ]]; then
  echo "ERROR: prod compose sync requires CONFIRM=PROD" >&2
  exit 2
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "ERROR: source file not found: $SOURCE" >&2
  exit 2
fi

REMOTE_PATH="$COMPOSE_DIR/docker-compose.env.yml"
SSH="ssh ${OCI_USER}@${OCI_HOST}"

echo "==> Target: ENV=$ENV  HOST=$OCI_HOST  REMOTE=$REMOTE_PATH"
echo "==> scp $SOURCE -> ${OCI_HOST}:${REMOTE_PATH}.new"
scp "$SOURCE" "${OCI_USER}@${OCI_HOST}:${REMOTE_PATH}.new"

echo "==> Diff (remote current vs new)"
$SSH "diff -u '$REMOTE_PATH' '${REMOTE_PATH}.new' || true"

echo "==> Promote .new -> live and apply via 'docker compose up -d'"
$SSH bash -se <<EOF
set -euo pipefail
cd "$COMPOSE_DIR"
mv docker-compose.env.yml docker-compose.env.yml.bak.\$(date +%s)
mv docker-compose.env.yml.new docker-compose.env.yml
docker compose -f docker-compose.env.yml up -d
docker compose -f docker-compose.env.yml ps
EOF

echo "==> Done."
