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
