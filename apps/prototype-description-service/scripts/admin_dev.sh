#!/usr/bin/env bash
#
# admin_dev.sh - Local dev automation for the /admin tenant-management console.
#
# The /admin router mounts only when RECOGNITION_ADMIN_ENABLED=true and a
# >=32-char RECOGNITION_ADMIN_TOKEN is set (recognition/config/security.py:
# validate_admin_config). This helper wires those into the local .env, brings the
# service up with /admin mounted, opens the browser console, and runs a JSON smoke
# harness against the admin API (create tenant -> mint key -> list -> revoke).
#
# RECOGNITION_ADMIN_TAILNET_BOUND is a production-only gate and is NOT required
# locally (the local .env runs RECOGNITION_RUNTIME_MODE=development).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

HOST="${ADMIN_DEV_HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
BASE_URL="http://${HOST}:${PORT}"
ADMIN_URL="${BASE_URL}/admin/"
TOKEN_MIN_LENGTH=32
READY_TIMEOUT="${ADMIN_DEV_READY_TIMEOUT:-60}"

ADMIN_TOKEN=""

log() { printf '[admin-dev] %s\n' "$*" >&2; }
die() { printf '[admin-dev] ERROR: %s\n' "$*" >&2; exit 1; }

require_env_file() {
  [[ -f "${ENV_FILE}" ]] || die ".env not found at ${ENV_FILE}. Set up the service first (README / make setup)."
}

gen_token() { python3 -c "import secrets; print(secrets.token_urlsafe(32))"; }

# Upsert KEY=VALUE in .env (replace the line in place, or append if absent).
upsert_env() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "${ENV_FILE}"; then
    awk -v k="${key}" -v v="${val}" '
      $0 ~ "^" k "=" { print k "=" v; next }
      { print }
    ' "${ENV_FILE}" >"${tmp}"
  else
    cat "${ENV_FILE}" >"${tmp}"
    printf '%s=%s\n' "${key}" "${val}" >>"${tmp}"
  fi
  mv "${tmp}" "${ENV_FILE}"
}

# read_env KEY -> prints the value (strips one layer of surrounding quotes).
read_env() {
  local key="$1" line
  line="$(grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -n1 || true)"
  line="${line#"${key}"=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "${line}"
}

ensure_admin_env() {
  require_env_file
  local token
  token="$(read_env RECOGNITION_ADMIN_TOKEN)"
  if [[ -z "${token}" || ${#token} -lt ${TOKEN_MIN_LENGTH} ]]; then
    token="$(gen_token)"
    upsert_env RECOGNITION_ADMIN_TOKEN "${token}"
    log "generated a new RECOGNITION_ADMIN_TOKEN in .env"
  fi
  upsert_env RECOGNITION_ADMIN_ENABLED true
  ADMIN_TOKEN="${token}"
}

load_token() {
  require_env_file
  ADMIN_TOKEN="$(read_env RECOGNITION_ADMIN_TOKEN)"
  [[ -n "${ADMIN_TOKEN}" ]] || die "RECOGNITION_ADMIN_TOKEN is not set. Run 'make admin-dev' first."
}

# http_code URL -> status code (000 when unreachable). curl's -w already prints
# "000" on connection failure; capture it and normalize rather than appending a
# second "000" via `||`, which would make a down service look like up_other:000000.
http_code() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null)" || true
  [[ "${code}" =~ ^[0-9]{3}$ ]] || code="000"
  printf '%s' "${code}"
}

# down | up_no_admin | up_admin | up_other:<code>
admin_state() {
  local health admin
  health="$(http_code "${BASE_URL}/health")"
  [[ "${health}" == "000" ]] && { echo down; return; }
  admin="$(http_code "${ADMIN_URL}")"
  case "${admin}" in
    401) echo up_admin ;;
    404) echo up_no_admin ;;
    *) echo "up_other:${admin}" ;;
  esac
}

wait_for_admin() {
  local waited=0
  while ((waited < READY_TIMEOUT)); do
    [[ "$(admin_state)" == "up_admin" ]] && return 0
    sleep 1; waited=$((waited + 1))
  done
  return 1
}

start_service() {
  log "starting service via 'make serve' (background)..."
  (cd "${PROJECT_ROOT}" && make serve) >/dev/null 2>&1 \
    || die "make serve failed; check ${PROJECT_ROOT}/logs/prototype-local.log"
}

stop_service() { (cd "${PROJECT_ROOT}" && make stop) || true; }

open_browser() {
  if command -v open >/dev/null 2>&1; then
    open "${ADMIN_URL}" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${ADMIN_URL}" >/dev/null 2>&1 || true
  else
    log "no 'open'/'xdg-open' found; browse to ${ADMIN_URL} manually."
  fi
}

print_access() {
  cat >&2 <<EOF

  /admin console : ${ADMIN_URL}
  Basic auth     : username = anything, password = the admin token below
  API header     : X-Admin-Token: <admin token below>
  Admin token    : ${ADMIN_TOKEN}

EOF
}

cmd_up() {
  ensure_admin_env
  case "$(admin_state)" in
    up_admin)
      log "service already up with /admin mounted." ;;
    down)
      start_service ;;
    *)
      log "service up but /admin not mounted; restarting to apply admin env..."
      stop_service
      start_service ;;
  esac
  wait_for_admin || die "/admin not reachable within ${READY_TIMEOUT}s. Check ${PROJECT_ROOT}/logs/prototype-local.log"
  log "/admin is reachable."
  print_access
  [[ "${ADMIN_DEV_NO_OPEN:-0}" == "1" ]] || open_browser
}

# --- JSON smoke harness --------------------------------------------------------

_LAST_BODY=""
_LAST_CODE=""

call_admin() { # call_admin METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}" raw
  local args=(-s -w $'\n%{http_code}' --max-time 10 -X "${method}" -H "X-Admin-Token: ${ADMIN_TOKEN}")
  [[ -n "${body}" ]] && args+=(-H 'Content-Type: application/json' -d "${body}")
  raw="$(curl "${args[@]}" "${BASE_URL}${path}")"
  _LAST_CODE="${raw##*$'\n'}"
  _LAST_BODY="${raw%$'\n'*}"
}

jget() { python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" <<<"${_LAST_BODY}"; }

PASS=0
FAIL=0

expect_code() { # expect_code "desc" want_code
  if [[ "${_LAST_CODE}" == "$2" ]]; then
    printf '  \033[32mPASS\033[0m %s (HTTP %s)\n' "$1" "${_LAST_CODE}" >&2
    PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m %s (want HTTP %s, got %s): %s\n' "$1" "$2" "${_LAST_CODE}" "${_LAST_BODY}" >&2
    FAIL=$((FAIL + 1))
  fi
}

expect_eq() { # expect_eq "desc" actual want
  if [[ "$2" == "$3" ]]; then
    printf '  \033[32mPASS\033[0m %s (%s)\n' "$1" "$2" >&2
    PASS=$((PASS + 1))
  else
    printf '  \033[31mFAIL\033[0m %s (want %s, got %s)\n' "$1" "$3" "$2" >&2
    FAIL=$((FAIL + 1))
  fi
}

cmd_test() {
  load_token
  [[ "$(admin_state)" == "up_admin" ]] || die "/admin not reachable at ${ADMIN_URL}. Run 'make admin-dev' first."

  local tid site kid apikey unauth
  tid="$(python3 -c 'import uuid;print(uuid.uuid4())')"
  site="https://smoke-${tid}.example.test"
  log "smoke harness -> ${BASE_URL}/admin (throwaway tenant ${tid})"

  call_admin POST "/admin/tenants" "{\"tenant_id\":\"${tid}\",\"site_url\":\"${site}\"}"
  expect_code "create tenant" 201

  call_admin POST "/admin/tenants" "{\"tenant_id\":\"${tid}\",\"site_url\":\"${site}\"}"
  expect_code "re-create same tenant is idempotent upsert" 201

  call_admin POST "/admin/tenants/${tid}/keys" "{}"
  expect_code "mint key" 201
  kid="$(jget key_id)"
  apikey="$(jget api_key)"
  expect_eq "raw key returned once" "$([[ -n "${apikey}" ]] && echo yes || echo no)" yes

  call_admin GET "/admin/tenants/${tid}/keys"
  expect_code "list keys" 200
  expect_eq "minted key present in list" "$(grep -q "${kid}" <<<"${_LAST_BODY}" && echo yes || echo no)" yes

  call_admin POST "/admin/keys/${kid}/revoke"
  expect_code "revoke key" 200
  expect_eq "first revoke already_revoked=False" "$(jget already_revoked)" False

  call_admin POST "/admin/keys/${kid}/revoke"
  expect_code "re-revoke is idempotent 200" 200
  expect_eq "second revoke already_revoked=True" "$(jget already_revoked)" True

  unauth="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST \
    "${BASE_URL}/admin/tenants" -H 'Content-Type: application/json' -d '{}' 2>/dev/null || echo 000)"
  expect_eq "unauthenticated create rejected 401" "${unauth}" 401

  printf '\n[admin-dev] smoke: %d passed, %d failed\n' "${PASS}" "${FAIL}" >&2
  [[ "${FAIL}" -eq 0 ]]
}

usage() {
  cat >&2 <<'USAGE'
Usage: admin_dev.sh <command>

Commands:
  up       Enable admin env in .env, start the service, open /admin, print token   (default)
  test     Run the JSON admin smoke harness (create tenant -> mint -> list -> revoke)
  open     Open the /admin console in a browser + print the token
  token    Print the current RECOGNITION_ADMIN_TOKEN (stdout)
  status   Print service/admin reachability state (down|up_no_admin|up_admin)
  down     Stop the local service (make stop)

Environment:
  PORT (8000), ADMIN_DEV_HOST (127.0.0.1), ADMIN_DEV_READY_TIMEOUT (60s),
  ADMIN_DEV_NO_OPEN=1  Skip auto-opening the browser on 'up'.
USAGE
}

main() {
  case "${1:-up}" in
    up) cmd_up ;;
    test) cmd_test ;;
    open) load_token; open_browser; print_access ;;
    token) load_token; printf '%s\n' "${ADMIN_TOKEN}" ;;
    status) admin_state ;;
    down) stop_service ;;
    help | -h | --help) usage ;;
    *) log "unknown command: $1"; usage; exit 1 ;;
  esac
}

main "$@"
