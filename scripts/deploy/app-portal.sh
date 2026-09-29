#!/usr/bin/env bash
# Bounded app.altcontext.com edge prep for the existing OCI host.
#
# Default is dry-run. --apply validates a real frontend build, stages every
# artifact, snapshots rollback state, and journals activation before promotion.
# The Caddyfile keeps its inode for single-file bind mounts; www and overlay
# promotion use same-directory atomic rename. Interrupted activation is restored
# from its durable journal at the start of the next --apply run.
# This script does not open a remote shell and does not mint Clerk/Polar
# credentials.
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
DEFAULT_APPROVED_ROOT="/opt/acx-backend"
DEFAULT_FRONTEND_ROOT="/srv/app-portal"

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
  APP_FRONTEND_ROOT    path inside Caddy (must be /srv/app-portal)
  CADDYFILE            live edge config (default /opt/acx-backend/Caddyfile)
  FRONTEND_DIST        built SPA directory (required for --apply)
  APP_SNIPPET          vhost snippet (default infra/oci/app/Caddyfile.app)
  APP_OVERLAY          compose overlay (default infra/oci/app/docker-compose.app.yml)
  APP_APPROVED_ROOTS   colon-separated host dest roots (default /opt/acx-backend)
  APP_RELOAD_CMD       optional absolute executable run after host promote
  APP_HEALTH_CMD       optional absolute executable run after reload
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
  APP_FRONTEND_ROOT="$DEFAULT_FRONTEND_ROOT"
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
if [ -z "${APP_APPROVED_ROOTS:-}" ]; then
  APP_APPROVED_ROOTS="$DEFAULT_APPROVED_ROOT"
fi
if [ -z "${APP_RELOAD_CMD:-}" ]; then
  APP_RELOAD_CMD=""
fi
if [ -z "${APP_HEALTH_CMD:-}" ]; then
  APP_HEALTH_CMD=""
fi

strip_trailing_slashes() {
  _value="$1"
  if [ "$_value" = "/" ]; then
    printf '%s' "/"
    return
  fi
  while [ "$_value" != "/" ] && [ "${_value%/}" != "$_value" ]; do
    _value="${_value%/}"
  done
  printf '%s' "$_value"
}

assert_lexical_path() {
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
    *//*) refuse "${_name} rejects empty path components (got: ${_value})" ;;
  esac
  if ! printf '%s' "$_value" | grep -Eq '^[A-Za-z0-9_./-]+$'; then
    refuse "${_name} has unsafe characters (got: ${_value})"
  fi
}

assert_not_filesystem_root() {
  _name="$1"
  _value="$2"
  if [ "$_value" = "/" ]; then
    refuse "${_name} rejects filesystem root /"
  fi
}

assert_no_symlink_components() {
  _name="$1"
  _value="$2"
  _cur=""
  _rest="${_value#/}"
  while [ -n "$_rest" ]; do
    _part="${_rest%%/*}"
    if [ "$_part" = "$_rest" ]; then
      _rest=""
    else
      _rest="${_rest#*/}"
    fi
    if [ -z "$_part" ] || [ "$_part" = "." ] || [ "$_part" = ".." ]; then
      refuse "${_name} rejects empty or dot path components (got: ${_value})"
    fi
    _cur="${_cur}/${_part}"
    if [ -L "$_cur" ]; then
      refuse "${_name} rejects symlink component ${_cur}"
    fi
  done
}

assert_under_approved_roots() {
  _name="$1"
  _value="$2"
  _ok=0
  _old_ifs="$IFS"
  IFS=:
  # shellcheck disable=SC2086
  set -- $APP_APPROVED_ROOTS
  IFS="$_old_ifs"
  for _root in "$@"; do
    case "$_value" in
      "$_root"/*)
        _ok=1
        break
        ;;
    esac
  done
  if [ "$_ok" -ne 1 ]; then
    refuse "${_name} is outside approved deploy roots (got: ${_value})"
  fi
}

guard_dest_path() {
  _name="$1"
  _value="$2"
  _kind="$3"
  assert_lexical_path "$_name" "$_value"
  _value="$(strip_trailing_slashes "$_value")"
  eval "${_name}=\"\${_value}\""
  assert_not_filesystem_root "$_name" "$_value"
  assert_no_symlink_components "$_name" "$_value"
  assert_under_approved_roots "$_name" "$_value"
  if [ -e "$_value" ]; then
    case "$_kind" in
      file)
        if [ -L "$_value" ] || [ ! -f "$_value" ]; then
          refuse "${_name} must be a regular file (got: ${_value})"
        fi
        ;;
      dir)
        if [ -L "$_value" ] || [ ! -d "$_value" ]; then
          refuse "${_name} must be a directory (got: ${_value})"
        fi
        ;;
    esac
  fi
}

guard_source_path() {
  _name="$1"
  _value="$2"
  _kind="$3"
  assert_lexical_path "$_name" "$_value"
  _value="$(strip_trailing_slashes "$_value")"
  eval "${_name}=\"\${_value}\""
  assert_not_filesystem_root "$_name" "$_value"
  assert_no_symlink_components "$_name" "$_value"
  if [ "$_kind" = "file" ]; then
    if [ ! -f "$_value" ] || [ -L "$_value" ]; then
      refuse "${_name} must be a regular file: ${_value}"
    fi
  elif [ "$_kind" = "dir" ]; then
    if [ ! -d "$_value" ] || [ -L "$_value" ]; then
      refuse "${_name} must be a directory: ${_value}"
    fi
  elif [ "$_kind" = "exec" ]; then
    if [ ! -f "$_value" ] || [ -L "$_value" ] || [ ! -x "$_value" ]; then
      refuse "${_name} must be a regular executable: ${_value}"
    fi
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

_old_ifs="$IFS"
IFS=:
# shellcheck disable=SC2086
set -- $APP_APPROVED_ROOTS
IFS="$_old_ifs"
_approved_normalized=""
for _root in "$@"; do
  _root="$(strip_trailing_slashes "$_root")"
  assert_lexical_path APP_APPROVED_ROOTS "$_root"
  assert_not_filesystem_root APP_APPROVED_ROOTS "$_root"
  assert_no_symlink_components APP_APPROVED_ROOTS "$_root"
  if [ -z "$_approved_normalized" ]; then
    _approved_normalized="$_root"
  else
    _approved_normalized="${_approved_normalized}:${_root}"
  fi
done
APP_APPROVED_ROOTS="$_approved_normalized"
[ -n "$APP_APPROVED_ROOTS" ] || refuse "APP_APPROVED_ROOTS is empty"

guard_dest_path APP_ROOT "$APP_ROOT" dir
guard_dest_path APP_WWW "$APP_WWW" dir
if [ "$APP_WWW" = "$APP_ROOT" ]; then
  refuse "APP_WWW must not equal APP_ROOT"
fi
case "$APP_WWW" in
  "$APP_ROOT"/rollback|"$APP_ROOT"/rollback/*|"$APP_ROOT"/staging|"$APP_ROOT"/staging/*)
    refuse "APP_WWW collides with staging/rollback paths"
    ;;
esac
assert_lexical_path APP_FRONTEND_ROOT "$APP_FRONTEND_ROOT"
APP_FRONTEND_ROOT="$(strip_trailing_slashes "$APP_FRONTEND_ROOT")"
assert_not_filesystem_root APP_FRONTEND_ROOT "$APP_FRONTEND_ROOT"
if [ "$APP_FRONTEND_ROOT" != "$DEFAULT_FRONTEND_ROOT" ]; then
  refuse "APP_FRONTEND_ROOT must be ${DEFAULT_FRONTEND_ROOT} (got: ${APP_FRONTEND_ROOT})"
fi
guard_dest_path CADDYFILE "$CADDYFILE" file
STAGING_DIR="${APP_ROOT}/staging"
OVERLAY_DEST="${APP_ROOT}/docker-compose.app.yml"
ROLLBACK_DIR="${APP_ROOT}/rollback"
ACTIVATION_JOURNAL="${APP_ROOT}/activation.journal"
case "$CADDYFILE" in
  "$APP_WWW"|"$APP_WWW"/*) refuse "CADDYFILE is inside APP_WWW" ;;
esac
guard_source_path APP_SNIPPET "$APP_SNIPPET" file
guard_source_path APP_OVERLAY "$APP_OVERLAY" file
if [ -n "${FRONTEND_DIST}" ]; then
  guard_source_path FRONTEND_DIST "$FRONTEND_DIST" dir
fi
if [ -n "$APP_RELOAD_CMD" ]; then
  guard_source_path APP_RELOAD_CMD "$APP_RELOAD_CMD" exec
fi
if [ -n "$APP_HEALTH_CMD" ]; then
  guard_source_path APP_HEALTH_CMD "$APP_HEALTH_CMD" exec
fi

SHARED_CADDY="${REPO_ROOT}/apps/prototype-description-service/Caddyfile"
if [ "$CADDYFILE" = "$SHARED_CADDY" ]; then
  refuse "refusing to mutate the shared repo Caddyfile; point CADDYFILE at the live VM config"
fi

assert_rm_safe() {
  _name="$1"
  _value="$2"
  assert_not_filesystem_root "$_name" "$_value"
  assert_under_approved_roots "$_name" "$_value"
  case "$_value" in
    "$APP_ROOT"/rollback|"$APP_ROOT"/rollback/*)
      refuse "${_name} refuses to mutate rollback paths"
      ;;
  esac
}

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

sync_path() {
  sync -f "$1"
}

atomic_copy_file() {
  _source="$1"
  _dest="$2"
  _tmp="${_dest}.new.$$"
  if ! cp -a "$_source" "$_tmp"; then
    rm -f "$_tmp"
    return 1
  fi
  if ! sync_path "$_tmp"; then
    rm -f "$_tmp"
    return 1
  fi
  if ! mv -f "$_tmp" "$_dest"; then
    rm -f "$_tmp"
    return 1
  fi
  sync_path "$(dirname -- "$_dest")"
}

copy_file_in_place() {
  _source="$1"
  _dest="$2"
  if ! sync_path "$_source"; then
    return 1
  fi
  if ! cat "$_source" > "$_dest"; then
    return 1
  fi
  sync_path "$_dest"
}

write_activation_journal() {
  _phase="$1"
  _tmp="${ACTIVATION_JOURNAL}.new.$$"
  if ! (
    umask 077
    printf 'version=1\nphase=%s\ncaddyfile=%s\napp_www=%s\noverlay=%s\nrollback_caddy=%s\nrollback_www=%s\nrollback_overlay=%s\n' \
      "$_phase" "$CADDYFILE" "$APP_WWW" "$OVERLAY_DEST" \
      "$ROLLBACK_CADDY" "$ROLLBACK_WWW" "$ROLLBACK_OVERLAY" > "$_tmp"
  ); then
    rm -f "$_tmp"
    return 1
  fi
  if ! sync_path "$_tmp"; then
    rm -f "$_tmp"
    return 1
  fi
  if ! mv -f "$_tmp" "$ACTIVATION_JOURNAL"; then
    rm -f "$_tmp"
    return 1
  fi
  sync_path "$APP_ROOT"
}

read_journal_field() {
  IFS= read -r _journal_line <&3 || return 1
  case "$_journal_line" in
    "$1="*) JOURNAL_VALUE="${_journal_line#*=}" ;;
    *) return 1 ;;
  esac
}

load_activation_journal() {
  if [ -L "$ACTIVATION_JOURNAL" ] || [ ! -f "$ACTIVATION_JOURNAL" ]; then
    echo "ERROR: activation journal is not a regular file: ${ACTIVATION_JOURNAL}" >&2
    return 1
  fi
  exec 3< "$ACTIVATION_JOURNAL" || return 1
  IFS= read -r _journal_line <&3 && [ "$_journal_line" = "version=1" ] || {
    exec 3<&-
    echo "ERROR: unsupported activation journal: ${ACTIVATION_JOURNAL}" >&2
    return 1
  }
  read_journal_field phase || { exec 3<&-; return 1; }
  JOURNAL_PHASE="$JOURNAL_VALUE"
  read_journal_field caddyfile || { exec 3<&-; return 1; }
  JOURNAL_CADDYFILE="$JOURNAL_VALUE"
  read_journal_field app_www || { exec 3<&-; return 1; }
  JOURNAL_WWW="$JOURNAL_VALUE"
  read_journal_field overlay || { exec 3<&-; return 1; }
  JOURNAL_OVERLAY="$JOURNAL_VALUE"
  read_journal_field rollback_caddy || { exec 3<&-; return 1; }
  ROLLBACK_CADDY="$JOURNAL_VALUE"
  read_journal_field rollback_www || { exec 3<&-; return 1; }
  ROLLBACK_WWW="$JOURNAL_VALUE"
  read_journal_field rollback_overlay || { exec 3<&-; return 1; }
  ROLLBACK_OVERLAY="$JOURNAL_VALUE"
  if IFS= read -r _journal_line <&3; then
    exec 3<&-
    echo "ERROR: extra data in activation journal: ${ACTIVATION_JOURNAL}" >&2
    return 1
  fi
  exec 3<&-

  case "$JOURNAL_PHASE" in
    prepared|caddy_promoted|www_promoted|overlay_promoted) ;;
    *) echo "ERROR: invalid activation journal phase: ${JOURNAL_PHASE}" >&2; return 1 ;;
  esac
  if [ "$JOURNAL_CADDYFILE" != "$CADDYFILE" ] || [ "$JOURNAL_WWW" != "$APP_WWW" ] || [ "$JOURNAL_OVERLAY" != "$OVERLAY_DEST" ]; then
    echo "ERROR: activation journal paths do not match this deploy configuration" >&2
    return 1
  fi
  _journal_stamp="${ROLLBACK_CADDY##*.}"
  case "$_journal_stamp" in
    ''|*[!0-9]*) echo "ERROR: invalid Caddy snapshot path in activation journal" >&2; return 1 ;;
  esac
  if [ "$ROLLBACK_CADDY" != "${ROLLBACK_DIR}/Caddyfile.${_journal_stamp}" ] || [ -L "$ROLLBACK_CADDY" ] || [ ! -f "$ROLLBACK_CADDY" ]; then
    echo "ERROR: Caddy snapshot is missing or invalid: ${ROLLBACK_CADDY}" >&2
    return 1
  fi
  if [ "$ROLLBACK_WWW" != "-" ] && { [ "$ROLLBACK_WWW" != "${ROLLBACK_DIR}/www.${_journal_stamp}" ] || [ -L "$ROLLBACK_WWW" ] || [ ! -d "$ROLLBACK_WWW" ]; }; then
    echo "ERROR: frontend snapshot is missing or invalid: ${ROLLBACK_WWW}" >&2
    return 1
  fi
  if [ "$ROLLBACK_OVERLAY" != "-" ] && { [ "$ROLLBACK_OVERLAY" != "${ROLLBACK_DIR}/docker-compose.app.yml.${_journal_stamp}" ] || [ -L "$ROLLBACK_OVERLAY" ] || [ ! -f "$ROLLBACK_OVERLAY" ]; }; then
    echo "ERROR: overlay snapshot is missing or invalid: ${ROLLBACK_OVERLAY}" >&2
    return 1
  fi
}

clear_activation_journal() {
  rm -f "$ACTIVATION_JOURNAL" "${ACTIVATION_JOURNAL}.new."*
  sync_path "$APP_ROOT"
}

restore_from_rollback() {
  echo "restoring Caddyfile, static root, and overlay from activation snapshot"
  if ! cmp -s "$ROLLBACK_CADDY" "$CADDYFILE"; then
    if ! copy_file_in_place "$ROLLBACK_CADDY" "$CADDYFILE"; then
      echo "ERROR: could not restore Caddyfile from ${ROLLBACK_CADDY}" >&2
      return 1
    fi
  fi
  if [ "$ROLLBACK_WWW" != "-" ]; then
    if [ ! -d "$APP_WWW" ] || ! diff -qr "$ROLLBACK_WWW" "$APP_WWW" >/dev/null 2>&1; then
      assert_rm_safe APP_WWW "$APP_WWW" || return 1
      if ! rm -rf "$APP_WWW" || ! cp -a "$ROLLBACK_WWW" "$APP_WWW" || ! sync_path "$APP_ROOT"; then
        echo "ERROR: could not restore static root from ${ROLLBACK_WWW}" >&2
        return 1
      fi
    fi
  elif [ -e "$APP_WWW" ]; then
    assert_rm_safe APP_WWW "$APP_WWW" || return 1
    if ! rm -rf "$APP_WWW" || ! sync_path "$APP_ROOT"; then
      echo "ERROR: could not remove uncommitted static root ${APP_WWW}" >&2
      return 1
    fi
  fi
  if [ "$ROLLBACK_OVERLAY" != "-" ]; then
    if [ ! -f "$OVERLAY_DEST" ] || ! cmp -s "$ROLLBACK_OVERLAY" "$OVERLAY_DEST"; then
      if ! atomic_copy_file "$ROLLBACK_OVERLAY" "$OVERLAY_DEST"; then
        echo "ERROR: could not restore overlay from ${ROLLBACK_OVERLAY}" >&2
        return 1
      fi
    fi
  elif [ -e "$OVERLAY_DEST" ]; then
    if ! rm -f "$OVERLAY_DEST" || ! sync_path "$APP_ROOT"; then
      echo "ERROR: could not remove uncommitted overlay ${OVERLAY_DEST}" >&2
      return 1
    fi
  fi
  if ! rm -rf "${APP_WWW}.prev" "$STAGING_DIR" || ! sync_path "$APP_ROOT"; then
    echo "ERROR: could not finish activation rollback cleanup" >&2
    return 1
  fi
  if ! reload_caddy; then
    echo "ERROR: rollback reload failed; activation journal retained for retry" >&2
    return 1
  fi
}

recover_interrupted_activation() {
  if ! load_activation_journal; then
    return 1
  fi
  echo "recovering interrupted activation from ${ACTIVATION_JOURNAL}"
  if ! restore_from_rollback; then
    return 1
  fi
  clear_activation_journal
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
  APP_APPROVED_ROOTS=$APP_APPROVED_ROOTS
  preserve existing Caddy hosts; merge ${APP_HOSTNAME} only
  live hosts:
$(list_live_hosts | sed 's/^/    /')
  stage Caddyfile, static root, and overlay; validate before activation
  durable activation journal precedes atomic Caddyfile, www, and overlay promotion
  failure trap or next run restores snapshots and reloads rollback
  retain rollback under ${APP_ROOT}/rollback
  render overlay APP_WWW=${APP_WWW} -> /srv/app-portal
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

render_overlay() {
  if ! grep -q '__APP_WWW__' "$APP_OVERLAY"; then
    refuse "APP_OVERLAY is missing __APP_WWW__ placeholder"
  fi
  sed -e "s|__APP_WWW__|${APP_WWW}|g" "$APP_OVERLAY"
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

reload_caddy() {
  if [ -n "$APP_RELOAD_CMD" ]; then
    "$APP_RELOAD_CMD"
    return $?
  fi
  if command -v caddy >/dev/null 2>&1; then
    caddy reload --config "$CADDYFILE" --adapter caddyfile
    return $?
  fi
  echo "reload skipped: set APP_RELOAD_CMD or install caddy; host files are activated, edge process not reloaded"
  return 0
}

default_health() {
  [ -f "$CADDYFILE" ] || return 1
  grep -F "$APP_HOSTNAME" "$CADDYFILE" >/dev/null || return 1
  [ -s "${APP_WWW}/index.html" ] || return 1
  [ -d "${APP_WWW}/assets" ] || return 1
  [ -f "$OVERLAY_DEST" ] || return 1
  grep -F "$APP_WWW" "$OVERLAY_DEST" >/dev/null || return 1
}

run_health() {
  if [ -n "$APP_HEALTH_CMD" ]; then
    "$APP_HEALTH_CMD"
    return $?
  fi
  default_health
}

if [ -e "$ACTIVATION_JOURNAL" ] || [ -L "$ACTIVATION_JOURNAL" ]; then
  if [ "$APPLY" -eq 1 ]; then
    if ! recover_interrupted_activation; then
      refuse "could not recover interrupted activation from ${ACTIVATION_JOURNAL}"
    fi
  else
    if ! load_activation_journal; then
      refuse "could not inspect interrupted activation journal ${ACTIVATION_JOURNAL}"
    fi
    echo "recovery pending: journal=${ACTIVATION_JOURNAL} phase=${JOURNAL_PHASE}; rerun with --apply"
  fi
fi

print_plan

if [ "$APPLY" -ne 1 ]; then
  echo "dry-run: no files changed"
  exit 0
fi

[ -f "$APP_SNIPPET" ] || refuse "APP_SNIPPET is missing: ${APP_SNIPPET}"
[ -f "$APP_OVERLAY" ] || refuse "APP_OVERLAY is missing: ${APP_OVERLAY}"
[ -f "$CADDYFILE" ] || refuse "CADDYFILE is missing: ${CADDYFILE}"
if [ -L "$CADDYFILE" ] || [ ! -f "$CADDYFILE" ]; then
  refuse "CADDYFILE must be a regular file: ${CADDYFILE}"
fi
validate_frontend

STAGED_CADDY="${STAGING_DIR}/Caddyfile"
STAGED_WWW="${STAGING_DIR}/www"
STAGED_OVERLAY="${STAGING_DIR}/docker-compose.app.yml"
mkdir -p "$APP_ROOT" "$STAGING_DIR"

{
  strip_app_vhost "$CADDYFILE"
  printf '\n'
  render_snippet
  printf '\n'
} > "$STAGED_CADDY"

render_overlay > "$STAGED_OVERLAY"

rm -rf "$STAGED_WWW"
mkdir -p "$STAGED_WWW"
cp -a "${FRONTEND_DIST}/." "$STAGED_WWW/"

if ! validate_staged_caddy "$STAGED_CADDY"; then
  echo "ERROR: staged Caddy validation failed; live config left intact: ${CADDYFILE}" >&2
  rm -rf "$STAGING_DIR"
  exit 4
fi

mkdir -p "$ROLLBACK_DIR"
ts="$(date +%s)"
ROLLBACK_CADDY="${ROLLBACK_DIR}/Caddyfile.${ts}"
ROLLBACK_WWW="${ROLLBACK_DIR}/www.${ts}"
ROLLBACK_OVERLAY="${ROLLBACK_DIR}/docker-compose.app.yml.${ts}"
cp -a "$CADDYFILE" "$ROLLBACK_CADDY"
if [ -d "$APP_WWW" ]; then
  cp -a "$APP_WWW" "$ROLLBACK_WWW"
else
  ROLLBACK_WWW="-"
fi
if [ -f "$OVERLAY_DEST" ]; then
  cp -a "$OVERLAY_DEST" "$ROLLBACK_OVERLAY"
else
  ROLLBACK_OVERLAY="-"
fi
sync_path "$ROLLBACK_DIR"
sync_path "$APP_ROOT"

activation_fail() {
  echo "ERROR: ${1:-activation step failed}" >&2
  trap - ERR INT TERM
  if ! restore_from_rollback; then
    echo "ERROR: activation rollback is incomplete; journal retained for next run" >&2
    exit 5
  fi
  if ! clear_activation_journal; then
    echo "ERROR: activation rollback completed but journal cleanup failed" >&2
  fi
  exit 5
}

trap 'activation_fail "interrupted during activation"' INT TERM
trap 'activation_fail "activation step failed"' ERR

write_activation_journal prepared
if ! copy_file_in_place "$STAGED_CADDY" "$CADDYFILE"; then
  activation_fail "Caddyfile promote failed"
fi
write_activation_journal caddy_promoted

assert_rm_safe APP_WWW "$APP_WWW"
if [ -e "$APP_WWW" ]; then
  rm -rf "${APP_WWW}.prev"
  mv "$APP_WWW" "${APP_WWW}.prev"
fi
mv "$STAGED_WWW" "$APP_WWW"
rm -rf "${APP_WWW}.prev"
sync_path "$APP_ROOT"
write_activation_journal www_promoted

if ! atomic_copy_file "$STAGED_OVERLAY" "$OVERLAY_DEST"; then
  activation_fail "overlay promote failed"
fi
write_activation_journal overlay_promoted
rm -rf "$STAGING_DIR"

if ! reload_caddy; then
  activation_fail "caddy reload failed after host promote"
fi
if ! run_health; then
  activation_fail "health check failed after reload"
fi

clear_activation_journal
trap - ERR INT TERM

echo "applied: ${APP_HOSTNAME} -> ${APP_UPSTREAM}; frontend ${APP_WWW}; overlay ${OVERLAY_DEST}; rollback ${ROLLBACK_CADDY}; reload=ok health=ok"
echo "next: apply compose overlay so Caddy mounts ${APP_WWW} at /srv/app-portal; recreate Caddy if the bind-mount inode diverged; do not ship this vhost via the shared repo Caddyfile from this lane"
