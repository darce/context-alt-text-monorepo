#!/usr/bin/env bash
# Characterization test for the demo bootstrap describe-apply gate
# (infra/oci/demo/lib/describe-gate.sh). Pins RUN/SKIP/BLOCK so a fail-open
# regression (especially allowing the canned `seeded` adapter) is caught
# without a live WordPress. Run: bash infra/oci/demo/tests/test-describe-gate.sh

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/describe-gate.sh
source "${script_dir}/../lib/describe-gate.sh"

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

# --- classify_describe_gate <adapter_profile> <total_media> <media_with_alt> ---
# Adapter allowlist is the first gate. Anything other than the three trusted
# live adapters BLOCKs — including today's production `seeded` profile.
assert_eq "seeded 100 0 (live situation)" BLOCK "$(classify_describe_gate seeded 100 0)"
assert_eq "empty profile 100 0"          BLOCK "$(classify_describe_gate '' 100 0)"
assert_eq "unknown_profile 100 0"        BLOCK "$(classify_describe_gate unknown_profile 100 0)"
assert_eq "hosted_gpt4o 100 0 (stub)"    BLOCK "$(classify_describe_gate hosted_gpt4o 100 0)"
assert_eq "gpu_phi4 100 0 (stub)"        BLOCK "$(classify_describe_gate gpu_phi4 100 0)"
assert_eq "florence_large 100 0 (stub)"  BLOCK "$(classify_describe_gate florence_large 100 0)"
assert_eq "SEEDED 100 0 (case hole)"     BLOCK "$(classify_describe_gate SEEDED 100 0)"
# Profile check precedes measurement: a bad profile with a broken probe still
# BLOCKs instead of crashing or skipping.
assert_eq "seeded empty empty (profile first)" BLOCK "$(classify_describe_gate seeded '' '')"

# Trusted adapters + missing alt -> RUN.
assert_eq "florence_small 100 0"               RUN "$(classify_describe_gate florence_small 100 0)"
assert_eq "gpu_qwen30b 100 40 (partial)"        RUN "$(classify_describe_gate gpu_qwen30b 100 40)"
assert_eq "florence_small 100 99 (one missing)" RUN "$(classify_describe_gate florence_small 100 99)"

# Idempotent full coverage / no media -> SKIP.
assert_eq "gpu_qwen30b_ensemble 100 100 (full)" SKIP "$(classify_describe_gate gpu_qwen30b_ensemble 100 100)"
assert_eq "florence_small 0 0 (no media)"       SKIP "$(classify_describe_gate florence_small 0 0)"
assert_eq "florence_small 10 10 (full)"         SKIP "$(classify_describe_gate florence_small 10 10)"

# Broken probe -> BLOCK (never guess).
assert_eq "florence_small empty total" BLOCK "$(classify_describe_gate florence_small '' 0)"
assert_eq "florence_small non-numeric alt" BLOCK "$(classify_describe_gate florence_small 100 abc)"
assert_eq "florence_small alt > total" BLOCK "$(classify_describe_gate florence_small 100 200)"
assert_eq "florence_small 0 1 (alt > total)" BLOCK "$(classify_describe_gate florence_small 0 1)"

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
