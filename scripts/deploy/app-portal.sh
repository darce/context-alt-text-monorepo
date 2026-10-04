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

# The runbook installs a copy under this name for live frontend/API checks.
if [ "${0##*/}" = "app-portal-health-check" ]; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required for app-portal-health-check" >&2
    exit 1
  fi
  health_status=0
  for health_url in "https://${APP_HOSTNAME:-app.altcontext.com}/" "https://api.altcontext.com/ready"; do
    if ! curl --fail --silent --show-error --location --max-time 15 --output /dev/null "$health_url"; then
      echo "ERROR: health check failed: ${health_url}" >&2
      health_status=1
    fi
  done
  portal_health_url="https://${APP_HOSTNAME:-app.altcontext.com}/portal/me"
  if ! portal_status="$(curl --silent --show-error --location --max-time 15 --output /dev/null --write-out '%{http_code}' "$portal_health_url")"; then
    echo "ERROR: health check failed: ${portal_health_url}" >&2
    health_status=1
  elif [ "$portal_status" != "401" ]; then
    echo "ERROR: health check failed: ${portal_health_url} (expected HTTP 401 from portal API, got ${portal_status:-no status})" >&2
    health_status=1
  fi
  exit "$health_status"
fi

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
--apply requires a real FRONTEND_DIST (index.html + assets), a live Caddyfile,
a Docker Compose file/client, jq, a reload mechanism, and APP_HEALTH_CMD to verify
the serving edge and portal API.

Environment:
  APP_HOSTNAME         public vhost (default app.altcontext.com)
  APP_UPSTREAM         portal reverse_proxy target (default prod-api:8000)
  APP_ROOT             staging/rollback root (default /opt/acx-backend/app)
  APP_WWW              host static root (default $APP_ROOT/www)
  CADDY_COMPOSE        base Caddy compose file (default in APP_ROOT's parent)
  APP_FRONTEND_ROOT    path inside Caddy (must be /srv/app-portal)
  CADDYFILE            live edge config (default /opt/acx-backend/Caddyfile)
  FRONTEND_DIST        built SPA directory (required for --apply)
  APP_SNIPPET          vhost snippet (default infra/oci/app/Caddyfile.app)
  APP_OVERLAY          compose overlay (default infra/oci/app/docker-compose.app.yml)
  APP_APPROVED_ROOTS   colon-separated host dest roots (default /opt/acx-backend)
  APP_DEPLOY_LOCK_WAIT seconds to wait for another deploy (default 30)
  APP_RELOAD_CMD       optional absolute executable run after host promote
  APP_HEALTH_CMD       required for --apply: absolute executable checking live
                       frontend and portal upstream after reload (nonzero on failure)
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

path_is_same_or_inside() {
  local _path="$1"
  local _parent="$2"
  case "$_path" in
    "$_parent"|"$_parent"/*) return 0 ;;
    *) return 1 ;;
  esac
}

paths_overlap() {
  local _first="$1"
  local _second="$2"
  path_is_same_or_inside "$_first" "$_second" || path_is_same_or_inside "$_second" "$_first"
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
if [ -z "${CADDY_COMPOSE:-}" ]; then
  CADDY_COMPOSE="${APP_ROOT%/*}/docker-compose.caddy.yml"
fi
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
# Reject staging aliases before lock, recovery, or staging writes can touch
# files through an unsafe directory component.
guard_dest_path STAGING_DIR "$STAGING_DIR" dir
OVERLAY_DEST="${APP_ROOT}/docker-compose.app.yml"
ROLLBACK_DIR="${APP_ROOT}/rollback"
ACTIVATION_JOURNAL="${APP_ROOT}/activation.journal"
DEPLOY_LOCK="${ACTIVATION_JOURNAL}.lock"
for _reserved_path in "$ACTIVATION_JOURNAL" "$DEPLOY_LOCK" "$OVERLAY_DEST"; do
  if paths_overlap "$APP_WWW" "$_reserved_path"; then
    refuse "APP_WWW collides with activation paths"
  fi
  if paths_overlap "${APP_WWW}.prev" "$_reserved_path"; then
    refuse "APP_WWW.prev collides with activation paths"
  fi
done
if path_is_same_or_inside "$APP_ROOT" "$APP_WWW"; then
  refuse "APP_WWW collides with activation paths"
fi
if path_is_same_or_inside "$APP_ROOT" "${APP_WWW}.prev"; then
  refuse "APP_WWW.prev collides with activation paths"
fi
case "$CADDYFILE" in
  "$APP_WWW"|"$APP_WWW"/*) refuse "CADDYFILE is inside APP_WWW" ;;
esac
guard_source_path APP_SNIPPET "$APP_SNIPPET" file
guard_source_path APP_OVERLAY "$APP_OVERLAY" file
# Planning needs a safe path, but the host Compose file may not be installed yet.
guard_source_path CADDY_COMPOSE "$CADDY_COMPOSE" path
# Guards above require absolute paths without dot or symlink components, so
# these normalized paths identify the actual filesystem destinations.
for _activation_path in "$STAGING_DIR" "$ROLLBACK_DIR" "$APP_WWW" "${APP_WWW}.prev" \
  "$CADDYFILE" "$OVERLAY_DEST" "$ACTIVATION_JOURNAL" "$DEPLOY_LOCK"; do
  if paths_overlap "$CADDY_COMPOSE" "$_activation_path"; then
    refuse "CADDY_COMPOSE collides with activation paths"
  fi
done
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

# Parse root-absolute assets from browser-loaded src and href attributes.
frontend_asset_references() {
  awk -v mode="${2:-assets}" '
    function strip_url_suffix(value, query, fragment, cut_at) {
      query = index(value, "?")
      fragment = index(value, "#")
      cut_at = 0
      if (query > 0) cut_at = query
      if (fragment > 0 && (cut_at == 0 || fragment < cut_at)) cut_at = fragment
      if (cut_at > 0) value = substr(value, 1, cut_at - 1)
      return value
    }

    function emit_asset(value, query, fragment, cut_at) {
      if (substr(value, 1, 8) != "/assets/") return
      print strip_url_suffix(value)
    }

    function emit_module_asset(value) {
      if (substr(value, 1, 8) != "/assets/") return
      value = strip_url_suffix(value)
      if (tolower(substr(value, length(value) - 2)) != ".js") return
      print value
    }

    function fail_scan(message) {
      print message | "cat 1>&2"
      close("cat 1>&2")
      exit 1
    }

    function find_raw_close(document, lower_document, element, from,    needle, offset, found, after, comment, nested, cursor, body_from) {
      needle = "</" element
      body_from = from
      while (from <= length(document)) {
        offset = index(substr(lower_document, from), needle)
        if (offset == 0) return -1
        found = from + offset - 1
        after = substr(document, found + length(needle), 1)
        if (after ~ /[ \t\r\n\f/>]/) {
          if (element == "script") {
            # Fail closed on potentially double-escaped script data. In that
            # state the first textual closing tag does not close the element.
            comment = index(substr(document, body_from, found - body_from), "<!--")
            if (comment > 0) {
              cursor = body_from + comment + 3
              while (cursor < found) {
                nested = index(substr(lower_document, cursor, found - cursor), "<script")
                if (nested == 0) break
                cursor += nested - 1
                if (substr(document, cursor + 7, 1) ~ /[ \t\r\n\f/>]/) return 0
                cursor += 7
              }
            }
          }
          return found
        }
        from = found + length(needle)
      }
      return -1
    }

    function parse_tag(tag, active,    i, n, c, start, name, value, quote) {
      i = 2
      n = length(tag)
      parsed_tag_name = ""
      parsed_tag_closing = 0
      parsed_script_type = ""
      parsed_script_src = ""
      if (substr(tag, i, 1) == "/") {
        parsed_tag_closing = 1
        i++
      }
      if (substr(tag, i, 1) !~ /[A-Za-z]/) return
      start = i
      while (i <= n && substr(tag, i, 1) !~ /[ \t\r\n\f/>]/) i++
      parsed_tag_name = tolower(substr(tag, start, i - start))
      if (parsed_tag_closing) return
      while (i <= n) {
        c = substr(tag, i, 1)
        if (c ~ /[ \t\r\n\f>]/ || c == "/") {
          i++
          continue
        }
        start = i
        while (i <= n && substr(tag, i, 1) !~ /[ \t\r\n\f=>]/ && substr(tag, i, 1) != "/") i++
        if (i == start) {
          i++
          continue
        }
        name = tolower(substr(tag, start, i - start))
        while (i <= n && substr(tag, i, 1) ~ /[ \t\r\n\f]/) i++
        value = ""
        if (substr(tag, i, 1) == "=") {
          i++
          while (i <= n && substr(tag, i, 1) ~ /[ \t\r\n\f]/) i++
          c = substr(tag, i, 1)
          if (c == "\047" || c == "\042") {
            quote = c
            i++
            start = i
            while (i <= n && substr(tag, i, 1) != quote) i++
            value = substr(tag, start, i - start)
            if (i <= n) i++
          } else {
            start = i
            while (i <= n && substr(tag, i, 1) !~ /[ \t\r\n\f>]/) i++
            value = substr(tag, start, i - start)
          }
        }
        if (name == "type") parsed_script_type = value
        if (name == "src") parsed_script_src = value
        if (active && mode == "assets" && (name == "src" || name == "href")) emit_asset(value)
      }
      if (active && mode == "modules" && parsed_tag_name == "script" &&
          tolower(parsed_script_type) == "module") {
        emit_module_asset(parsed_script_src)
      }
    }

    {
      document = document $0 "\n"
    }

    END {
      i = 1
      n = length(document)
      lower_document = tolower(document)
      inert_depth = 0
      raw_element = ""
      while (i <= n) {
        if (raw_element != "") {
          raw_close = find_raw_close(document, lower_document, raw_element, i)
          if (raw_close == 0) fail_scan("index.html contains undecidable <script> data")
          if (raw_close < 0) fail_scan("index.html ends inside an unterminated <" raw_element ">")
          i = raw_close
          raw_element = ""
          continue
        }
        if (substr(document, i, 4) == "<!--") {
          comment_end = index(substr(document, i + 4), "-->")
          if (comment_end == 0) fail_scan("index.html ends inside an unterminated comment")
          i += comment_end + 6
          continue
        }
        if (substr(document, i, 1) != "<") {
          i++
          continue
        }
        next_char = substr(document, i + 1, 1)
        if (next_char == "/") {
          if (substr(document, i + 2, 1) !~ /[A-Za-z]/) {
            i++
            continue
          }
        } else if (next_char !~ /[A-Za-z]/) {
          i++
          continue
        }
        quote = ""
        end = i + 1
        while (end <= n) {
          c = substr(document, end, 1)
          if (quote != "") {
            if (c == quote) quote = ""
          } else if (c == "\047" || c == "\042") {
            quote = c
          } else if (c == ">") {
            break
          }
          end++
        }
        if (end <= n) {
          parse_tag(substr(document, i, end - i + 1), inert_depth == 0)
          if (parsed_tag_name == "template") {
            if (parsed_tag_closing) {
              for (depth = inert_depth; depth > 0; depth--) {
                if (inert_stack[depth] == parsed_tag_name) {
                  inert_depth = depth - 1
                  break
                }
              }
            } else {
              inert_stack[++inert_depth] = parsed_tag_name
            }
          }
          if (!parsed_tag_closing && parsed_tag_name == "plaintext") {
            fail_scan("index.html contains unsupported <plaintext> data")
          }
          if (!parsed_tag_closing &&
              (parsed_tag_name == "script" || parsed_tag_name == "style" ||
               parsed_tag_name == "textarea" || parsed_tag_name == "title" ||
               parsed_tag_name == "iframe" || parsed_tag_name == "xmp" ||
               parsed_tag_name == "noembed" || parsed_tag_name == "noframes" ||
               parsed_tag_name == "noscript")) {
            raw_element = parsed_tag_name
          }
          i = end + 1
        } else {
          fail_scan("index.html ends inside an unterminated tag")
        }
      }
      if (inert_depth > 0) fail_scan("index.html ends inside an unterminated <template>")
    }
  ' "$1"
}

validate_frontend() {
  local _frontend_dir="${1:-${FRONTEND_DIST}}"
  local _symlink_paths _asset_refs _module_refs _asset_ref _asset

  if [ -z "$_frontend_dir" ]; then
    echo "ERROR: FRONTEND_DIST is required for --apply" >&2
    return 1
  fi
  if [ -L "$_frontend_dir" ] || [ ! -d "$_frontend_dir" ]; then
    echo "ERROR: FRONTEND_DIST is not a directory: ${_frontend_dir}" >&2
    return 1
  fi
  if ! _symlink_paths="$(find "$_frontend_dir" -type l -print)"; then
    echo "ERROR: could not inspect FRONTEND_DIST for symlinks: ${_frontend_dir}" >&2
    return 1
  fi
  if [ -n "$_symlink_paths" ]; then
    echo "ERROR: FRONTEND_DIST contains a symlink in the staged tree" >&2
    return 1
  fi
  if [ ! -f "${_frontend_dir}/index.html" ]; then
    echo "ERROR: FRONTEND_DIST is missing index.html: ${_frontend_dir}" >&2
    return 1
  fi
  if [ ! -s "${_frontend_dir}/index.html" ]; then
    echo "ERROR: FRONTEND_DIST index.html is empty: ${_frontend_dir}/index.html" >&2
    return 1
  fi
  if [ ! -d "${_frontend_dir}/assets" ]; then
    echo "ERROR: FRONTEND_DIST is missing assets/: ${_frontend_dir}" >&2
    return 1
  fi
  if ! _asset_refs="$(frontend_asset_references "${_frontend_dir}/index.html" assets)"; then
    echo "ERROR: could not read FRONTEND_DIST index.html: ${_frontend_dir}/index.html" >&2
    return 1
  fi
  if [ -z "$_asset_refs" ]; then
    echo "ERROR: FRONTEND_DIST index.html has no /assets/ src or href references" >&2
    return 1
  fi
  if ! _module_refs="$(frontend_asset_references "${_frontend_dir}/index.html" modules)"; then
    echo "ERROR: could not read FRONTEND_DIST index.html: ${_frontend_dir}/index.html" >&2
    return 1
  fi
  if [ -z "$_module_refs" ]; then
    echo "ERROR: FRONTEND_DIST index.html has no /assets/*.js module script entry" >&2
    return 1
  fi
  while IFS= read -r _asset_ref; do
    [ -n "$_asset_ref" ] || continue
    case "$_asset_ref" in
      *"/../"*|*"/./"*|*/..|*/.)
        echo "ERROR: FRONTEND_DIST index.html has an unsafe asset reference: ${_asset_ref}" >&2
        return 1
        ;;
    esac
    _asset="${_frontend_dir}${_asset_ref}"
    if [ ! -f "$_asset" ]; then
      echo "ERROR: FRONTEND_DIST index.html references missing asset: ${_asset_ref}" >&2
      return 1
    fi
    if [ ! -s "$_asset" ]; then
      echo "ERROR: FRONTEND_DIST index.html references empty asset: ${_asset_ref}" >&2
      return 1
    fi
  done <<< "$_asset_refs"
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
    printf 'version=2\nphase=%s\ncaddyfile=%s\napp_www=%s\noverlay=%s\ncaddy_compose=%s\nrollback_caddy=%s\nrollback_www=%s\nrollback_overlay=%s\n' \
      "$_phase" "$CADDYFILE" "$APP_WWW" "$OVERLAY_DEST" "$CADDY_COMPOSE" \
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
  sync_path "$APP_ROOT" || return 1
  JOURNAL_PHASE="$_phase"
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
  IFS= read -r _journal_line <&3 && [ "$_journal_line" = "version=2" ] || {
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
  read_journal_field caddy_compose || { exec 3<&-; return 1; }
  JOURNAL_CADDY_COMPOSE="$JOURNAL_VALUE"
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
  if [ "$JOURNAL_CADDYFILE" != "$CADDYFILE" ] || [ "$JOURNAL_WWW" != "$APP_WWW" ] || [ "$JOURNAL_OVERLAY" != "$OVERLAY_DEST" ] || [ "$JOURNAL_CADDY_COMPOSE" != "$CADDY_COMPOSE" ]; then
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
    assert_rm_safe APP_WWW "$APP_WWW" || return 1
    if ! rm -rf "$APP_WWW" || ! cp -a "$ROLLBACK_WWW" "$APP_WWW" || ! sync_path "$APP_ROOT"; then
      echo "ERROR: could not restore static root from ${ROLLBACK_WWW}" >&2
      return 1
    fi
  elif [ -e "$APP_WWW" ]; then
    assert_rm_safe APP_WWW "$APP_WWW" || return 1
    if ! rm -rf "$APP_WWW" || ! sync_path "$APP_ROOT"; then
      echo "ERROR: could not remove uncommitted static root ${APP_WWW}" >&2
      return 1
    fi
  fi
  if [ "$ROLLBACK_OVERLAY" != "-" ]; then
    if ! atomic_copy_file "$ROLLBACK_OVERLAY" "$OVERLAY_DEST"; then
      echo "ERROR: could not restore overlay from ${ROLLBACK_OVERLAY}" >&2
      return 1
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
  # Restoring www replaces its directory even when activation stopped before
  # overlay promotion. Recreate Caddy after restoration to refresh its mount.
  if ! apply_caddy_compose; then
    echo "ERROR: compose rollback failed; activation journal retained for retry" >&2
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
  CADDY_COMPOSE=$CADDY_COMPOSE
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
  apply the Caddy compose overlay before reload and live health checking
  failure trap or next run restores snapshots, reapplies compose, and reloads rollback
  retain only the latest successful apply's rollback set under ${APP_ROOT}/rollback
  render overlay APP_WWW=${APP_WWW} -> /srv/app-portal
  env ownership: Clerk/Polar stay in /opt/acx-backend/prod/.env; VITE_CLERK_* is baked into FRONTEND_DIST
EOF
  if [ ! -f "$CADDY_COMPOSE" ]; then
    echo "CADDY_COMPOSE is absent: ${CADDY_COMPOSE} (required for --apply)"
  fi
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
    "$APP_RELOAD_CMD" 9>&-
    return $?
  fi
  if [ -f "$OVERLAY_DEST" ]; then
    docker compose -f "$CADDY_COMPOSE" -f "$OVERLAY_DEST" exec -T caddy \
      caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 9>&-
  else
    docker compose -f "$CADDY_COMPOSE" exec -T caddy \
      caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile 9>&-
  fi
}

verify_caddyfile_binding() {
  local _source
  # Compose resolves relative bind sources. Parse its model, never raw YAML.
  # The same mount must survive base-only rollback and every selected overlay.
  if ! _source=$(docker compose -f "$CADDY_COMPOSE" "$@" config --format json 9>&- |
    jq -er '[.services.caddy.volumes[]? | select(.target == "/etc/caddy/Caddyfile")] |
      if length == 1 and .[0].type == "bind" then .[0].source | select(type == "string")
      else error("expected one Caddyfile bind mount") end'); then
    refuse "cannot resolve Caddy bind source for /etc/caddy/Caddyfile; expected CADDYFILE=${CADDYFILE}"
  fi
  [ "$_source" = "$CADDYFILE" ] ||
    refuse "Caddy bind source ${_source} for /etc/caddy/Caddyfile does not match CADDYFILE=${CADDYFILE}"
}

apply_caddy_compose() {
  # A bind mount pins the directory inode; unchanged Compose configuration
  # cannot detect the www swap. Recreate only Caddy after every replacement.
  if [ -f "$OVERLAY_DEST" ]; then
    docker compose -f "$CADDY_COMPOSE" -f "$OVERLAY_DEST" up -d --force-recreate --no-deps caddy || return 1
  else
    docker compose -f "$CADDY_COMPOSE" up -d --force-recreate --no-deps caddy || return 1
  fi
  wait_for_caddy_admin
}

wait_for_caddy_admin() {
  local _attempt
  local -a _compose=(docker compose -f "$CADDY_COMPOSE")
  if [ -f "$OVERLAY_DEST" ]; then
    _compose+=(-f "$OVERLAY_DEST")
  fi
  # Compose returns before Caddy is ready. BusyBox wget ships in caddy:2-alpine;
  # probe inside the service because its admin port is not published on the host.
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "${_compose[@]}" exec -T caddy wget -q -T 1 -O /dev/null \
      http://127.0.0.1:2019/config/ 9>&-; then
      return 0
    fi
    if [ "$_attempt" -lt 10 ]; then
      sleep 1
    fi
  done
  echo "ERROR: Caddy admin endpoint not ready after 10 attempts" >&2
  return 1
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
  default_health || return 1
  if [ -z "$APP_HEALTH_CMD" ]; then
    echo "ERROR: APP_HEALTH_CMD is required to check the live frontend and portal upstream" >&2
    return 1
  fi
  APP_HOSTNAME="$APP_HOSTNAME" "$APP_HEALTH_CMD" 9>&-
}

reclaim_rollback_snapshots() {
  # Called only after the activation journal is cleared; keep the current set
  # and leave operator files alone. Never prune recovery's active snapshots.
  local _snapshot _snapshot_name _stamp
  for _snapshot in "$ROLLBACK_DIR"/Caddyfile.* "$ROLLBACK_DIR"/www.* "$ROLLBACK_DIR"/docker-compose.app.yml.*; do
    _snapshot_name="${_snapshot##*/}"
    case "$_snapshot_name" in
      Caddyfile.*)
        _stamp="${_snapshot_name#Caddyfile.}"
        [ -f "$_snapshot" ] && [ ! -L "$_snapshot" ] || continue
        ;;
      www.*)
        _stamp="${_snapshot_name#www.}"
        [ -d "$_snapshot" ] && [ ! -L "$_snapshot" ] || continue
        ;;
      docker-compose.app.yml.*)
        _stamp="${_snapshot_name#docker-compose.app.yml.}"
        [ -f "$_snapshot" ] && [ ! -L "$_snapshot" ] || continue
        ;;
      *)
        continue
        ;;
    esac
    case "$_stamp" in ''|*[!0-9]*) continue ;; esac
    [ "$_stamp" != "$ts" ] || continue
    rm -rf -- "$_snapshot" || return 1
  done
  sync_path "$ROLLBACK_DIR"
}

if [ "$APPLY" -eq 1 ]; then
  # Refuse before creating the lock or performing recovery/staging mutations.
  guard_source_path CADDY_COMPOSE "$CADDY_COMPOSE" file
  APP_DEPLOY_LOCK_WAIT="${APP_DEPLOY_LOCK_WAIT:-30}"
  case "$APP_DEPLOY_LOCK_WAIT" in
    ''|*[!0-9]*) refuse "APP_DEPLOY_LOCK_WAIT must be a non-negative integer" ;;
  esac
  mkdir -p "$APP_ROOT"
  if ! command -v flock >/dev/null 2>&1; then
    refuse "flock is required for deploy lock ${DEPLOY_LOCK}"
  fi
  if ! exec 9>>"$DEPLOY_LOCK"; then
    refuse "could not open deployment lock ${DEPLOY_LOCK}"
  fi
  if ! flock -w "$APP_DEPLOY_LOCK_WAIT" 9; then
    exec 9>&-
    refuse "could not acquire deployment lock ${DEPLOY_LOCK} within ${APP_DEPLOY_LOCK_WAIT}s"
  fi
  # No staging, journal recovery, or live changes before the binding gate.
  # Preserve journal path validation before contacting a different project.
  if [ -e "$ACTIVATION_JOURNAL" ] || [ -L "$ACTIVATION_JOURNAL" ]; then
    load_activation_journal || refuse "could not inspect interrupted activation journal ${ACTIVATION_JOURNAL}"
  elif [ -n "${FRONTEND_DIST}" ]; then
    # Without recovery work, reject unsafe source paths before contacting Compose.
    guard_source_path FRONTEND_DIST "$FRONTEND_DIST" dir
  fi
  command -v docker >/dev/null 2>&1 || refuse "docker compose is required to apply the Caddy overlay and reload Caddy"
  docker compose version >/dev/null 2>&1 || refuse "docker compose is unavailable; cannot apply the Caddy overlay or reload Caddy"
  command -v jq >/dev/null 2>&1 || refuse "jq is required to verify the Caddyfile bind source"
  verify_caddyfile_binding
  if [ -f "$OVERLAY_DEST" ]; then
    verify_caddyfile_binding -f "$OVERLAY_DEST"
  fi
  render_overlay | verify_caddyfile_binding -f -
fi

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

# Recovery must not depend on the replacement build being available or valid.
if [ "$APPLY" -eq 1 ]; then
  if [ -z "${FRONTEND_DIST}" ]; then
    refuse "FRONTEND_DIST is required for --apply"
  fi
  guard_source_path FRONTEND_DIST "$FRONTEND_DIST" dir
elif [ -n "${FRONTEND_DIST}" ]; then
  guard_source_path FRONTEND_DIST "$FRONTEND_DIST" dir
fi

print_plan

if [ "$APPLY" -ne 1 ]; then
  echo "dry-run: no files changed"
  exit 0
fi

[ -f "$APP_SNIPPET" ] || refuse "APP_SNIPPET is missing: ${APP_SNIPPET}"
[ -f "$APP_OVERLAY" ] || refuse "APP_OVERLAY is missing: ${APP_OVERLAY}"
[ -f "$CADDY_COMPOSE" ] || refuse "CADDY_COMPOSE is missing: ${CADDY_COMPOSE}"
[ -f "$CADDYFILE" ] || refuse "CADDYFILE is missing: ${CADDYFILE}"
if [ -L "$CADDYFILE" ] || [ ! -f "$CADDYFILE" ]; then
  refuse "CADDYFILE must be a regular file: ${CADDYFILE}"
fi
[ -n "$APP_HEALTH_CMD" ] || refuse "APP_HEALTH_CMD is required to check the live frontend and portal upstream"

# Reject invalid source output before creating staging or rollback artifacts.
# The staged copy is validated again below in case FRONTEND_DIST changes.
if ! validate_frontend "$FRONTEND_DIST"; then
  exit 2
fi

STAGED_CADDY="${STAGING_DIR}/Caddyfile"
STAGED_WWW="${STAGING_DIR}/www"
STAGED_OVERLAY="${STAGING_DIR}/docker-compose.app.yml"
mkdir -p "$APP_ROOT" "$STAGING_DIR"

# Redirection would follow a stale symlink and could truncate the live config
# before strip_app_vhost reads it. Unlink stale symlinks, and refuse a hardlink
# (or identical path) to the live file before opening the staged destination.
if [ -L "$STAGED_CADDY" ]; then
  if ! rm -f -- "$STAGED_CADDY"; then
    refuse "cannot remove staged Caddy symlink: ${STAGED_CADDY}"
  fi
elif [ -e "$STAGED_CADDY" ]; then
  if [ "$STAGED_CADDY" -ef "$CADDYFILE" ]; then
    refuse "staged Caddy path is the same file as CADDYFILE: ${STAGED_CADDY}"
  fi
  if [ ! -f "$STAGED_CADDY" ]; then
    refuse "staged Caddy path is not a regular file: ${STAGED_CADDY}"
  fi
  if ! rm -f -- "$STAGED_CADDY"; then
    refuse "cannot remove stale staged Caddy file: ${STAGED_CADDY}"
  fi
fi

{
  strip_app_vhost "$CADDYFILE"
  printf '\n'
  render_snippet
  printf '\n'
} > "$STAGED_CADDY"

render_overlay > "$STAGED_OVERLAY"

rm -rf "$STAGED_WWW"
mkdir -p "$STAGED_WWW"
guard_source_path FRONTEND_DIST "$FRONTEND_DIST" dir
cp -a "${FRONTEND_DIST}/." "$STAGED_WWW/"

# Validate the private copy that will be promoted; external writers may change
# FRONTEND_DIST during deploy, but cannot change this staged snapshot.
if ! validate_frontend "$STAGED_WWW"; then
  if ! rm -rf -- "$STAGING_DIR"; then
    echo "ERROR: staged frontend validation failed and staging cleanup failed: ${STAGING_DIR}" >&2
  fi
  exit 2
fi

if ! validate_staged_caddy "$STAGED_CADDY"; then
  echo "ERROR: staged Caddy validation failed; live config left intact: ${CADDYFILE}" >&2
  rm -rf "$STAGING_DIR"
  exit 4
fi

guard_dest_path ROLLBACK_DIR "$ROLLBACK_DIR" dir
mkdir -p "$ROLLBACK_DIR"
ts="$(date +%s)"
# Separate snapshots even for deployments in the same second (or clock rollback).
while [ -e "${ROLLBACK_DIR}/Caddyfile.${ts}" ] || [ -e "${ROLLBACK_DIR}/www.${ts}" ] || [ -e "${ROLLBACK_DIR}/docker-compose.app.yml.${ts}" ]; do
  ts=$((ts + 1))
done
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

if ! apply_caddy_compose; then
  activation_fail "docker compose failed while applying the app portal mount"
fi
if ! reload_caddy; then
  activation_fail "caddy reload failed after host promote"
fi
if ! run_health; then
  activation_fail "health check failed after reload"
fi

clear_activation_journal
trap - ERR INT TERM
if ! reclaim_rollback_snapshots; then
  echo "ERROR: activation succeeded but rollback snapshot reclamation failed" >&2
  exit 6
fi

echo "applied: ${APP_HOSTNAME} -> ${APP_UPSTREAM}; frontend ${APP_WWW}; overlay ${OVERLAY_DEST}; rollback ${ROLLBACK_CADDY}; reload=ok health=ok"
echo "next: verify Caddy mounts ${APP_WWW} at /srv/app-portal; do not ship this vhost via the shared repo Caddyfile from this lane"
