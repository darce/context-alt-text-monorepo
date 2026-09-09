#!/usr/bin/env bash
# Deliberate per-site enable for the signed-out public guide at /guide/.
#
# Usage:
#   WP_PATH=/path/to/wordpress scripts/deploy/enable-public-guide.sh --site-url https://demo.altcontext.com
#   DRY_RUN=1 WP_PATH=/path/to/wordpress scripts/deploy/enable-public-guide.sh --site-url https://example.com --dry-run
#   ACX_WP_RUNNER=host WP_PATH=/path/to/app/public scripts/deploy/enable-public-guide.sh --site-url http://localhost:10010
#
# Default WP runner is the compose `wpcli` tools service (same seam as
# infra/oci/demo/bootstrap-wp.sh) when a compose file is present. Host `wp`
# is for LocalWP via ACX_WP_RUNNER=host. Does not enable acx_public_demo_enabled
# (`/acx/v1/public/demo/describe` stays off unless ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1).
set -euo pipefail
export LC_ALL=C
export LANG=C

DRY_RUN="${DRY_RUN:-0}"
WP_PATH="${WP_PATH:-}"
SITE_URL="${SITE_URL:-}"
RETAIN_PUBLIC_DEMO_DESCRIBE="${ACX_RETAIN_PUBLIC_DEMO_DESCRIBE:-0}"
ACX_WP_RUNNER="${ACX_WP_RUNNER:-}"
DEMO_DIR="${DEMO_DIR:-/opt/acx-backend/demo}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.demo.yml}"
WP_RUNNER=""
RESOLVED_COMPOSE_FILE=""

usage() {
  cat <<'EOF' >&2
Usage: WP_PATH=/path/to/wordpress scripts/deploy/enable-public-guide.sh --site-url <url> [--dry-run]

Environment:
  WP_PATH                          WordPress root (required; no default site)
  SITE_URL                         Alternate to --site-url
  DRY_RUN=1                        Print the plan; mutate nothing
  ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1  Allow acx_public_demo_enabled to stay on
  ACX_WP_RUNNER=compose|host       Force the wp runner (default: compose when a
                                   compose file is present, else host wp)
  DEMO_DIR                         Demo stack dir (default /opt/acx-backend/demo)
  COMPOSE_FILE                     Compose file name or path (default docker-compose.demo.yml)
EOF
}

refuse() {
  echo "ERROR: $*" >&2
  usage
  exit 2
}

is_truthy() {
  case "$1" in
    true|TRUE|True|1|"'1'") return 0 ;;
    *) return 1 ;;
  esac
}

strip_trailing_slashes() {
  # bash 3.2: no ${var:0:-1}; peel one trailing slash at a time.
  _value="$1"
  while [ "${_value%/}" != "$_value" ]; do
    _value="${_value%/}"
  done
  printf '%s' "$_value"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --site-url)
      SITE_URL="${2:-}"
      shift 2
      ;;
    --site-url=*)
      SITE_URL="${1#--site-url=}"
      shift
      ;;
    --wp-path)
      WP_PATH="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      refuse "unknown argument: $1"
      ;;
  esac
done

if [ -z "$WP_PATH" ]; then
  refuse "WP_PATH is required (no default site)."
fi
if [ -z "$SITE_URL" ]; then
  refuse "--site-url (or SITE_URL) is required (no default site)."
fi

SITE_URL="$(strip_trailing_slashes "$SITE_URL")"
GUIDE_URL="${SITE_URL}/guide/"

resolve_compose_file() {
  _cf="$COMPOSE_FILE"
  if [ -n "$_cf" ] && [ -f "$_cf" ]; then
    _cf_dir="$(cd "$(dirname "$_cf")" && pwd)"
    printf '%s' "${_cf_dir}/$(basename "$_cf")"
    return 0
  fi
  if [ -n "$DEMO_DIR" ] && [ -f "${DEMO_DIR}/${_cf}" ]; then
    _demo_dir="$(cd "$DEMO_DIR" && pwd)"
    printf '%s' "${_demo_dir}/$(basename "$_cf")"
    return 0
  fi
  if [ -n "$DEMO_DIR" ] && [ -f "${DEMO_DIR}/docker-compose.demo.yml" ]; then
    _demo_dir="$(cd "$DEMO_DIR" && pwd)"
    printf '%s' "${_demo_dir}/docker-compose.demo.yml"
    return 0
  fi
  printf ''
}

compose() {
  docker compose -f "$RESOLVED_COMPOSE_FILE" "$@"
}

compose_available() {
  [ -n "$RESOLVED_COMPOSE_FILE" ] && [ -f "$RESOLVED_COMPOSE_FILE" ] && command -v docker >/dev/null 2>&1
}

host_wp_available() {
  command -v wp >/dev/null 2>&1
}

neither_runner_message() {
  printf '%s' "neither compose wpcli nor host wp is available (set ACX_WP_RUNNER=host with wp on PATH, or provide COMPOSE_FILE/DEMO_DIR and docker)"
}

select_wp_runner() {
  RESOLVED_COMPOSE_FILE="$(resolve_compose_file)"
  case "$ACX_WP_RUNNER" in
    compose)
      if compose_available; then
        WP_RUNNER="compose"
        return 0
      fi
      refuse "ACX_WP_RUNNER=compose but docker compose wpcli is unavailable (set COMPOSE_FILE or DEMO_DIR and ensure docker is on PATH)"
      ;;
    host)
      if host_wp_available; then
        WP_RUNNER="host"
        return 0
      fi
      refuse "ACX_WP_RUNNER=host but wp is not on PATH"
      ;;
    "")
      if compose_available; then
        WP_RUNNER="compose"
        return 0
      fi
      if host_wp_available; then
        WP_RUNNER="host"
        return 0
      fi
      refuse "$(neither_runner_message)"
      ;;
    *)
      refuse "ACX_WP_RUNNER must be compose or host (got: $ACX_WP_RUNNER)"
      ;;
  esac
}

run_wp() {
  case "$WP_RUNNER" in
    compose)
      compose run --rm --no-deps wpcli wp "$@"
      ;;
    host)
      wp --path="$WP_PATH" "$@"
      ;;
    *)
      refuse "$(neither_runner_message)"
      ;;
  esac
}

wp_plan_prefix() {
  case "$WP_RUNNER" in
    compose)
      printf 'docker compose -f %s run --rm --no-deps wpcli wp' "$RESOLVED_COMPOSE_FILE"
      ;;
    *)
      printf 'wp --path=%s' "$WP_PATH"
      ;;
  esac
}

print_plan() {
  _wp_prefix="$(wp_plan_prefix)"
  cat <<EOF
plan:
  WP_PATH=$WP_PATH
  SITE_URL=$SITE_URL
  GUIDE_URL=$GUIDE_URL
  ACX_WP_RUNNER=$WP_RUNNER
  ${_wp_prefix} option update acx_public_guide_enabled 1
  ${_wp_prefix} rewrite flush --hard
  curl signed-out GET $GUIDE_URL expect 200 and id="acx-public-guide-js"
  print acx_public_demo_enabled; refuse unless it is off or ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1
  on GET 4/5: option update acx_public_guide_enabled 0; rewrite flush --hard
EOF
}

select_wp_runner

if is_truthy "$DRY_RUN"; then
  print_plan
  exit 0
fi

if [ ! -d "$WP_PATH" ]; then
  refuse "WP_PATH is not a directory: $WP_PATH"
fi

command -v curl >/dev/null 2>&1 || refuse "curl is not on PATH"

demo_enabled="$(run_wp option get acx_public_demo_enabled 2>/dev/null || true)"
demo_enabled="$(printf '%s' "$demo_enabled" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [ -z "$demo_enabled" ]; then
  demo_enabled="0"
fi
echo "acx_public_demo_enabled=${demo_enabled}"

if is_truthy "$demo_enabled" && ! is_truthy "$RETAIN_PUBLIC_DEMO_DESCRIBE"; then
  echo "ERROR: acx_public_demo_enabled is on (${demo_enabled}); /acx/v1/public/demo/describe must stay off unless ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1." >&2
  exit 3
fi

echo "==> Enable acx_public_guide_enabled on $SITE_URL"
run_wp option update acx_public_guide_enabled 1
echo "==> Flush rewrites"
run_wp rewrite flush --hard

body_file="$(mktemp "${TMPDIR:-/tmp}/acx-public-guide.XXXXXX")"
verify_exit=0
rollback_public_guide() {
  echo "==> Verification failed (exit ${verify_exit}); rolling back acx_public_guide_enabled" >&2
  run_wp option update acx_public_guide_enabled 0 || true
  run_wp rewrite flush --hard || true
  echo "rolled back acx_public_guide_enabled to 0" >&2
}
cleanup() {
  if [ "$verify_exit" -eq 4 ] || [ "$verify_exit" -eq 5 ]; then
    rollback_public_guide
  fi
  rm -f "$body_file"
}
trap cleanup EXIT

echo "==> Signed-out GET $GUIDE_URL"
http_code="$(curl -sS -L --max-redirs 3 --connect-timeout 10 --max-time 15 -o "$body_file" -w '%{http_code}' "$GUIDE_URL")"
echo "GET $GUIDE_URL -> ${http_code}"

if [ "$http_code" != "200" ]; then
  echo "ERROR: expected HTTP 200 from $GUIDE_URL, got ${http_code}" >&2
  verify_exit=4
  exit 4
fi
if ! grep -q 'id="acx-public-guide-js"' "$body_file"; then
  echo "ERROR: response body from $GUIDE_URL lacks id=\"acx-public-guide-js\" (working guide bundle)" >&2
  verify_exit=5
  exit 5
fi

demo_enabled_after="$(run_wp option get acx_public_demo_enabled 2>/dev/null || true)"
demo_enabled_after="$(printf '%s' "$demo_enabled_after" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [ -z "$demo_enabled_after" ]; then
  demo_enabled_after="0"
fi
echo "acx_public_demo_enabled=${demo_enabled_after}"
if is_truthy "$demo_enabled_after" && ! is_truthy "$RETAIN_PUBLIC_DEMO_DESCRIBE"; then
  echo "ERROR: acx_public_demo_enabled is on (${demo_enabled_after}) after enable; describe endpoint must stay off unless ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1." >&2
  exit 3
fi

echo "public guide enabled: $GUIDE_URL"
