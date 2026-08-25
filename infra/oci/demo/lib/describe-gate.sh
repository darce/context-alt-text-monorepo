#!/usr/bin/env bash
# Pure classifier for the demo bootstrap describe-apply step.
# Sourced by infra/oci/demo/bootstrap-wp.sh and
# infra/oci/demo/tests/test-describe-gate.sh. Keep it dependency-free
# (no jq, no arrays, no bash-4 features) so the same function runs under
# macOS bash 3.2 and the VM's bash.
#
# WHY this is an allowlist, not a denylist (do not "simplify" this):
# The live `seeded` adapter emits 8 canned fixture sentences. Publishing
# those across demo media is worse for accessibility than leaving alt
# empty: empty alt is honest; canned alt is a lie. Only adapters proven
# to produce real descriptions may RUN. Unknown, empty, seeded, and
# fail-closed stub profiles BLOCK.
#
# classify_describe_gate <adapter_profile> <total_media> <media_with_alt>
#   -> RUN | SKIP | BLOCK

# classify_describe_gate <adapter_profile> <total_media> <media_with_alt>
classify_describe_gate() {
    local profile="$1"
    local total="${2:-}"
    local with_alt="${3:-}"

    case "$profile" in
        florence_small|gpu_qwen30b|gpu_qwen30b_ensemble) ;;
        *) echo BLOCK; return ;;
    esac

    case "$total" in
        *[!0-9]*|'') echo BLOCK; return ;;
    esac
    case "$with_alt" in
        *[!0-9]*|'') echo BLOCK; return ;;
    esac

    if [ "$with_alt" -gt "$total" ]; then
        echo BLOCK
        return
    fi

    if [ "$total" -eq 0 ]; then
        echo SKIP
        return
    fi

    if [ "$with_alt" -eq "$total" ]; then
        echo SKIP
        return
    fi

    echo RUN
}
