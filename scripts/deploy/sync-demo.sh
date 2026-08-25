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
SEED_IMPORT_SRC="${SEED_IMPORT_SRC:-infra/oci/demo/seed/import.sh}"
SEED_MEDIA_DIR="${SEED_MEDIA_DIR:-infra/oci/demo/seed/media}"

REMOTE_DEMO_DIR="/opt/acx-backend/demo"
REMOTE_BACKEND_DIR="/opt/acx-backend"
REMOTE_PLUGIN_ZIP="/tmp/alt-context.zip"
SSH="ssh ${OCI_USER}@${OCI_HOST}"
SCP="scp"

if [[ -z "${PLUGIN_ZIP:-}" ]]; then
  PLUGIN_ZIP="$(ls -t dist/alt-context-*.zip 2>/dev/null | head -1 || true)"
fi

# Resolved early and preflighted with the other sources: discovering it missing
# at the final smoke step would leave the Caddy promote applied but unsmoked.
SMOKE_GATE_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/smoke-gate.sh"

for src in "$DEMO_COMPOSE_SRC" "$CADDYFILE_SRC" "$CADDY_COMPOSE_SRC" "$SYSTEMD_SRC" "$ENV_EXAMPLE_SRC" "$BOOTSTRAP_SRC" "$DESCRIBE_GATE_SRC" "$SEED_IMPORT_SRC" "$SMOKE_GATE_LIB"; do
  if [[ ! -f "$src" ]]; then
    echo "ERROR: source file not found: $src" >&2
    exit 2
  fi
done

echo "==> Target host: ${OCI_USER}@${OCI_HOST}"
echo "==> Ensure demo secrets exist at ${REMOTE_DEMO_DIR}/secrets/.env (from ${ENV_EXAMPLE_SRC})"

$SSH "sudo mkdir -p '${REMOTE_DEMO_DIR}/secrets' '${REMOTE_DEMO_DIR}/lib' '${REMOTE_DEMO_DIR}/seed/media' '${REMOTE_BACKEND_DIR}/data/demo-wpdata' '${REMOTE_BACKEND_DIR}/data/demo-dbdata'"
# sudo mkdir leaves root-owned dirs; the scp/ln below run as ${OCI_USER}.
$SSH "sudo chown -R ${OCI_USER}: '${REMOTE_DEMO_DIR}'"

echo "==> Rsync demo compose, bootstrap script, seed import, and env example"
$SCP "$DEMO_COMPOSE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/docker-compose.demo.yml"
$SCP "$BOOTSTRAP_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/bootstrap-wp.sh"
$SCP "$DESCRIBE_GATE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/lib/describe-gate.sh"
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
PLUGIN_ZIP='${REMOTE_PLUGIN_ZIP}' ./bootstrap-wp.sh
EOF
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
mv Caddyfile.new Caddyfile
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
# raise this bar. min_pct below the fixed floor of 50 FAILs closed; the floor
# is a safety constant, not an environment knob) and that published
# captions are not the description-service `seeded` fixture pool. Coverage
# counts only usable alt (classify_alt_text_usable), not placeholder strings.
# DEMO_ALT_GATE_ENFORCE defaults to 1 (a FAIL blocks the deploy). Set it to 0
# to keep the measurement line but print WARN instead of setting smoke_fail
# for overridable sub-gates (population and coverage) so a known-empty demo
# can still ship while the seed/describe pass is repaired. Provenance is not
# overridable: a canned-caption FAIL always sets smoke_fail, regardless of
# DEMO_ALT_GATE_ENFORCE. The override covers empty alt, never canned captions.
echo "==> Smoke four vhosts (api.* via /health, demo via / + media alt-text)"
{
  cat "$SMOKE_GATE_LIB"
  printf 'PRE_CODES="%s"\n' "$PRE_CODES"
  printf 'DEMO_ALT_MIN_COVERAGE_PCT="%s"\n' "${DEMO_ALT_MIN_COVERAGE_PCT:-95}"
  printf 'DEMO_ALT_GATE_ENFORCE="%s"\n' "${DEMO_ALT_GATE_ENFORCE:-1}"
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
  verdict=$(classify_api_probe "$code" "$pre")
  # A regression FAIL (reachable but unhealthy after a healthy baseline) gets one
  # confirming re-sample: the just-recreated edge can serve a single transient
  # 5xx while proxy routes settle, and a one-sample hard-fail trains operators
  # to ignore the gate. 000 FAILs already had bounded retries above.
  if [[ "$verdict" == "FAIL" && "$code" != "000" ]]; then
    sleep 10
    out=$(probe_with_retry "https://${host}/health")
    code=${out%% *}
    verdict=$(classify_api_probe "$code" "$pre")
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
verdict=$(classify_demo_probe "$code" "$final_url")
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
  "https://demo.altcontext.com/wp-json/wp/v2/media?per_page=100&_fields=id,alt_text" || true
set +o pipefail
header_total=$(grep -i '^x-wp-total:' "$media_headers" | tr -d '\r ' | sed 's/.*://;q')
body_total=$(grep -o '"alt_text": *"[^"]*"' "$media_body" | wc -l | tr -d ' ')
with_alt=0
sample=""
while IFS= read -r alt_json; do
  [ -n "$alt_json" ] || continue
  alt=$(printf '%s' "$alt_json" | sed 's/^"alt_text": *"//;s/"$//')
  if [ "$(classify_alt_text_usable "$alt")" = "PASS" ]; then
    with_alt=$((with_alt + 1))
    sample="${sample}${alt} "
  fi
done <<ALTJSON
$(grep -o '"alt_text": *"[^"]*"' "$media_body" || true)
ALTJSON
set -o pipefail
rm -f "$media_headers" "$media_body"
min="${DEMO_ALT_MIN_COVERAGE_PCT:-95}"
pop=$(classify_alt_population "$header_total" "$body_total")
if [ "$pop" = "FAIL" ]; then
  pop_msg="demo alt coverage (measured ${body_total:-empty} of ${header_total:-empty} reported by x-wp-total; probe covers only one page, cannot certify coverage)"
else
  pop_msg="demo alt population (header=${header_total} body=${body_total})"
fi
emit_alt_gate "$pop" "$pop_msg" 1
verdict=$(classify_alt_coverage "$body_total" "$with_alt" "$min")
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
emit_alt_gate "$verdict" "$cov_msg" 1
run_prov=0
case "$with_alt" in *[!0-9]*|'') ;; *)
  if [ "$with_alt" -gt 0 ]; then
    run_prov=1
  fi
  ;;
esac
if [ "$run_prov" = "1" ]; then
  prov=$(classify_alt_provenance "$sample")
  if [ "$prov" = "FAIL" ]; then
    prov_msg="demo alt provenance (seeded fixture caption detected in ${with_alt} published alt texts)"
  else
    prov_msg="demo alt provenance (no seeded fixture captions in ${with_alt} published alt texts)"
  fi
  emit_alt_gate "$prov" "$prov_msg" 0
else
  echo "SKIP demo alt provenance (no alt text published)"
fi
exit "$smoke_fail"
EOF
} | $SSH bash -se

echo "==> Done."
