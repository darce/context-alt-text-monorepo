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
#   reset          <env>              Destructive: stop unit, clear env Postgres state, restart, verify
#                                       /ready, run post-reset bootstrap (tenant + api_key creation).
#                                       Requires CONFIRM_REMOTE_RESET=RESET and ACX_RESET_SITE_URL.
#                                       'reset prod' also requires CONFIRM=PROMOTE.
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
#   ACX_CONVERGE_RUNTIME     default 1: 'deploy' converges the deployed compose+unit with the repo
#                              before restart. Set 0 for an image-only hotfix restart. Use
#                              'deploy <env> --check' for a read-only drift report (no mutation).
#   ACX_BOOT_SMOKE           default 1: 'deploy' boots the freshly-built :SHA in a throwaway
#                              container (import smoke + /health probe) before promoting/restarting,
#                              aborting on failure with prod untouched. Set 0 to bypass.
#   CONFIRM                  required for prod actions: CONFIRM=PROMOTE (applies to deploy prod and promote * prod)
#
# Reset-specific environment overrides (see do_reset()):
#   ACX_RESET_SITE_URL       REQUIRED for reset. WordPress site URL the plugin will hit
#                              (e.g. http://localhost:10010 for LocalWP). The bootstrap derives the
#                              per-site tenant UUID from this value via
#                              scripts/deploy/_derive_tenant_id.py (mirror of
#                              TenantIdentity::derive_from_site_url()). If the URL does
#                              not match the plugin's site URL, recognition requests fail
#                              with 403 tenant mismatch.
#   ACX_RESET_TENANT_ID      Optional explicit override. Skips per-site derivation; rare.
#   ACX_RESET_DRY_RUN        set to 1 to print the reset plan and exit without executing.
#   CONFIRM_REMOTE_RESET     required for reset: CONFIRM_REMOTE_RESET=RESET (fail-closed gate).
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
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
# Push a single fully-qualified image ref, honoring local vs remote-build mode.
_push_ref() {
  local ref="$1"
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    ssh "${SSH_TARGET}" "docker push ${ref}"
  else
    docker push "${ref}"
  fi
}

# Push the immutable :SHA tag. Done BEFORE the boot smoke so the candidate is
# fetchable for the smoke without promoting the env tag (:latest) yet.
do_push_sha() {
  local sha; sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  if [[ "${REMOTE_BUILD}" == "1" ]]; then preflight_remote_ocir_auth; else preflight_ocir_auth; fi
  log "Pushing ${IMAGE_BASE}:${sha:0:8}"
  _push_ref "${IMAGE_BASE}:${sha}"
}

# Promote the env tag (e.g. :latest for prod). Called ONLY after the boot smoke
# passes, so a bad image never poisons the env tag in OCIR.
do_push_tag() {
  local tag="$1"
  log "Promoting ${IMAGE_BASE}:${tag} in OCIR"
  _push_ref "${IMAGE_BASE}:${tag}"
}

# Shared pre-restart safety gate for <env> on candidate <image>: preserve a
# rollback tag, boot-smoke the candidate (abort on failure), converge compose+
# unit. Used by both do_deploy and do_promote so the prod path is uniform.
promote_gate() {
  local env="$1" image="$2"
  # Rollback tag is non-blocking and must exist even when the smoke is
  # bypassed (ACX_BOOT_SMOKE=0) — it is the recovery path for exactly the
  # deploys risky enough to bypass the gate.
  preserve_rollback_tag "$env"
  if [[ "${ACX_BOOT_SMOKE:-1}" == "1" ]]; then
    if ! do_boot_smoke "$env" "$image"; then
      fail "Pre-promote boot smoke failed for ${env} (${image}); prod left on the old image (no restart). Fix the build and re-run, or set ACX_BOOT_SMOKE=0 to bypass."
    fi
  else
    warn "ACX_BOOT_SMOKE=0: skipping pre-promote boot smoke"
  fi

  if [[ "${ACX_CONVERGE_RUNTIME:-1}" == "1" ]]; then
    converge_runtime "$env"
  else
    warn "ACX_CONVERGE_RUNTIME=0: skipping compose+unit convergence (image-only restart)"
  fi
}

env_to_compose_files() {
  case "$1" in
    prod)        echo "-f docker-compose.env.yml -f docker-compose.admin.yml" ;;
    dev|staging) echo "-f docker-compose.env.yml" ;;
    *)           fail "Unknown env: $1" ;;
  esac
}

# Render the systemd unit for <env> from the checked-in template to stdout.
render_unit() {
  local env="$1" compose_files
  compose_files="$(env_to_compose_files "$env")"
  sed -e "s/{{ENV}}/${env}/g" -e "s|{{COMPOSE_FILES}}|${compose_files}|g" \
    "${SERVICE_DIR}/systemd/acx-env.service.template"
}

# Converge the deployed compose file(s) + systemd unit with the repo *before*
# the image restart, so drift (missing volume/env/overlay) cannot reach a live
# prod. Backs up the prior compose/unit on the VM first. The Caddy edge is
# deliberately not reshipped here (E15-29 hazard: a Caddy restart can drop it
# off acx-demo-net); it stays owned by sync-compose.sh / sync-demo.sh.
converge_runtime() {
  local env="$1" remote_dir unit
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  log "Converging compose + unit for ${env} on ${SSH_TARGET} (edge proxy not reshipped)"
  ssh "${SSH_TARGET}" "cp -f '${remote_dir}/docker-compose.env.yml' '${remote_dir}/docker-compose.env.yml.bak' 2>/dev/null || true; sudo cp -f '/etc/systemd/system/${unit}.service' '/etc/systemd/system/${unit}.service.bak' 2>/dev/null || true"
  scp "${SERVICE_DIR}/docker-compose.env.yml" "${SSH_TARGET}:${remote_dir}/docker-compose.env.yml"
  if [[ "$env" == "prod" ]]; then
    # Back up the admin overlay too so a bad overlay is restorable from *.bak.
    ssh "${SSH_TARGET}" "cp -f '${remote_dir}/docker-compose.admin.yml' '${remote_dir}/docker-compose.admin.yml.bak' 2>/dev/null || true"
    scp "${SERVICE_DIR}/docker-compose.admin.yml" "${SSH_TARGET}:${remote_dir}/docker-compose.admin.yml"
  fi
  render_unit "$env" | ssh "${SSH_TARGET}" "cat > '/tmp/${unit}.service' && sudo cp '/tmp/${unit}.service' '/etc/systemd/system/${unit}.service' && rm -f '/tmp/${unit}.service' && sudo systemctl daemon-reload"
  log "Runtime converged for ${env} (compose + unit match repo)"
}

# Read-only drift gate: diff the deployed compose/unit against the repo and exit
# non-zero on any drift, without mutating the VM. Operator triage for `--check`.
converge_check() {
  local env="$1" remote_dir unit drift=0 rendered
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  log "Checking runtime drift for ${env} on ${SSH_TARGET} (read-only)"
  if ! ssh "${SSH_TARGET}" "cat '${remote_dir}/docker-compose.env.yml' 2>/dev/null" \
       | diff -u - "${SERVICE_DIR}/docker-compose.env.yml"; then
    warn "drift: docker-compose.env.yml on ${env} differs from repo (or is missing)"; drift=1
  fi
  if [[ "$env" == "prod" ]]; then
    if ! ssh "${SSH_TARGET}" "cat '${remote_dir}/docker-compose.admin.yml' 2>/dev/null" \
         | diff -u - "${SERVICE_DIR}/docker-compose.admin.yml"; then
      warn "drift: docker-compose.admin.yml on ${env} differs from repo (or is missing)"; drift=1
    fi
  fi
  rendered="$(render_unit "$env")"
  if ! ssh "${SSH_TARGET}" "cat '/etc/systemd/system/${unit}.service' 2>/dev/null" \
       | diff -u - <(printf '%s\n' "$rendered"); then
    warn "drift: ${unit}.service on ${env} differs from repo template (or is missing)"; drift=1
  fi
  if (( drift )); then
    fail "runtime drift detected for ${env}; run '$0 deploy ${env}' to converge"
  fi
  log "no runtime drift for ${env} (compose + unit match repo)"
}

# Formalize the manual E15-29 rollback step: before a new promote, tag the
# currently-promoted image as :rollback-<id> so a bad deploy can be retagged
# back to the previous good image. Best-effort — never blocks the deploy.
preserve_rollback_tag() {
  local env="$1" env_tag prev_id
  env_tag="$(env_to_tag "$env")"
  # `|| true`: a missing image makes the pipeline exit non-zero; without this,
  # set -e would abort the whole deploy on a first deploy / pruned image.
  prev_id="$(ssh "${SSH_TARGET}" "docker image inspect --format '{{.Id}}' ${IMAGE_BASE}:${env_tag} 2>/dev/null" | sed 's/^sha256://' | cut -c1-12)" || true
  if [[ -n "${prev_id}" ]]; then
    if ssh "${SSH_TARGET}" "docker tag ${IMAGE_BASE}:${env_tag} ${IMAGE_BASE}:rollback-${prev_id}"; then
      log "Preserved rollback tag ${IMAGE_BASE}:rollback-${prev_id}"
    else
      warn "could not create rollback tag for ${env} (continuing)"
    fi
  else
    warn "no current ${IMAGE_BASE}:${env_tag} on ${SSH_TARGET} to preserve as rollback (first deploy?)"
  fi
}

# Pre-promote boot smoke: boot the freshly-built :SHA in a throwaway container on
# the VM *before* :latest is restarted, so a bad image (missing package, import
# error, failed boot) aborts the deploy with prod still serving the old image.
# Returns non-zero on any smoke failure. Two gates: (1) a network-free import
# smoke that catches ModuleNotFoundError-class packaging omissions; (2) a
# short-lived full-boot /health probe on an ephemeral port against the env net.
do_boot_smoke() {
  local env="$1" image="$2" remote_dir
  remote_dir="$(env_to_remote_dir "$env")"
  log "Pre-promote boot smoke: ${image} on ${SSH_TARGET} (env=${env})"
  # Gate 1 — network-free import smoke. Catches the ModuleNotFoundError-class
  # packaging omissions (the scene/ incident) without touching the DB.
  if ! ssh "${SSH_TARGET}" "docker pull ${image} >/dev/null && docker run --rm --entrypoint python ${image} -c 'import api.main'"; then
    warn "boot smoke: 'import api.main' failed on ${image} (packaging/import error)"
    return 1
  fi
  # Gate 2 — full-boot /health probe in a throwaway container. The entrypoint is
  # overridden to run uvicorn ONLY (skipping the image's migrate + verify boot
  # steps), so the smoke never mutates the live prod schema — it proves the app
  # boots and /health answers, then is torn down. Network name is read (not
  # sourced) from the deployed .env so a docker-only env line cannot abort it.
  if ! ssh "${SSH_TARGET}" "bash -s ${env} ${image} ${remote_dir}" <<'SMOKE'
set -euo pipefail
env="$1"; image="$2"; remote_dir="$3"
net="$(grep -E '^ACX_NETWORK_NAME=' "${remote_dir}/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"' " || true)"
net="${net:-acx-${env}-net}"
name="acx-smoke-${env}-$$"
docker run -d --rm --name "$name" --env-file "${remote_dir}/.env" --network "$net" -P \
  --entrypoint sh "$image" -c 'cd /app && exec uvicorn api.main:app --host 0.0.0.0 --port 8000' >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
port="$(docker port "$name" 8000/tcp | head -1 | sed 's/.*://')"
for _ in $(seq 1 12); do
  if curl -fsS "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then echo "smoke health OK"; exit 0; fi
  sleep 2
done
echo "smoke health FAILED after 24s" >&2
exit 1
SMOKE
  then
    warn "boot smoke: /health never came up for ${image}"
    return 1
  fi
  log "Boot smoke passed for ${image}"
}

do_restart() {
  local env="$1"
  local remote_dir unit compose_files
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  compose_files="$(env_to_compose_files "$env")"
  log "Pulling latest image + restarting ${unit} on ${SSH_TARGET}"
  ssh "${SSH_TARGET}" "cd ${remote_dir} && docker compose ${compose_files} pull api && sudo systemctl restart ${unit}"
}

#---------------------------------------------------------------- deploy
do_deploy() {
  local env="$1"; shift || true
  local check=0
  [[ "${1:-}" == "--check" ]] && check=1

  # Read-only drift check bypasses build/push and the promote confirmation.
  if (( check )); then
    env_to_remote_dir "$env" >/dev/null   # validate env before any network
    preflight_ssh
    converge_check "$env"
    return 0
  fi

  local tag sha
  tag="$(env_to_tag "$env")"
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"

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

  # Push :SHA first, gate on the boot smoke, and only then promote the env tag
  # (e.g. :latest) so a failed smoke never poisons the promotion tag in OCIR.
  do_push_sha
  promote_gate "$env" "${IMAGE_BASE}:${sha}"
  do_push_tag "$tag"

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

  # Pull the source image so the boot smoke can run it before it is promoted.
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    log "Mode: remote-retag (${SSH_TARGET})"
    preflight_remote_docker
    preflight_remote_ocir_auth
    log "Pulling source image ${IMAGE_BASE}:${from_tag} on ${SSH_TARGET}"
    ssh "${SSH_TARGET}" "docker pull ${IMAGE_BASE}:${from_tag}"
  else
    preflight_docker
    preflight_ocir_auth
    log "Pulling source image ${IMAGE_BASE}:${from_tag}"
    docker pull "${IMAGE_BASE}:${from_tag}"
  fi

  # Same safety gate as deploy: boot-smoke the source image + converge compose/
  # unit + preserve rollback BEFORE the source is retagged over the env tag.
  promote_gate "$to_env" "${IMAGE_BASE}:${from_tag}"

  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    log "Tagging ${from_tag} -> ${to_tag} on ${SSH_TARGET}"
    ssh "${SSH_TARGET}" "docker tag ${IMAGE_BASE}:${from_tag} ${IMAGE_BASE}:${to_tag} && docker push ${IMAGE_BASE}:${to_tag}"
  else
    log "Tagging ${from_tag} -> ${to_tag}"
    docker tag "${IMAGE_BASE}:${from_tag}" "${IMAGE_BASE}:${to_tag}"
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
  # E15-12-BR-06: the plugin sends X-Tenant-ID = TenantIdentity::derive_from_site_url()
  # on every authenticated recognition request, where site_url is the WordPress
  # site URL — not the recognition API URL. The bootstrap MUST bind the new
  # service-mode API key to that same per-site tenant UUID, otherwise the
  # backend rejects the plugin's first authenticated request with HTTP 403
  # 'tenant mismatch' and the operator is left thinking reset failed.
  #
  # Operator contract:
  #   - ACX_RESET_SITE_URL is required and must be the WordPress site URL the
  #     plugin will hit (e.g. http://localhost:10010 for a LocalWP site).
  #     There is no safe default: the previous defaults were the recognition
  #     API URLs, which are NOT what the plugin sends as its origin tenant.
  #   - ACX_RESET_TENANT_ID is optional. When unset, the bootstrap derives the
  #     UUID from ACX_RESET_SITE_URL via scripts/deploy/_derive_tenant_id.py
  #     (the Python mirror of TenantIdentity::derive_from_site_url()). When
  #     set, the explicit value wins — escape hatch for non-derived tenants.
  if [[ -z "${ACX_RESET_SITE_URL:-}" ]]; then
    fail "ACX_RESET_SITE_URL must be set to the WordPress site URL the plugin will hit (e.g. http://localhost:10010 for LocalWP, or https://staging.altcontext.com). The bootstrap derives the per-site tenant UUID from this value to match the plugin's TenantIdentity::derive_from_site_url() (E15-12-BR-06). Set ACX_RESET_TENANT_ID as well only if you need to override derivation for a custom tenant."
  fi
  local site_url="${ACX_RESET_SITE_URL}"
  local tenant_id
  if [[ -n "${ACX_RESET_TENANT_ID:-}" ]]; then
    tenant_id="${ACX_RESET_TENANT_ID}"
  else
    tenant_id="$(python3 "${SCRIPT_DIR}/_derive_tenant_id.py" "${site_url}")"
  fi
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
# Skip dispatch when the script is sourced (e.g. by tests calling individual
# functions), run it only on direct execution.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  cmd="${1:-}"; shift || true
  case "$cmd" in
    build)        do_build "${1:-dev}" ;;
    build-remote) do_build_remote "${1:-dev}" ;;
    deploy)       [[ -n "${1:-}" ]] || fail "deploy requires <env>"; do_deploy "$@" ;;
    promote)      [[ -n "${1:-}" && -n "${2:-}" ]] || fail "promote requires <from-env> <to-env>"; do_promote "$1" "$2" ;;
    reset)        [[ -n "${1:-}" ]] || fail "reset requires <env> (dev|staging|prod)"; do_reset "$1" ;;
    verify)       do_verify "${1:-dev}" ;;
    status)       do_status ;;
    ""|-h|--help|help) sed -n '2,40p' "$0" ;;
    *) fail "Unknown command: ${cmd}. Run '$0 help'." ;;
  esac
fi
