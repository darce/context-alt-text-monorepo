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
# classify_describe_gate <adapter_profile> <total_media> <media_with_alt> [provenance] [readiness]
#   -> RUN | RUN_FORCE | SKIP | BLOCK
# provenance is PASS|FAIL|UNKNOWN. Omitted/empty/garbage is UNKNOWN.
# readiness is the compact value emitted by extract_probed_description_adapter;
# when omitted, the most recent extraction in this shell is used.
#
# Shared allowlist: one space-delimited string, exact-word predicate.
# Callers (bootstrap-wp.sh) read the same source so BLOCK messages can
# distinguish "untrusted adapter" from "trusted adapter, unmeasurable corpus".

ACX_TRUSTED_DESCRIBE_PROFILES="florence_small gpu_qwen30b gpu_qwen30b_ensemble"

# These are every configuration-fault member of AdapterReadinessReason in
# apps/prototype-description-service/api/main.py. The intentionally omitted
# endpoint_resolution_pending member is a warmth-independent cold-GPU state.
ACX_DESCRIBE_CONFIGURATION_FAULT_REASONS="profile_unavailable vlm_dependencies_missing endpoint_unconfigured endpoint_invalid_url endpoint_not_allowlisted endpoint_not_private"

# bootstrap-wp.sh keeps the profile-only stdout contract for the extractor. The
# readiness fields travel alongside it in a per-shell file so the unchanged
# caller can still pass ADAPTER_PROFILE to the gate. $$ is stable across bash
# command substitutions, while distinct bootstrap processes get distinct files.
_DESCRIBE_GATE_READINESS_FILE="${TMPDIR:-/tmp}/acx-describe-gate-readiness-$$"

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
    # Runs under `set -f` in a subshell, same guard as
    # classify_claimed_adapter_matches_probe: without it the split is also a
    # pathname expansion, so a profile of `*` would match cwd and be reported
    # TRUSTED while the gate itself BLOCKs it.
    trimmed=$(
        set -f
        # shellcheck disable=SC2086
        set -- $profile
        printf '%s' "${1:-}"
    )
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
# Returns description_adapter.profile from the top-level JSON readiness object
# when HTTP is 2xx, the body is parseable, and description_adapter matches the
# full descriptionAdapterReadiness shape. Empty on probe failure, non-2xx,
# missing or invalid shape fields (including non-empty model identity strings
# for trusted profiles), unparseable body,
# nested-only key, non-object value, untrusted model identity, or missing
# python3.
# NEVER invents a fallback profile. python3 is required; fail closed if absent.
extract_probed_description_adapter() {
    local code="$1"
    local body="$2"
    local value=""
    local profile=""
    local readiness=""
    rm -f "$_DESCRIBE_GATE_READINESS_FILE"
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
if data.get("status") not in {"ok", "degraded"}:
    raise SystemExit(0)
value = data.get("description_adapter")
if not isinstance(value, dict):
    raise SystemExit(0)

required_keys = {
    "profile",
    "kind",
    "endpoint_configured",
    "endpoint_allowlisted",
    "endpoint_private",
    "checked_at",
    "fresh",
    "usable",
    "reason",
    "model_id",
    "model_version",
}
if set(value) != required_keys:
    raise SystemExit(0)

profile = value.get("profile")
if not isinstance(profile, str) or not profile:
    raise SystemExit(0)
if value["kind"] not in {"seeded", "local_cpu", "gpu", "hosted_provider"}:
    raise SystemExit(0)
for key in ("endpoint_configured", "endpoint_allowlisted", "fresh", "usable"):
    if type(value[key]) is not bool:
        raise SystemExit(0)
if value["endpoint_private"] is not None and type(value["endpoint_private"]) is not bool:
    raise SystemExit(0)
checked_at = value["checked_at"]
if checked_at is not None and (
    isinstance(checked_at, bool)
    or not isinstance(checked_at, (int, float))
    or not checked_at >= 0
):
    raise SystemExit(0)
if value["reason"] is not None and not isinstance(value["reason"], str):
    raise SystemExit(0)
for key in ("model_id", "model_version"):
    if value[key] is not None and (not isinstance(value[key], str) or not value[key]):
        raise SystemExit(0)
trusted_profiles = set(sys.argv[1].split()) if len(sys.argv) > 1 else set()
if profile in trusted_profiles and any(
    not isinstance(value[key], str) or not value[key]
    for key in ("model_id", "model_version")
):
    raise SystemExit(0)
# Keep the profile on stdout for bootstrap-wp.sh. The readiness record is one
# structured value; shell only consumes its already-validated scalar fields.
endpoint_private = "null" if value["endpoint_private"] is None else str(value["endpoint_private"]).lower()
reason = "null" if value["reason"] is None else value["reason"]
fields = [
    profile,
    value["kind"],
    str(value["endpoint_configured"]).lower(),
    str(value["endpoint_allowlisted"]).lower(),
    endpoint_private,
    str(value["fresh"]).lower(),
    str(value["usable"]).lower(),
    reason,
]
if any(
    any(separator in field or control in field for separator in ("|",) for control in ("\r", "\n"))
    for field in fields
):
    raise SystemExit(0)
sys.stdout.write(profile + "\n" + "|".join(fields))
' "$ACX_TRUSTED_DESCRIBE_PROFILES" 2>/dev/null) || value=""
    [ -n "$value" ] || return
    case "$value" in
        *$'\n'*) ;;
        *) return ;;
    esac
    profile="${value%%$'\n'*}"
    readiness="${value#*$'\n'}"
    [ -n "$profile" ] || return
    [ -n "$readiness" ] || return
    printf '%s' "$readiness" >"$_DESCRIBE_GATE_READINESS_FILE"
    printf '%s' "$profile"
}

# extract_probed_description_adapter_readiness <expected_profile>
# Returns the structured readiness captured by the most recent extractor in
# this shell. The profile field prevents stale evidence from being paired with
# a different adapter; no JSON is reparsed here.
extract_probed_description_adapter_readiness() {
    local expected_profile="${1:-}"
    local readiness=""
    local stored_profile=""
    [ -r "$_DESCRIBE_GATE_READINESS_FILE" ] || return 1
    readiness=$(<"$_DESCRIBE_GATE_READINESS_FILE")
    [ -n "$readiness" ] || return 1
    case "$readiness" in
        *'|'*) ;;
        *) return 1 ;;
    esac
    stored_profile="${readiness%%|*}"
    [ -n "$expected_profile" ] && [ "$stored_profile" = "$expected_profile" ] || return 1
    printf '%s' "$readiness"
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

# _describe_profile_kind <profile> -> kind
# Trusted profiles are the only profiles that reach this mapping. Keeping the
# mapping here makes a claimed profile with a mismatched producer kind block.
_describe_profile_kind() {
    case "$1" in
        florence_small) printf '%s' local_cpu ;;
        gpu_qwen30b|gpu_qwen30b_ensemble) printf '%s' gpu ;;
        *) return 1 ;;
    esac
}

# _describe_readiness_allows_gate <profile> <readiness>
# The gate deliberately ignores usable/fresh: those fields describe GPU
# warmth, and a cold but correctly configured GPU must be admitted so the
# burst can warm it. It checks only profile-independent configuration evidence.
_describe_readiness_allows_gate() {
    local profile="$1"
    local readiness="$2"
    local readiness_profile=""
    local kind=""
    local endpoint_configured=""
    local endpoint_allowlisted=""
    local endpoint_private=""
    local fresh=""
    local usable=""
    local reason=""
    local extra=""
    local expected_kind=""
    local fault_reason=""

    [ -n "$readiness" ] || return 1
    case "$readiness" in
        *$'\n'*|*$'\r'*) return 1 ;;
    esac
    IFS='|' read -r readiness_profile kind endpoint_configured endpoint_allowlisted endpoint_private fresh usable reason extra <<EOF
$readiness
EOF
    [ -z "$extra" ] || return 1
    [ "$readiness_profile" = "$profile" ] || return 1
    expected_kind=$(_describe_profile_kind "$profile") || return 1
    [ "$kind" = "$expected_kind" ] || return 1
    case "$endpoint_configured" in true|false) ;; *) return 1 ;; esac
    case "$endpoint_allowlisted" in true|false) ;; *) return 1 ;; esac
    case "$endpoint_private" in true|null) ;; false) return 1 ;; *) return 1 ;; esac
    case "$fresh" in true|false) ;; *) return 1 ;; esac
    case "$usable" in true|false) ;; *) return 1 ;; esac

    # AdapterReadinessReason's only non-fault terminal state is pending. An
    # unknown reason also blocks so adding a new producer fault cannot silently
    # widen this release gate.
    if [ "$reason" != "null" ] && [ "$reason" != "endpoint_resolution_pending" ]; then
        for fault_reason in $ACX_DESCRIBE_CONFIGURATION_FAULT_REASONS; do
            [ "$reason" = "$fault_reason" ] && return 1
        done
        return 1
    fi

    if [ "$kind" = "gpu" ]; then
        [ "$endpoint_configured" = true ] || return 1
        [ "$endpoint_allowlisted" = true ] || return 1
    fi
    return 0
}

# classify_describe_gate <adapter_profile> <total_media> <media_with_alt> [provenance] [readiness]
classify_describe_gate() {
    local profile="${1:-}"
    local total="${2:-}"
    local with_alt="${3:-}"
    local provenance="${4:-}"
    local readiness="${5:-}"

    # Accept the structured value as the first argument too, so callers that
    # already have one readiness value need not split it into profile + fields.
    if [ -z "$readiness" ] && [[ "$profile" == *'|'* ]]; then
        readiness="$profile"
        profile="${profile%%|*}"
    fi
    # Likewise tolerate the additive readiness argument in position four;
    # bootstrap's position-four provenance contract remains unchanged.
    if [ -z "$readiness" ] && [[ "$provenance" == *'|'* ]]; then
        readiness="$provenance"
        provenance=""
    fi

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
            FAIL) ;;
            *) echo BLOCK; return ;;
        esac
    fi

    if [ -z "$readiness" ]; then
        readiness="$(extract_probed_description_adapter_readiness "$profile")" || readiness=""
    fi
    if ! _describe_readiness_allows_gate "$profile" "$readiness"; then
        echo BLOCK
        return
    fi

    if [ "$with_alt" -eq "$total" ]; then
        echo RUN_FORCE
        return
    fi

    echo RUN
}
