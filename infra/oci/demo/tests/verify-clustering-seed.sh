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
# select-guided-seed.sh. Every guided-manifest row is validated individually
# (exact 1..N files + MIME). CRLF is stripped before parse; leftover malformed
# lines fail closed instead of counting as guided=0.
fail=0
guided=0

is_image_name() {
  case "$1" in
    *.jpg|*.jpeg|*.png|*.JPG|*.JPEG|*.PNG) return 0 ;;
    *) return 1 ;;
  esac
}

count_prefix_files() {
  _dir=$1
  _prefix=$2
  _n=0
  for _f in "$_dir"/${_prefix}_*; do
    [[ -f "$_f" ]] || continue
    _n=$((_n + 1))
  done
  printf '%s\n' "$_n"
}

find_guided_file() {
  _dir=$1
  _slug=$2
  _idx=$3
  for _ext in jpg jpeg png JPG JPEG PNG; do
    if [[ -f "$_dir/${_slug}_${_idx}.$_ext" ]]; then
      printf '%s\n' "$_dir/${_slug}_${_idx}.$_ext"
      return 0
    fi
  done
  return 1
}

if [[ -f "$GUIDED_MANIFEST" ]]; then
  while IFS= read -r line || [[ -n "${line:-}" ]]; do
    line=${line%$'\r'}
    [[ -z "$line" ]] && continue
    if [[ ! "$line" =~ ^[a-z0-9_]+\ [0-9]+$ ]]; then
      echo "FAIL: malformed guided-manifest line (CRLF stripped): $line" >&2
      fail=1
      continue
    fi
    set -- $line
    p=$1
    c=$2
    guided=$((guided + c))
    i=1
    while [[ "$i" -le "$c" ]]; do
      if ! gfile=$(find_guided_file "$OUT" "$p" "$i"); then
        echo "FAIL: guided $p missing exact file ${p}_${i}.jpg (or jpeg/png)" >&2
        fail=1
        i=$((i + 1))
        continue
      fi
      gmt=$(file -b --mime-type "$gfile" 2>/dev/null || echo unknown)
      case "$gmt" in
        image/jpeg|image/png) : ;;
        *) echo "FAIL: guided $(basename "$gfile") is '$gmt' by content, not image/jpeg|image/png" >&2; fail=1 ;;
      esac
      i=$((i + 1))
    done
  done < "$GUIDED_MANIFEST"
fi
EXPECT=$((PERSONS * PER_PERSON + guided))

n=0
w=0
for f in "$OUT"/*; do
  [[ -f "$f" ]] || continue
  base=$(basename "$f")
  case "$base" in
    *.webp|*.WEBP) w=$((w + 1)) ;;
  esac
  if is_image_name "$base"; then
    n=$((n + 1))
  fi
done
[[ "$n" -eq "$EXPECT" ]] || { echo "FAIL: expected $EXPECT images in $OUT, found $n" >&2; fail=1; }

[[ "$w" -eq 0 ]] || { echo "FAIL: $w .webp files in $OUT (glob excludes webp)" >&2; fail=1; }

# Content (magic-byte) assertion — extension alone is insufficient: webp/avif files
# carrying .jpg/.jpeg/.png names pass the glob but break the recognition decoder and
# WP media handling (E15-29-BR-02). Require every image to be TRUE image/jpeg|image/png.
bad_content=0
for f in "$OUT"/*; do
  [[ -f "$f" ]] || continue
  is_image_name "$(basename "$f")" || continue
  mt=$(file -b --mime-type "$f" 2>/dev/null || echo unknown)
  case "$mt" in
    image/jpeg|image/png) : ;;
    *) echo "FAIL: $(basename "$f") is '$mt' by content, not image/jpeg|image/png" >&2; bad_content=$((bad_content + 1)) ;;
  esac
done
[[ "$bad_content" -eq 0 ]] || { echo "FAIL: $bad_content image(s) have non-jpeg/png content" >&2; fail=1; }

if [[ ! -f "$MANIFEST" ]]; then
  echo "FAIL: manifest missing at $MANIFEST" >&2; fail=1
else
  lines=0
  while IFS= read -r line || [[ -n "${line:-}" ]]; do
    line=${line%$'\r'}
    [[ -z "$line" ]] && continue
    if [[ "$line" =~ ^[a-z0-9_]+\ [0-9]+$ ]]; then
      lines=$((lines + 1))
    fi
  done < "$MANIFEST"
  [[ "$lines" -eq "$PERSONS" ]] || { echo "FAIL: manifest has $lines persons, expected $PERSONS" >&2; fail=1; }
  while read -r p c; do
    [[ -z "${p:-}" ]] && continue
    p=${p%$'\r'}
    c=${c%$'\r'}
    [[ "${c:-0}" -ge "$PER_PERSON" ]] || { echo "FAIL: manifest person $p has $c < $PER_PERSON" >&2; fail=1; }
    actual=$(count_prefix_files "$OUT" "$p")
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
