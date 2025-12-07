#!/usr/bin/env bash
#
# db_shell.sh - Connect to the development database (native PostgreSQL)
#
# Usage:
#   ./scripts/db_shell.sh              # Connect as app user (RLS-enabled)
#   ./scripts/db_shell.sh --admin      # Connect as admin (bypasses RLS)
#   ./scripts/db_shell.sh -c "SELECT * FROM tenants"  # Run a query
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

# Check for --admin flag
USE_ADMIN=false
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--admin" ]]; then
    USE_ADMIN=true
  else
    ARGS+=("$arg")
  fi
done

# Select credentials based on mode
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5432}"
DB_NAME="${DB_NAME:-context_alt_text_service}"

if [[ "$USE_ADMIN" == true ]]; then
  DB_USER="${ADMIN_PGUSER:-context_admin}"
  DB_PASS="${ADMIN_PGPASSWORD:-context_admin_password}"
  echo "Connecting to ${DB_NAME} at ${DB_HOST}:${DB_PORT} as ${DB_USER} (ADMIN - bypasses RLS)..."
else
  DB_USER="${APP_PGUSER:-recognition_test_user}"
  DB_PASS="${APP_PGPASSWORD:-recognition_test_password}"
  echo "Connecting to ${DB_NAME} at ${DB_HOST}:${DB_PORT} as ${DB_USER} (APP - RLS enabled)..."
  echo "  Tip: SET app.current_tenant = '<uuid>' to see tenant data, or use --admin to bypass RLS"
fi

if [[ -n "${DB_PASS}" ]]; then
  PGPASSWORD="${DB_PASS}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" "${ARGS[@]}"
else
  psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" "${ARGS[@]}"
fi
