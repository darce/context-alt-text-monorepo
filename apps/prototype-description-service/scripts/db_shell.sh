#!/usr/bin/env bash
#
# db_shell.sh - Connect to the development database (native PostgreSQL)
#
set -e

# Load environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

# Defaults for native PostgreSQL
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5432}"
DB_USER="${PGUSER:-context_user}"
DB_PASS="${PGPASSWORD:-}"
DB_NAME="${DB_NAME:-context_alt_text_service}"

echo "Connecting to ${DB_NAME} at ${DB_HOST}:${DB_PORT} as ${DB_USER}..."
if [[ -n "${DB_PASS}" ]]; then
  PGPASSWORD="${DB_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" "$@"
else
  psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" "$@"
fi
