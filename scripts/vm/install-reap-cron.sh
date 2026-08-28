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
cp "$src" "$HOME/bin/reap-lane.sh"
chmod +x "$HOME/bin/reap-lane.sh"

marker='# acx-reap-lane'
# Every root that accumulates lane clones. Kept in step with REAP_LANE_ROOTS in
# reap-lane.sh; the sweep is only as wide as the narrower of the two.
# shellcheck disable=SC2016  # $HOME must stay literal: cron expands it, not us.
roots='$HOME/w3 $HOME/uxw2 $HOME/l1 $HOME/w $HOME/lanes'
all_args=''
for r in $roots; do
  all_args="${all_args}--all ${r} "
done
entry="17 6 * * 1 \$HOME/bin/reap-lane.sh --yes ${all_args}>> \$HOME/reap-lane.log 2>&1"

# Replace any previous acx-reap-lane block rather than treating its presence as
# "already installed". The VM was carrying an entry that swept one root of five;
# a marker check that no-ops means widening the roots never reaches the machine.
current="$(crontab -l 2>/dev/null || true)"
{
  if [[ -n "$current" ]]; then
    printf '%s\n' "$current" | awk -v m="$marker" '
      $0 == m { skip = 1; next }
      skip && $0 ~ /reap-lane\.sh/ { skip = 0; next }
      { skip = 0; print }
    '
  fi
  printf '%s\n' "$marker" "$entry"
} | crontab -

crontab -l
