#!/usr/bin/env bash
# E15-29 Slice 1: deterministically select a clustering-showcase seed.
#
# Picks the top PERSONS persons by eligible-image count (desc; ties alphabetical)
# from a source dir of `<person>_<n>.<ext>` files, copies the first PER_PERSON
# eligible images of each into the demo seed bundle, writes a manifest, and
# regenerates the provenance table in seed/README.md between the SEED-PROVENANCE markers.
#
# Eligible = .jpg/.jpeg/.png BY EXTENSION *and* true image/jpeg|image/png BY CONTENT.
# Content validation is mandatory: the source mixes in webp/avif files renamed to
# image extensions, which the recognition decoder cannot read (E15-29-BR-02). Extension
# alone admits them; magic-byte filtering excludes them. import.sh/sync-demo.sh skip webp too.
#
# Idempotent: clears any prior manifest-listed selection from OUT before copying.
# Refuses (exit 2) if fewer than PERSONS persons have >= PER_PERSON eligible images.
# Portable to bash 3.2 (macOS) and bash 5 (VM): no mapfile / associative arrays.
#
# Usage:
#   SRC=/path/to/celebs01 PERSONS=20 PER_PERSON=5 README=/path/to/README.md \
#     bash infra/oci/demo/seed/select-clustering-seed.sh
# The README rights note is derived from BASIS, SOURCE and NOTICE; LICENSE_NOTE
# is rejected so its claim cannot diverge from the rights ledger.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_DIR="$SCRIPT_DIR"
README="${README:-$SEED_DIR/README.md}"
SRC="${SRC:-/Users/daniel/Development/altcontext-marketing-monorepo/static/input-images/celebs01}"
PERSONS="${PERSONS:-20}"
PER_PERSON="${PER_PERSON:-5}"
OUT="${OUT:-$SEED_DIR/media}"
MANIFEST="${MANIFEST:-$SEED_DIR/clustering-manifest.txt}"
RIGHTS="${RIGHTS:-$SEED_DIR/clustering-rights.tsv}"
BASIS="${BASIS:-editorial_fair_use}"
NOTICE="${NOTICE:-takedown_on_request}"
SOURCE="${SOURCE:-celebs01}"
ADDED="${ADDED:-2026-06-13}"
STRIP='s#.*/##; s/_[0-9]+\.(jpg|jpeg|png|JPG|JPEG|PNG)$//'

case "$BASIS" in
  editorial_fair_use|cc_by|cc_by_sa|public_domain|eu_reuse|generated) ;;
  *) echo "ERROR: unrecognized BASIS: $BASIS" >&2; exit 2 ;;
esac
case "$NOTICE" in
  takedown_on_request|attribution_required|none) ;;
  *) echo "ERROR: unrecognized NOTICE: $NOTICE" >&2; exit 2 ;;
esac
if [ "${LICENSE_NOTE+x}" = x ]; then
  echo "ERROR: LICENSE_NOTE is derived from BASIS, SOURCE and NOTICE" >&2
  exit 2
fi
case "$BASIS" in
  editorial_fair_use) BASIS_LABEL='editorial/fair-use' ;;
  cc_by) BASIS_LABEL='CC BY 4.0' ;;
  cc_by_sa) BASIS_LABEL='CC BY-SA 4.0' ;;
  public_domain) BASIS_LABEL='public domain' ;;
  eu_reuse) BASIS_LABEL='EU reuse licence' ;;
  generated) BASIS_LABEL='generated' ;;
esac
case "$NOTICE" in
  takedown_on_request) NOTICE_LABEL='takedown on request' ;;
  attribution_required) NOTICE_LABEL='attribution required' ;;
  none) NOTICE_LABEL='no notice' ;;
esac
LICENSE_NOTE="$SOURCE — $BASIS_LABEL demo ($NOTICE_LABEL)"

[ -d "$SRC" ] || { echo "ERROR: SRC not found: $SRC" >&2; exit 2; }
mkdir -p "$OUT"

tmp_elig="$(mktemp)"; tmp_map="$(mktemp)"; tmp_persons="$(mktemp)"; tmp_rows="$(mktemp)"; tmp_rights_rows="$(mktemp)"; tmp_readme="$(mktemp)"; tmp_rights=''
trap 'rm -f "$tmp_elig" "$tmp_map" "$tmp_persons" "$tmp_rows" "$tmp_rights_rows" "$tmp_readme"; [ -z "$tmp_rights" ] || rm -f "$tmp_rights"' EXIT

# Eligibility = jpg/jpeg/png extension AND true image/jpeg|image/png content. Batch
# `file --mime-type` (portable; few invocations), keep only paths whose detected MIME
# is jpeg/png — drops webp/avif/gif renamed with image extensions (E15-29-BR-02).
find "$SRC" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) -exec file --mime-type {} + 2>/dev/null \
  | awk -F': ' '{ mt = $2; gsub(/^[ \t]+|[ \t]+$/, "", mt); if (mt == "image/jpeg" || mt == "image/png") print $1 }' \
  | sort > "$tmp_elig"
[ -s "$tmp_elig" ] || { echo "ERROR: no eligible (true image/jpeg|image/png) files under $SRC" >&2; exit 2; }

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

: > "$MANIFEST"; : > "$tmp_rows"; : > "$tmp_rights_rows"
total=0
while IFS= read -r p; do
  label=$(printf '%s' "$p" | tr '_' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1')
  n=0
  while IFS= read -r f; do
    cp "$f" "$OUT/$(basename "$f")"
    printf '| %s | %s | %s | %s |\n' "$(basename "$f")" "$label" "$LICENSE_NOTE" "$ADDED" >> "$tmp_rows"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(basename "$f")" "$label" "$BASIS" "$SOURCE" "$NOTICE" "$ADDED" >> "$tmp_rights_rows"
    n=$((n + 1)); total=$((total + 1))
  done < <(awk -F'\t' -v p="$p" -v k="$PER_PERSON" '$1==p && c<k {print $2; c++}' "$tmp_map")
  printf '%s %s\n' "$p" "$n" >> "$MANIFEST"
done < "$tmp_persons"

echo "==> Selected $navail persons x $PER_PERSON = $total images into $OUT"

# Write the rights ledger atomically after selection has completed.
tmp_rights="$(mktemp "${RIGHTS}.tmp.XXXXXX")"
{
  printf 'file\tsubject\tbasis\tsource\tnotice\tadded\n'
  LC_ALL=C sort -t "$(printf '\t')" -k1,1 "$tmp_rights_rows"
} > "$tmp_rights"
mv "$tmp_rights" "$RIGHTS"
tmp_rights=''
echo "==> Wrote rights ledger to $RIGHTS ($total rows)"

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
