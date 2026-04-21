#!/usr/bin/env bash
#
# prod-smoke.sh — Minimal round-trip smoke test against the deployed backend.
#
# Closes E15-3a-BR-04: no CI cron yet, but ships a manually-invokable script
# so operators can detect plugin/backend contract drift during release gates.
# Exits non-zero on any probe failure so it can be wired into CI later.
#
# Probes (in order):
#   1. GET  /health              — liveness (PR-01)
#   2. GET  /version             — deployed identity (E15-3a-BR-03)
#   3. GET  /recognition/health  — recognition subsystem
#   4. POST /recognition/settings/test   — auth'd echo with X-Api-Key
#   5. POST /recognition/describe-minimal (optional, flagged by ACX_SMOKE_RECOGNIZE=1)
#
# Usage:
#   scripts/prod-smoke.sh --base-url https://api.altcontext.com --api-key "$CANARY_KEY"
#
# Env overrides:
#   ACX_SMOKE_BASE_URL       default: https://api.altcontext.com
#   ACX_SMOKE_API_KEY        required for auth'd probes
#   ACX_SMOKE_TIMEOUT        curl --max-time seconds (default 10)
#   ACX_SMOKE_RECOGNIZE      set to 1 to exercise a minimal recognition call
#
set -euo pipefail

BASE_URL="${ACX_SMOKE_BASE_URL:-https://api.altcontext.com}"
API_KEY="${ACX_SMOKE_API_KEY:-}"
TIMEOUT="${ACX_SMOKE_TIMEOUT:-10}"

show_usage() {
	cat <<'USAGE'
Usage:
  scripts/prod-smoke.sh [--base-url URL] [--api-key KEY] [--timeout SECONDS]

Options:
  --base-url   Backend root (default $ACX_SMOKE_BASE_URL or https://api.altcontext.com)
  --api-key    Canary key for auth'd probes (default $ACX_SMOKE_API_KEY)
  --timeout    Per-request curl timeout in seconds (default 10)
  --help       Show this help and exit

Exit codes:
  0  all probes passed
  1  a probe failed (stderr names which one)
  2  invalid arguments
USAGE
}

while (($# > 0)); do
	case "$1" in
		--base-url) BASE_URL="${2:-}"; shift 2 ;;
		--api-key)  API_KEY="${2:-}";  shift 2 ;;
		--timeout)  TIMEOUT="${2:-}";  shift 2 ;;
		--help|-h)  show_usage; exit 0 ;;
		*) echo "Unknown argument: $1" >&2; show_usage >&2; exit 2 ;;
	esac
done

if [[ -z "${BASE_URL}" ]]; then
	echo "error: --base-url is required" >&2
	exit 2
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
	if [[ -z "${API_KEY}" ]]; then
		echo "skip ${path}: no --api-key supplied" >&2
		return
	fi
	local code
	code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${TIMEOUT}" \
		-H "X-Api-Key: ${API_KEY}" "${url}" || echo '000')"
	if [[ "${code}" != "200" ]]; then
		echo "FAIL ${path}: HTTP ${code}" >&2
		fail=1
	else
		echo "ok   ${path}: HTTP 200"
	fi
}

probe_auth_post() {
	local path="$1"
	local body="${2:-{}}"
	local url="${BASE_URL%/}${path}"
	if [[ -z "${API_KEY}" ]]; then
		echo "skip ${path}: no --api-key supplied" >&2
		return
	fi
	local code
	code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${TIMEOUT}" \
		-H "X-Api-Key: ${API_KEY}" -H 'Content-Type: application/json' \
		-X POST -d "${body}" "${url}" || echo '000')"
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
probe_unauth "/recognition/health"
probe_auth_post "/recognition/settings/test" '{}'

if [[ "${ACX_SMOKE_RECOGNIZE:-0}" == "1" ]]; then
	probe_auth_post "/recognition/describe-minimal" '{"prompt":"smoke"}'
fi

if ((fail == 0)); then
	echo "all probes ok"
	exit 0
fi
echo "one or more probes failed" >&2
exit 1
