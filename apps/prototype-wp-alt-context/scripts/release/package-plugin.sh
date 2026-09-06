#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="${ACX_PACKAGE_PLUGIN_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
REPO_ROOT="${ACX_PACKAGE_REPO_ROOT:-$(cd "${PLUGIN_DIR}/../.." && pwd)}"
PLUGIN_SLUG="alt-context"
PLUGIN_FILE="${PLUGIN_DIR}/alt-context.php"
PACKAGE_JSON_FILE="${PLUGIN_DIR}/package.json"
DIST_DIR="${ACX_PACKAGE_DIST_DIR:-${REPO_ROOT}/dist}"

show_usage() {
    cat <<'USAGE'
Usage: bash scripts/release/package-plugin.sh [--no-build] [--help]

Options:
  --no-build  Skip npm/composer build steps and package pre-built artifacts only.
  --help      Show this usage message.

Runtime files:
  js/public   If present, stage its runtime files, excluding __tests__/,
              *.d.ts, *.test.*, and *.spec.*; require at least one *.js file.
USAGE
}

NO_BUILD=0

while (($# > 0)); do
    case "$1" in
        --no-build)
            NO_BUILD=1
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            show_usage
            exit 1
            ;;
    esac
done

extract_plugin_version() {
    local version=""

    version="$(sed -n 's/^ \* Version:[[:space:]]*//p' "${PLUGIN_FILE}" | head -n 1 | tr -d '\r')"

    if [[ -z "${version}" ]]; then
        echo "ERROR: Could not extract plugin version from ${PLUGIN_FILE}" >&2
        exit 1
    fi

    echo "${version}"
}

extract_package_json_version() {
    local package_version=""

    if [[ ! -f "${PACKAGE_JSON_FILE}" ]]; then
        echo "ERROR: package.json not found at ${PACKAGE_JSON_FILE}" >&2
        exit 1
    fi

    ensure_command node

    package_version="$(node -e "
        const fs = require('fs');
        const filePath = process.argv[1];
        const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
        const version = typeof parsed.version === 'string' ? parsed.version.trim() : '';
        process.stdout.write(version);
    " "${PACKAGE_JSON_FILE}")"

    if [[ -z "${package_version}" ]]; then
        echo "ERROR: Could not extract version from ${PACKAGE_JSON_FILE}" >&2
        exit 1
    fi

    echo "${package_version}"
}

validate_version_consistency() {
    local plugin_version="$1"
    local package_version="$2"

    if [[ "${plugin_version}" != "${package_version}" ]]; then
        echo "ERROR: Version mismatch detected." >&2
        echo "  alt-context.php Version: ${plugin_version}" >&2
        echo "  package.json version:   ${package_version}" >&2
        exit 1
    fi
}

ensure_command() {
    local command_name="$1"
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "ERROR: Required command '${command_name}' is not installed." >&2
        exit 1
    fi
}

ensure_runtime_inputs() {
    if [[ ! -d "${PLUGIN_DIR}/public/assets/dist" ]]; then
        echo "ERROR: Missing build output at ${PLUGIN_DIR}/public/assets/dist." >&2
        exit 1
    fi

    if [[ -z "$(find "${PLUGIN_DIR}/public/assets/dist" -maxdepth 5 -type f | head -n 1)" ]]; then
        echo "ERROR: Build output directory is empty: ${PLUGIN_DIR}/public/assets/dist." >&2
        exit 1
    fi
}

copy_runtime_files_to_staging() {
    local staging_plugin_dir="$1"

    mkdir -p "${staging_plugin_dir}/public/assets"

    cp "${PLUGIN_FILE}" "${staging_plugin_dir}/alt-context.php"
    cp -R "${PLUGIN_DIR}/src" "${staging_plugin_dir}/src"
    cp -R "${PLUGIN_DIR}/public/assets/dist" "${staging_plugin_dir}/public/assets/dist"
    cp "${PLUGIN_DIR}/composer.json" "${staging_plugin_dir}/composer.json"

    local public_runtime_dir="${PLUGIN_DIR}/js/public"
    if [[ -d "${public_runtime_dir}" ]]; then
        if [[ -z "$(find "${public_runtime_dir}" \
            \( -type d -name '__tests__' -prune \) -o \
            \( -type f -name '*.js' \
                ! -name '*.test.*' \
                ! -name '*.spec.*' \
                -print \
            \) | head -n 1)" ]]; then
            echo "ERROR: Public runtime directory contains no JavaScript files: ${public_runtime_dir}." >&2
            exit 1
        fi

        mkdir -p "${staging_plugin_dir}/js/public"
        (
            cd "${public_runtime_dir}"
            find . \
                \( -type d -name '__tests__' -prune \) -o \
                \( -type f \
                    ! -name '*.d.ts' \
                    ! -name '*.test.*' \
                    ! -name '*.spec.*' \
                    -exec sh -c '
                        set -eu
                        staging_dir="$1"
                        shift
                        for source_file do
                            destination="${staging_dir}/js/public/${source_file#./}"
                            mkdir -p "$(dirname "${destination}")"
                            cp "${source_file}" "${destination}"
                        done
                    ' sh "${staging_plugin_dir}" {} + \)
        )
    fi

    if [[ -f "${PLUGIN_DIR}/composer.lock" ]]; then
        cp "${PLUGIN_DIR}/composer.lock" "${staging_plugin_dir}/composer.lock"
    fi

    if [[ -d "${PLUGIN_DIR}/vendor" ]]; then
        cp -R "${PLUGIN_DIR}/vendor" "${staging_plugin_dir}/vendor"
    fi
}

sanitize_staging_tree() {
    local staging_plugin_dir="$1"
    find "${staging_plugin_dir}" -name ".DS_Store" -type f -delete
}

validate_staging_contents() {
    local staging_plugin_dir="$1"

    if [[ ! -f "${staging_plugin_dir}/vendor/autoload.php" ]]; then
        echo "ERROR: Missing vendor/autoload.php in staging directory." >&2
        exit 1
    fi

    local forbidden_paths=(
        "node_modules"
        "tests"
        ".env"
        ".env.local"
        ".env.development"
        ".env.production"
    )

    for forbidden in "${forbidden_paths[@]}"; do
        if [[ -e "${staging_plugin_dir}/${forbidden}" ]]; then
            echo "ERROR: Forbidden path found in package staging: ${forbidden}" >&2
            exit 1
        fi
    done
}

validate_no_dev_dependencies() {
    local staging_plugin_dir="$1"
    local dev_markers=(
        "vendor/phpunit"
        "vendor/squizlabs/php_codesniffer"
        "vendor/wp-coding-standards/wpcs"
    )

    for marker in "${dev_markers[@]}"; do
        if [[ -e "${staging_plugin_dir}/${marker}" ]]; then
            echo "ERROR: Dev dependency marker found in package: ${marker}" >&2
            echo "Run without --no-build or provide pre-built production vendor/." >&2
            exit 1
        fi
    done
}

checksum_file() {
    local target_file="$1"
    local output_file="$2"

    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "${target_file}" >"${output_file}"
        return
    fi

    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "${target_file}" >"${output_file}"
        return
    fi

    echo "ERROR: Neither sha256sum nor shasum is available for checksum generation." >&2
    exit 1
}

if [[ ! -f "${PLUGIN_FILE}" ]]; then
    echo "ERROR: Plugin file not found: ${PLUGIN_FILE}" >&2
    exit 1
fi

VERSION="$(extract_plugin_version)"
PACKAGE_VERSION="$(extract_package_json_version)"
validate_version_consistency "${VERSION}" "${PACKAGE_VERSION}"

# Reuse the validated plugin version as Composer's root version so `composer
# install` does not warn "could not detect the root package version" and default
# to 1.0.0. Derived from the single source of truth (alt-context.php == package.json)
# rather than hardcoding `version` in composer.json (which would add a third sync
# point). Exported so the staging-dir composer subshell inherits it.
export COMPOSER_ROOT_VERSION="${VERSION}"

ZIP_NAME="${PLUGIN_SLUG}-${VERSION}.zip"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"
CHECKSUM_PATH="${ZIP_PATH}.sha256"

STAGING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/acx-package.XXXXXX")"
STAGING_PLUGIN_DIR="${STAGING_ROOT}/${PLUGIN_SLUG}"
trap 'rm -rf "${STAGING_ROOT}"' EXIT

if [[ "${NO_BUILD}" -eq 0 ]]; then
    echo "Running production build steps..."
    (
        cd "${PLUGIN_DIR}"
        npm run build
    )
fi

ensure_runtime_inputs
copy_runtime_files_to_staging "${STAGING_PLUGIN_DIR}"
sanitize_staging_tree "${STAGING_PLUGIN_DIR}"

if [[ "${NO_BUILD}" -eq 0 ]]; then
    echo "Installing production-only Composer dependencies in staging..."
    (
        cd "${STAGING_PLUGIN_DIR}"
        composer install --no-dev --optimize-autoloader --no-interaction --no-progress
    )
fi

validate_staging_contents "${STAGING_PLUGIN_DIR}"
validate_no_dev_dependencies "${STAGING_PLUGIN_DIR}"

ensure_command zip

mkdir -p "${DIST_DIR}"
rm -f "${ZIP_PATH}" "${CHECKSUM_PATH}"

echo "Creating ${ZIP_PATH} ..."
(
    cd "${STAGING_ROOT}"
    zip -X -r "${ZIP_PATH}" "${PLUGIN_SLUG}" >/dev/null
)

checksum_file "${ZIP_PATH}" "${CHECKSUM_PATH}"

echo "Package created:"
echo "  ZIP: ${ZIP_PATH}"
echo "  SHA256: ${CHECKSUM_PATH}"
