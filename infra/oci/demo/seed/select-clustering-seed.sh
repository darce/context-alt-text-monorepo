#!/usr/bin/env bash
# E15-29 Slice 1: deterministically select a clustering-showcase seed.
#
# Picks the top PERSONS persons by eligible-image count (desc; ties alphabetical)
# from a source dir of `<person>_<n>.<ext>` files, copies the first PER_PERSON
# eligible (.jpg/.jpeg/.png — .webp excluded, since import.sh/sync-demo.sh skip it)
# images of each into the demo seed bundle, writes a manifest, and regenerates the
# provenance table in seed/README.md between the SEED-PROVENANCE markers.
#
# Idempotent: clears any prior manifest-listed selection from OUT before copying.
# Refuses (exit 2) if fewer than PERSONS persons have >= PER_PERSON eligible images.
# Portable to bash 3.2 (macOS) and bash 5 (VM): no mapfile / associative arrays.
#
# Usage:
#   SRC=/path/to/celebs01 PERSONS=20 PER_PERSON=5 \
#     bash infra/oci/demo/seed/select-clustering-seed.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_DIR="$SCRIPT_DIR"
README="$SEED_DIR/README.md"
SRC="${SRC:-/Users/daniel/Development/altcontext-marketing-monorepo/static/input-images/celebs01}"
PERSONS="${PERSONS:-20}"
PER_PERSON="${PER_PERSON:-5}"
OUT="${OUT:-$SEED_DIR/media}"
MANIFEST="${MANIFEST:-$SEED_DIR/clustering-manifest.txt}"
LICENSE_NOTE="${LICENSE_NOTE:-celebs01 — editorial/fair-use demo (takedown on request)}"
ADDED="${ADDED:-2026-06-13}"
STRIP='s#.*/##; s/_[0-9]+\.(jpg|jpeg|png|JPG|JPEG|PNG)$//'

[ -d "$SRC" ] || { echo "ERROR: SRC not found: $SRC" >&2; exit 2; }
mkdir -p "$OUT"

tmp_elig="$(mktemp)"; tmp_map="$(mktemp)"; tmp_persons="$(mktemp)"; tmp_rows="$(mktemp)"; tmp_readme="$(mktemp)"
trap 'rm -f "$tmp_elig" "$tmp_map" "$tmp_persons" "$tmp_rows" "$tmp_readme"' EXIT

find "$SRC" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | sort > "$tmp_elig"
[ -s "$tmp_elig" ] || { echo "ERROR: no eligible jpg/jpeg/png under $SRC" >&2; exit 2; }

# person<TAB>path, preserving sorted-by-path order.
sed -E "$STRIP" "$tmp_elig" | paste - "$tmp_elig" > "$tmp_map"

# Rank persons with >= PER_PERSON eligible: count desc, then name asc; top PERSONS.
# awk-limited (no `head`) so no SIGPIPE under `set -o pipefail`.
cut -f1 "$tmp_map" | sort | uniq -c \
  | awk -v min="$PER_PERSON" '$1+0 >= min { print $1"\t"$2 }' \
  | sort -k1,1nr -k2,2 \
  | awk -F'\t' -v k="$PERSONS" 'NR<=k {print $2}' > "$tmp_persons"

navail=$(wc -l < "$tmp_persons" | tr -d ' ')
[ "$navail" -ge "$PERSONS" ] || { echo "ERROR: only $navail persons have >= $PER_PERSON eligible images; need $PERSONS" >&2; exit 2; }

# Idempotent clear: prior manifest persons + current selection.
if [ -f "$MANIFEST" ]; then
  while read -r oldp _; do
    [ -n "${oldp:-}" ] && find "$OUT" -maxdepth 1 -type f -name "${oldp}_*" -delete 2>/dev/null || true
  done < "$MANIFEST"
fi
while IFS= read -r p; do
  find "$OUT" -maxdepth 1 -type f -name "${p}_*" -delete 2>/dev/null || true
done < "$tmp_persons"

: > "$MANIFEST"; : > "$tmp_rows"
total=0
while IFS= read -r p; do
  label=$(printf '%s' "$p" | tr '_' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1')
  n=0
  while IFS= read -r f; do
    cp "$f" "$OUT/$(basename "$f")"
    printf '| %s | %s | %s | %s |\n' "$(basename "$f")" "$label" "$LICENSE_NOTE" "$ADDED" >> "$tmp_rows"
    n=$((n + 1)); total=$((total + 1))
  done < <(awk -F'\t' -v p="$p" -v k="$PER_PERSON" '$1==p && c<k {print $2; c++}' "$tmp_map")
  printf '%s %s\n' "$p" "$n" >> "$MANIFEST"
done < "$tmp_persons"

echo "==> Selected $navail persons x $PER_PERSON = $total images into $OUT"

# Regenerate the provenance table between the SEED-PROVENANCE markers in README.md.
if [ -f "$README" ] && grep -q 'SEED-PROVENANCE:START' "$README" && grep -q 'SEED-PROVENANCE:END' "$README"; then
  start_line=$(grep -n 'SEED-PROVENANCE:START' "$README" | head -1 | cut -d: -f1)
  end_line=$(grep -n 'SEED-PROVENANCE:END' "$README" | head -1 | cut -d: -f1)
  {
    head -n "$start_line" "$README"
    printf '| File | Subject label (for assertions) | Source / license | Added |\n'
    printf '| --- | --- | --- | --- |\n'
    cat "$tmp_rows"
    tail -n +"$end_line" "$README"
  } > "$tmp_readme"
  mv "$tmp_readme" "$README"
  echo "==> Regenerated provenance table in $README ($total rows)"
else
  echo "WARN: $README missing SEED-PROVENANCE markers — table not updated" >&2
fi
