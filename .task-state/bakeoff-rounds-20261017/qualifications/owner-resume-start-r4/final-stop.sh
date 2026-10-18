#!/usr/bin/env bash
# FUTURE normal ubuntu sudo execution; explicit immutable window handoff.
set -euo pipefail
umask 077
A=${1:?exact protected procedure directory required}
W=${2:?exact window path required}
window_id=${3:?exact immutable window ID required}
test "$(sudo -n python3 -B "$A/owner-window.py" id "$W")" = "$window_id"
released=0
cleanup() {
 code=$?
 trap - EXIT HUP INT TERM
 if [[ "$released" != 1 ]]; then
  if release_op=$(sudo -n timeout 75s python3 -B "$A/owner-window.py" withdraw "$W" "$window_id"); then
   if [[ "$release_op" != none ]]; then
    release_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" auto)
    sudo -n timeout 190s python3 -B "$A/observe.py" "$W/ops/$release_op/publication.json" "$release_out" auto \
     || printf 'Owned AUTO consumption unknown; preserve receipts.\n' >&2
   fi
  else
   printf 'Withdrawal refused/unknown; preserve foreign state or guardian/fences/custody.\n' >&2
  fi
 fi
 printf 'Final-stop exact window: %s; window_id=%s; exit=%s\n' "$W" "$window_id" "$code"
 exit "$code"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
previous=$(sudo -n timeout 35s python3 -B "$A/owner-window.py" reconcile "$W" "$window_id")
test "$previous" != none
stop_op=$(sudo -n timeout 45s python3 -B "$A/owner-window.py" stop "$W" "$previous")
stop_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" stop)
sudo -n timeout 190s python3 -B "$A/observe.py" "$W/ops/$stop_op/publication.json" "$stop_out" stop
release_op=$(sudo -n timeout 45s python3 -B "$A/owner-window.py" auto "$W" "$stop_op")
release_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" auto)
sudo -n timeout 190s python3 -B "$A/observe.py" "$W/ops/$release_op/publication.json" "$release_out" auto
released=1
