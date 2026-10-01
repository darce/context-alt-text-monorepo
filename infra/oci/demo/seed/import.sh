#!/usr/bin/env bash
# Import seed media into the demo WordPress library via wp-cli.
#
# Usage:
#   cd /opt/acx-backend/demo && ./seed/import.sh
#   DEMO_DIR=/opt/acx-backend/demo infra/oci/demo/seed/import.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_MEDIA_DIR="${SEED_MEDIA_DIR:-${SCRIPT_DIR}/media}"
SEED_RIGHTS_DIR="${SEED_RIGHTS_DIR:-${SCRIPT_DIR}}"
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
media_files=("$SEED_MEDIA_DIR"/*.{jpg,jpeg,png,webp,JPG,JPEG,PNG,WEBP})
shopt -u nullglob

if ((${#media_files[@]} == 0)); then
  echo "ERROR: no images found under $SEED_MEDIA_DIR — add licensed seed/media files first" >&2
  exit 2
fi

rights_header=$'file\tsubject\tbasis\tsource\tnotice\tadded'
rights_files=("${SEED_RIGHTS_DIR}/clustering-rights.tsv" "${SEED_RIGHTS_DIR}/guided-rights.tsv")
valid_rights_files=()
valid_rights_count=0
validation_failed=0

for ledger in "${rights_files[@]}"; do
  if [[ ! -f "$ledger" ]]; then
    echo "ERROR: seed rights ledger missing: $ledger" >&2
    validation_failed=1
    continue
  fi

  ledger_header=""
  IFS= read -r ledger_header < "$ledger" || true
  if [[ "$ledger_header" != "$rights_header" ]]; then
    echo "ERROR: seed rights ledger has wrong header: $ledger" >&2
    validation_failed=1
    continue
  fi

  valid_rights_files+=("$ledger")
  valid_rights_count=$((valid_rights_count + 1))
done

find_rights_row() {
  local wanted="$1"
  local ledger
  local row

  for ledger in "${valid_rights_files[@]}"; do
    if row="$(awk -F '\t' -v wanted="$wanted" '$1 == wanted { print $3 "\t" $4; found = 1; exit } END { if (!found) exit 1 }' "$ledger")"; then
      printf '%s\n' "$row"
      return 0
    fi
  done

  return 1
}

for path in "${media_files[@]}"; do
  filename="${path##*/}"
  if ((valid_rights_count == 0)) || ! find_rights_row "$filename" >/dev/null; then
    echo "ERROR: seed media file has no rights ledger row: $filename" >&2
    validation_failed=1
  fi
done

if ((validation_failed)); then
  exit 2
fi

echo "==> Importing ${#media_files[@]} seed media file(s)"
imported_count=0
refused_count=0
for path in "${media_files[@]}"; do
  filename="${path##*/}"
  rights_row="$(find_rights_row "$filename")"
  rights_basis="${rights_row%%$'\t'*}"
  rights_source="${rights_row#*$'\t'}"

  case "$rights_basis" in
    editorial_fair_use|cc_by|cc_by_sa|public_domain|eu_reuse|generated)
      ;;
    *)
      echo "REFUSED: $filename has unrecognised rights basis '$rights_basis'" >&2
      refused_count=$((refused_count + 1))
      continue
      ;;
  esac

  attachment_id="$(docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    -v "${SEED_MEDIA_DIR}:/seed:ro" \
    wpcli wp media import "/seed/${filename}" --porcelain)"
  docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    wpcli wp post meta update "$attachment_id" acx_seed_rights_basis "$rights_basis"
  docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    wpcli wp post meta update "$attachment_id" acx_seed_rights_source "$rights_source"
  imported_count=$((imported_count + 1))
done

echo "==> Seed import complete: imported=${imported_count} refused=${refused_count}"
