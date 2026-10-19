#!/usr/bin/python3
"""NEW benchmark-owned procedural producer, not an installed API extension.

CLI is implemented by owner-window.py. These functions have no cloud/API calls.
All live paths are supplied only by its fixed Production configuration.
"""
import ast,errno,fcntl,hashlib,importlib.util,json,os,pathlib,select,signal,stat,subprocess,sys,time,uuid
from datetime import UTC,datetime,timedelta
P=pathlib.Path
ENVS=('dev','dev-fir','prod','staging')
PIN='54f7bd837f20c24529ce3e1ea53e91a405b16234c62092890c22b507c149a2d9'
LOAD_PIN='0d08441a76a5f9f5c38ac32c3b4dd7956de07af3255fb31748bef36b5da26521'
MAX=1048576

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

def lock_path(path,deadline,group=None):
 p=P(path)
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
 ops=subdir(wfd,'ops'); result={}
 try:
  names=os.listdir(ops); check(len(names)<=32,'operation budget exhausted')
  for name in names:
   check(str(uuid.UUID(name))==name,'unexpected operation directory')
   f=subdir(ops,name)
   try:
    try: result[name]=load_json(f,'candidate.json')
    except FileNotFoundError: pass
   finally: os.close(f)
 finally: os.close(ops)
 return result

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
