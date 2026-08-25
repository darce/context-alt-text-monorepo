#!/usr/bin/env bash
# Canonical fixture-caption normalizer + denylist.
#
# Consumed by infra/oci/demo/lib/describe-gate.sh (copy, VM-self-contained)
# and available for scripts/deploy/lib/smoke-gate.sh to source or concatenate.
# Both ship paths are single-file (SCP describe-gate.sh / cat smoke-gate.sh)
# and cannot import Python, so this file stays dependency-free (no jq, no
# arrays, no bash-4 features).
#
# Matching semantics (DEMOLIVE-9 / R2-01):
#   lowercase via tr '[:upper:]' '[:lower:]'
#   alphanumeric skeleton via LC_ALL=C tr -c 'a-z0-9' ' '
#   whitespace runs collapsed with tr -s ' '
#   leading/trailing space stripped
#   denylist arms are content-token AND sets (articles/prepositions dropped)
# Empty-sample policy is NOT here: smoke fails closed, describe returns
# UNKNOWN. Callers wrap fixture_sample_is_denied with that policy.

# normalize_fixture_sample <text> -> normalized text on stdout
normalize_fixture_sample() {
    local sample="$1"
    sample=$(printf '%s' "$sample" | tr '[:upper:]' '[:lower:]' | LC_ALL=C tr -c 'a-z0-9' ' ' | tr -s ' ')
    sample=${sample# }
    sample=${sample% }
    printf '%s' "$sample"
}

# _fixture_tokens_all_present <needles> <haystack>
#   return 0 if every whitespace-split needle token is a whole word in haystack.
_fixture_tokens_all_present() {
    local needles="$1" haystack=" $2 "
    local tok
    for tok in $needles
    do
        case "$haystack" in
            *" $tok "*) ;;
            *) return 1 ;;
        esac
    done
    return 0
}

# fixture_sample_is_denied <text>
#   return 0 if the normalized sample contains every content token of a
#   seeded fixture caption. return 1 otherwise (including empty /
#   whitespace-only after normalize).
fixture_sample_is_denied() {
    local sample
    sample=$(normalize_fixture_sample "$1")
    # Homoglyphs inside a content word (e.g. Cyrillic "е" in "pеrson") still
    # evade Gate B; Gate A (trusted adapter identity) is the compensating control.
    if _fixture_tokens_all_present "person standing outdoors greenery" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "plate food wooden table" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "scenic landscape mountains clear sky" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "close up small object neutral background" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "printed document several lines text" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "two people seated indoors conversation" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "building exterior seen street" "$sample"; then return 0; fi
    if _fixture_tokens_all_present "pet animal resting soft surface" "$sample"; then return 0; fi
    return 1
}
