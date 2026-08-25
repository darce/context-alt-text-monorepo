#!/usr/bin/env bash
# AUTH-01: demo wp-admin credential must converge on every bootstrap run.
# Characterization + behavioral harness (same shape as test-describe-gate.sh).
# Proves: (1) a second run with a changed secret rotates via wp user update;
# (2) an unchanged secret is a no-op. No live WordPress — wpcli is a seam.
# Run: bash infra/oci/demo/tests/test-credential-lifecycle.sh

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash, not sh/dash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
bootstrap_file="${script_dir}/../bootstrap-wp.sh"

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

assert_file_grep() {
    local label="$1" file="$2" pattern="$3"
    if grep -qE "$pattern" "$file"; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: expected ${file} to match /${pattern}/"
        failures=$((failures + 1))
    fi
}

r211_self=$(awk '
    /BASH_VERSION/ && !seen_pf { g=1 }
    /set -euo pipefail/ { seen_pf=1 }
    END { if (g) print "guard-before-pipefail"; else print "missing-guard" }
' "$0")
assert_eq "suite guards BASH_VERSION before pipefail" \
    "guard-before-pipefail" "$r211_self"

# --- source pins: rotation is not trapped behind first-install ---
assert_file_grep "bootstrap uses wp user update for rotation" \
    "$bootstrap_file" 'wp user update'
assert_file_grep "bootstrap checks current password before update" \
    "$bootstrap_file" 'wp user check-password'
assert_file_grep "bootstrap calls converge_wp_user_password on admin" \
    "$bootstrap_file" 'converge_wp_user_password "\$WP_ADMIN_USER" "\$WP_ADMIN_PASSWORD"'
assert_file_grep "rotation failure is loud (ERROR)" \
    "$bootstrap_file" 'ERROR: failed to rotate WordPress credential'

# The first-install gate must not be the only consumer of WP_ADMIN_PASSWORD.
# Count user-update / check-password sites; they must sit outside the
# `if ! wpcli wp core is-installed` block (AUTH-01: second run must rotate).
outside_install_gate=$(awk '
    /if ! wpcli wp core is-installed/ { in_gate=1 }
    in_gate && /^fi$/ { in_gate=0; next }
    in_gate { next }
    /wpcli wp user check-password/ { checks++ }
    /wpcli wp user update/ { updates++ }
    END { print checks+0, updates+0 }
' "$bootstrap_file")
assert_eq "check-password + user-update live outside first-install gate" \
    "1 1" "$outside_install_gate"

# --- extract credential functions and exercise a mocked wpcli ---
funcs=$(sed -n '/^# AUTH_CREDENTIAL_FUNCS_BEGIN$/,/^# AUTH_CREDENTIAL_FUNCS_END$/p' "$bootstrap_file")
if ! grep -q 'converge_wp_user_password()' <<<"$funcs"; then
    echo "FAIL bootstrap credential block missing converge_wp_user_password()"
    failures=$((failures + 1))
    echo
    if [ "$failures" -gt 0 ]; then
        echo "${failures} assertion(s) failed"
        exit 1
    fi
fi

# Mocked WordPress user store.
CURRENT_PASS="alpha"
INSTALLED=1
UPDATE_FAIL=0
CHECK_CALLS=0
UPDATE_CALLS=0
LAST_UPDATE_USER=""

wpcli() {
    local cmd="$1"
    shift || true
    if [ "$cmd" != "wp" ]; then
        echo "wpcli mock expected leading 'wp', got ${cmd}" >&2
        return 2
    fi
    case "$1 ${2:-}" in
        "core is-installed")
            if [ "$INSTALLED" = "1" ]; then return 0; else return 1; fi
            ;;
        "user check-password")
            CHECK_CALLS=$((CHECK_CALLS + 1))
            local _user="$3" _pass="$4"
            if [ "$_pass" = "$CURRENT_PASS" ]; then return 0; else return 1; fi
            ;;
        "user update")
            UPDATE_CALLS=$((UPDATE_CALLS + 1))
            LAST_UPDATE_USER="$3"
            local arg pass=""
            for arg in "$@"; do
                case "$arg" in
                    --user_pass=*) pass="${arg#--user_pass=}" ;;
                esac
            done
            if [ "$UPDATE_FAIL" = "1" ]; then return 1; fi
            CURRENT_PASS="$pass"
            return 0
            ;;
        *)
            echo "wpcli mock unexpected: $*" >&2
            return 2
            ;;
    esac
}

eval "$funcs"

# (2) unchanged secret is a no-op
CHECK_CALLS=0
UPDATE_CALLS=0
CURRENT_PASS="alpha"
converge_rc=0
converge_wp_user_password "acx-demo-admin" "alpha" >/dev/null || converge_rc=$?
assert_eq "unchanged secret exits 0" "0" "$converge_rc"
assert_eq "unchanged secret does not call wp user update" "0" "$UPDATE_CALLS"
assert_eq "unchanged secret still probes check-password" "1" "$CHECK_CALLS"
assert_eq "unchanged secret leaves store at alpha" "alpha" "$CURRENT_PASS"

# (1) second run with a changed secret rotates
CHECK_CALLS=0
UPDATE_CALLS=0
CURRENT_PASS="alpha"
converge_rc=0
converge_wp_user_password "acx-demo-admin" "beta" >/dev/null || converge_rc=$?
assert_eq "changed secret exits 0" "0" "$converge_rc"
assert_eq "changed secret calls wp user update once" "1" "$UPDATE_CALLS"
assert_eq "changed secret updates the admin user" "acx-demo-admin" "$LAST_UPDATE_USER"
assert_eq "changed secret store converges to beta" "beta" "$CURRENT_PASS"
# check-password: mismatch (1) + post-update verify (1)
assert_eq "changed secret re-checks after update" "2" "$CHECK_CALLS"

# Loud failure if update cannot apply
UPDATE_FAIL=1
UPDATE_CALLS=0
CURRENT_PASS="alpha"
converge_rc=0
converge_wp_user_password "acx-demo-admin" "gamma" >/dev/null 2>/dev/null || converge_rc=$?
assert_eq "failed rotation exits 2" "2" "$converge_rc"
assert_eq "failed rotation attempted update" "1" "$UPDATE_CALLS"
assert_eq "failed rotation leaves original secret" "alpha" "$CURRENT_PASS"
UPDATE_FAIL=0

# Post-update verify fail (update reported ok but password did not land)
CURRENT_PASS="alpha"
UPDATE_CALLS=0
wpcli() {
    local cmd="$1"
    shift || true
    case "$1 ${2:-}" in
        "user check-password")
            return 1
            ;;
        "user update")
            UPDATE_CALLS=$((UPDATE_CALLS + 1))
            return 0
            ;;
        *)
            return 2
            ;;
    esac
}
converge_rc=0
converge_wp_user_password "acx-demo-admin" "delta" >/dev/null 2>/dev/null || converge_rc=$?
assert_eq "update-without-converge exits 2" "2" "$converge_rc"
assert_eq "update-without-converge still called update" "1" "$UPDATE_CALLS"

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
