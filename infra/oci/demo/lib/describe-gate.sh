#!/usr/bin/env bash
# Pure classifier for the demo bootstrap describe-apply step.
# Sourced by infra/oci/demo/bootstrap-wp.sh and
# infra/oci/demo/tests/test-describe-gate.sh. Keep it dependency-free
# (no jq, no curl, no arrays, no bash-4 features) so the same function runs
# under macOS bash 3.2 and the VM's bash.
#
# WHY this is an allowlist, not a denylist (do not "simplify" this):
# The live `seeded` adapter emits 8 canned fixture sentences. Publishing
# those across demo media is worse for accessibility than leaving alt
# empty: empty alt is honest; canned alt is a lie. Only adapters proven
# to produce real descriptions may RUN. Unknown, empty, seeded, and
# fail-closed stub profiles BLOCK.
#
# classify_describe_gate <adapter_profile> <total_media> <media_with_alt> [provenance]
#   -> RUN | RUN_FORCE | SKIP | BLOCK
# provenance is PASS|FAIL|UNKNOWN. Omitted/empty/garbage is UNKNOWN.
#
# Shared allowlist: one space-delimited string, exact-word predicate.
# Callers (bootstrap-wp.sh) read the same source so BLOCK messages can
# distinguish "untrusted adapter" from "trusted adapter, unmeasurable corpus".

ACX_TRUSTED_DESCRIBE_PROFILES="florence_small gpu_qwen30b gpu_qwen30b_ensemble"

# is_trusted_describe_profile <profile>
#   exit 0 if <profile> is an exact allowlist member, else 1 (not echo).
# WHY word-split + [ = ], not case *"$p"*: "florence" and "small" are
# substrings of florence_small and must not count as trusted.
is_trusted_describe_profile() {
    local profile="$1"
    local candidate
    [ -n "$profile" ] || return 1
    for candidate in $ACX_TRUSTED_DESCRIBE_PROFILES; do
        [ "$candidate" = "$profile" ] && return 0
    done
    return 1
}

# classify_describe_block_cause <profile>
#   -> PROBE_FAILED | UNTRUSTED_PROFILE | TRUSTED
# WHY: is_trusted_describe_profile returns 1 for both an empty profile and an
# unrecognized one, so a caller that branches on it alone reports a failed
# /health/detailed probe as a bad producer profile and sends the operator to
# fix the wrong system. Empty (or whitespace-only) means the probe never
# yielded a value; a non-empty miss means the producer really is untrusted.
classify_describe_block_cause() {
    local profile="$1"
    local trimmed
    # Word-splitting collapses whitespace-only input to the empty string.
    # shellcheck disable=SC2086
    set -- $profile
    trimmed="${1:-}"
    if [ -z "$trimmed" ]; then
        echo PROBE_FAILED
        return
    fi
    if is_trusted_describe_profile "$trimmed"; then
        echo TRUSTED
        return
    fi
    echo UNTRUSTED_PROFILE
}

# php_define_value <constant_name> <wordpress_config_extra>
# Extracts define('NAME','value') / define("NAME","value") from the already-
# loaded WORDPRESS_CONFIG_EXTRA string. Reuses secrets/.env material the
# bootstrap already parses; does not invent a new secret name.
php_define_value() {
    local name="$1"
    local src="$2"
    local value
    [ -n "$name" ] || { echo ""; return; }
    value=$(printf '%s' "$src" | tr ';' '\n' | sed -n "s/.*define(['\"]${name}['\"],['\"]\\([^'\"]*\\)['\"].*/\\1/p" | sed -n '1p')
    printf '%s' "$value"
}

# extract_probed_description_adapter <http_code> <body>
# Returns the top-level JSON string field description_adapter when HTTP is 2xx
# and the body is parseable. Empty on probe failure, non-2xx, missing field,
# unparseable body, nested-only key, non-string value, or missing python3.
# NEVER invents a fallback profile. python3 is required; fail closed if absent.
extract_probed_description_adapter() {
    local code="$1"
    local body="$2"
    local value=""
    case "$code" in
        2[0-9][0-9]) ;;
        *) echo ""; return ;;
    esac
    if ! command -v python3 >/dev/null 2>&1; then
        echo ""
        return
    fi
    value=$(printf '%s' "$body" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
if not isinstance(data, dict):
    raise SystemExit(0)
value = data.get("description_adapter")
if isinstance(value, str):
    sys.stdout.write(value)
' 2>/dev/null) || value=""
    printf '%s' "$value"
}

# classify_claimed_adapter_matches_probe <probed_adapter> <claimed_adapters_blob>
#   -> PASS | FAIL | UNKNOWN
# Cross-check the WP media payload's claimed adapter names against the
# independently probed description-service /health/detailed adapter.
# claimed_adapters_blob is the whitespace-separated list of adapter names
# the WP media payload claims (same shape classify_alt_identity consumes).
#
# Semantics (do not weaken):
# 1. probed_adapter empty (probe unavailable / no python3 / non-JSON) ->
#    UNKNOWN. Callers decide policy; do not guess. UNKNOWN is NOT a pass.
# 2. claimed blob empty (nothing claimed yet; coverage gate owns that) ->
#    UNKNOWN.
# 3. any claimed token that is not byte-identical to probed_adapter -> FAIL.
#    Live failure mode: production serves `seeded` while postmeta claims
#    `florence_small`.
# 4. every claimed token equals probed_adapter -> PASS.
# 5. a claimed token containing whitespace, a glob metacharacter (* ? [)
#    or that is otherwise unsplittable -> FAIL, not UNKNOWN.
# Word-split runs under set -f so a claimed `*` cannot glob against cwd.
# Identity check is byte-identical, not case-folded.
classify_claimed_adapter_matches_probe() {
    local probed_adapter="${1:-}"
    local claimed_adapters_blob="${2:-}"
    local out

    if [ -z "$probed_adapter" ]; then
        echo UNKNOWN
        return
    fi
    if [ -z "$(printf '%s' "$claimed_adapters_blob" | tr -d '[:space:]')" ]; then
        echo UNKNOWN
        return
    fi

    out=$(
        set -f
        for adapter in $claimed_adapters_blob; do
            # Leading `(` on the pattern: bash 3.2's command-substitution
            # parser miscounts the `)` of a case pattern nested inside `$( )`
            # and dies with "syntax error near unexpected token `;;'". The VM
            # runs bash 5 and parses it fine, so this only ever failed on a
            # macOS laptop -- which is where the gate's own tests run.
            case "$adapter" in
                (*[[:space:]]*|*'*'*|*'?'*|*'['*)
                    echo FAIL
                    exit 0
                    ;;
            esac
            if [ "$adapter" != "$probed_adapter" ]; then
                echo FAIL
                exit 0
            fi
        done
        echo PASS
    )
    echo "$out"
}

# classify_describe_provenance <sample_text> -> PASS|FAIL|UNKNOWN
# UNKNOWN when nothing was measured. FAIL when any canned seeded fixture
# caption appears in the sample. PASS otherwise.
#
# Matching semantics MUST stay identical to classify_alt_provenance after
# DEMOLIVE-9's alphanumeric-skeleton + content-token AND matcher (R2-01):
# lowercase, map non-alnum bytes to space, collapse spaces, then require
# every content token of a denylist arm. The matcher lives in
# scripts/deploy/lib/fixture-denylist.sh; this file is SCP'd standalone
# to the VM so the same functions are inlined here. A corpus test binds
# the two copies. Do not revert to substring match — punctuation or
# Unicode whitespace inside a fixture caption would SKIP describe while
# smoke FAILs, with no heal path (INT-10 / R1-04 relocated).

# normalize_fixture_sample / _fixture_tokens_all_present /
# fixture_sample_is_denied
# Keep byte-equivalent to scripts/deploy/lib/fixture-denylist.sh (test-bound).
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

classify_describe_provenance() {
    local sample="$1"
    if [ -z "$sample" ]; then
        echo UNKNOWN
        return
    fi
    if fixture_sample_is_denied "$sample"; then
        echo FAIL
        return
    fi
    echo PASS
}

# classify_describe_gate <adapter_profile> <total_media> <media_with_alt> [provenance]
classify_describe_gate() {
    local profile="$1"
    local total="${2:-}"
    local with_alt="${3:-}"
    local provenance="${4:-}"

    if ! is_trusted_describe_profile "$profile"; then
        echo BLOCK
        return
    fi

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
        case "$provenance" in
            PASS) echo SKIP; return ;;
            FAIL) echo RUN_FORCE; return ;;
            *) echo BLOCK; return ;;
        esac
    fi

    echo RUN
}
