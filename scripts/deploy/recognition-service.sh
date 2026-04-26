#!/usr/bin/env bash
# Deploy or promote the recognition service Docker image to an OCI environment.
#
# Modes:
#   build    Build :$SHA + :$ENV_TAG from current HEAD on the OCI host, push, restart service.
#   promote  Retag an existing :$SOURCE_TAG to :$ENV_TAG on the registry, restart service.
#
# Usage:
#   ENV=dev MODE=build  scripts/deploy/recognition-service.sh
#   ENV=staging MODE=promote SOURCE_TAG=dev scripts/deploy/recognition-service.sh
#   ENV=prod MODE=promote SOURCE_TAG=staging CONFIRM=PROD scripts/deploy/recognition-service.sh

set -euo pipefail

ENV="${ENV:?ENV must be set (dev|staging|prod)}"
MODE="${MODE:?MODE must be set (build|promote)}"
OCI_HOST="${OCI_HOST:-129.213.40.111}"
OCI_USER="${OCI_USER:-ubuntu}"
OCIR_REGISTRY="${OCIR_REGISTRY:-iad.ocir.io}"
OCIR_NAMESPACE="${OCIR_NAMESPACE:-idu2kqqe2jxy}"
IMAGE_NAME="${IMAGE_NAME:-acx-backend}"
GIT_REF="${GIT_REF:-HEAD}"

case "$ENV" in
  dev)     ENV_TAG=dev;     SERVICE=acx-dev;     COMPOSE_DIR=/opt/acx-backend/dev;     HEALTH_URL=https://dev.api.altcontext.com/health ;;
  staging) ENV_TAG=staging; SERVICE=acx-staging; COMPOSE_DIR=/opt/acx-backend/staging; HEALTH_URL=https://staging.api.altcontext.com/health ;;
  prod)    ENV_TAG=latest;  SERVICE=acx-prod;    COMPOSE_DIR=/opt/acx-backend/prod;    HEALTH_URL=https://api.altcontext.com/health ;;
  *) echo "ERROR: ENV must be dev|staging|prod (got: $ENV)" >&2; exit 2 ;;
esac

if [[ "$ENV" == "prod" && "${CONFIRM:-}" != "PROD" ]]; then
  echo "ERROR: prod deploys require CONFIRM=PROD" >&2
  exit 2
fi

IMAGE="${OCIR_REGISTRY}/${OCIR_NAMESPACE}/${IMAGE_NAME}"
SSH="ssh ${OCI_USER}@${OCI_HOST}"

echo "==> Target: ENV=$ENV  TAG=$ENV_TAG  SERVICE=$SERVICE  HOST=$OCI_HOST"

restart_and_verify() {
  local expected_sha="${1:-}"
  echo "==> Pull + restart $SERVICE on $OCI_HOST"
  $SSH "cd '$COMPOSE_DIR' && docker compose -f docker-compose.env.yml pull api && sudo systemctl restart '$SERVICE'"
  echo "==> Wait for health"
  sleep 5
  local resp
  for i in 1 2 3 4 5 6; do
    if resp=$(curl -fsS --max-time 10 "$HEALTH_URL" 2>/dev/null); then
      echo "$resp"
      if [[ -n "$expected_sha" ]]; then
        if echo "$resp" | grep -q "$expected_sha"; then
          echo "==> Health OK (sha matches: $expected_sha)"
          return 0
        else
          echo "WARN: health responded but expected sha $expected_sha not found, retrying..."
        fi
      else
        echo "==> Health OK"
        return 0
      fi
    fi
    sleep 5
  done
  echo "ERROR: health check did not confirm deploy" >&2
  return 1
}

if [[ "$MODE" == "build" ]]; then
  SHA=$(git rev-parse "$GIT_REF")
  echo "==> Build mode: SHA=$SHA"
  ARCHIVE="/tmp/acx-svc-${SHA}.tar.gz"
  REMOTE_BUILD="/tmp/acx-build-${SHA}"

  echo "==> git archive"
  git archive --format=tar.gz --prefix=svc/ "$SHA" apps/prototype-description-service/ -o "$ARCHIVE"

  echo "==> scp archive to $OCI_HOST"
  scp "$ARCHIVE" "${OCI_USER}@${OCI_HOST}:/tmp/"

  echo "==> Remote build + push"
  $SSH bash -se <<EOF
set -euo pipefail
rm -rf "$REMOTE_BUILD"
mkdir -p "$REMOTE_BUILD"
cd "$REMOTE_BUILD"
tar xzf "$ARCHIVE"
cd svc/apps/prototype-description-service
docker build --platform linux/arm64 \
  --build-arg GIT_COMMIT_SHA=$SHA \
  -t ${IMAGE}:${ENV_TAG} \
  -t ${IMAGE}:${SHA} .
docker push ${IMAGE}:${ENV_TAG}
docker push ${IMAGE}:${SHA}
rm -rf "$REMOTE_BUILD" "$ARCHIVE"
EOF

  rm -f "$ARCHIVE"
  restart_and_verify "$SHA"

elif [[ "$MODE" == "promote" ]]; then
  SOURCE_TAG="${SOURCE_TAG:?SOURCE_TAG must be set for MODE=promote}"
  echo "==> Promote mode: ${IMAGE}:${SOURCE_TAG} -> ${IMAGE}:${ENV_TAG}"
  $SSH bash -se <<EOF
set -euo pipefail
docker pull ${IMAGE}:${SOURCE_TAG}
docker tag ${IMAGE}:${SOURCE_TAG} ${IMAGE}:${ENV_TAG}
docker push ${IMAGE}:${ENV_TAG}
EOF
  restart_and_verify ""

else
  echo "ERROR: MODE must be build|promote (got: $MODE)" >&2
  exit 2
fi

echo "==> Done."
