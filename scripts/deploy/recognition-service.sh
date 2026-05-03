#!/usr/bin/env bash
# Recognition service deploy automation for OCI.
#
# Wraps the build -> push -> ssh restart -> verify procedure documented in
# infra/oci/README.md into one command per environment, with pre-flight checks
# that catch the common foot-guns:
#   - docker daemon not running (local build mode)
#   - OCIR auth token missing/expired (local or remote)
#   - SSH key not loaded / public-IP allowlist drift
#   - HEAD diverged from origin/main (staging/prod only)
#   - dirty working tree (warned for dev, blocked for staging/prod)
#
# Subcommands:
#   build          [tag]              Build :SHA + :tag locally (no push). tag default = dev.
#   build-remote   [tag]              Build :SHA + :tag on the OCI VM (no local docker).
#   deploy <env>                      Build + push :SHA + :ENV_TAG + ssh restart + verify.
#                                       'deploy prod' requires CONFIRM=PROMOTE.
#   promote <from> <to>               Retag :FROM_TAG -> :TO_TAG on OCIR + restart + verify.
#                                       e.g. promote dev staging, promote staging prod (CONFIRM=PROMOTE),
#                                       promote staging dev (rollback path).
#   verify         <env>              GET /health and compare commit_sha to GIT_REF (default HEAD).
#                                       Retries up to ACX_VERIFY_ATTEMPTS times for warm-up. Fails closed.
#   status                            Snapshot /health for dev, staging, prod.
#
# Set REMOTE_BUILD=1 (or env ACX_REMOTE_BUILD=1) to make 'deploy' / 'promote' build/retag
# on the OCI VM via SSH+rsync instead of locally. Removes the colima/Docker-Desktop
# dependency entirely; build runs natively on linux/arm64 (no cross-compile).
#
# Environment overrides:
#   OCI_HOST                 default acx-backend.tail1a44b8.ts.net  (Tailscale MagicDNS)
#                              override to the public IP if the tailnet is unavailable
#   OCI_USER                 default ubuntu
#   OCIR_REGISTRY            default iad.ocir.io
#   OCIR_NAMESPACE           default idu2kqqe2jxy
#   IMAGE_NAME               default acx-backend
#   GIT_REF                  default HEAD
#   ACX_DEPLOY_PLATFORM      default linux/arm64 (matches A1 Always Free shape; ignored in remote-build)
#   ACX_REMOTE_BUILD         set to 1 to build on the VM instead of locally
#   ACX_REMOTE_BUILD_DIR     default /tmp/acx-build  (rsync target on the VM)
#   ACX_ALLOW_DIRTY          set to 1 to skip dirty-tree check (dev only)
#   ACX_VERIFY_ATTEMPTS      default 5  (post-deploy verify retry count for warm-up)
#   ACX_VERIFY_SLEEP         default 5  (seconds between verify attempts)
#   ACX_VERIFY_OPTIONAL      set to 1 to downgrade verify failure from fail to warn after deploy/promote
#   CONFIRM                  required for prod actions: CONFIRM=PROMOTE (applies to deploy prod and promote * prod)
set -euo pipefail

OCI_HOST="${OCI_HOST:-acx-backend.tail1a44b8.ts.net}"
OCI_USER="${OCI_USER:-ubuntu}"
OCIR_REGISTRY="${OCIR_REGISTRY:-iad.ocir.io}"
OCIR_NAMESPACE="${OCIR_NAMESPACE:-idu2kqqe2jxy}"
IMAGE_NAME="${IMAGE_NAME:-acx-backend}"
GIT_REF="${GIT_REF:-HEAD}"
PLATFORM="${ACX_DEPLOY_PLATFORM:-linux/arm64}"
REMOTE_BUILD="${REMOTE_BUILD:-${ACX_REMOTE_BUILD:-0}}"
REMOTE_BUILD_DIR="${ACX_REMOTE_BUILD_DIR:-/tmp/acx-build}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${REPO_ROOT}/apps/prototype-description-service"
IMAGE_BASE="${OCIR_REGISTRY}/${OCIR_NAMESPACE}/${IMAGE_NAME}"
SSH_TARGET="${OCI_USER}@${OCI_HOST}"

GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
RED=$'\033[0;31m'
RESET=$'\033[0m'

log()  { printf '%s==>%s %s\n' "${GREEN}" "${RESET}" "$*"; }
warn() { printf '%s!!%s %s\n'  "${YELLOW}" "${RESET}" "$*" >&2; }
fail() { printf '%sxx%s %s\n'  "${RED}"    "${RESET}" "$*" >&2; exit 1; }

#---------------------------------------------------------------- env mapping
env_to_tag() {
  case "$1" in
    dev)     echo "dev" ;;
    staging) echo "staging" ;;
    prod)    echo "latest" ;;
    *)       fail "Unknown env: $1 (expected dev|staging|prod)" ;;
  esac
}
env_to_unit() {
  case "$1" in
    dev) echo "acx-dev" ;; staging) echo "acx-staging" ;; prod) echo "acx-prod" ;;
    *) fail "Unknown env: $1" ;;
  esac
}
env_to_remote_dir() {
  case "$1" in
    dev) echo "/opt/acx-backend/dev" ;;
    staging) echo "/opt/acx-backend/staging" ;;
    prod) echo "/opt/acx-backend/prod" ;;
    *) fail "Unknown env: $1" ;;
  esac
}
env_to_health_url() {
  case "$1" in
    dev)     echo "https://dev.api.altcontext.com/health" ;;
    staging) echo "https://staging.api.altcontext.com/health" ;;
    prod)    echo "https://api.altcontext.com/health" ;;
    *) fail "Unknown env: $1" ;;
  esac
}
env_to_ready_url() {
  case "$1" in
    dev)     echo "https://dev.api.altcontext.com/ready" ;;
    staging) echo "https://staging.api.altcontext.com/ready" ;;
    prod)    echo "https://api.altcontext.com/ready" ;;
    *) fail "Unknown env: $1" ;;
  esac
}

#---------------------------------------------------------------- pre-flight
preflight_docker() {
  command -v docker >/dev/null 2>&1 || fail "docker not found in PATH"
  docker info >/dev/null 2>&1 || fail "docker daemon not running (start colima with \`colima start\`, or start Docker Desktop)"
}
preflight_ocir_auth() {
  local cfg="${HOME}/.docker/config.json"
  if [[ ! -f "$cfg" ]] || ! grep -q "\"${OCIR_REGISTRY}\"" "$cfg" 2>/dev/null; then
    warn "No cached OCIR credential for ${OCIR_REGISTRY}."
    warn "Run: docker login ${OCIR_REGISTRY} -u '${OCIR_NAMESPACE}/<email>' (paste OCI auth token as password)"
    fail "OCIR auth missing"
  fi
}
preflight_ssh() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${SSH_TARGET}" 'echo ok' >/dev/null 2>&1; then
    warn "SSH to ${SSH_TARGET} failed (check ssh-add, public-IP allowlist, key path, tailnet status)."
    fail "SSH unavailable"
  fi
}
preflight_remote_docker() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${SSH_TARGET}" 'docker info >/dev/null 2>&1'; then
    fail "docker not running (or user lacks docker group) on ${SSH_TARGET}"
  fi
}
preflight_remote_ocir_auth() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${SSH_TARGET}" \
       "test -f ~/.docker/config.json && grep -q '\"${OCIR_REGISTRY}\"' ~/.docker/config.json"; then
    warn "No cached OCIR credential on ${SSH_TARGET} (~/.docker/config.json missing or unauthenticated for ${OCIR_REGISTRY})."
    warn "On the VM run: docker login ${OCIR_REGISTRY} -u '${OCIR_NAMESPACE}/<email>' (paste OCI auth token as password)"
    fail "remote OCIR auth missing"
  fi
}
preflight_rsync() {
  command -v rsync >/dev/null 2>&1 || fail "rsync not found in PATH (required for remote-build mode)"
}
preflight_git_clean() {
  local env="$1"
  if ! git -C "${REPO_ROOT}" diff --quiet HEAD -- 2>/dev/null \
     || [[ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    if [[ "$env" == "dev" && "${ACX_ALLOW_DIRTY:-0}" == "1" ]]; then
      warn "Working tree is dirty (ACX_ALLOW_DIRTY=1, continuing for dev)."
    elif [[ "$env" == "dev" ]]; then
      warn "Working tree is dirty. Re-run with ACX_ALLOW_DIRTY=1 to override."
      fail "dirty tree (dev)"
    else
      fail "Working tree must be clean for ${env} deploys."
    fi
  fi
}
preflight_branch_synced() {
  local env="$1"
  [[ "$env" == "dev" ]] && return 0
  local head upstream
  head="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
  git -C "${REPO_ROOT}" fetch origin main >/dev/null 2>&1 || warn "git fetch failed; skew check may be stale"
  upstream="$(git -C "${REPO_ROOT}" rev-parse origin/main 2>/dev/null || echo unknown)"
  if [[ "$head" != "$upstream" ]]; then
    fail "HEAD (${head:0:8}) != origin/main (${upstream:0:8}). Pull/push first."
  fi
}

#---------------------------------------------------------------- build
do_build() {
  preflight_docker
  local sha tag
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  tag="${1:-dev}"
  log "Building ${IMAGE_BASE}:${tag} + :${sha:0:8} (${PLATFORM}, GIT_COMMIT_SHA=${sha:0:8})"
  cd "${SERVICE_DIR}"
  docker build \
    --platform "${PLATFORM}" \
    --build-arg "GIT_COMMIT_SHA=${sha}" \
    -t "${IMAGE_BASE}:${tag}" \
    -t "${IMAGE_BASE}:${sha}" \
    .
  log "Built ${IMAGE_BASE}:${tag} (also tagged :${sha:0:8})"
}

do_build_remote() {
  preflight_ssh
  preflight_remote_docker
  preflight_rsync
  local sha tag
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  tag="${1:-dev}"

  log "Syncing build context ${SERVICE_DIR}/ -> ${SSH_TARGET}:${REMOTE_BUILD_DIR}/"
  ssh "${SSH_TARGET}" "mkdir -p ${REMOTE_BUILD_DIR}"
  rsync -az --delete \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.venv/' \
    --exclude='*.egg-info/' \
    --exclude='build/' \
    --exclude='dist/' \
    --exclude='data/' \
    --exclude='logs/' \
    --exclude='node_modules/' \
    "${SERVICE_DIR}/" "${SSH_TARGET}:${REMOTE_BUILD_DIR}/"

  log "Building ${IMAGE_BASE}:${tag} + :${sha:0:8} on ${SSH_TARGET} (native arm64)"
  # No --platform: VM is already linux/arm64 (Ampere A1).
  ssh "${SSH_TARGET}" "cd ${REMOTE_BUILD_DIR} && docker build \
      --build-arg GIT_COMMIT_SHA=${sha} \
      -t ${IMAGE_BASE}:${tag} \
      -t ${IMAGE_BASE}:${sha} \
      ."
  log "Built ${IMAGE_BASE}:${tag} on ${SSH_TARGET} (also tagged :${sha:0:8})"
}

#---------------------------------------------------------------- push / restart
# Push both :tag and :sha so rollback by SHA stays available.
do_push() {
  local tag sha
  tag="$1"
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    preflight_remote_ocir_auth
    log "Pushing ${IMAGE_BASE}:${tag} + :${sha:0:8} from ${SSH_TARGET}"
    ssh "${SSH_TARGET}" "docker push ${IMAGE_BASE}:${tag} && docker push ${IMAGE_BASE}:${sha}"
  else
    preflight_ocir_auth
    log "Pushing ${IMAGE_BASE}:${tag} + :${sha:0:8} (local)"
    docker push "${IMAGE_BASE}:${tag}"
    docker push "${IMAGE_BASE}:${sha}"
  fi
}

do_restart() {
  local env="$1"
  local remote_dir unit
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  log "Pulling latest image + restarting ${unit} on ${SSH_TARGET}"
  ssh "${SSH_TARGET}" "cd ${remote_dir} && docker compose -f docker-compose.env.yml pull api && sudo systemctl restart ${unit}"
}

#---------------------------------------------------------------- deploy
do_deploy() {
  local env="$1"
  local tag
  tag="$(env_to_tag "$env")"

  if [[ "$env" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "Production deploy requires CONFIRM=PROMOTE. Re-run: CONFIRM=PROMOTE $0 deploy prod"
  fi

  preflight_ssh
  preflight_git_clean "$env"
  preflight_branch_synced "$env"

  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    log "Mode: remote-build (${SSH_TARGET}, no local docker required)"
    do_build_remote "$tag"
  else
    do_build "$tag"
  fi

  do_push "$tag"
  do_restart "$env"

  log "Deploy submitted. Verifying..."
  sleep 5
  if ! do_verify "$env"; then
    if [[ "${ACX_VERIFY_OPTIONAL:-0}" == "1" ]]; then
      warn "Verify failed but ACX_VERIFY_OPTIONAL=1; not failing the deploy."
    else
      fail "Deploy verification failed. Re-run '$0 verify $env' to retry, or set ACX_VERIFY_OPTIONAL=1 to downgrade to a warning."
    fi
  fi
}

#---------------------------------------------------------------- promote
do_promote() {
  local from_env="$1" to_env="$2"
  local from_tag to_tag
  from_tag="$(env_to_tag "$from_env")"
  to_tag="$(env_to_tag "$to_env")"

  preflight_ssh

  if [[ "$to_env" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "Production promotion requires CONFIRM=PROMOTE. Re-run: CONFIRM=PROMOTE $0 promote $from_env $to_env"
  fi

  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    log "Mode: remote-retag (${SSH_TARGET})"
    preflight_remote_docker
    preflight_remote_ocir_auth
    log "Pulling source image ${IMAGE_BASE}:${from_tag} on ${SSH_TARGET}"
    ssh "${SSH_TARGET}" "docker pull ${IMAGE_BASE}:${from_tag}"
    log "Tagging ${from_tag} -> ${to_tag} on ${SSH_TARGET}"
    ssh "${SSH_TARGET}" "docker tag ${IMAGE_BASE}:${from_tag} ${IMAGE_BASE}:${to_tag}"
    log "Pushing ${IMAGE_BASE}:${to_tag} from ${SSH_TARGET}"
    ssh "${SSH_TARGET}" "docker push ${IMAGE_BASE}:${to_tag}"
  else
    preflight_docker
    preflight_ocir_auth
    log "Pulling source image ${IMAGE_BASE}:${from_tag}"
    docker pull "${IMAGE_BASE}:${from_tag}"
    log "Tagging ${from_tag} -> ${to_tag}"
    docker tag "${IMAGE_BASE}:${from_tag}" "${IMAGE_BASE}:${to_tag}"
    log "Pushing ${IMAGE_BASE}:${to_tag}"
    docker push "${IMAGE_BASE}:${to_tag}"
  fi

  do_restart "$to_env"

  log "Promotion submitted. Verifying..."
  sleep 5
  if ! do_verify "$to_env"; then
    if [[ "${ACX_VERIFY_OPTIONAL:-0}" == "1" ]]; then
      warn "Verify failed but ACX_VERIFY_OPTIONAL=1; not failing the promotion."
    else
      fail "Promotion verification failed. Re-run '$0 verify $to_env' to retry, or set ACX_VERIFY_OPTIONAL=1 to downgrade to a warning."
    fi
  fi
}

#---------------------------------------------------------------- verify
do_verify() {
  local env="$1"
  local url expected_sha actual_sha body attempt max_attempts sleep_s
  url="$(env_to_health_url "$env")"
  # Use GIT_REF (defaults to HEAD) so verify after `GIT_REF=v0.4.1 deploy ...`
  # checks against the same ref the build/push paths used.
  expected_sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"

  # Bounded retry so post-restart warm-up (typically <30s) does not flap
  # verification, while a genuinely missing/skewed SHA still fails closed.
  max_attempts="${ACX_VERIFY_ATTEMPTS:-5}"
  sleep_s="${ACX_VERIFY_SLEEP:-5}"

  for attempt in $(seq 1 "$max_attempts"); do
    log "GET ${url} (attempt ${attempt}/${max_attempts})"
    if ! body="$(curl --fail --silent --show-error --max-time 10 "$url" 2>&1)"; then
      warn "Health check fetch failed: ${body}"
      sleep "$sleep_s"
      continue
    fi
    echo "$body"

    # /health surfaces commit SHA for E15-3a-BR-03 deploy-lag detection.
    actual_sha="$(printf '%s' "$body" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("commit_sha") or d.get("git_commit_sha") or d.get("version") or "")' 2>/dev/null || true)"

    if [[ -z "$actual_sha" || "$actual_sha" == "unknown" ]]; then
      warn "Service did not report a commit SHA (attempt ${attempt}/${max_attempts}). Image may have been built without --build-arg GIT_COMMIT_SHA."
      sleep "$sleep_s"
      continue
    fi

    if [[ "${actual_sha:0:8}" == "${expected_sha:0:8}" ]]; then
      log "Verified: ${env} runs ${actual_sha:0:8} (matches GIT_REF=${GIT_REF})"
      return 0
    else
      warn "SKEW: ${env} runs ${actual_sha:0:8}, expected ${expected_sha:0:8} (attempt ${attempt}/${max_attempts}; warm-up retry)"
      sleep "$sleep_s"
    fi
  done

  warn "SKEW: ${env} did not converge to ${expected_sha:0:8} after ${max_attempts} attempts."
  return 1
}

#---------------------------------------------------------------- status
do_status() {
  local env url body sha
  for env in dev staging prod; do
    url="$(env_to_health_url "$env")"
    if body="$(curl -fsS --max-time 5 "$url" 2>/dev/null)"; then
      sha="$(printf '%s' "$body" | python3 -c 'import json,sys;d=json.load(sys.stdin);print((d.get("commit_sha") or d.get("git_commit_sha") or "?")[:8])' 2>/dev/null || echo '?')"
      printf '%-8s %s   %s\n' "$env" "$sha" "$url"
    else
      printf '%-8s %s   %s\n' "$env" "unreachable" "$url"
    fi
  done
}

#---------------------------------------------------------------- reset
# Destructive remote reset for an OCI environment. This sub-slice (E15-12 slice
# 2a) lands the validation gates and the affirmative dry-run path. The actual
# stop/reset/start sequence + bootstrap + /ready verify is implemented in the
# follow-on slice; that path runs only when ACX_RESET_DRY_RUN!=1.
do_reset() {
  local env="$1"
  local unit remote_dir ready_url

  # env validation: reuse the existing case-based guards. They `fail` on unknown.
  unit="$(env_to_unit "$env")"
  remote_dir="$(env_to_remote_dir "$env")"
  ready_url="$(env_to_ready_url "$env")"

  if [[ "${CONFIRM_REMOTE_RESET:-}" != "RESET" ]]; then
    fail "Remote reset requires CONFIRM_REMOTE_RESET=RESET. Re-run: CONFIRM_REMOTE_RESET=RESET $0 reset $env"
  fi
  if [[ "$env" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "Production remote reset additionally requires CONFIRM=PROMOTE. Re-run: CONFIRM=PROMOTE CONFIRM_REMOTE_RESET=RESET $0 reset prod"
  fi

  log "Reset plan for env=${env}: unit=${unit} remote_dir=${remote_dir} ready_url=${ready_url}"
  log "SSH target: ${SSH_TARGET}"

  # Canonical remote command sequence. ACX_PGDATA_PATH is sourced from the env's
  # .env so the reset boundary stays exactly the env-scoped Postgres data root —
  # no other env's data is touched. `docker compose down` releases the volume
  # mount so the directory can be cleared atomically before restart.
  local remote_cmd
  printf -v remote_cmd '%s\n' \
    "set -euo pipefail" \
    "cd ${remote_dir}" \
    "echo '==> Stopping unit ${unit}'" \
    "sudo systemctl stop ${unit}" \
    "echo '==> Bringing compose project down to release the postgres volume'" \
    "sudo docker compose -f docker-compose.env.yml down --remove-orphans" \
    "echo '==> Sourcing ACX_PGDATA_PATH from ${remote_dir}/.env'" \
    "set -a" \
    "source ${remote_dir}/.env" \
    "set +a" \
    "if [ -z \"\${ACX_PGDATA_PATH:-}\" ]; then echo 'ACX_PGDATA_PATH is empty after sourcing .env — refusing to wipe' >&2; exit 64; fi" \
    "if [ \"\${ACX_PGDATA_PATH}\" = '/' ] || [ \"\${ACX_PGDATA_PATH}\" = '/opt' ] || [ \"\${ACX_PGDATA_PATH}\" = '/opt/acx-backend' ]; then echo \"Refusing to clear suspicious ACX_PGDATA_PATH=\${ACX_PGDATA_PATH}\" >&2; exit 65; fi" \
    "echo \"==> Clearing \${ACX_PGDATA_PATH}\"" \
    "sudo rm -rf -- \"\${ACX_PGDATA_PATH}\"" \
    "sudo mkdir -p -- \"\${ACX_PGDATA_PATH}\"" \
    "echo '==> Starting unit ${unit}'" \
    "sudo systemctl start ${unit}"

  # Post-reset bootstrap. Recreates one usable service-mode API key after the
  # destructive reset wipes the credentials table.
  #
  # Contract notes (E15-12-BR-03):
  #   - manage_api_keys.py requires a top-level --env {prod,dev,local}. The
  #     CLI validates --env against the configured DSN host: 'prod' rejects
  #     loopback hosts, 'dev|local' rejects non-loopback. Inside the api
  #     container on the OCI VM the DSN host is 'postgres' (compose service),
  #     which is non-loopback, so --env prod is the only choice that passes
  #     the validation guard regardless of OCI deployment env (dev/staging/prod).
  #   - The CLI uses `--tenant <uuid>`, NOT `--tenant-id <string>`. Tenant
  #     identifiers must be UUIDs.
  #   - There is no `--name` flag.
  #   - `create` requires the tenant row to already exist (FK constraint), so
  #     we run `tenant create --tenant <uuid> --site-url <url>` first; the
  #     CLI handles the create-or-update case idempotently.
  #   - The OCI postgres is what just got wiped — bootstrap must run on the
  #     remote VM via `docker compose exec api`, not locally.
  local tenant_id="${ACX_RESET_TENANT_ID:-00000000-0000-7000-8000-000000000000}"
  local site_url
  case "${env}" in
    prod)    site_url="${ACX_RESET_SITE_URL:-https://api.altcontext.com}" ;;
    staging) site_url="${ACX_RESET_SITE_URL:-https://staging.api.altcontext.com}" ;;
    *)       site_url="${ACX_RESET_SITE_URL:-https://dev.api.altcontext.com}" ;;
  esac
  # E15-12-BR-05: each `docker compose exec -T` reads from this script's
  # stdin (the `bash -s <<<"${bootstrap_cmd}"` heredoc on line 509). Without
  # `< /dev/null` on each exec, the first call swallows the remaining lines
  # of bootstrap_cmd and the second call silently never runs — the operator
  # sees the tenant create succeed but no `api_key=` line is printed and the
  # plugin has nothing to authenticate with.
  local bootstrap_cmd
  printf -v bootstrap_cmd '%s\n' \
    "cd ${remote_dir}" \
    "echo '==> Ensuring tenant row exists for service-mode key bootstrap'" \
    "sudo docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod tenant create --tenant ${tenant_id} --site-url ${site_url} < /dev/null" \
    "echo '==> Creating post-reset service-mode API key (operator: copy api_key= line into the plugin)'" \
    "sudo docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod create --tenant ${tenant_id} < /dev/null"

  # /ready verification: distinct from /health because reset specifically needs
  # dependency readiness (postgres up, schema migrated, models loaded) before
  # we declare the env operable.
  local verify_cmd="curl -fsS --max-time 30 ${ready_url}"

  if [[ "${ACX_RESET_DRY_RUN:-0}" == "1" ]]; then
    log "DRY-RUN: would invoke ssh ${SSH_TARGET} with the following remote command:"
    printf '%s\n' "${remote_cmd}"
    log "DRY-RUN: would then verify readiness:"
    printf '%s\n' "${verify_cmd}"
    log "DRY-RUN: would then run post-reset bootstrap on ${SSH_TARGET}:"
    printf '%s\n' "${bootstrap_cmd}"
    log "DRY-RUN: no SSH session opened; no remote state mutated"
    return 0
  fi

  preflight_ssh
  log "Executing reset on ${SSH_TARGET}"
  ssh "${SSH_TARGET}" "bash -s" <<<"${remote_cmd}"

  log "Verifying readiness at ${ready_url}"
  # Brief settle window: systemd start is async; the unit may need a few seconds
  # before postgres + the API report ready. The bootstrap must wait for /ready
  # because `docker compose exec api` requires the api container to be up.
  local attempts=0
  until eval "${verify_cmd}"; do
    attempts=$((attempts + 1))
    if (( attempts >= 6 )); then
      fail "Readiness check failed after ${attempts} attempts at ${ready_url}"
    fi
    log "Readiness not yet reported (attempt ${attempts}/6); retrying in 5s"
    sleep 5
  done

  log "Running post-reset bootstrap on ${SSH_TARGET} (tenant create + key create)"
  ssh "${SSH_TARGET}" "bash -s" <<<"${bootstrap_cmd}"

  log "Reset complete. ${ready_url} returned ready and a fresh service-mode API key was printed above."
}

#---------------------------------------------------------------- dispatch
cmd="${1:-}"; shift || true
case "$cmd" in
  build)        do_build "${1:-dev}" ;;
  build-remote) do_build_remote "${1:-dev}" ;;
  deploy)       [[ -n "${1:-}" ]] || fail "deploy requires <env>"; do_deploy "$1" ;;
  promote)      [[ -n "${1:-}" && -n "${2:-}" ]] || fail "promote requires <from-env> <to-env>"; do_promote "$1" "$2" ;;
  reset)        [[ -n "${1:-}" ]] || fail "reset requires <env> (dev|staging|prod)"; do_reset "$1" ;;
  verify)       do_verify "${1:-dev}" ;;
  status)       do_status ;;
  ""|-h|--help|help) sed -n '2,40p' "$0" ;;
  *) fail "Unknown command: ${cmd}. Run '$0 help'." ;;
esac
