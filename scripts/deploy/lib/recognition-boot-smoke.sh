set -euo pipefail
# Leading space keeps this helper off the column-0 `fn() {` parser.
 _smoke_timeout() {
  local secs="$1" pid watcher rc=0
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout -k 1 "$secs" "$@"
    return
  fi
  # Cleanup trap ignores TERM/INT/HUP (inherited by children). SIGKILL cannot
  # be ignored, so the no-timeout reaper always bounds the command.
  "$@" &
  pid=$!
  ( sleep "$secs"; kill -s KILL "$pid" 2>/dev/null || true ) &
  watcher=$!
  wait "$pid" || rc=$?
  kill -s KILL "$watcher" 2>/dev/null || true
  wait "$watcher" 2>/dev/null || true
  if (( rc == 143 || rc == 137 )); then
    return 124
  fi
  return "$rc"
}
 _fail_if_setup_timeout() {
  local rc=0
  "$@" || rc=$?
  if (( rc == 124 )); then
    echo "smoke setup timed out" >&2
    exit 1
  fi
  if (( rc != 0 )); then
    exit "$rc"
  fi
}
env="$1"; image="$2"; remote_dir="$3"; budget_s="$4"; poll_s="$5"; vlm_budget="$6"
pg_budget="${7:-30}"
setup_slack="${8:-30}"
net_create_cap="${9:-10}"
port_cap="${10:-5}"
trap_docker_s="${11:-10}"
if ! [[ "${vlm_budget}" =~ ^[01]$ ]]; then
  echo "smoke vlm_budget invalid" >&2
  exit 2
fi
for _smoke_pair in "budget_s=${budget_s}" "poll_s=${poll_s}" "pg_budget=${pg_budget}" "setup_slack=${setup_slack}"; do
  _smoke_var="${_smoke_pair%%=*}"
  _smoke_val="${_smoke_pair#*=}"
  if ! [[ "${_smoke_val}" =~ ^[1-9][0-9]*$ ]]; then
    echo "smoke ${_smoke_var} invalid" >&2
    exit 2
  fi
done
env_file="${remote_dir}/.env"
net="$(grep -E '^ACX_NETWORK_NAME=' "${env_file}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"' " || true)"
net="${net:-acx-${env}-net}"
models_path="$(grep -E '^ACX_MODELS_PATH=' "${env_file}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
name="acx-smoke-${env}-$$"
blob_vol="acx-smoke-blobs-${env}-$$"
pg_name="acx-smoke-pg-${env}-$$"
smoke_owner="${pg_name}"
smoke_user="acx_smoke"
smoke_pass="acx_smoke_not_prod"
smoke_db="acx_smoke"
# Throwaway DSNs — host is the ephemeral container name on the smoke network.
smoke_async_dsn="postgresql+asyncpg://${smoke_user}:${smoke_pass}@${pg_name}:5432/${smoke_db}"
smoke_sync_dsn="postgresql+psycopg://${smoke_user}:${smoke_pass}@${pg_name}:5432/${smoke_db}"
# Inline trap (no nested function) so structural parsers that stop at first \n}\n
# still capture the full do_boot_smoke body. Print last_health_body + docker logs
# here so a deadline SIGTERM still emits the 503 body before cleanup.
# Install the trap before network create so a hung create still cleans up.
curl_err="$(mktemp)"
log_cap="$(mktemp)"
last_health_code="000"
last_health_body=""
smoke_passed=0
# WHY: EPIPE/closed stderr under set -e aborts a trap at the first echo; docker
# ops must run before any diagnostic write, and every write must tolerate failure.
trap '
  set +e
  trap - EXIT
  trap "" TERM INT HUP
  if [[ "${smoke_passed:-0}" != "1" ]]; then
    _smoke_timeout 2 docker logs --tail 80 "$name" >"$log_cap" 2>&1 || true
  fi
  _smoke_timeout 2 docker rm -f "$name" >/dev/null 2>&1 || true
  _smoke_timeout 2 docker rm -f "$pg_name" >/dev/null 2>&1 || true
  _smoke_timeout 2 docker volume rm -f "$blob_vol" >/dev/null 2>&1 || true
  if [[ "${smoke_passed:-0}" != "1" ]]; then
    _smoke_net_owner="$(_smoke_timeout 2 docker network inspect --format "{{index .Labels \"acx.smoke.owner\"}}" "$net" 2>/dev/null || true)"
    if [[ -n "${_smoke_net_owner}" && "${_smoke_net_owner}" == "${smoke_owner}" ]]; then
      _smoke_timeout 2 docker network rm "$net" >/dev/null 2>&1 || true
    fi
    if [[ -n "${curl_err:-}" && -s "${curl_err}" ]]; then
      if ! sanitize_deploy_diagnostic < "${curl_err}" >&2; then
        echo "diagnostic: curl stderr unavailable" >&2 || true
      fi
    fi
    echo "smoke health LAST HTTP code: ${last_health_code:-000}" >&2 || true
    echo "smoke health LAST body (up to 2000 bytes):" >&2 || true
    if ! printf "%s\n" "${last_health_body:0:2000}" | sanitize_deploy_diagnostic >&2; then
      echo "diagnostic: smoke health LAST body unavailable" >&2 || true
    fi
    echo "smoke container logs (last 80 lines):" >&2 || true
    if [[ -s "${log_cap}" ]]; then
      if ! sanitize_deploy_diagnostic < "${log_cap}" >&2; then
        echo "smoke container logs unavailable" >&2 || true
      fi
    else
      echo "smoke container logs unavailable" >&2 || true
    fi
  fi
  rm -f "$curl_err" "$log_cap"
' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
# First-ever deploy of an env runs this smoke BEFORE converge_runtime's net
# auto-create, so the env net may not exist yet (gate r0811864a A-01). Create
# it idempotently with compose-parity labels so the later `compose up` adopts
# it instead of refusing an unlabeled pre-existing net (A-02 pattern).
# Ownership label lets the trap rm a net whose create timed out after the
# daemon already created it, without touching a compose-owned or foreign net.
if ! docker network inspect "$net" >/dev/null 2>&1; then
  _fail_if_setup_timeout _smoke_timeout "$net_create_cap" docker network create \
    --label com.docker.compose.network=backend \
    --label "com.docker.compose.project=acx-${env}" \
    --label "acx.smoke.owner=${smoke_owner}" \
    "$net"
fi
# Ephemeral Postgres so entrypoint migrate/schema-verify never touch live env DB.
# Ready-wait uses pg_budget, not the /health attempt count / ACX_SMOKE_TIMEOUT.
# --pull=never: pgvector was pre-pulled fail-closed before this body ran.
_fail_if_setup_timeout _smoke_timeout "$setup_slack" docker run -d --rm --name "$pg_name" --network "$net" --pull=never \
  -e POSTGRES_USER="$smoke_user" \
  -e POSTGRES_PASSWORD="$smoke_pass" \
  -e POSTGRES_DB="$smoke_db" \
  pgvector/pgvector:pg17 >/dev/null
pg_ready=0
pg_end=$((SECONDS + pg_budget))
while (( SECONDS < pg_end )); do
  pg_exec_rc=0
  _smoke_timeout 2 docker exec "$pg_name" pg_isready -U "$smoke_user" -d "$smoke_db" >/dev/null 2>&1 || pg_exec_rc=$?
  if (( pg_exec_rc == 0 )); then
    pg_ready=1
    break
  fi
  if (( SECONDS < pg_end )); then
    sleep 1
  fi
done
if [[ "$pg_ready" != "1" ]]; then
  echo "smoke ephemeral postgres failed to become ready" >&2
  exit 1
fi
# Real image CMD — do not override entrypoint; must exercise docker-entrypoint.sh
# (and /app/.image-variant fail-closed checks owned by sibling lane).
# -e overrides beat --env-file; force env secret backend so oci_vault cannot
# inject the live prod POSTGRES_DSN after env-file is loaded.
# tmpfs matches compose HF_MODULES_CACHE mount (HARM-A-02): noexec + uid 10001
# so smoke exercises the deployed module-scratch topology, not the image layer dir.
# S2-A-08: compose hard-fails without ACX_MODELS_PATH (no default on the :ro
# cache bind). Smoke must not go green on an .env the real stack cannot start under.
if [[ -z "${models_path}" ]]; then
  echo "smoke requires ACX_MODELS_PATH in ${env_file} (compose would fail without it)" >&2
  exit 1
fi
# WHY: do not --rm the API smoke container. Entrypoint crash would delete it
# before the failure branch can `docker logs`; the EXIT trap already rm -f's it.
run_args=( -d --name "$name" --env-file "${env_file}" --network "$net" -P
  -e RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs
  -e RECOGNITION_SECRET_BACKEND=env
  -e POSTGRES_DSN="${smoke_async_dsn}"
  -e POSTGRES_SYNC_DSN="${smoke_sync_dsn}"
  -e PGHOST="${pg_name}"
  -e PGPORT=5432
  -e PGUSER="${smoke_user}"
  -e PGPASSWORD="${smoke_pass}"
  -e DB_NAME="${smoke_db}"
  -e RECOGNITION_ADMIN_TOKEN=acx-smoke-admin-token-not-for-prod-use
  -v "${blob_vol}:/var/lib/acx-blobs"
  -v "${models_path}:/data/cache:ro"
  --tmpfs /var/cache/acx/hf_modules:mode=0700,uid=10001,gid=10001,size=32m,noexec )
_fail_if_setup_timeout _smoke_timeout "$setup_slack" docker run "${run_args[@]}" "$image" >/dev/null
port_rc=0
port_out="$(_smoke_timeout "$port_cap" docker port "$name" 8000/tcp)" || port_rc=$?
if (( port_rc == 124 )); then
  echo "smoke setup timed out" >&2
  exit 1
fi
if (( port_rc != 0 )); then
  exit "$port_rc"
fi
port="$(printf '%s\n' "$port_out" | head -1 | sed 's/.*://')"
if ! [[ "${port}" =~ ^[0-9]+$ ]]; then
  echo "smoke setup failed: no published port" >&2
  exit 1
fi
# EXIT trap: timeout 2 × 6 docker ops; composite_deadline reserves its wall
# clock separately from this full health window.
# Outer composite adds +1s kill-grace per op (GR-262).
health_budget="$budget_s"
if (( health_budget < 1 )); then
  health_budget=1
fi
health_end=$((SECONDS + health_budget))
probe_n=0
while (( SECONDS < health_end )); do
  # Skip a probe when only one poll interval remains, but always allow the
  # first probe so a tiny clamped health_budget still observes /health.
  if (( probe_n > 0 && health_end - SECONDS <= poll_s )); then
    break
  fi
  health_response=""
  health_curl_rc=0
  health_response="$(curl -sS --max-time $(( health_end - SECONDS > 0 ? health_end - SECONDS : 1 )) --write-out $'\n%{http_code}' "http://127.0.0.1:${port}/health" 2>"${curl_err}")" || health_curl_rc=$?
  probe_n=$((probe_n + 1))
  if [[ "${health_response}" == *$'\n'* ]]; then
    last_health_code="${health_response##*$'\n'}"
    last_health_body="${health_response%$'\n'*}"
  else
    last_health_code="000"
    last_health_body="${health_response}"
  fi
  [[ "${last_health_code}" =~ ^[0-9]{3}$ ]] || last_health_code="000"
  if (( health_curl_rc == 0 )) && [[ "${last_health_code}" =~ ^2[0-9][0-9]$ ]]; then
    # Exit before any /ready probe. The outer run_with_deadline uses the same
    # budget as this loop; a diagnostic must not turn a marginal pass into rc 124.
    if ! printf '%s\n' "smoke health OK (HTTP ${last_health_code})" | sanitize_deploy_diagnostic; then
      echo "diagnostic: smoke health OK (HTTP ${last_health_code})"
    fi
    smoke_passed=1
    exit 0
  fi
  if (( SECONDS < health_end )); then
    sleep "${poll_s}"
  fi
done
if [[ "${vlm_budget}" == "1" ]]; then
  echo "smoke health FAILED after ${budget_s}s (VLM budget is an UNVALIDATED default — raise via ACX_SMOKE_TIMEOUT once a real arm64 VLM smoke is measured)" >&2
else
  echo "smoke health FAILED after ${budget_s}s" >&2
fi
exit 1
