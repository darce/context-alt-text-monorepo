"""Transport exact remote-generated, independently reviewed Qwen recipes."""
from pathlib import Path
import sys,json,hashlib,ast,tarfile,subprocess,argparse
b=Path(__file__).resolve().parent;p=Path('/Users/daniel/Development/context-alt-text-monorepo/.task-state/bakeoff-rounds-20261017');sys.path.insert(0,str(p));import run_selected_root_resume_qualification as runner
args=argparse.ArgumentParser();args.add_argument('--name',required=True);args.add_argument('--previous-settlement',required=True);args.add_argument('--pilot',required=True);a=args.parse_args();n=a.name
r=json.loads((b/(n+'.prepared.json')).read_bytes());raw=(b/(n+'.remote.py')).read_bytes();assert hashlib.sha256(raw).hexdigest()==r['recipe_sha256'];ast.parse(raw);assert r['name']==n and r['mode']=='full'
with tarfile.open(b/'QWEN-AB-G2.custody.tar')as t:g=json.load(t.extractfile('output/result.json'))
assert g['status']=='PASS'and g['source_sha']=='22b61b6c7bc3932378dcb7e795a99f3ab288ff58'
assert json.loads((p/'QWEN-AB-G2.actual-capacity-return.json').read_bytes())['remaining_actor_claim']==0
pilot_path=p/(a.pilot+'.actual-capacity-return.json');pilot_raw=pilot_path.read_bytes();pilot=json.loads(pilot_raw);assert pilot['remaining_actor_claim']==0 and pilot['native']['GPU_stopped']and pilot['native']['UID0_hits']==pilot['native']['UID0_errors']==0
assert (pilot['execution_evidence']['persisted_image_rows'],pilot['execution_evidence']['contract_valid_pairs'],pilot['execution_evidence']['recorded_completion_POST_attempts'])==(2,2,6)
pr=json.loads((b/(a.pilot+'.prepared.json')).read_bytes());assert pr['mode']=='pilot'and pr['candidate']==r['candidate'];assert pr['asset_spec_sha256']==r['asset_spec_sha256']and pr['model_contract']==r['model_contract']and pr['sources']==r['sources'];assert pr['immutable_candidate_configs']==r['immutable_candidate_configs']
archive=Path(pilot['archive']);assert hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()==pilot['archive_sha256']
with tarfile.open(archive)as t:
 c=json.load(t.extractfile('permanent/candidate-result.json'));assert c['complete']and c['evaluated_images']==2 and c['item_errors']==0 and c['raw_passes']==6
 records=[json.load(t.extractfile(x))for x in t.getnames()if x.startswith('permanent/')and x.endswith('/raw.json')];assert len(records)==1
 record=records[0];assert record['model_id']==r['model_contract']['wire_model_id']and record['model_revision']==r['model_contract']['model_revision']and record['valid_pairs']==2
 previous=json.loads((p/(a.previous_settlement+'.actual-capacity-return.json')).read_bytes());assert previous['remaining_actor_claim']==0 and previous['native']['GPU_stopped']
 with tarfile.open(previous['archive'])as z:
  returned=json.load(z.extractfile('permanent/owned-window-return.json'));closed=json.load(z.extractfile('permanent/completed-physical-lease-closed.json'))
 assert returned['Qwen_restored']and returned['owned_client_reaped']and returned['owned_candidate_reaped']and closed['canonical_stopped'];assert r['actual_previous_AUTO']==returned['operation']
helper=json.loads((b/'LEXICON-MIMO-40-LAST40-R1.prepared.json').read_bytes());pilot_sha=hashlib.sha256(pilot_raw).hexdigest()
receipt=dict(r,source_head=g['source_sha'],gate='QWEN-AB-G2',stage=helper['stage'],manifest_sha256=helper['manifest_sha256'],helper_source_head=helper['source_head'],helper_independent_gate=helper['gate'],remote_orchestration_sha256=r['recipe_sha256'],actual_pilot=a.pilot,actual_pilot_receipt_sha256=pilot_sha,actual_pilot_custody_sha256=pilot['archive_sha256'],previous_settlement=a.previous_settlement)
# Reject an expired predecessor before claiming resources; actual recipe also
# reconciles/observes it and checks fixed remaining phase budgets.
probe="""import pathlib,json,datetime
w=pathlib.Path('/tmp/qwen-owner-window.rcqmefq9');op=OP;root=w/'ops'/op
intent=json.loads((root/'intent.json').read_bytes());pub=json.loads((root/'publication.json').read_bytes());result=json.loads((root/'result.json').read_bytes());assert intent['action']==pub['action']=='auto'and result['operation']==op and result['outcome']=='published'
remaining=(datetime.datetime.fromisoformat(pub['expires_at'].replace('Z','+00:00'))-datetime.datetime.now(datetime.timezone.utc)).total_seconds();assert remaining>300
state=json.loads(pathlib.Path('/run/acx/gpu-state.json').read_bytes());assert state['state']=='stopped'and state.get('lease_expires_at')is None
print(json.dumps(dict(operation=op,publication=pub,result=result,remaining_seconds=remaining,GPU_stopped=True)))
""".replace('op=OP','op='+repr(r['actual_previous_AUTO']))
q=subprocess.run(['ssh','-oBatchMode=yes','ubuntu@acx-backend.tail1a44b8.ts.net','sudo -n /usr/bin/python3 -I -B -'],input=probe,text=True,capture_output=True,timeout=30);assert q.returncode==0,q.stderr;runner.cap.persist(p/(n+'.fresh-preclaim-predecessor.json'),json.loads(q.stdout))
runner.N=n;runner.UNIT=r['unit'];runner.ROLE='actual_frozen_Qwen_'+r['candidate']+'_paired_lexicon_full_cohort'
def inputs(head,gate):
 dest=p/(n+'.remote.py')
 if dest.exists():assert dest.read_bytes()==raw
 else:dest.write_bytes(raw)
 runner.cap.persist(p/(n+'.prepared-inputs.json'),receipt);return {},receipt
def bootstrap(files,receipt):
 return 'import os\nos.environ["QWEN_AB_SOL_XHIGH_GATE"]='+repr(r['gate_token'])+'\nos.environ["QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256"]='+repr(pilot_sha)+'\nexec(compile('+repr(raw.decode())+','+repr(n+'.remote.py')+',"exec"))\n'
runner.inputs=inputs;runner.bootstrap=bootstrap;runner.run(receipt['source_head'],receipt['gate'])
