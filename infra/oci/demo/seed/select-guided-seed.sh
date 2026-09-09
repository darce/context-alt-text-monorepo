#!/usr/bin/env bash
# GUIDESEED-1: add the guided-prototype people (Katy Perry, Justin Trudeau) to the
# demo seed bundle so the live roster can name them.
#
# Copies the six bundled, licence-cleared plugin assets
# (apps/prototype-wp-alt-context/js/admin/assets/guided/*.jpg, credits in CREDITS.md)
# into seed/media/ under the `<person_slug>_<n>.jpg` scheme import.sh and the roster
# scan expect, writes seed/guided-manifest.txt, and regenerates the provenance rows
# between the GUIDED-PROVENANCE markers in seed/README.md. The SEED-PROVENANCE
# (celebs01) block is left untouched.
#
# Idempotent: removes only the exact <slug>_1..N files this script owns (from the
# previous guided-manifest counts and the rows about to be written). Never glob-
# deletes shared-media prefixes — a clustering file like katy_perry_99.jpg must
# survive a guided rerun.
# Refuses (exit 2) if any bundled source is missing or is not image/jpeg by content.
# Portable to bash 3.2 (macOS) and bash 5 (VM): no mapfile / associative arrays /
# GNU-only find depth flags. Cleanup failures are not suppressed.
#
# Usage:
#   bash infra/oci/demo/seed/select-guided-seed.sh
#   SRC=<assets dir> OUT=<media dir> MANIFEST=<file> README=<file>  # overrides (tests)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "$SEED_DIR/../../../.." && pwd)"
SRC="${SRC:-$REPO_ROOT/apps/prototype-wp-alt-context/js/admin/assets/guided}"
OUT="${OUT:-$SEED_DIR/media}"
MANIFEST="${MANIFEST:-$SEED_DIR/guided-manifest.txt}"
README="${README:-$SEED_DIR/README.md}"
ADDED="${ADDED:-2026-09-08}"

# source_file|target_slug|subject label|source / licence  (one row per bundled asset;
# mirrors js/admin/assets/guided/CREDITS.md — keep the two in sync)
ROWS='guided-katy-perry-2026.jpg|katy_perry|Katy Perry|Wikimedia Commons, Justin Higuchi — CC BY 4.0
guided-katy-perry-2019.jpg|katy_perry|Katy Perry|Wikimedia Commons, Glenn Francis (Toglenn) — CC BY-SA 4.0
guided-katy-perry-2016.jpg|katy_perry|Katy Perry|Wikimedia Commons, Voice of America — public domain
guided-justin-trudeau-2025.jpg|justin_trudeau|Justin Trudeau|Wikimedia Commons, European Commission — EU reuse licence (Commission Decision 2011/833/EU)
guided-justin-trudeau-2025-b.jpg|justin_trudeau|Justin Trudeau|Wikimedia Commons, European Commission — EU reuse licence (Commission Decision 2011/833/EU)
guided-press-tribeca-2026.jpg|tribeca_press|Justin Trudeau and Katy Perry (press photo, walkthrough subject)|Wikimedia Commons, Colleen Sturtevant — CC BY-SA 4.0'

[ -d "$SRC" ] || { echo "ERROR: SRC not found: $SRC" >&2; exit 2; }

# Validate every source before touching OUT/MANIFEST/README (all-or-nothing).
missing=0
while IFS='|' read -r src _slug _label _lic; do
  [ -n "${src:-}" ] || continue
  if [ ! -f "$SRC/$src" ]; then
    echo "ERROR: bundled source missing: $SRC/$src" >&2; missing=$((missing + 1)); continue
  fi
  mt=$(file -b --mime-type "$SRC/$src" 2>/dev/null || echo unknown)
  [ "$mt" = "image/jpeg" ] || { echo "ERROR: $src is '$mt' by content, not image/jpeg" >&2; missing=$((missing + 1)); }
done <<< "$ROWS"
[ "$missing" -eq 0 ] || exit 2

mkdir -p "$OUT"
tmp_rows="$(mktemp)"; tmp_manifest="$(mktemp)"; tmp_readme="$(mktemp)"
trap 'rm -f "$tmp_rows" "$tmp_manifest" "$tmp_readme"' EXIT

# Remove exactly slug_1..slug_count in OUT. Never glob slug_* (GR-01).
# Portable: no find(1) (GR-06). Do not swallow rm failures.
remove_guided_owned() {
  _slug=$1
  _count=$2
  _i=1
  case "$_count" in
    ''|*[!0-9]*) _count=0 ;;
  esac
  while [ "$_i" -le "$_count" ]; do
    for _ext in jpg jpeg png JPG JPEG PNG; do
      _path="$OUT/${_slug}_${_i}.$_ext"
      if [ -e "$_path" ]; then
        rm -f "$_path" || { echo "ERROR: failed to remove owned guided file: $_path" >&2; exit 1; }
      fi
    done
    _i=$((_i + 1))
  done
}

# Idempotent clear of previously owned guided files (exact 1..N from last manifest).
if [ -f "$MANIFEST" ]; then
  while IFS= read -r _line || [ -n "${_line:-}" ]; do
    _line=${_line%$'\r'}
    [ -n "$_line" ] || continue
    # Word-split the manifest row: "<slug> <count>"
    set -- $_line
    _oldp=$1
    _oldc=${2:-0}
    [ -n "${_oldp:-}" ] || continue
    remove_guided_owned "$_oldp" "$_oldc"
  done < "$MANIFEST"
fi

# Also drop the exact targets we are about to write (manifest missing or counts changed).
_prev=""
_n=0
while IFS='|' read -r _src _slug _label _lic; do
  [ -n "${_src:-}" ] || continue
  if [ "$_slug" != "$_prev" ]; then
    _prev=$_slug
    _n=0
  fi
  _n=$((_n + 1))
  for _ext in jpg jpeg png JPG JPEG PNG; do
    _path="$OUT/${_slug}_${_n}.$_ext"
    if [ -e "$_path" ]; then
      rm -f "$_path" || { echo "ERROR: failed to remove guided target: $_path" >&2; exit 1; }
    fi
  done
done <<< "$ROWS"

total=0
prev=""; n=0
while IFS='|' read -r src slug label lic; do
  [ -n "${src:-}" ] || continue
  if [ "$slug" != "$prev" ]; then
    [ -n "$prev" ] && printf '%s %s\n' "$prev" "$n" >> "$tmp_manifest"
    prev="$slug"; n=0
  fi
  n=$((n + 1)); total=$((total + 1))
  cp "$SRC/$src" "$OUT/${slug}_${n}.jpg"
  printf '| %s | %s | %s | %s |\n' "${slug}_${n}.jpg" "$label" "$lic" "$ADDED" >> "$tmp_rows"
done <<< "$ROWS"
[ -n "$prev" ] && printf '%s %s\n' "$prev" "$n" >> "$tmp_manifest"
sort "$tmp_manifest" > "$MANIFEST"

echo "==> Copied $total guided images into $OUT ($(wc -l < "$MANIFEST" | tr -d ' ') persons in $MANIFEST)"

if [ -f "$README" ] && grep -q 'GUIDED-PROVENANCE:START' "$README" && grep -q 'GUIDED-PROVENANCE:END' "$README"; then
  start_line=$(grep -n 'GUIDED-PROVENANCE:START' "$README" | head -1 | cut -d: -f1)
  end_line=$(grep -n 'GUIDED-PROVENANCE:END' "$README" | head -1 | cut -d: -f1)
  {
    head -n "$start_line" "$README"
    printf '| File | Subject label (for assertions) | Source / license | Added |\n'
    printf '| --- | --- | --- | --- |\n'
    cat "$tmp_rows"
    tail -n +"$end_line" "$README"
  } > "$tmp_readme"
  mv "$tmp_readme" "$README"
  echo "==> Regenerated guided provenance table in $README ($total rows)"
else
  echo "WARN: $README missing GUIDED-PROVENANCE markers — table not updated" >&2
fi
