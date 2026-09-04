#!/usr/bin/env bash
# Shared description-adapter allowlist for deploy-time gates.
# Keep this file data-only apart from the exact-member predicate so callers can
# source it before reading any secrets.

ACX_TRUSTED_DESCRIBE_PROFILES="florence_small gpu_qwen30b gpu_qwen30b_ensemble"

acx_is_trusted_describe_profile() {
    local profile="$1"
    local candidate
    [ -n "$profile" ] || return 1
    for candidate in $ACX_TRUSTED_DESCRIBE_PROFILES; do
        [ "$candidate" = "$profile" ] && return 0
    done
    return 1
}
