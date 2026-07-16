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

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
