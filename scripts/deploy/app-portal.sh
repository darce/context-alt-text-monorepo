#!/usr/bin/env bash
# Bounded app.altcontext.com edge prep for the existing OCI host.
#
# Default is dry-run. --apply validates a real frontend build, stages a Caddy
# vhost that preserves every existing host, validates the staged file, then
# activates in place and keeps a rollback copy. This script does not open a
# remote shell and does not mint Clerk/Polar credentials.
#
# Usage:
#   scripts/deploy/app-portal.sh
#   scripts/deploy/app-portal.sh --dry-run
#   FRONTEND_DIST=/path/to/dist scripts/deploy/app-portal.sh --apply
set -euo pipefail
export LC_ALL=C
export LANG=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

APPLY=0
FORCE_DRY=0

PROTECTED_HOSTS="api.altcontext.com staging.api.altcontext.com dev.api.altcontext.com fir.dev.api.altcontext.com demo.altcontext.com 129-213-40-111.sslip.io dl.darce.xyz"

usage() {
  cat <<'EOF' >&2
Usage: scripts/deploy/app-portal.sh [--dry-run|--apply]

Default: print the plan and mutate nothing.
--apply requires a real FRONTEND_DIST (index.html + assets) and a live Caddyfile.

Environment:
  APP_HOSTNAME         public vhost (default app.altcontext.com)
  APP_UPSTREAM         portal reverse_proxy target (default prod-api:8000)
  APP_ROOT             staging/rollback root (default /opt/acx-backend/app)
  APP_WWW              host static root (default $APP_ROOT/www)
  APP_FRONTEND_ROOT    path inside Caddy (default /srv/app-portal)
  CADDYFILE            live edge config (default /opt/acx-backend/Caddyfile)
  FRONTEND_DIST        built SPA directory (required for --apply)
  APP_SNIPPET          vhost snippet (default infra/oci/app/Caddyfile.app)
  APP_OVERLAY          compose overlay (default infra/oci/app/docker-compose.app.yml)
EOF
}

refuse() {
  echo "ERROR: $*" >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --dry-run)
      FORCE_DRY=1
      APPLY=0
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

if [ "$FORCE_DRY" -eq 1 ]; then
  APPLY=0
fi

if [ -z "${APP_HOSTNAME:-}" ]; then
  APP_HOSTNAME="app.altcontext.com"
fi
if [ -z "${APP_UPSTREAM+x}" ]; then
  APP_UPSTREAM="prod-api:8000"
fi
if [ -z "${APP_ROOT:-}" ]; then
  APP_ROOT="/opt/acx-backend/app"
fi
if [ -z "${APP_WWW:-}" ]; then
  APP_WWW="${APP_ROOT}/www"
fi
if [ -z "${APP_FRONTEND_ROOT:-}" ]; then
  APP_FRONTEND_ROOT="/srv/app-portal"
fi
if [ -z "${CADDYFILE:-}" ]; then
  CADDYFILE="/opt/acx-backend/Caddyfile"
fi
if [ -z "${FRONTEND_DIST:-}" ]; then
  FRONTEND_DIST=""
fi
if [ -z "${APP_SNIPPET:-}" ]; then
  APP_SNIPPET="${REPO_ROOT}/infra/oci/app/Caddyfile.app"
fi
if [ -z "${APP_OVERLAY:-}" ]; then
  APP_OVERLAY="${REPO_ROOT}/infra/oci/app/docker-compose.app.yml"
fi

is_safe_path() {
  _name="$1"
  _value="$2"
  if [ -z "$_value" ]; then
    refuse "${_name} is empty"
  fi
  case "$_value" in
    /*) ;;
    *) refuse "${_name} must be an absolute path (got: ${_value})" ;;
  esac
  case "$_value" in
    *..*) refuse "${_name} rejects path traversal (got: ${_value})" ;;
  esac
  if ! printf '%s' "$_value" | grep -Eq '^[A-Za-z0-9_./-]+$'; then
    refuse "${_name} has unsafe characters (got: ${_value})"
  fi
}

is_safe_hostname() {
  _value="$1"
  if ! printf '%s' "$_value" | grep -Eq '^[A-Za-z0-9.-]+$'; then
    refuse "APP_HOSTNAME has unsafe characters (got: ${_value})"
  fi
}

is_safe_upstream() {
  _value="$1"
  if [ -z "$_value" ]; then
    refuse "APP_UPSTREAM is empty"
  fi
  if ! printf '%s' "$_value" | grep -Eq '^[A-Za-z0-9._-]+:[0-9]+$'; then
    refuse "APP_UPSTREAM is unsafe or not host:port (got: ${_value})"
  fi
}

is_protected_hostname() {
  _value="$1"
  for _h in $PROTECTED_HOSTS; do
    if [ "$_value" = "$_h" ]; then
      return 0
    fi
  done
  return 1
}

is_safe_hostname "$APP_HOSTNAME"
if is_protected_hostname "$APP_HOSTNAME"; then
  refuse "APP_HOSTNAME ${APP_HOSTNAME} is an existing Caddy host; refusing to overwrite it"
fi
if [ -n "$APP_UPSTREAM" ]; then
  is_safe_upstream "$APP_UPSTREAM"
elif [ "$APPLY" -eq 1 ]; then
  refuse "APP_UPSTREAM is empty"
fi

is_safe_path APP_ROOT "$APP_ROOT"
is_safe_path APP_WWW "$APP_WWW"
is_safe_path APP_FRONTEND_ROOT "$APP_FRONTEND_ROOT"
is_safe_path CADDYFILE "$CADDYFILE"
is_safe_path APP_SNIPPET "$APP_SNIPPET"
is_safe_path APP_OVERLAY "$APP_OVERLAY"
if [ -n "${FRONTEND_DIST}" ]; then
  is_safe_path FRONTEND_DIST "$FRONTEND_DIST"
fi

SHARED_CADDY="${REPO_ROOT}/apps/prototype-description-service/Caddyfile"
if [ "$CADDYFILE" = "$SHARED_CADDY" ]; then
  refuse "refusing to mutate the shared repo Caddyfile; point CADDYFILE at the live VM config"
fi

validate_frontend() {
  if [ -z "${FRONTEND_DIST}" ]; then
    refuse "FRONTEND_DIST is required for --apply"
  fi
  if [ ! -d "$FRONTEND_DIST" ]; then
    refuse "FRONTEND_DIST is not a directory: ${FRONTEND_DIST}"
  fi
  if [ ! -f "${FRONTEND_DIST}/index.html" ]; then
    refuse "FRONTEND_DIST is missing index.html: ${FRONTEND_DIST}"
  fi
  if [ ! -s "${FRONTEND_DIST}/index.html" ]; then
    refuse "FRONTEND_DIST index.html is empty: ${FRONTEND_DIST}/index.html"
  fi
  if [ ! -d "${FRONTEND_DIST}/assets" ]; then
    refuse "FRONTEND_DIST is missing assets/: ${FRONTEND_DIST}"
  fi
  _asset_found=0
  for _asset in "${FRONTEND_DIST}/assets"/*; do
    if [ -f "$_asset" ]; then
      _asset_found=1
      break
    fi
  done
  if [ "$_asset_found" -ne 1 ]; then
    refuse "FRONTEND_DIST assets/ has no files: ${FRONTEND_DIST}/assets"
  fi
}

list_live_hosts() {
  if [ -f "$CADDYFILE" ]; then
    grep -E '^[A-Za-z0-9._-]+(,[ ]*[A-Za-z0-9._-]+)*[[:space:]]*\{' "$CADDYFILE" || true
  else
    echo "(live Caddyfile not present)"
  fi
}

print_plan() {
  cat <<EOF
plan:
  mode=$([ "$APPLY" -eq 1 ] && echo apply || echo dry-run)
  APP_HOSTNAME=$APP_HOSTNAME
  APP_UPSTREAM=$APP_UPSTREAM
  APP_ROOT=$APP_ROOT
  APP_WWW=$APP_WWW
  APP_FRONTEND_ROOT=$APP_FRONTEND_ROOT
  CADDYFILE=$CADDYFILE
  FRONTEND_DIST=${FRONTEND_DIST:-}
  APP_SNIPPET=$APP_SNIPPET
  APP_OVERLAY=$APP_OVERLAY
  preserve existing Caddy hosts; merge ${APP_HOSTNAME} only
  live hosts:
$(list_live_hosts | sed 's/^/    /')
  validate staged Caddyfile before in-place activation
  retain rollback under ${APP_ROOT}/rollback
  later overlay mount: ${APP_WWW} -> /srv/app-portal via docker-compose.app.yml
  env ownership: Clerk/Polar stay in /opt/acx-backend/prod/.env; VITE_CLERK_* is baked into FRONTEND_DIST
EOF
}

strip_app_vhost() {
  _src="$1"
  _host_re="$(printf '%s' "$APP_HOSTNAME" | sed 's/\./\\./g')"
  awk -v host_re="$_host_re" '
    BEGIN { skip=0; depth=0 }
    function braces(s, n, i, c) {
      n=0
      for (i=1; i<=length(s); i++) {
        c=substr(s,i,1)
        if (c=="{") n++
        else if (c=="}") n--
      }
      return n
    }
    $0 ~ /# BEGIN APP_PORTAL_VHOST/ { skip=1; next }
    skip==1 && $0 ~ /# END APP_PORTAL_VHOST/ { skip=0; next }
    skip==1 { next }
    skip==0 && $0 ~ ("^" host_re "[[:space:]]*\\{") {
      skip=2
      depth=braces($0)
      if (depth<=0) skip=0
      next
    }
    skip==2 {
      depth+=braces($0)
      if (depth<=0) skip=0
      next
    }
    { print }
  ' "$_src"
}

render_snippet() {
  sed -e "s|__APP_HOSTNAME__|${APP_HOSTNAME}|g" \
      -e "s|^app.altcontext.com {|${APP_HOSTNAME} {|" \
      -e "s|__APP_UPSTREAM__|${APP_UPSTREAM}|g" \
      -e "s|__APP_FRONTEND_ROOT__|${APP_FRONTEND_ROOT}|g" \
      "$APP_SNIPPET"
}

validate_staged_caddy() {
  _staged="$1"
  if command -v caddy >/dev/null 2>&1; then
    caddy validate --config "$_staged" --adapter caddyfile
    return $?
  fi
  if command -v docker >/dev/null 2>&1; then
    docker run --rm \
      -v "${_staged}:/etc/caddy/Caddyfile:ro" \
      caddy:2-alpine \
      caddy validate --config /etc/caddy/Caddyfile
    return $?
  fi
  refuse "neither caddy nor docker is available for staged validation"
}

print_plan

if [ "$APPLY" -ne 1 ]; then
  echo "dry-run: no files changed"
  exit 0
fi

[ -f "$APP_SNIPPET" ] || refuse "APP_SNIPPET is missing: ${APP_SNIPPET}"
[ -f "$APP_OVERLAY" ] || refuse "APP_OVERLAY is missing: ${APP_OVERLAY}"
[ -f "$CADDYFILE" ] || refuse "CADDYFILE is missing: ${CADDYFILE}"
validate_frontend

STAGED="${APP_ROOT}/Caddyfile.staged"
STAGING_WWW="${APP_WWW}.staging"
ROLLBACK_DIR="${APP_ROOT}/rollback"
mkdir -p "$APP_ROOT"

{
  strip_app_vhost "$CADDYFILE"
  printf '\n'
  render_snippet
  printf '\n'
} > "$STAGED"

if ! validate_staged_caddy "$STAGED"; then
  echo "ERROR: staged Caddy validation failed; live config left intact: ${CADDYFILE}" >&2
  exit 4
fi

mkdir -p "$ROLLBACK_DIR"
ts="$(date +%s)"
ROLLBACK_CADDY="${ROLLBACK_DIR}/Caddyfile.${ts}"
cp -a "$CADDYFILE" "$ROLLBACK_CADDY"

rm -rf "$STAGING_WWW"
mkdir -p "$STAGING_WWW"
cp -a "${FRONTEND_DIST}/." "$STAGING_WWW/"

if ! cat "$STAGED" > "$CADDYFILE"; then
  cat "$ROLLBACK_CADDY" > "$CADDYFILE" || true
  rm -rf "$STAGING_WWW"
  refuse "activation failed; restored rollback ${ROLLBACK_CADDY}"
fi

if [ -d "$APP_WWW" ]; then
  rm -rf "${ROLLBACK_DIR}/www.${ts}"
  mv "$APP_WWW" "${ROLLBACK_DIR}/www.${ts}"
fi
mv "$STAGING_WWW" "$APP_WWW"
cp -a "$APP_OVERLAY" "${APP_ROOT}/docker-compose.app.yml"
rm -f "$STAGED"

echo "applied: ${APP_HOSTNAME} -> ${APP_UPSTREAM}; frontend ${APP_WWW}; rollback ${ROLLBACK_CADDY}"
echo "next: apply compose overlay so Caddy mounts ${APP_WWW} at /srv/app-portal; do not ship this vhost via the shared repo Caddyfile from this lane"
