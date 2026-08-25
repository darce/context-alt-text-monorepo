#!/usr/bin/env bash
# Pure classification logic for the sync-demo.sh post-deploy vhost smoke.
# Sourced locally by scripts/deploy/tests/test-smoke-gate.sh and shipped to the
# VM inline by sync-demo.sh — keep it dependency-free (no curl, no arrays) so
# the same functions run under macOS bash 3.2 and the VM's bash.
#
# Gate semantics ("the deploy owns the edge and the demo stack, not backend
# health"):
#   api.* /health   000 after retries            -> FAIL (edge/TLS broken)
#                   200                          -> PASS
#                   other + was 200 pre-promote  -> FAIL (deploy-caused regression)
#                   other + was already unhealthy-> WARN (backend outage, out of scope)
#   demo /          final code (redirects followed) must be 2xx AND the final
#                   URL must not be a WP installer/setup page — a wiped DB
#                   302->install.php lands on a 200 installer, which is a
#                   broken demo, not a healthy one.
#   demo media      alt coverage below min_pct (inclusive boundary;
#                   DEMO_ALT_MIN_COVERAGE_PCT default 95; operators may raise
#                   this bar) including 0/N empty alt and 0/0 no media -> FAIL.
#                   Empty, non-numeric, or impossible (with_alt > total) counts
#                   fail closed. min_pct below the fixed floor of 50 also FAILs
#                   — the floor is a safety constant, not an environment knob,
#                   so DEMO_ALT_MIN_COVERAGE_PCT=0 cannot certify an empty-alt
#                   library. Coverage numerator counts only usable alt (see
#                   classify_alt_text_usable), not any non-empty JSON string.
#                   Coverage numerator/denominator come from the same page;
#                   header_total vs body_total disagreement FAILs rather than
#                   measuring a paged subset. Published alt matching any
#                   seeded fixture caption (after lowercase / whitespace
#                   collapse / trailing .!? strip) -> FAIL (the canned pool is
#                   not accessibility content).

# classify_api_probe <post_code> <pre_code> -> PASS|WARN|FAIL
classify_api_probe() {
    local post="$1" pre="${2:-}"
    if [ "$post" = "000" ]; then
        echo FAIL
    elif [ "$post" = "200" ]; then
        echo PASS
    elif [ "$pre" = "200" ]; then
        echo FAIL
    else
        echo WARN
    fi
}

# classify_demo_probe <final_code> <final_url> -> PASS|FAIL
classify_demo_probe() {
    local code="$1" url="$2"
    case "$code" in
        2*) ;;
        *) echo FAIL; return ;;
    esac
    case "$url" in
        *wp-admin/install.php*|*wp-admin/setup-config.php*) echo FAIL ;;
        *) echo PASS ;;
    esac
}

# classify_alt_coverage <total> <with_alt> <min_pct> -> PASS|FAIL
# Integer-only: (with_alt * 100 / total) >= min_pct. Fail closed on anything
# that is not a measurable non-empty media set. Fail closed when min_pct is
# below the fixed floor of 50 (not operator-overridable) so a 0% threshold
# cannot certify 0/N empty alt. DEMO_ALT_MIN_COVERAGE_PCT may raise the bar;
# nothing may lower this floor.
classify_alt_coverage() {
    local total="$1" with_alt="$2" min_pct="$3"
    local floor=50
    case "$total" in *[!0-9]*|'') echo FAIL; return ;; esac
    case "$with_alt" in *[!0-9]*|'') echo FAIL; return ;; esac
    case "$min_pct" in *[!0-9]*|'') echo FAIL; return ;; esac
    if [ "$min_pct" -lt "$floor" ]; then
        echo FAIL
        return
    fi
    if [ "$total" -eq 0 ]; then
        echo FAIL
        return
    fi
    if [ "$with_alt" -gt "$total" ]; then
        echo FAIL
        return
    fi
    if [ $((with_alt * 100 / total)) -ge "$min_pct" ]; then
        echo PASS
    else
        echo FAIL
    fi
}

# classify_alt_population <header_total> <body_total> -> PASS|FAIL
# PASS only when both are the same positive integer (the probed page is the
# whole reported set). FAIL on empty, non-numeric, zero, or mismatch so a
# per_page=100 probe cannot silently certify a larger corpus.
classify_alt_population() {
    local header_total="$1" body_total="$2"
    case "$header_total" in *[!0-9]*|'') echo FAIL; return ;; esac
    case "$body_total" in *[!0-9]*|'') echo FAIL; return ;; esac
    if [ "$header_total" -eq 0 ] || [ "$body_total" -eq 0 ]; then
        echo FAIL
        return
    fi
    if [ "$header_total" -eq "$body_total" ]; then
        echo PASS
    else
        echo FAIL
    fi
}

# classify_alt_text_usable <text> -> PASS|FAIL
# FAIL on empty-after-trim, fewer than 15 characters, or no alphabetic
# character. Placeholder alt (".", a single space, digit-only padding) is not
# coverage.
classify_alt_text_usable() {
    local text="$1"
    text=$(printf '%s' "$text" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [ -z "$text" ]; then
        echo FAIL
        return
    fi
    if [ "${#text}" -lt 15 ]; then
        echo FAIL
        return
    fi
    case "$text" in
        *[A-Za-z]*) echo PASS ;;
        *) echo FAIL ;;
    esac
}

# classify_alt_provenance <sample_text> -> PASS|FAIL
# FAIL when the sample is empty (nothing measured) or contains any canned
# `seeded` adapter fixture caption. The sample is normalized before matching
# (lowercase, whitespace runs collapsed, trailing .!? stripped) and denylist
# arms are lowercased without trailing punctuation so dropping a period or
# lowercasing the first letter cannot evade the gate. This is not a complete
# denylist; adapter-identity meta is the durable fix and is deferred.
# Captions are hardcoded because this file is shipped standalone to the VM
# and cannot import Python; test-smoke-gate.sh extracts _FIXTURE_POOL at
# test time to catch drift.
classify_alt_provenance() {
    local sample="$1" last
    if [ -z "$sample" ]; then
        echo FAIL
        return
    fi
    sample=$(printf '%s' "$sample" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ')
    sample=$(printf '%s' "$sample" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    while [ -n "$sample" ]; do
        last="${sample#"${sample%?}"}"
        case "$last" in
            [.!?]) sample="${sample%?}" ;;
            *) break ;;
        esac
    done
    sample=$(printf '%s' "$sample" | sed 's/[[:space:]]*$//')
    if [ -z "$sample" ]; then
        echo FAIL
        return
    fi
    case "$sample" in
        *"a person standing outdoors near greenery"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"a plate of food on a wooden table"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"a scenic landscape with mountains under a clear sky"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"a close-up of a small object on a neutral background"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"a printed document with several lines of text"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"two people seated indoors in conversation"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"a building exterior seen from the street"*) echo FAIL; return ;;
    esac
    case "$sample" in
        *"a pet animal resting on a soft surface"*) echo FAIL; return ;;
    esac
    echo PASS
}
