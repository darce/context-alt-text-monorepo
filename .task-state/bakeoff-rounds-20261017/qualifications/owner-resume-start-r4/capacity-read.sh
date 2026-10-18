#!/usr/bin/env bash
# FUTURE root caller: exact start-observed.json, fresh protected outdir, staged procedure.
# Root holds approved bytes; ubuntu receives script stdin, never a root-only path.
set -euo pipefail
umask 077
exec python3 -B - "$@" <<'PY'
import datetime,hashlib,importlib.util,json,math,os,pathlib,signal,stat,subprocess,sys,time
receipt,out,procedure=sys.argv[1:]
assert os.geteuid()==0,'normal ubuntu sudo required'
# This client has a finite wait. A detached read-only guardian retains held
# identities and any unresolved native child/I/O after timeout or client death.
cancelled=False
cancel_r,cancel_w=os.pipe2(os.O_CLOEXEC|os.O_NONBLOCK)
def cancel(signum,frame):
 global cancelled
 cancelled=True
 try: os.write(cancel_w,b'1')
 except OSError: pass
for sig in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM): signal.signal(sig,cancel)
child=os.fork()
if child:
 os.close(cancel_r)
 deadline=time.monotonic()+112
 while time.monotonic()<deadline:
  found,status=os.waitpid(child,os.WNOHANG)
  if found:
   raise SystemExit(130 if cancelled else os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 70)
  if cancelled: break
  time.sleep(.1)
 # Closing this owned pipe requests cancellation without a PID-based signal.
 # EOF/client death is never native completion proof.
 os.close(cancel_w)
 print('capacity client unknown/cancelled; retain exact output and guardian custody: '+out,file=sys.stderr)
 raise SystemExit(130 if cancelled else 124)
os.close(cancel_w)
os.setsid()
# A dead caller cannot keep the guardian attached to its output transport.
null=os.open('/dev/null',os.O_RDWR)
for fd in (0,1,2): os.dup2(null,fd)
if null>2: os.close(null)
def cancel_guardian(signum,frame):
 global cancelled
 cancelled=True
for sig in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM): signal.signal(sig,cancel_guardian)
def cancellation():
 global cancelled
 try:
  os.read(cancel_r,1)
  cancelled=True  # byte or EOF: caller cancelled/disappeared
 except BlockingIOError: pass
 return cancelled
fds=[cancel_r]; ofd=None; fresh=False; native_pending=False
try:
 A=pathlib.Path(procedure)
 spec=importlib.util.spec_from_file_location('capacity_custody',A/'owner-custody.py')
 c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
 afd=c.directory(A,0);fds.append(afd)
 ofd=c.directory(out,0);fds.append(ofd)
 assert not os.listdir(ofd),'fresh exclusive capacity output directory required'
 fresh=True
 c.seal(ofd,'capacity-custody.json',dict(guardian_pid=os.getpid(),receipt=receipt,procedure=procedure,output=out))
 rp=pathlib.Path(receipt);assert rp.name=='start-observed.json','exact START receipt required'
 rfd=c.directory(rp.parent,0);fds.append(rfd)
 raw=c.read_at(rfd,rp.name,0);j=json.loads(raw);s=j['state'];mode=j['capacity_observation']
 assert s['instance_id']=='ocid1.instance.oc1.iad.anuwcljt2mcagaqcoop3g4euuthldjy6wbrhmh5yfjgznxdg353urol27bfa','alternate winner: no guest probe'
 assert mode in ('capacity-entry-candidate/NOTrawready','failure-diagnostic/NOTrawready'),'no capacity entry candidate'
 expires=datetime.datetime.fromisoformat(s['lease_expires_at'].replace('Z','+00:00'))
 assert expires.tzinfo is not None and math.isfinite(expires.timestamp()) and expires.timestamp()-time.time()>=180,'insufficient remaining power lease'
 pins=json.loads(c.read_at(afd,'approved-scripts.json',0,sealed=True))
 assert set(pins)=={'owner-window.py','owner-custody.py','observe.py','capacity-read.sh','guest-read.sh','root-flow.sh','final-stop.sh'},'approved staging manifest incomplete'
 # Hold this no-follow root-owned sealed descriptor until all native attempts
 # are reaped. Read and hash THESE bytes before passing them to ubuntu stdin.
 probe=os.open('guest-read.sh',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=afd);fds.append(probe)
 ps=os.fstat(probe)
 assert stat.S_ISREG(ps.st_mode) and ps.st_uid==0 and ps.st_nlink==1 and stat.S_IMODE(ps.st_mode)==0o400 and ps.st_size<=c.MAX,'unsafe staged guest script'
 guest=b''
 while len(guest)<=c.MAX:
  part=os.read(probe,min(65536,c.MAX+1-len(guest)))
  if not part: break
  guest+=part
 assert len(guest)<=c.MAX and hashlib.sha256(guest).hexdigest()==pins['guest-read.sh'],'guest script hash mismatch'
 c.seal(ofd,'capacity-input.json',dict(source_receipt=receipt,source_receipt_sha256=hashlib.sha256(raw).hexdigest(),start_observation=j,guest_sha256=pins['guest-read.sh'],classification=mode))
 attempts=[];last=1
 for attempt in (1,2,3):
  if cancellation(): last=130;break
  handles=[]
  for suffix in ('stdout','stderr'):
   fd=os.open('guest-attempt-%d.%s'%(attempt,suffix),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=ofd);handles.append(fd);fds.append(fd)
  # At most 3*(30+2)+2*5=106s; client112s and outer120s remain finite.
  native_pending=True  # even a spawn exception can leave native completion unknown
  p=subprocess.Popen(['sudo','-n','-H','-u','ubuntu','timeout','--signal=TERM','--kill-after=2s','30s','bash'],stdin=subprocess.PIPE,stdout=handles[0],stderr=handles[1],start_new_session=True,close_fds=True)
  c.seal(ofd,'guest-attempt-%d.launched.json'%attempt,dict(pid=p.pid,diagnostic_only=True))
  try: p.communicate(input=guest,timeout=34)
  except subprocess.TimeoutExpired:
   # No retry or completion claim until THIS native child has been reaped.
   # Its timeout may itself be blocked in I/O. Keep all handles and guardian.
   cancelled=True
   while p.poll() is None: time.sleep(.2)
   p.communicate()
  assert p.returncode is not None
  native_pending=False  # communicate/poll reaped this exact native child
  last=p.returncode if p.returncode>=0 else 128-p.returncode
  for fd in handles: os.fsync(fd);os.fchmod(fd,0o400);os.fsync(fd)
  c.seal(ofd,'guest-attempt-%d.exit.json'%attempt,dict(exit_code=last,native_reaped=True))
  attempts.append(dict(attempt=attempt,exit_code=last,native_reaped=True))
  if last==0 or cancellation(): break
  if attempt!=3:
   end=time.monotonic()+5
   while time.monotonic()<end and not cancellation(): time.sleep(min(.1,max(0,end-time.monotonic())))
 complete=last==0 and not cancellation()
 c.seal(ofd,'capacity-result.json',dict(status='complete' if complete else 'unknown',classification=mode,source_receipt_sha256=hashlib.sha256(raw).hexdigest(),guest_sha256=pins['guest-read.sh'],attempts=attempts,native_children_reaped=True))
 for fd in reversed(fds): os.close(fd)
 os._exit(0 if complete else 130 if cancelled else last)
except OSError:
 # Unknown I/O does not release held identities or certify native completion.
 while True: time.sleep(1)
except BaseException as exc:
 if native_pending:
  # An unexpected post-spawn exception is not proof that its child stopped.
  while True: time.sleep(1)
 # Validation failure has no guest effect; keep any exclusive refusal receipt.
 if ofd is not None and fresh:
  try: c.seal(ofd,'capacity-refused.json',dict(kind=type(exc).__name__,detail=str(exc)))
  except OSError:
   while True: time.sleep(1)
 os._exit(65)
PY
