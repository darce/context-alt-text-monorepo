#!/usr/bin/env bash
# Pure classification logic for the sync-demo.sh post-deploy vhost smoke.
# Sourced locally by scripts/deploy/tests/test-smoke-gate.sh and shipped to the
# VM inline by sync-demo.sh — keep it dependency-free (no curl, no arrays) so
# the same functions run under macOS bash 3.2 and the VM's bash.
#
# Fixture-caption denylist arms live in scripts/deploy/lib/fixture-denylist.sh.
# sync-demo.sh concatenates that file ahead of this one in the remote heredoc.
# Tests source fixture-denylist.sh first so classify_alt_provenance can call
# normalize_fixture_sample / fixture_sample_is_denied.
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
# FAIL when the sample is empty after normalize (nothing measured) or matches
# any canned `seeded` adapter fixture caption. Denylist arms live in
# fixture-denylist.sh; sync-demo.sh concatenates that file ahead of this one
# so the helpers exist on the VM. Empty-after-normalize FAILs closed — the
# one intentional difference from describe-gate, which returns UNKNOWN.
# This is not a complete denylist; adapter-identity meta is the durable fix
# and is deferred. test-smoke-gate.sh extracts _FIXTURE_POOL at test time
# to catch drift against the shared matcher.
classify_alt_provenance() {
    local sample="$1"
    if [ -z "$(normalize_fixture_sample "$sample")" ]; then
        echo FAIL
        return
    fi
    if fixture_sample_is_denied "$sample"; then
        echo FAIL
        return
    fi
    echo PASS
}
