#!/usr/bin/env bash
# Sync the demo WordPress stack and Caddy edge config to the OCI host.
#
# Order matters: bring up acx-demo first so acx-demo-net exists, then recreate
# Caddy (network join requires container recreate — reload-only is insufficient).
#
# Usage:
#   scripts/deploy/sync-demo.sh
#   OCI_HOST=<host> OCI_USER=ubuntu scripts/deploy/sync-demo.sh

set -euo pipefail

OCI_HOST="${OCI_HOST:-129.213.40.111}"
OCI_USER="${OCI_USER:-ubuntu}"

DEMO_COMPOSE_SRC="${DEMO_COMPOSE_SRC:-apps/prototype-description-service/docker-compose.demo.yml}"
CADDYFILE_SRC="${CADDYFILE_SRC:-apps/prototype-description-service/Caddyfile}"
CADDY_COMPOSE_SRC="${CADDY_COMPOSE_SRC:-apps/prototype-description-service/docker-compose.caddy.yml}"
SYSTEMD_SRC="${SYSTEMD_SRC:-apps/prototype-description-service/systemd/acx-demo.service}"
ENV_EXAMPLE_SRC="${ENV_EXAMPLE_SRC:-infra/oci/demo/.env.example}"

REMOTE_DEMO_DIR="/opt/acx-backend/demo"
REMOTE_BACKEND_DIR="/opt/acx-backend"
SSH="ssh ${OCI_USER}@${OCI_HOST}"
SCP="scp"

for src in "$DEMO_COMPOSE_SRC" "$CADDYFILE_SRC" "$CADDY_COMPOSE_SRC" "$SYSTEMD_SRC" "$ENV_EXAMPLE_SRC"; do
  if [[ ! -f "$src" ]]; then
    echo "ERROR: source file not found: $src" >&2
    exit 2
  fi
done

echo "==> Target host: ${OCI_USER}@${OCI_HOST}"
echo "==> Ensure demo secrets exist at ${REMOTE_DEMO_DIR}/secrets/.env (from ${ENV_EXAMPLE_SRC})"

$SSH "sudo mkdir -p '${REMOTE_DEMO_DIR}/secrets' '${REMOTE_BACKEND_DIR}/data/demo-wpdata' '${REMOTE_BACKEND_DIR}/data/demo-dbdata'"

echo "==> Rsync demo compose + env example"
$SCP "$DEMO_COMPOSE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/docker-compose.demo.yml"
$SCP "$ENV_EXAMPLE_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/secrets/.env.example"

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

echo "==> Bring up demo stack (creates acx-demo-net)"
$SSH bash -se <<EOF
set -euo pipefail
cd '${REMOTE_DEMO_DIR}'
if [[ ! -f secrets/.env ]]; then
  echo "ERROR: ${REMOTE_DEMO_DIR}/secrets/.env missing — copy from secrets/.env.example and populate" >&2
  exit 2
fi
ln -sf secrets/.env .env
docker compose -f docker-compose.demo.yml up -d
docker compose -f docker-compose.demo.yml ps
docker network ls | grep acx-demo-net
EOF

echo "==> Promote Caddy config and validate syntax"
$SSH bash -se <<'EOF'
set -euo pipefail
cd /opt/acx-backend
mv Caddyfile.new Caddyfile
mv docker-compose.caddy.yml.new docker-compose.caddy.yml
docker run --rm \
  -v /opt/acx-backend/Caddyfile:/etc/caddy/Caddyfile:ro \
  caddy:2-alpine \
  caddy validate --config /etc/caddy/Caddyfile
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
