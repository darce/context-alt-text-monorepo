#!/usr/bin/env bash
# Deploy or update an ACX environment on the OCI VM.
#
# Usage:
#   ./deploy-env.sh <env> [<ssh-target>]
#
# Examples:
#   ./deploy-env.sh prod                         # deploy prod to default VM
#   ./deploy-env.sh staging ubuntu@129.213.40.111 # deploy staging to specific host
#   ./deploy-env.sh dev                          # deploy dev
#
# Prerequisites:
#   - SSH access to the VM
#   - Docker images tagged and pushed to OCIR
#   - /opt/acx-backend/<env>/secrets/.env exists on the VM

set -euo pipefail

ENV="${1:?Usage: deploy-env.sh <env> [<ssh-target>]}"
SSH_TARGET="${2:-ubuntu@129.213.40.111}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$SERVICE_DIR/systemd"

if [[ "$ENV" != "prod" && "$ENV" != "staging" && "$ENV" != "dev" ]]; then
  echo "Error: env must be prod, staging, or dev" >&2
  exit 1
fi

COMPOSE_FILES="-f docker-compose.env.yml"
if [[ "$ENV" == "prod" ]]; then
  COMPOSE_FILES="-f docker-compose.env.yml -f docker-compose.admin.yml"
fi

echo "=== Deploying $ENV to $SSH_TARGET ==="

# Copy compose template, db-init, and Caddy files
echo "Copying compose template..."
scp "$SERVICE_DIR/docker-compose.env.yml" "$SSH_TARGET:/opt/acx-backend/$ENV/docker-compose.env.yml"
if [[ "$ENV" == "prod" ]]; then
  scp "$SERVICE_DIR/docker-compose.admin.yml" "$SSH_TARGET:/opt/acx-backend/$ENV/docker-compose.admin.yml"
fi
scp -r "$SERVICE_DIR/db/docker-prod-init" "$SSH_TARGET:/opt/acx-backend/$ENV/db/"

echo "Copying Caddy files..."
scp "$SERVICE_DIR/docker-compose.caddy.yml" "$SSH_TARGET:/opt/acx-backend/docker-compose.caddy.yml"
scp "$SERVICE_DIR/Caddyfile" "$SSH_TARGET:/opt/acx-backend/Caddyfile"

# Install systemd units from checked-in templates (always converge)
echo "Installing systemd units from repo templates..."

# Render env-specific unit from template and install
sed -e "s/{{ENV}}/$ENV/g" -e "s|{{COMPOSE_FILES}}|$COMPOSE_FILES|g" \
  "$SYSTEMD_DIR/acx-env.service.template" > "/tmp/acx-$ENV.service"
scp "/tmp/acx-$ENV.service" "$SSH_TARGET:/tmp/acx-$ENV.service"
rm "/tmp/acx-$ENV.service"

# Copy Caddy unit as-is (no templating needed)
scp "$SYSTEMD_DIR/acx-caddy.service" "$SSH_TARGET:/tmp/acx-caddy.service"

# Install both units on the VM (always overwrite to converge with repo)
ssh "$SSH_TARGET" bash -s "$ENV" << 'REMOTE'
ENV="$1"

sudo cp "/tmp/acx-$ENV.service" "/etc/systemd/system/acx-$ENV.service"
sudo cp "/tmp/acx-caddy.service" "/etc/systemd/system/acx-caddy.service"
rm -f "/tmp/acx-$ENV.service" "/tmp/acx-caddy.service"

sudo systemctl daemon-reload
sudo systemctl enable "acx-$ENV.service" acx-caddy.service 2>/dev/null
echo "Systemd units installed and enabled (acx-$ENV, acx-caddy)"
REMOTE

# Pull latest image and restart
echo "Pulling image and restarting $ENV..."
ssh "$SSH_TARGET" "cd /opt/acx-backend/$ENV && docker compose $COMPOSE_FILES pull && sudo systemctl restart acx-$ENV"

# Restart Caddy to pick up any Caddyfile changes
ssh "$SSH_TARGET" "sudo systemctl restart acx-caddy"

echo "=== $ENV deployment complete ==="
