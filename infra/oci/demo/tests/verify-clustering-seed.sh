#!/usr/bin/env bash
# E15-29 Slice 1: assert the clustering seed bundle is correctly populated.
#   - exactly PERSONS*PER_PERSON (+ guided-manifest files) eligible images in OUT, zero webp
#   - every image is TRUE image/jpeg or image/png by content (magic bytes),
#     not just by extension (E15-29-BR-02: webp/avif renamed .jpg break the decoder)
#   - manifest lists PERSONS persons, each with >= PER_PERSON
#   - each manifest person has >= PER_PERSON files on disk
#   - provenance table filled (no placeholder; >= expected data rows)
#
# Usage: bash infra/oci/demo/tests/verify-clustering-seed.sh
set -euo pipefail

SEED_DIR="${SEED_DIR:-infra/oci/demo/seed}"
OUT="${OUT:-$SEED_DIR/media}"
MANIFEST="${MANIFEST:-$SEED_DIR/clustering-manifest.txt}"
README="${README:-$SEED_DIR/README.md}"
PERSONS="${PERSONS:-20}"
PER_PERSON="${PER_PERSON:-5}"
GUIDED_MANIFEST="${GUIDED_MANIFEST:-$SEED_DIR/guided-manifest.txt}"
# GUIDESEED-1: media/ also holds the guided-prototype people written by
# select-guided-seed.sh; their count comes from guided-manifest.txt (0 when absent).
guided=0
if [[ -f "$GUIDED_MANIFEST" ]]; then
  guided=$(awk '/^[a-z0-9_]+ [0-9]+$/ { s += $2 } END { print s + 0 }' "$GUIDED_MANIFEST")
fi
EXPECT=$((PERSONS * PER_PERSON + guided))
fail=0

n=$(find "$OUT" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) 2>/dev/null | wc -l | tr -d ' ')
[[ "$n" -eq "$EXPECT" ]] || { echo "FAIL: expected $EXPECT images in $OUT, found $n" >&2; fail=1; }

w=$(find "$OUT" -maxdepth 1 -type f -iname '*.webp' 2>/dev/null | wc -l | tr -d ' ')
[[ "$w" -eq 0 ]] || { echo "FAIL: $w .webp files in $OUT (glob excludes webp)" >&2; fail=1; }

# Content (magic-byte) assertion — extension alone is insufficient: webp/avif files
# carrying .jpg/.jpeg/.png names pass the glob but break the recognition decoder and
# WP media handling (E15-29-BR-02). Require every image to be TRUE image/jpeg|image/png.
bad_content=0
while IFS= read -r f; do
  [[ -n "$f" ]] || continue
  mt=$(file -b --mime-type "$f" 2>/dev/null || echo unknown)
  case "$mt" in
    image/jpeg|image/png) : ;;
    *) echo "FAIL: $(basename "$f") is '$mt' by content, not image/jpeg|image/png" >&2; bad_content=$((bad_content + 1)) ;;
  esac
done < <(find "$OUT" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) 2>/dev/null)
[[ "$bad_content" -eq 0 ]] || { echo "FAIL: $bad_content image(s) have non-jpeg/png content" >&2; fail=1; }

if [[ ! -f "$MANIFEST" ]]; then
  echo "FAIL: manifest missing at $MANIFEST" >&2; fail=1
else
  lines=$(grep -cE '^[a-z0-9_]+ [0-9]+$' "$MANIFEST" || true)
  [[ "$lines" -eq "$PERSONS" ]] || { echo "FAIL: manifest has $lines persons, expected $PERSONS" >&2; fail=1; }
  while read -r p c; do
    [[ -z "${p:-}" ]] && continue
    [[ "${c:-0}" -ge "$PER_PERSON" ]] || { echo "FAIL: manifest person $p has $c < $PER_PERSON" >&2; fail=1; }
    actual=$(find "$OUT" -maxdepth 1 -type f -name "${p}_*" 2>/dev/null | wc -l | tr -d ' ')
    [[ "$actual" -ge "$PER_PERSON" ]] || { echo "FAIL: $p has $actual files on disk < $PER_PERSON" >&2; fail=1; }
  done < "$MANIFEST"
fi

if grep -q '_(operator fills)_' "$README" 2>/dev/null; then
  echo "FAIL: placeholder provenance row remains in $README" >&2; fail=1
fi
rows=$(grep -cE '^\| [a-z0-9_]+\.(jpg|jpeg|png) \|' "$README" 2>/dev/null || true)
[[ "$rows" -ge "$EXPECT" ]] || { echo "FAIL: provenance rows $rows < $EXPECT in $README" >&2; fail=1; }

if [[ "$fail" -ne 0 ]]; then echo "verify-clustering-seed: FAIL" >&2; exit 1; fi
echo "verify-clustering-seed: OK ($n images = $PERSONS persons x $PER_PERSON + $guided guided, $rows provenance rows)"
