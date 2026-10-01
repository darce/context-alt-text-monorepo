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

find_rights_rows() {
  local wanted="$1"

  if ((valid_rights_count == 0)); then
    printf '0\n'
    return 0
  fi

  awk -F '\t' -v wanted="$wanted" '
    $1 == wanted {
      matches++
      if (matches == 1) {
        row = $0
      }
    }
    END {
      print matches + 0
      if (matches == 1) {
        print row
      }
    }
  ' "${valid_rights_files[@]}"
}

parse_rights_row() {
  local remaining="$1"

  rights_row_file="${remaining%%$'\t'*}"
  remaining="${remaining#*$'\t'}"
  rights_row_subject="${remaining%%$'\t'*}"
  remaining="${remaining#*$'\t'}"
  rights_row_basis="${remaining%%$'\t'*}"
  remaining="${remaining#*$'\t'}"
  rights_row_source="${remaining%%$'\t'*}"
  remaining="${remaining#*$'\t'}"
  rights_row_notice="${remaining%%$'\t'*}"
  rights_row_added="${remaining#*$'\t'}"
}

validate_rights_row() {
  local filename="$1"
  local row="$2"
  local row_without_tabs
  local invalid=0
  local year month day days_in_month

  row_without_tabs="${row//$'\t'/}"
  if ((${#row} - ${#row_without_tabs} != 5)); then
    echo "ERROR: seed rights ledger row for $filename must have exactly six tab-separated fields" >&2
    return 1
  fi

  parse_rights_row "$row"
  if [[ -z "$rights_row_subject" ]]; then
    echo "ERROR: seed rights ledger row for $filename has an empty subject field" >&2
    invalid=1
  fi
  if [[ -z "$rights_row_basis" ]]; then
    echo "ERROR: seed rights ledger row for $filename has an empty basis field" >&2
    invalid=1
  fi
  if [[ -z "$rights_row_source" ]]; then
    echo "ERROR: seed rights ledger row for $filename has an empty source field" >&2
    invalid=1
  fi
  case "$rights_row_notice" in
    takedown_on_request|attribution_required|none)
      ;;
    *)
      echo "ERROR: seed rights ledger row for $filename has unrecognised notice '$rights_row_notice'" >&2
      invalid=1
      ;;
  esac
  if [[ -z "$rights_row_added" ]]; then
    echo "ERROR: seed rights ledger row for $filename has an empty added field" >&2
    invalid=1
  elif [[ ! "$rights_row_added" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "ERROR: seed rights ledger row for $filename has invalid added date '$rights_row_added'" >&2
    invalid=1
  else
    year=$((10#${rights_row_added:0:4}))
    month=$((10#${rights_row_added:5:2}))
    day=$((10#${rights_row_added:8:2}))

    case "$month" in
      1|3|5|7|8|10|12)
        days_in_month=31
        ;;
      4|6|9|11)
        days_in_month=30
        ;;
      2)
        if ((year % 400 == 0 || (year % 4 == 0 && year % 100 != 0))); then
          days_in_month=29
        else
          days_in_month=28
        fi
        ;;
      *)
        days_in_month=0
        ;;
    esac

    if ((month < 1 || month > 12 || day < 1 || day > days_in_month)); then
      echo "ERROR: seed rights ledger row for $filename has invalid added date '$rights_row_added'" >&2
      invalid=1
    fi
  fi

  return "$invalid"
}

for path in "${media_files[@]}"; do
  filename="${path##*/}"
  rights_result="$(find_rights_rows "$filename")"
  rights_match_count="${rights_result%%$'\n'*}"
  if [[ "$rights_result" == *$'\n'* ]]; then
    rights_row="${rights_result#*$'\n'}"
  else
    rights_row=""
  fi

  if [[ "$rights_match_count" != "1" ]]; then
    if [[ "$rights_match_count" == "0" ]]; then
      echo "ERROR: seed media file has no rights ledger row: $filename" >&2
    else
      echo "ERROR: seed media file must match exactly one rights ledger row: $filename (found $rights_match_count)" >&2
    fi
    validation_failed=1
  elif ! validate_rights_row "$filename" "$rights_row"; then
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
  rights_result="$(find_rights_rows "$filename")"
  rights_row="${rights_result#*$'\n'}"
  parse_rights_row "$rights_row"
  rights_basis="$rights_row_basis"
  rights_source="$rights_row_source"

  case "$rights_basis" in
    editorial_fair_use|cc_by|cc_by_sa|public_domain|eu_reuse|generated)
      ;;
    *)
      echo "REFUSED: $filename has unrecognised rights basis '$rights_basis'" >&2
      refused_count=$((refused_count + 1))
      continue
      ;;
  esac

  if ! attachment_id="$(docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    -v "${SEED_MEDIA_DIR}:/seed:ro" \
    wpcli wp media import "/seed/${filename}" --porcelain)"; then
    echo "ERROR: failed to import seed media file: $filename" >&2
    exit 1
  fi
  if [[ ! "$attachment_id" =~ ^[0-9]+$ ]]; then
    echo "ERROR: seed media import returned an invalid attachment id for $filename" >&2
    exit 1
  fi

  if ! docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    wpcli wp post meta update "$attachment_id" acx_seed_rights_basis "$rights_basis"; then
    if ! docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
      wpcli wp post delete "$attachment_id" --force; then
      echo "ERROR: failed to remove attachment $attachment_id after a rights metadata failure for $filename" >&2
    fi
    echo "ERROR: failed to write rights metadata for seed media file: $filename" >&2
    exit 1
  fi
  if ! docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
    wpcli wp post meta update "$attachment_id" acx_seed_rights_source "$rights_source"; then
    if ! docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
      wpcli wp post delete "$attachment_id" --force; then
      echo "ERROR: failed to remove attachment $attachment_id after a rights metadata failure for $filename" >&2
    fi
    echo "ERROR: failed to write rights metadata for seed media file: $filename" >&2
    exit 1
  fi
  imported_count=$((imported_count + 1))
done

echo "==> Seed import complete: imported=${imported_count} refused=${refused_count}"
