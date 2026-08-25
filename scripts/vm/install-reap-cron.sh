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
entry='17 6 * * 1 $HOME/bin/reap-lane.sh --yes --all $HOME/w3 >> $HOME/reap-lane.log 2>&1'

current="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "$current" | grep -F "$marker" >/dev/null 2>&1; then
  crontab -l
  exit 0
fi
if [[ -n "$current" ]] && printf '%s\n' "$current" | grep -F "$entry" >/dev/null 2>&1; then
  crontab -l
  exit 0
fi

{
  if [[ -n "$current" ]]; then
    printf '%s\n' "$current"
  fi
  printf '%s\n' "$marker" "$entry"
} | crontab -

crontab -l
