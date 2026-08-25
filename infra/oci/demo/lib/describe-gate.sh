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
# or unparseable body. NEVER invents a fallback profile.
extract_probed_description_adapter() {
    local code="$1"
    local body="$2"
    local value=""
    case "$code" in
        2[0-9][0-9]) ;;
        *) echo ""; return ;;
    esac
    body=$(printf '%s' "$body" | tr '\n' ' ')
    value=$(printf '%s' "$body" | sed -n 's/.*"description_adapter"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | sed -n '1p')
    printf '%s' "$value"
}

# classify_describe_provenance <sample_text> -> PASS|FAIL|UNKNOWN
# UNKNOWN when nothing was measured. FAIL when any canned seeded fixture
# caption appears in the sample. PASS otherwise.
classify_describe_provenance() {
    local sample="$1"
    if [ -z "$sample" ]; then
        echo UNKNOWN
        return
    fi
    case "$sample" in
        *"A person standing outdoors near greenery."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"A plate of food on a wooden table."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"A scenic landscape with mountains under a clear sky."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"A close-up of a small object on a neutral background."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"A printed document with several lines of text."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"Two people seated indoors in conversation."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"A building exterior seen from the street."*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"A pet animal resting on a soft surface."*) echo FAIL; return ;;
    esac
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
