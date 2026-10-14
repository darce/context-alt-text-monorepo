#!/usr/bin/env bash
# Converge the invoking user's reap-lane cron entries. [RES-25][RLSE-11]
set -euo pipefail

: "${HOME:?HOME must be set}"

src="$(cd "$(dirname "$0")" && pwd)/reap-lane.sh"
if [[ ! -f "$src" ]]; then
  echo "install-reap-cron: missing $src" >&2
  exit 1
fi

stage="$(mktemp -d "${TMPDIR:-/tmp}/install-reap-cron.XXXXXX")"
install_tmp=""
wrapper_tmp=""
trap 'rm -rf "$stage"; rm -f -- "${install_tmp:-}" "${wrapper_tmp:-}"' EXIT
cp "$src" "$stage/reap-lane.sh"
# Validate the exact copy to install before changing any declared host state.
if ! grep -Eq '^[[:space:]]*(function[[:space:]]+)?lane_has_live_process[[:space:]]*\(\)[[:space:]]*\{' "$stage/reap-lane.sh"; then
  echo 'install-reap-cron: reap-lane.sh lacks lane_has_live_process; refusing installation' >&2
  exit 1
fi

remote_agent_ttl="${WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC-3600}"
if [[ ! "$remote_agent_ttl" =~ ^[0-9]+$ ]]; then
  echo 'install-reap-cron: WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC must be an integer >= 900' >&2
  exit 1
fi
# Strip leading zeroes without arithmetic overflow or octal interpretation.
remote_agent_ttl="${remote_agent_ttl#"${remote_agent_ttl%%[!0]*}"}"
if [[ ${#remote_agent_ttl} -lt 3 ]] || [[ ${#remote_agent_ttl} -eq 3 && "$remote_agent_ttl" < 900 ]]; then
  echo 'install-reap-cron: WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC must be an integer >= 900' >&2
  exit 1
fi
if [[ "${WORKBAY_REMOTE_AGENT_ROOT:-}" == *$'\n'* || "${WORKBAY_REMOTE_AGENT_ROOT:-}" == *$'\r'* ]]; then
  echo 'install-reap-cron: WORKBAY_REMOTE_AGENT_ROOT must fit on one crontab line' >&2
  exit 1
fi

if crontab -l >"$stage/current" 2>"$stage/crontab-error"; then
  :
else
  crontab_status=$?
  crontab_diagnostic="$(cat "$stage/crontab-error")"
  case "$crontab_diagnostic" in
    no\ crontab\ for\ *|crontab:\ no\ crontab\ for\ *) : >"$stage/current" ;;
    *)
      if [[ -n "$crontab_diagnostic" ]]; then
        printf '%s\n' "$crontab_diagnostic" >&2
      else
        echo "install-reap-cron: crontab -l failed with status $crontab_status" >&2
      fi
      exit "$crontab_status"
      ;;
  esac
fi

marker='# acx-reap-lane'
# Every root that accumulates lane clones. Kept in step with REAP_LANE_ROOTS in
# reap-lane.sh; the sweep is only as wide as the narrower of the two.
#
# These are $HOME-relative and this installer writes the crontab of the invoking
# user, so the cron only ever reaches lanes owned by whoever runs it. [RES-07]
# Run this installer as EACH user that owns lane roots.
# shellcheck disable=SC2016  # $HOME must stay literal: cron expands it, not us.
roots='w3 uxw2 l1 w lanes grok-sandbox'
all_args=""
for r in $roots; do
  all_args="${all_args} --all \"\$HOME/${r}\""
done
cron_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\$/\\\$}"
  value="${value//\`/\\\`}"
  # crontab(5) rewrites an unescaped % into a newline before /bin/sh runs.
  value="${value//%/\\%}"
  printf '"%s"' "$value"
}

entry="17 * * * * \"\$HOME/bin/reap-lane.sh.cron\" home --yes --archive-to \"\$HOME/lane-archive.git\"${all_args}"
remote_entry=""
if [[ -n "${WORKBAY_REMOTE_AGENT_ROOT:-}" ]]; then
  remote_root="$(cron_quote "$WORKBAY_REMOTE_AGENT_ROOT")"
  remote_entry="23 * * * * WORKBAY_REMOTE_AGENT_ROOT=${remote_root} WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC=${remote_agent_ttl} \"\$HOME/bin/reap-lane.sh.cron\" remote --yes --archive-to \"\$HOME/lane-archive.git\" --all ${remote_root}"
fi

# Own hand-added invocations too; preserve all unrelated comments and blank
# lines, including trailing blank lines lost by command substitution. [RES-25]
{
  awk -v m="$marker" '
    function before_comment(line, i, c, quote, escaped) {
      for (i = 1; i <= length(line); i++) {
        c = substr(line, i, 1)
        if (escaped) { escaped = 0; continue }
        if (c == "\\" && quote != "\047") { escaped = 1; continue }
        if (quote != "") {
          if (c == quote) quote = ""
          continue
        }
        if (c == "\047" || c == "\"") { quote = c; continue }
        if (c == "#" && (i == 1 || substr(line, i - 1, 1) ~ /[[:space:];&|]/))
          return substr(line, 1, i - 1)
      }
      return line
    }
    $0 == m { next }
    /^[[:space:]]*#/ { print; next }
    before_comment($0) ~ /(^|[[:space:]\/"\047(;&|])reap-lane[.]sh([.]cron)?($|[[:space:])"\047;&|])/ { next }
    { print }
  ' "$stage/current"
  printf '%s\n' "$marker" "$entry"
  if [[ -n "$remote_entry" ]]; then printf '%s\n' "$remote_entry"; fi
} >"$stage/target-crontab"

cat >"$stage/reap-lane.sh.cron" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  home) unset WORKBAY_REMOTE_AGENT_ROOT WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC ;;
  remote) ;;
  *) echo 'reap-lane: invalid cron sweep mode' >&2; exit 2 ;;
esac
shift
log="$HOME/reap-lane.log"
# Keep the lock in this scope: the reaper reuses descriptor 9. [RES-20]
exec 9>"$HOME/.reap-lane.cron.lock"
lock_status=0
flock -n -E 75 9 || lock_status=$?
if [[ "$lock_status" -eq 75 ]]; then
  printf '%s\n' 'reap-lane: skipped, previous sweep still running' >>"$log"
  exit 0
fi
if [[ "$lock_status" -ne 0 ]]; then exit "$lock_status"; fi
# One generation bounds steady-state log growth. [RES-07]
if [[ -f "$log" ]] && [[ "$(stat -c %s -- "$log")" -gt 33554432 ]]; then
  mv -f -- "$log" "$log.1"
fi
# Cron must observe the reaper's status, including freshness alert 4.
reaper_status=0
"$HOME/bin/reap-lane.sh" "$@" >>"$log" 2>&1 || reaper_status=$?
exit "$reaper_status"
WRAPPER

# This may be the only copy of a reaped lane's history; never re-init it.
archive="$HOME/lane-archive.git"
if ! git -C "$archive" rev-parse --is-bare-repository >/dev/null 2>&1; then
  git init --bare --quiet "$archive"
fi
mkdir -p "$HOME/bin"
install_tmp="$(mktemp "$HOME/bin/.reap-lane.sh.XXXXXX")"
wrapper_tmp="$(mktemp "$HOME/bin/.reap-lane.sh.cron.XXXXXX")"
cp "$stage/reap-lane.sh" "$install_tmp"
cp "$stage/reap-lane.sh.cron" "$wrapper_tmp"
chmod +x "$install_tmp" "$wrapper_tmp"
mv -f "$install_tmp" "$HOME/bin/reap-lane.sh"
mv -f "$wrapper_tmp" "$HOME/bin/reap-lane.sh.cron"
crontab - <"$stage/target-crontab"

crontab -l
