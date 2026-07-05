#!/usr/bin/env bash
# E15-29 S2 build hygiene: the plugin packager must not emit Composer's
# "could not detect the root package ... version" warning. The packager sets
# COMPOSER_ROOT_VERSION from the validated plugin version (single source of truth).
#
# Runs the real packager (npm build + composer install) and asserts the warning
# is absent. Run from the repo root.
#
# Usage: bash apps/prototype-wp-alt-context/scripts/release/verify-no-composer-root-version-warning.sh
set -euo pipefail

PLUGIN_DIR="${PLUGIN_DIR:-apps/prototype-wp-alt-context}"

out="$(cd "$PLUGIN_DIR" && bash scripts/release/package-plugin.sh 2>&1)"

if printf '%s\n' "$out" | grep -qi 'could not detect the root package'; then
  echo "FAIL: Composer root-package version warning still present:" >&2
  printf '%s\n' "$out" | grep -i 'could not detect the root package' >&2
  exit 1
fi

echo "verify-no-composer-root-version-warning: OK (no Composer root-package version warning)"
