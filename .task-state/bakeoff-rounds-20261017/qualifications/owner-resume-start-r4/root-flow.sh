#!/usr/bin/env bash
# FUTURE operator execution only, under normal ubuntu on acx-backend.
set -euo pipefail
umask 077
A=${1:?exact protected procedure directory required}
W=$(sudo -n python3 -B "$A/owner-window.py" new-window)
window_id=$(sudo -n python3 -B "$A/owner-window.py" id "$W")
finished=0
cleanup() {
 code=$?
 trap - EXIT HUP INT TERM
 if [[ "$finished" != 1 ]]; then
  # Reconcile EVERY operation in this exact window before choosing a candidate.
  # Client failure never leaves a stale shell variable as withdrawal authority.
  if release_op=$(sudo -n timeout 75s python3 -B "$A/owner-window.py" withdraw "$W" "$window_id"); then
   if [[ "$release_op" != none ]]; then
    release_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" auto)
    sudo -n timeout 190s python3 -B "$A/observe.py" "$W/ops/$release_op/publication.json" "$release_out" auto \
     || printf 'AUTO consumption unknown; retain exact window and guardian custody.\n' >&2
   fi
  else
   printf 'Owned withdrawal unresolved; no further publication; preserve guardian/fences/custody.\n' >&2
  fi
 fi
 printf 'Operator window: %s; window_id=%s; procedure=%s; exit=%s; finished=%s\n' "$W" "$window_id" "$A" "$code" "$finished"
 exit "$code"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
# Offline existing trust only. No connection and no key creation.
sudo -n -H -u ubuntu timeout 10s ssh-keygen -F 10.0.1.9 \
 -f /home/ubuntu/.ssh/known_hosts > /dev/null
sudo -n timeout 45s python3 -B "$A/owner-window.py" inspect "$W"
# Review saved source/config, loads and boot effects before this publication.
start_op=$(sudo -n timeout 45s python3 -B "$A/owner-window.py" start "$W" -)
start_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" start)
sudo -n timeout 310s python3 -B "$A/observe.py" "$W/ops/$start_op/publication.json" "$start_out" start
sudo -n python3 -B - "$start_out/start-observed.json" <<'PY'
import json,sys,datetime,time
s=json.load(open(sys.argv[1]))['state']
assert s['instance_id']=='ocid1.instance.oc1.iad.anuwcljt2mcagaqcoop3g4euuthldjy6wbrhmh5yfjgznxdg353urol27bfa', 'alternate winner: no guest probe'
assert datetime.datetime.fromisoformat(s['lease_expires_at'].replace('Z','+00:00')).timestamp()-time.time()>=180, 'insufficient remaining power lease'
PY
capacity_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" start)
sudo -n timeout 120s bash "$A/capacity-read.sh" "$start_out/start-observed.json" "$capacity_out" "$A"
sudo -n timeout 10s python3 -B - "$start_out/start-observed.json" "$capacity_out" "$A" <<'PY'
import hashlib,importlib.util,json,os,pathlib,sys
receipt,out,procedure=sys.argv[1:]
spec=importlib.util.spec_from_file_location('capacity_receipt_custody',pathlib.Path(procedure)/'owner-custody.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
fd=c.directory(out,0)
try:
 result=c.load_json(fd,'capacity-result.json');bound=c.load_json(fd,'capacity-input.json')
 rp=pathlib.Path(receipt);rfd=c.directory(rp.parent,0)
 try: raw=c.read_at(rfd,rp.name,0)
 finally: os.close(rfd)
 approved=c.directory(procedure,0)
 try: pins=json.loads(c.read_at(approved,'approved-scripts.json',0,sealed=True))
 finally: os.close(approved)
 assert result['status']=='complete' and result['native_children_reaped'] is True
 assert result['source_receipt_sha256']==bound['source_receipt_sha256']==hashlib.sha256(raw).hexdigest()
 assert result['classification']==bound['classification']==json.loads(raw)['capacity_observation']
 assert result['guest_sha256']==bound['guest_sha256']==pins['guest-read.sh']
 attempts=result['attempts'];assert 1<=len(attempts)<=3 and attempts[-1]['exit_code']==0
 assert all(a['native_reaped'] is True for a in attempts)
 print('Capacity receipt:',out+'/capacity-result.json',result['classification'])
finally: os.close(fd)
PY
# Do not start/stop/reconfigure a guest service, run inference, hash weights or benchmark.
withdraw_op=$(sudo -n timeout 45s python3 -B "$A/owner-window.py" auto "$W" "$start_op")
withdraw_out=$(sudo -n python3 -B "$A/owner-window.py" outdir "$W" auto)
sudo -n timeout 190s python3 -B "$A/observe.py" "$W/ops/$withdraw_op/publication.json" "$withdraw_out" auto
# Root reviews the guest and withdrawal receipts before the separate final-stop block.
finished=1
printf 'Exact final handoff: procedure=%s window=%s window_id=%s\n' "$A" "$W" "$window_id"
