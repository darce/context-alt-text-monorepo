#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
DEFAULT_HOST="0.0.0.0"
DEFAULT_PORT="8000"
ENV_FILE="${PROJECT_ROOT}/.env"
DB_COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.db.yml"
COMPOSE_CMD=()

resolve_compose_command() {
  if [[ "${#COMPOSE_CMD[@]}" -gt 0 ]]; then
    return 0
  fi

  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return 0
  fi

  return 1
}

docker_daemon_running() {
  docker info >/dev/null 2>&1
}

cleanup_colima_profile() {
  local profile="$1"

  colima stop --profile "${profile}" >/dev/null 2>&1 || true
  if command -v limactl >/dev/null 2>&1; then
    limactl stop "${profile}" >/dev/null 2>&1 || true
  fi
}

start_colima() {
  if ! command -v colima >/dev/null 2>&1; then
    return 1
  fi

  local profile="${COLIMA_PROFILE:-default}"
  if colima status --profile "${profile}" >/dev/null 2>&1; then
    return 0
  fi

  cleanup_colima_profile "${profile}"

  echo "[prototype-local] Docker daemon unavailable. Attempting to start Colima profile '${profile}'..." >&2
  if colima start --profile "${profile}"; then
    return 0
  fi

  echo "[prototype-local] Colima start failed; attempting to stop any stale '${profile}' instance..." >&2
  cleanup_colima_profile "${profile}"

  echo "[prototype-local] Retrying Colima start for profile '${profile}'..." >&2
  if colima start --profile "${profile}"; then
    return 0
  fi

  echo "[prototype-local] Failed to start Colima profile '${profile}'. Start Docker manually or set SKIP_DB_START=1." >&2
  if command -v limactl >/dev/null 2>&1; then
    echo "[prototype-local] Hint: 'limactl list' to inspect lingering Lima VMs, or 'limactl delete ${profile}' to reset the Colima VM." >&2
  fi
  return 1
}

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
  SKIP_DB_START        Set to 1 to skip starting the dockerized Postgres dependency
  HOST                 Uvicorn host binding (default: 0.0.0.0)
  PORT                 Uvicorn port (default: 8000)
  FORCE_INSTALL        Set to 1 to force reinstalling deps even when offline
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
  if [[ "${SKIP_DB_START:-0}" == "1" ]]; then
    echo "[prototype-local] SKIP_DB_START=1: skipping docker compose Postgres startup." >&2
    return
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "[prototype-local] Docker is not available; cannot start Postgres container. Set SKIP_DB_START=1 to silence this warning." >&2
    return
  fi

  if [[ ! -f "${DB_COMPOSE_FILE}" ]]; then
    echo "[prototype-local] ${DB_COMPOSE_FILE} not found; skipping Postgres startup." >&2
    return
  fi

  if ! resolve_compose_command; then
    echo "[prototype-local] docker compose plugin or docker-compose binary is required to manage Postgres. Set SKIP_DB_START=1 to silence this warning." >&2
    return
  fi

  if ! docker_daemon_running; then
    if ! start_colima; then
      return 1
    fi
    if ! docker_daemon_running; then
      echo "[prototype-local] Docker daemon is still unavailable after attempting to start Colima." >&2
      return 1
    fi
  fi

  echo "[prototype-local] Ensuring dockerized Postgres is running..." >&2
  "${COMPOSE_CMD[@]}" -f "${DB_COMPOSE_FILE}" up -d postgres
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

  echo "[prototype-local] Starting uvicorn on ${HOST_VALUE}:${PORT_VALUE}" >&2
  exec "${PYTHON_BIN}" -m uvicorn api.main:app --host "${HOST_VALUE}" --port "${PORT_VALUE}" --reload --reload-dir "${PROJECT_ROOT}"
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

  stop_postgres
}

stop_postgres() {
  if [[ "${SKIP_DB_START:-0}" == "1" ]]; then
    return
  fi

  if ! command -v docker >/dev/null 2>&1; then
    return
  fi

  if [[ ! -f "${DB_COMPOSE_FILE}" ]]; then
    return
  fi

  if ! resolve_compose_command; then
    return
  fi

  if ! docker_daemon_running; then
    return
  fi

  if "${COMPOSE_CMD[@]}" -f "${DB_COMPOSE_FILE}" ps --services --filter "status=running" | grep -q "^postgres\$"; then
    echo "[prototype-local] Stopping dockerized Postgres..." >&2
    "${COMPOSE_CMD[@]}" -f "${DB_COMPOSE_FILE}" stop postgres >/dev/null 2>&1 || true
  fi
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
