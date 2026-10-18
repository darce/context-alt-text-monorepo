#!/usr/bin/env bash
# Pure-local tests for db-reset-remote.sh (no network / SSH).
# Exit non-zero on any failure.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT}/scripts/deploy/db-reset-remote.sh"
SYNC_DEMO="${ROOT}/scripts/deploy/sync-demo.sh"

failures=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

# (a) bash -n on both scripts
if bash -n "$SCRIPT" && bash -n "$SYNC_DEMO"; then
  pass "bash -n db-reset-remote.sh and sync-demo.sh"
else
  fail "bash -n syntax check"
fi

# (b) ENV=prod dry-run exits non-zero
set +e
out="$(ENV=prod CONFIRM=RESET "$SCRIPT" --dry-run 2>&1)"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  pass "ENV=prod refused (exit $rc)"
else
  fail "ENV=prod should exit non-zero; got 0. out=$out"
fi

# (c) ENV=bogus exits non-zero
set +e
out="$(ENV=bogus CONFIRM=RESET "$SCRIPT" --dry-run 2>&1)"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  pass "ENV=bogus refused (exit $rc)"
else
  fail "ENV=bogus should exit non-zero; got 0. out=$out"
fi

# (d) missing CONFIRM exits non-zero
set +e
out="$(ENV=dev CONFIRM= "$SCRIPT" --dry-run 2>&1)"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  pass "missing CONFIRM refused (exit $rc)"
else
  fail "missing CONFIRM should exit non-zero; got 0. out=$out"
fi

# (e) ENV=dev CONFIRM=RESET --dry-run output checks
set +e
out="$(ENV=dev CONFIRM=RESET "$SCRIPT" --dry-run 2>&1)"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  fail "ENV=dev CONFIRM=RESET --dry-run should exit 0; got $rc. out=$out"
elif [[ "$out" != *"DROP SCHEMA public CASCADE"* ]]; then
  fail "dev dry-run missing DROP SCHEMA public CASCADE. out=$out"
elif [[ "$out" != *"acx-dev-postgres-1"* ]]; then
  fail "dev dry-run missing acx-dev-postgres-1. out=$out"
elif [[ "$out" != *"dev.api.altcontext.com/health"* ]]; then
  fail "dev dry-run missing dev.api.altcontext.com/health. out=$out"
else
  pass "ENV=dev CONFIRM=RESET --dry-run output"
fi

# (f) ENV=staging CONFIRM=RESET --dry-run contains staging postgres container
set +e
out="$(ENV=staging CONFIRM=RESET "$SCRIPT" --dry-run 2>&1)"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  fail "ENV=staging CONFIRM=RESET --dry-run should exit 0; got $rc. out=$out"
elif [[ "$out" != *"acx-staging-postgres-1"* ]]; then
  fail "staging dry-run missing acx-staging-postgres-1. out=$out"
else
  pass "ENV=staging CONFIRM=RESET --dry-run output"
fi

if [[ $failures -gt 0 ]]; then
  echo "FAILED: $failures case(s)"
  exit 1
fi
echo "ALL PASS"
exit 0
