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
fi

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
