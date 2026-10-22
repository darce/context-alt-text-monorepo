"""Bounded fourth remote owner correction; coordinator transport only."""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import bakeoff_frontier_capacity as cap
import orchestrate as d

N = 'OWNER-ROOT-FIXTURE-R6'
P = d.P
BRANCH = 'feature/bakerounds-20261017-raw-auth-initial-source'
G=1024**3
PROFILE=dict(lane=N,model='gpt-6.1-sol',effort='xhigh',speed='standard',aggregate_cpu_cores_max=.5,aggregate_memory_bytes_max=2*G,forward_disk_bytes=G,physical_key=cap.RAWKEY,same_key_warm_only=True,timeout_seconds=900,no_auto_retry=True,ordinal=6,role='root_fixture_corrective_source',read_only=False)
NATIVE_CPU='25%'


def ssh(host, script, timeout=30):
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                        host, 'sudo -n python3 -' if host.startswith('ubuntu@') else 'python3 -'],
                       input=script, capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=d.ROOT, text=True, timeout=40).strip()


def guard():
    before = cap.LEDGER.read_bytes()
    ledger = json.loads(before)
    assert ledger['pending_reservations_complete']
    assert not ledger['Bakeoff']['remaining_actor_claim'] and not ledger['Bakeoff']['reserved_now']
    assert ledger['setup_owner'] is None or (isinstance(ledger['setup_owner'],str) and ledger['setup_owner'].startswith('Owner-coordinated-next')), 'Actual shared setup owner must return first'
    assert not ledger['aura']['active_models'] and not ledger['aura']['setup_granted'], 'Reconcile new Aura profile before this claim'
    assert not ledger['Canvas']['active_models'] and not ledger['Canvas']['setup_granted']
    rows = {}
    for k, v in ledger.items():
        if k in {'wb', 'Bakeoff', 'aura', 'Canvas', 'aura_runtime'} or not isinstance(v, dict):
            continue
        if v.get('remaining_actor_claim') or v.get('reserved_now') or v.get('future_model_claims'):
            if v.get('aggregate_cpu_cores_max') == 0 and v.get('aggregate_memory_bytes_max') == 0:
                phase = v.get('VM_phase_retirement', {})
                assert not v.get('remaining_actor_claim') and not v.get('future_model_claims') and not v.get('setup_granted'), k
                assert phase.get('authority_decision') == 18330 and phase.get('phase') == 'host_custody_verification_no_VM_execution', k
                assert phase.get('transport_fsync_complete') and phase.get('remote_all_lstat_unchanged') and phase.get('native_wrapper_model_archive_inactive'), k
                assert phase.get('UID0_hits') == 0 and phase.get('UID0_errors') == 0 and phase.get('PG4healthy'), k
                assert phase.get('remaining_VM_actor_claim') == 0 and phase.get('remaining_retention_claim') == 1, k
                # Disk remains charged in pending_reservations; this phase has no VM execution.
                continue
            assert isinstance(v.get('aggregate_cpu_cores_max'), (int, float)) and 0 < v['aggregate_cpu_cores_max'] <= 4, k
            assert isinstance(v.get('aggregate_memory_bytes_max'), int) and v['aggregate_memory_bytes_max'] > 0, k
            assert v.get('physical_key') or v.get('expected_physical_key') or v.get('branch') or v.get('custody_unit') or v.get('native_unit'), k
            row = dict(v)
            if not row.get('physical_key') and row.get('expected_physical_key'):
                row['physical_key']=row['expected_physical_key']
            if not row.get('physical_key') and row.get('branch'):
                branch = row['branch']
                row['physical_key'] = re.sub('[^A-Za-z0-9._-]', '-', branch)[:40]+'-'+hashlib.sha256(branch.encode()).hexdigest()[:8]
            rows[k] = row
    for k, v in ledger['WB_operations'].items():
        if v.get('remaining_actor_claim'):
            rows[k] = dict(v, physical_key=v.get('physical_key')or v.get('expected_physical_key'), aggregate_cpu_cores_max=v['cpu_cores_aggregate'], aggregate_memory_bytes_max=v['memory_bytes_aggregate'])
    aura_a = ledger.get('Aura_WP400_A', {})
    if aura_a.get('remaining_actor_claim'):
        assert (aura_a['source_commit'], aura_a['model'], aura_a['effort'], aura_a['speed']) == ('a4fabeb0732a36f1610504eacdca8b457346566b', 'gpt-6.1-sol', 'low', 'standard')
        assert (aura_a['aggregate_cpu_cores_max'], aura_a['aggregate_memory_bytes_max'], aura_a['forward_disk_bytes'], aura_a['scratch_max_bytes']) == (.5, 3*G, 4*G, G//2)
        branch = aura_a['branch']
        key = re.sub('[^A-Za-z0-9._-]', '-', branch)[:40]+'-'+hashlib.sha256(branch.encode()).hexdigest()[:8]
        rows['Aura_WP400_A'] = dict(aura_a, physical_key=key)
    cpu, memory = .25 + PROFILE['aggregate_cpu_cores_max'], 2*G + PROFILE['aggregate_memory_bytes_max']
    expected = {}
    for k, v in rows.items():
        assert not v.get('setup_granted'), k
        assert dt.datetime.fromisoformat(v['expires']) > dt.datetime.now(dt.timezone.utc), 'Expired owner lease: '+k
        cpu += v['aggregate_cpu_cores_max']; memory += v['aggregate_memory_bytes_max']
        if v.get('physical_key'):
            expected['workbay-lane-' + v['physical_key']] = [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
        for field in ['custody_unit', 'custody_scope']:
            if v.get(field): expected[v[field]] = [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
    # The first source offer predates its row; never resurrect it after return.
    # Actual maintenance and subsequent owner claims are counted from their rows.
    if not aura_a:
        cpu += .5; memory += 4*G
    assert cpu <= 3.25 and cpu + 1.5 <= 4 and memory <= 16*G
    root_units={v['native_unit']:[v['aggregate_cpu_cores_max'],v['aggregate_memory_bytes_max']]for v in rows.values()if v.get('native_unit')}
    root_named_units={}
    if root_units:
        script="""import json,subprocess
units=UNITS;out={}
for n,(c,m)in units.items():
 out[n]={};total_cpu=0.;total_memory=0
 commands={'system':['systemctl'],'gate-user':['sudo','-n','-H','-u','gate','env','XDG_RUNTIME_DIR=/run/user/1002','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1002/bus','systemctl','--user']}
 for namespace,prefix in commands.items():
  q=subprocess.check_output(prefix+['show',n,'-p','LoadState','-p','ActiveState','-p','ControlGroup','-p','MainPID','-p','CPUQuotaPerSecUSec','-p','MemoryMax'],text=True,timeout=6)
  v=dict(l.split('=',1)for l in q.splitlines()if '='in l);out[n][namespace]=v
  if v['LoadState']=='not-found':
   assert v['ActiveState']=='inactive'and not v['ControlGroup'],(n,namespace,v)
   if 'MainPID'in v:assert v['MainPID']=='0',(n,namespace,v)
   continue
  cpu=v['CPUQuotaPerSecUSec']
  for suffix,factor in [('us',1e-6),('ms',1e-3),('s',1.)]:
   if cpu.endswith(suffix):actual=float(cpu[:-len(suffix)])*factor;break
  else:raise AssertionError('Unbounded existing native CPU')
  total_cpu+=actual;total_memory+=int(v['MemoryMax'])
 assert total_cpu<=c+1e-8 and total_memory<=m,(n,out[n])
print(json.dumps(out))
""".replace('UNITS',repr(root_units))
        root_named_units=ssh('ubuntu@acx-backend.tail1a44b8.ts.net',script)
    pending = sum(v['reserved_bytes'] for v in ledger['pending_reservations']) + ledger['runtime_reserve_bytes'] + ledger['emergency_reserve_bytes'] + G
    if not aura_a:
        pending += 4*G + G//2
    assert ledger['runtime_reserve_bytes'] == 3*G and ledger['emergency_reserve_bytes'] == 1400000000
    probe = (P/'raw_auth_source_gate_root_probe.py').read_text()
    probe += "\n"
    root = ssh('ubuntu@acx-backend.tail1a44b8.ts.net', probe)
    assert root['euid'] == 0 and not root['hits'] and not root['unknown'] and root['pg_all_healthy']
    a = root['df'].splitlines()[1].split(); used, free = int(a[2])*1024, int(a[3])*1024
    assert int(a[4].strip('%')) < 90 and math.ceil((used+pending)/(used+free)*100) < 90
    native_script = '''import json,pathlib,subprocess,time,os
q=lambda *a:subprocess.check_output(a,text=True,timeout=8)
b=pathlib.Path('/sys/fs/cgroup/user.slice/user-'+str(os.getuid())+'.slice')
units=[]
for line in q('systemctl','--user','list-units','--state=running','--no-legend','--plain','workbay-lane-*.scope','workbay-lane-*.service','workbay-custody-*.scope','workbay-custody-*.service').splitlines():
 n=line.split()[0];r=dict(x.split('=',1)for x in q('systemctl','--user','show',n,'-p','CPUQuotaPerSecUSec','-p','MemoryMax').splitlines()if '='in x);r['unit']=n;units.append(r)
i=dict(l.split(':',1)for l in pathlib.Path('/proc/meminfo').read_text().splitlines());s=dict(l.split()for l in (b/'memory.stat').read_text().splitlines())
print(json.dumps({'at':time.time(),'units':units,'cpu':pathlib.Path('/proc/pressure/cpu').read_text(),'io':(b/'io.pressure').read_text(),'physical_mem_available':int(i['MemAvailable'].split()[0])*1024,'working_headroom':int((b/'memory.max').read_text())-max(0,int((b/'memory.current').read_text())-int(s.get('inactive_file',0)))}))
'''
    native = ssh(d.HOST, native_script)
    assert float(re.search(r'avg60=([0-9.]+)', native['cpu']).group(1)) < 55
    assert float(re.search(r'full avg10=[^ ]+ avg60=([0-9.]+)', native['io']).group(1)) <= 15
    assert min(native['physical_mem_available'], native['working_headroom']) >= 3*G
    totals = {k: [0., 0] for k in expected}
    for row in native['units']:
        matches = [k for k in expected if row['unit'].startswith(k)]
        assert matches, 'Unreconciled native operation: ' + row['unit']
        k = max(matches, key=len); value = row['CPUQuotaPerSecUSec']
        for suffix, factor in [('us', 1e-6), ('ms', 1e-3), ('s', 1.)]:
            if value.endswith(suffix): c = float(value[:-len(suffix)])*factor; break
        else: raise AssertionError('Unbounded native CPU')
        totals[k][0] += c; totals[k][1] += int(row['MemoryMax'])
    for k, (c, m) in totals.items(): assert c <= expected[k][0]+1e-8 and m <= expected[k][1], k
    proof = dict(at=time.time(), ledger_sha256=hashlib.sha256(before).hexdigest(), pending=pending,
                 prospective_CPU=cpu+1.5, prospective_RAM=memory+4*G,
                 projected_root=math.ceil((used+pending)/(used+free)*100), root=root, native=native, root_named_units=root_named_units)
    cap.persist(P/(N+'.operation-capacity.json'), proof)
    assert cap.LEDGER.read_bytes() == before, 'Owner event changed ledger; remeasure'
    return before, ledger, proof


def verify_warm():
    receipt=json.loads((P/'OWNER-ROOT-FIXTURE-G2.terminal-verified.json').read_text())
    returned=json.loads((P/'OWNER-ROOT-FIXTURE-G2.actual-capacity-return.json').read_text())
    assert returned['remaining_actor_claim']==0 and returned['head']==receipt['head']
    bundle=Path(receipt['external_dir'])/'complete-head.bundle'
    with bundle.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==receipt['external_full_bundle_sha256']
    custody=dict(key=cap.RAWKEY,head=receipt['head'],tree=receipt['tree'],anchors=receipt['anchors'])
    script = """import json,pathlib,subprocess,hashlib
c=CUSTODY;r=pathlib.Path('/home/gate/workbay-sandbox')/c['key'];g=lambda *a:subprocess.check_output(['git',*a],cwd=r,text=True,timeout=8).strip()
assert g('rev-parse','HEAD')==c['head'] and g('rev-parse','HEAD^{tree}')==c['tree'];assert not g('status','--porcelain','--untracked-files=normal')
for p,a in c['anchors'].items():assert hashlib.sha256((r/p).read_bytes()).hexdigest()==a['sha256']
stamp=r.parent/('.venv-sync-stamp-'+c['key']);assert stamp.read_text().strip()=='3379106c9d66e0cbda4f24ced8c34e1ffd7d463c98ddc4f379b83a9c79abaed7'
assert (r.parent/('.venv-lane-'+c['key'])/'bin/python').exists();print(json.dumps({'warm_verified':True,'head':c['head'],'tree':c['tree']}))
""".replace('CUSTODY',repr(custody))
    cap.persist(P/(N+'.warm-custody-check.json'),ssh(d.HOST,script))


def run():
    assert not (P/(N+'.capacity-claim.json')).exists(), 'Existing claim must be reconciled; never redispatch'
    stage = json.loads((P/(N+'.input.stage.json')).read_text())
    verify_warm()
    before, ledger, proof = guard()
    profile = dict(PROFILE, source_commit=stage['sha'], source_tree=stage['tree'])
    expiry = (dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=45)).isoformat()
    allocation = dict(owner='Bakeoff', authority='Operator authorized sixth narrow Root-fixture correction; LOUD18413', reserved_now=True, captured_at=dt.datetime.now(dt.timezone.utc).isoformat(), expires=expiry, profiles={N:profile}, aggregate_cpu_cores_max=PROFILE['aggregate_cpu_cores_max'], aggregate_memory_bytes_max=2*G, forward_disk_bytes=G, actual_models=0, setup_granted=True, remaining_actor_claim=1, no_auto_retry=True)
    ledger['Bakeoff'] = allocation; ledger['setup_owner'] = 'Bakeoff'; ledger['updated_at'] = allocation['captured_at']
    ledger['pending_reservations'] = [r for r in ledger['pending_reservations'] if not r['owner'].startswith('Bake-')] + [dict(owner='Bake-'+N, reserved_bytes=G, source=stage['sha'], owner_receipt=str(cap.OWNER))]
    assert cap.LEDGER.read_bytes() == before
    cap.persist(cap.LEDGER, ledger); cap.persist(cap.LEASE, allocation)
    owner=json.loads(cap.OWNER.read_text())
    owner.update(captured_at=allocation['captured_at'], remaining_forward_disk_bytes=G,
                 exact_self_reserved_profiles={N:profile}, reserved_now=True,
                 setup_in_progress=True, remaining_actor_claim=1,
                 capacity_authority=allocation['authority'])
    cap.persist(cap.OWNER, owner)
    claim = dict(allocation, native_branch=BRANCH, model=PROFILE['model'], effort=PROFILE['effort'], speed='standard', native_CPU_each=NATIVE_CPU, native_RAM_each='1G', guard=proof)
    fd=os.open(P/(N+'.capacity-claim.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(claim,f,indent=2);f.flush();os.fsync(f.fileno())
    original=git('rev-parse','refs/heads/'+BRANCH);assert 'branch refs/heads/'+BRANCH not in git('worktree','list','--porcelain')
    spec=json.loads((P/(N+'.spec.json')).read_text());assert spec['operator_values']==[PROFILE['model'],PROFILE['effort'],'standard'];spec.update(branch=BRANCH,lane_timeout_s=900);cap.persist(P/(N+'.spec.json'),spec)
    git('update-ref','refs/heads/'+BRANCH,stage['sha'],original)
    cap.persist(P/(N+'.branch-alias.json'),dict(state='active',native_branch=BRANCH,original_commit=original,dispatch_input=stage['sha']))
    env=dict(os.environ,WORKBAY_REMOTE_GATE_HOST=d.HOST,WORKBAY_REMOTE_GATE_MEMORY_MAX='1G',WORKBAY_REMOTE_GATE_CPU_QUOTA=NATIVE_CPU,WORKBAY_REMOTE_AGENT_MAX_LANE_VENVS='0',WORKBAY_REMOTE_AGENT_UV_CACHE_CAP_MB='0',WORKBAY_REMOTE_AGENT_DISPATCH_TTL_SEC='0',WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC='0',WORKBAY_REMOTE_AGENT_SANDBOX_IDLE_SEC='0',WORKBAY_ALLOW_NONCONFORMING_BRANCH_PUSH='1',WORKBAY_ALLOW_NONCONFORMING_BRANCH_PUSH_REASON='Authorized sixth remote-only fixture correction; no local implementation')
    env.pop('WORKBAY_REMOTE_AGENT_MAX_LANES',None)
    args=[d.HELPER,'build','--branch',BRANCH,'--brief',str(P/(N+'.brief.md')),'--schema',str(P/'CORPUS-G1.schema.json'),'--agent-spec',str(P/(N+'.spec.json')),'--timeout','900']
    for opt,suf in [('out','patch'),('result-out','result.json'),('debug-out','debug.log'),('stream-out','stream.jsonl'),('phases-out','phases.json'),('provenance-out','provenance.json'),('uncommitted-out','uncommitted.patch')]:args+=['--'+opt,str(P/(N+'.'+suf))]
    try:
        proc=subprocess.Popen(args,cwd=d.ROOT,env=env,stdout=(P/(N+'.build.out')).open('a'),stderr=(P/(N+'.build.log')).open('a'))
        print(json.dumps(dict(status='native_transport_started',pid=proc.pid,model=PROFILE['model'],effort=PROFILE['effort'],speed='standard',source=stage['sha'])),flush=True)
        rc=proc.wait(timeout=1020)
        cap.persist(P/(N+'.build-receipt.json'),dict(lane=N,exit=rc,finished=time.time(),model=PROFILE['model'],effort=PROFILE['effort'],speed='standard'))
        print(json.dumps(dict(status='transport_terminal',exit=rc)),flush=True)
    finally:
        git('update-ref','refs/heads/'+BRANCH,original,stage['sha'])
        cap.persist(P/(N+'.branch-alias.json'),dict(state='restored',native_branch=BRANCH,original_commit=original,dispatch_input=stage['sha']))


if __name__ == '__main__':
    import fcntl
    locks=[]
    old_guard=guard
    old_git=git
    def locked_guard():
        global locks
        assert (P/'OWNER-RESUME-START-R4.shared-mutex-confirmed.json').exists(), 'Confirm canonical all-owner shared setup mutex before claim'
        for path in [d.ROOT/'.task-state/gtm-continue-20261012/vm-launch.lock',cap.LEDGER.parent/'shared-capacity-reservations-20261018.owner-update.lock']:
            handle=path.open('a+')
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BaseException:
                handle.close()
                raise
            locks.append(handle)
        return old_guard()
    def unlock_git(*args):
        while locks:
            handle=locks.pop();fcntl.flock(handle,fcntl.LOCK_UN);handle.close()
        return old_git(*args)
    guard=locked_guard
    git=unlock_git
    try:run()
    finally:
        while locks:
            handle=locks.pop();fcntl.flock(handle,fcntl.LOCK_UN);handle.close()

