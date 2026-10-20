import pathlib,json,hashlib,subprocess,os,time,uuid,stat
from pathlib import Path
assert os.getuid()==os.geteuid()==0
stage=Path('/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure');window=Path('/tmp/qwen-owner-window.rcqmefq9');wid='223eb2de-b63a-4b19-a31e-a34d07a8e187'
assert hashlib.sha256((stage/'owner-window.py').read_bytes()).hexdigest()=='033d187835c9243bd486b185167563c16ef24812eb26f174ea062fc46fe798e9';assert hashlib.sha256((stage/'approved-scripts.json').read_bytes()).hexdigest()=='45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca'
base=Path('/home/gate/bakeoff-rounds-20261017-inputs/results')/('LEXICON-FRESH-CONTROL-R2-'+uuid.uuid4().hex);base.mkdir(mode=0o700);permanent=base/'permanent';permanent.mkdir(mode=0o700)
print(json.dumps(dict(status='CONTROL_CAPSULE_STAGED',base=str(base))),flush=True)
def save(name,value):
    path=permanent/name
    with path.open('x')as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    path.chmod(0o400)

def public(arguments,label,timeout):
    # A writable result is pending integrity state, never evidence of no effect.
    # Recover only this exact response ambiguity through the public read API.
    mutating=arguments[0]in('start','stop')
    before={p.name for p in(window/'ops').iterdir()}if mutating else set()
    deadline=time.monotonic()+timeout
    command=['/usr/bin/python3','-I','-B',str(stage/'owner-window.py'),*arguments]
    q=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
    save(label+'.json',dict(arguments=arguments,exit_code=q.returncode,stdout=q.stdout,stderr=q.stderr))
    if q.returncode==0:return q.stdout.strip()
    assert mutating and q.returncode==1 and q.stderr.strip().splitlines()[-1]=='RuntimeError: receipt is mutable',label+' refused; retain exact window'
    created={p.name for p in(window/'ops').iterdir()}-before
    assert len(created)==1,'Ambiguous operation inventory; retain exact window'
    op=created.pop();assert str(uuid.UUID(op))==op
    def sealed(name):
        p=window/'ops'/op/name;s=p.lstat()
        assert stat.S_ISREG(s.st_mode)and not stat.S_IMODE(s.st_mode)&0o222 and s.st_uid==0,'Unsealed or foreign operation evidence'
        return json.loads(p.read_bytes())
    intent=sealed('intent.json')
    assert intent==dict(id=op,window=wid,action=arguments[0],previous=arguments[2]),'Operation linkage changed; retain exact window'
    remaining=deadline-time.monotonic();assert remaining>0,'Fixed public-call deadline exhausted'
    read_arguments=['reconcile',str(window),wid]
    r=subprocess.run(['/usr/bin/python3','-I','-B',str(stage/'owner-window.py'),*read_arguments],capture_output=True,text=True,timeout=remaining)
    save(label+'-sealed-result-reconciliation.json',dict(arguments=read_arguments,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr,expected_operation=op,no_publication_replayed=True))
    assert r.returncode==0 and r.stdout.strip()==op,'Ownership reconciliation unknown or changed; retain exact window'
    result=sealed('result.json');publication=sealed('publication.json')
    assert result.get('operation')==op and result.get('window')==wid and result.get('outcome')=='published','Operation did not publish'
    assert publication.get('action')==arguments[0],'Publication action changed'
    return op

def observe(op,phase,label,timeout):
    # Only repeat a completed, read-only observer's exact unknown-deadline result.
    # No START, STOP, withdrawal, controller or model request is replayed.
    deadline=time.monotonic()+timeout-5
    attempt=0
    while True:
        remaining=deadline-time.monotonic()
        assert remaining>0,label+' observation deadline; retain exact ownership'
        suffix=label+'-attempt-'+str(attempt)
        out=public(['outdir',str(window),phase],suffix+'-directory',10)
        q=subprocess.run(['/usr/bin/python3','-I','-B',str(stage/'observe.py'),str(window/'ops'/op/'publication.json'),out,phase],capture_output=True,text=True,timeout=min(310,remaining))
        save(suffix+'.json',dict(exit_code=q.returncode,stdout=q.stdout,stderr=q.stderr,output=out))
        if q.returncode==0:return Path(out)
        retry=(phase=='start' and q.returncode==1 and q.stderr.strip()=='receipt deadline: unknown; preserve all files and do not infer stopped/unloaded')
        assert retry and time.monotonic()<deadline,label+' observation unknown/refused; retain exact ownership'
        attempt+=1
state=json.loads(Path('/run/acx/gpu-state.json').read_bytes());assert state['state']=='stopped'and state.get('lease_expires_at')is None
prior=public(['reconcile',str(window),wid],'prior-reconcile',45);assert prior=='5f6ef7e1-5aae-4286-9d14-fe1eddf65d44'
previous=Path('/home/gate/bakeoff-rounds-20261017-inputs/results/LEXICON-FRESH-CONTROL-R1-b98fde7bb15a48aebab8567bf12b781d/permanent/owned-window-return.json');old=json.loads(previous.read_bytes());assert old['operation']==prior and old['Qwen_restored']and old['owned_client_reaped']and old['owned_candidate_reaped']
stop=public(['stop',str(window),prior],'fresh-stop',75);observe(stop,'stop','fresh-stop-observe',195)
s=json.loads(Path('/run/acx/gpu-state.json').read_bytes());assert s['state']=='stopped'and s.get('lease_expires_at')is None
save('completed-physical-lease-closed.json',dict(STOP=stop,canonical_stopped=True,after_Qwen_restore=True,no_actor_or_request_active=True,control_only=True,previous_restoration_sha256=hashlib.sha256(previous.read_bytes()).hexdigest()))
auto=public(['withdraw',str(window),wid],'fresh-auto',75);assert auto!='none';observe(auto,'auto','fresh-auto-observe',190)
assert public(['reconcile',str(window),wid],'final-reconcile',45)==auto
save('owned-window-return.json',dict(operation=auto,owned_client_reaped=True,owned_candidate_reaped=True,Qwen_restored=True,completed_STOP=stop,control_only=True,previous_Qwen_restoration_carried_from=prior,no_START_or_model_requests=True))
save('candidate-result.json',dict(complete=True,control_only=True,evaluated_images=0,raw_passes=0,item_errors=0,new_GPU_requests=0))
print(json.dumps(dict(status='FRESH_STOP_AUTO_SETTLED',base=str(base),STOP=stop,AUTO=auto,new_GPU_requests=0)),flush=True)
