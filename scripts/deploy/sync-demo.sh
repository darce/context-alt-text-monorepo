#!/usr/bin/env bash
# Sync the demo WordPress stack after verifying the shared Caddy edge.
# The recognition deploy owns edge convergence; this deploy only probes it.
# When PLUGIN_ZIP is unset, freshness-gates the newest dist/alt-context-*.zip and
# runs bootstrap-wp.sh after the stack is healthy. An explicitly empty PLUGIN_ZIP
# means no artifact: skip the plugin rsync, skip bootstrap, leave BOOTSTRAP_RAN=0.
# Explicit non-empty PLUGIN_ZIP pins a reviewed artifact without freshness checks.
#
# Usage:
#   scripts/deploy/sync-demo.sh
#   PLUGIN_ZIP=dist/alt-context-1.2.3.zip scripts/deploy/sync-demo.sh
#   PLUGIN_ZIP= scripts/deploy/sync-demo.sh
#   OCI_HOST=<host> OCI_USER=ubuntu scripts/deploy/sync-demo.sh

set -euo pipefail

# Public port 22 is closed; host reachable via Tailscale SSH only.
OCI_HOST="${OCI_HOST:-acx-backend.tail1a44b8.ts.net}"
OCI_USER="${OCI_USER:-ubuntu}"

DEMO_COMPOSE_SRC="${DEMO_COMPOSE_SRC:-apps/prototype-description-service/docker-compose.demo.yml}"
CADDYFILE_SRC="${CADDYFILE_SRC:-apps/prototype-description-service/Caddyfile}"
CADDY_COMPOSE_SRC="${CADDY_COMPOSE_SRC:-apps/prototype-description-service/docker-compose.caddy.yml}"
SYSTEMD_SRC="${SYSTEMD_SRC:-apps/prototype-description-service/systemd/acx-demo.service}"
ENV_EXAMPLE_SRC="${ENV_EXAMPLE_SRC:-infra/oci/demo/.env.example}"
BOOTSTRAP_SRC="${BOOTSTRAP_SRC:-infra/oci/demo/bootstrap-wp.sh}"
DESCRIBE_GATE_SRC="${DESCRIBE_GATE_SRC:-infra/oci/demo/lib/describe-gate.sh}"
GPU_ENV_CONTRACT_SRC="${GPU_ENV_CONTRACT_SRC:-scripts/deploy/lib/gpu-env-contract.sh}"
GPU_PREFLIGHT_SRC="${GPU_PREFLIGHT_SRC:-scripts/deploy/preflight-gpu-env.sh}"
SEED_IMPORT_SRC="${SEED_IMPORT_SRC:-infra/oci/demo/seed/import.sh}"
SEED_RIGHTS_DIR="${SEED_RIGHTS_DIR:-infra/oci/demo/seed}"
SEED_MEDIA_DIR="${SEED_MEDIA_DIR:-infra/oci/demo/seed/media}"

REMOTE_DEMO_DIR="/opt/acx-backend/demo"
REMOTE_BACKEND_DIR="/opt/acx-backend"
REMOTE_PLUGIN_ZIP="/tmp/alt-context.zip"
REMOTE_GPU_PREFLIGHT_DIR="/tmp/acx-gpu-preflight"
DESCRIBE_CHUNK_VALUE="${ACX_DEMO_DESCRIBE_CHUNK:-10}"
DESCRIBE_MAX_VALUE="${ACX_DEMO_DESCRIBE_MAX:-100}"
SSH="ssh ${OCI_USER}@${OCI_HOST}"
SCP="scp"

# Quote operator-provided describe bounds before embedding them in the remote
# bootstrap heredoc. The bootstrap validates the values semantically; this
# helper keeps a malformed value from becoming remote shell syntax first.
shell_quote() {
  local value="$1"
  value=${value//\'/\'\\\'\'}
  printf "'%s'" "$value"
}

if [[ -z ${PLUGIN_ZIP+x} ]]; then
  PLUGIN_ZIP="$(ls -t dist/alt-context-*.zip 2>/dev/null | head -1 || true)"
  if [[ -n "${PLUGIN_ZIP}" ]]; then
    ACX_BUILD_SOURCE_STAMP="${ACX_BUILD_SOURCE_STAMP:-apps/prototype-wp-alt-context/public/assets/dist/.acx-build-source.sha256}"
    PACKAGE_PLUGIN_SCRIPT="${PACKAGE_PLUGIN_SCRIPT:-apps/prototype-wp-alt-context/scripts/release/package-plugin.sh}"
    remediation="Rerun bash apps/prototype-wp-alt-context/scripts/release/package-plugin.sh, or pin a reviewed artifact with PLUGIN_ZIP=<path>."
    if [[ ! -f "${ACX_BUILD_SOURCE_STAMP}" ]]; then
      echo "ERROR: Missing build source stamp: ${ACX_BUILD_SOURCE_STAMP}. ${remediation}" >&2
      exit 3
    fi
    if ! expected_digest="$(bash "${PACKAGE_PLUGIN_SCRIPT}" --print-source-digest 2>/dev/null)"; then
      echo "ERROR: Cannot compute build source digest with ${PACKAGE_PLUGIN_SCRIPT}. ${remediation}" >&2
      exit 3
    fi
    found_digest="$(<"${ACX_BUILD_SOURCE_STAMP}")"
    if [[ -z "${expected_digest}" || "${expected_digest}" != "${found_digest}" ]]; then
      echo "ERROR: Build source stamp digest mismatch: expected ${expected_digest}, found ${found_digest}. ${remediation}" >&2
      exit 3
    fi
    if [[ "${PLUGIN_ZIP}" -ot "${ACX_BUILD_SOURCE_STAMP}" ]]; then
      echo "ERROR: Plugin ZIP ${PLUGIN_ZIP} is older than stamp ${ACX_BUILD_SOURCE_STAMP}. ${remediation}" >&2
      exit 3
    fi
    echo "==> Auto-discovered plugin artifact: ${PLUGIN_ZIP}"
    echo "==> Plugin artifact freshness verified against build source stamp"
  else
    echo "==> No plugin artifact auto-discovered (no dist/alt-context-*.zip)"
  fi
elif [[ -z "${PLUGIN_ZIP}" ]]; then
  echo "==> PLUGIN_ZIP is empty — deploying without a plugin artifact"
fi

# Resolved early and preflighted with the other sources: discovering it missing
# at the final smoke step would leave the demo deployment unsmoked.
# Remote smoke heredoc concatenation order (later definition wins):
#   1. describe-gate.sh — ACX_TRUSTED_DESCRIBE_PROFILES + is_trusted_describe_profile
#      (only definition site). Also carries a VM-self-contained copy of
#      normalize_fixture_sample / fixture_sample_is_denied.
#   2. fixture-denylist.sh — canonical denylist helpers overwrite the
#      describe-gate copies. Canonical wins: this is Gate B's source of truth;
#      describe-gate's copies exist so bootstrap-wp.sh can SCP a single file.
#   3. smoke-gate.sh — classifiers that AND identity with the denylist.
SMOKE_GATE_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/smoke-gate.sh"
FIXTURE_DENYLIST_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/fixture-denylist.sh"

for src in "$DEMO_COMPOSE_SRC" "$CADDYFILE_SRC" "$CADDY_COMPOSE_SRC" "$SYSTEMD_SRC" "$ENV_EXAMPLE_SRC" "$BOOTSTRAP_SRC" "$DESCRIBE_GATE_SRC" "$GPU_ENV_CONTRACT_SRC" "$SEED_IMPORT_SRC" "$SEED_RIGHTS_DIR/clustering-rights.tsv" "$SEED_RIGHTS_DIR/guided-rights.tsv" "$SMOKE_GATE_LIB" "$FIXTURE_DENYLIST_LIB"; do
  if [[ ! -f "$src" ]]; then
    echo "ERROR: source file not found: $src" >&2
    exit 2
  fi
done

run_gpu_env_preflight() {
  [[ "${ACX_DEMO_GPU_PREFLIGHT:-0}" == "1" ]] || return 0
  for src in "$GPU_PREFLIGHT_SRC" "$DESCRIBE_GATE_SRC"; do
    if [[ ! -f "$src" ]]; then
      echo "ERROR: GPU environment preflight source file not found: $src" >&2
      return 2
    fi
  done

  echo "==> Run GPU environment preflight before bringing up the demo stack"
  # The following scp commands run as OCI_USER. Create both temporary
  # directories as that user so a clean VM does not leave a root-only staging
  # tree that blocks the upload before the preflight can run.
  $SSH "install -d -m 700 '${REMOTE_GPU_PREFLIGHT_DIR}/lib'"
  $SCP "$GPU_PREFLIGHT_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_GPU_PREFLIGHT_DIR}/preflight-gpu-env.sh"
  $SCP "$GPU_ENV_CONTRACT_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_GPU_PREFLIGHT_DIR}/lib/gpu-env-contract.sh"
  $SCP "$DESCRIBE_GATE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_GPU_PREFLIGHT_DIR}/lib/describe-gate.sh"
  if ! $SSH "sudo chmod 700 '${REMOTE_GPU_PREFLIGHT_DIR}/preflight-gpu-env.sh' && sudo chmod 644 '${REMOTE_GPU_PREFLIGHT_DIR}/lib/gpu-env-contract.sh' '${REMOTE_GPU_PREFLIGHT_DIR}/lib/describe-gate.sh' && sudo '${REMOTE_GPU_PREFLIGHT_DIR}/preflight-gpu-env.sh' --check-reaper '${REMOTE_BACKEND_DIR}/prod/.env' '${REMOTE_DEMO_DIR}/secrets/.env'"; then
    echo "ERROR: GPU environment preflight failed; demo deploy aborted (exit 4)." >&2
    return 4
  fi
  echo "==> GPU environment preflight passed"
  $SSH "sudo rm -f '${REMOTE_GPU_PREFLIGHT_DIR}/preflight-gpu-env.sh' '${REMOTE_GPU_PREFLIGHT_DIR}/lib/gpu-env-contract.sh' '${REMOTE_GPU_PREFLIGHT_DIR}/lib/describe-gate.sh' && sudo rmdir '${REMOTE_GPU_PREFLIGHT_DIR}/lib' '${REMOTE_GPU_PREFLIGHT_DIR}'"
}

if run_gpu_env_preflight; then
  :
else
  preflight_status=$?
  exit "$preflight_status"
fi


# Shared-edge ABI is owned by recognition/app-portal; recognition-service.sh is
# the only edge writer. This deploy streams the frozen helper plus a read-only
# program and refuses unless the live edge equals what that writer installs.
# Decoded inputs exist only under the remote /tmp, never in /opt/acx-backend.
# Any generic env converges the whole edge; the probe selects Aura networks as
# that env would, so the printed command and the comparison cannot disagree.
EDGE_CONVERGE_ENV="prod"

# Bound one remote call on the local clock as well: the remote `timeout` cannot
# help when the transport itself stalls. bash 3.2 has no BASHPID or wait -n.
run_with_local_deadline() {
  local limit="$1" pid started state
  shift
  # Without job control `cmd &` reads /dev/null; keep the caller's here-string.
  "$@" <&0 &
  pid=$!
  started=$SECONDS
  while kill -0 "$pid" 2>/dev/null; do
    state="$(ps -o stat= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
    [[ "$state" != Z* ]] || break
    if ((SECONDS - started >= limit)); then
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      echo "ERROR: shared edge probe exceeded ${limit}s on the local clock; edge state UNKNOWN" >&2
      return 124
    fi
    sleep 0.2
  done
  wait "$pid"
}

# Remote program: $1 budget seconds, $2 converge env, $3/$4 base64 Caddyfile and
# Compose. A function, not "$(cat <<...)", so bash 3.2 parses the heredoc.
edge_probe_program() {
  cat -- "$(dirname "${BASH_SOURCE[0]}")/lib/shared-edge.sh" || return 2
  cat <<'EDGE_PROBE'
set -euo pipefail
budget="$1"
converge_env="$2"
[[ "$budget" =~ ^[1-9][0-9]{0,2}$ && "$budget" -le 600 ]] || { echo 'ERROR: shared edge probe budget must be 1..600 seconds' >&2; exit 2; }
[[ "$converge_env" =~ ^(dev|staging|prod)$ ]] || { echo 'ERROR: shared edge probe needs a generic converge env' >&2; exit 2; }
edge_dir=/opt/acx-backend
live="$edge_dir/Caddyfile"
base="$edge_dir/docker-compose.caddy.yml"
overlay="$edge_dir/app/docker-compose.app.yml"
journal="$edge_dir/app/activation.journal"
handle=""
scratch=""
reaper=""
refuse() { echo "ERROR: shared edge drift: $1" >&2; exit 1; }
# Unknown is neither converged nor drift: exit 3, never the drift status 1.
unknown() { echo "ERROR: shared edge probe could not $1 (rc $2); edge state UNKNOWN" >&2; exit 3; }

# One shared budget. The outer `timeout -k 5` signals only its own process
# group, but edge_bounded_run starts every Docker read under a nested `timeout`
# that leads a new group, so a stalled read would outlive the deadline and keep
# this session open. Each helper operation gets only what is left, and the
# reaper kills those nested groups 2 s before the outer deadline.
stop_at=$((SECONDS + budget - 2))
spend() {
  EDGE_OP_DEADLINE=$((stop_at - SECONDS))
  ((EDGE_OP_DEADLINE >= 1)) || {
    echo "ERROR: shared edge probe ran out of its ${budget}s budget; edge state UNKNOWN" >&2
    exit 124
  }
}
reap_nested() {
  local own groups group
  own="$(ps -o pgid= -p "$$" | tr -d ' ')" || return 0
  [[ "$own" =~ ^[1-9][0-9]*$ ]] || return 0
  groups="$(ps -e -o pid= -o ppid= -o pgid= | awk -v root="$$" -v own="$own" '
    { parent[$1] = $2; group[$1] = $3 }
    END {
      for (pid in parent) {
        up = pid
        for (hops = 0; hops < 64 && up != root && (up in parent); hops++) up = parent[up]
        if (up == root && group[pid] != own && group[pid] > 1) print group[pid]
      }
    }' | sort -u)" || return 0
  for group in $groups; do kill -KILL -- "-$group" 2>/dev/null || true; done
}
(
  while ((SECONDS < stop_at)); do sleep 0.2; done
  reap_nested
) </dev/null >/dev/null 2>&1 &
reaper=$!
cleanup() {
  local rc=$?
  kill "$reaper" 2>/dev/null || true
  if [[ -n "$scratch" ]]; then rm -rf -- "$scratch"; fi
  # Cleanup removes at most one private file; keep it inside the kill grace.
  EDGE_OP_DEADLINE=1
  edge_compose_cleanup || rc=1
  if [[ -n "$handle" ]]; then edge_lock_release "$handle" 5 >/dev/null || rc=1; fi
  exit "$rc"
}
trap cleanup EXIT

spend
if handle="$(edge_lock_acquire "$edge_dir/app/activation.journal.lock" 0 "$((budget + 10))" 0)"; then
  :
else
  rc=$?
  handle=""
  if [[ "$rc" == 75 ]]; then echo 'ERROR: shared edge drift: lock_busy' >&2; fi
  exit "$rc"
fi
# Same admission as the writer probe: a pending journal is an unfinished
# activation or recovery, so the edge is not settled.
if [[ -e "$journal" || -L "$journal" ]]; then
  echo 'ERROR: shared edge drift: lock_busy (pending activation journal; recovery required)' >&2
  exit 75
fi
scratch="$(mktemp -d "${TMPDIR:-/tmp}/sync-demo-edge.XXXXXX")"
printf '%s' "$3" | base64 -d >"$scratch/Caddyfile.repo" || unknown "decode the repository Caddyfile" "$?"
printf '%s' "$4" | base64 -d >"$scratch/compose.repo.yml" || unknown "decode the repository Compose file" "$?"

edge_effective_caddyfile "$scratch/Caddyfile.repo" "$live" >"$scratch/Caddyfile" || refuse caddyfile
cmp -s -- "$scratch/Caddyfile" "$live" || refuse caddyfile

# The writer (recognition-service.sh edge_desired) installs the canonical JSON
# of the resolved Compose model, with only absent unselected Aura networks
# dropped, and its probe compares models. Compare the same models here.
[[ -f "$base" && ! -L "$base" ]] || refuse compose
spend
model="$(edge_bounded_run docker compose --project-directory "$edge_dir" -f "$scratch/compose.repo.yml" config --format json)" ||
  unknown "resolve the repository Compose model" "$?"
spend
inventory="$(edge_bounded_run docker network ls --format '{{.Name}}')" || unknown "read the Docker network inventory" "$?"
python3 -c '
import json,re,sys
model,inventory,env=sys.argv[1:]
d=json.loads(model); present=set(inventory.splitlines())
if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", n) for n in present): raise SystemExit(2)
nets=d["networks"]; service=d["services"]["caddy"]["networks"]
selected="acx-"+env+"-net"
for key in list(service):
    name=nets[key].get("name",key)
    if re.fullmatch(r"acx-(dev|staging|prod)-auraface-net",name) and name not in present and name != selected:
        if isinstance(service,list): service.remove(key)
        else: del service[key]
        del nets[key]
print(json.dumps(d,sort_keys=True,separators=(",",":")))' "$model" "$inventory" "$converge_env" >"$scratch/desired.json" ||
  unknown "select the desired Compose model" "$?"
spend
current="$(edge_bounded_run docker compose --project-directory "$edge_dir" -f "$base" config --format json)" ||
  unknown "resolve the live Compose model" "$?"
canonical="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]),sort_keys=True,separators=(",",":")))' "$current")" ||
  unknown "normalize the live Compose model" "$?"
[[ "$canonical" == "$(cat -- "$scratch/desired.json")" ]] || refuse compose

spend
edge_compose_args "$base" "$overlay" || unknown "select the effective edge generation" "$?"
spend
names="$(edge_required_networks "$base" "$overlay")" || unknown "resolve the required caddy networks" "$?"
spend
cid="$(edge_bounded_run docker compose "${EDGE_COMPOSE_ARGV[@]}" ps -q caddy)" || unknown "find the caddy container" "$?"
[[ "$cid" =~ ^[a-f0-9]{12,64}$ ]] || refuse 'network:acx-demo-net (caddy container absent or ambiguous)'
spend
networks="$(edge_bounded_run docker inspect -f '{{json .NetworkSettings.Networks}}' "$cid")" ||
  unknown "inspect the caddy container" "$?"
while IFS= read -r name; do
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if isinstance(d,dict) and sys.argv[2] in d else 1)' "$networks" "$name" ||
    refuse "network:$name"
done <<<"$(printf '%s\nacx-demo-net\n' "$names" | LC_ALL=C sort -u)"
# A live hold now proves every read above was serialized with the writers.
edge_lock_check "$handle" 0 || unknown "prove the shared edge lock was held throughout" "$?"
EDGE_PROBE
}

probe_shared_edge() {
  local deadline command caddy64 compose64 program
  deadline="${ACX_REMOTE_COMMAND_TIMEOUT:-120}"
  [[ "$deadline" =~ ^[1-9][0-9]{0,2}$ && "$deadline" -le 600 ]] || {
    echo "ERROR: shared edge deadline must be 1..600 seconds" >&2
    return 2
  }
  [[ -r "$(dirname "${BASH_SOURCE[0]}")/lib/shared-edge.sh" ]] || { echo "ERROR: shared edge helper missing" >&2; return 2; }
  caddy64="$(base64 < "$CADDYFILE_SRC" | tr -d '\n')" || return 2
  compose64="$(base64 < "$CADDY_COMPOSE_SRC" | tr -d '\n')" || return 2
  command="sudo -n timeout -k 5 $deadline bash -s -- $deadline $EDGE_CONVERGE_ENV $(shell_quote "$caddy64") $(shell_quote "$compose64")"
  program="$(edge_probe_program)" || return 2
  # Local bound: 5 s connect + the remote deadline + its 5 s kill grace.
  run_with_local_deadline "$((deadline + 10))" \
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 "${OCI_USER}@${OCI_HOST}" "$command" <<<"$program"
}
if probe_shared_edge; then
  :
else
  edge_status=$?
  echo "ERROR: shared edge probe refused (sudo, transport, deadline, unknown state or drift); no demo changes made." >&2
  echo "Converge: OCI_HOST=$(shell_quote "$OCI_HOST") OCI_USER=$(shell_quote "$OCI_USER") ACX_EDGE_APPLY=1 bash scripts/deploy/recognition-service.sh sync-runtime ${EDGE_CONVERGE_ENV}" >&2
  exit "$edge_status"
fi

# Retain an API baseline before demo mutations to detect collateral regressions.
echo "==> Capture pre-deploy api vhost baseline"
PRE_CODES=$($SSH bash -se <<'EOF'
set -euo pipefail
for host in api.altcontext.com staging.api.altcontext.com dev.api.altcontext.com; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "https://${host}/health" || true)
  [[ -n "$code" && "$code" != "000" ]] || code=000
  printf '%s=%s ' "$host" "$code"
done
EOF
)
echo "    baseline: ${PRE_CODES}"

echo "==> Target host: ${OCI_USER}@${OCI_HOST}"
echo "==> Ensure demo secrets exist at ${REMOTE_DEMO_DIR}/secrets/.env (from ${ENV_EXAMPLE_SRC})"

$SSH "sudo mkdir -p '${REMOTE_DEMO_DIR}/secrets' '${REMOTE_DEMO_DIR}/lib' '${REMOTE_DEMO_DIR}/seed/media' '${REMOTE_BACKEND_DIR}/data/demo-wpdata' '${REMOTE_BACKEND_DIR}/data/demo-dbdata'"
# sudo mkdir leaves root-owned dirs; the scp/ln below run as ${OCI_USER}.
$SSH "sudo chown -R ${OCI_USER}: '${REMOTE_DEMO_DIR}'"

echo "==> Rsync demo compose, bootstrap script, seed import, and env example"
$SCP "$DEMO_COMPOSE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/docker-compose.demo.yml"
$SCP "$BOOTSTRAP_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/bootstrap-wp.sh"
$SCP "$DESCRIBE_GATE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/lib/describe-gate.sh"
$SCP "$GPU_ENV_CONTRACT_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/lib/gpu-env-contract.sh"
$SCP "$SEED_IMPORT_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/seed/import.sh"
$SCP "$SEED_RIGHTS_DIR/clustering-rights.tsv" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/seed/clustering-rights.tsv"
$SCP "$SEED_RIGHTS_DIR/guided-rights.tsv" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/seed/guided-rights.tsv"
$SCP "$ENV_EXAMPLE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/secrets/.env.example"
$SSH "chmod +x '${REMOTE_DEMO_DIR}/bootstrap-wp.sh' '${REMOTE_DEMO_DIR}/seed/import.sh'"

seed_media_files=()
while IFS= read -r f; do seed_media_files+=("$f"); done < <(find "$SEED_MEDIA_DIR" -maxdepth 1 \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) 2>/dev/null)
if ((${#seed_media_files[@]} > 0)); then
  echo "==> Rsync ${#seed_media_files[@]} seed media file(s)"
  $SCP "${seed_media_files[@]}" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/seed/media/"
else
  echo "WARN: no licensed seed media under ${SEED_MEDIA_DIR} — seed/import.sh will refuse to run until media ships" >&2
fi

if [[ -n "${PLUGIN_ZIP}" ]]; then
  echo "==> Rsync plugin package: ${PLUGIN_ZIP} -> ${REMOTE_PLUGIN_ZIP}"
  $SCP "$PLUGIN_ZIP" "${OCI_USER}@${OCI_HOST}:${REMOTE_PLUGIN_ZIP}"
else
  echo "==> No plugin artifact to rsync; skipping bootstrap-wp.sh"
fi

echo "==> Bring up demo stack (acx-demo-net is external — create it out-of-band)"
$SSH bash -se <<EOF
set -euo pipefail
cd '${REMOTE_DEMO_DIR}'
if [[ ! -f secrets/.env ]]; then
  echo "ERROR: ${REMOTE_DEMO_DIR}/secrets/.env missing — copy from secrets/.env.example and populate" >&2
  exit 2
fi
ln -sf secrets/.env .env
docker network inspect acx-demo-net >/dev/null 2>&1 || docker network create acx-demo-net
docker compose -f docker-compose.demo.yml up -d
docker compose -f docker-compose.demo.yml ps
docker network ls | grep acx-demo-net
EOF

if [[ -n "${PLUGIN_ZIP}" ]]; then
  echo "==> Run bootstrap-wp.sh (core install + alt-context plugin)"
  $SSH bash -se <<EOF
set -euo pipefail
cd '${REMOTE_DEMO_DIR}'
ACX_DEMO_DESCRIBE_CHUNK=$(shell_quote "$DESCRIBE_CHUNK_VALUE") \
ACX_DEMO_DESCRIBE_MAX=$(shell_quote "$DESCRIBE_MAX_VALUE") \
PLUGIN_ZIP='${REMOTE_PLUGIN_ZIP}' ./bootstrap-wp.sh
EOF
fi

BOOTSTRAP_RAN=0
FIRST_BURST_COUNT=""
if [[ -n "${PLUGIN_ZIP}" ]]; then
  BOOTSTRAP_RAN=1
  FIRST_BURST_COUNT=$($SSH "cat '${REMOTE_DEMO_DIR}/.acx-describe-first-burst.count' 2>/dev/null" || true)
fi

echo "==> Install/refresh systemd unit (operator enables manually if first install)"
$SCP "$SYSTEMD_SRC" "${OCI_USER}@${OCI_HOST}:/tmp/acx-demo.service"
$SSH "sudo cp /tmp/acx-demo.service /etc/systemd/system/acx-demo.service && sudo systemctl daemon-reload"

# api.* vhosts have no root route (/ -> 404), so probe /health there; the demo
# vhost serves the WP front page at /. Gate semantics (pinned by
# scripts/deploy/tests/test-smoke-gate.sh; classification logic lives in
# scripts/deploy/lib/smoke-gate.sh and is shipped to the VM inline): the deploy
# owns the demo stack, not backend health. 000 after retries FAILs
# (edge/TLS unreachable); an
# api.* HTTP error FAILs only when the pre-deploy baseline was healthy
# (deploy-caused regression), else WARNs; the demo probe follows redirects and
# requires a final 2xx that is not the WP installer (a wiped DB 302->install.php
# answers 200 and is a broken demo, not a healthy one).
# After the front-page probe, a credential-free WP media check asserts demo
# alt-text coverage (>= DEMO_ALT_MIN_COVERAGE_PCT, default 95; operators may
# raise this bar. The default IS the floor: any value below 95 FAILs closed)
# and that published
# captions are not the description-service `seeded` fixture pool. Coverage
# counts only usable alt (classify_alt_text_usable), not placeholder strings.
# DEMO_ALT_GATE_ENFORCE defaults to 1 (a FAIL blocks the deploy). Set it to 0
# to keep the measurement line but print WARN instead of setting smoke_fail
# for overridable sub-gates (population, and coverage only when with_alt>0)
# so a PARTIALLY described demo can ship while the corpus is being filled.
# The hatch was never meant to cover "we described nothing" (with_alt=0) or
# "we cannot count" (non-numeric with_alt); those two cases fail closed even
# when DEMO_ALT_GATE_ENFORCE=0. Population stays overridable: a header/body
# mismatch is a probe limitation, not a content lie. Provenance is never
# overridable: untrusted/absent adapter identity and canned-caption FAILs
# always set smoke_fail, and an empty sample (nothing to certify) is FAIL
# closed, not SKIP.
echo "==> Smoke four vhosts (api.* via /health, demo via / + media alt-text)"
{
  # describe-gate first (trusted profiles), then canonical denylist so its
  # helper copies win the collision, then smoke-gate classifiers.
  cat "$DESCRIBE_GATE_SRC"
  cat "$FIXTURE_DENYLIST_LIB"
  cat "$SMOKE_GATE_LIB"
  printf 'PRE_CODES="%s"\n' "$PRE_CODES"
  printf 'DEMO_ALT_MIN_COVERAGE_PCT="%s"\n' "${DEMO_ALT_MIN_COVERAGE_PCT:-95}"
  printf 'DEMO_ALT_GATE_ENFORCE="%s"\n' "${DEMO_ALT_GATE_ENFORCE:-1}"
  printf 'BOOTSTRAP_RAN="%s"\n' "$BOOTSTRAP_RAN"
  printf 'FIRST_BURST_COUNT="%s"\n' "$FIRST_BURST_COUNT"
  printf 'DESCRIBE_MAX="%s"\n' "${ACX_DEMO_DESCRIBE_MAX:-100}"
  cat <<'EOF'
set -euo pipefail
smoke_fail=0
fetch_final() {
  # -> "final_code final_url" after following redirects
  local out
  out=$(curl -sS -o /dev/null -L --max-redirs 5 --max-time 15 -w '%{http_code} %{url_effective}' "$1" || true)
  [[ -n "${out%% *}" && "${out%% *}" != "000" ]] || out="000 -"
  echo "$out"
}
probe_with_retry() {
  # retry ONLY while unreachable (000): absorbs the Caddy recreate / ACME window
  local url="$1" attempts="${2:-6}" out
  for _ in $(seq 1 "$attempts"); do
    out=$(fetch_final "$url")
    [[ "${out%% *}" != "000" ]] && break
    sleep 5
  done
  echo "$out"
}
pre_code_for() {
  local host="$1" kv
  for kv in $PRE_CODES; do
    [[ "${kv%%=*}" == "$host" ]] && { echo "${kv#*=}"; return; }
  done
  echo ""
}
for host in api.altcontext.com staging.api.altcontext.com dev.api.altcontext.com; do
  out=$(probe_with_retry "https://${host}/health")
  code=${out%% *}
  pre=$(pre_code_for "$host")
  verdict=$(classify_api_probe "$code" "$pre") || true
  # A regression FAIL (reachable but unhealthy after a healthy baseline) gets one
  # confirming re-sample: the just-recreated edge can serve a single transient
  # 5xx while proxy routes settle, and a one-sample hard-fail trains operators
  # to ignore the gate. 000 FAILs already had bounded retries above.
  if [[ "$verdict" == "FAIL" && "$code" != "000" ]]; then
    sleep 10
    out=$(probe_with_retry "https://${host}/health")
    code=${out%% *}
    verdict=$(classify_api_probe "$code" "$pre") || true
  fi
  case "$verdict" in
    PASS) echo "PASS ${host}/health (200)" ;;
    WARN) echo "WARN ${host}/health (${code}; pre-promote ${pre:-n/a} — pre-existing backend unhealth, not a deploy failure)" ;;
    FAIL)
      if [[ "$code" == "000" ]]; then
        echo "FAIL ${host}/health (unreachable after retries — edge/TLS broken)"
      else
        echo "FAIL ${host}/health (${code}; was ${pre} pre-promote — deploy-caused edge regression)"
      fi
      smoke_fail=1 ;;
  esac
done
out=$(probe_with_retry "https://demo.altcontext.com/")
code=${out%% *}
final_url=${out#* }
verdict=$(classify_demo_probe "$code" "$final_url") || true
if [[ "$verdict" == "PASS" ]]; then
  echo "PASS demo.altcontext.com/ (final ${code} at ${final_url})"
else
  echo "FAIL demo.altcontext.com/ (final ${code} at ${final_url})"
  smoke_fail=1
fi
emit_alt_gate() {
  local gate_verdict="$1" msg="$2" overridable="${3:-0}"
  if [ "$gate_verdict" = "FAIL" ] && [ "$overridable" = "1" ] && [ "${DEMO_ALT_GATE_ENFORCE:-1}" = "0" ]; then
    echo "WARN ${msg} (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)"
    return
  fi
  echo "${gate_verdict} ${msg}"
  if [ "$gate_verdict" = "FAIL" ]; then
    smoke_fail=1
  fi
}
media_headers=$(mktemp)
media_body=$(mktemp)
curl -sS -D "$media_headers" -o "$media_body" --max-time 30 \
  "https://demo.altcontext.com/wp-json/wp/v2/media?per_page=100&_fields=id,alt_text,acx_alt_provenance" || true
set +o pipefail
header_total=$(grep -i '^x-wp-total:' "$media_headers" | tr -d '\r ' | sed 's/.*://;q')
# One JSON parse binds each attachment's alt to its own acx_alt_provenance
# adapter. Independent grep -o scrapes cannot join those fields.
load_alt_counts_from_media_body "$media_body"
set -o pipefail
rm -f "$media_headers" "$media_body"
if [[ "$BOOTSTRAP_RAN" == "1" ]]; then
  first_burst_verdict=$(classify_first_burst_bounded "$FIRST_BURST_COUNT" "$DESCRIBE_MAX" "$header_total") || true
  if [[ "$first_burst_verdict" == "PASS" ]]; then
    echo "PASS demo first describe burst (count=${FIRST_BURST_COUNT}, max=${DESCRIBE_MAX}, total=${header_total})"
  else
    echo "FAIL demo first describe burst (count=${FIRST_BURST_COUNT:-empty}, max=${DESCRIBE_MAX:-empty}, total=${header_total:-empty})"
    smoke_fail=1
  fi
else
  echo "SKIP demo first describe burst (bootstrap did not run; no plugin artifact was deployed)"
fi
min="${DEMO_ALT_MIN_COVERAGE_PCT:-95}"
pop=$(classify_alt_population "$header_total" "$body_total") || true
if [ "$pop" = "FAIL" ]; then
  pop_msg="demo alt coverage (measured ${body_total:-empty} of ${header_total:-empty} reported by x-wp-total; probe covers only one page, cannot certify coverage)"
else
  pop_msg="demo alt population (header=${header_total} body=${body_total})"
fi
emit_alt_gate "$pop" "$pop_msg" 1
verdict=$(classify_alt_coverage "$body_total" "$with_alt" "$min") || true
pct="?"
case "$body_total" in *[!0-9]*|'') ;; *)
  case "$with_alt" in *[!0-9]*|'') ;; *)
    if [ "$body_total" -gt 0 ]; then
      pct=$((with_alt * 100 / body_total))
    fi
    ;;
  esac
  ;;
esac
if [ "$pct" != "?" ]; then
  cov_msg="demo alt coverage (${with_alt}/${body_total} = ${pct}%, need ${min}%)"
else
  cov_msg="demo alt coverage (total=${body_total:-empty} with_alt=${with_alt:-empty}, need ${min}%)"
fi
cov_overridable=1
case "$with_alt" in
  *[!0-9]*|'') cov_overridable=0 ;;
  0) cov_overridable=0 ;;
esac
emit_alt_gate "$verdict" "$cov_msg" "$cov_overridable"
run_prov=0
case "$with_alt" in *[!0-9]*|'') ;; *)
  if [ "$with_alt" -gt 0 ]; then
    run_prov=1
  fi
  ;;
esac
if [ "$run_prov" = "1" ]; then
  prov=$(classify_alt_provenance "$denied_count" "$adapters" "$with_alt" "$usable_normalized_count") || true
  if [ "$prov" = "FAIL" ]; then
    # Identity is primary [INT-10]: operator must tell untrusted/absent
    # adapter from a seeded fixture caption without reading the source.
    identity=$(classify_alt_identity "$adapters" "$with_alt") || true
    if [ "$identity" = "FAIL" ]; then
      prov_msg="demo alt provenance (untrusted or absent adapter identity behind ${with_alt} published alt texts)"
    else
      prov_msg="demo alt provenance (seeded fixture caption detected in ${with_alt} published alt texts)"
    fi
  else
    prov_msg="demo alt provenance (trusted adapter identity, no seeded fixture captions in ${with_alt} published alt texts)"
  fi
  emit_alt_gate "$prov" "$prov_msg" 0
else
  emit_alt_gate FAIL "demo alt provenance (no alt text published; nothing to certify)" 0
fi
exit "$smoke_fail"
EOF
} | $SSH bash -se

echo "==> Done."
