#!/usr/bin/env bash
# Pure-local tests for install-reap-cron.sh. No real crontab is touched: a fake
# `crontab` on PATH backs onto a file.
#
# The installer is the reclaimer's own delivery path, so it has to roll forward.
# VMDISK-1: the VM was already carrying an entry that swept only ~/w3, and the
# marker check made re-running the installer a no-op -- widening the roots in
# reap-lane.sh would have shipped a fix that never reached the machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT}/scripts/vm/install-reap-cron.sh"

failures=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

[[ -f "$SCRIPT" ]] || { echo "FAIL: missing $SCRIPT"; exit 1; }

WORKDIR="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/reap-cron-test.XXXXXX")" && pwd -P)"
trap 'rm -rf "$WORKDIR"' EXIT
export HOME="$WORKDIR"

# Fake crontab: `-l` prints the file, `-` replaces it from stdin.
mkdir -p "$WORKDIR/fakebin"
export CRONTAB_FILE="$WORKDIR/crontab.txt"
cat >"$WORKDIR/fakebin/crontab" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -l) [[ -s "$CRONTAB_FILE" ]] || exit 1; cat "$CRONTAB_FILE" ;;
  -)  cat >"$CRONTAB_FILE" ;;
  *)  echo "fake crontab: unsupported: $*" >&2; exit 2 ;;
esac
FAKE
chmod +x "$WORKDIR/fakebin/crontab"
export PATH="$WORKDIR/fakebin:$PATH"

run_install() {
  out=""
  rc=0
  out="$(bash "$SCRIPT" 2>&1)" || rc=$?
}

assert_rc0() {
  if [[ "$rc" -eq 0 ]]; then pass "$1 exit 0"; else fail "$1 exit $rc; out=$out"; fi
}

assert_one_marker() {
  local n
  n="$(count_marker)"
  if [[ "$n" -eq 1 ]]; then pass "$1 keeps exactly one marker"; else fail "$1 left $n markers"; fi
}
assert_cron_contains() {
  # -e: the needles include leading `--`, which grep would read as an option.
  if grep -qFe "$2" "$CRONTAB_FILE"; then pass "$1 crontab contains $2"
  else fail "$1 crontab missing '$2'; crontab=$(cat "$CRONTAB_FILE")"; fi
}
assert_cron_absent() {
  if grep -qFe "$2" "$CRONTAB_FILE"; then fail "$1 crontab still has '$2'"
  else pass "$1 crontab free of $2"; fi
}
count_marker() { grep -cF '# acx-reap-lane' "$CRONTAB_FILE" || true; }

# --- fresh install ------------------------------------------------------------
: >"$CRONTAB_FILE"
run_install
assert_rc0 "fresh"

if [[ -x "$HOME/bin/reap-lane.sh" ]]; then pass "fresh installs the script"
else fail "fresh: $HOME/bin/reap-lane.sh not executable"; fi

# Every root that accumulates lanes must be swept, not just w3.
# Asserted as a whole `--all $HOME/<root> ` token: a bare "$HOME/w" substring
# would be satisfied by "$HOME/w3" and the widening would go unnoticed.
for root in w3 uxw2 l1 w lanes; do
  assert_cron_contains "fresh" "--all \$HOME/$root "
done

# --- idempotence: a second run must not duplicate the entry -------------------
run_install
assert_rc0 "rerun"
assert_one_marker "rerun"

# --- roll-forward: a stale narrow entry is REPLACED, not preserved ------------
cat >"$CRONTAB_FILE" <<'STALE'
0 3 * * * /usr/bin/some-other-job
# acx-reap-lane
17 6 * * 1 $HOME/bin/reap-lane.sh --yes --all $HOME/w3 >> $HOME/reap-lane.log 2>&1
STALE
run_install
assert_rc0 "roll-forward"
assert_cron_contains "roll-forward" "--all \$HOME/lanes "
# shellcheck disable=SC2016  # literal $HOME: this is cron text, not a path here.
assert_cron_absent "roll-forward" '--all $HOME/w3 >>'
assert_one_marker "roll-forward"

# An unrelated entry belonging to someone else must survive untouched.
assert_cron_contains "roll-forward" "/usr/bin/some-other-job"

# --- the installed copy is the current one, not a stale one -------------------
printf '# stale\n' >"$HOME/bin/reap-lane.sh"
run_install
if cmp -s "$HOME/bin/reap-lane.sh" "${ROOT}/scripts/vm/reap-lane.sh"; then
  pass "reinstall refreshes the copied script"
else
  fail "reinstall left a stale $HOME/bin/reap-lane.sh"
fi

echo
if [[ "$failures" -gt 0 ]]; then
  echo "$failures FAILED"
  exit 1
fi
echo "all cases passed"
