#!/usr/bin/env bash
# Import seed media into the demo WordPress library via wp-cli.
#
# Usage:
#   cd /opt/acx-backend/demo && ./seed/import.sh
#   DEMO_DIR=/opt/acx-backend/demo infra/oci/demo/seed/import.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_MEDIA_DIR="${SEED_MEDIA_DIR:-${SCRIPT_DIR}/media}"
DEMO_DIR="${DEMO_DIR:-/opt/acx-backend/demo}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.demo.yml}"

cd "$DEMO_DIR"

if [[ ! -f secrets/.env ]]; then
  echo "ERROR: ${DEMO_DIR}/secrets/.env missing — copy from secrets/.env.example" >&2
  exit 2
fi
ln -sf secrets/.env .env

if [[ ! -d "$SEED_MEDIA_DIR" ]]; then
  echo "ERROR: seed media directory missing: $SEED_MEDIA_DIR" >&2
  exit 2
fi

shopt -s nullglob
media_files=("$SEED_MEDIA_DIR"/*.{jpg,jpeg,png,JPG,JPEG,PNG})
shopt -u nullglob

if ((${#media_files[@]} == 0)); then
  echo "ERROR: no images found under $SEED_MEDIA_DIR — add licensed seed/media files first" >&2
  exit 2
fi

echo "==> Importing ${#media_files[@]} seed media file(s)"
for path in "${media_files[@]}"; do
  docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    -v "${SEED_MEDIA_DIR}:/seed:ro" \
    wpcli wp media import "/seed/$(basename "$path")" --porcelain
done

echo "==> Seed import complete"
