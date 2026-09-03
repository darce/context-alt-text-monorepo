#!/usr/bin/env bash
# Idempotently install the weekly reap-lane cron entry for the invoking user.
set -euo pipefail

: "${HOME:?HOME must be set}"

src="$(cd "$(dirname "$0")" && pwd)/reap-lane.sh"
if [[ ! -f "$src" ]]; then
  echo "install-reap-cron: missing $src" >&2
  exit 1
fi

mkdir -p "$HOME/bin"
install_tmp="$(mktemp "$HOME/bin/.reap-lane.sh.XXXXXX")"
trap 'rm -f "$install_tmp"' EXIT
cp "$src" "$install_tmp"
chmod +x "$install_tmp"
mv -f "$install_tmp" "$HOME/bin/reap-lane.sh"
trap - EXIT

marker='# acx-reap-lane'
# Every root that accumulates lane clones. Kept in step with REAP_LANE_ROOTS in
# reap-lane.sh; the sweep is only as wide as the narrower of the two.
#
# These are $HOME-relative and this installer writes the crontab of the invoking
# user, so the cron only ever reaches lanes owned by whoever runs it. [RES-07]
# offload lanes live under the `gate` user's ~/grok-sandbox; a cron installed as
# `ubuntu` reported success weekly while 60G of gate-owned lanes accumulated
# untouched. Run this installer as EACH user that owns lane roots.
# shellcheck disable=SC2016  # $HOME must stay literal: cron expands it, not us.
roots='w3 uxw2 l1 w lanes grok-sandbox'
all_args=""
for r in $roots; do
  all_args="${all_args} --all \"\$HOME/${r}\""
done
# The keep-repo. Ancestry alone skips every lane of a squash- or rebase-merged
# wave, so a guarded-only sweep frees nothing; archiving the commits first makes
# deleting the checkout lossless. Never re-init: for a reaped lane these refs
# may be the only copy of its history.
archive="$HOME/lane-archive.git"
if ! git -C "$archive" rev-parse --is-bare-repository >/dev/null 2>&1; then
  git init --bare --quiet "$archive"
fi

# Do not mask reap-lane.sh's status: exit 4 is the freshness alert when a
# pressured sweep sees candidates but reclaims none. Cron must observe it.
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

remote_agent_env=""
if [[ -n "${WORKBAY_REMOTE_AGENT_ROOT:-}" ]]; then
  remote_agent_env="WORKBAY_REMOTE_AGENT_ROOT=$(cron_quote "$WORKBAY_REMOTE_AGENT_ROOT") "
fi
entry="17 6 * * 1 ${remote_agent_env}\"\$HOME/bin/reap-lane.sh\" --yes --archive-to \"\$HOME/lane-archive.git\"${all_args} >> \"\$HOME/reap-lane.log\" 2>&1"

# Replace any previous acx-reap-lane block rather than treating its presence as
# "already installed". The VM was carrying an entry that swept one root of five;
# a marker check that no-ops means widening the roots never reaches the machine.
crontab_error="$(mktemp "${TMPDIR:-/tmp}/reap-crontab-error.XXXXXX")"
trap 'rm -f "$crontab_error"' EXIT
if current="$(crontab -l 2>"$crontab_error")"; then
  :
else
  crontab_status=$?
  crontab_diagnostic="$(cat "$crontab_error")"
  case "$crontab_diagnostic" in
    no\ crontab\ for\ *|crontab:\ no\ crontab\ for\ *) current="" ;;
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
rm -f "$crontab_error"
trap - EXIT
{
  if [[ -n "$current" ]]; then
    printf '%s\n' "$current" | awk -v m="$marker" '
      $0 == m { skip = 1; next }
      skip && $0 ~ /^[[:space:]]*(#.*)?$/ { next }
      skip && $0 ~ /reap-lane\.sh/ { skip = 0; next }
      { skip = 0; print }
    '
  fi
  printf '%s\n' "$marker" "$entry"
} | crontab -

crontab -l
