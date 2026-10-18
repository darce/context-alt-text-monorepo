#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
app_dir=$(cd "$script_dir/.." && pwd)
repo_root=$(cd "$app_dir/../.." && pwd)

declare -a module_roots=()

if [[ -n "${ACX_PLAYWRIGHT_NODE_MODULES:-}" ]]; then
  module_roots+=("${ACX_PLAYWRIGHT_NODE_MODULES}")
fi

module_roots+=("$app_dir/node_modules")

common_git_dir=$(git -C "$repo_root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [[ -n "$common_git_dir" ]]; then
  common_repo_root=$(cd "$(dirname "$common_git_dir")" && pwd)
  common_app_dir="$common_repo_root/apps/prototype-wp-alt-context"
  if [[ "$common_app_dir" != "$app_dir" ]]; then
    module_roots+=("$common_app_dir/node_modules")
  fi
fi

for module_root in "${module_roots[@]}"; do
  playwright_bin="$module_root/.bin/playwright"
  if [[ -x "$playwright_bin" ]]; then
    export NODE_PATH="$module_root${NODE_PATH:+:$NODE_PATH}"
    exec "$playwright_bin" "$@"
  fi
done

printf 'Playwright binary not found. Install dependencies in %s or set ACX_PLAYWRIGHT_NODE_MODULES.\n' "$app_dir" >&2
exit 127