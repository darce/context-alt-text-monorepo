#!/usr/bin/env bash
# Repository-side description-adapter contract used by GPU env preflight.
# infra/oci/demo/lib/describe-gate.sh must remain VM-self-contained because it
# is the artifact sync-demo ships. A runtime parity test binds that staged copy
# to this contract, including exact-member behavior, before either can deploy.

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
