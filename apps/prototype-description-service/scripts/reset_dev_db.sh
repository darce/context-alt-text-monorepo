#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[reset-dev-db] Missing ${ENV_FILE}. Copy .env.example first." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

ENVIRONMENT_VALUE="${ENVIRONMENT:-development}"
if [[ "${ENVIRONMENT_VALUE}" != "development" ]]; then
  echo "[reset-dev-db] Refusing to run because ENVIRONMENT=${ENVIRONMENT_VALUE}." >&2
  exit 1
fi

if [[ "${ALLOW_DEV_DB_RESET:-0}" != "1" ]]; then
  echo "[reset-dev-db] Set ALLOW_DEV_DB_RESET=1 in your environment to confirm this destructive action." >&2
  exit 1
fi

cd "${PROJECT_ROOT}"

echo "[reset-dev-db] Dropping all objects via Alembic downgrade..." >&2
alembic -c db/alembic.ini downgrade base

echo "[reset-dev-db] Recreating schema via Alembic upgrade..." >&2
alembic -c db/alembic.ini upgrade head

echo "[reset-dev-db] Done – database reset for development environment." >&2
