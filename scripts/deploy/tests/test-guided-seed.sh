#!/usr/bin/env bash
# GUIDESEED-1: contract suite for infra/oci/demo/seed/select-guided-seed.sh.
# Runs the selector against a scratch OUT/MANIFEST/README so the real seed
# bundle is never touched. Asserts: deterministic <slug>_<n>.jpg naming, the
# committed guided manifest counts, content-verified JPEGs, provenance rows
# regenerated between GUIDED-PROVENANCE markers (SEED-PROVENANCE untouched),
# idempotent re-run, and refusal when a bundled source image is missing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SELECT="$REPO_ROOT/infra/oci/demo/seed/select-guided-seed.sh"
ASSETS="$REPO_ROOT/apps/prototype-wp-alt-context/js/admin/assets/guided"
fails=0
pass() { echo "ok - $1"; }
fail() { echo "FAIL - $1" >&2; fails=$((fails + 1)); }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
OUT="$tmp/media"; MANIFEST="$tmp/guided-manifest.txt"; README="$tmp/README.md"
cat > "$README" <<'MD'
# scratch
<!-- SEED-PROVENANCE:START -->
| File | Subject label (for assertions) | Source / license | Added |
| --- | --- | --- | --- |
| sigourney_weaver_1.jpg | Sigourney Weaver | celebs01 | 2026-06-13 |
<!-- SEED-PROVENANCE:END -->
<!-- GUIDED-PROVENANCE:START -->
<!-- GUIDED-PROVENANCE:END -->
MD

[ -x "$SELECT" ] && pass "selector is executable" || fail "selector missing or not executable: $SELECT"
bash -n "$SELECT" && pass "selector parses (bash -n)" || fail "selector has a syntax error"

OUT="$OUT" MANIFEST="$MANIFEST" README="$README" bash "$SELECT" >/dev/null \
  && pass "selector exits 0 against the bundled assets" || fail "selector exited non-zero"

for f in katy_perry_1.jpg katy_perry_2.jpg katy_perry_3.jpg justin_trudeau_1.jpg justin_trudeau_2.jpg tribeca_press_1.jpg; do
  [ -f "$OUT/$f" ] && pass "copied $f" || fail "missing $OUT/$f"
done
n=$(find "$OUT" -maxdepth 1 -type f | wc -l | tr -d ' ')
[ "$n" -eq 6 ] && pass "exactly 6 files in OUT" || fail "expected 6 files in OUT, found $n"

while IFS= read -r f; do
  mt=$(file -b --mime-type "$f")
  [ "$mt" = "image/jpeg" ] || fail "$(basename "$f") is $mt, not image/jpeg"
done < <(find "$OUT" -maxdepth 1 -type f)
pass "content check ran on every copied file"

cmp -s "$ASSETS/guided-katy-perry-2026.jpg" "$OUT/katy_perry_1.jpg" && pass "katy_perry_1 is the 2026 Hotel Café photo" || fail "katy_perry_1 byte mismatch"
cmp -s "$ASSETS/guided-press-tribeca-2026.jpg" "$OUT/tribeca_press_1.jpg" && pass "tribeca_press_1 is the press photo" || fail "tribeca_press_1 byte mismatch"

expected_manifest=$'justin_trudeau 2\nkaty_perry 3\ntribeca_press 1'
[ "$(cat "$MANIFEST")" = "$expected_manifest" ] && pass "manifest lists justin_trudeau 2 / katy_perry 3 / tribeca_press 1" \
  || fail "manifest content unexpected: $(tr '\n' '|' < "$MANIFEST")"
diff -q "$MANIFEST" "$REPO_ROOT/infra/oci/demo/seed/guided-manifest.txt" >/dev/null \
  && pass "committed guided-manifest.txt matches the generated one" || fail "committed infra/oci/demo/seed/guided-manifest.txt is stale"

rows=$(grep -cE '^\| (katy_perry|justin_trudeau|tribeca_press)_[0-9]+\.jpg \|' "$README" || true)
[ "$rows" -eq 6 ] && pass "6 guided provenance rows" || fail "expected 6 guided provenance rows, found $rows"
grep -q 'sigourney_weaver_1.jpg' "$README" && pass "SEED-PROVENANCE block untouched" || fail "SEED-PROVENANCE block was clobbered"
grep -q 'CC BY-SA 4.0' "$README" && grep -q 'EU reuse licence' "$README" && grep -q 'public domain' "$README" \
  && pass "licence text present per source" || fail "licence text missing"
grep -q '| Katy Perry |' "$README" && grep -q '| Justin Trudeau |' "$README" && pass "subject labels match roster names" || fail "subject labels wrong"
start=$(grep -n 'GUIDED-PROVENANCE:START' "$README" | cut -d: -f1); end=$(grep -n 'GUIDED-PROVENANCE:END' "$README" | cut -d: -f1)
[ "$((end - start))" -eq 9 ] && pass "guided block is header + separator + 6 rows + END" || fail "guided block has $((end - start - 1)) lines between markers"

OUT="$OUT" MANIFEST="$MANIFEST" README="$README" bash "$SELECT" >/dev/null
n2=$(find "$OUT" -maxdepth 1 -type f | wc -l | tr -d ' '); rows2=$(grep -cE '^\| (katy_perry|justin_trudeau|tribeca_press)_[0-9]+\.jpg \|' "$README" || true)
[ "$n2" -eq 6 ] && [ "$rows2" -eq 6 ] && pass "re-run is idempotent (6 files, 6 rows)" || fail "re-run drifted: $n2 files, $rows2 rows"

stale="$tmp/stale"; mkdir -p "$stale"; cp "$ASSETS"/*.jpg "$stale"/; rm "$stale/guided-katy-perry-2019.jpg"
set +e
SRC="$stale" OUT="$tmp/out2" MANIFEST="$tmp/m2" README="$README" bash "$SELECT" >/dev/null 2>&1; rc=$?
set -e
[ "$rc" -eq 2 ] && pass "refuses (exit 2) when a bundled source image is missing" || fail "expected exit 2 on missing source, got $rc"
[ ! -f "$tmp/m2" ] || [ ! -s "$tmp/m2" ] && pass "no manifest written on refusal" || fail "manifest written despite refusal"

if [ "$fails" -ne 0 ]; then echo "test-guided-seed: $fails failure(s)" >&2; exit 1; fi
echo "test-guided-seed: all assertions passed"
