#!/usr/bin/env bash
# Deliberate per-site enable for the signed-out public guide at /guide/.
#
# Usage:
#   WP_PATH=/path/to/wordpress scripts/deploy/enable-public-guide.sh --site-url https://demo.altcontext.com
#   DRY_RUN=1 WP_PATH=/path/to/wordpress scripts/deploy/enable-public-guide.sh --site-url https://example.com --dry-run
#
# Requires WP-CLI (`wp`) and `curl` on PATH. Does not enable acx_public_demo_enabled
# (`/acx/v1/public/demo/describe` stays off unless ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1).
set -euo pipefail
export LC_ALL=C
export LANG=C

DRY_RUN="${DRY_RUN:-0}"
WP_PATH="${WP_PATH:-}"
SITE_URL="${SITE_URL:-}"
RETAIN_PUBLIC_DEMO_DESCRIBE="${ACX_RETAIN_PUBLIC_DEMO_DESCRIBE:-0}"

usage() {
  cat <<'EOF' >&2
Usage: WP_PATH=/path/to/wordpress scripts/deploy/enable-public-guide.sh --site-url <url> [--dry-run]

Environment:
  WP_PATH                          WordPress root (required; no default site)
  SITE_URL                         Alternate to --site-url
  DRY_RUN=1                        Print the plan; mutate nothing
  ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1  Allow acx_public_demo_enabled to stay on
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

run_wp() {
  wp --path="$WP_PATH" "$@"
}

print_plan() {
  cat <<EOF
plan:
  WP_PATH=$WP_PATH
  SITE_URL=$SITE_URL
  GUIDE_URL=$GUIDE_URL
  wp --path=$WP_PATH option update acx_public_guide_enabled 1
  wp --path=$WP_PATH rewrite flush --hard
  curl signed-out GET $GUIDE_URL expect 200 and id="acx-public-guide"
  print acx_public_demo_enabled; refuse unless it is off or ACX_RETAIN_PUBLIC_DEMO_DESCRIBE=1
EOF
}

if is_truthy "$DRY_RUN"; then
  print_plan
  exit 0
fi

if [ ! -d "$WP_PATH" ]; then
  refuse "WP_PATH is not a directory: $WP_PATH"
fi

command -v wp >/dev/null 2>&1 || refuse "wp is not on PATH"
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
cleanup() {
  rm -f "$body_file"
}
trap cleanup EXIT

echo "==> Signed-out GET $GUIDE_URL"
http_code="$(curl -sS -o "$body_file" -w '%{http_code}' "$GUIDE_URL")"
echo "GET $GUIDE_URL -> ${http_code}"

if [ "$http_code" != "200" ]; then
  echo "ERROR: expected HTTP 200 from $GUIDE_URL, got ${http_code}" >&2
  exit 4
fi
if ! grep -q 'id="acx-public-guide"' "$body_file"; then
  echo "ERROR: response body from $GUIDE_URL lacks id=\"acx-public-guide\"" >&2
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
