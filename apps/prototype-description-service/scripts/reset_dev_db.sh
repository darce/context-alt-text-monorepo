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

# Resolve DB connection info directly from environment
DB_HOST="${PGHOST:-}"
DB_PORT="${PGPORT:-}"
DB_USER="${PGUSER:-}"
DB_PASS="${PGPASSWORD:-}"
DB_NAME="${DB_NAME:-}"

if [[ -z "${DB_HOST}" || -z "${DB_PORT}" || -z "${DB_USER}" || -z "${DB_PASS}" || -z "${DB_NAME}" ]]; then
  echo "[reset-dev-db] PGHOST, PGPORT, PGUSER, PGPASSWORD, and DB_NAME must be set in .env for this script." >&2
  exit 1
fi

ADMIN_USER="${ADMIN_PGUSER:-${DB_USER}}"
ADMIN_PASS="${ADMIN_PGPASSWORD:-${DB_PASS}}"

run_admin_psql() {
  local database=$1
  shift
  local cmd=(env -u PGHOST)
  [[ "${DB_HOST}" == /* ]] && cmd+=("PGPORT=${DB_PORT}")
  if [[ -n "${ADMIN_PASS}" ]]; then
    cmd+=("PGPASSWORD=${ADMIN_PASS}")
  fi
  if [[ "${DB_HOST}" == /* ]]; then
    cmd+=("psql" "-U" "${ADMIN_USER}" "-d" "${database}")
  else
    cmd+=("psql" "-h" "${DB_HOST}" "-p" "${DB_PORT}" "-U" "${ADMIN_USER}" "-d" "${database}")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

run_user_psql() {
  local database=$1
  shift
  local cmd=(env -u PGHOST "PGPASSWORD=${DB_PASS}")
  [[ "${DB_HOST}" == /* ]] && cmd+=("PGPORT=${DB_PORT}")
  if [[ "${DB_HOST}" == /* ]]; then
    cmd+=("psql" "-U" "${DB_USER}" "-d" "${database}")
  else
    cmd+=("psql" "-h" "${DB_HOST}" "-p" "${DB_PORT}" "-U" "${DB_USER}" "-d" "${database}")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

cd "${PROJECT_ROOT}"

echo "[reset-dev-db] Dropping database \"${DB_NAME}\" using admin user ${ADMIN_USER}..." >&2
run_admin_psql postgres -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";" >/dev/null

echo "[reset-dev-db] Creating database \"${DB_NAME}\"..." >&2
run_admin_psql postgres -c "CREATE DATABASE \"${DB_NAME}\";" >/dev/null

echo "[reset-dev-db] Setting database owner to ${DB_USER}..." >&2
run_admin_psql postgres -c "ALTER DATABASE \"${DB_NAME}\" OWNER TO \"${DB_USER}\";" >/dev/null

echo "[reset-dev-db] Ensuring pgvector extension and schema privileges..." >&2
run_admin_psql "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
run_admin_psql "${DB_NAME}" -c "ALTER SCHEMA public OWNER TO \"${DB_USER}\";" >/dev/null
run_admin_psql "${DB_NAME}" -c "GRANT ALL ON SCHEMA public TO \"${DB_USER}\";" >/dev/null

echo "[reset-dev-db] Applying migrations as ${DB_USER}..." >&2
if [[ "${DB_HOST}" == /* ]]; then
  PGHOST= PGPORT="${DB_PORT}" PGPASSWORD="${DB_PASS}" alembic -c db/alembic.ini upgrade head
else
  PGHOST="${DB_HOST}" PGPORT="${DB_PORT}" PGPASSWORD="${DB_PASS}" alembic -c db/alembic.ini upgrade head
fi

echo "[reset-dev-db] Done – database dropped, recreated, and migrated for development environment." >&2
