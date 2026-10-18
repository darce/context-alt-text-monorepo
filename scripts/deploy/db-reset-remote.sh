#!/usr/bin/env bash
# Guarded schema-only reset for long-lived OCI dev/staging Postgres volumes.
#
# Greenfield policy edits 001_identity_schema.py in place. Long-lived remote
# DBs then fail at api boot with UndefinedColumn (Caddy 502). This drops and
# recreates the public schema so Alembic re-runs cleanly on api restart.
# Prod is intentionally refused — no override path exists (SEC-04).
#
# Usage:
#   make db-reset-remote ENV=dev CONFIRM=RESET
#   make db-reset-remote ENV=staging CONFIRM=RESET
#   make db-reset-remote ENV=dev CONFIRM=RESET DRY_RUN=1
#   scripts/deploy/db-reset-remote.sh --dry-run   # with ENV=… CONFIRM=RESET
#
# Env overrides: OCI_HOST (default tailnet MagicDNS), OCI_USER (default ubuntu).

set -euo pipefail

# Public port 22 is closed; host reachable via Tailscale SSH only.
OCI_HOST="${OCI_HOST:-acx-backend.tail1a44b8.ts.net}"
OCI_USER="${OCI_USER:-ubuntu}"

DRY_RUN="${DRY_RUN:-0}"
ENV="${ENV:-}"
CONFIRM="${CONFIRM:-}"

usage() {
  cat <<'EOF' >&2
Usage: ENV=dev|dev-fir|staging CONFIRM=RESET scripts/deploy/db-reset-remote.sh [--dry-run]
   or: make db-reset-remote ENV=dev|dev-fir|staging CONFIRM=RESET [DRY_RUN=1]

Hard refusals (exit 2): ENV=prod, unknown ENV, missing/incorrect CONFIRM=RESET.
EOF
}

refuse() {
  echo "ERROR: $*" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      refuse "unknown argument: $1"
      ;;
  esac
done

if [[ -z "$ENV" ]]; then
  refuse "ENV is required (dev|dev-fir|staging). Prod has no reset path."
fi

if [[ "$ENV" == "prod" ]]; then
  refuse "ENV=prod is refused — no prod schema-reset path exists (SEC-04)."
fi

case "$ENV" in
  dev)
    PG_CONTAINER="acx-dev-postgres-1"
    API_CONTAINER="acx-dev-api-1"
    PG_USER="acx_dev"
    PG_DB="alt_context_dev"
    HEALTH_URL="https://dev.api.altcontext.com/health"
    ;;
  dev-fir)
    PG_CONTAINER="acx-dev-fir-postgres-1"
    API_CONTAINER="acx-dev-fir-api-1"
    PG_USER="acx_dev_fir"
    PG_DB="alt_context_dev_fir"
    HEALTH_URL="https://fir.dev.api.altcontext.com/health"
    ;;
  staging)
    PG_CONTAINER="acx-staging-postgres-1"
    API_CONTAINER="acx-staging-api-1"
    PG_USER="acx_staging"
    PG_DB="alt_context_staging"
    HEALTH_URL="https://staging.api.altcontext.com/health"
    ;;
  *)
    refuse "ENV must be dev|dev-fir|staging (got: $ENV). Prod has no reset path."
    ;;
esac

if [[ "$CONFIRM" != "RESET" ]]; then
  refuse "CONFIRM=RESET is required. Re-run: make db-reset-remote ENV=$ENV CONFIRM=RESET"
fi

SSH_TARGET="${OCI_USER}@${OCI_HOST}"
PSQL_CMD="docker exec ${PG_CONTAINER} psql -U ${PG_USER} -d ${PG_DB} -c \"DROP SCHEMA public CASCADE; CREATE SCHEMA public;\""
RESTART_CMD="docker restart ${API_CONTAINER}"

echo "==> Target: ENV=$ENV  HOST=$SSH_TARGET"
echo "==> Postgres: $PG_CONTAINER  user=$PG_USER  db=$PG_DB"
echo "==> API: $API_CONTAINER"
echo "==> Health: $HEALTH_URL"
echo "==> Remote commands:"
echo "    $PSQL_CMD"
echo "    $RESTART_CMD"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "==> Dry-run only — no SSH, no remote mutation."
  exit 0
fi

echo "==> DROP SCHEMA public CASCADE + CREATE SCHEMA public"
# shellcheck disable=SC2029
ssh "$SSH_TARGET" "$PSQL_CMD"

echo "==> Restart $API_CONTAINER (Alembic re-runs on boot)"
# shellcheck disable=SC2029
ssh "$SSH_TARGET" "$RESTART_CMD"

echo "==> Poll $HEALTH_URL (12 × 5s)"
attempt=1
max_attempts=12
while (( attempt <= max_attempts )); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" || true)"
  if [[ "$code" == "200" ]]; then
    echo "==> Health OK (HTTP 200) on attempt $attempt"
    exit 0
  fi
  echo "    attempt $attempt/$max_attempts: HTTP ${code:-none}"
  if (( attempt == max_attempts )); then
    break
  fi
  sleep 5
  attempt=$((attempt + 1))
done

echo "ERROR: $HEALTH_URL did not return HTTP 200 within $((max_attempts * 5))s" >&2
exit 1
