#!/usr/bin/env bash
#
# localwp-db.sh — Connect to the LocalWP MySQL database
#
# Automatically discovers the LocalWP MySQL socket so callers don't need
# to hard-code the volatile run-directory hash.
#
# Usage:
#   ./scripts/localwp-db.sh                        # Interactive MySQL shell
#   ./scripts/localwp-db.sh -e "SHOW TABLES"       # Run a single statement
#   ./scripts/localwp-db.sh -e "SELECT * FROM wp_acx_clusters"
#   ./scripts/localwp-db.sh < dump.sql              # Pipe a file
#
# Environment overrides (optional):
#   LOCALWP_SOCKET   — full path to mysqld.sock (skips auto-discovery)
#   LOCALWP_DB_NAME  — database name          (default: local)
#   LOCALWP_DB_USER  — mysql user             (default: root)
#   LOCALWP_DB_PASS  — mysql password         (default: root)
#   LOCALWP_MYSQL_BIN — mysql client path     (default: auto-detect)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOCAL_RUN_DIR="${HOME}/Library/Application Support/Local/run"
DB_NAME="${LOCALWP_DB_NAME:-local}"
DB_USER="${LOCALWP_DB_USER:-root}"
DB_PASS="${LOCALWP_DB_PASS:-root}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCALWP_RUNTIME_HELPER="${SCRIPT_DIR}/localwp-runtime.sh"

resolve_mysql_bin() {
  if [[ -n "${LOCALWP_MYSQL_BIN:-}" ]]; then
    if [[ -x "${LOCALWP_MYSQL_BIN}" ]]; then
      echo "${LOCALWP_MYSQL_BIN}"
      return 0
    fi
    echo "Error: LOCALWP_MYSQL_BIN is set but '${LOCALWP_MYSQL_BIN}' is not executable." >&2
    return 1
  fi

  if command -v mysql >/dev/null 2>&1; then
    command -v mysql
    return 0
  fi

  local candidates=(
    "/opt/homebrew/bin/mysql"
    "/usr/local/bin/mysql"
  )
  local candidate=""
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done

  echo "Error: mysql client not found on PATH or common Homebrew locations." >&2
  echo "       Install mysql client tools or set LOCALWP_MYSQL_BIN explicitly." >&2
  return 1
}

if [[ ! -x "${LOCALWP_RUNTIME_HELPER}" ]]; then
  echo "Error: LocalWP runtime helper missing or not executable: ${LOCALWP_RUNTIME_HELPER}" >&2
  exit 1
fi

SOCKET="$("${LOCALWP_RUNTIME_HELPER}" socket)"
MYSQL_BIN="$(resolve_mysql_bin)"

# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------
exec "${MYSQL_BIN}" \
  -u "${DB_USER}" \
  -p"${DB_PASS}" \
  -S "${SOCKET}" \
  "${DB_NAME}" \
  "$@"
