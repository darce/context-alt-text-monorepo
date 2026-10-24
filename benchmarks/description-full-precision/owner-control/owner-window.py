#!/usr/bin/python3
"""NEW procedural client/guardian, fixed production topology; no live call here.

new-window -> window path; inspect W -> immutable read-only source receipts;
start|stop|auto W PREVIOUS_OP_OR_DASH -> fresh operation UUID after proven write;
reconcile W WINDOW_ID -> latest proven operation, or none;
withdraw W WINDOW_ID -> owned AUTO operation, or none; no forced STOP;
outdir W PHASE -> fresh protected observation directory; id W -> immutable ID.
Every publication JSON remains the canonical native payload at top level.
"""
import base64,hashlib,importlib.util,json,os,pathlib,subprocess,sys,tempfile,time,uuid
P=pathlib.Path; A=P(__file__).absolute().parent
assert os.geteuid()==0,'normal ubuntu passwordless sudo required'
# The adopted composed staging manifest pins this file AND owner-custody.py.
# Bootstrap verifies those bytes through held no-follow file identities before
# copying them to a fresh root-owned directory beneath root sticky /tmp.
spec=importlib.util.spec_from_file_location('owner_custody',A/'owner-custody.py'); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
afd=c.directory(A,0); c.read_at(afd,'owner-custody.py',0,sealed=True); os.close(afd)
paths=c.Paths('/run/acx-write','/var/lib/acx-gpu','/var/lib/acx-gpu/lifecycle.lock','/run/acx-gpu',10001,10001)

def raw_seal(fd,name,b):
 f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=fd)
 try:
  view=memoryview(b)
  while view: view=view[os.write(f,view):]
  os.fsync(f); os.fchmod(f,0o400); os.fsync(f)
 finally: os.close(f)
 os.fsync(fd)

def inspect(wfd):
 compose=['docker','compose','-f','/opt/acx-backend/prod/docker-compose.env.yml','-f','/opt/acx-backend/prod/docker-compose.admin.yml','exec','-T','api','python','-B','-']
 code="""import signal
signal.signal(signal.SIGALRM,signal.SIG_DFL); signal.alarm(12)
import ast,base64,hashlib,importlib.util,json,pathlib,os
s=importlib.util.find_spec('scene'); d=pathlib.Path(next(iter(s.submodule_search_locations)))/'application'
files={n:(d/n).read_bytes() for n in ('gpu_intent.py','describe_load.py')}
for b in files.values(): ast.parse(b)
print(json.dumps({'files':{n:base64.b64encode(b).decode() for n,b in files.items()},'env':{n:os.environ.get(n) for n in ('ACX_ENV','ACX_DESCRIBE_LOAD_PATH','ACX_GPU_INTENT_PATH','ACX_GPU_INTENT_DURABLE_PATH')}}))
"""
 r=subprocess.run(compose,input=code.encode(),capture_output=True,timeout=20,check=True)
 v=json.loads(r.stdout); e=v['env']; c.check(e['ACX_ENV']=='prod' and e['ACX_DESCRIBE_LOAD_PATH']=='/run/acx-write/prod/describe-load.json' and e['ACX_GPU_INTENT_PATH'] in (None,'','/run/acx-write/prod/gpu-intent.json') and e['ACX_GPU_INTENT_DURABLE_PATH'] in (None,''),'installed topology changed')
 writer=base64.b64decode(v['files']['gpu_intent.py']); load=base64.b64decode(v['files']['describe_load.py']); c.load_writer(writer,load)
 raw_seal(wfd,'writer-source.py',writer); raw_seal(wfd,'load-source.py',load); c.seal(wfd,'installed-source-config.json',dict(writer_sha256=c.PIN,load_sha256=c.LOAD_PIN,env=e))
 status,view=c.native_job(lambda:c.view(paths,'inspect'),5); c.check(status==0 and view is not None,'read-only inspect unknown'); c.seal(wfd,'inspect.json',view)

def operation(wfd,w,action,previous):
 c.check(action in ('start','stop','auto'),'unsupported operation')
 ofd=None
 try:
  lock=c.lock_path(P(w['path'])/'window.lock',time.monotonic()+15)
  try:
   ops=c.subdir(wfd,'ops')
   try:
    c.known_candidates(wfd)  # Preserve validation of every retained directory/receipt.
    # Every directory, including failed/pending custody, consumes one slot.
    # START stops at 1022; STOP/AUTO share the final two cleanup slots.
    # Neither cleanup action is guaranteed its own slot; no receipt is reused.
    limit=c.MAX_WINDOW_OPERATIONS-(2 if action=='start' else 0)
    c.check(len(os.listdir(ops))<limit,'operation budget exhausted; retain window custody')
    op=str(uuid.uuid4()); ofd=c.subdir(ops,op,create=True)
    plan=dict(id=op,window=w['id'],action=action,previous=previous); c.seal(ofd,'intent.json',plan)
   finally: os.close(ops)
  finally: c.unlock([lock])
  # Release admission's window fence before the guardian acquires that fence.
  log=os.open('guardian.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=ofd)
  try:
   child=subprocess.Popen([sys.executable,'-B',str(A/'owner-window.py'),'--guardian',w['path'],op],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
   # This is only launch diagnostics; native writer-stopped.json is proof.
   c.seal(ofd,'client-launch.json',dict(guardian_pid=child.pid,operation=op,window=w['id']))
  finally: os.close(log)
  deadline=time.monotonic()+35
  while time.monotonic()<deadline:
   try:
    result=c.load_json(ofd,'result.json'); c.check(result['outcome']=='published','operation '+result['outcome']+'; retain custody'); return op
   except FileNotFoundError: time.sleep(.1)
  raise RuntimeError('client deadline; guardian/custody retained; reconcile exact window read-only')
 finally:
  if ofd is not None: os.close(ofd)

def reconciled(wfd):
 deadline=time.monotonic()+30
 while True:
  try: return c.reconcile(wfd,paths)
  except RuntimeError as e:
   if time.monotonic()>=deadline: raise
   if not ('pending' in str(e) or 'unresolved' in str(e)): raise
   time.sleep(.2)

mode=sys.argv[1]
if mode=='new-window':
 c.directory(A,0)  # A is the staged root-owned procedure, not an author root.
 W=tempfile.mkdtemp(prefix='qwen-owner-window.',dir='/tmp'); os.chmod(W,0o700)
 fd=c.directory(W,0)
 try:
  c.seal(fd,'window.json',dict(id=str(uuid.uuid4()),path=W,procedure=str(A)))
  for name in ('ops','observations'): os.close(c.subdir(fd,name,create=True))
 finally: os.close(fd)
 print(W); raise SystemExit(0)
W=sys.argv[2]; wfd,w=c.validate_window(W)
try:
 c.check(w['procedure']==str(A),'window/procedure mismatch')
 if mode=='--guardian':
  op=sys.argv[3]; ops=c.subdir(wfd,'ops'); ofd=c.subdir(ops,op); os.close(ops)
  try:
   plan=c.load_json(ofd,'intent.json'); c.check(plan['id']==op and plan['window']==w['id'],'operation mismatch')
   writer=c.load_writer(c.read_at(wfd,'writer-source.py',0,sealed=True),c.read_at(wfd,'load-source.py',0,sealed=True))
   c.guardian(wfd,ofd,paths,writer,plan,w)
  finally: os.close(ofd)
 elif mode=='inspect': inspect(wfd); print('read-only preflight complete')
 elif mode=='id': print(w['id'])
 elif mode=='outdir':
  phase=sys.argv[3]; c.check(phase in ('start','auto','stop'),'bad phase'); parent=c.subdir(wfd,'observations'); name=phase+'-'+str(uuid.uuid4()); os.close(c.subdir(parent,name,create=True)); os.close(parent); print(str(P(W)/'observations'/name))
 elif mode in ('start','stop','auto'):
  previous=None if sys.argv[3]=='-' else sys.argv[3]
  c.check(mode=='start' or previous is not None,'explicit previous operation required')
  print(operation(wfd,w,mode,previous))
 elif mode in ('reconcile','withdraw'):
  c.check(sys.argv[3]==w['id'],'exact window handoff mismatch'); op=reconciled(wfd)
  if mode=='withdraw' and op is not None:
   candidate=c.known_candidates(wfd)[op]
   if candidate['action']!='auto': op=operation(wfd,w,'auto',op)
  print(op or 'none')
 else: raise RuntimeError('unsupported command')
finally: os.close(wfd)
