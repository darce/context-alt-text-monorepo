"""One bounded borrowed-runtime observation through the qualified existing CLI.

Executed only inside the declared Root scope on the remote backend. No model
server, weights, shared cache, production service or foreign process is changed.
"""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import time
import uuid

assert os.geteuid()==os.getuid()==0
cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
assert(cg/'cpu.max').read_text().strip()=='50000 100000'and(cg/'memory.max').read_text().strip()=='2147483648'
N='QWEN38-GSQ-ALL38-LONG-R20C'
SOURCE='ab94e904ca25e2e031ad241f2600aa0406201c15'
KEY='feature-bakerounds-20261017-raw-auth-ini-3255682b'
repo=Path('/home/gate/workbay-sandbox')/KEY
python=repo.parent/('.venv-lane-'+KEY)/'bin/python'
stage=Path('/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure')
window=Path('/tmp/qwen-owner-window.rcqmefq9')
wid='223eb2de-b63a-4b19-a31e-a34d07a8e187'
endpoint='http://10.0.1.9:8000'
base=Path('/home/gate/bakeoff-rounds-20261017-inputs/results')/(N+'-'+uuid.uuid4().hex)
base.mkdir(mode=0o700);os.chown(base,1002,1002)
permanent=base/'permanent';permanent.mkdir(mode=0o700);os.chown(permanent,1002,1002)
workspace=Path('/home/gate/bakeoff-rounds-20261017-inputs/results/RAW-INCUMBENT-OBSERVATION-R1-0c2012a4be0649188b54942696474aa6/workspace');keyfile=base/'private-api-key'
owned_start=None;safe_withdraw=True;key_bytes=None;maintenance_attempted=False;child=None;maintenance_root=None
env=dict(PATH='/usr/local/bin:/usr/bin:/bin',HOME='/home/gate',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')


def save(name,value):
    path=permanent/name
    with path.open('x')as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    path.chmod(0o400)


def gate(command,**kw):
    return subprocess.run(command,user=1002,group=1002,extra_groups=[],env=env,**kw)


def public(arguments,label,timeout):
    command=['/usr/bin/python3','-I','-B',str(stage/'owner-window.py'),*arguments]
    q=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
    save(label+'.json',dict(arguments=arguments,exit_code=q.returncode,stdout=q.stdout,stderr=q.stderr))
    assert q.returncode==0,label+' refused; retain exact window'
    return q.stdout.strip()


def observe(op,phase,label,timeout):
    out=public(['outdir',str(window),phase],label+'-directory',10)
    q=subprocess.run(['/usr/bin/python3','-I','-B',str(stage/'observe.py'),str(window/'ops'/op/'publication.json'),out,phase],capture_output=True,text=True,timeout=timeout)
    save(label+'.json',dict(exit_code=q.returncode,stdout=q.stdout,stderr=q.stderr,output=out))
    assert q.returncode==0,label+' observation unknown'
    return Path(out)


def guest(command,timeout=20):
    prefix=['sudo','-n','-H','-u','ubuntu','ssh','-n','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','ConnectionAttempts=1','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','-o','UserKnownHostsFile=/home/ubuntu/.ssh/known_hosts','ubuntu@10.0.1.9']
    try:q=subprocess.run(prefix+[command],capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired as e:
        err=(e.stderr or b'').decode(errors='replace')
        save('guest-timeout-'+uuid.uuid4().hex+'.json',dict(timeout=timeout,stderr=re.sub(r'[0-9a-fA-F]{64}','<redacted>',err),stdout_bytes=len(e.stdout or b'')))
        raise
    if q.returncode:
        save('guest-failure-'+uuid.uuid4().hex+'.json',dict(exit_code=q.returncode,stderr=re.sub(r'[0-9a-fA-F]{64}','<redacted>',q.stderr.decode(errors='replace')),stdout_bytes=len(q.stdout),stdout_sha256=hashlib.sha256(q.stdout).hexdigest()))
    assert q.returncode==0,'Guest operation failed; redacted error retained'
    return q.stdout


try:
    assert hashlib.sha256((stage/'owner-window.py').read_bytes()).hexdigest()=='033d187835c9243bd486b185167563c16ef24812eb26f174ea062fc46fe798e9'
    assert hashlib.sha256((stage/'approved-scripts.json').read_bytes()).hexdigest()=='45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca'
    pointer=Path('/home/gate/bakeoff-rounds-20261017-inputs/results/INPUT-AMENDMENTS-20261017/regression-replace/proposed-ready-pointers.json')
    assert hashlib.sha256(pointer.read_bytes()).hexdigest()=='00323fb7739ebc0a8d6ded0f75984b7bba878cdf0c12622e9231ddd5f98cdd2e'
    data=json.loads(pointer.read_bytes());manifest=Path('/home/gate/bakeoff-rounds-20261017-inputs/results/RAW-INCUMBENT-OBSERVATION-R1-0c2012a4be0649188b54942696474aa6/workspace/apps/prototype-description-service/scene/tests/seed/bakeoff_golden.json')
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()=='2318b216d2124b038b3e4e9f60e47a8b6d61fc3d72945bb61a9641465fb08b7b'
    q=gate(['git','-C',str(repo),'rev-parse','HEAD'],capture_output=True,text=True,timeout=10);assert q.returncode==0 and q.stdout.strip()==SOURCE
    q=gate(['git','-C',str(workspace),'rev-parse','HEAD'],capture_output=True,text=True,timeout=10);assert q.returncode==0 and q.stdout.strip()==SOURCE
    q=gate(['git','-C',str(workspace),'diff','--name-only'],capture_output=True,text=True,timeout=15);assert q.returncode==0 and not q.stdout.strip(),'Warm source changed'
    save('source-and-input.json',dict(source_head=SOURCE,workspace=str(workspace),manifest=str(manifest),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),images_dir=data['images_dir'],role='owned_MiniCPM46_all38_one_residency_restore_Qwen',limit=38,quality_ground_truth=False,adoption_decision=17805,client_uid=1002,client_cgroup=str(cg),request_budget=76,request_budget_unit='completion POSTs',metadata_GET_budget=3,total_HTTP_budget=79,scope='authorized_single_GPU_maintenance_restore_Qwen'))
    save('runtime-recipe-amendment.json',dict(candidate='qwen3.8-27b-gsq-rco-gguf',variant='server-thinking-disabled-v1',server_flags=['--reasoning-budget','0','--chat-template-kwargs','{"enable_thinking":false}'],prompts_changed=False,token_budgets_changed=False,seed=0,prior_control='MINICPM45-RESPONSE-DIAGNOSTIC-R4',rationale='Prospective common fixed nonthinking v3 two-pass seed0 recipe on exact registered qwen3.8-27b-gsq-rco-gguf IQ3_S; all38 attempted, errors retained, no selective retry',completeness_policy='all cohort items attempted; errors remain errors; max76POSTs/1200s; priorR5 partial retained separately'))
    prior=Path('/home/gate/bakeoff-rounds-20261017-inputs/results/MINICPM46-ALL-IMAGES-R12-e45713cbaea143d48b994b1cb2fc15a3')
    extra_manifest=prior/'supplemental-eight.json';images=prior/'batch-images'
    cohorts=[dict(id='selection10',manifest=str(manifest),count=10),dict(id='heldout20',manifest=str(workspace/'apps/prototype-description-service/scene/tests/seed/held_out_golden.json'),count=20),dict(id='supplemental8',manifest=str(extra_manifest),count=8)]
    for cohort in cohorts:
        checked=gate([str(python),'-B','-c','import json,sys;from scripts.eval_harness.manifest import load_manifest;m=load_manifest(sys.argv[1],images_dir=sys.argv[2]);print(json.dumps(dict(entries=len(m.entries))))',cohort['manifest'],str(images)],cwd=workspace/'apps/prototype-description-service',capture_output=True,text=True,timeout=30)
        assert checked.returncode==0 and json.loads(checked.stdout)['entries']==cohort['count']
    all_entries=[entry for row in cohorts for entry in json.loads(Path(row['manifest']).read_bytes())['entries']];assert len(all_entries)==len({x['sha256']for x in all_entries})==38
    data=dict(data,images_dir=str(images));save('all-images-batch-plan.json',dict(cohorts=cohorts,images_dir=str(images),total_distinct_images=38,one_model_residency=True,selection_and_heldout_unchanged=True))
    prior_state=json.loads(Path('/run/acx/gpu-state.json').read_bytes());assert prior_state['state']=='stopped' and prior_state.get('lease_expires_at')is None,'Prior physical GPU lease must close before a new START'
    previous=public(['reconcile',str(window),wid],'before-reconcile',45)
    assert previous=='92c15692-6da6-4727-bc2b-3687e9f95874','Unexpected current operation; do not replace another publication'
    print(json.dumps(dict(status='PRIVATE_RAW_WORKSPACE_READY',directory=str(base),source=SOURCE,pid=os.getpid(),uid=os.getuid(),cgroup=str(cg),at=time.time())),flush=True)
    owned_start=public(['start',str(window),previous],'start',45)
    out=observe(owned_start,'start','start-observe',310)
    started=json.loads((out/'start-observed.json').read_bytes());state=started['state']
    assert state['instance_id']=='ocid1.instance.oc1.iad.anuwcljt2mcagaqcoop3g4euuthldjy6wbrhmh5yfjgznxdg353urol27bfa','Alternate winner; no guest probe'
    publication=json.loads((window/'ops'/owned_start/'publication.json').read_bytes())
    expires=min(dt.datetime.fromisoformat(state['lease_expires_at'].replace('Z','+00:00')).timestamp(),dt.datetime.fromisoformat(publication['expires_at'].replace('Z','+00:00')).timestamp())
    assert expires-time.time()>=1450,'Insufficient actual lease for identity and raw operation'
    save('start-boundary.json',dict(operation=owned_start,instance_id=state['instance_id'],lease_expires_at=state['lease_expires_at'],observation_directory=str(out)))
    print(json.dumps(dict(status='PRIMARY_RESUMED',operation=owned_start,remaining_lease_seconds=round(expires-time.time()))),flush=True)
    identity_code=r'''import hashlib,json,os,pathlib,subprocess,time
def q(a,t=8):return subprocess.check_output(a,text=True,timeout=t)
assert os.geteuid()==0
instance=q(['curl','--fail','--silent','--show-error','--connect-timeout','5','--max-time','10','-H','Authorization: Bearer Oracle','http://169.254.169.254/opc/v2/instance/id'],15).strip()
assert instance=='ocid1.instance.oc1.iad.anuwcljt2mcagaqcoop3g4euuthldjy6wbrhmh5yfjgznxdg353urol27bfa'
c=json.loads(q(['docker','inspect','acx-gpu-vlm']))[0];pid=c['State']['Pid'];assert c['State']['Running']and pid>0
paths=[pathlib.Path('/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-q4.gguf'),pathlib.Path('/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-mmproj.gguf')]
def stats():return [dict(path=str(p),bytes=p.stat().st_size,ino=p.stat().st_ino,mtime_ns=p.stat().st_mtime_ns)for p in paths]
before=stats();raw=q(['timeout','--kill-after=5s','120s','sha256sum','--',*[str(p)for p in paths]],130);after=stats();assert before==after
digests=[line.split()[0]for line in raw.splitlines()];assert len(digests)==2
with open('/proc/'+str(pid)+'/exe','rb')as f:binary=hashlib.file_digest(f,'sha256').hexdigest()
image=json.loads(q(['docker','image','inspect',c['Image']]))[0]
version_result=subprocess.run(['timeout','--kill-after=2s','10s','docker','exec','acx-gpu-vlm','/app/llama-server','--version'],capture_output=True,text=True,timeout=15)
version=version_result.stdout+version_result.stderr
now=json.loads(q(['docker','inspect','acx-gpu-vlm']))[0];assert now['Id']==c['Id']and now['State']['Pid']==pid
args=c['Config'].get('Cmd')or[];allowed={}
for i,a in enumerate(args):
 if a in ['--model','--mmproj','--ctx-size','--parallel','--n-gpu-layers','--batch-size','--ubatch-size']and i+1<len(args):allowed[a]=args[i+1]
print(json.dumps(dict(at=time.time(),instance_id=instance,boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),container_id=c['Id'],container_pid=pid,image_id=c['Image'],repo_digests=image.get('RepoDigests'),model_sha256=digests[0],projector_sha256=digests[1],weight_before=before,weight_after=after,binary_sha256=binary,binary_path=os.readlink('/proc/'+str(pid)+'/exe'),version=version,version_exit=version_result.returncode,arguments=allowed,container_memory_limit=c['HostConfig'].get('Memory'),container_NanoCPUs=c['HostConfig'].get('NanoCpus'),cgroup=pathlib.Path('/proc',str(pid),'cgroup').read_text(),GPU=q(['nvidia-smi','--query-gpu=uuid,index,name,memory.total,memory.free,memory.used','--format=csv,noheader,nounits']),GPU_processes=q(['nvidia-smi','--query-compute-apps=pid,process_name,used_gpu_memory','--format=csv,noheader,nounits']))))
'''
    identity=json.loads(guest('sudo -n /usr/bin/python3 -I -B -c '+shlex.quote(identity_code),180))
    save('runtime-identity.json',identity)
    assert identity['image_id']=='sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb' and identity['binary_sha256']=='59a74a6528e0dcedfb89e6a3df41b8dbd593a2c3689096a2d030ad1c67ffe4d0','Observed runtime image or binary changed'
    save('incumbent-before-maintenance.json',dict(status='OBSERVED_OFFICIAL_QWEN_REFERENCE',upstream_artifact_identity='Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF@f54435e6cc31258f04b0969105c3f6badb197931',registered_candidate=False,model_adoption=False,comparison_or_quality_claim=False,model_sha256=identity['model_sha256'],projector_sha256=identity['projector_sha256'],first_identity_receipt='/Volumes/Butter/WorkBay/custody/raw-incumbent-r1-identity-refusal-20261018/full-source-worktree-git-metadata-private.tar'))
    assert identity['version_exit']==0 and 'llama-server'in Path(identity['binary_path']).name,'Actual serving binary is not independently qualified'
    assert identity['model_sha256']=='87bb374d849f80ebdfabb304189fac9e0bd35a0f74506e6a59c51b206cbe863b','Observed installed snapshot changed'
    assert identity['projector_sha256']=='cae72cf123cc9e08d553cd5a5055d6d3cf0f82652aa41c3e4aa424cda9a26f7f','Observed installed projector snapshot changed'
    builds=[int(v)for v in re.findall(r'\bb(\d{4,})\b',identity['version'])]
    numeric=re.findall(r'version:\s*(\d{4,})\b',identity['version'])
    assert max(builds+[int(v)for v in numeric]+[0])>=6887,'Actual serving build is not independently qualified'
    assert expires-time.time()>=1450,'Insufficient remaining lease; no inference started'
    operation=base.name.rsplit('-',1)[1]
    maintenance_root='/run/bakeoff-minicpm45-'+operation
    candidate_unit='workbay-bakeoff-minicpm45-'+operation+'.service'
    spec={'cache': '/opt/acx-gpu/bakeoff-owned-cache/qwen3.8-27b-gsq-rco-gguf-d562806dbafae37109975e970aae91b43e73b440', 'components': {'Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf': {'bytes': 11771546784, 'sha256': '64b53b64c7aa39f20a7e54bd80582fe595b1d745624ee8a72e92508c0326d810'}, 'mmproj-Qwen3.8-27B-BF16.gguf': {'bytes': 931146528, 'sha256': '13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16'}}, 'image_id': 'sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb', 'qwen_config_sha256': '60b918fa38f308933e08bbbcf881d66336c2567b786764a095430c7313710849', 'qwen_binary_sha256': '59a74a6528e0dcedfb89e6a3df41b8dbd593a2c3689096a2d030ad1c67ffe4d0', 'restore_program_b64': 'IiIiT3duZWQgbWFpbnRlbmFuY2UgY2xlYW51cDsgcmVzdG9yZSB0aGUgdW5jaGFuZ2VkLCBlbmFibGVkIFF3ZW4gdW5pdC4iIiIKaW1wb3J0IGZjbnRsCmltcG9ydCBoYXNobGliCmltcG9ydCBqc29uCmltcG9ydCBvcwpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKaW1wb3J0IHN1YnByb2Nlc3MKaW1wb3J0IHN5cwppbXBvcnQgdGltZQppbXBvcnQgdXJsbGliLnJlcXVlc3QKCnJvb3Q9UGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpLnBhcmVudAphc3NlcnQgb3MuZ2V0ZXVpZCgpPT0wIGFuZCByb290LnBhcmVudD09UGF0aCgnL3J1bicpIGFuZCByb290Lm5hbWUuc3RhcnRzd2l0aCgnYmFrZW9mZi1taW5pY3BtNDUtJykKdj1qc29uLmxvYWRzKChyb290LydiZWZvcmUuanNvbicpLnJlYWRfYnl0ZXMoKSkKZGVmIHJ1bihhcmdzLHRpbWVvdXQ9MjApOnJldHVybiBzdWJwcm9jZXNzLnJ1bihhcmdzLGNhcHR1cmVfb3V0cHV0PVRydWUsdGV4dD1UcnVlLHRpbWVvdXQ9dGltZW91dCkKZGVmIGNvbmZpZ19oYXNoKGMpOnJldHVybiBoYXNobGliLnNoYTI1Nihqc29uLmR1bXBzKHtrOmNbJ0NvbmZpZyddLmdldChrKWZvciBrIGluIFsnSW1hZ2UnLCdDbWQnLCdFbnRyeXBvaW50JywnRW52JywnV29ya2luZ0RpcicsJ1VzZXInXX0sc29ydF9rZXlzPVRydWUpLmVuY29kZSgpKS5oZXhkaWdlc3QoKQp3aXRoKHJvb3QvJ3Jlc3RvcmUubG9jaycpLm9wZW4oJ2ErJylhcyBsb2NrOgogZmNudGwuZmxvY2sobG9jayxmY250bC5MT0NLX0VYKQogaWYocm9vdC8ncmVzdG9yZWQuanNvbicpLmV4aXN0cygpOgogIHByaW50KChyb290LydyZXN0b3JlZC5qc29uJykucmVhZF90ZXh0KCkpO3JhaXNlIFN5c3RlbUV4aXQoMCkKIHE9cnVuKFsnZG9ja2VyJywnaW5zcGVjdCcsdlsnY2FuZGlkYXRlX25hbWUnXV0pCiBpZiBxLnJldHVybmNvZGU9PTA6CiAgYz1qc29uLmxvYWRzKHEuc3Rkb3V0KVswXTtsYWJlbHM9Y1snQ29uZmlnJ10uZ2V0KCdMYWJlbHMnKW9ye30KICBhc3NlcnQgbGFiZWxzLmdldCgnd29ya2JheS5vd25lcicpPT0nQmFrZW9mZidhbmQgbGFiZWxzLmdldCgnd29ya2JheS5vcGVyYXRpb24nKT09dlsnb3BlcmF0aW9uJ11hbmQgY1snSW1hZ2UnXT09dlsnaW1hZ2VfaWQnXQogIHN0b3BwZWQ9cnVuKFsnZG9ja2VyJywnc3RvcCcsJy0tdGltZScsJzEwJyxjWydJZCddXSwyNSkKICBpZiBzdG9wcGVkLnJldHVybmNvZGUhPTA6YXNzZXJ0IHJ1bihbJ2RvY2tlcicsJ2luc3BlY3QnLGNbJ0lkJ11dKS5yZXR1cm5jb2RlIT0wCiBhc3NlcnQgcnVuKFsnZG9ja2VyJywnaW5zcGVjdCcsdlsnY2FuZGlkYXRlX25hbWUnXV0pLnJldHVybmNvZGUhPTAsJ093bmVkIGNhbmRpZGF0ZSBub3QgcmVhcGVkJwogZGVhZGxpbmU9dGltZS5tb25vdG9uaWMoKSs3NQogcT1ydW4oWydzeXN0ZW1jdGwnLCdzdGFydCcsJ2FjeC1ncHUtdmxtLnNlcnZpY2UnXSwzMCk7YXNzZXJ0IHEucmV0dXJuY29kZT09MCwnT3JpZ2luYWwgUXdlbiBzZXJ2aWNlIHJlc3RvcmUgZmFpbGVkJwogY29udGFpbmVyPU5vbmUKIHdoaWxlIHRpbWUubW9ub3RvbmljKCk8ZGVhZGxpbmU6CiAgcT1ydW4oWydkb2NrZXInLCdpbnNwZWN0JywnYWN4LWdwdS12bG0nXSw4KQogIGlmIHEucmV0dXJuY29kZT09MDoKICAgYz1qc29uLmxvYWRzKHEuc3Rkb3V0KVswXQogICBpZiBjWydTdGF0ZSddWydSdW5uaW5nJ106CiAgICBhc3NlcnQgY1snSW1hZ2UnXT09dlsnaW1hZ2VfaWQnXWFuZCBjb25maWdfaGFzaChjKT09dlsncXdlbl9jb25maWdfc2hhMjU2J10sJ09yaWdpbmFsIFF3ZW4gY29uZmlndXJhdGlvbiBjaGFuZ2VkJwogICAgYXNzZXJ0IGNbJ0hvc3RDb25maWcnXVsnTmV0d29ya01vZGUnXT09dlsnb3JpZ2luYWxfbmV0d29ya19tb2RlJ11hbmQgY1snSG9zdENvbmZpZyddWydQb3J0QmluZGluZ3MnXT09dlsnb3JpZ2luYWxfcG9ydF9iaW5kaW5ncyddLCdPcmlnaW5hbCBRd2VuIG5ldHdvcmsgcm91dGUgY2hhbmdlZCcKICAgIHRyeToKICAgICB3aXRoIHVybGxpYi5yZXF1ZXN0LnVybG9wZW4oJ2h0dHA6Ly8xMjcuMC4wLjE6ODAwMC9oZWFsdGgnLHRpbWVvdXQ9MylhcyByZXNwb25zZTpvaz1yZXNwb25zZS5zdGF0dXM9PTIwMAogICAgZXhjZXB0IEV4Y2VwdGlvbjpvaz1GYWxzZQogICAgaWYgb2s6Y29udGFpbmVyPWM7YnJlYWsKICB0aW1lLnNsZWVwKC41KQogYXNzZXJ0IGNvbnRhaW5lciBpcyBub3QgTm9uZSwnT3JpZ2luYWwgUXdlbiByZWFkaW5lc3MgdW5rbm93bicKIGZvciByb3cgaW4gdlsncXdlbl93ZWlnaHRfc3RhdHMnXToKICBwPVBhdGgocm93WydwYXRoJ10pO3M9cC5zdGF0KCk7YXNzZXJ0IGRpY3QocGF0aD1zdHIocCksYnl0ZXM9cy5zdF9zaXplLGlubz1zLnN0X2lubyxtdGltZV9ucz1zLnN0X210aW1lX25zKT09cm93CiB3aXRoIG9wZW4oJy9wcm9jLycrc3RyKGNvbnRhaW5lclsnU3RhdGUnXVsnUGlkJ10pKycvZXhlJywncmInKWFzIGY6YmluYXJ5PWhhc2hsaWIuZmlsZV9kaWdlc3QoZiwnc2hhMjU2JykuaGV4ZGlnZXN0KCkKIGFzc2VydCBiaW5hcnk9PXZbJ3F3ZW5fYmluYXJ5X3NoYTI1NiddCiAocm9vdC8nYXBpLWtleScpLnVubGluayhtaXNzaW5nX29rPVRydWUpCiByZWNlaXB0PWRpY3QoYXQ9dGltZS50aW1lKCksb3JpZ2luYWxfUXdlbl9yZXN0b3JlZD1UcnVlLFF3ZW5fcmVhZHlfSFRUUD0yMDAsUXdlbl9jb25maWdfc2hhMjU2PXZbJ3F3ZW5fY29uZmlnX3NoYTI1NiddLGltYWdlX2lkPWNvbnRhaW5lclsnSW1hZ2UnXSxiaW5hcnlfc2hhMjU2PWJpbmFyeSxjYW5kaWRhdGVfYWJzZW50PVRydWUsZ3Vlc3RfcHJpdmF0ZV9rZXlfYWJzZW50PVRydWUsY29udGFpbmVyX2lkPWNvbnRhaW5lclsnSWQnXSxjb250YWluZXJfcGlkPWNvbnRhaW5lclsnU3RhdGUnXVsnUGlkJ10sd2VpZ2h0X3N0YXRzX3VuY2hhbmdlZD1UcnVlKQogd2l0aChyb290LydyZXN0b3JlZC5qc29uJykub3BlbigneCcpYXMgZjpqc29uLmR1bXAocmVjZWlwdCxmLHNvcnRfa2V5cz1UcnVlKTtmLmZsdXNoKCk7b3MuZnN5bmMoZi5maWxlbm8oKSkKIHByaW50KGpzb24uZHVtcHMocmVjZWlwdCkpCg==', 'restore_program_sha256': '88ded798eedb75969a0c762c4a760312265f6cda9221e00c0589ed3e16b2b1dd', 'original_network_mode': 'bridge', 'original_port_bindings': {'8000/tcp': [{'HostIp': '', 'HostPort': '8000'}]}}
    spec.update(operation=operation,candidate_name='wb-bake-minicpm45-'+operation,unit=candidate_unit)
    setup_program='"""Start one bounded candidate; ExecStopPost independently restores Qwen."""\nimport base64\nimport hashlib\nimport json\nimport os\nfrom pathlib import Path\nimport secrets\nimport subprocess\nimport time\nimport urllib.request\nimport urllib.error\n\nv=CONFIG\nassert os.geteuid()==0\ndef run(args,timeout=15):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)\ndef container_absent(name,timeout=8):\n result=run([\'docker\',\'inspect\',name],timeout)\n assert result.returncode==1 and result.stderr.strip()in(\'Error: No such object: \'+name,\'Error: No such container: \'+name,\'error: no such object: \'+name),\'Container absence unknown; retain exact operation\'\ndef stop_original():\n # Native TimeoutStopUSec is 90s; stop plus postconditions share 110s.\n deadline=time.monotonic()+110\n def budget(maximum):\n  remaining=deadline-time.monotonic();assert remaining>0,\'Original stop deadline exhausted\'\n  return min(maximum,remaining)\n run([\'systemctl\',\'stop\',\'acx-gpu-vlm.service\'],budget(110))\n unit=run([\'systemctl\',\'show\',\'acx-gpu-vlm.service\',\'--all\',\'-p\',\'ActiveState\',\'-p\',\'MainPID\',\'-p\',\'ControlGroup\',\'-p\',\'Job\'],budget(8))\n assert unit.returncode==0,\'Original stop state unknown\'\n fields=dict(line.split(\'=\',1)for line in unit.stdout.splitlines()if \'=\'in line)\n assert fields.get(\'ActiveState\')in(\'inactive\',\'failed\')and fields.get(\'MainPID\')==\'0\'and fields.get(\'ControlGroup\')==\'\'and fields.get(\'Job\')==\'\',\'Original stop not quiescent\'\n container_absent(\'acx-gpu-vlm\',budget(8))\n assert time.monotonic()<deadline,\'Original stop deadline exhausted\'\ndef config_hash(c):return hashlib.sha256(json.dumps({k:c[\'Config\'].get(k)for k in [\'Image\',\'Cmd\',\'Entrypoint\',\'Env\',\'WorkingDir\',\'User\']},sort_keys=True).encode()).hexdigest()\nunit=run([\'systemctl\',\'show\',\'acx-gpu-vlm.service\',\'-p\',\'ActiveState\',\'-p\',\'UnitFileState\']);assert unit.returncode==0 and\'ActiveState=active\'in unit.stdout and\'UnitFileState=enabled\'in unit.stdout\nbefore=json.loads(run([\'docker\',\'inspect\',\'acx-gpu-vlm\']).stdout)[0];assert before[\'State\'][\'Running\']and before[\'Image\']==v[\'image_id\']and config_hash(before)==v[\'qwen_config_sha256\']\nassert before[\'HostConfig\'][\'AutoRemove\'],\'Verify alternate original container lifecycle before maintenance\'\nassert before[\'HostConfig\'][\'NetworkMode\']==v[\'original_network_mode\']and before[\'HostConfig\'][\'PortBindings\']==v[\'original_port_bindings\'],\'Original published-port route changed\'\nassert os.cpu_count()>=5 and int(next(x for x in Path(\'/proc/meminfo\').read_text().splitlines()if x.startswith(\'MemAvailable:\')).split()[1])*1024>=40*1024**3\ncache=Path(v[\'cache\']);assert cache.parent==Path(\'/opt/acx-gpu/bakeoff-owned-cache\')and not cache.is_symlink()\nfor name,expected in v[\'components\'].items():\n p=cache/name;assert p.is_file()and not p.is_symlink()and p.stat().st_size==expected[\'bytes\']\n with p.open(\'rb\')as f:assert hashlib.file_digest(f,\'sha256\').hexdigest()==expected[\'sha256\']\nhelp_result=run([\'docker\',\'exec\',\'acx-gpu-vlm\',\'/app/llama-server\',\'--help\'],15);assert help_result.returncode==0\nfor flag in [\'--batch-size\',\'--ubatch-size\',\'--image-max-tokens\',\'--api-key-file\',\'--parallel\',\'--mmproj\',\'--ctx-size\',\'--reasoning-budget\',\'--chat-template-kwargs\']:assert flag in help_result.stdout+help_result.stderr,\'Serving flag unsupported: \'+flag\nroot=Path(\'/run\')/(\'bakeoff-minicpm45-\'+v[\'operation\']);root.mkdir(mode=0o700)\nrestore=base64.b64decode(v[\'restore_program_b64\'],validate=True);assert hashlib.sha256(restore).hexdigest()==v[\'restore_program_sha256\']\nwith(root/\'restore.py\').open(\'xb\')as f:f.write(restore);f.flush();os.fsync(f.fileno())\n(root/\'restore.py\').chmod(0o400)\nkey=secrets.token_hex(32).encode()\nfd=os.open(root/\'api-key\',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)\nwith os.fdopen(fd,\'wb\')as f:f.write(key);f.flush();os.fsync(f.fileno())\nv.pop(\'restore_program_b64\');v[\'qwen_weight_stats\']=[]\nfor path in [\'/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-q4.gguf\',\'/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-mmproj.gguf\']:\n p=Path(path);s=p.stat();v[\'qwen_weight_stats\'].append(dict(path=str(p),bytes=s.st_size,ino=s.st_ino,mtime_ns=s.st_mtime_ns))\nwith(root/\'before.json\').open(\'x\')as f:json.dump(v,f,sort_keys=True);f.flush();os.fsync(f.fileno())\ncontainer_absent(v[\'candidate_name\'])\ncommand=[\'systemd-run\',\'--quiet\',\'--collect\',\'--unit=\'+v[\'unit\'],\'--property=CPUQuota=25%\',\'--property=MemoryMax=268435456\',\'--property=RuntimeMaxSec=1500\',\'--property=TimeoutStopSec=120\',\'--property=Restart=no\',\'--property=ExecStopPost=/usr/bin/python3 -I -B \'+str(root/\'restore.py\'),\'--\',\'/usr/bin/docker\',\'run\',\'--rm\',\'--pull=never\',\'--name\',v[\'candidate_name\'],\'--label\',\'workbay.owner=Bakeoff\',\'--label\',\'workbay.operation=\'+v[\'operation\'],\'--gpus\',\'device=0\',\'--network\',\'bridge\',\'--publish\',\'8000:8000\',\'--cpus\',\'4\',\'--memory\',str(32*1024**3),\'--memory-swap\',str(32*1024**3),\'--read-only\',\'--tmpfs\',\'/tmp:rw,nosuid,nodev,size=268435456\',\'--env\',\'CUDA_CACHE_PATH=/tmp/cuda-cache\',\'--cap-drop\',\'ALL\',\'--security-opt\',\'no-new-privileges\',\'--mount\',\'type=bind,src=\'+str(cache)+\',dst=/models,readonly\',\'--mount\',\'type=bind,src=\'+str(root/\'api-key\')+\',dst=/run/bakeoff-api-key,readonly\',\'--entrypoint\',\'/app/llama-server\',v[\'image_id\'],\'--model\',\'/models/Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf\',\'--mmproj\',\'/models/mmproj-Qwen3.8-27B-BF16.gguf\',\'--host\',\'0.0.0.0\',\'--port\',\'8000\',\'--ctx-size\',\'8192\',\'--batch-size\',\'2048\',\'--ubatch-size\',\'2048\',\'--image-max-tokens\',\'1536\',\'--parallel\',\'1\',\'--n-gpu-layers\',\'99\',\'--api-key-file\',\'/run/bakeoff-api-key\',\'--reasoning-budget\',\'0\',\'--chat-template-kwargs\',\'{"enable_thinking":false}\']\ntry:\n stop_original()\n started=run(command,20);assert started.returncode==0,\'Owned candidate service start refused\'\n deadline=time.monotonic()+150;candidate=None\n while time.monotonic()<deadline:\n  try:\n   request=urllib.request.Request(\'http://127.0.0.1:8000/health\',headers={\'Authorization\':\'Bearer \'+key.decode()})\n   with urllib.request.urlopen(request,timeout=min(3,deadline-time.monotonic()))as response:ready=response.status==200\n  except Exception:ready=False\n  remaining=deadline-time.monotonic()\n  if remaining<=0:break\n  q=run([\'docker\',\'inspect\',v[\'candidate_name\']],min(5,remaining))\n  if q.returncode==0:\n   c=json.loads(q.stdout)[0]\n   if ready and c[\'State\'][\'Running\']and time.monotonic()<deadline:candidate=c;break\n  elif(root/\'restored.json\').exists():break\n  time.sleep(min(.5,max(0,deadline-time.monotonic())))\n assert candidate is not None,\'Candidate readiness refused; original Qwen restoration required\'\n with open(\'/proc/\'+str(candidate[\'State\'][\'Pid\'])+\'/exe\',\'rb\')as f:binary=hashlib.file_digest(f,\'sha256\').hexdigest()\n assert candidate[\'Image\']==v[\'image_id\']and binary==v[\'qwen_binary_sha256\']\n probe=dict(private_file_matches_generated_key=(root/\'api-key\').read_bytes()==key)\n for label,headers in [(\'authorized\',{\'Authorization\':\'Bearer \'+key.decode()}),(\'anonymous\',{})]:\n  try:\n   request=urllib.request.Request(\'http://127.0.0.1:8000/v1/models\',headers=headers)\n   try:response=urllib.request.urlopen(request,timeout=5)\n   except urllib.error.HTTPError as e:response=e\n   with response:status=response.status;body=response.read(1024**2)\n   row=dict(status=status,response_bytes=len(body))\n   if status==200:\n    value=json.loads(body);row[\'top_level_keys\']=sorted(value)if isinstance(value,dict)else[]\n    models=value.get(\'data\')if isinstance(value,dict)else None\n    row[\'model_count\']=len(models)if isinstance(models,list)else None\n    row[\'model_ids\']=[str(x.get(\'id\',\'\'))[:256].replace(key.decode(),\'<credential-redacted>\')for x in models]if isinstance(models,list)else[]\n   probe[label]=row\n  except Exception as e:probe[label]=dict(error_type=type(e).__name__)\n with(root/\'metadata-probe.json\').open(\'x\')as f:json.dump(probe,f,sort_keys=True);f.flush();os.fsync(f.fileno())\n print(json.dumps(dict(at=time.time(),root=str(root),unit=v[\'unit\'],candidate_name=v[\'candidate_name\'],candidate_id=candidate[\'Id\'],candidate_pid=candidate[\'State\'][\'Pid\'],image_id=candidate[\'Image\'],binary_sha256=binary,credential_b64=base64.b64encode(key).decode(),guest_metadata_probe=probe,guest_model_CPU=4,guest_model_memory_bytes=32*1024**3,guest_control_CPU=.25,guest_control_memory_bytes=268435456,automatic_restore_RuntimeMaxSec=1500,original_Qwen_temporarily_stopped=True)))\nexcept BaseException:\n run([\'systemctl\',\'stop\',v[\'unit\']],120)\n restored=run([\'/usr/bin/python3\',\'-I\',\'-B\',str(root/\'restore.py\')],120)\n assert restored.returncode==0,\'Original Qwen restore unknown; retain operation\'\n raise\n'.replace('v=CONFIG','v='+repr(spec))
    safe_withdraw=False;maintenance_attempted=True
    command='sudo -n systemd-run --scope --quiet --collect --unit=workbay-bakeoff-minicpm45-setup-'+operation+'.scope --property=CPUQuota=200% --property=MemoryMax=42949672960 --property=RuntimeMaxSec=540 /usr/bin/python3 -I -B -c '+shlex.quote(setup_program)
    serving=json.loads(guest(command,570))
    encoded=serving.pop('credential_b64');secret=base64.b64decode(encoded,validate=True);assert len(secret)==64
    fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
    with os.fdopen(fd,'wb')as f:f.write(secret);f.flush();os.fsync(f.fileno())
    os.chown(keyfile,1002,1002);secret=None;encoded=None
    save('candidate-runtime.json',serving)
    assert expires-time.time()>=330,'Insufficient remaining intent for bounded client and Qwen restoration'
    metadata_code="import json,sys\nfrom scripts.eval_harness.bakeoff import BakeoffClient,_load_server_api_key\nkeypath=sys.argv[2]\nclient=BakeoffClient(sys.argv[1],model_id='metadata-only',model_version='qwen3.8-27b-gsq-rco-gguf-IQ3_S',model_revision='installed-snapshot',server_api_key=(None if keypath=='-'else _load_server_api_key(keypath)),timeout_s=5,prompt_variant='v3',two_pass=True)\nif keypath!='-':client._response_private_values+=(keypath, __import__('pathlib').Path(keypath).name)\ntry:\n payload=client._request_dict('GET','/v1/models');rows=payload.get('data')\n assert isinstance(rows,list)and len(rows)==1,'Expected one installed served model'\n value=rows[0].get('id');assert isinstance(value,str)and 0<len(value)<=256 and not any(ord(c)<32 for c in value)\n assert client._redact_response(value)==value,'Private response metadata refused'\n print(json.dumps(dict(id=value,identifier_scope='server-declared-only; upstream unverified')))\nfinally:client.close()\n"
    meta=gate([str(python),'-B','-c',metadata_code,endpoint,str(keyfile)],cwd=workspace/'apps/prototype-description-service',capture_output=True,text=True,timeout=15)
    redact_key=keyfile.read_text()
    def redact_metadata(value):
        return value.replace(redact_key,'<credential-redacted>').replace(str(keyfile),'<private-credential-file>').replace(keyfile.name,'<private-credential-file>')
    save('metadata-process.json',dict(exit_code=meta.returncode,stdout=redact_metadata(meta.stdout),stderr=redact_metadata(meta.stderr),keyfile_uid=keyfile.stat().st_uid,keyfile_mode=oct(stat.S_IMODE(keyfile.stat().st_mode)),keyfile_bytes=keyfile.stat().st_size,credential_values_suppressed=True))
    redact_key=None
    assert meta.returncode==0,'Candidate authenticated metadata refused'
    served=json.loads(meta.stdout);wire_model_id=served['id'];assert wire_model_id=='/models/Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf','Candidate model mismatch; no Qwen fallback';save('served-model-metadata.json',served)
    raw=permanent/'raw.json';clientenv=dict(env,ACX_EVAL_LIVE='1',GOLDEN_IMAGES_DIR=data['images_dir'])
    deadline=time.monotonic()+min(1200,int(expires-time.time()-105));assert deadline-time.monotonic()>=1100,'Insufficient fixed remaining residency for full batch'
    cohort_results=[];all_items=[];all_passes=[]
    for cohort in cohorts:
        remaining=int(deadline-time.monotonic())
        if remaining<5:
            cohort_results.append(dict(id=cohort['id'],requested_images=cohort['count'],evaluated_images=0,status='NOT_STARTED_FIXED_DEADLINE'));continue
        directory=permanent/cohort['id'];directory.mkdir(mode=0o700);os.chown(directory,1002,1002)
        raw=directory/'raw.json';manifest=Path(cohort['manifest'])
        command=[str(python),'-B','-c',"import json,os,sys\nfrom scripts.eval_harness import bakeoff as b\nfrom pathlib import Path\np=Path(sys.argv[1]);sys.argv=sys.argv[1:];expected=sys.argv[sys.argv.index('--model-id')+1];original=b.BakeoffClient._parse_response\ndef observed(self,parser,value):\n # Preserve actual completion envelope privately; no request/output changes.\n # No request or credential headers are recorded.\n path=p.parent/('completion-envelope-'+str(len(list(p.parent.glob('completion-envelope-*.json'))))+'.json')\n if isinstance(value,dict)and 'choices'in value:\n  cleaned=self._redact_response(value)\n  with path.open('x')as f:json.dump(cleaned,f,sort_keys=True);f.flush();os.fsync(f.fileno())\n  path.chmod(0o400)\n  if value.get('model')!=expected:raise SystemExit('Response model mismatch; batch stopped without further inference')\n return original(self,parser,value)\nb.BakeoffClient._parse_response=observed\nb.main(sys.argv[1:])\n",str(raw),'--endpoint',endpoint,'--server-api-key-file',str(keyfile),'--model-id',wire_model_id,'--model-version','qwen3.8-27b-gsq-rco-gguf-IQ3_S','--model-revision','sha256:64b53b64c7aa39f20a7e54bd80582fe595b1d745624ee8a72e92508c0326d810','--manifest',str(manifest),'--prompt-variant','v3','--caption-length','standard','--two-pass','--no-think','--seed','0','--limit',str(cohort['count']),'--stall-limit',str(cohort['count']),'--timeout','30','--warmup','0','--vram-sample-interval-s','0','--keep','1','--out',str(raw)]
        with(directory/'client.stdout').open('xb')as stdout,(directory/'client.stderr').open('xb')as stderr:
            child=subprocess.Popen(command,cwd=workspace/'apps/prototype-description-service',env=clientenv,user=1002,group=1002,extra_groups=[],start_new_session=True,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL)
            save('client-launch-'+cohort['id']+'.json',dict(pid=child.pid,start=time.time(),uid=1002,source_head=SOURCE,request_budget=2*cohort['count'],whole_batch_deadline_monotonic=deadline,remaining_batch_seconds=remaining,candidate_container=serving['candidate_id']))
            timed_out=False
            try:rc=child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out=True;os.killpg(child.pid,signal.SIGTERM)
                try:rc=child.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);rc=child.wait(timeout=5)
            stdout.flush();stderr.flush();os.fsync(stdout.fileno());os.fsync(stderr.fileno())
        if not raw.is_file()and raw.with_name('raw-aborted.json').is_file():raw=raw.with_name('raw-aborted.json')
        record=json.loads(raw.read_bytes())if raw.is_file()else None;items=record.get('items',[])if isinstance(record,dict)else[]
        passes=[v for i in items for v in(i.get('describe')or{}).get('passes',[])];errors=sum(bool(i.get('error'))for i in items)
        cohort_results.append(dict(id=cohort['id'],requested_images=cohort['count'],evaluated_images=len(items),item_errors=errors,raw_passes=len(passes),owned_client_exit=rc,owned_client_natively_reaped=True,owned_client_timed_out=timed_out,raw_path=str(raw),raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest()if raw.is_file()else None,execution_complete=len(items)==cohort['count']))
        all_items.extend(items);all_passes.extend(passes)
        if rc!=0:
            for later in cohorts[cohorts.index(cohort)+1:]:cohort_results.append(dict(id=later['id'],requested_images=later['count'],evaluated_images=0,status='NOT_STARTED_PRIOR_CLIENT_FAILURE'))
            break
        print(json.dumps(dict(status='COHORT_ATTEMPT_RECORDED',cohort=cohort['id'],items=len(items),errors=errors,remaining_batch_seconds=max(0,round(deadline-time.monotonic())))),flush=True)
    errors=sum(bool(i.get('error'))for i in all_items);complete=len(all_items)==38 and errors==0 and len(all_passes)==76
    save('candidate-result.json',dict(status='ALL38_RAW_COMPLETE'if complete else'ALL38_ATTEMPT_RECORDED',execution_complete=len(all_items)==38,complete=complete,requested_images=38,evaluated_images=len(all_items),item_errors=errors,raw_passes=len(all_passes),cohorts=cohort_results,one_model_residency=True,model_sha256=spec['components']['Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf']['sha256'],projector_sha256=spec['components']['mmproj-Qwen3.8-27B-BF16.gguf']['sha256'],source_head=SOURCE,authenticated_header_present=True,quality_or_winner=False,isolated_performance=False))
    print(json.dumps(dict(status='CANDIDATE_ATTEMPT_RECORDED',complete=complete,items=len(all_items),item_errors=errors,directory=str(base))),flush=True)

except BaseException as exc:
    save('failure.json',dict(exception_type=type(exc).__name__,detail=str(exc),maintenance_attempted=maintenance_attempted,owned_start=owned_start))
    print(json.dumps(dict(status='CANDIDATE_OPERATION_REFUSED',exception_type=type(exc).__name__,directory=str(base))),flush=True)
    raise
finally:
    if child is not None and child.poll()is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
    if keyfile.exists():keyfile.unlink()
    if maintenance_attempted:
        setup_proof_program="import json,subprocess;u=UNIT;v=dict(x.split('=',1)for x in subprocess.check_output(['systemctl','show',u,'-p','ActiveState','-p','ControlGroup'],text=True,timeout=8).splitlines()if '='in x);assert v['ActiveState']=='inactive'and not v['ControlGroup'],'Owned setup launcher remains active; retain before cleanup';print(json.dumps(v))".replace('UNIT',repr('workbay-bakeoff-minicpm45-setup-'+operation+'.scope'))
        setup_quiescent=json.loads(guest('sudo -n /usr/bin/python3 -I -B -c '+shlex.quote(setup_proof_program),20));save('setup-quiescent-before-cleanup.json',setup_quiescent)
        cleanup_program="import json,pathlib,subprocess\nroot=pathlib.Path(ROOT);unit=UNIT\nif(root/'before.json').exists():\n subprocess.run(['systemctl','stop',unit],capture_output=True,timeout=125)\n q=subprocess.run(['/usr/bin/python3','-I','-B',str(root/'restore.py')],capture_output=True,text=True,timeout=100);assert q.returncode==0,'Qwen restore unknown';print(q.stdout)\nelse:\n q=subprocess.check_output(['docker','inspect','acx-gpu-vlm'],text=True,timeout=8);c=json.loads(q)[0];assert c['State']['Running']and c['Image']==IMAGE\n if(root/'api-key').exists():(root/'api-key').unlink()\n print(json.dumps(dict(original_Qwen_restored=True,maintenance_never_started=True,image_id=c['Image'],guest_private_key_absent=True)))\n".replace('ROOT',repr(maintenance_root)).replace('UNIT',repr(candidate_unit)).replace('IMAGE',repr('sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb'))
        try:
            command='sudo -n systemd-run --scope --quiet --collect --unit=workbay-bakeoff-minicpm45-cleanup-'+operation+'.scope --property=CPUQuota=50% --property=MemoryMax=536870912 /usr/bin/python3 -I -B -c '+shlex.quote(cleanup_program)
            restored=json.loads(guest(command,245));assert restored['original_Qwen_restored']
            save('Qwen-restored.json',restored);safe_withdraw=True
        except BaseException as exc:
            save('RESTORE-UNKNOWN.json',dict(exception_type=type(exc).__name__,unit=candidate_unit,guest_root=maintenance_root,automatic_restore_RuntimeMaxSec=1500))
            safe_withdraw=False
    if safe_withdraw:
        current=public(['reconcile',str(window),wid],'before-lease-close',45)
        stopped=public(['stop',str(window),current],'close-completed-lease',75)
        observe(stopped,'stop','close-completed-lease-observe',195)
        save('completed-physical-lease-closed.json',dict(STOP=stopped,canonical_stopped=True,after_Qwen_restore=True,no_actor_or_request_active=True))
        op=public(['withdraw',str(window),wid],'withdraw',75)
        if op!='none':observe(op,'auto','auto-observe',190)
        save('owned-window-return.json',dict(at=time.time(),operation=op,owned_client_reaped=True,owned_candidate_reaped=True,Qwen_restored=True))
    else:raise RuntimeError('Qwen restoration unknown; retain exact actor/window/resources for recovery')
