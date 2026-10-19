#!/usr/bin/python3
"""NEW benchmark-owned procedural producer, not an installed API extension.

CLI is implemented by owner-window.py. These functions have no cloud/API calls.
All live paths are supplied only by its fixed Production configuration.
"""
import ast,errno,fcntl,hashlib,importlib.util,json,os,pathlib,select,signal,stat,subprocess,sys,time,uuid
from datetime import UTC,datetime,timedelta
P=pathlib.Path
ENVS=('dev','dev-fir','prod','staging','dev-auraface')
PIN='54f7bd837f20c24529ce3e1ea53e91a405b16234c62092890c22b507c149a2d9'
LOAD_PIN='0d08441a76a5f9f5c38ac32c3b4dd7956de07af3255fb31748bef36b5da26521'
MAX=1048576
SCRIPTS=frozenset(('owner-window.py','owner-custody.py','observe.py','capacity-read.sh','guest-read.sh','root-flow.sh','final-stop.sh'))

def check(condition,message):
 if not condition: raise RuntimeError(message)

def directory(path,uid):
 """Walk without following links; return held identity, never resolve aliases."""
 p=P(path); check(p.is_absolute() and '..' not in p.parts,'absolute canonical custody path required')
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
 system_uid=os.fstat(fd).st_uid  # filesystem-root identity in this native namespace
 try:
  for component in p.parts[1:]:
   nxt=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
   s=os.fstat(nxt)
   safe=s.st_uid in (system_uid,uid) and not s.st_mode&0o022
   sticky=s.st_uid==system_uid and bool(s.st_mode&stat.S_ISVTX) and stat.S_IMODE(s.st_mode)==0o1777
   if not (safe or sticky): os.close(nxt); raise RuntimeError('unsafe custody ancestor')
   os.close(fd); fd=nxt
  s=os.fstat(fd); check(s.st_uid==uid and stat.S_IMODE(s.st_mode)==0o700,'expected-owner private directory required')
  return fd
 except BaseException:
  os.close(fd); raise

def read_at(fd,name,uid=None,sealed=False):
 check('/' not in name and name not in ('.','..'),'simple basename required')
 f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
 try:
  s=os.fstat(f); check(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=MAX,'regular bounded single-link file required')
  if uid is not None: check(s.st_uid==uid,'wrong receipt owner')
  if sealed: check(not s.st_mode&0o222,'receipt is mutable')
  b=b''
  while len(b)<=MAX:
   q=os.read(f,min(65536,MAX+1-len(b)))
   if not q: break
   b+=q
  check(len(b)<=MAX,'oversize receipt'); return b
 finally: os.close(f)

def seal(fd,name,value):
 b=json.dumps(value,sort_keys=True,indent=2).encode()+b'\n'
 f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=fd)
 try:
  view=memoryview(b)
  while view: view=view[os.write(f,view):]
  os.fsync(f); os.fchmod(f,0o400); os.fsync(f)
 finally: os.close(f)
 os.fsync(fd)

def subdir(fd,name,create=False):
 check('/' not in name and name not in ('.','..'),'simple directory name required')
 if create: os.mkdir(name,0o700,dir_fd=fd); os.fsync(fd)
 f=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
 s=os.fstat(f); check(s.st_uid==os.geteuid() and stat.S_IMODE(s.st_mode)==0o700,'unsafe owned subdirectory'); return f

def load_json(fd,name): return json.loads(read_at(fd,name,os.geteuid(),sealed=True))

def load_writer(writer_bytes,load_bytes):
 check(hashlib.sha256(writer_bytes).hexdigest()==PIN,'writer hash mismatch')
 check(hashlib.sha256(load_bytes).hexdigest()==LOAD_PIN,'load resolver hash mismatch')
 # Execute the COMPLETE unchanged writer with only its DB-heavy dependency
 # replaced by the exact pure resolver function extracted from its pinned source.
 import types
 dependency=types.ModuleType('scene.application.describe_load')
 tree=ast.parse(load_bytes)
 node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='resolve_load_path')
 dependency.__dict__.update(os=os,LOAD_PATH_ENV='ACX_DESCRIBE_LOAD_PATH',DEFAULT_LOAD_PATH='/run/acx/describe-load.json')
 exec(compile(ast.Module(body=[node],type_ignores=[]),'pinned-describe_load.py','exec'),dependency.__dict__)
 sys.modules[dependency.__name__]=dependency
 name='benchmark_owned_pinned_writer'; m=types.ModuleType(name); sys.modules[name]=m
 exec(compile(writer_bytes,'pinned-gpu_intent.py','exec'),m.__dict__); return m

def lock_path(path,deadline,group=None,existing=False):
 p=P(path)
 if existing:
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
 else:
  try:
   fd=os.open(p,os.O_RDONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o660)
   # Match native persistent-fence provisioning despite a private umask. Only
   # a newly/exclusively created fence is initialized; never chown/chmod an
   # existing or uncertain resource. Production group is native acxapi10001.
   if group is not None: os.fchown(fd,-1,group)
   os.fchmod(fd,0o660)
  except FileExistsError:
   fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(fd); check(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'unsafe persistent fence')
  while True:
   try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); break
   except BlockingIOError:
    check(time.monotonic()<deadline,'publication fence deadline'); time.sleep(.02)
  named=os.stat(p,follow_symlinks=False); check((named.st_dev,named.st_ino)==(s.st_dev,s.st_ino),'fence identity changed')
  return fd
 except BaseException: os.close(fd); raise

def unlock(fds):
 for fd in reversed(fds): fcntl.flock(fd,fcntl.LOCK_UN); os.close(fd)

class Paths:
 def __init__(self,runtime,store,lifecycle,markers,writer_uid=None,writer_gid=None,now=None):
  self.runtime=P(runtime); self.store=P(store); self.lifecycle=P(lifecycle); self.markers=P(markers)
  self.writer_uid=writer_uid; self.writer_gid=writer_gid; self.now=now
 @property
 def target(self): return self.runtime/'prod/gpu-intent.json'
 def fences(self,mode):
  # Existing units take lifecycle first. Public writers take one intent fence;
  # load publishers take one load fence. This helper never calls a locking
  # writer while holding that writer's nonreentrant flock.
  result=[self.lifecycle]
  result += [self.runtime/e/'gpu-intent.json.lock' for e in ENVS]
  if mode!='auto': result += [self.runtime/e/'describe-load.json.lock' for e in ENVS]
  result += [self.store/'.intent-authority.json.lock']
  return result

def bounded_json(path,optional=False):
 try:
  p=P(path); fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
 except FileNotFoundError:
  if optional: return None
  raise
 try:
  s=os.fstat(fd); check(stat.S_ISREG(s.st_mode) and s.st_size<=MAX,'unsafe source receipt')
  raw=os.read(fd,MAX+1); check(len(raw)<=MAX,'oversize source'); return json.loads(raw)
 finally: os.close(fd)

def view(paths,mode):
 a=bounded_json(paths.store/'intent-authority.json')
 pubs={str(p):bounded_json(p) for base in [paths.runtime,paths.store/'intents'] for p in sorted(base.glob('*/gpu-intent.json'))}
 loads=[] if mode=='auto' else [bounded_json(paths.runtime/e/'describe-load.json') for e in ENVS]
 return dict(authority=a,publications=pubs,loads=loads,deferred=bounded_json(paths.store/'deferred-stop.json',optional=True))

def known_candidates(wfd):
 checkpoint_ready(wfd)
 ops=subdir(wfd,'ops'); result={}
 try:
  names=bounded_names(ops,32,'operation budget exhausted')
  for name in names:
   check(str(uuid.UUID(name))==name,'unexpected operation directory')
   f=subdir(ops,name)
   try:
    try: result[name]=load_json(f,'candidate.json')
    except FileNotFoundError: pass
   finally: os.close(f)
 finally: os.close(ops)
 return result

def bounded_names(fd,limit,message):
 names=[]
 with os.scandir(fd) as entries:
  for entry in entries:
   check(len(names)<limit,message); names.append(entry.name)
 return sorted(names)

def identity(s):
 return dict(dev=s.st_dev,ino=s.st_ino,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode))

def proof_file(fd,name,mode=0o400,uid=None,durable=False):
 """Hash through one no-follow descriptor and verify its still-named identity."""
 check('/' not in name and name not in ('.','..'),'simple proof basename required')
 uid=os.geteuid() if uid is None else uid
 f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
 try:
  s=os.fstat(f)
  check(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==uid and stat.S_IMODE(s.st_mode)==mode and s.st_size<=MAX,'unsafe proof file: '+name)
  raw=b''
  while len(raw)<=MAX:
   chunk=os.read(f,min(65536,MAX+1-len(raw)))
   if not chunk: break
   raw+=chunk
  check(len(raw)==s.st_size and len(raw)<=MAX,'proof size changed: '+name)
  after=os.fstat(f); named=os.stat(name,dir_fd=fd,follow_symlinks=False)
  def stable(q): return (q.st_dev,q.st_ino,q.st_uid,q.st_gid,q.st_mode,q.st_nlink,q.st_size,q.st_mtime_ns,q.st_ctime_ns)
  check(stable(s)==stable(after)==stable(named),'proof identity changed: '+name)
  if durable: os.fsync(f)
  return raw,dict(identity(s),size=len(raw),sha256=hashlib.sha256(raw).hexdigest())
 finally: os.close(f)

def validate_procedure(wfd,window,procedure):
 """Only a protected, exact old-stage receipt can bridge a procedure mismatch.

 No receipt path/flag is accepted from a caller. The window's sealed procedure
 remains authoritative; old code is hashed, never imported or edited.
 """
 afd=directory(procedure,0)
 try:
  try: raw,_=proof_file(afd,'procedure-predecessor.json',uid=0)
  except FileNotFoundError:
   check(window['procedure']==str(P(procedure)),'window/procedure mismatch'); return
  check(window['procedure']!=str(P(procedure)),'extraneous procedure predecessor proof')
  receipt=json.loads(raw)
  fields={'schema','window_id','window_path','procedure','manifest_sha256','owner_window_sha256','owner_custody_sha256'}
  check(type(receipt) is dict and set(receipt)==fields and receipt['schema']=='acx-owner-procedure-predecessor/v1','bad procedure predecessor schema')
  check((receipt['window_id'],receipt['window_path'],receipt['procedure'])==(window['id'],window['path'],window['procedure']),'procedure predecessor binding mismatch')
  current=json.loads(proof_file(wfd,'window.json',uid=0)[0])
  check(current==window,'bound current window changed')
  old=directory(window['procedure'],0)
  try:
   check(set(bounded_names(old,8,'extraneous predecessor stage file'))==SCRIPTS|{'approved-scripts.json'},'predecessor stage inventory')
   manifest,mp=proof_file(old,'approved-scripts.json',uid=0); pins=json.loads(manifest)
   check(type(pins) is dict and set(pins)==SCRIPTS and mp['sha256']==receipt['manifest_sha256'],'predecessor manifest mismatch')
   for name in sorted(SCRIPTS):
    _,p=proof_file(old,name,uid=0)
    check(p['sha256']==pins[name],'predecessor script hash mismatch')
    if name in ('owner-window.py','owner-custody.py'):
     field='owner_window_sha256' if name=='owner-window.py' else 'owner_custody_sha256'
     check(p['sha256']==receipt[field],'predecessor helper hash mismatch')
   check(identity(os.fstat(old))==identity(os.stat(window['procedure'],follow_symlinks=False)),'predecessor stage identity changed')
  finally: os.close(old)
 finally: os.close(afd)

def checkpoint_ready(wfd):
 try: fd=subdir(wfd,'checkpoints')
 except FileNotFoundError: return
 try:
  try: os.stat('pending.json',dir_fd=fd,follow_symlinks=False)
  except FileNotFoundError: return
  raise RuntimeError('checkpoint pending; explicit exact-window checkpoint recovery required')
 finally: os.close(fd)

def require_idle_load(q,now):
 """Validate current producer evidence before START/STOP; AUTO never reads it.

 Counters/batch/time are required by the actual aggregate parser. Demand is
 additive (already included in in_flight); absent demand/revision and extra
 keys remain compatible. Explicit null demand is unknown, not measured zero.
 """
 import math
 check(type(q) is dict,'unknown load object')
 stamp=q.get('written_at')
 check(type(stamp) in (int,float) and math.isfinite(stamp),'unknown load timestamp')
 check(-5<=now-stamp<=120,'unknown/stale load')
 for field in ('queue_depth','in_flight'):
  value=q.get(field)
  check(type(value) is int and value>=0,'unknown load counter: '+field)
 check(type(q.get('batch_in_progress')) is bool,'unknown batch evidence')
 if 'lease_demand' in q:
  demand=q['lease_demand']
  check(type(demand) is int and demand>=0,'unknown lease demand')
 if 'revision' in q:
  revision=q['revision']
  check(type(revision) is int and revision>=1,'unknown load revision')
 check(q['queue_depth']==0 and q['in_flight']==0 and q['batch_in_progress'] is False and q.get('lease_demand',0)==0,'work/demand')

def guard(v,previous,known,actor,mode):
 a=v['authority']; high=a['highest_sequence']; check(type(high) is int and high>=0,'unknown authority')
 check(not a.get('rejected_sequences'),'authority rejection history')
 pubs=list(v['publications'].values())
 if previous is None:
  check(high==0 and not a['intents'] and not pubs and v['deferred'] is None,'first-use changed; preserve foreign state')
 else:
  check(previous in known.values(),'previous lacks immutable candidate custody')
  check(previous['requested_by']==actor,'other window')
  check(high<=previous['sequence'],'newer authority')
  check(pubs and previous in pubs,'previous publication is not currently persisted')
  check(all(p in known.values() and p['sequence']<=previous['sequence'] for p in pubs),'foreign publication')
  for nonce,record in a['intents'].items():
   if record['sequence']>previous['sequence']: raise RuntimeError('newer authority record')
   if record['sequence']==previous['sequence']:
    check(nonce==previous['nonce'] and record['publication']=={k:previous[k] for k in ('action','requested_at','expires_at','ttl_seconds','requested_by','sequence')},'conflicting authority')
  d=v['deferred']
  if d is not None: check(any(d['nonce']==p['nonce'] and d['sequence']==p['sequence'] and p['action']=='stop' for p in known.values()),'foreign deferred STOP')
 if mode!='auto':
  check(type(v['loads']) is list and len(v['loads'])==len(ENVS),'unknown required load inventory')
  now=time.time()
  for q in v['loads']: require_idle_load(q,now)
 return high

def native_job(fn,seconds,after=None,before=None):
 """One owned fork; reaping proves this native worker cannot publish later.

 Returns (wait status, JSON result). No IPC payload is accepted as authority.
 A stuck uninterruptible worker leaves the guardian alive holding its fences.
 """
 r,w=os.pipe2(os.O_CLOEXEC)
 gate_r,gate_w=os.pipe2(os.O_CLOEXEC) if before else (None,None)
 pid=os.fork()
 if pid==0:
  os.close(r)
  try:
   if before:
    os.close(gate_w)
    if not select.select([gate_r],[],[],20)[0] or os.read(gate_r,1)!=b'1': os._exit(70)
    os.close(gate_r)
   value=fn(); encoded=json.dumps(value).encode(); check(len(encoded)<60000,'job result budget')
   os.write(w,encoded)
   if after: after()
   os._exit(0)
  except BaseException: os._exit(71)
 os.close(w)
 if before:
  os.close(gate_r)
  try:
   before(pid)  # immutable native identity must be retained BEFORE effects
   os.write(gate_w,b'1')
  except BaseException:
   os.kill(pid,signal.SIGKILL)
   while True:
    found,_=os.waitpid(pid,os.WNOHANG)
    if found: break
    time.sleep(.02)
   raise
  finally: os.close(gate_w)
 os.set_blocking(r,False); deadline=time.monotonic()+seconds; status=None; raw=b''
 def drain():
  nonlocal raw
  while True:
   try: q=os.read(r,60001-len(raw))
   except BlockingIOError: return
   if not q: return
   raw+=q; check(len(raw)<=60000,'job result budget')
 while time.monotonic()<deadline:
  drain(); found,status=os.waitpid(pid,os.WNOHANG)
  if found: break
  time.sleep(.02)
 else:
  os.kill(pid,signal.SIGKILL)
  end=time.monotonic()+2
  while time.monotonic()<end:
   found,status=os.waitpid(pid,os.WNOHANG)
   if found: break
   time.sleep(.02)
  else:
   while True: time.sleep(1)  # unreaped owned worker: retain guardian/fences
 drain(); os.close(r)
 return status,(json.loads(raw) if raw else None)

def guardian(wfd,ofd,paths,writer,plan,window,hook=None):
 """Effectful producer. Acquire shared fences, compare, bind, publish, reconcile.

 hook is a private regression-only callable; CLI never exposes it.
 """
 fds=[]; safe=True
 for sig in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM): signal.signal(sig,signal.SIG_IGN)
 seal(ofd,'guardian.json',dict(pid=os.getpid(),boot=P('/proc/sys/kernel/random/boot_id').read_text().strip(),start=P('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]))
 try:
  fds.append(lock_path(P(window['path'])/'window.lock',time.monotonic()+15))
  for p in paths.fences(plan['action']): fds.append(lock_path(p,time.monotonic()+15,paths.writer_gid))
  known=known_candidates(wfd); previous=None if plan['previous'] is None else known[plan['previous']]
  if previous is not None:
   pf=subdir(wfd,'ops'); prior=subdir(pf,plan['previous']); os.close(pf)
   try: check(load_json(prior,'result.json')['outcome']=='published','previous operation unresolved')
   finally: os.close(prior)
  status,v=native_job(lambda:view(paths,plan['action']),5); check(status==0 and v is not None,'read-only preflight unknown')
  seal(ofd,'preflight.json',v)
  actor='ubuntu:QWEN-OWNER-ADMISSION:capacity-only:'+window['id']
  guard(v,previous,known,actor,plan['action'])
  if plan['action']!='auto':
   check(not any(os.path.lexists(paths.markers/n) for n in ('activity.lock','bake.lease','evaluation.lease')),'foreign activity marker')
  if hook: hook('compared',None)
  now=paths.now() if paths.now is not None else datetime.now(UTC); sequence=writer._allocate_sequence(paths.target,None)
  check(sequence==max([v['authority']['highest_sequence']]+[p['sequence'] for p in v['publications'].values()])+1,'sequence/authority mismatch; do not retry')
  candidate=writer.OperatorIntent(schema_version=writer.INTENT_SCHEMA_VERSION,sequence=sequence,action=writer.IntentAction(plan['action']),requested_at=now,expires_at=now+timedelta(seconds=600),ttl_seconds=600,requested_by=actor,nonce=str(uuid.uuid4())).to_payload()
  # Candidate is a native OperatorIntent payload, not a receipt or an issuer.
  # Its unique nonce and operation/window custody become immutable BEFORE effects.
  seal(ofd,'candidate.json',candidate)
  if hook: hook('bound',candidate)
  safe=False
  def effect():
   if paths.writer_uid is not None:
    os.setgroups([]); os.setgid(paths.writer_gid); os.setuid(paths.writer_uid)
   writer._publish_atomic_json(paths.target,json.dumps(candidate,separators=(',',':')))
   return dict(native_publish_completed=True)
  def started(pid):
   seal(ofd,'writer-started.json',dict(pid=pid,boot=P('/proc/sys/kernel/random/boot_id').read_text().strip(),start=P('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19],operation=plan['id'],window=window['id']))
  status,completed=native_job(effect,12,after=(lambda:hook('written',candidate)) if hook else None,before=started)
  barrier=completed==dict(native_publish_completed=True)
  seal(ofd,'writer-stopped.json',dict(wait_status=status,native_reaped=True,native_publish_completed=barrier))
  # Do not drop a publication fence merely because the child was reaped.
  # Compare actual persisted bytes under all fences; never republish/retry.
  attempt=0
  while True:
   read_status,after=native_job(lambda:view(paths,'auto'),5)
   if barrier and read_status==0 and after is not None:
    current=after['publications'].get(str(paths.target))
    if current==candidate:
     seal(ofd,'publication.json',candidate); seal(ofd,'result.json',dict(outcome='published',operation=plan['id'],window=window['id'],writer_wait_status=status)); safe=True; return
    if after==dict(authority=v['authority'],publications=v['publications'],loads=[],deferred=v['deferred']):
     seal(ofd,'result.json',dict(outcome='not-published',operation=plan['id'],window=window['id'],writer_wait_status=status)); safe=True; return
   if attempt==0: seal(ofd,'unknown.json',dict(outcome='unknown',custody='guardian retains all publication fences; no advancement'))
   attempt+=1; time.sleep(5)
 except BaseException as exc:
  if safe:
   try: seal(ofd,'result.json',dict(outcome='refused',error=type(exc).__name__+': '+str(exc),operation=plan['id'],window=window['id']))
   except BaseException: pass
  else:
   # Receipt I/O is also uncertain. Retain guardian and native lock identities.
   while True: time.sleep(1)
 finally:
  if safe: unlock(fds)

def validate_window(path,expected_id=None):
 fd=directory(path,os.geteuid())
 try:
  w=load_json(fd,'window.json')
  check(w['path']==str(P(path)) and (expected_id is None or w['id']==expected_id),'explicit window mismatch')
  check(str(uuid.UUID(w['id']))==w['id'],'bad window identity'); return fd,w
 except BaseException: os.close(fd); raise

def reconcile(wfd,paths):
 """Bounded read-only selection; no controller invocation or candidate guessing."""
 known=known_candidates(wfd); ops=subdir(wfd,'ops'); proven=[]
 for op in os.listdir(ops):
  f=subdir(ops,op)
  try:
   try: load_json(f,'result.json')
   except FileNotFoundError: raise RuntimeError('operation pending; no new effect or guessed previous publication')
  finally: os.close(f)
 try:
  for op,candidate in known.items():
   f=subdir(ops,op)
   try:
    try:
     result=load_json(f,'result.json')
     if result['outcome']!='published': continue
     stopped=load_json(f,'writer-stopped.json')
     if result['outcome']=='published' and stopped['native_reaped'] and stopped['native_publish_completed'] and load_json(f,'publication.json')==candidate: proven.append((candidate['sequence'],op,candidate))
    except FileNotFoundError: raise RuntimeError('publication operation unresolved; retain guardian and custody')
   finally: os.close(f)
 finally: os.close(ops)
 if not proven: return None
 _,op,candidate=max(proven)
 status,v=native_job(lambda:view(paths,'auto'),5); check(status==0 and v is not None,'reconciliation read unknown')
 guard(v,candidate,known,candidate['requested_by'],'auto'); return op

def dead_native(record):
 """A receipt is not a liveness oracle: compare real boot/PID/start identity."""
 pid=record['pid']; start=record['start']; boot=record['boot']
 check(type(pid) is int and pid>0 and type(start) is str and start.isdecimal() and type(boot) is str and str(uuid.UUID(boot))==boot,'invalid native process identity')
 if boot!=P('/proc/sys/kernel/random/boot_id').read_text().strip(): return
 try: current=P('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
 except FileNotFoundError: return
 check(current!=start,'live guardian/writer; retain custody')

def operation_snapshot(fd,op,window):
 """Validate every original byte before archiving; never repair an operation."""
 allowed={'intent.json','client-launch.json','guardian.json','guardian.log','preflight.json','candidate.json','writer-started.json','writer-stopped.json','publication.json','result.json'}
 names=set(bounded_names(fd,len(allowed)+1,'operation file budget exhausted'))
 check('unknown.json' not in names,'UNKNOWN operation; no checkpoint retry')
 check(names<=allowed and {'intent.json','guardian.json','result.json'}<=names,'pending or unexpected operation inventory')
 files={}; values={}
 for name in sorted(names):
  raw,files[name]=proof_file(fd,name,mode=0o600 if name=='guardian.log' else 0o400,durable=True)
  if name!='guardian.log': values[name]=json.loads(raw)
 plan=values['intent.json']; result=values['result.json']
 check(plan['id']==op and plan['window']==window['id'] and plan['action'] in ('start','stop','auto'),'foreign operation plan')
 previous=plan['previous']
 check(previous is None or (type(previous) is str and str(uuid.UUID(previous))==previous),'invalid operation predecessor')
 check(result['operation']==op and result['window']==window['id'] and result['outcome'] in ('published','not-published','refused'),'pending/UNKNOWN operation result')
 dead_native(values['guardian.json'])
 if 'client-launch.json' in values:
  launch=values['client-launch.json']
  check(launch['operation']==op and launch['window']==window['id'] and launch['guardian_pid']==values['guardian.json']['pid'],'client/guardian identity conflict')
 if 'writer-started.json' in values:
  started=values['writer-started.json']; dead_native(started)
  check(started['operation']==op and started['window']==window['id'],'foreign writer identity')
  check('writer-stopped.json' in values,'unreaped writer')
  stopped=values['writer-stopped.json']
  check(stopped['native_reaped'] is True and type(stopped['wait_status']) is int and type(stopped['native_publish_completed']) is bool,'unproven writer reap')
  check(result['writer_wait_status']==stopped['wait_status'],'writer wait status conflict')
 else: check('writer-stopped.json' not in values,'writer stop lacks original identity')
 candidate=values.get('candidate.json')
 if candidate is not None:
  check(candidate['requested_by']=='ubuntu:QWEN-OWNER-ADMISSION:capacity-only:'+window['id'] and candidate['action']==plan['action'] and type(candidate['sequence']) is int and candidate['sequence']>0 and str(uuid.UUID(candidate['nonce']))==candidate['nonce'],'foreign/invalid candidate')
 if result['outcome']=='published':
  check(candidate is not None and {'preflight.json','writer-started.json','writer-stopped.json','publication.json'}<=names,'incomplete publication proof')
  check(values['publication.json']==candidate and values['writer-stopped.json']['native_publish_completed'] is True,'publication proof conflict')
 else:
  check('publication.json' not in values,'nonpublication has publication proof')
  if result['outcome']=='not-published': check(candidate is not None and {'preflight.json','writer-started.json','writer-stopped.json'}<=names,'incomplete nonpublication proof')
  else: check('writer-started.json' not in values,'refused operation has writer effects')
 os.fsync(fd)
 return dict(directory=identity(os.fstat(fd)),files=files,candidate=candidate,outcome=result['outcome'])

def checkpoint_selection(records,v,window):
 known={op:r['candidate'] for op,r in records.items() if r['candidate'] is not None}
 proven=[(r['candidate']['sequence'],op) for op,r in records.items() if r['outcome']=='published']
 check(len({p['nonce'] for p in known.values()})==len(known) and len({p['sequence'] for p in known.values()})==len(known),'conflicting candidate history')
 previous=max(proven)[1] if proven else None
 actor='ubuntu:QWEN-OWNER-ADMISSION:capacity-only:'+window['id']
 guard(v,None if previous is None else known[previous],known,actor,'auto')
 retained=set()
 for p in v['publications'].values():
  matches=[op for op,q in known.items() if q==p and records[op]['outcome']=='published']
  check(len(matches)==1,'persisted candidate lacks complete publication proof'); retained.add(matches[0])
 if previous is not None: retained.add(previous)
 if v['deferred'] is not None:
  d=v['deferred']
  matches=[op for op,p in known.items() if p['nonce']==d['nonce'] and p['sequence']==d['sequence'] and p['action']=='stop' and records[op]['outcome']=='published']
  check(len(matches)==1,'deferred candidate lacks complete proof'); retained.add(matches[0])
 return previous,sorted(retained)

def checkpoint_view(paths):
 """Fixed topology, held no-follow ancestry and bounded actual resource proof.

 This is read-only. Publication/authority acceptance still uses guard(), with
 the same native payloads; no checkpoint receipt substitutes for source state.
 """
 owners={os.geteuid(),paths.writer_uid}; groups={os.getegid(),paths.writer_gid}; system_uid=os.stat('/').st_uid; proofs={}; missing=object()
 def open_dir(path):
  p=P(path); check(p.is_absolute() and '..' not in p.parts,'canonical resource path required')
  fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
  try:
   for part in p.parts[1:]:
    nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
    os.close(fd); fd=nxt; s=os.fstat(fd)
    sticky=s.st_uid==system_uid and stat.S_IMODE(s.st_mode)==0o1777
    check(s.st_uid in owners|{system_uid} and (sticky or (not s.st_mode&0o002 and (not s.st_mode&0o020 or s.st_gid in groups))),'unsafe current resource directory')
   return fd
  except BaseException: os.close(fd); raise
 def read(path,optional=False):
  fd=open_dir(P(path).parent)
  try:
   try: s=os.stat(P(path).name,dir_fd=fd,follow_symlinks=False)
   except FileNotFoundError:
    if optional: return missing
    raise
   mode=stat.S_IMODE(s.st_mode)
   check(s.st_uid in owners and mode in (0o400,0o600,0o640,0o644,0o660) and (not mode&0o020 or s.st_gid in groups),'unsafe current resource file')
   raw,proof=proof_file(fd,P(path).name,mode=mode,uid=s.st_uid)
   proofs[str(path)]=proof; return json.loads(raw)
  finally: os.close(fd)
 a=read(paths.store/'intent-authority.json'); pubs={}
 for base in (paths.runtime,paths.store/'intents'):
  try: fd=open_dir(base)
  except FileNotFoundError:
   check(base==paths.store/'intents','missing current runtime'); continue
  try:
   names=bounded_names(fd,len(ENVS),'unexpected publication environment inventory')
   check(set(names)<=set(ENVS),'foreign publication environment')
  finally: os.close(fd)
  for env in names:
   path=base/env/'gpu-intent.json'; p=read(path,optional=True)
   if p is not missing: pubs[str(path)]=p
 deferred=read(paths.store/'deferred-stop.json',optional=True)
 v=dict(authority=a,publications=pubs,loads=[],deferred=None if deferred is missing else deferred)
 return v,proofs

def checkpoint(wfd,paths,window):
 """Explicit bounded recovery only; ordinary known_candidates remains capped32.

 Manifest precedes any rename. A pending transaction blocks ordinary effects.
 Re-entry verifies the entire split inventory and actual state before finishing
 the SAME transaction. No authority, intent, load or service bytes are written.
 """
 fds=[]; ops=None; cfd=None; tfd=None; archive=None
 try:
  # Revalidate the caller's held window, including its still-named identity.
  named,w=validate_window(window['path'],window['id'])
  try: check(w==window and identity(os.fstat(named))==identity(os.fstat(wfd)),'checkpoint window identity changed')
  finally: os.close(named)
  window_raw,window_proof=proof_file(wfd,'window.json')
  deadline=time.monotonic()+15
  for p in [P(window['path'])/'window.lock']+paths.fences('auto'):
   s=os.stat(p,follow_symlinks=False)
   check(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid in (os.geteuid(),paths.writer_uid) and s.st_gid in (os.getegid(),paths.writer_gid) and stat.S_IMODE(s.st_mode)==0o660,'unsafe/missing checkpoint fence')
   fds.append(lock_path(p,deadline,paths.writer_gid,existing=True))
   check(identity(os.fstat(fds[-1]))==identity(s),'checkpoint fence identity changed')
  ops=subdir(wfd,'ops'); active=bounded_names(ops,33,'checkpoint operation budget exhausted (>33)')
  for op in active: check(str(uuid.UUID(op))==op,'unexpected operation directory')
  try: cfd=subdir(wfd,'checkpoints')
  except FileNotFoundError: pass
  pending=None
  if cfd is not None:
   try: pending=json.loads(proof_file(cfd,'pending.json')[0])
   except FileNotFoundError: pass
  if pending is None:
   records={}
   for op in active:
    fd=subdir(ops,op)
    try: records[op]=operation_snapshot(fd,op,window)
    finally: os.close(fd)
   before,resources=checkpoint_view(paths); previous,retained=checkpoint_selection(records,before,window)
   moved=sorted(set(records)-set(retained))
   check(moved and len(retained)<32,'checkpoint has no safe budget to reclaim')
   # All refusal controls run before creating checkpoint custody or moving ops.
   tx=str(uuid.uuid4())
   manifest=dict(schema='acx-owner-window-checkpoint/v1',id=tx,window_id=window['id'],window_path=window['path'],window=identity(os.fstat(wfd)),window_file=window_proof,previous=previous,retained=retained,archived=moved,operations=records,state=before,resources=resources)
   check(len(json.dumps(manifest).encode())<MAX//2,'checkpoint manifest budget')
   if cfd is None: cfd=subdir(wfd,'checkpoints',create=True)
   tfd=subdir(cfd,tx,create=True); archive=subdir(tfd,'ops',create=True)
   seal(tfd,'manifest.json',manifest)
   _,mp=proof_file(tfd,'manifest.json')
   seal(cfd,'pending.json',dict(id=tx,manifest_sha256=mp['sha256']))
  else:
   check(type(pending) is dict and set(pending)=={'id','manifest_sha256'} and str(uuid.UUID(pending['id']))==pending['id'],'invalid pending checkpoint')
   tx=pending['id']; tfd=subdir(cfd,tx); archive=subdir(tfd,'ops')
   raw,mp=proof_file(tfd,'manifest.json'); check(mp['sha256']==pending['manifest_sha256'],'checkpoint manifest hash mismatch'); manifest=json.loads(raw)
   check(manifest['schema']=='acx-owner-window-checkpoint/v1' and manifest['id']==tx and manifest['window_id']==window['id'] and manifest['window_path']==window['path'] and manifest['window']==identity(os.fstat(wfd)) and manifest['window_file']==window_proof,'checkpoint identity mismatch')
  records=manifest['operations']; retained=manifest['retained']; moved=manifest['archived']; previous=manifest['previous']
  check(len(records)<=33 and set(retained).isdisjoint(moved) and set(retained)|set(moved)==set(records),'checkpoint partition conflict')
  archived=bounded_names(archive,33,'checkpoint archive budget exhausted')
  check(set(active).isdisjoint(archived) and set(active)|set(archived)==set(records) and set(retained)<=set(active) and set(archived)<=set(moved),'ambiguous checkpoint directory inventory')
  for op,expected in records.items():
   fd=subdir(ops if op in active else archive,op)
   try: check(operation_snapshot(fd,op,window)==expected,'checkpoint original bytes/identity changed')
   finally: os.close(fd)
  actual,resources=checkpoint_view(paths)
  check(actual==manifest['state'] and resources==manifest['resources'],'checkpoint current state changed; no retry')
  check(checkpoint_selection(records,actual,window)==(previous,retained),'checkpoint predecessor changed')
  # Recovery always verifies every byte/location first, then resumes only the
  # manifest's original moves. Rename retains directory/file inode identities.
  for op in moved:
   if op in active:
    os.rename(op,op,src_dir_fd=ops,dst_dir_fd=archive)
    os.fsync(archive); os.fsync(ops)
  receipt=dict(schema='acx-owner-window-checkpoint-receipt/v1',checkpoint_id=tx,window_id=window['id'],window_path=window['path'],previous=previous,retained=retained,archived=moved,manifest_sha256=mp['sha256'],durable=True)
  try: old_receipt=json.loads(proof_file(tfd,'complete.json')[0]); check(old_receipt==receipt,'checkpoint completion conflict')
  except FileNotFoundError: seal(tfd,'complete.json',receipt)
  os.fsync(archive); os.fsync(ops); os.fsync(tfd); os.fsync(cfd); os.fsync(wfd)
  os.unlink('pending.json',dir_fd=cfd); os.fsync(cfd)
  return receipt
 finally:
  for fd in (archive,tfd,cfd,ops):
   if fd is not None: os.close(fd)
  unlock(fds)
