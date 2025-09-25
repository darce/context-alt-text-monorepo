#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
DEFAULT_HOST="0.0.0.0"
DEFAULT_PORT="7860"

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
    echo "[recognition-local] SKIP_INSTALL=1: skipping dependency installation." >&2
    return 0
  fi

  if [[ "${FORCE_INSTALL:-0}" == "1" ]]; then
    install_deps
    return 0
  fi

  if has_network_access; then
    install_deps
  else
    echo "[recognition-local] No network detected; skipping dependency installation. Set FORCE_INSTALL=1 to override." >&2
  fi
}

print_usage() {
  cat <<'USAGE'
Usage: start_recognition_local.sh [command]

Commands:
  start        Install dependencies (unless SKIP_INSTALL=1) and launch uvicorn
  install      Install/upgrade local dependencies only
  stop         Stop uvicorn processes started for this app (best effort)
  help         Show this help text

Environment variables:
  PYTHON_BIN        Python executable to use (default: python)
  SKIP_INSTALL      Set to 1 to skip dependency installation during start
  HOST              Uvicorn host binding (default: 0.0.0.0)
  PORT              Uvicorn port (default: 7860)
  LOCAL_CACHE_ROOT  Cache root (default: /Volumes/Butter)
USAGE
}

install_deps() {
  echo "[recognition-local] Upgrading pip and installing requirements..." >&2
  "${PYTHON_BIN}" -u -m pip install --upgrade pip

  if [[ $(uname -s) == "Darwin" && $(uname -m) == "arm64" ]]; then
    "${SCRIPT_DIR}/install_insightface_mac.sh"
  fi

  "${PYTHON_BIN}" -m pip install -r "${PROJECT_ROOT}/requirements_local.txt"
  echo "[recognition-local] Runtime dependencies installed." >&2
  "${PYTHON_BIN}" -m pip install -r "${PROJECT_ROOT}/requirements_local_dev.txt"
  echo "[recognition-local] Dev dependencies installed." >&2

  if ! "${PYTHON_BIN}" -m pip check >/dev/null; then
    echo "[recognition-local] Warning: dependency check reported issues." >&2
    "${PYTHON_BIN}" -m pip check || true
  fi
}

start_service() {
  export RECOG_SETTINGS="${PROJECT_ROOT}/recognition_core/config/settings.yaml"
  export LOCAL_CACHE_ROOT="${LOCAL_CACHE_ROOT:-/Volumes/Butter}"

  if [[ ! -d "${LOCAL_CACHE_ROOT}" ]]; then
    echo "[recognition-local] Warning: LOCAL_CACHE_ROOT (${LOCAL_CACHE_ROOT}) does not exist." >&2
  fi

  HOST_VALUE="${HOST:-${DEFAULT_HOST}}"
  PORT_VALUE="${PORT:-${DEFAULT_PORT}}"

  if lsof -ti tcp:"${PORT_VALUE}" >/dev/null; then
    echo "[recognition-local] Port ${PORT_VALUE} appears busy. Use './scripts/start_recognition_local.sh stop' or set PORT before retrying." >&2
    exit 1
  fi

  echo "[recognition-local] Starting uvicorn on ${HOST_VALUE}:${PORT_VALUE}" >&2
  exec uvicorn app:app --host "${HOST_VALUE}" --port "${PORT_VALUE}" --reload
}

stop_service() {
  local port="${PORT:-${DEFAULT_PORT}}"
  echo "[recognition-local] Attempting to stop processes on port ${port}..." >&2

  pids_str="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -z "${pids_str}" ]]; then
    echo "[recognition-local] No process bound to port ${port}." >&2
    # Fallback: try killing uvicorn explicitly in case port changed
    pkill -f "uvicorn app:app" >/dev/null 2>&1 && echo "[recognition-local] Terminated matching uvicorn process." >&2
    return
  fi

  for pid in ${pids_str}; do
    echo "[recognition-local] Terminating PID ${pid}" >&2
    kill -TERM "${pid}" >/dev/null 2>&1 || true
  done
  sleep 1

  if lsof -ti tcp:"${port}" >/dev/null; then
    echo "[recognition-local] Processes still alive; sending SIGKILL." >&2
    for pid in ${pids_str}; do
      kill -KILL "${pid}" >/dev/null 2>&1 || true
    done
  fi

  if lsof -ti tcp:"${port}" >/dev/null; then
    echo "[recognition-local] Warning: port ${port} remains in use." >&2
  else
    echo "[recognition-local] Port ${port} is free." >&2
  fi
}

COMMAND="${1:-start}"

case "${COMMAND}" in
  start)
    maybe_install_deps
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
    echo "[recognition-local] Unknown command: ${COMMAND}" >&2
    print_usage
    exit 1
    ;;
esac
