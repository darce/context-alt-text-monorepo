"""One bounded borrowed-runtime observation through the qualified existing CLI.

Executed only inside the declared Root scope on the remote backend. The reviewed helper owns candidate preparation and original restoration.
"""
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import secrets
import signal
import stat
import subprocess
import time
import uuid


# RES-02 finite bounds; GRPH-33 producer contracts; DBG-11 actual failure evidence.
# Stable canon IDs: https://github.com/darce/heuristics-canon
HELPER_B64='__REVIEWED_HELPER_B64__'
HELPER_SHA256='__REVIEWED_HELPER_SHA256__'
MODEL_ID='Qwen/Qwen3-VL-8B-Instruct'
CANDIDATE_REF='vllm/vllm-openai@sha256:d8d39b59e909d2378ac4feeb191f7e7b6f1342477dc66b7c47cec89e9985ad8a'
CANDIDATE_IMAGE='sha256:d8d39b59e909d2378ac4feeb191f7e7b6f1342477dc66b7c47cec89e9985ad8a'
PROFILE=dict(runtime='vLLM v0.11 BF16',CPU=8,RAM=64*1024**3,GPU=1,context=8192,image_max_pixels=1572864,renderer_equal_to_llama=False)

def reviewed_helper(encoded,digest):
    if not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Unfilled helper pin')
    data=base64.b64decode(encoded,validate=True)
    if not 0<len(data)<=256*1024 or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Helper pin mismatch')
    return data

def transfer_payload(operation,route,helper,key):
    assert str(uuid.UUID(operation))==operation
    assert 32<=len(key)<=256 and re.fullmatch(rb'[A-Za-z0-9_-]+',key)
    spec=dict(version=1,operation=operation,original_network_mode=route['original_network_mode'],original_port_bindings=route['original_port_bindings'])
    assert len(json.dumps(spec).encode())<=16384
    return json.dumps(dict(operation=operation,spec=spec,helper=base64.b64encode(helper).decode(),helper_sha256=hashlib.sha256(helper).hexdigest(),key=key.decode('ascii'))).encode()

def require_restored(receipt):
    for field in ('original_Qwen_restored','candidate_absent','guest_private_key_absent'):
        if receipt.get(field)is not True:raise RuntimeError('Restoration unknown')

def restore_program(root,operation,unit):
    # Manual helper has its own 110s budget, following finite automatic stop.
    return "import subprocess,sys;root=ROOT;operation=OP;unit=UNIT;subprocess.run(['systemctl','stop',unit],capture_output=True,timeout=125);q=subprocess.run(['/usr/bin/python3','-I','-B',root+'/gpu_vllm_maintenance.py','restore','--operation',operation,'--spec',root+'/spec.json'],capture_output=True,timeout=110);assert q.returncode==0,'Restore unknown';sys.stdout.buffer.write(q.stdout)".replace('ROOT',repr(root)).replace('OP',repr(operation)).replace('UNIT',repr(unit))

SETUP_PROGRAM=r'''import base64,hashlib,json,os,pathlib,subprocess,sys,uuid
v=json.load(sys.stdin);operation=v['operation'];assert str(uuid.UUID(operation))==operation
root=pathlib.Path('/run')/('bakeoff-vllm-'+uuid.UUID(operation).hex)
helper=base64.b64decode(v['helper'],validate=True)
assert hashlib.sha256(helper).hexdigest()==v['helper_sha256']
spec=json.dumps(v['spec'],sort_keys=True).encode();assert len(spec)<=16384
assert set(v['spec'])=={'version','operation','original_network_mode','original_port_bindings'}
assert v['spec']['operation']==operation and v['spec']['version']==1
key=v['key'].encode('ascii');assert 32<=len(key)<=256 and all(c in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'for c in key)
assert os.geteuid()==0 and 0<len(helper)<=256*1024
root.mkdir(mode=0o700)
for name,data in [('gpu_vllm_maintenance.py',helper),('spec.json',spec),('api-key',key)]:
 fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
 with os.fdopen(fd,'wb')as f:f.write(data);f.flush();os.fsync(f.fileno())
 s=(root/name).lstat();assert s.st_uid==s.st_gid==0 and s.st_nlink==1 and s.st_mode&0o777==0o400
q=subprocess.run(['/usr/bin/python3','-I','-B',str(root/'gpu_vllm_maintenance.py'),'prepare','--operation',operation,'--spec',str(root/'spec.json')],capture_output=True,timeout=525)
assert q.returncode==0,'Reviewed prepare refused'
sys.stdout.buffer.write(q.stdout)
'''
MODEL_MANIFEST={'id': 'qwen3-vl-8b', 'revision': '0c351dd01ed87e9c1b53cbc748cba10e6187ff3b', 'cache': '/opt/acx-gpu/bakeoff-owned-cache/qwen3-vl-8b-0c351dd01ed87e9c1b53cbc748cba10e6187ff3b', 'components': {'chat_template.json': {'bytes': 5499, 'sha256': '5c72a170d2a4a1a3bc5adad2e689ae28138a9700e5b8c96c0266331e86c0acce', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/chat_template.json'}, 'config.json': {'bytes': 1474, 'sha256': '5cd452860dc1e9c29dd71cc3cef7f39b338b7a40793f7a260655c2d3568f3661', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/config.json'}, 'generation_config.json': {'bytes': 269, 'sha256': '8469742d1fce0de951c8909b26a2c0c0d8490837ce476efb114da9e0cefc4d44', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/generation_config.json'}, 'merges.txt': {'bytes': 1671839, 'sha256': '599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/merges.txt'}, 'model.safetensors.index.json': {'bytes': 67759, 'sha256': '520b2e05079402e9468a8701d03d1154d14b2599593afb6effa7fb60c1bff070', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/model.safetensors.index.json'}, 'preprocessor_config.json': {'bytes': 390, 'sha256': '27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/preprocessor_config.json'}, 'tokenizer.json': {'bytes': 7032403, 'sha256': 'a5d85b6dcc535e6b93115a9ef287e6132fdbf30270da6218194ba742261173c7', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/tokenizer.json'}, 'tokenizer_config.json': {'bytes': 10868, 'sha256': 'c2da771801886ad9ae98181793ffd3dfb7f1af30f6f7c6a4e15d7dbba52e2399', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/tokenizer_config.json'}, 'video_preprocessor_config.json': {'bytes': 385, 'sha256': '7768af27c1fafa9cc9011c1dc20067e03f8915e03b63504550e11d5066986d13', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/video_preprocessor_config.json'}, 'vocab.json': {'bytes': 2776833, 'sha256': 'ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/vocab.json'}, 'model-00001-of-00004.safetensors': {'bytes': 4902275944, 'sha256': 'd5d0aef0eb170fc7453a296c43c0849a56f510555d3588e4fd662bb35490aefa', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/model-00001-of-00004.safetensors'}, 'model-00002-of-00004.safetensors': {'bytes': 4915962496, 'sha256': '8be88fb5501e4d5719a6d4cc212e6a13480330e74f3e8c77daa1a68f199106b5', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/model-00002-of-00004.safetensors'}, 'model-00003-of-00004.safetensors': {'bytes': 4999831048, 'sha256': '83de00eafe6e0d57ccd009dbcf71c9974d74df2f016c27afb7e95aafd16b2192', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/model-00003-of-00004.safetensors'}, 'model-00004-of-00004.safetensors': {'bytes': 2716270024, 'sha256': '0a88b98e9f96270973f567e6a2c103ede6ccdf915ca3075e21c755604d0377a5', 'url': 'https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/resolve/0c351dd01ed87e9c1b53cbc748cba10e6187ff3b/model-00004-of-00004.safetensors'}}, 'stack': 'vllm', 'quant': 'bf16'}
MODEL_MANIFEST_SHA256='a55b7821d05f42c0c1db92f80013d59373f722e1e0d0552e4572a1c43a34f05a'

helper_bytes=reviewed_helper(HELPER_B64,HELPER_SHA256)
assert os.geteuid()==os.getuid()==0
cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
assert(cg/'cpu.max').read_text().strip()=='50000 100000'and(cg/'memory.max').read_text().strip()=='2147483648'
assert(cg/'memory.swap.max').read_text().strip()=='1073741824'
N='QWEN8-VLLM-ALL38-R23'
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


def guest(command,timeout=20,private_stdin=None):
    prefix=['sudo','-n','-H','-u','ubuntu','ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','ConnectionAttempts=1','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','-o','UserKnownHostsFile=/home/ubuntu/.ssh/known_hosts','ubuntu@10.0.1.9']
    try:q=subprocess.run(prefix+[command],input=private_stdin,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        save('guest-timeout-'+uuid.uuid4().hex+'.json',dict(timeout=timeout))
        raise RuntimeError('Bounded guest operation timed out')from None
    if q.returncode:
        save('guest-failure-'+uuid.uuid4().hex+'.json',dict(exit_code=q.returncode))
        raise RuntimeError('Guest operation refused; output suppressed')
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
    save('source-and-input.json',dict(source_head=SOURCE,workspace=str(workspace),manifest=str(manifest),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),images_dir=data['images_dir'],role='owned_Qwen8_vllm_all38_one_residency_restore_Qwen',limit=38,quality_ground_truth=False,adoption_decision=17805,client_uid=1002,client_cgroup=str(cg),request_budget=76,request_budget_unit='completion POSTs',metadata_GET_budget=3,total_HTTP_budget=79,scope='authorized_single_GPU_maintenance_restore_Qwen'))
    save('runtime-recipe-amendment.json',dict(candidate=MODEL_ID,profile=PROFILE,prompts_changed=False,token_budgets_changed=False,seed=0,recipe='frozen v3 two-pass no-think',completeness_policy='all38/errors retained/max76POSTs/client1200/intent1800'))
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
    assert previous=='__PREVIOUS_AUTO__','Unexpected current operation; do not replace another publication'
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
    operation=str(uuid.uuid4())
    maintenance_root='/run/bakeoff-vllm-'+uuid.UUID(operation).hex
    candidate_unit='workbay-bakeoff-vllm-'+operation+'.service'
    setup_unit='workbay-bakeoff-vllm-setup-'+operation+'.scope'
    secret=secrets.token_hex(32).encode('ascii')
    fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
    with os.fdopen(fd,'wb')as f:f.write(secret);f.flush();os.fsync(f.fileno())
    os.chown(keyfile,1002,1002)
    # Route is freshly captured from the running original, never inferred.
    route_code="import json,subprocess;c=json.loads(subprocess.check_output(['docker','inspect','acx-gpu-vlm'],timeout=8))[0];assert c['State']['Running'];h=c['HostConfig'];print(json.dumps(dict(original_network_mode=h['NetworkMode'],original_port_bindings=h['PortBindings'])))"
    route=json.loads(guest('sudo -n /usr/bin/python3 -I -B -c '+shlex.quote(route_code),20))
    payload=transfer_payload(operation,route,helper_bytes,secret)
    safe_withdraw=False;maintenance_attempted=True
    command='sudo -n systemd-run --scope --quiet --collect --unit='+setup_unit+' --property=CPUQuota=200% --property=MemoryMax=42949672960 --property=RuntimeMaxSec=540 /usr/bin/python3 -I -B -c '+shlex.quote(SETUP_PROGRAM)
    try:serving=json.loads(guest(command,570,private_stdin=payload))
    finally:payload=None;secret=None
    assert serving['status']=='ready' and serving['operation']==operation
    assert serving['candidate_image_ref']==CANDIDATE_REF and serving['candidate_image_id']==CANDIDATE_IMAGE
    serving.update(helper_sha256=HELPER_SHA256,profile=PROFILE)
    save('candidate-runtime.json',serving)
    assert expires-time.time()>=330,'Insufficient remaining intent for bounded client and Qwen restoration'
    metadata_code="import json,sys\nfrom scripts.eval_harness.bakeoff import BakeoffClient,_load_server_api_key\nkeypath=sys.argv[2]\nclient=BakeoffClient(sys.argv[1],model_id='metadata-only',model_version='Qwen3-VL-8B-Instruct',model_revision='0c351dd01ed87e9c1b53cbc748cba10e6187ff3b',server_api_key=(None if keypath=='-'else _load_server_api_key(keypath)),timeout_s=5,prompt_variant='v3',two_pass=True)\nif keypath!='-':client._response_private_values+=(keypath, __import__('pathlib').Path(keypath).name)\ntry:\n payload=client._request_dict('GET','/v1/models');rows=payload.get('data')\n assert isinstance(rows,list)and len(rows)==1,'Expected one installed served model'\n value=rows[0].get('id');assert isinstance(value,str)and 0<len(value)<=256 and not any(ord(c)<32 for c in value)\n assert client._redact_response(value)==value,'Private response metadata refused'\n print(json.dumps(dict(id=value,identifier_scope='server-declared-only; upstream unverified')))\nfinally:client.close()\n"
    meta=gate([str(python),'-B','-c',metadata_code,endpoint,str(keyfile)],cwd=workspace/'apps/prototype-description-service',capture_output=True,text=True,timeout=15)
    redact_key=keyfile.read_text()
    def redact_metadata(value):
        return value.replace(redact_key,'<credential-redacted>').replace(str(keyfile),'<private-credential-file>').replace(keyfile.name,'<private-credential-file>')
    save('metadata-process.json',dict(exit_code=meta.returncode,stdout=redact_metadata(meta.stdout),stderr=redact_metadata(meta.stderr),keyfile_uid=keyfile.stat().st_uid,keyfile_mode=oct(stat.S_IMODE(keyfile.stat().st_mode)),keyfile_bytes=keyfile.stat().st_size,credential_values_suppressed=True))
    redact_key=None
    assert meta.returncode==0,'Candidate authenticated metadata refused'
    served=json.loads(meta.stdout);wire_model_id=served['id'];assert wire_model_id==MODEL_ID,'Candidate model mismatch; no Qwen fallback';save('served-model-metadata.json',served)
    raw=permanent/'raw.json';clientenv=dict(env,ACX_EVAL_LIVE='1',GOLDEN_IMAGES_DIR=data['images_dir'])
    deadline=time.monotonic()+min(1200,int(expires-time.time()-105));assert deadline-time.monotonic()>=1100,'Insufficient fixed remaining residency for full batch'
    cohort_results=[];all_items=[];all_passes=[]
    for cohort in cohorts:
        remaining=int(deadline-time.monotonic())
        if remaining<5:
            cohort_results.append(dict(id=cohort['id'],requested_images=cohort['count'],evaluated_images=0,status='NOT_STARTED_FIXED_DEADLINE'));continue
        directory=permanent/cohort['id'];directory.mkdir(mode=0o700);os.chown(directory,1002,1002)
        raw=directory/'raw.json';manifest=Path(cohort['manifest'])
        command=[str(python),'-B','-c',"import json,os,sys\nfrom scripts.eval_harness import bakeoff as b\nfrom pathlib import Path\np=Path(sys.argv[1]);sys.argv=sys.argv[1:];expected=sys.argv[sys.argv.index('--model-id')+1];original=b.BakeoffClient._parse_response\ndef observed(self,parser,value):\n # Preserve actual completion envelope privately; no request/output changes.\n # No request or credential headers are recorded.\n path=p.parent/('completion-envelope-'+str(len(list(p.parent.glob('completion-envelope-*.json'))))+'.json')\n if isinstance(value,dict)and 'choices'in value:\n  cleaned=self._redact_response(value)\n  with path.open('x')as f:json.dump(cleaned,f,sort_keys=True);f.flush();os.fsync(f.fileno())\n  path.chmod(0o400)\n  if value.get('model')!=expected:raise SystemExit('Response model mismatch; batch stopped without further inference')\n return original(self,parser,value)\nb.BakeoffClient._parse_response=observed\nb.main(sys.argv[1:])\n",str(raw),'--endpoint',endpoint,'--server-api-key-file',str(keyfile),'--model-id',wire_model_id,'--model-version','Qwen3-VL-8B-Instruct','--model-revision',MODEL_MANIFEST['revision'],'--manifest',str(manifest),'--prompt-variant','v3','--caption-length','standard','--two-pass','--no-think','--seed','0','--limit',str(cohort['count']),'--stall-limit',str(cohort['count']),'--timeout','30','--warmup','0','--vram-sample-interval-s','0','--keep','1','--out',str(raw)]
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
    save('candidate-result.json',dict(status='ALL38_RAW_COMPLETE'if complete else'ALL38_ATTEMPT_RECORDED',execution_complete=len(all_items)==38,complete=complete,requested_images=38,evaluated_images=len(all_items),item_errors=errors,raw_passes=len(all_passes),cohorts=cohort_results,one_model_residency=True,model_assets=MODEL_MANIFEST['components'],model_revision=MODEL_MANIFEST['revision'],model_manifest_sha256=MODEL_MANIFEST_SHA256,actual_runtime_image=serving['candidate_image_id'],runtime_image_ref=serving['candidate_image_ref'],runtime_profile=PROFILE,helper_sha256=HELPER_SHA256,source_head=SOURCE,authenticated_header_present=True,quality_or_winner=False,isolated_performance=False))
    print(json.dumps(dict(status='CANDIDATE_ATTEMPT_RECORDED',complete=complete,items=len(all_items),item_errors=errors,directory=str(base))),flush=True)

except BaseException as exc:
    save('failure.json',dict(exception_type=type(exc).__name__,maintenance_attempted=maintenance_attempted,owned_start=owned_start))
    print(json.dumps(dict(status='CANDIDATE_OPERATION_REFUSED',exception_type=type(exc).__name__,directory=str(base))),flush=True)
    raise
finally:
    if child is not None and child.poll()is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
    if keyfile.exists():keyfile.unlink()
    if maintenance_attempted:
        try:
            # Quiescence must precede restore: a late launcher cannot create a candidate.
            proof="import json,subprocess;v=dict(x.split('=',1)for x in subprocess.check_output(['systemctl','show',UNIT,'-p','ActiveState','-p','ControlGroup','-p','MainPID'],text=True,timeout=8).splitlines()if '='in x);assert v.get('ActiveState')in ['inactive','failed']and not v.get('ControlGroup')and v.get('MainPID','0')=='0';print(json.dumps(v))".replace('UNIT',repr(setup_unit))
            setup_quiescent=json.loads(guest('sudo -n /usr/bin/python3 -I -B -c '+shlex.quote(proof),20))
            save('setup-quiescent-before-cleanup.json',setup_quiescent)
            # Only the reviewed helper restores; no guessed pre-before success.
            cleanup=restore_program(maintenance_root,operation,candidate_unit)
            restored=json.loads(guest('sudo -n /usr/bin/python3 -I -B -c '+shlex.quote(cleanup),245))
            require_restored(restored)
            save('Qwen-restored.json',restored)
            # Full owned root, including sealed before and helper, retained privately.
            archive=guest('sudo -n tar -C /run -cf - -- '+shlex.quote(Path(maintenance_root).name),60)
            fd=os.open(base/'guest-private.tar',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
            with os.fdopen(fd,'wb')as f:f.write(archive);f.flush();os.fsync(f.fileno())
            archive=None
            safe_withdraw=True
        except BaseException as exc:
            try:
                evidence=guest('sudo -n tar -C /run -cf - -- '+shlex.quote(Path(maintenance_root).name),60)
                fd=os.open(base/'guest-private-uncertain.tar',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
                with os.fdopen(fd,'wb')as f:f.write(evidence);f.flush();os.fsync(f.fileno())
                evidence=None
            except BaseException:
                save('PRIVATE-CAPTURE-UNKNOWN.json',dict(captured=False))
            save('RESTORE-UNKNOWN.json',dict(exception_type=type(exc).__name__,unit=candidate_unit,automatic_restore_RuntimeMaxSec=1500))
            safe_withdraw=False
    if safe_withdraw and owned_start is not None:
        current=public(['reconcile',str(window),wid],'before-lease-close',45)
        assert current==owned_start,'Foreign publication; retain exact window'
        stopped=public(['stop',str(window),current],'close-completed-lease',75)
        observe(stopped,'stop','close-completed-lease-observe',195)
        save('completed-physical-lease-closed.json',dict(STOP=stopped,canonical_stopped=True,after_Qwen_restore=True,no_actor_or_request_active=True))
        op=public(['withdraw',str(window),wid],'withdraw',75)
        if op!='none':observe(op,'auto','auto-observe',190)
        save('owned-window-return.json',dict(at=time.time(),operation=op,owned_client_reaped=True,owned_candidate_reaped=True,Qwen_restored=True))
    elif not safe_withdraw:raise RuntimeError('Qwen restoration unknown; retain exact actor/window/resources for recovery')
