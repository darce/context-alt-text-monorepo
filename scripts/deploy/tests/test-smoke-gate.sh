#!/usr/bin/env bash
# Characterization test for the sync-demo.sh vhost-smoke gate matrix
# (scripts/deploy/lib/smoke-gate.sh). Pins PASS/WARN/FAIL semantics so a gate
# regression is caught without a live deploy. Run: bash scripts/deploy/tests/test-smoke-gate.sh

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/smoke-gate.sh
source "${script_dir}/../lib/smoke-gate.sh"

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
assert_eq "alt coverage 2/3 >= 60 (integer math keeps a true pass)" PASS "$(classify_alt_coverage 3 2 60)"
assert_eq "alt coverage 1/3 < 60" FAIL "$(classify_alt_coverage 3 1 60)"
# R1-02B: the floor is a fixed safety constant (50), not a policy knob.
# classify_alt_coverage 100 0 0 used to evaluate 0>=0 and print PASS.
assert_eq "alt coverage min_pct 0 below fixed floor (certify-a-lie)" FAIL "$(classify_alt_coverage 100 0 0)"
assert_eq "alt coverage 100 0 49 below fixed floor" FAIL "$(classify_alt_coverage 100 0 49)"
assert_eq "alt coverage 100 100 50 at the floor, full coverage" PASS "$(classify_alt_coverage 100 100 50)"
assert_eq "alt coverage 100 95 95 shipped default still works" PASS "$(classify_alt_coverage 100 95 95)"
assert_eq "alt coverage 100/100 but min_pct 49 below floor 50" FAIL "$(classify_alt_coverage 100 100 49)"
assert_eq "alt coverage 50/100 >= 50 equals fixed floor" PASS "$(classify_alt_coverage 100 50 50)"
assert_eq "alt coverage 49/100 < floor 50" FAIL "$(classify_alt_coverage 100 49 50)"
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

# --- classify_alt_population <header_total> <body_total> ---
assert_eq "alt population 100 == 100" PASS "$(classify_alt_population 100 100)"
assert_eq "alt population 250 vs 100 (paged subset)" FAIL "$(classify_alt_population 250 100)"
assert_eq "alt population 100 vs 250 (body exceeds header)" FAIL "$(classify_alt_population 100 250)"
assert_eq "alt population empty header" FAIL "$(classify_alt_population '' 100)"
assert_eq "alt population empty body" FAIL "$(classify_alt_population 100 '')"
assert_eq "alt population non-numeric header" FAIL "$(classify_alt_population abc 100)"
assert_eq "alt population 0 == 0 (nothing measured)" FAIL "$(classify_alt_population 0 0)"

# --- classify_alt_provenance <sample_text> ---
assert_eq "alt provenance empty sample (cannot prove)" FAIL "$(classify_alt_provenance '')"
assert_eq "alt provenance live seeded draft on demo media id 5" FAIL "$(classify_alt_provenance 'antonio_banderas_10. A close-up of a small object on a neutral background.')"
assert_eq "alt provenance real caption (not a fixture)" PASS "$(classify_alt_provenance 'A woman in a red coat speaks at a podium in front of a blue backdrop.')"
assert_eq "alt provenance fixture: person outdoors" FAIL "$(classify_alt_provenance 'A person standing outdoors near greenery.')"
assert_eq "alt provenance fixture: plate of food" FAIL "$(classify_alt_provenance 'A plate of food on a wooden table.')"
assert_eq "alt provenance fixture: scenic landscape" FAIL "$(classify_alt_provenance 'A scenic landscape with mountains under a clear sky.')"
assert_eq "alt provenance fixture: close-up object" FAIL "$(classify_alt_provenance 'A close-up of a small object on a neutral background.')"
assert_eq "alt provenance fixture: printed document" FAIL "$(classify_alt_provenance 'A printed document with several lines of text.')"
assert_eq "alt provenance fixture: two people seated" FAIL "$(classify_alt_provenance 'Two people seated indoors in conversation.')"
assert_eq "alt provenance fixture: building exterior" FAIL "$(classify_alt_provenance 'A building exterior seen from the street.')"
assert_eq "alt provenance fixture: pet animal" FAIL "$(classify_alt_provenance 'A pet animal resting on a soft surface.')"
# R1-03b: trivial denylist evasions must still FAIL.
assert_eq "alt provenance lowercase first letter still fixture" FAIL "$(classify_alt_provenance 'a person standing outdoors near greenery.')"
assert_eq "alt provenance dropped trailing period still fixture" FAIL "$(classify_alt_provenance 'A person standing outdoors near greenery')"
assert_eq "alt provenance extra internal whitespace still fixture" FAIL "$(classify_alt_provenance 'A person  standing   outdoors near greenery.')"
assert_eq "alt provenance trailing bang still fixture" FAIL "$(classify_alt_provenance 'A person standing outdoors near greenery!')"

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

# TEST-15 mutation proof (2026-08-25): adding a 9th _FIXTURE_POOL caption
# not present in smoke-gate.sh makes this suite exit 1 with:
# FAIL drift: pool caption classified FAIL (A drift sentinel caption that is not in the shell gate.): expected FAIL, got PASS
# Reverted; suite green. The guard is falsifiable, not merely passing.
# Drift guard: every caption in the Python _FIXTURE_POOL must FAIL provenance.
# If a fixture is added to seeded_adapter.py and not hardcoded in smoke-gate.sh,
# this goes red. Missing source file is a FAIL, not a skip.
adapter_file=$(cd "${script_dir}/../../.." && pwd)/apps/prototype-description-service/scene/application/seeded_adapter.py
if [ ! -f "$adapter_file" ]; then
    echo "FAIL fixture-pool source missing: ${adapter_file}"
    failures=$((failures + 1))
else
    extracted=0
    while IFS= read -r caption; do
        [ -n "$caption" ] || continue
        extracted=$((extracted + 1))
        assert_eq "drift: pool caption classified FAIL (${caption})" FAIL "$(classify_alt_provenance "$caption")"
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
    assert_eq "R1-01 coverage emit_alt_gate overridable=1" 'emit_alt_gate "$verdict" "$cov_msg" 1' "$cov_line"
    assert_eq "R1-01 provenance emit_alt_gate overridable=0" 'emit_alt_gate "$prov" "$prov_msg" 0' "$prov_line"
    if grep -q 'The override covers empty alt, never canned captions.' "$sync_demo"; then
        echo "ok   R1-01 header states override covers empty alt, never canned captions"
    else
        echo "FAIL R1-01 header missing 'The override covers empty alt, never canned captions.'"
        failures=$((failures + 1))
    fi
    if grep -q 'classify_alt_text_usable' "$sync_demo"; then
        echo "ok   R1-03 classify_alt_text_usable wired into sync-demo.sh"
    else
        echo "FAIL R1-03 classify_alt_text_usable not wired into sync-demo.sh"
        failures=$((failures + 1))
    fi
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
        cov_override=$(run_emit 0 FAIL "demo alt coverage (0/100 = 0%, need 95%)" 1)
        assert_eq "R1-01 coverage FAIL overridable under DEMO_ALT_GATE_ENFORCE=0" \
            "WARN demo alt coverage (0/100 = 0%, need 95%) (enforcement disabled via DEMO_ALT_GATE_ENFORCE=0)
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
            pop=$(classify_alt_population "$header_total" "$body_total")
            emit_alt_gate "$pop" "demo alt population (header=${header_total} body=${body_total})" 1
            verdict=$(classify_alt_coverage "$body_total" "$with_alt" "$min")
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
    fi
fi

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
