#!/usr/bin/env bash
# AUTH-03: CI WordPress identity must be distinct from demo admin/viewer.
# Harness pattern matches test-describe-gate.sh / test-credential-lifecycle.sh.
# Run: bash infra/oci/demo/tests/test-ci-account-split.sh

if [ -z "${BASH_VERSION:-}" ]; then
    echo "FAIL $0 must run under bash, not sh/dash. Example: bash $0" >&2
    exit 2
fi

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
bootstrap_file="${script_dir}/../bootstrap-wp.sh"
workflow_file="${script_dir}/../../../../.github/workflows/deploy-demo.yml"
makefile_d="${script_dir}/../../../../Makefile.d/demo-auth.mk"
walkthrough_file="${script_dir}/../../../../apps/prototype-wp-alt-context/tests/e2e/evidence/demo-walkthrough.spec.ts"
api_file="${script_dir}/../../../../apps/prototype-wp-alt-context/src/api/class-api.php"

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
    if grep -qE -- "$pattern" "$file"; then
        echo "ok   ${label}"
    else
        echo "FAIL ${label}: expected ${file} to match /${pattern}/"
        failures=$((failures + 1))
    fi
}

assert_file_not_grep() {
    local label="$1" file="$2" pattern="$3"
    if grep -qE -- "$pattern" "$file"; then
        echo "FAIL ${label}: expected ${file} NOT to match /${pattern}/"
        failures=$((failures + 1))
    else
        echo "ok   ${label}"
    fi
}

r211_self=$(awk '
    /BASH_VERSION/ && !seen_pf { g=1 }
    /set -euo pipefail/ { seen_pf=1 }
    END { if (g) print "guard-before-pipefail"; else print "missing-guard" }
' "$0")
assert_eq "suite guards BASH_VERSION before pipefail" \
    "guard-before-pipefail" "$r211_self"

# --- bootstrap pins: CI account is required and distinct ---
assert_file_grep "bootstrap reads WP_CI_USER" "$bootstrap_file" 'env_get WP_CI_USER'
assert_file_grep "bootstrap reads WP_CI_PASSWORD" "$bootstrap_file" 'env_get WP_CI_PASSWORD'
assert_file_grep "bootstrap reads WP_CI_EMAIL" "$bootstrap_file" 'env_get WP_CI_EMAIL'
assert_file_grep "bootstrap requires WP_CI_USER" "$bootstrap_file" 'WP_CI_USER'
assert_file_grep "bootstrap calls converge_wp_ci_account" \
    "$bootstrap_file" 'converge_wp_ci_account "\$WP_CI_USER" "\$WP_CI_PASSWORD" "\$WP_CI_EMAIL" "\$WP_ADMIN_USER"'
after_install_calls=$(awk '
    /if ! wpcli wp core is-installed/ { in_gate=1 }
    in_gate && /^fi$/ { in_gate=0; after_fi=1; next }
    {
        if (in_gate) next
        line=$0
        sub(/^[ \t]+/, "", line)
        if (line ~ /^#/) next
        if (after_fi && line ~ /converge_wp_user_password[ \t]+"\$WP_ADMIN_USER"/) admin++
        if (after_fi && line ~ /converge_wp_ci_account[ \t]+"\$WP_CI_USER"/) ci++
    }
    END { print admin+0, ci+0 }
' "$bootstrap_file")
assert_eq "admin+CI converge calls sit on non-comment lines after install fi" \
    "1 1" "$after_install_calls"
assert_file_grep "CI role is acx_ci not administrator" \
    "$bootstrap_file" 'WP_CI_ROLE_NAME="acx_ci"'
assert_file_grep "CI role clones subscriber not administrator" \
    "$bootstrap_file" 'role create "\$WP_CI_ROLE_NAME" "ACX CI" --clone=subscriber'
assert_file_grep "CI role gains manage_options for plugin smoke" \
    "$bootstrap_file" 'cap add "\$WP_CI_ROLE_NAME" manage_options'
assert_file_grep "CI role gains upload_files for workbench media REST" \
    "$bootstrap_file" 'cap add "\$WP_CI_ROLE_NAME" upload_files'
assert_file_grep "workbench media REST requires upload_files" \
    "$api_file" "current_user_can\\( 'upload_files' \\)"
assert_file_grep "walkthrough fails closed when selectCount is 0" \
    "$walkthrough_file" 'selectCount === 0'
assert_file_grep "walkthrough empty-media path is an assertion not a skip" \
    "$walkthrough_file" 'toBeGreaterThan'

# --- deploy-demo.yml: CI secrets, not demo admin login ---
assert_file_grep "workflow smoke maps ACX_E2E_WP_CI_USER" \
    "$workflow_file" 'ACX_E2E_WP_ADMIN_USER: \$\{\{ secrets\.ACX_E2E_WP_CI_USER \}\}'
assert_file_grep "workflow smoke maps ACX_E2E_WP_CI_PASS" \
    "$workflow_file" 'ACX_E2E_WP_ADMIN_PASS: \$\{\{ secrets\.ACX_E2E_WP_CI_PASS \}\}'
assert_file_not_grep "workflow smoke does not inject demo-admin secret user" \
    "$workflow_file" 'ACX_E2E_WP_ADMIN_USER: \$\{\{ secrets\.ACX_E2E_WP_ADMIN_USER \}\}'
assert_file_not_grep "workflow smoke does not inject demo-admin secret pass" \
    "$workflow_file" 'ACX_E2E_WP_ADMIN_PASS: \$\{\{ secrets\.ACX_E2E_WP_ADMIN_PASS \}\}'
assert_file_grep "workflow refuses empty CI user" \
    "$workflow_file" 'ACX_E2E_WP_CI_USER must be set'
assert_file_grep "workflow refuses acx-demo-admin as CI user" \
    "$workflow_file" 'acx-demo-admin\|admin'

# --- Makefile.d wraps provision_demo.py (rg-006) ---
assert_file_grep "Makefile.d issue-demo-ci-account target exists" \
    "$makefile_d" '^issue-demo-ci-account:'
assert_file_grep "Makefile.d wraps scripts.provision_demo" \
    "$makefile_d" 'python -m scripts.provision_demo'
assert_file_grep "Makefile.d passes --account ci" \
    "$makefile_d" '--account ci'
assert_file_grep "Makefile.d passes --admin-user" \
    "$makefile_d" '--admin-user'

# --- behavioral: extracted CI converge ---
funcs=$(sed -n '/^# AUTH_CREDENTIAL_FUNCS_BEGIN$/,/^# AUTH_CREDENTIAL_FUNCS_END$/p' "$bootstrap_file")
if ! grep -q 'converge_wp_ci_account()' <<<"$funcs"; then
    echo "FAIL bootstrap credential block missing converge_wp_ci_account()"
    failures=$((failures + 1))
    echo
    echo "${failures} assertion(s) failed"
    exit 1
fi

ROLE_EXISTS=0
USERS=""
CURRENT_PASS_ADMIN="admin-secret"
CURRENT_PASS_CI=""
CREATE_CALLS=0
UPDATE_CALLS=0
SETROLE_CALLS=0
ROLE_CREATE_CALLS=0
CAP_ADD_CALLS=0
CAP_ADD_FAIL=0
CAPS_ADDED=""
LAST_CREATE_ROLE=""
LAST_CREATE_USER=""

wpcli() {
    local cmd="$1"
    shift || true
    if [ "$cmd" != "wp" ]; then
        echo "wpcli mock expected leading 'wp', got ${cmd}" >&2
        return 2
    fi
    case "$1 ${2:-}" in
        "role exists")
            if [ "$ROLE_EXISTS" = "1" ]; then return 0; else return 1; fi
            ;;
        "role create")
            ROLE_CREATE_CALLS=$((ROLE_CREATE_CALLS + 1))
            ROLE_EXISTS=1
            return 0
            ;;
        "cap add")
            CAP_ADD_CALLS=$((CAP_ADD_CALLS + 1))
            local cap
            for cap in "${@:4}"; do
                CAPS_ADDED="${CAPS_ADDED} ${cap}"
            done
            if [ "$CAP_ADD_FAIL" = "1" ]; then return 1; fi
            return 0
            ;;
        "user get")
            local u="$3"
            case " $USERS " in
                *" $u "*) return 0 ;;
                *) return 1 ;;
            esac
            ;;
        "user create")
            CREATE_CALLS=$((CREATE_CALLS + 1))
            LAST_CREATE_USER="$3"
            local arg
            for arg in "$@"; do
                case "$arg" in
                    --role=*) LAST_CREATE_ROLE="${arg#--role=}" ;;
                    --user_pass=*) CURRENT_PASS_CI="${arg#--user_pass=}" ;;
                esac
            done
            USERS="${USERS} $3"
            return 0
            ;;
        "user set-role")
            SETROLE_CALLS=$((SETROLE_CALLS + 1))
            return 0
            ;;
        "user check-password")
            local u="$3" p="$4" have=""
            if [ "$u" = "acx-demo-admin" ]; then have="$CURRENT_PASS_ADMIN"
            else have="$CURRENT_PASS_CI"
            fi
            if [ "$p" = "$have" ]; then return 0; else return 1; fi
            ;;
        "user update")
            UPDATE_CALLS=$((UPDATE_CALLS + 1))
            local arg u="$3" pass=""
            for arg in "$@"; do
                case "$arg" in
                    --user_pass=*) pass="${arg#--user_pass=}" ;;
                esac
            done
            if [ "$u" = "acx-demo-admin" ]; then CURRENT_PASS_ADMIN="$pass"
            else CURRENT_PASS_CI="$pass"
            fi
            return 0
            ;;
        *)
            echo "wpcli mock unexpected: $*" >&2
            return 2
            ;;
    esac
}

eval "$funcs"

# Collision with admin is loud
rc=0
converge_wp_ci_account "acx-demo-admin" "ci-secret" "ci@example.com" "acx-demo-admin" >/dev/null 2>/dev/null || rc=$?
assert_eq "CI user equal to admin exits 2" "2" "$rc"
assert_eq "collision does not create a user" "0" "$CREATE_CALLS"

# Missing fields fail loud
rc=0
converge_wp_ci_account "" "ci-secret" "ci@example.com" "acx-demo-admin" >/dev/null 2>/dev/null || rc=$?
assert_eq "empty CI user exits 2" "2" "$rc"

# First apply creates least-privilege user
CREATE_CALLS=0
ROLE_CREATE_CALLS=0
CAP_ADD_CALLS=0
CAPS_ADDED=""
ROLE_EXISTS=0
USERS=""
CURRENT_PASS_CI=""
rc=0
converge_wp_ci_account "acx-demo-ci" "ci-secret" "ci@example.com" "acx-demo-admin" >/dev/null || rc=$?
assert_eq "first CI converge exits 0" "0" "$rc"
assert_eq "first CI converge creates the role" "1" "$ROLE_CREATE_CALLS"
assert_eq "first CI converge creates the user" "1" "$CREATE_CALLS"
assert_eq "CI user created under acx_ci role" "acx_ci" "$LAST_CREATE_ROLE"
assert_eq "CI username is acx-demo-ci" "acx-demo-ci" "$LAST_CREATE_USER"
assert_eq "first CI converge cap-adds twice (manage_options + upload_files)" "2" "$CAP_ADD_CALLS"
case " ${CAPS_ADDED} " in
    *" upload_files "*) upload_files_granted=1 ;;
    *) upload_files_granted=0 ;;
esac
assert_eq "first CI converge grants upload_files" "1" "$upload_files_granted"

# Role already exists: still re-grant caps (failed first cap-add must not stick)
CAP_ADD_CALLS=0
CAPS_ADDED=""
ROLE_EXISTS=1
rc=0
ensure_wp_ci_role >/dev/null || rc=$?
assert_eq "existing-role retry exits 0" "0" "$rc"
assert_eq "existing-role retry cap-adds twice" "2" "$CAP_ADD_CALLS"
case " ${CAPS_ADDED} " in
    *" manage_options "*) retry_manage=1 ;;
    *) retry_manage=0 ;;
esac
case " ${CAPS_ADDED} " in
    *" upload_files "*) retry_upload=1 ;;
    *) retry_upload=0 ;;
esac
assert_eq "existing-role retry re-grants manage_options" "1" "$retry_manage"
assert_eq "existing-role retry re-grants upload_files" "1" "$retry_upload"
CAP_ADD_FAIL=1
rc=0
ensure_wp_ci_role >/dev/null 2>/dev/null || rc=$?
assert_eq "cap-add failure on existing role exits 2" "2" "$rc"
CAP_ADD_FAIL=0

# Unchanged CI secret is a no-op (user exists)
UPDATE_CALLS=0
CREATE_CALLS=0
SETROLE_CALLS=0
rc=0
converge_wp_ci_account "acx-demo-ci" "ci-secret" "ci@example.com" "acx-demo-admin" >/dev/null || rc=$?
assert_eq "unchanged CI secret exits 0" "0" "$rc"
assert_eq "unchanged CI secret does not recreate user" "0" "$CREATE_CALLS"
assert_eq "unchanged CI secret does not rotate password" "0" "$UPDATE_CALLS"
assert_eq "existing CI user is pinned to acx_ci" "1" "$SETROLE_CALLS"

# Changed CI secret rotates
UPDATE_CALLS=0
rc=0
converge_wp_ci_account "acx-demo-ci" "ci-rotated" "ci@example.com" "acx-demo-admin" >/dev/null || rc=$?
assert_eq "changed CI secret exits 0" "0" "$rc"
assert_eq "changed CI secret rotates via user update" "1" "$UPDATE_CALLS"
assert_eq "changed CI secret store converges" "ci-rotated" "$CURRENT_PASS_CI"

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} assertion(s) failed"
    exit 1
fi
echo "all assertions passed"
