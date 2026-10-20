"""Finite remote-only orchestration of the existing, source-gated Root fixture."""
import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import bakeoff_frontier_capacity as cap
import run_owner_root_fixture_r6 as admission

P = cap.P
N = 'OWNER-ROOT-RESUME-QUAL-R6'
G = 1024**3
UNIT = 'workbay-bakeoff-root-resume-r6-qual-20261018.scope'
ROLE = 'actual_selected_isolated_root_qualification'
PREFIX = '.task-state/bakeoff-rounds-20261017/'


def git_blob(head, path):
    return subprocess.check_output(['git', 'show', head+':'+path], cwd=admission.d.ROOT, timeout=30)


def inputs(head, gate):
    """Assemble exact approved bytes externally; no implementation is edited."""
    review = json.loads((P/(gate+'.result.json')).read_text())
    reviewed = json.loads((P/(gate+'.input.stage.json')).read_text())
    assert review['status'] == 'PASS' and reviewed['reviewed_subject'] == head
    assert (P/(gate+'.terminal-verified.json')).exists()
    original = json.loads((P/'OWNER-RESUME-START-R4.root-qualification-inputs.json').read_text())
    root = Path(original['input_dir'])
    files = {}
    for name, expected in original['files'].items():
        if name == 'root_fixture_plan.py':
            continue
        data = (root/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, name
        files[name] = data
    for name, path in [('root_fixture_plan.py', PREFIX+'qualifications/owner-resume-start-r4/root_fixture_plan.py'),
                       ('root_resume_fixture_coordinator.py', PREFIX+'root_resume_fixture_coordinator.py')]:
        files[name] = git_blob(head, path)
    assert hashlib.sha256(files['OWNER-FLOW-CONTROLS-R2.py']).hexdigest() == '369c120b901b1ee3faeb642d6d498ef2ae0e5b98904c44d0b1a9c64c3a51e062'
    manifest = dict(version=1, source_head=head, independent_gate=gate,
                    files={name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())})
    raw = (json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode()
    digest = hashlib.sha256(raw).hexdigest()
    files['input-manifest.json'] = raw
    stage = '/root/bakeoff-root-resume-r6-qual-20261018-'+digest[:12]
    external = Path('/Volumes/Butter/WorkBay/custody')/('root-resume-r6-qualified-inputs-'+digest[:12])
    existed = external.exists()
    external.mkdir(mode=0o700, exist_ok=True)
    for name, data in files.items():
        path = external/name
        if existed:
            assert path.is_file() and not path.is_symlink() and path.read_bytes() == data, name
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        path.chmod(0o400)
    receipt = dict(source_head=head, gate=gate, stage=stage, manifest_sha256=digest,
                   external_inputs=str(external), file_count=len(files), input_bytes=sum(map(len, files.values())),
                   unit=UNIT, root_execution_performed=False)
    cap.persist(P/(N+'.prepared-inputs.json'), receipt)
    return files, receipt


def bootstrap(files, receipt):
    payload = dict(stage=receipt['stage'], manifest=receipt['manifest_sha256'],
                   files={n: base64.b64encode(v).decode() for n, v in files.items()})
    return '''import base64,hashlib,json,os,pathlib,stat,time
v=PAYLOAD
assert os.getuid()==os.geteuid()==0
cg=pathlib.Path('/sys/fs/cgroup')/pathlib.Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
assert (cg/'cpu.max').read_text().strip()=='50000 100000'
assert (cg/'memory.max').read_text().strip()=='2147483648'
os.umask(0o077);root=pathlib.Path(v['stage']);root.mkdir(mode=0o700)
data={n:base64.b64decode(s,validate=True)for n,s in v['files'].items()}
assert hashlib.sha256(data['input-manifest.json']).hexdigest()==v['manifest']
manifest=json.loads(data['input-manifest.json'])
assert set(data)==set(manifest['files'])|{'input-manifest.json'}
for name,raw in data.items():
 p=pathlib.Path(name);assert not p.is_absolute()and '..'not in p.parts
 if name!='input-manifest.json':assert hashlib.sha256(raw).hexdigest()==manifest['files'][name]
 target=root/p;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
 with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
 s=target.lstat();assert s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o400 and s.st_nlink==1
for folder,dirs,_ in os.walk(root,topdown=False):
 for name in dirs:os.chmod(pathlib.Path(folder)/name,0o700)
 fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
e=dict(at=time.time(),pid=os.getpid(),uid=os.getuid(),stage=str(root),manifest_sha256=v['manifest'],cgroup=str(cg),status='NATIVE_ROOT_INPUTS_STAGED')
fd=os.open(root/'native-start.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
with os.fdopen(fd,'w')as f:json.dump(e,f);f.flush();os.fsync(f.fileno())
print(json.dumps(e),flush=True)
os.execv('/usr/bin/python3',['/usr/bin/python3','-I','-B',str(root/'root_resume_fixture_coordinator.py'),'--input-root',str(root),'--manifest-sha256',v['manifest']])
'''.replace('PAYLOAD', repr(payload))


def run(head, gate):
    assert not (P/(N+'.capacity-claim.json')).exists(), 'Existing operation must be recovered; never redispatch'
    files, receipt = inputs(head, gate)
    profile = dict(lane=N, role=ROLE, model=None,
                   aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=2*G, forward_disk_bytes=G,
                   native_unit=UNIT, native_namespace='system', no_auto_retry=True, source_commit=head,
                   manifest_sha256=receipt['manifest_sha256'])
    admission.N = N
    admission.PROFILE = profile
    handles = []
    try:
        for path in [admission.d.ROOT/'.task-state/gtm-continue-20261012/vm-launch.lock',
                     cap.LEDGER.parent/'shared-capacity-reservations-20261018.owner-update.lock']:
            handle = path.open('a+')
            fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB); handles.append(handle)
        before, ledger, proof = admission.guard()
        stamp = dt.datetime.now(dt.timezone.utc)
        allocation = dict(owner='Bakeoff', authority='Operator bakeoff execution; qualified exact source and existing complete Root fixture',
                          reserved_now=True, captured_at=stamp.isoformat(), expires=(stamp+dt.timedelta(minutes=45)).isoformat(),
                          profiles={N:profile}, aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=2*G,
                          forward_disk_bytes=G, actual_models=0, remaining_actor_claim=1, setup_granted=True,
                          native_unit=UNIT, native_namespace='system', no_auto_retry=True)
        ledger['Bakeoff'] = allocation; ledger['setup_owner'] = 'Bakeoff'; ledger['updated_at'] = stamp.isoformat()
        ledger['pending_reservations'] = [r for r in ledger['pending_reservations'] if not r['owner'].startswith('Bake-')]+[
            dict(owner='Bake-'+N, reserved_bytes=G, source=head, owner_receipt=str(cap.OWNER))]
        assert cap.LEDGER.read_bytes() == before
        owner = json.loads(cap.OWNER.read_text())
        owner.update(captured_at=stamp.isoformat(), remaining_forward_disk_bytes=G,
                     exact_self_reserved_profiles={N:profile}, reserved_now=True, setup_in_progress=True,
                     remaining_actor_claim=1, actual_own_model_processes=0, active_own_handles_nonces=[UNIT])
        cap.persist(P/(N+'.capacity-claim.json'), dict(allocation, guard=proof, prepared_inputs=receipt))
        cap.persist(cap.LEASE, allocation); cap.persist(cap.OWNER, owner); cap.persist(cap.LEDGER, ledger)
    finally:
        while handles:
            handle=handles.pop(); fcntl.flock(handle,fcntl.LOCK_UN); handle.close()
    command = ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','ubuntu@acx-backend.tail1a44b8.ts.net',
               'sudo -n systemd-run --scope --quiet --collect --unit='+UNIT+
               ' --property=CPUQuota=50% --property=MemoryMax=2147483648 /usr/bin/python3 -I -B -']
    with (P/(N+'.stdout.log')).open('xb') as stdout, (P/(N+'.stderr.log')).open('xb') as stderr:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
        child.stdin.write(bootstrap(files, receipt).encode()); child.stdin.close()
        cap.persist(P/(N+'.ssh-handle.json'),dict(pid=child.pid,unit=UNIT,at=time.time(),stage=receipt['stage']))
        print(json.dumps(dict(status='NATIVE_ROOT_TRANSPORT_STARTED',pid=child.pid,unit=UNIT,stage=receipt['stage'])),flush=True)
        # Uncertain Root descendants are retained. There is deliberately no timeout kill.
        rc = child.wait()
        stdout.flush(); stderr.flush(); os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
    cap.persist(P/(N+'.transport-terminal.json'),dict(at=time.time(),exit_code=rc,unit=UNIT,stage=receipt['stage'],
                                                     no_qualification_or_resource_return_inferred=True))
    print(json.dumps(dict(status='ROOT_TRANSPORT_TERMINAL',exit_code=rc)),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--head',required=True)
    parser.add_argument('--gate',required=True)
    args = parser.parse_args()
    run(args.head,args.gate)
