#!/usr/bin/env bash
# GUIDESEED-1: contract suite for infra/oci/demo/seed/select-guided-seed.sh.
# Runs the selector against a scratch OUT/MANIFEST/README so the real seed
# bundle is never touched. Asserts: deterministic <slug>_<n>.<source extension>
# naming, the committed guided manifest counts, content-verified images, provenance rows
# regenerated between GUIDED-PROVENANCE markers (SEED-PROVENANCE untouched),
# idempotent re-run, and refusal when a bundled source image is missing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SELECT="$REPO_ROOT/infra/oci/demo/seed/select-guided-seed.sh"
VERIFY="$REPO_ROOT/infra/oci/demo/tests/verify-clustering-seed.sh"
ASSETS="$REPO_ROOT/apps/prototype-wp-alt-context/js/admin/assets/guided"
fails=0
pass() { echo "ok - $1"; }
fail() { echo "FAIL - $1" >&2; fails=$((fails + 1)); }

count_files() {
  local d="$1" n=0 f
  for f in "$d"/*; do
    [ -f "$f" ] || continue
    n=$((n + 1))
  done
  printf '%s\n' "$n"
}

run_verify() {
  local seed="$1" persons="$2" per_person="$3"
  SEED_DIR="$seed" OUT="$seed/media" MANIFEST="$seed/clustering-manifest.txt" \
    README="$seed/README.md" RIGHTS="$seed/guided-rights.tsv" GUIDED_MANIFEST="$seed/guided-manifest.txt" \
    PERSONS="$persons" PER_PERSON="$per_person" \
    bash "$VERIFY"
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
OUT="$tmp/media"; MANIFEST="$tmp/guided-manifest.txt"; README="$tmp/README.md"; RIGHTS="$tmp/guided-rights.tsv"
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
[ -f "$VERIFY" ] && bash -n "$VERIFY" && pass "verifier parses (bash -n)" || fail "verifier missing or has a syntax error"

OUT="$OUT" MANIFEST="$MANIFEST" README="$README" RIGHTS="$RIGHTS" bash "$SELECT" >/dev/null \
  && pass "selector exits 0 against the bundled assets" || fail "selector exited non-zero"

if rights_mode=$(stat -c %a "$RIGHTS" 2>/dev/null); then
  :
else
  rights_mode=$(stat -f %Lp "$RIGHTS" 2>/dev/null || echo unknown)
fi
[ "$rights_mode" = "644" ] && pass "generated rights ledger has mode 644" \
  || fail "generated rights ledger has mode $rights_mode, expected 644"

for f in katy_perry_1.jpg katy_perry_2.jpg katy_perry_3.jpg justin_trudeau_1.jpg justin_trudeau_2.jpg tribeca_press_1.jpg coachella_press_1.webp; do
  [ -f "$OUT/$f" ] && pass "copied $f" || fail "missing $OUT/$f"
done
n=$(count_files "$OUT")
[ "$n" -eq 7 ] && pass "exactly 7 files in OUT" || fail "expected 7 files in OUT, found $n"

for f in "$OUT"/*; do
  [ -f "$f" ] || continue
  mt=$(file -b --mime-type "$f")
  if [ "$(basename "$f")" = "coachella_press_1.webp" ]; then
    [ "$mt" = "image/webp" ] && pass "coachella_press_1.webp is image/webp" \
      || fail "coachella_press_1.webp is $mt, not image/webp"
  else
    [ "$mt" = "image/jpeg" ] || fail "$(basename "$f") is $mt, not image/jpeg"
  fi
done
pass "content check ran on every copied file"

# GUIDESEED-1-GR-05: every bundled source maps to the exact output bytes.
cmp -s "$ASSETS/guided-katy-perry-2026.jpg" "$OUT/katy_perry_1.jpg" && pass "katy_perry_1 is the 2026 Hotel Café photo" || fail "katy_perry_1 byte mismatch"
cmp -s "$ASSETS/guided-katy-perry-2019.jpg" "$OUT/katy_perry_2.jpg" && pass "katy_perry_2 is the 2019 photo" || fail "katy_perry_2 byte mismatch"
cmp -s "$ASSETS/guided-katy-perry-2016.jpg" "$OUT/katy_perry_3.jpg" && pass "katy_perry_3 is the 2016 photo" || fail "katy_perry_3 byte mismatch"
cmp -s "$ASSETS/guided-justin-trudeau-2025.jpg" "$OUT/justin_trudeau_1.jpg" && pass "justin_trudeau_1 is the 2025 photo" || fail "justin_trudeau_1 byte mismatch"
cmp -s "$ASSETS/guided-justin-trudeau-2023.jpg" "$OUT/justin_trudeau_2.jpg" && pass "justin_trudeau_2 is the 2023 photo" || fail "justin_trudeau_2 byte mismatch"
cmp -s "$ASSETS/guided-press-tribeca-2026.jpg" "$OUT/tribeca_press_1.jpg" && pass "tribeca_press_1 is the press photo" || fail "tribeca_press_1 byte mismatch"

expected_manifest=$'coachella_press 1\njustin_trudeau 2\nkaty_perry 3\ntribeca_press 1'
[ "$(cat "$MANIFEST")" = "$expected_manifest" ] && pass "manifest lists coachella_press 1 / justin_trudeau 2 / katy_perry 3 / tribeca_press 1" \
  || fail "manifest content unexpected: $(tr '\n' '|' < "$MANIFEST")"
diff -q "$MANIFEST" "$REPO_ROOT/infra/oci/demo/seed/guided-manifest.txt" >/dev/null \
  && pass "committed guided-manifest.txt matches the generated one" || fail "committed infra/oci/demo/seed/guided-manifest.txt is stale"

expected_rights_header=$'file\tsubject\tbasis\tsource\tnotice\tadded'
[ "$(head -n 1 "$RIGHTS")" = "$expected_rights_header" ] \
  && pass "rights ledger has the exact header" || fail "rights ledger header is unexpected"
rights_rows=$(awk 'END { print NR - 1 }' "$RIGHTS")
[ "$rights_rows" -eq "$n" ] && pass "rights ledger has one data row per guided media file" \
  || fail "expected $n rights rows, found $rights_rows"
rights_match=1
for f in "$OUT"/*; do
  [ -f "$f" ] || continue
  base=$(basename "$f")
  matches=$(awk -F '\t' -v file="$base" 'NR > 1 && $1 == file { count++ } END { print count + 0 }' "$RIGHTS")
  if [ "$matches" -ne 1 ]; then
    fail "rights ledger has $matches rows for $base"
    rights_match=0
  fi
done
[ "$rights_match" -eq 1 ] && pass "every guided media file has exactly one rights row"
awk -F '\t' '$1 == "coachella_press_1.webp" && $3 == "unrecorded" { found = 1 } END { exit !found }' "$RIGHTS" \
  && pass "coachella row records unrecorded basis" || fail "coachella row lacks unrecorded basis"
awk -F '\t' '$1 == "katy_perry_3.jpg" && $3 == "public_domain" { found = 1 } END { exit !found }' "$RIGHTS" \
  && pass "Katy Perry public-domain row records public_domain basis" || fail "Katy Perry public-domain row lacks public_domain basis"
diff -q "$RIGHTS" "$REPO_ROOT/infra/oci/demo/seed/guided-rights.tsv" >/dev/null \
  && pass "committed guided-rights.tsv matches the generated one" || fail "committed infra/oci/demo/seed/guided-rights.tsv is stale"

rows=$(grep -cE '^\| (coachella_press|katy_perry|justin_trudeau|tribeca_press)_[0-9]+\.(jpg|webp) \|' "$README" || true)
[ "$rows" -eq 7 ] && pass "7 guided provenance rows" || fail "expected 7 guided provenance rows, found $rows"
grep -q 'sigourney_weaver_1.jpg' "$README" && pass "SEED-PROVENANCE block untouched" || fail "SEED-PROVENANCE block was clobbered"
grep -q 'CC BY-SA 4.0' "$README" && grep -q 'EU reuse licence' "$README" && grep -q 'public domain' "$README" \
  && pass "licence text present per source" || fail "licence text missing"
grep -q '| Katy Perry |' "$README" && grep -q '| Justin Trudeau |' "$README" && pass "subject labels match roster names" || fail "subject labels wrong"
start=$(grep -n 'GUIDED-PROVENANCE:START' "$README" | cut -d: -f1); end=$(grep -n 'GUIDED-PROVENANCE:END' "$README" | cut -d: -f1)
[ "$((end - start))" -eq 10 ] && pass "guided block is header + separator + 7 rows + END" || fail "guided block has $((end - start - 1)) lines between markers"

OUT="$OUT" MANIFEST="$MANIFEST" README="$README" RIGHTS="$RIGHTS" bash "$SELECT" >/dev/null
n2=$(count_files "$OUT"); rows2=$(grep -cE '^\| (coachella_press|katy_perry|justin_trudeau|tribeca_press)_[0-9]+\.(jpg|webp) \|' "$README" || true)
[ "$n2" -eq 7 ] && [ "$rows2" -eq 7 ] && pass "re-run is idempotent (7 files, 7 rows)" || fail "re-run drifted: $n2 files, $rows2 rows"

# GUIDESEED-1-GR-01: a clustering file whose name collides with a guided slug
# must survive a rerun. Cleanup may only remove exact owned 1..N files.
sentinel="$OUT/katy_perry_99.jpg"
cp "$ASSETS/guided-katy-perry-2016.jpg" "$sentinel"
OUT="$OUT" MANIFEST="$MANIFEST" README="$README" RIGHTS="$RIGHTS" bash "$SELECT" >/dev/null
[ -f "$sentinel" ] && pass "GR-01 clustering sentinel katy_perry_99.jpg survived rerun" \
  || fail "GR-01 clustering sentinel was deleted on guided rerun"
n_gr01=$(count_files "$OUT")
[ "$n_gr01" -eq 8 ] && pass "GR-01 OUT keeps 7 guided files plus the sentinel" \
  || fail "GR-01 expected 8 files (7 guided + sentinel), found $n_gr01"

# GUIDESEED-1-GR-06: cleanup must work without GNU find -maxdepth and must not
# swallow content-changing failures.
if grep -q -- '-maxdepth' "$SELECT"; then
  fail "GR-06 selector still uses find -maxdepth"
else
  pass "GR-06 selector does not use find -maxdepth"
fi
stub_bin="$tmp/stub-bin"
mkdir -p "$stub_bin"
cat > "$stub_bin/find" <<'STUB'
#!/bin/sh
echo "GR-06 stub find invoked; GNU -maxdepth is not available: $*" >&2
exit 1
STUB
chmod +x "$stub_bin/find"
set +e
PATH="$stub_bin:$PATH" OUT="$OUT" MANIFEST="$MANIFEST" README="$README" RIGHTS="$RIGHTS" bash "$SELECT" >/dev/null 2>"$tmp/gr06.err"
gr06_rc=$?
set -e
[ "$gr06_rc" -eq 0 ] && pass "GR-06 selector reruns when find(1) rejects -maxdepth" \
  || fail "GR-06 selector exited $gr06_rc when find is a non-GNU stub: $(tr '\n' ' ' < "$tmp/gr06.err")"
[ -f "$sentinel" ] && pass "GR-06 clustering sentinel still present after stub-find rerun" \
  || fail "GR-06 clustering sentinel was deleted when find was stubbed"
n_gr06=$(count_files "$OUT")
[ "$n_gr06" -eq 8 ] && pass "GR-06 OUT still has 7 guided files plus the sentinel" \
  || fail "GR-06 expected 8 files after stub-find rerun, found $n_gr06"
cmp -s "$ASSETS/guided-katy-perry-2026.jpg" "$OUT/katy_perry_1.jpg" \
  && pass "GR-06 rerun still copied owned guided targets" || fail "GR-06 rerun did not refresh katy_perry_1.jpg"

# GUIDESEED-1-GR-02: missing guided image replaced by an unrelated valid image must FAIL.
gr02="$tmp/gr02"
mkdir -p "$gr02/media"
cp "$ASSETS/guided-press-tribeca-2026.jpg" "$gr02/media/unrelated_1.jpg"
: > "$gr02/clustering-manifest.txt"
printf 'katy_perry 1\n' > "$gr02/guided-manifest.txt"
cat > "$gr02/README.md" <<'MD'
| unrelated_1.jpg | filler | test | 2026-01-01 |
MD
set +e
run_verify "$gr02" 0 0 >"$gr02/out" 2>"$gr02/err"
gr02_rc=$?
set -e
[ "$gr02_rc" -ne 0 ] && pass "GR-02 missing guided image replaced by unrelated valid image fails verification" \
  || fail "GR-02 verifier reported OK with missing guided image: $(tr '\n' ' ' < "$gr02/out") $(tr '\n' ' ' < "$gr02/err")"

# GUIDESEED-1-GR-03: CRLF guided manifests must not be counted as zero.
gr03_false="$tmp/gr03-false"
mkdir -p "$gr03_false/media"
cp "$ASSETS/guided-katy-perry-2026.jpg" "$gr03_false/media/cluster_person_1.jpg"
printf 'cluster_person 1\n' > "$gr03_false/clustering-manifest.txt"
printf 'katy_perry 1\r\n' > "$gr03_false/guided-manifest.txt"
cat > "$gr03_false/README.md" <<'MD'
| cluster_person_1.jpg | cluster | test | 2026-01-01 |
MD
set +e
run_verify "$gr03_false" 1 1 >"$gr03_false/out" 2>"$gr03_false/err"
gr03_false_rc=$?
set -e
[ "$gr03_false_rc" -ne 0 ] && pass "GR-03 CRLF guided manifest with missing guided file does not false-pass" \
  || fail "GR-03 CRLF manifest counted as zero and passed: $(tr '\n' ' ' < "$gr03_false/out") $(tr '\n' ' ' < "$gr03_false/err")"

gr03_ok="$tmp/gr03-ok"
mkdir -p "$gr03_ok/media"
cp "$ASSETS/guided-katy-perry-2026.jpg" "$gr03_ok/media/cluster_person_1.jpg"
cp "$ASSETS/guided-katy-perry-2019.jpg" "$gr03_ok/media/katy_perry_1.jpg"
printf 'cluster_person 1\n' > "$gr03_ok/clustering-manifest.txt"
printf 'katy_perry 1\r\n' > "$gr03_ok/guided-manifest.txt"
cat > "$gr03_ok/README.md" <<'MD'
| cluster_person_1.jpg | cluster | test | 2026-01-01 |
| katy_perry_1.jpg | Katy Perry | test | 2026-01-01 |
MD
set +e
run_verify "$gr03_ok" 1 1 >"$gr03_ok/out" 2>"$gr03_ok/err"
gr03_ok_rc=$?
set -e
[ "$gr03_ok_rc" -eq 0 ] && pass "GR-03 CRLF guided manifest is normalised and validates present files" \
  || fail "GR-03 CRLF manifest with valid files was rejected: $(tr '\n' ' ' < "$gr03_ok/out") $(tr '\n' ' ' < "$gr03_ok/err")"

stale="$tmp/stale"; mkdir -p "$stale"; cp "$ASSETS"/*.jpg "$stale"/; rm "$stale/guided-katy-perry-2019.jpg"
set +e
SRC="$stale" OUT="$tmp/out2" MANIFEST="$tmp/m2" README="$README" RIGHTS="$tmp/rights2.tsv" bash "$SELECT" >/dev/null 2>&1; rc=$?
set -e
[ "$rc" -eq 2 ] && pass "refuses (exit 2) when a bundled source image is missing" || fail "expected exit 2 on missing source, got $rc"
# GUIDESEED-1-GR-07: empty-file is still a write. Refusal must leave the path absent.
if [ -e "$tmp/m2" ]; then
  fail "GR-07 manifest created on refusal ($(wc -c < "$tmp/m2" | tr -d ' ') bytes)"
else
  pass "GR-07 no manifest created on refusal"
fi
if [ -e "$tmp/rights2.tsv" ]; then
  fail "rights ledger created on refusal ($(wc -c < "$tmp/rights2.tsv" | tr -d ' ') bytes)"
else
  pass "no rights ledger created on refusal"
fi

if [ "$fails" -ne 0 ]; then echo "test-guided-seed: $fails failure(s)" >&2; exit 1; fi
echo "test-guided-seed: all assertions passed"
