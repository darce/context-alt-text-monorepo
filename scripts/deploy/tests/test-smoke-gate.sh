#!/usr/bin/env bash
# Characterization test for the sync-demo.sh vhost-smoke gate matrix
# (scripts/deploy/lib/smoke-gate.sh). Pins PASS/WARN/FAIL semantics so a gate
# regression is caught without a live deploy. Run: bash scripts/deploy/tests/test-smoke-gate.sh

# R2-11: refuse non-bash before `set -o pipefail`. dash/sh reject pipefail
# with exit 2 and print no assertions, which a caller can misread as green.
if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash, not sh/dash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
describe_gate_file="${script_dir}/../../../infra/oci/demo/lib/describe-gate.sh"
fixture_denylist_file="${script_dir}/../lib/fixture-denylist.sh"
if [ ! -f "$describe_gate_file" ]; then
    echo "FAIL describe-gate.sh missing: ${describe_gate_file}"
    exit 1
fi
if [ ! -f "$fixture_denylist_file" ]; then
    echo "FAIL fixture-denylist.sh missing: ${fixture_denylist_file}"
    exit 1
fi
# Same order as the remote heredoc: describe-gate (trusted profiles), then
# canonical denylist (helper copies win), then smoke-gate classifiers.
# shellcheck source=../../../infra/oci/demo/lib/describe-gate.sh
source "$describe_gate_file"
# shellcheck source=../lib/fixture-denylist.sh
source "$fixture_denylist_file"
# shellcheck source=../lib/smoke-gate.sh
source "${script_dir}/../lib/smoke-gate.sh"

REAL_CAPTION='A woman in a red coat speaks at a podium in front of a blue backdrop.'
FIXTURE_CAPTION='A close-up of a small object on a neutral background.'
TRUSTED_ONE='florence_small'

failures=0

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: expected ${expected}, got ${actual}"
        failures=$((failures + 1))
    fi
}

# Dual-channel pin: printed verdict AND $?. FAIL must return 1; PASS/WARN 0.
# `|| actual_rc=$?` keeps set -e from aborting the suite on a FAIL return.
assert_verdict_rc() {
    local label="$1" expected_verdict="$2" expected_rc="$3"
    shift 3
    local actual_verdict actual_rc=0
    actual_verdict=$("$@") || actual_rc=$?
    assert_eq "${label} verdict" "$expected_verdict" "$actual_verdict"
    assert_eq "${label} rc" "$expected_rc" "$actual_rc"
}

# Caption → denied_count using the same per-caption matcher as
# load_alt_counts_from_media_body. Keeps the existing fixture-caption
# assertions load-bearing against the matcher after the first
# classify_alt_provenance argument changed from sample text to denied_count.
caption_denied_count() {
    if fixture_sample_is_denied "$1"; then
        printf '%s' 1
    else
        printf '%s' 0
    fi
}

# --- classify_api_probe <post_code> <pre_code> ---
# Unreachable after retries = edge/TLS broken by the promote -> FAIL, regardless of baseline.
assert_eq "api 000, pre 200"     FAIL "$(classify_api_probe 000 200)"
assert_eq "api 000, pre 502"     FAIL "$(classify_api_probe 000 502)"
assert_eq "api 000, no baseline" FAIL "$(classify_api_probe 000 '')"
# Healthy -> PASS.
assert_eq "api 200, pre 200"     PASS "$(classify_api_probe 200 200)"
assert_eq "api 200, no baseline" PASS "$(classify_api_probe 200 '')"
# Reachable-but-unhealthy: deploy-caused only if healthy before the promote.
assert_eq "api 502 after healthy baseline (deploy-caused regression)" FAIL "$(classify_api_probe 502 200)"
assert_eq "api 404 after healthy baseline (deploy-caused misroute)"   FAIL "$(classify_api_probe 404 200)"
assert_eq "api 502, already 502 pre-promote (backend outage)"         WARN "$(classify_api_probe 502 502)"
assert_eq "api 502, pre unreachable (pre-existing breakage)"          WARN "$(classify_api_probe 502 000)"
assert_eq "api 503, no baseline captured"                             WARN "$(classify_api_probe 503 '')"

# --- classify_demo_probe <final_code> <final_url> ---
# Redirects are followed by the prober; only the FINAL state is judged.
assert_eq "demo 200 front page"        PASS "$(classify_demo_probe 200 'https://demo.altcontext.com/')"
assert_eq "demo 200 after canonical redirect" PASS "$(classify_demo_probe 200 'https://129-213-40-111.sslip.io/')"
# Wiped/fresh DB: WP 302 -> installer answers 200; that is a broken demo.
assert_eq "demo 200 on install.php (wiped DB)" FAIL "$(classify_demo_probe 200 'https://demo.altcontext.com/wp-admin/install.php')"
assert_eq "demo 200 on setup-config.php (no wp-config)" FAIL "$(classify_demo_probe 200 'https://demo.altcontext.com/wp-admin/setup-config.php?step=0')"
# Hard failures.
assert_eq "demo 500" FAIL "$(classify_demo_probe 500 'https://demo.altcontext.com/')"
assert_eq "demo 404" FAIL "$(classify_demo_probe 404 'https://demo.altcontext.com/')"
assert_eq "demo 000" FAIL "$(classify_demo_probe 000 '')"
# A 3xx surviving --max-redirs (redirect loop) is not a healthy final state.
assert_eq "demo 301 final (redirect loop)" FAIL "$(classify_demo_probe 301 'https://demo.altcontext.com/')"

# --- classify_alt_coverage <total> <with_alt> <min_pct> ---
assert_eq "alt coverage 100/100 >= 95" PASS "$(classify_alt_coverage 100 100 95)"
assert_eq "alt coverage 96/100 >= 95"  PASS "$(classify_alt_coverage 100 96 95)"
assert_eq "alt coverage 95/100 >= 95 (boundary inclusive)" PASS "$(classify_alt_coverage 100 95 95)"
assert_eq "alt coverage 94/100 < 95"   FAIL "$(classify_alt_coverage 100 94 95)"
assert_eq "alt coverage 0/100 (live empty-alt bug)" FAIL "$(classify_alt_coverage 100 0 95)"
assert_eq "alt coverage 0/0 (no media = broken seed)" FAIL "$(classify_alt_coverage 0 0 95)"
assert_eq "alt coverage empty inputs (unmeasurable)" FAIL "$(classify_alt_coverage '' '' 95)"
assert_eq "alt coverage non-numeric total" FAIL "$(classify_alt_coverage abc 10 95)"
assert_eq "alt coverage with_alt > total (impossible)" FAIL "$(classify_alt_coverage 100 200 95)"
assert_eq "alt coverage 2/3 min_pct 60 below default floor 95" FAIL "$(classify_alt_coverage 3 2 60)"
assert_eq "alt coverage 1/3 min_pct 60 below default floor 95" FAIL "$(classify_alt_coverage 3 1 60)"
# R2-06: the default IS the floor. DEMO_ALT_MIN_COVERAGE_PCT may only raise
# the bar above 95; any value below 95 fails closed. classify_alt_coverage
# 100 0 0 used to evaluate 0>=0 and print PASS.
assert_eq "alt coverage min_pct 0 below default floor 95 (certify-a-lie)" FAIL "$(classify_alt_coverage 100 0 0)"
assert_eq "alt coverage 100 0 49 below default floor 95" FAIL "$(classify_alt_coverage 100 0 49)"
assert_eq "alt coverage 100 100 50 below default floor 95, full coverage" FAIL "$(classify_alt_coverage 100 100 50)"
assert_eq "alt coverage 100 95 95 shipped default still works" PASS "$(classify_alt_coverage 100 95 95)"
assert_eq "alt coverage 100/100 but min_pct 49 below floor 95" FAIL "$(classify_alt_coverage 100 100 49)"
assert_eq "alt coverage 50/100 min_pct 50 below default floor 95" FAIL "$(classify_alt_coverage 100 50 50)"
assert_eq "alt coverage 49/100 min_pct 50 below default floor 95" FAIL "$(classify_alt_coverage 100 49 50)"
# The knob is gone: exporting DEMO_ALT_MIN_COVERAGE_FLOOR=0 must not certify 0/100.
_saved_floor="${DEMO_ALT_MIN_COVERAGE_FLOOR-}"
DEMO_ALT_MIN_COVERAGE_FLOOR=0
export DEMO_ALT_MIN_COVERAGE_FLOOR
assert_eq "alt coverage FLOOR=0 env cannot override fixed floor (100 0 0 still FAIL)" FAIL "$(classify_alt_coverage 100 0 0)"
if [ -n "${_saved_floor}" ]; then
    DEMO_ALT_MIN_COVERAGE_FLOOR="${_saved_floor}"
    export DEMO_ALT_MIN_COVERAGE_FLOOR
else
    unset DEMO_ALT_MIN_COVERAGE_FLOOR
fi
unset _saved_floor

# --- classify_first_burst_bounded <chunk_count> <max> <total> ---
# The describe publish is bounded by both the configured first-burst maximum
# and the live media total.  FAIL is returned for malformed or impossible
# measurements so smoke cannot certify an unbounded publish.
assert_verdict_rc "first burst 10 <= max 100 and total 250" PASS 0 \
    classify_first_burst_bounded 10 100 250
assert_verdict_rc "first burst at max 100" PASS 0 \
    classify_first_burst_bounded 100 100 250
assert_verdict_rc "first burst at total 100" PASS 0 \
    classify_first_burst_bounded 100 250 100
assert_verdict_rc "first burst zero count (SKIP)" PASS 0 \
    classify_first_burst_bounded 0 100 0
assert_verdict_rc "first burst exceeds max" FAIL 1 \
    classify_first_burst_bounded 101 100 250
assert_verdict_rc "first burst exceeds total" FAIL 1 \
    classify_first_burst_bounded 101 250 100
assert_verdict_rc "first burst empty count" FAIL 1 \
    classify_first_burst_bounded '' 100 250
assert_verdict_rc "first burst zero max" FAIL 1 \
    classify_first_burst_bounded 1 0 250

# --- classify_alt_population <header_total> <body_total> ---
assert_eq "alt population 100 == 100" PASS "$(classify_alt_population 100 100)"
assert_eq "alt population 250 vs 100 (paged subset)" FAIL "$(classify_alt_population 250 100)"
assert_eq "alt population 100 vs 250 (body exceeds header)" FAIL "$(classify_alt_population 100 250)"
assert_eq "alt population empty header" FAIL "$(classify_alt_population '' 100)"
assert_eq "alt population empty body" FAIL "$(classify_alt_population 100 '')"
assert_eq "alt population non-numeric header" FAIL "$(classify_alt_population abc 100)"
assert_eq "alt population 0 == 0 (nothing measured)" FAIL "$(classify_alt_population 0 0)"

# --- classify_alt_provenance <denied_count> <adapters_blob> <usable_count> [usable_normalized_count] ---
# Gate B pins pass a trusted adapter so FAIL cannot hide behind Gate A (TEST-15 M2).
# First arg is denied_count (per-caption fixture signal), not a concatenated blob.
assert_eq "alt provenance empty sample (cannot prove)" FAIL "$(classify_alt_provenance 0 "$TRUSTED_ONE" 1 0)"
assert_eq "alt provenance live seeded draft on demo media id 5" FAIL "$(classify_alt_provenance "$(caption_denied_count 'antonio_banderas_10. A close-up of a small object on a neutral background.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance real caption (not a fixture)" PASS "$(classify_alt_provenance "$(caption_denied_count "$REAL_CAPTION")" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: person outdoors" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A person standing outdoors near greenery.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: plate of food" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A plate of food on a wooden table.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: scenic landscape" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A scenic landscape with mountains under a clear sky.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: close-up object" FAIL "$(classify_alt_provenance "$(caption_denied_count "$FIXTURE_CAPTION")" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: printed document" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A printed document with several lines of text.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: two people seated" FAIL "$(classify_alt_provenance "$(caption_denied_count 'Two people seated indoors in conversation.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: building exterior" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A building exterior seen from the street.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance fixture: pet animal" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A pet animal resting on a soft surface.')" "$TRUSTED_ONE" 1)"
# R1-03b: trivial denylist evasions must still FAIL.
assert_eq "alt provenance lowercase first letter still fixture" FAIL "$(classify_alt_provenance "$(caption_denied_count 'a person standing outdoors near greenery.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance dropped trailing period still fixture" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A person standing outdoors near greenery')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance extra internal whitespace still fixture" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A person  standing   outdoors near greenery.')" "$TRUSTED_ONE" 1)"
assert_eq "alt provenance trailing bang still fixture" FAIL "$(classify_alt_provenance "$(caption_denied_count 'A person standing outdoors near greenery!')" "$TRUSTED_ONE" 1)"
# R1-03B part 2: Gate A adapter identity, ANDed with Gate B.
assert_eq "alt provenance trusted adapter x1 usable 1" PASS "$(classify_alt_provenance 0 "$TRUSTED_ONE" 1)"
assert_eq "alt provenance trusted adapters x3 usable 3" PASS "$(classify_alt_provenance 0 "florence_small gpu_qwen30b gpu_qwen30b_ensemble" 3)"
assert_eq "alt provenance untrusted adapter seeded" FAIL "$(classify_alt_provenance 0 "seeded" 1)"
assert_eq "alt provenance mixed trusted + untrusted" FAIL "$(classify_alt_provenance 0 "florence_small seeded" 2)"
assert_eq "alt provenance empty adapters blob usable 1 (fail closed)" FAIL "$(classify_alt_provenance 0 "" 1)"
assert_eq "alt provenance whitespace adapters blob usable 1 (fail closed)" FAIL "$(classify_alt_provenance 0 "   " 1)"
assert_eq "alt provenance trusted fewer than usable_count" FAIL "$(classify_alt_provenance 0 "$TRUSTED_ONE" 2)"
assert_eq "alt identity extra trusted tokens fail equality (not >=)" FAIL "$(classify_alt_identity 'florence_small florence_small' 1)"
assert_eq "alt identity glob star token is untrusted" FAIL "$(classify_alt_identity '*' 1)"
assert_eq "alt identity glob question token is untrusted" FAIL "$(classify_alt_identity '?' 1)"
assert_eq "alt identity glob bracket token is untrusted" FAIL "$(classify_alt_identity '[a-z]' 1)"
assert_eq "alt provenance trusted adapter AND denylisted caption" FAIL "$(classify_alt_provenance 1 "$TRUSTED_ONE" 1)"
assert_eq "alt provenance non-numeric usable_count" FAIL "$(classify_alt_provenance 0 "$TRUSTED_ONE" abc)"
assert_eq "alt provenance empty usable_count" FAIL "$(classify_alt_provenance 0 "$TRUSTED_ONE" "")"

# --- classify_alt_text_usable <text> ---
# R1-03a: placeholder / non-content alt is not coverage.
assert_eq "usable alt empty" FAIL "$(classify_alt_text_usable '')"
assert_eq "usable alt whitespace only" FAIL "$(classify_alt_text_usable '   ')"
assert_eq "usable alt period placeholder" FAIL "$(classify_alt_text_usable '.')"
assert_eq "usable alt single space" FAIL "$(classify_alt_text_usable ' ')"
assert_eq "usable alt 14 letters (below 15)" FAIL "$(classify_alt_text_usable 'abcdefghijklmn')"
assert_eq "usable alt 15 letters" PASS "$(classify_alt_text_usable 'abcdefghijklmno')"
assert_eq "usable alt 15 digits no alphabetic" FAIL "$(classify_alt_text_usable '123456789012345')"
assert_eq "usable alt real caption" PASS "$(classify_alt_text_usable 'A woman in a red coat speaks at a podium.')"
# R2-09: 'abcde' + five U+00E9 = 10 characters, 15 UTF-8 bytes. ${#text}
# PASSes this under C/POSIX (bytes) and FAILs under UTF-8 (chars). Characters
# is the documented unit; both locales must FAIL, and the verdicts must match.
# UTF-8 bytes, not $'\u00e9', so macOS bash 3.2 can construct the sample.
r209_sample="abcde$(printf '\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9')"
r209_c=$(LC_ALL=C classify_alt_text_usable "$r209_sample") || true
r209_utf=$(LC_ALL=C.UTF-8 classify_alt_text_usable "$r209_sample") || true
assert_eq "R2-09 10-char/15-byte under LC_ALL=C" FAIL "$r209_c"
assert_eq "R2-09 10-char/15-byte under LC_ALL=C.UTF-8" FAIL "$r209_utf"
assert_eq "R2-09 locale-independent verdict" "$r209_c" "$r209_utf"
# R2-11: this suite (and the describe suite) must refuse non-bash before
# `set -o pipefail`. Pin the guard so deleting it goes red under bash too,
# not only as an early sh abort with no assertion output.
r211_self=$(awk '
    /BASH_VERSION/ && !seen_pf { g=1 }
    /set -euo pipefail/ { seen_pf=1 }
    END { if (g) print "guard-before-pipefail"; else print "missing-guard" }
' "$0")
assert_eq "R2-11 smoke suite guards BASH_VERSION before pipefail" \
    "guard-before-pipefail" "$r211_self"
describe_test="${script_dir}/../../../infra/oci/demo/tests/test-describe-gate.sh"
r211_describe=$(awk '
    /BASH_VERSION/ && !seen_pf { g=1 }
    /set -euo pipefail/ { seen_pf=1 }
    END { if (g) print "guard-before-pipefail"; else print "missing-guard" }
' "$describe_test")
assert_eq "R2-11 describe suite guards BASH_VERSION before pipefail" \
    "guard-before-pipefail" "$r211_describe"

# VLMHEAL-1: boot-smoke must retain and print the last /health body before the
# throwaway container's EXIT trap removes it, so a 503 body is not lost.
recognition_deploy="${script_dir}/../recognition-service.sh"
boot_smoke_heredoc=$(awk '
    /^do_boot_smoke\(\) \{/ { in_fn=1 }
    in_fn && /<<.*SMOKE/ { in_smoke=1; next }
    in_smoke && /^SMOKE$/ { exit }
    in_smoke { print }
' "$recognition_deploy")
assert_eq "VLMHEAL-1 boot smoke prints last /health body on failure" \
    "1" "$(printf '%s\n' "$boot_smoke_heredoc" | grep -cF '${last_health_body:0:2000}' || true)"

# R2-13: printed verdict AND $? for at least one PASS and one FAIL per classifier.
# WARN is not a failure (rc 0), matching UNKNOWN policy.
assert_verdict_rc "R2-13 api PASS" PASS 0 classify_api_probe 200 200
assert_verdict_rc "R2-13 api FAIL" FAIL 1 classify_api_probe 000 200
assert_verdict_rc "R2-13 api WARN" WARN 0 classify_api_probe 502 502
assert_verdict_rc "R2-13 demo PASS" PASS 0 classify_demo_probe 200 'https://demo.altcontext.com/'
assert_verdict_rc "R2-13 demo FAIL" FAIL 1 classify_demo_probe 500 'https://demo.altcontext.com/'
assert_verdict_rc "R2-13 coverage PASS" PASS 0 classify_alt_coverage 100 100 95
assert_verdict_rc "R2-13 coverage FAIL" FAIL 1 classify_alt_coverage 100 0 95
assert_verdict_rc "R2-13 population PASS" PASS 0 classify_alt_population 100 100
assert_verdict_rc "R2-13 population FAIL" FAIL 1 classify_alt_population 250 100
assert_verdict_rc "R2-13 usable PASS" PASS 0 classify_alt_text_usable 'abcdefghijklmno'
assert_verdict_rc "R2-13 usable FAIL" FAIL 1 classify_alt_text_usable ''
assert_verdict_rc "R2-13 identity PASS" PASS 0 classify_alt_identity "$TRUSTED_ONE" 1
assert_verdict_rc "R2-13 identity FAIL" FAIL 1 classify_alt_identity seeded 1
assert_verdict_rc "R2-13 provenance PASS" PASS 0 classify_alt_provenance 0 "$TRUSTED_ONE" 1
assert_verdict_rc "R2-13 provenance FAIL" FAIL 1 classify_alt_provenance 1 "$TRUSTED_ONE" 1

# TEST-15 mutation proof (2026-08-25): adding a 9th _FIXTURE_POOL caption
# not present in smoke-gate.sh makes this suite exit 1 with:
# FAIL drift: pool caption classified FAIL (A drift sentinel caption that is not in the shell gate.): expected FAIL, got PASS
# Reverted; suite green. The guard is falsifiable, not merely passing.
# Drift guard: every caption in the Python _FIXTURE_POOL must FAIL provenance.
# If a fixture is added to seeded_adapter.py and not the shared denylist,
# this goes red. Missing source file is a FAIL, not a skip.
# XLANE-03: smoke-gate.sh must not grow a third inline denylist copy.
assert_eq "smoke-gate.sh has no inline fixture-caption case arms" \
    "0" "$(grep -c 'a close-up of a small object' "${script_dir}/../lib/smoke-gate.sh" || true)"
adapter_file=$(cd "${script_dir}/../../.." && pwd)/apps/prototype-description-service/scene/application/seeded_adapter.py
if [ ! -f "$adapter_file" ]; then
    echo "FAIL fixture-pool source missing: ${adapter_file}"
    failures=$((failures + 1))
else
    extracted=0
    while IFS= read -r caption; do
        [ -n "$caption" ] || continue
        extracted=$((extracted + 1))
        assert_eq "drift: pool caption classified FAIL (${caption})" FAIL "$(classify_alt_provenance "$(caption_denied_count "$caption")" "$TRUSTED_ONE" 1)"
    done <<DRIFT
$(grep '"caption":' "$adapter_file" | sed 's/.*"caption": "\([^"]*\)".*/\1/')
DRIFT
    if [ "$extracted" -eq 0 ]; then
        echo "FAIL fixture-pool extraction produced zero captions from ${adapter_file}"
        failures=$((failures + 1))
    fi
    # R3-01: extracted count must equal the true _FIXTURE_POOL length (ast).
    # grep '"caption":' misses 'caption' keys; -gt 0 would still pass a partial miss.
    true_pool_len=""
    if ! true_pool_len=$(python3 - "$adapter_file" <<'PY'
import ast
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
mod = ast.parse(path.read_text())
for node in mod.body:
    name = None
    value = None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name, value = node.target.id, node.value
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_FIXTURE_POOL":
                name, value = target.id, node.value
                break
    if name == "_FIXTURE_POOL":
        if not isinstance(value, (ast.Tuple, ast.List)):
            sys.stderr.write("FAIL _FIXTURE_POOL is not a tuple/list\n")
            sys.exit(2)
        print(len(value.elts))
        sys.exit(0)
sys.stderr.write("FAIL _FIXTURE_POOL not found\n")
sys.exit(2)
PY
    ); then
        echo "FAIL fixture-pool ast parse failed for ${adapter_file}"
        failures=$((failures + 1))
    elif [ "$extracted" -ne "$true_pool_len" ]; then
        echo "FAIL fixture-pool extraction count ${extracted} != pool length ${true_pool_len}"
        failures=$((failures + 1))
    else
        echo "ok   drift: extracted ${extracted} == pool length ${true_pool_len}"
    fi
fi

# --- emit_alt_gate <verdict> <msg> <overridable> (extracted from sync-demo.sh) ---
# R1-01: provenance FAIL is non-overridable; population/coverage stay overridable.
sync_demo="${script_dir}/../sync-demo.sh"
if [ ! -f "$sync_demo" ]; then
    echo "FAIL sync-demo.sh missing: ${sync_demo}"
    failures=$((failures + 1))
else
    pop_line=$(grep 'emit_alt_gate "$pop"' "$sync_demo" | sed 's/^[[:space:]]*//')
    cov_line=$(grep 'emit_alt_gate "$verdict" "$cov_msg"' "$sync_demo" | sed 's/^[[:space:]]*//')
    prov_line=$(grep 'emit_alt_gate "$prov"' "$sync_demo" | sed 's/^[[:space:]]*//')
    assert_eq "R1-01 population emit_alt_gate overridable=1" 'emit_alt_gate "$pop" "$pop_msg" 1' "$pop_line"
    assert_eq "R1-01B coverage emit_alt_gate uses cov_overridable" 'emit_alt_gate "$verdict" "$cov_msg" "$cov_overridable"' "$cov_line"
    assert_eq "R1-01 provenance emit_alt_gate overridable=0" 'emit_alt_gate "$prov" "$prov_msg" 0' "$prov_line"
    if grep -q 'PARTIALLY described demo can ship' "$sync_demo"; then
        echo "ok   R1-01B header states hatch is for a PARTIALLY described demo"
    else
        echo "FAIL R1-01B header missing 'PARTIALLY described demo can ship'"
        failures=$((failures + 1))
    fi
    if grep -q 'echo "SKIP demo alt provenance' "$sync_demo"; then
        echo "FAIL R1-01B empty provenance still a SKIP echo (must FAIL closed)"
        failures=$((failures + 1))
    else
        echo "ok   R1-01B empty provenance is not a SKIP echo"
    fi
    if grep -q 'cov_overridable=1' "$sync_demo"; then
        echo "ok   R1-01B coverage override is conditional (cov_overridable)"
    else
        echo "FAIL R1-01B coverage override is conditional (cov_overridable)"
        failures=$((failures + 1))
    fi
    if grep -q 'classify_alt_text_usable' "$sync_demo"; then
        echo "ok   R1-03 classify_alt_text_usable wired into sync-demo.sh"
    else
        echo "FAIL R1-03 classify_alt_text_usable not wired into sync-demo.sh"
        failures=$((failures + 1))
    fi
    if grep -qE '_fields=[^[:space:]]*acx_alt_provenance' "$sync_demo"; then
        echo "ok   R1-03B _fields requests acx_alt_provenance"
    else
        echo "FAIL R1-03B _fields= in sync-demo.sh missing acx_alt_provenance"
        failures=$((failures + 1))
    fi
    assert_eq "TEST-15 sync-demo.sh calls load_alt_counts_from_media_body" \
        "1" "$(grep -c 'load_alt_counts_from_media_body' "$sync_demo")"
    assert_eq "TEST-15 sync-demo.sh has no independent adapter grep" \
        "0" "$(grep -c 'ADAPTERJSON' "$sync_demo" || true)"
    assert_eq "TEST-15 parser reads provenance adapter key" \
        "1" "$(grep -c 'prov.get("adapter")' "${script_dir}/../lib/smoke-gate.sh")"
    # R2-04: the remote heredoc concatenates three libraries in a
    # load-bearing order (later definition wins). Pin file order by
    # reading sync-demo.sh itself — do not source or execute it.
    cat_order=$(
        grep -n 'cat "\$' "$sync_demo" \
            | sed 's/.*cat "\$//;s/"$//' \
            | paste -sd' ' -
    )
    assert_eq "R2-04 remote heredoc cat order" \
        "DESCRIBE_GATE_SRC FIXTURE_DENYLIST_LIB SMOKE_GATE_LIB" \
        "$cat_order"
    extract_fn_stripped() {
        local file="$1" name="$2"
        awk -v n="$name" '
            $0 ~ "^" n "\\(\\) \\{" {grab=1}
            grab {print}
            grab && $0 == "}" {exit}
        ' "$file" | sed '/^[[:space:]]*#/d;/^[[:space:]]*$/d'
    }
    for fn in normalize_fixture_sample fixture_sample_is_denied; do
        describe_body=$(extract_fn_stripped "$describe_gate_file" "$fn")
        denylist_body=$(extract_fn_stripped "$fixture_denylist_file" "$fn")
        if [ -z "$describe_body" ] || [ -z "$denylist_body" ]; then
            echo "FAIL drift: ${fn} body empty in one copy"
            failures=$((failures + 1))
        elif [ "$describe_body" = "$denylist_body" ]; then
            echo "ok   drift: ${fn} bodies agree (comments/blanks stripped)"
        else
            echo "FAIL drift: ${fn} bodies diverged between describe-gate.sh and fixture-denylist.sh"
            failures=$((failures + 1))
        fi
    done
    emit_src=$(awk '/^emit_alt_gate\(\) \{/,/^}/' "$sync_demo")
    if [ -z "$emit_src" ]; then
        echo "FAIL emit_alt_gate not found in ${sync_demo}"
        failures=$((failures + 1))
    else
        eval "$emit_src"
        run_emit() {
            DEMO_ALT_GATE_ENFORCE="$1"
            smoke_fail=0
            emit_alt_gate "$2" "$3" "$4"
            echo "smoke_fail=${smoke_fail}"
        }
        cov_override=$(run_emit 0 FAIL "demo alt coverage (60/100 = 60%, need 95%)" 1)
        assert_eq "R1-01 partial coverage FAIL overridable under DEMO_ALT_GATE_ENFORCE=0" \
            "WARN demo alt coverage (60/100 = 60%, need 95%) (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)
smoke_fail=0" "$cov_override"
        prov_locked=$(run_emit 0 FAIL "demo alt provenance (seeded fixture caption detected in 100 published alt texts)" 0)
        assert_eq "R1-01 provenance FAIL non-overridable under DEMO_ALT_GATE_ENFORCE=0" \
            "FAIL demo alt provenance (seeded fixture caption detected in 100 published alt texts)
smoke_fail=1" "$prov_locked"
        prov_default=$(run_emit 0 FAIL "demo alt provenance (canned)" "")
        assert_eq "R1-01 missing overridable defaults fail-closed" \
            "FAIL demo alt provenance (canned)
smoke_fail=1" "$prov_default"

        # R1-02B: DEMO_ALT_MIN_COVERAGE_FLOOR must not be injected into the
        # remote heredoc — the floor is a constant inside smoke-gate.sh.
        if grep -q "printf 'DEMO_ALT_MIN_COVERAGE_FLOOR=" "$sync_demo"; then
            echo "FAIL R1-02B sync-demo.sh still injects DEMO_ALT_MIN_COVERAGE_FLOOR into the remote heredoc"
            failures=$((failures + 1))
        else
            echo "ok   R1-02B sync-demo.sh does not inject DEMO_ALT_MIN_COVERAGE_FLOOR"
        fi
        if grep -q 'floor="${DEMO_ALT_MIN_COVERAGE_FLOOR' "${script_dir}/../lib/smoke-gate.sh"; then
            echo "FAIL R1-02B classify_alt_coverage still reads DEMO_ALT_MIN_COVERAGE_FLOOR from the environment"
            failures=$((failures + 1))
        else
            echo "ok   R1-02B classify_alt_coverage does not read DEMO_ALT_MIN_COVERAGE_FLOOR"
        fi

        # End-to-end through the sync-demo.sh counting block: FLOOR=0 PCT=0
        # against a 0/100 empty-alt payload must still leave smoke_fail=1.
        run_empty_alt_floor_override() {
            DEMO_ALT_MIN_COVERAGE_FLOOR=0
            DEMO_ALT_MIN_COVERAGE_PCT=0
            DEMO_ALT_GATE_ENFORCE=1
            export DEMO_ALT_MIN_COVERAGE_FLOOR DEMO_ALT_MIN_COVERAGE_PCT DEMO_ALT_GATE_ENFORCE
            smoke_fail=0
            header_total=100
            body_total=100
            with_alt=0
            min="${DEMO_ALT_MIN_COVERAGE_PCT:-95}"
            pop=$(classify_alt_population "$header_total" "$body_total") || true
            emit_alt_gate "$pop" "demo alt population (header=${header_total} body=${body_total})" 1
            verdict=$(classify_alt_coverage "$body_total" "$with_alt" "$min") || true
            pct=$((with_alt * 100 / body_total))
            cov_msg="demo alt coverage (${with_alt}/${body_total} = ${pct}%, need ${min}%)"
            emit_alt_gate "$verdict" "$cov_msg" 1
            echo "smoke_fail=${smoke_fail}"
        }
        empty_override=$(run_empty_alt_floor_override)
        assert_eq "R1-02B counting block FLOOR=0 PCT=0 empty-alt 0/100 leaves smoke_fail=1" \
            "PASS demo alt population (header=100 body=100)
FAIL demo alt coverage (0/100 = 0%, need 0%)
smoke_fail=1" "$empty_override"

        # R1-01B: emit/override composition. Duplicated from the remote
        # heredoc in sync-demo.sh on purpose — not extracted by regex.
        # Drift risk: if sync-demo.sh composition changes and this harness
        # does not, these pins stay green. The source pins above (SKIP echo
        # gone, cov_overridable present, coverage emit uses $cov_overridable)
        # are the only lock on the production file itself.
        run_alt_pipeline() {
            local header_total="$1" body_total="$2" with_alt="$3" sample="${4:-}"
            local adapters i
            if [ "$#" -ge 5 ]; then
                adapters="$5"
            else
                adapters=""
                case "$with_alt" in *[!0-9]*|'') ;; *)
                    i=0
                    while [ "$i" -lt "$with_alt" ]; do
                        adapters="${adapters}florence_small "
                        i=$((i + 1))
                    done
                    ;;
                esac
            fi
            smoke_fail=0
            min="${DEMO_ALT_MIN_COVERAGE_PCT:-95}"
            pop=$(classify_alt_population "$header_total" "$body_total") || true
            if [ "$pop" = "FAIL" ]; then
                pop_msg="demo alt coverage (measured ${body_total:-empty} of ${header_total:-empty} reported by x-wp-total; probe covers only one page, cannot certify coverage)"
            else
                pop_msg="demo alt population (header=${header_total} body=${body_total})"
            fi
            emit_alt_gate "$pop" "$pop_msg" 1
            verdict=$(classify_alt_coverage "$body_total" "$with_alt" "$min") || true
            pct="?"
            case "$body_total" in *[!0-9]*|'') ;; *)
                case "$with_alt" in *[!0-9]*|'') ;; *)
                    if [ "$body_total" -gt 0 ]; then
                        pct=$((with_alt * 100 / body_total))
                    fi
                    ;;
                esac
                ;;
            esac
            if [ "$pct" != "?" ]; then
                cov_msg="demo alt coverage (${with_alt}/${body_total} = ${pct}%, need ${min}%)"
            else
                cov_msg="demo alt coverage (total=${body_total:-empty} with_alt=${with_alt:-empty}, need ${min}%)"
            fi
            cov_overridable=1
            case "$with_alt" in
                *[!0-9]*|'') cov_overridable=0 ;;
                0) cov_overridable=0 ;;
            esac
            emit_alt_gate "$verdict" "$cov_msg" "$cov_overridable"
            run_prov=0
            case "$with_alt" in *[!0-9]*|'') ;; *)
                if [ "$with_alt" -gt 0 ]; then
                    run_prov=1
                fi
                ;;
            esac
            if [ "$run_prov" = "1" ]; then
                _denied=0
                if [ -n "$sample" ] && fixture_sample_is_denied "$sample"; then
                    _denied=1
                fi
                _norm="$with_alt"
                if [ -z "$(normalize_fixture_sample "$sample")" ]; then
                    _norm=0
                fi
                prov=$(classify_alt_provenance "$_denied" "$adapters" "$with_alt" "$_norm") || true
                if [ "$prov" = "FAIL" ]; then
                    identity=$(classify_alt_identity "$adapters" "$with_alt") || true
                    if [ "$identity" = "FAIL" ]; then
                        prov_msg="demo alt provenance (untrusted or absent adapter identity behind ${with_alt} published alt texts)"
                    else
                        prov_msg="demo alt provenance (seeded fixture caption detected in ${with_alt} published alt texts)"
                    fi
                else
                    prov_msg="demo alt provenance (trusted adapter identity, no seeded fixture captions in ${with_alt} published alt texts)"
                fi
                emit_alt_gate "$prov" "$prov_msg" 0
            else
                emit_alt_gate FAIL "demo alt provenance (no alt text published; nothing to certify)" 0
            fi
            echo "smoke_fail=${smoke_fail}"
        }
        pipeline_line() {
            printf '%s\n' "$1" | grep -E "$2" | head -1
        }
        pipeline_fail() {
            printf '%s\n' "$1" | sed -n 's/^smoke_fail=//p'
        }

        REAL_CAPTION='A woman in a red coat speaks at a podium in front of a blue backdrop.'
        FIXTURE_CAPTION='A close-up of a small object on a neutral background.'

        DEMO_ALT_GATE_ENFORCE=0
        export DEMO_ALT_GATE_ENFORCE
        empty_e0=$(run_alt_pipeline 100 100 0 "")
        assert_eq "R1-01B live empty library ENFORCE=0 exits non-zero" \
            "1" "$(pipeline_fail "$empty_e0")"
        assert_eq "R1-01B live empty library ENFORCE=0 coverage is FAIL (not waived)" \
            "FAIL demo alt coverage (0/100 = 0%, need 95%)" \
            "$(pipeline_line "$empty_e0" 'demo alt coverage')"
        assert_eq "R1-01B live empty library ENFORCE=0 provenance is FAIL closed" \
            "FAIL demo alt provenance (no alt text published; nothing to certify)" \
            "$(pipeline_line "$empty_e0" 'demo alt provenance')"

        DEMO_ALT_GATE_ENFORCE=1
        export DEMO_ALT_GATE_ENFORCE
        empty_e1=$(run_alt_pipeline 100 100 0 "")
        assert_eq "R1-01B live empty library ENFORCE=1 exits non-zero" \
            "1" "$(pipeline_fail "$empty_e1")"

        DEMO_ALT_GATE_ENFORCE=1
        export DEMO_ALT_GATE_ENFORCE
        full_real=$(run_alt_pipeline 100 100 100 "$REAL_CAPTION")
        assert_eq "R1-01B full real captions exit zero" \
            "0" "$(pipeline_fail "$full_real")"

        DEMO_ALT_GATE_ENFORCE=0
        export DEMO_ALT_GATE_ENFORCE
        partial_e0=$(run_alt_pipeline 100 100 60 "$REAL_CAPTION")
        assert_eq "R1-01B partial coverage 60/100 ENFORCE=0 still ships" \
            "0" "$(pipeline_fail "$partial_e0")"

        DEMO_ALT_GATE_ENFORCE=0
        export DEMO_ALT_GATE_ENFORCE
        fixture_e0=$(run_alt_pipeline 100 100 100 "$FIXTURE_CAPTION")
        assert_eq "R1-01B fixture captions ENFORCE=0 still blocked (provenance locked)" \
            "1" "$(pipeline_fail "$fixture_e0")"

        # TEST-15: the real counting block must parse provenance per attachment.
        # Pinning _fields= only proved the deploy ASKS for the field.
        media_json=$(mktemp)
        SECOND_CAPTION='A man sits at a wooden table writing in a notebook.'

        cat > "$media_json" <<JSON
[
  {"id":1,"alt_text":"${REAL_CAPTION}","acx_alt_provenance":{"adapter":"florence_small","model_id":"x"}},
  {"id":2,"alt_text":"${SECOND_CAPTION}","acx_alt_provenance":{"adapter":"gpu_qwen30b","model_id":"y"}},
  {"id":3,"alt_text":"","acx_alt_provenance":null}
]
JSON
        load_alt_counts_from_media_body "$media_json"
        assert_eq "TEST-15 realistic body_total follows attachment count" "3" "$body_total"
        assert_eq "TEST-15 realistic with_alt counts only usable alts" "2" "$with_alt"
        assert_eq "TEST-15 realistic adapters are per-usable-item join" "florence_small gpu_qwen30b " "$adapters"
        assert_eq "TEST-15 realistic identity PASS" PASS "$(classify_alt_identity "$adapters" "$with_alt")"

        cat > "$media_json" <<JSON
[
  {"id":1,"alt_text":"${REAL_CAPTION}","acx_alt_provenance":{"adapter":"florence_small florence_small","model_id":"x"}},
  {"id":2,"alt_text":"${SECOND_CAPTION}","acx_alt_provenance":null}
]
JSON
        load_alt_counts_from_media_body "$media_json"
        assert_eq "TEST-15 padded blob with_alt 2" "2" "$with_alt"
        assert_eq "TEST-15 padded blob adapters are sentinels not word-split" "__invalid__ __invalid__ " "$adapters"
        assert_eq "TEST-15 padded blob identity FAIL" FAIL "$(classify_alt_identity "$adapters" "$with_alt")"

        cat > "$media_json" <<JSON
[{"id":1,"alt_text":"${REAL_CAPTION}","acx_alt_provenance":{"adapter":"*"}}]
JSON
        load_alt_counts_from_media_body "$media_json"
        assert_eq "TEST-15 glob adapter sanitized" "__invalid__ " "$adapters"
        assert_eq "TEST-15 glob adapter identity FAIL" FAIL "$(classify_alt_identity "$adapters" "$with_alt")"

        # R3V-01: token-AND over a concatenated blob false-denies a genuine
        # library whose captions collectively contain every content token of
        # the "person standing outdoors greenery" arm, but where no single
        # caption is a fixture caption.
        python3 - "$media_json" <<'PY'
import json
import sys

captions = [
    "A person walks through the city at dusk near shops.",
    "A cyclist standing beside a painted mural downtown.",
    "Families picnic outdoors on a sandy beach at noon.",
    "Dense greenery fills the greenhouse behind glass.",
    "A ceramic bowl sits beside a window in morning light.",
    "The chef arranges herbs on a marble counter.",
    "Children chase a kite across an open field.",
    "A round oak desk holds books and a reading lamp.",
    "Two musicians perform on a small stage at night.",
    "A red brick facade faces the river at sunset.",
]
items = []
for i, caption in enumerate(captions, start=1):
    items.append({
        "id": i,
        "alt_text": caption,
        "acx_alt_provenance": {"adapter": "florence_small", "model_id": "x"},
    })
json.dump(items, open(sys.argv[1], "w"))
PY
        load_alt_counts_from_media_body "$media_json"
        blob_denied_rc=0
        fixture_sample_is_denied "$sample" || blob_denied_rc=$?
        assert_eq "R3V-01 genuine library body_total 10" "10" "$body_total"
        assert_eq "R3V-01 genuine library with_alt 10" "10" "$with_alt"
        assert_eq "R3V-01 genuine library denied_count 0" "0" "$denied_count"
        assert_eq "R3V-01 genuine library usable_normalized_count 10" "10" "$usable_normalized_count"
        assert_eq "R3V-01 concatenated blob trips person standing outdoors greenery arm" "0" "$blob_denied_rc"
        assert_eq "R3V-01 genuine library provenance PASS" PASS "$(classify_alt_provenance "$denied_count" "$adapters" "$with_alt" "$usable_normalized_count")"

        python3 - "$media_json" <<'PY'
import json
import sys

path = sys.argv[1]
items = json.load(open(path))
items.append({
    "id": 11,
    "alt_text": "A close-up of a small object on a neutral background.",
    "acx_alt_provenance": {"adapter": "florence_small", "model_id": "x"},
})
json.dump(items, open(path, "w"))
PY
        load_alt_counts_from_media_body "$media_json"
        assert_eq "R3V-01 genuine library plus one fixture body_total 11" "11" "$body_total"
        assert_eq "R3V-01 genuine library plus one fixture with_alt 11" "11" "$with_alt"
        assert_eq "R3V-01 genuine library plus one fixture denied_count 1" "1" "$denied_count"
        assert_eq "R3V-01 genuine library plus one fixture provenance FAIL" FAIL "$(classify_alt_provenance "$denied_count" "$adapters" "$with_alt" "$usable_normalized_count")"

        python3 - "$media_json" <<'PY'
import json
import sys

usable = "A woman in a red coat speaks at a podium."
items = []
for i in range(10):
    items.append({"id": i + 1, "alt_text": usable, "acx_alt_provenance": None})
for i in range(10):
    items.append({"id": i + 11, "alt_text": "", "acx_alt_provenance": {"adapter": "florence_small"}})
json.dump(items, open(sys.argv[1], "w"))
PY
        load_alt_counts_from_media_body "$media_json"
        assert_eq "TEST-15 empty-alt mix body_total 20" "20" "$body_total"
        assert_eq "TEST-15 empty-alt mix with_alt 10" "10" "$with_alt"
        assert_eq "TEST-15 empty-alt mix coverage at min_pct=50" FAIL "$(classify_alt_coverage "$body_total" "$with_alt" 50)"
        assert_eq "TEST-15 empty-alt mix identity FAIL" FAIL "$(classify_alt_identity "$adapters" "$with_alt")"

        DEMO_ALT_GATE_ENFORCE=1
        DEMO_ALT_MIN_COVERAGE_PCT=50
        export DEMO_ALT_GATE_ENFORCE DEMO_ALT_MIN_COVERAGE_PCT
        mix_out=$(run_alt_pipeline "$body_total" "$body_total" "$with_alt" "$sample" "$adapters")
        assert_eq "TEST-15 empty-alt mix min_pct=50 smoke_fail=1" \
            "1" "$(pipeline_fail "$mix_out")"
        assert_eq "TEST-15 empty-alt mix provenance FAIL line" \
            "FAIL demo alt provenance (untrusted or absent adapter identity behind 10 published alt texts)" \
            "$(pipeline_line "$mix_out" 'demo alt provenance')"
        unset DEMO_ALT_MIN_COVERAGE_PCT
        rm -f "$media_json"
    fi
fi

# --- bootstrap first describe burst: chunking + mid-run provenance recheck ---
# Run the real bootstrap against a local fake compose/wp-cli seam. The positive
# fixture proves the final chunk is trimmed to the remaining media, while the
# negative fixture flips provenance after chunk one and proves no second chunk
# is admitted.
bootstrap_file="${script_dir}/../../../infra/oci/demo/bootstrap-wp.sh"
# bootstrap-wp.sh uses bash 4 case-conversion expansion. macOS ships bash 3.2,
# where every invocation dies on "bad substitution" and this block reports five
# failures that say nothing about the product. Resolve a newer bash or skip, so
# a harness portability gap is not read as a product defect.
burst_bash=""
for burst_candidate in "${BASH_FOR_BOOTSTRAP:-}" bash /opt/homebrew/bin/bash /usr/local/bin/bash; do
    [ -n "$burst_candidate" ] || continue
    burst_resolved=$(command -v "$burst_candidate" 2>/dev/null) || continue
    burst_major=$("$burst_resolved" -c 'echo "${BASH_VERSINFO[0]}"' 2>/dev/null) || continue
    case "$burst_major" in ''|*[!0-9]*) continue ;; esac
    if [ "$burst_major" -ge 4 ]; then
        burst_bash="$burst_resolved"
        break
    fi
done
if [ -z "$burst_bash" ]; then
    echo "SKIP bootstrap describe-burst block (bootstrap-wp.sh needs bash >= 4; this host has $(bash --version | sed -n 1p))"
else
burst_root=$(mktemp -d)
mkdir -p "$burst_root/bin" "$burst_root/demo/lib" "$burst_root/demo/secrets"
cp "${script_dir}/../../../infra/oci/demo/lib/describe-gate.sh" "$burst_root/demo/lib/describe-gate.sh"
cp "${script_dir}/../lib/gpu-env-contract.sh" "$burst_root/demo/lib/gpu-env-contract.sh"
cat >"$burst_root/demo/secrets/.env" <<'EOF'
WP_ADMIN_USER=demo-admin
WP_ADMIN_PASSWORD=demo-admin-password
WP_ADMIN_EMAIL=admin@example.test
WP_CI_USER=demo-ci
WP_CI_PASSWORD=demo-ci-password
WP_CI_EMAIL=ci@example.test
WORDPRESS_CONFIG_EXTRA=define('ACX_RECOGNITION_URL','http://127.0.0.1:18080'); define('ACX_RECOGNITION_API_KEY','tenant-key'); define('ACX_RECOGNITION_TENANT_ID','123e4567-e89b-42d3-a456-426614174000');
EOF
: >"$burst_root/plugin.zip"
cat >"$burst_root/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
log="${BOOTSTRAP_LOG:?}"
state="${BOOTSTRAP_STATE:?}"
printf 'docker %q ' "$@" >>"$log"
printf '\n' >>"$log"
joined="$*"
if [[ "$joined" == *"alt-context describe generate"* ]]; then
    limit=0
    for arg in "$@"; do
        case "$arg" in
            --limit=*) limit="${arg#--limit=}" ;;
        esac
    done
    current=$(<"$state")
    if [[ "${BOOTSTRAP_BURST_MODE:-}" == flip ]]; then
        current=10
    else
        current=$((current + limit))
        burst_total="${BOOTSTRAP_BURST_TOTAL:-25}"
        if (( current > burst_total )); then current="$burst_total"; fi
        if [[ "${BOOTSTRAP_BURST_MODE:-}" == force ]]; then
            : >"${state}.force"
        fi
    fi
    printf '%s\n' "$current" >"$state"
    exit 0
fi
if [[ "$joined" == *"wp post list"* ]]; then
    if [[ "$joined" == *"--meta_key=_wp_attachment_image_alt"* ]]; then
        cat "$state"
    else
        printf '%s\n' "${BOOTSTRAP_BURST_TOTAL:-25}"
    fi
    exit 0
fi
if [[ "$joined" == *"wp eval"* ]]; then
    current=$(<"$state")
    if (( current > 0 )); then
        if [[ "${BOOTSTRAP_BURST_MODE:-}" == flip || ( "${BOOTSTRAP_BURST_MODE:-}" == force && ! -f "${state}.force" ) ]]; then
            printf '%s\n' 'A close-up of a small object on a neutral background.'
        else
            printf '%s\n' 'A woman in a red coat speaks at a podium in front of a blue backdrop.'
        fi
    fi
    exit 0
fi
if [[ "$joined" == *"--field=user_email"* ]]; then
    printf 'ci@example.test\n'
fi
exit 0
EOF
cat >"$burst_root/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
body=""
while (( $# > 0 )); do
    if [[ "$1" == "-o" ]]; then body="$2"; shift 2; else shift; fi
done
printf '%s' '{"description_adapter":"florence_small"}' >"$body"
printf '200'
EOF
chmod 700 "$burst_root/bin/docker" "$burst_root/bin/curl"
run_bootstrap_burst() {
    local mode="$1" output_file="$2" total="${3:-25}" initial_alt="${4:-0}" log_file
    log_file="$burst_root/${mode}.log"
    printf '%s\n' "$initial_alt" >"$burst_root/state"
    rm -f "$burst_root/state.force"
    : >"$log_file"
    local rc=0 output
    if output=$(
        PATH="$burst_root/bin:$PATH" \
        BOOTSTRAP_LOG="$log_file" \
        BOOTSTRAP_STATE="$burst_root/state" \
        BOOTSTRAP_BURST_MODE="$mode" \
        BOOTSTRAP_BURST_TOTAL="$total" \
        DEMO_DIR="$burst_root/demo" \
        PLUGIN_ZIP="$burst_root/plugin.zip" \
        ACX_DEMO_DESCRIBE_CHUNK=10 \
        ACX_DEMO_DESCRIBE_MAX=25 \
        "$burst_bash" "$bootstrap_file" 2>&1
    ); then
        rc=0
    else
        rc=$?
    fi
    printf '%s\n' "$rc" >"$output_file.rc"
    printf '%s\n' "$output" >"$output_file"
    return "$rc"
}

positive_output="$burst_root/positive.out"
positive_rc=0
run_bootstrap_burst positive "$positive_output" || positive_rc=$?
assert_eq "describe burst positive rc" 0 "$positive_rc"
positive_limits=$(sed -n 's/.*--limit=\([0-9][0-9]*\).*/\1/p' "$burst_root/positive.log" | tr '\n' ' ' | sed 's/[[:space:]]*$//')
assert_eq "describe burst trims final chunk" "10 10 5" "$positive_limits"
if grep -q 'Describe burst bounded: admitted=25/25 chunks=3' "$positive_output"; then
    echo "ok   describe burst reports bounded admitted count"
else
    echo "FAIL describe burst reports bounded admitted count"
    failures=$((failures + 1))
fi

small_output="$burst_root/small.out"
small_rc=0
run_bootstrap_burst small "$small_output" 5 0 || small_rc=$?
assert_eq "describe burst smaller-than-default population rc" 0 "$small_rc"
small_limits=$(sed -n 's/.*--limit=\([0-9][0-9]*\).*/\1/p' "$burst_root/small.log" | tr '\n' ' ' | sed 's/[[:space:]]*$//')
assert_eq "describe burst caps first chunk to live media total" "5" "$small_limits"
small_marker=$(tr -d '\r\n' <"$burst_root/demo/.acx-describe-first-burst.count")
assert_eq "describe burst marker stays within smaller media total" "5" "$small_marker"

force_output="$burst_root/force.out"
force_rc=0
run_bootstrap_burst force "$force_output" 5 5 || force_rc=$?
assert_eq "describe burst RUN_FORCE smaller-than-default population rc" 0 "$force_rc"
force_limits=$(sed -n 's/.*--limit=\([0-9][0-9]*\).*/\1/p' "$burst_root/force.log" | tr '\n' ' ' | sed 's/[[:space:]]*$//')
assert_eq "describe burst RUN_FORCE caps first chunk to live media total" "5" "$force_limits"
force_marker=$(tr -d '\r\n' <"$burst_root/demo/.acx-describe-first-burst.count")
assert_eq "describe burst RUN_FORCE marker stays within media total" "5" "$force_marker"

negative_output="$burst_root/negative.out"
negative_rc=0
run_bootstrap_burst flip "$negative_output" || negative_rc=$?
assert_eq "describe burst provenance flip rc" 1 "$negative_rc"
negative_calls=$(grep -c -- '--limit=10' "$burst_root/flip.log" || true)
assert_eq "describe burst stops after provenance flip" 1 "$negative_calls"
if grep -q 'provenance became untrusted after describe chunk 1' "$negative_output"; then
    echo "ok   describe burst blocks on mid-run provenance drift"
else
    echo "FAIL describe burst blocks on mid-run provenance drift"
    failures=$((failures + 1))
fi
fi
[ -n "${burst_root:-}" ] && rm -rf "$burst_root"

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
