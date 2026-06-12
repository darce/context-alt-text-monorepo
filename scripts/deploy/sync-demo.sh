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

OCI_HOST="${OCI_HOST:-129.213.40.111}"
OCI_USER="${OCI_USER:-ubuntu}"

DEMO_COMPOSE_SRC="${DEMO_COMPOSE_SRC:-apps/prototype-description-service/docker-compose.demo.yml}"
CADDYFILE_SRC="${CADDYFILE_SRC:-apps/prototype-description-service/Caddyfile}"
CADDY_COMPOSE_SRC="${CADDY_COMPOSE_SRC:-apps/prototype-description-service/docker-compose.caddy.yml}"
SYSTEMD_SRC="${SYSTEMD_SRC:-apps/prototype-description-service/systemd/acx-demo.service}"
ENV_EXAMPLE_SRC="${ENV_EXAMPLE_SRC:-infra/oci/demo/.env.example}"
BOOTSTRAP_SRC="${BOOTSTRAP_SRC:-infra/oci/demo/bootstrap-wp.sh}"
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

for src in "$DEMO_COMPOSE_SRC" "$CADDYFILE_SRC" "$CADDY_COMPOSE_SRC" "$SYSTEMD_SRC" "$ENV_EXAMPLE_SRC" "$BOOTSTRAP_SRC" "$SEED_IMPORT_SRC"; do
  if [[ ! -f "$src" ]]; then
    echo "ERROR: source file not found: $src" >&2
    exit 2
  fi
done

echo "==> Target host: ${OCI_USER}@${OCI_HOST}"
echo "==> Ensure demo secrets exist at ${REMOTE_DEMO_DIR}/secrets/.env (from ${ENV_EXAMPLE_SRC})"

$SSH "sudo mkdir -p '${REMOTE_DEMO_DIR}/secrets' '${REMOTE_DEMO_DIR}/seed/media' '${REMOTE_BACKEND_DIR}/data/demo-wpdata' '${REMOTE_BACKEND_DIR}/data/demo-dbdata'"
# sudo mkdir leaves root-owned dirs; the scp/ln below run as ${OCI_USER}.
$SSH "sudo chown -R ${OCI_USER}: '${REMOTE_DEMO_DIR}'"

echo "==> Rsync demo compose, bootstrap script, seed import, and env example"
$SCP "$DEMO_COMPOSE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/docker-compose.demo.yml"
$SCP "$BOOTSTRAP_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/bootstrap-wp.sh"
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
docker compose -f docker-compose.caddy.yml up -d
docker compose -f docker-compose.caddy.yml ps
EOF

echo "==> Install/refresh systemd unit (operator enables manually if first install)"
$SCP "$SYSTEMD_SRC" "${OCI_USER}@${OCI_HOST}:/tmp/acx-demo.service"
$SSH "sudo cp /tmp/acx-demo.service /etc/systemd/system/acx-demo.service && sudo systemctl daemon-reload"

echo "==> Smoke four vhosts (demo may fail until DNS/TLS propagates)"
$SSH bash -se <<'EOF'
set -euo pipefail
for host in api.altcontext.com staging.api.altcontext.com dev.api.altcontext.com demo.altcontext.com; do
  code=$(curl -fsS -o /dev/null -w '%{http_code}' "https://${host}/" || echo FAIL)
  echo "${code} ${host}"
done
EOF

echo "==> Done."
