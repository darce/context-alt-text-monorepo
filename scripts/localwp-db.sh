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
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOCAL_RUN_DIR="${HOME}/Library/Application Support/Local/run"
DB_NAME="${LOCALWP_DB_NAME:-local}"
DB_USER="${LOCALWP_DB_USER:-root}"
DB_PASS="${LOCALWP_DB_PASS:-root}"

# ---------------------------------------------------------------------------
# Socket discovery
# ---------------------------------------------------------------------------
discover_socket() {
  if [[ -n "${LOCALWP_SOCKET:-}" ]]; then
    if [[ -S "${LOCALWP_SOCKET}" ]]; then
      echo "${LOCALWP_SOCKET}"
      return 0
    fi
    echo "Error: LOCALWP_SOCKET is set but '${LOCALWP_SOCKET}' is not a valid socket." >&2
    return 1
  fi

  if [[ ! -d "${LOCAL_RUN_DIR}" ]]; then
    echo "Error: LocalWP run directory not found at '${LOCAL_RUN_DIR}'." >&2
    echo "       Is LocalWP installed?" >&2
    return 1
  fi

  local sockets=()
  while IFS= read -r -d '' sock; do
    sockets+=("${sock}")
  done < <(find "${LOCAL_RUN_DIR}" -name "mysqld.sock" -print0 2>/dev/null)

  if [[ ${#sockets[@]} -eq 0 ]]; then
    echo "Error: No mysqld.sock found under '${LOCAL_RUN_DIR}'." >&2
    echo "       Is a LocalWP site running?" >&2
    return 1
  fi

  if [[ ${#sockets[@]} -gt 1 ]]; then
    echo "Warning: Multiple LocalWP MySQL sockets found. Using the first one." >&2
    echo "         Set LOCALWP_SOCKET to choose a specific one:" >&2
    for s in "${sockets[@]}"; do
      echo "           ${s}" >&2
    done
  fi

  echo "${sockets[0]}"
}

SOCKET="$(discover_socket)"

# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------
exec mysql \
  -u "${DB_USER}" \
  -p"${DB_PASS}" \
  -S "${SOCKET}" \
  "${DB_NAME}" \
  "$@"
