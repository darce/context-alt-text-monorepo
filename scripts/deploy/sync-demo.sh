#!/usr/bin/env bash
# Sync the demo WordPress stack and Caddy edge config to the OCI host.
#
# Order matters: bring up acx-demo first so acx-demo-net exists, then recreate
# Caddy (network join requires container recreate — reload-only is insufficient).
# When PLUGIN_ZIP is available (local dist/ or explicit path), runs bootstrap-wp.sh
# after the stack is healthy.
#
# Usage:
#   scripts/deploy/sync-demo.sh
#   PLUGIN_ZIP=dist/alt-context-1.2.3.zip scripts/deploy/sync-demo.sh
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

if [[ -z "${PLUGIN_ZIP:-}" ]]; then
  PLUGIN_ZIP="$(ls -t dist/alt-context-*.zip 2>/dev/null | head -1 || true)"
fi

# Resolved early and preflighted with the other sources: discovering it missing
# at the final smoke step would leave the Caddy promote applied but unsmoked.
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

for src in "$DEMO_COMPOSE_SRC" "$CADDYFILE_SRC" "$CADDY_COMPOSE_SRC" "$SYSTEMD_SRC" "$ENV_EXAMPLE_SRC" "$BOOTSTRAP_SRC" "$DESCRIBE_GATE_SRC" "$GPU_ENV_CONTRACT_SRC" "$SEED_IMPORT_SRC" "$SMOKE_GATE_LIB" "$FIXTURE_DENYLIST_LIB"; do
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
  if ! $SSH "sudo chmod 700 '${REMOTE_GPU_PREFLIGHT_DIR}/preflight-gpu-env.sh' && sudo chmod 644 '${REMOTE_GPU_PREFLIGHT_DIR}/lib/gpu-env-contract.sh' '${REMOTE_GPU_PREFLIGHT_DIR}/lib/describe-gate.sh' && sudo '${REMOTE_GPU_PREFLIGHT_DIR}/preflight-gpu-env.sh' --check-reaper '${REMOTE_BACKEND_DIR}/prod/secrets/.env' '${REMOTE_DEMO_DIR}/secrets/.env'"; then
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
$SCP "$ENV_EXAMPLE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/secrets/.env.example"
$SSH "chmod +x '${REMOTE_DEMO_DIR}/bootstrap-wp.sh' '${REMOTE_DEMO_DIR}/seed/import.sh'"

seed_media_files=()
while IFS= read -r f; do seed_media_files+=("$f"); done < <(find "$SEED_MEDIA_DIR" -maxdepth 1 \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) 2>/dev/null)
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
  echo "WARN: no dist/alt-context-*.zip found locally — bootstrap will fail until a zip is shipped" >&2
fi

echo "==> Rsync Caddy edge config (repo-tracked source of truth)"
$SCP "$CADDYFILE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_BACKEND_DIR}/Caddyfile.new"
$SCP "$CADDY_COMPOSE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_BACKEND_DIR}/docker-compose.caddy.yml.new"

echo "==> Stage rollback copies on the VM"
$SSH bash -se <<'EOF'
set -euo pipefail
cd /opt/acx-backend
if [[ -f Caddyfile ]]; then cp -a Caddyfile "Caddyfile.bak.$(date +%s)"; fi
if [[ -f docker-compose.caddy.yml ]]; then cp -a docker-compose.caddy.yml "docker-compose.caddy.yml.bak.$(date +%s)"; fi
EOF

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

# Baseline BEFORE the Caddy promote: an api.* vhost that was healthy (200) and
# turns unhealthy after the promote is a deploy-caused edge regression and must
# FAIL the smoke; one that was already broken stays a WARN (backend outage,
# out of deploy scope). `caddy validate` below is syntax-only — it cannot catch
# a typo'd reverse_proxy upstream, which is exactly what this baseline catches.
echo "==> Capture pre-promote api vhost baseline"
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

echo "==> Validate staged Caddy config, then promote"
$SSH bash -se <<'EOF'
set -euo pipefail
cd /opt/acx-backend
# Validate the staged .new file BEFORE promoting: a failed validation must
# leave the live Caddyfile untouched, or the next container restart loads a
# broken config and takes down every vhost.
docker run --rm \
  -v /opt/acx-backend/Caddyfile.new:/etc/caddy/Caddyfile:ro \
  caddy:2-alpine \
  caddy validate --config /etc/caddy/Caddyfile
# `mv` over the live Caddyfile allocates a new inode. docker-compose.caddy.yml
# bind-mounts this one file, and a single-file bind mount pins the inode at
# container start, so a mv'd promote never reaches the running proxy: the deploy
# reports success while Caddy keeps serving the pre-promote config
# (GUIDEDEPLOY-1-BR-04). Truncate in place so the mounted inode is the one we
# just wrote.
cat Caddyfile.new > Caddyfile
rm -f Caddyfile.new
mv docker-compose.caddy.yml.new docker-compose.caddy.yml
EOF

echo "==> Recreate Caddy so it joins acx-demo-net"
$SSH bash -se <<'EOF'
set -euo pipefail
cd /opt/acx-backend
# acx-dev-fir-net is external:true on docker-compose.caddy.yml; create it if the
# fir stack has never stood it up. Labels match docker-compose.env.yml's
# declaring key (backend) + COMPOSE_PROJECT_NAME=acx-dev-fir so fir can adopt.
docker network inspect acx-dev-fir-net >/dev/null 2>&1 || docker network create \
  --label com.docker.compose.network=backend \
  --label com.docker.compose.project=acx-dev-fir \
  acx-dev-fir-net
docker compose -f docker-compose.caddy.yml up -d

# The in-place promote above only reaches Caddy when the container's mount
# already pins the current inode. A container recreated before an earlier
# mv-style promote is pinned to an orphaned inode that no reload can reach, so
# compare host and container copies and recreate when they diverge. Reload
# otherwise: it applies the new config without dropping in-flight TLS sessions.
want_config="$(sha256sum Caddyfile | cut -d' ' -f1)"
have_config="$(docker compose -f docker-compose.caddy.yml exec -T caddy sha256sum /etc/caddy/Caddyfile | cut -d' ' -f1)"
if [ "$want_config" != "$have_config" ]; then
  echo "    caddy mount diverged from /opt/acx-backend/Caddyfile; recreating"
  docker compose -f docker-compose.caddy.yml up -d --force-recreate caddy
else
  docker compose -f docker-compose.caddy.yml exec -T caddy \
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
fi
docker compose -f docker-compose.caddy.yml ps
EOF

echo "==> Install/refresh systemd unit (operator enables manually if first install)"
$SCP "$SYSTEMD_SRC" "${OCI_USER}@${OCI_HOST}:/tmp/acx-demo.service"
$SSH "sudo cp /tmp/acx-demo.service /etc/systemd/system/acx-demo.service && sudo systemctl daemon-reload"

# api.* vhosts have no root route (/ -> 404), so probe /health there; the demo
# vhost serves the WP front page at /. Gate semantics (pinned by
# scripts/deploy/tests/test-smoke-gate.sh; classification logic lives in
# scripts/deploy/lib/smoke-gate.sh and is shipped to the VM inline): the deploy
# owns the edge and the demo stack, NOT backend health. 000 after retries FAILs
# (edge/TLS broken; retries absorb the Caddy-recreate/ACME startup window); an
# api.* HTTP error FAILs only when the pre-promote baseline was healthy
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
