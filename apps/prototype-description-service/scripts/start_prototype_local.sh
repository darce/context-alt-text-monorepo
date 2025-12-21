#!/usr/bin/env bash
#
# start_prototype_local.sh - Start the prototype description service (native PostgreSQL)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
DEFAULT_HOST="0.0.0.0"
DEFAULT_PORT="8000"
ENV_FILE="${PROJECT_ROOT}/.env"

has_network_access() {
  if [[ "${ASSUME_OFFLINE:-0}" == "1" ]]; then
    return 1
  fi

  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import socket

try:
    socket.create_connection(("pypi.org", 443), timeout=2)
except OSError:
    raise SystemExit(1)
PY
}

maybe_install_deps() {
  if [[ "${SKIP_INSTALL:-0}" == "1" ]]; then
    echo "[prototype-local] SKIP_INSTALL=1: skipping dependency installation." >&2
    return 0
  fi

  if [[ "${FORCE_INSTALL:-0}" == "1" ]]; then
    install_deps
    return 0
  fi

  if has_network_access; then
    install_deps
  else
    echo "[prototype-local] No network detected; skipping dependency installation. Set FORCE_INSTALL=1 to override." >&2
  fi
}

print_usage() {
  cat <<'USAGE'
Usage: start_prototype_local.sh [command]

Commands:
  start        Install dependencies (unless SKIP_INSTALL=1) and launch uvicorn
  install      Install/upgrade local dependencies only
  stop         Stop uvicorn processes started for this app (best effort)
  help         Show this help text

Environment variables:
  PYTHON_BIN           Python executable to use (default: python)
  SKIP_INSTALL         Set to 1 to skip dependency installation during start
  SKIP_DB_CHECK        Set to 1 to skip PostgreSQL readiness check
  HOST                 Uvicorn host binding (default: 0.0.0.0)
  PORT                 Uvicorn port (default: 8000)
  FORCE_INSTALL        Set to 1 to force reinstalling deps even when offline
  START_SCAN_WORKER    Set to 1 to start the scan worker alongside the API
  SCAN_WORKER_LOG      Path for scan worker output (default: logs/scan_worker.log)
  UVICORN_EXTRA_ARGS   Extra args passed to uvicorn (example: "--timeout-graceful-shutdown 1")

Requires:
  - Native PostgreSQL (brew install postgresql@17)
  - pgvector extension (brew install pgvector)
USAGE
}

install_deps() {
  echo "[prototype-local] Installing editable package and dev extras..." >&2
  "${PYTHON_BIN}" -m pip install --upgrade pip
  "${PYTHON_BIN}" -m pip install -e "${PROJECT_ROOT}[dev]"
}

load_env() {
  if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck source=/dev/null
    set -a
    source "${ENV_FILE}"
    set +a
  fi
}

ensure_postgres() {
  if [[ "${SKIP_DB_CHECK:-0}" == "1" ]]; then
    echo "[prototype-local] SKIP_DB_CHECK=1: skipping PostgreSQL check." >&2
    return
  fi

  local db_host="${PGHOST:-localhost}"
  local db_port="${PGPORT:-5432}"

  echo "[prototype-local] Checking PostgreSQL is running at ${db_host}:${db_port}..." >&2
  if ! pg_isready -h "${db_host}" -p "${db_port}" >/dev/null 2>&1; then
    echo "[prototype-local] PostgreSQL is not running. Start it with: brew services start postgresql@17" >&2
    echo "[prototype-local] Or set SKIP_DB_CHECK=1 to bypass this check." >&2
    exit 1
  fi
  echo "[prototype-local] PostgreSQL is ready." >&2
}

check_database_exists() {
  local db_name="${DB_NAME:-}"
  if [[ -z "${db_name}" ]]; then
    return 0
  fi

  local db_host="${PGHOST:-localhost}"
  local db_port="${PGPORT:-5432}"
  local admin_user="${ADMIN_PGUSER:-${PGUSER:-}}"
  local admin_pass="${ADMIN_PGPASSWORD:-${PGPASSWORD:-}}"

  local exists
  if [[ -n "${admin_pass}" ]]; then
    exists="$(PGPASSWORD="${admin_pass}" psql -h "${db_host}" -p "${db_port}" -U "${admin_user}" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname = '${db_name}'" 2>/dev/null || true)"
  else
    exists="$(psql -h "${db_host}" -p "${db_port}" -U "${admin_user}" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname = '${db_name}'" 2>/dev/null || true)"
  fi

  if [[ "${exists}" != "1" ]]; then
    echo "[prototype-local] Database ${db_name} not found." >&2
    if [[ "${ALLOW_DEV_DB_RESET:-0}" == "1" ]]; then
      echo "[prototype-local] Bootstrapping database via reset_dev_db.sh..." >&2
      "${PROJECT_ROOT}/scripts/reset_dev_db.sh"
    else
      echo "[prototype-local] Set ALLOW_DEV_DB_RESET=1 and run ./scripts/reset_dev_db.sh to bootstrap." >&2
      exit 1
    fi
  fi
}

find_scan_worker_pids() {
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -f "recognition/worker/scan_worker.py" || true
    return
  fi
  ps -ax | awk '/recognition\/worker\/scan_worker\.py/ && !/awk/ {print $1}'
}

start_scan_worker() {
  if [[ "${START_SCAN_WORKER:-0}" != "1" ]]; then
    return
  fi

  local existing_pids
  existing_pids="$(find_scan_worker_pids)"
  if [[ -n "${existing_pids}" ]]; then
    echo "[prototype-local] Scan worker already running (PID(s): ${existing_pids})." >&2
    return
  fi

  local log_path="${SCAN_WORKER_LOG:-${PROJECT_ROOT}/logs/scan_worker.log}"
  mkdir -p "$(dirname "${log_path}")"
  echo "[prototype-local] Starting scan worker (log: ${log_path})..." >&2
  nohup "${PYTHON_BIN}" "${PROJECT_ROOT}/recognition/worker/scan_worker.py" >"${log_path}" 2>&1 &
}

start_service() {
  load_env
  export CACHE_BASE="${CACHE_BASE:-/Volumes/Butter/cache}"

  if [[ ! -d "${CACHE_BASE}" ]]; then
    echo "[prototype-local] Warning: CACHE_BASE (${CACHE_BASE}) does not exist." >&2
  fi

  HOST_VALUE="${HOST:-${DEFAULT_HOST}}"
  PORT_VALUE="${PORT:-${DEFAULT_PORT}}"

  if lsof -ti tcp:"${PORT_VALUE}" >/dev/null; then
    echo "[prototype-local] Port ${PORT_VALUE} appears busy. Use './scripts/start_prototype_local.sh stop' or set PORT before retrying." >&2
    exit 1
  fi

  cd "${PROJECT_ROOT}"

  check_database_exists
  start_scan_worker

  uvicorn_args=(--host "${HOST_VALUE}" --port "${PORT_VALUE}" --reload --reload-dir "${PROJECT_ROOT}")
  if [[ -n "${UVICORN_EXTRA_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    uvicorn_args+=(${UVICORN_EXTRA_ARGS})
  fi

  echo "[prototype-local] Starting uvicorn on ${HOST_VALUE}:${PORT_VALUE}" >&2
  exec "${PYTHON_BIN}" -m uvicorn api.main:app "${uvicorn_args[@]}"
}

stop_service() {
  local port="${PORT:-${DEFAULT_PORT}}"
  echo "[prototype-local] Attempting to stop processes on port ${port}..." >&2

  local pids_str
  pids_str="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -z "${pids_str}" ]]; then
    echo "[prototype-local] No process bound to port ${port}." >&2
    pkill -f "uvicorn api.main:app" >/dev/null 2>&1 && echo "[prototype-local] Terminated matching uvicorn process." >&2
    return
  fi

  for pid in ${pids_str}; do
    echo "[prototype-local] Terminating PID ${pid}" >&2
    kill -TERM "${pid}" >/dev/null 2>&1 || true
  done
  sleep 1

  if lsof -ti tcp:"${port}" >/dev/null; then
    echo "[prototype-local] Processes still alive; sending SIGKILL." >&2
    for pid in ${pids_str}; do
      kill -KILL "${pid}" >/dev/null 2>&1 || true
    done
  fi

  if lsof -ti tcp:"${port}" >/dev/null; then
    echo "[prototype-local] Warning: port ${port} remains in use." >&2
  else
    echo "[prototype-local] Port ${port} is free." >&2
  fi

  local worker_pids
  worker_pids="$(find_scan_worker_pids)"
  if [[ -z "${worker_pids}" ]]; then
    echo "[prototype-local] No scan worker process found." >&2
    return
  fi

  echo "[prototype-local] Stopping scan worker PID(s): ${worker_pids}" >&2
  for pid in ${worker_pids}; do
    kill -TERM "${pid}" >/dev/null 2>&1 || true
  done
}

COMMAND="${1:-start}"

case "${COMMAND}" in
  start)
    maybe_install_deps
    ensure_postgres
    start_service
    ;;
  install)
    FORCE_INSTALL=1 maybe_install_deps
    ;;
  stop)
    stop_service
    ;;
  help|-h|--help)
    print_usage
    ;;
  *)
    echo "[prototype-local] Unknown command: ${COMMAND}" >&2
    print_usage
    exit 1
    ;;
esac
