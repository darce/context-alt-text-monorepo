#!/usr/bin/env bash
# Regression tests for package-plugin.sh runtime staging. The fixtures live in
# temporary directories so the repository's dist/ directory is never changed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PACKAGER="${ROOT}/scripts/release/package-plugin.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/acx-package-plugin-test.XXXXXX")"
trap 'rm -rf "${TEST_ROOT}"' EXIT

failures=0
pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }

assert_file() {
    local label="$1"
    local path="$2"
    if [[ -f "${path}" ]]; then
        pass "${label} (${path})"
    else
        fail "${label} (missing ${path})"
    fi
}

assert_output_contains() {
    local label="$1"
    local needle="$2"
    local output="$3"
    if [[ "${output}" == *"${needle}"* ]]; then
        pass "${label}"
    else
        fail "${label} (missing '${needle}'; output: ${output})"
    fi
}

assert_zip_contains() {
    local label="$1"
    local zip_path="$2"
    local member="$3"
    local listing=""

    if ! listing="$(unzip -Z1 "${zip_path}" 2>&1)"; then
        fail "${label} (could not list ${zip_path}: ${listing})"
    elif printf '%s\n' "${listing}" | grep -Fqx "${member}"; then
        pass "${label}"
    else
        fail "${label} (missing '${member}'; listing: ${listing})"
    fi
}

assert_zip_excludes() {
    local label="$1"
    local zip_path="$2"
    local member="$3"
    local listing=""

    if ! listing="$(unzip -Z1 "${zip_path}" 2>&1)"; then
        fail "${label} (could not list ${zip_path}: ${listing})"
    elif printf '%s\n' "${listing}" | grep -Fqx "${member}"; then
        fail "${label} (unexpected '${member}'; listing: ${listing})"
    else
        pass "${label}"
    fi
}

create_common_fixture() {
    local fixture_dir="$1"

    mkdir -p "${fixture_dir}/src" \
        "${fixture_dir}/public/assets/dist" \
        "${fixture_dir}/vendor"

    cat >"${fixture_dir}/alt-context.php" <<'PHP'
<?php

/**
 * Version: 0.0.1
 */
PHP
    printf '%s\n' '{"version":"0.0.1"}' >"${fixture_dir}/package.json"
    printf '%s\n' '{"name":"fixture/alt-context"}' >"${fixture_dir}/composer.json"
    printf '%s\n' '<?php' >"${fixture_dir}/vendor/autoload.php"
    printf '%s\n' '<?php // fixture source' >"${fixture_dir}/src/x.php"
    printf '%s\n' '{}' >"${fixture_dir}/public/assets/dist/manifest.json"
}

run_packager() {
    local fixture_dir="$1"
    local dist_dir="$2"

    last_output=""
    last_rc=0
    last_output="$(
        ACX_PACKAGE_PLUGIN_DIR="${fixture_dir}" \
        ACX_PACKAGE_DIST_DIR="${dist_dir}" \
        bash "${PACKAGER}" --no-build 2>&1
    )" || last_rc=$?
}

help_output="$(bash "${PACKAGER}" --help 2>&1)"
assert_output_contains \
    "--help documents optional js/public staging" \
    "js/public" \
    "${help_output}"

# --- Case 1: stage runtime JS/CSS while excluding declarations and tests. ----
case_one_fixture="${TEST_ROOT}/with-public"
case_one_dist="${TEST_ROOT}/dist-with-public"
create_common_fixture "${case_one_fixture}"
mkdir -p "${case_one_fixture}/js/public/__tests__"
printf '%s\n' 'console.log("demo");' >"${case_one_fixture}/js/public/demo-describe.js"
printf '%s\n' '.demo {}' >"${case_one_fixture}/js/public/demo-describe.css"
printf '%s\n' 'declare const demo: unknown;' >"${case_one_fixture}/js/public/demo-describe.d.ts"
printf '%s\n' 'test("demo", () => {});' >"${case_one_fixture}/js/public/demo-describe.test.ts"
printf '%s\n' 'test("nested", () => {});' >"${case_one_fixture}/js/public/__tests__/x.test.ts"

case_one_before=$failures
run_packager "${case_one_fixture}" "${case_one_dist}"
if [[ "${last_rc}" -eq 0 ]]; then
    pass "case 1 packages with js/public"
    case_one_zip="${case_one_dist}/alt-context-0.0.1.zip"
    assert_file "case 1 creates the artifact" "${case_one_zip}"
    if [[ -f "${case_one_zip}" ]]; then
        assert_zip_contains "case 1 includes public JavaScript" "${case_one_zip}" \
            "alt-context/js/public/demo-describe.js"
        assert_zip_contains "case 1 includes public CSS" "${case_one_zip}" \
            "alt-context/js/public/demo-describe.css"
        assert_zip_excludes "case 1 excludes TypeScript declarations" "${case_one_zip}" \
            "alt-context/js/public/demo-describe.d.ts"
        assert_zip_excludes "case 1 excludes public test files" "${case_one_zip}" \
            "alt-context/js/public/demo-describe.test.ts"
        assert_zip_excludes "case 1 excludes public __tests__" "${case_one_zip}" \
            "alt-context/js/public/__tests__/x.test.ts"
    fi
else
    fail "case 1 packages with js/public (exit ${last_rc}; output: ${last_output})"
fi
if [[ "${failures}" -eq "${case_one_before}" ]]; then
    pass "case 1 regression"
else
    printf 'FAIL: case 1 regression\n' >&2
fi

# --- Case 2: retain the pre-js/public layout when the directory is absent. ---
case_two_fixture="${TEST_ROOT}/without-public"
case_two_dist="${TEST_ROOT}/dist-without-public"
create_common_fixture "${case_two_fixture}"

case_two_before=$failures
run_packager "${case_two_fixture}" "${case_two_dist}"
if [[ "${last_rc}" -eq 0 ]]; then
    pass "case 2 packages without js/public"
    assert_file "case 2 creates the artifact" "${case_two_dist}/alt-context-0.0.1.zip"
else
    fail "case 2 packages without js/public (exit ${last_rc}; output: ${last_output})"
fi
if [[ "${failures}" -eq "${case_two_before}" ]]; then
    pass "case 2 regression"
else
    printf 'FAIL: case 2 regression\n' >&2
fi

# --- Case 3: fail closed when js/public has no JavaScript runtime file. ------
case_three_fixture="${TEST_ROOT}/css-only"
case_three_dist="${TEST_ROOT}/dist-css-only"
create_common_fixture "${case_three_fixture}"
mkdir -p "${case_three_fixture}/js/public"
printf '%s\n' '.demo {}' >"${case_three_fixture}/js/public/demo-describe.css"

case_three_before=$failures
run_packager "${case_three_fixture}" "${case_three_dist}"
if [[ "${last_rc}" -ne 0 ]]; then
    pass "case 3 rejects js/public without JavaScript"
    assert_output_contains \
        "case 3 reports the invalid js/public directory" \
        "ERROR: Public runtime directory contains no JavaScript files: ${case_three_fixture}/js/public" \
        "${last_output}"
else
    fail "case 3 rejects js/public without JavaScript (unexpected exit 0; output: ${last_output})"
fi
if [[ "${failures}" -eq "${case_three_before}" ]]; then
    pass "case 3 regression"
else
    printf 'FAIL: case 3 regression\n' >&2
fi

# --- Case 4: reject js/public when every JavaScript file is excluded. -------
case_four_fixture="${TEST_ROOT}/excluded-js-only"
case_four_dist="${TEST_ROOT}/dist-excluded-js-only"
create_common_fixture "${case_four_fixture}"
mkdir -p "${case_four_fixture}/js/public/__tests__"
printf '%s\n' 'test("excluded", () => {});' >"${case_four_fixture}/js/public/demo.test.js"
printf '%s\n' 'test("excluded", () => {});' >"${case_four_fixture}/js/public/demo.spec.js"
printf '%s\n' 'test("excluded", () => {});' >"${case_four_fixture}/js/public/__tests__/x.js"

case_four_before=$failures
run_packager "${case_four_fixture}" "${case_four_dist}"
if [[ "${last_rc}" -ne 0 ]]; then
    pass "case 4 rejects js/public with only excluded JavaScript"
    assert_output_contains \
        "case 4 reports the excluded-only js/public directory" \
        "ERROR: Public runtime directory contains no JavaScript files: ${case_four_fixture}/js/public" \
        "${last_output}"
else
    fail "case 4 rejects js/public with only excluded JavaScript (unexpected exit 0; output: ${last_output})"
fi
if [[ "${failures}" -eq "${case_four_before}" ]]; then
    pass "case 4 regression"
else
    printf 'FAIL: case 4 regression\n' >&2
fi

# --- Case 5: stop when a staged runtime file cannot be copied. --------------
case_five_fixture="${TEST_ROOT}/copy-failure"
case_five_dist="${TEST_ROOT}/dist-copy-failure"
create_common_fixture "${case_five_fixture}"
mkdir -p "${case_five_fixture}/js/public"
printf '%s\n' 'console.log("failure");' >"${case_five_fixture}/js/public/a-fail.js"
printf '%s\n' 'console.log("success");' >"${case_five_fixture}/js/public/z-good.js"

fake_bin="${TEST_ROOT}/fake-bin"
real_cp="$(command -v cp)"
mkdir -p "${fake_bin}"
cat >"${fake_bin}/cp" <<'CP'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "./a-fail.js" ]]; then
    echo "simulated cp failure for ${1}" >&2
    exit 1
fi

exec "${ACX_TEST_REAL_CP}" "$@"
CP
chmod +x "${fake_bin}/cp"

case_five_before=$failures
last_output=""
last_rc=0
last_output="$(
    PATH="${fake_bin}:${PATH}" \
    ACX_TEST_REAL_CP="${real_cp}" \
    ACX_PACKAGE_PLUGIN_DIR="${case_five_fixture}" \
    ACX_PACKAGE_DIST_DIR="${case_five_dist}" \
    bash "${PACKAGER}" --no-build 2>&1
)" || last_rc=$?
if [[ "${last_rc}" -ne 0 ]]; then
    pass "case 5 rejects a failed public runtime copy"
    assert_output_contains \
        "case 5 reports the failed copy" \
        "simulated cp failure for ./a-fail.js" \
        "${last_output}"
else
    fail "case 5 rejects a failed public runtime copy (unexpected exit 0; output: ${last_output})"
fi
if [[ "${failures}" -eq "${case_five_before}" ]]; then
    pass "case 5 regression"
else
    printf 'FAIL: case 5 regression\n' >&2
fi

if [[ "${failures}" -ne 0 ]]; then
    printf 'FAIL: package-plugin regression suite (%s failure(s))\n' "${failures}" >&2
    exit 1
fi

printf 'PASS: package-plugin regression suite\n'
