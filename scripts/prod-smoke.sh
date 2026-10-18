#!/usr/bin/env bash
#
# prod-smoke.sh — Minimal round-trip smoke test against the deployed backend.
#
# Closes E15-3a-BR-04: no CI cron yet, but ships a manually-invokable script
# so operators can detect plugin/backend contract drift during release gates.
# Exits non-zero on any probe failure so it can be wired into CI later.
#
# Probes (in order):
#   1. GET /health                       — liveness (PR-01)
#   2. GET /version                      — deployed identity (E15-3a-BR-03)
#   3. GET /ready                        — readiness (E15-2 consolidated surface)
#   4. GET /recognition/clusters?limit=1 — auth'd read with X-Api-Key (E15-3a-BR-08)
#
# Usage:
#   scripts/prod-smoke.sh --base-url https://api.altcontext.com --api-key "$CANARY_KEY"
#
# Env overrides:
#   ACX_SMOKE_BASE_URL       default: https://api.altcontext.com
#   ACX_SMOKE_API_KEY        required for auth'd probe
#   ACX_SMOKE_TENANT_ID      required for auth'd probe; sent as X-Tenant-ID
#   ACX_SMOKE_TIMEOUT        curl --max-time seconds (default 10)
#
set -euo pipefail

BASE_URL="${ACX_SMOKE_BASE_URL:-https://api.altcontext.com}"
API_KEY="${ACX_SMOKE_API_KEY:-}"
TENANT_ID="${ACX_SMOKE_TENANT_ID:-}"
TIMEOUT="${ACX_SMOKE_TIMEOUT:-10}"
UNAUTH_ONLY=0

show_usage() {
	cat <<'USAGE'
Usage:
  scripts/prod-smoke.sh [--base-url URL] [--api-key KEY] [--tenant-id UUID] [--timeout SECONDS] [--unauth-only]

Options:
  --base-url     Backend root (default $ACX_SMOKE_BASE_URL or https://api.altcontext.com)
  --api-key      Canary key for auth'd probes (default $ACX_SMOKE_API_KEY); required unless --unauth-only
  --tenant-id    Canary tenant UUID sent as X-Tenant-ID (default $ACX_SMOKE_TENANT_ID); required unless --unauth-only
  --timeout      Per-request curl timeout in seconds (default 10)
  --unauth-only  Skip the authenticated /recognition/clusters probe. Use only for
                 pre-auth deploys where the API key is not yet provisioned. Release
                 gates for production MUST run without this flag so a broken
                 plugin-facing auth path cannot silently pass the smoke (E15-3a-BR-23).
  --help         Show this help and exit

Exit codes:
  0  all probes passed
  1  a probe failed (stderr names which one)
  2  invalid arguments (including missing --api-key / --tenant-id without --unauth-only)
USAGE
}

while (($# > 0)); do
	case "$1" in
		--base-url)    BASE_URL="${2:-}";  shift 2 ;;
		--api-key)     API_KEY="${2:-}";   shift 2 ;;
		--tenant-id)   TENANT_ID="${2:-}"; shift 2 ;;
		--timeout)     TIMEOUT="${2:-}";   shift 2 ;;
		--unauth-only) UNAUTH_ONLY=1;      shift 1 ;;
		--help|-h)  show_usage; exit 0 ;;
		*) echo "Unknown argument: $1" >&2; show_usage >&2; exit 2 ;;
	esac
done

if [[ -z "${BASE_URL}" ]]; then
	echo "error: --base-url is required" >&2
	exit 2
fi

# E15-3a-BR-23: fail argument validation when the auth credentials are
# missing unless the caller explicitly opted into unauth-only mode. The
# previous behaviour silently skipped the authenticated probe and still
# exited 0 if the unauth paths were 200, letting a broken plugin-facing
# auth contract slip past the release gate.
if (( UNAUTH_ONLY == 0 )); then
	if [[ -z "${API_KEY}" || -z "${TENANT_ID}" ]]; then
		echo "error: --api-key and --tenant-id are required (or pass --unauth-only to skip the authenticated probe)" >&2
		exit 2
	fi
fi

fail=0

probe_unauth() {
	local path="$1"
	local url="${BASE_URL%/}${path}"
	local code
	code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${TIMEOUT}" "${url}" || echo '000')"
	if [[ "${code}" != "200" ]]; then
		echo "FAIL ${path}: HTTP ${code}" >&2
		fail=1
	else
		echo "ok   ${path}: HTTP 200"
	fi
}

probe_auth_get() {
	local path="$1"
	local url="${BASE_URL%/}${path}"
	# Argument validation above guarantees API_KEY and TENANT_ID are set
	# whenever this is called; --unauth-only callers skip the call entirely.
	local code
	code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${TIMEOUT}" \
		-H "X-Api-Key: ${API_KEY}" \
		-H "X-Tenant-ID: ${TENANT_ID}" \
		"${url}" || echo '000')"
	if [[ "${code}" != "200" ]]; then
		echo "FAIL ${path}: HTTP ${code}" >&2
		fail=1
	else
		echo "ok   ${path}: HTTP 200"
	fi
}

echo "prod-smoke against ${BASE_URL}"
probe_unauth "/health"
probe_unauth "/version"
probe_unauth "/ready"
if (( UNAUTH_ONLY == 1 )); then
	echo "skip /recognition/clusters: --unauth-only was set; authenticated probe bypassed"
else
	probe_auth_get "/recognition/clusters?limit=1"
fi

if ((fail == 0)); then
	echo "all probes ok"
	exit 0
fi
echo "one or more probes failed" >&2
exit 1
