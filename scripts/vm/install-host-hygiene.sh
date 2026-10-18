#!/usr/bin/env bash
set -euo pipefail
[[ "$(timeout --kill-after=2s 10s id -u)" == 0 ]] || {
  printf 'install-host-hygiene: run as root\n' >&2
  exit 1
}
action=${1:-install}
[[ $# -le 1 && ( "$action" == install || "$action" == --uninstall ) ]] || {
  printf 'usage: install-host-hygiene.sh [--uninstall]\n' >&2
  exit 2
}
etc_root=${HYGIENE_ETC_ROOT:-/etc}
usr_root=${HYGIENE_USR_ROOT:-/usr}
unit_root=$etc_root/systemd/system
journal_root=$etc_root/systemd/journald.conf.d
journal=$journal_root/60-acx-size.conf
pending=$journal_root/.acx-size-restart-pending
binary=$usr_root/local/sbin/acx-host-hygiene
defaults=$etc_root/default/acx-host-hygiene
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/host-hygiene.sh

systemctl_bounded() { timeout --kill-after=5s 60s systemctl "$@"; }

# RES-20, RES-25: each atomic writer owns its temporary file on every exit.
write_declared() (
  target=$1
  mode=$2
  mkdir -p -- "$(dirname -- "$target")"
  temporary=$(mktemp "$(dirname -- "$target")/.acx-hygiene.XXXXXX")
  trap 'rm -f -- "$temporary"' EXIT
  cat >"$temporary"
  chmod "$mode" "$temporary"
  if [[ -f "$target" ]] && cmp -s -- "$temporary" "$target"; then
    chmod "$mode" "$target"
  else
    mv -f -- "$temporary" "$target"
  fi
)

if [[ "$action" == --uninstall ]]; then
  # RLSE-08: stop producers before removing their declared state.
  if [[ -f "$unit_root/acx-host-hygiene.timer" ]]; then
    systemctl_bounded disable --now acx-host-hygiene.timer
  fi
  if [[ -f "$unit_root/acx-host-hygiene.service" ]]; then
    systemctl_bounded stop acx-host-hygiene.service
  fi
  if [[ -f "$journal" ]]; then
    touch "$pending"
  fi
  rm -f -- "$binary" "$defaults" "$journal" \
    "$unit_root/acx-host-hygiene.service" "$unit_root/acx-host-hygiene.timer"
  systemctl_bounded daemon-reload
  if [[ -f "$pending" ]]; then
    systemctl_bounded restart systemd-journald
    rm -f -- "$pending"
  fi
  printf 'host-hygiene uninstalled\n'
  exit 0
fi

[[ -f "$src" ]] || { printf 'install-host-hygiene: missing sweep\n' >&2; exit 1; }
write_declared "$binary" 0755 <"$src"
write_declared "$unit_root/acx-host-hygiene.service" 0644 <<'UNIT'
[Unit]
Description=Bounded ACX host disk hygiene

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/sbin/acx-host-hygiene
Nice=19
IOSchedulingClass=idle
TimeoutStartSec=1800
UNIT
write_declared "$unit_root/acx-host-hygiene.timer" 0644 <<'TIMER'
[Unit]
Description=Daily ACX host disk hygiene

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1h
Unit=acx-host-hygiene.service

[Install]
WantedBy=timers.target
TIMER
if [[ ! -e "$defaults" ]]; then
  write_declared "$defaults" 0644 <<'DEFAULTS'
# /tmp is held until the operator explicitly selects delete.
ACX_HYGIENE_TMP_MODE=report
DEFAULTS
fi
mkdir -p -- "$journal_root"
if [[ ! -f "$journal" ]] || ! cmp -s -- "$journal" <(printf '[Journal]\nSystemMaxUse=512M\n'); then
  touch "$pending"
fi
write_declared "$journal" 0644 <<'JOURNAL'
[Journal]
SystemMaxUse=512M
JOURNAL
systemctl_bounded daemon-reload
if [[ -f "$pending" ]]; then
  systemctl_bounded restart systemd-journald
  rm -f -- "$pending"
fi
systemctl_bounded enable --now acx-host-hygiene.timer
printf 'host-hygiene installed (tmp defaults to report)\n'
