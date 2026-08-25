#!/usr/bin/env bash
# Canonical fixture-caption normalizer + denylist.
#
# Consumed by infra/oci/demo/lib/describe-gate.sh (copy, VM-self-contained)
# and available for scripts/deploy/lib/smoke-gate.sh to source or concatenate.
# Both ship paths are single-file (SCP describe-gate.sh / cat smoke-gate.sh)
# and cannot import Python, so this file stays dependency-free (no jq, no
# arrays, no bash-4 features).
#
# Matching semantics (DEMOLIVE-6 / XLANE-01):
#   lowercase via tr '[:upper:]' '[:lower:]'
#   whitespace runs collapsed with tr -s '[:space:]' ' '
#   trailing .!? stripped in a loop
#   denylist arms are lowercase with no trailing punctuation
# Empty-sample policy is NOT here: smoke fails closed, describe returns
# UNKNOWN. Callers wrap fixture_sample_is_denied with that policy.

# normalize_fixture_sample <text> -> normalized text on stdout
normalize_fixture_sample() {
    local sample="$1"
    sample=$(printf '%s' "$sample" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ')
    while :
    do
        case "$sample" in
            *[.!?]) sample=${sample%?} ;;
            *) break ;;
        esac
    done
    printf '%s' "$sample"
}

# fixture_sample_is_denied <text>
#   return 0 if the normalized sample contains a seeded fixture caption.
#   return 1 otherwise (including empty / whitespace-only after normalize).
fixture_sample_is_denied() {
    local sample
    sample=$(normalize_fixture_sample "$1")
    case "$sample" in
        *"a person standing outdoors near greenery"*) return 0 ;;
        *"a plate of food on a wooden table"*) return 0 ;;
        *"a scenic landscape with mountains under a clear sky"*) return 0 ;;
        *"a close-up of a small object on a neutral background"*) return 0 ;;
        *"a printed document with several lines of text"*) return 0 ;;
        *"two people seated indoors in conversation"*) return 0 ;;
        *"a building exterior seen from the street"*) return 0 ;;
        *"a pet animal resting on a soft surface"*) return 0 ;;
    esac
    return 1
}
