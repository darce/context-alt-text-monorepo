#!/usr/bin/python3
# Receipt reader only; eligible capacity observation is not a guest/serving attestation.
import json,pathlib,sys,time,datetime,math
P=pathlib.Path
class Unknown(Exception): pass
class Refuse(Exception): pass
def number(v):
 return not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v)
def epoch(v):
 if not isinstance(v,str): raise Unknown('timestamp unavailable')
 try:
  d=datetime.datetime.fromisoformat(v.replace('Z','+00:00'))
  if d.tzinfo is None: raise ValueError('timezone missing')
  return d.timestamp()
 except (ValueError,OverflowError) as exc: raise Unknown('invalid timestamp') from exc
def nonfinite(value):
 raise ValueError("nonfinite JSON constant: "+value)
def read(p):
 try:
  with p.open('rb') as f: b=f.read(2097153)
  if len(b)>2097152: raise ValueError('receipt exceeds 2MiB')
  v=json.loads(b,parse_constant=nonfinite)
  if not isinstance(v,dict): raise ValueError('receipt is not an object')
  return v,None
 except (OSError,UnicodeError,ValueError) as exc:
  return None,dict(kind=type(exc).__name__,detail=str(exc))
def save(name,v):
 # AUTHORITY supplies a fresh protected per-attempt directory. Never replace evidence.
 with (out/name).open('x') as f: f.write(json.dumps(v,indent=2,allow_nan=False)+'\n')
publication,publication_error=read(P(sys.argv[1])); out=P(sys.argv[2]); phase=sys.argv[3]
if publication_error: raise SystemExit('publication receipt unknown: '+str(publication_error))
if phase not in ('start','auto','stop') or not out.is_dir(): raise SystemExit('invalid observer arguments')
if (not isinstance(publication,dict) or publication.get('action')!=phase
 or type(publication.get('sequence')) is not int or publication['sequence']<1
 or not isinstance(publication.get('nonce'),str) or not publication['nonce']
 or not isinstance(publication.get('requested_by'),str) or not publication['requested_by']):
 raise SystemExit('invalid publication receipt')
requested=epoch(publication.get('requested_at'))
limit=time.monotonic()+(300 if phase=='start' else 180)
stopped_written=None; stopped_identity=None
S='/run/acx/gpu-state.json'; A='/var/lib/acx-gpu/intent-authority.json'
L='/var/lib/acx-gpu/running-since.json'; D='/var/lib/acx-gpu/intents/prod/gpu-intent.json'
ENVS=('dev','dev-fir','staging','prod')
# Exact installed subjects reviewed by this procedure; no foreign identity.
STOP_SUBJECTS=(
 'ocid1.instance.oc1.iad.anuwcljt2mcagaqcoop3g4euuthldjy6wbrhmh5yfjgznxdg353urol27bfa',
 'ocid1.instance.oc1.iad.anuwcljr2mcagaqcki4d2szgsymtr4ucpc3dsqzfsvwoj2gtemrjx2dlammq')
def canonical_stopped(s):
 # The public producer retains the configured identity for a sole STOPPED
 # subject; an all-stopped configured set may instead have null identity.
 identity=s.get('instance_id')
 return (s.get('state')=='stopped' and s.get('reason') is None
  and 'instance_id' in s and (identity is None or
   (isinstance(identity,str) and bool(identity.strip()) and identity in STOP_SUBJECTS)))
def collect():
 errors={}; paths=[P(S),P(A),P(L),P(D)]
 try:
  paths+=sorted(P('/var/lib/acx-gpu/intents').glob('*/gpu-intent.json'))
  paths+=sorted(P('/run/acx-write').glob('*/gpu-intent.json'))
 except OSError as exc: errors['publication_inventory']=dict(kind=type(exc).__name__,detail=str(exc))
 paths += [P('/run/acx-write',e,'describe-load.json') for e in ENVS]
 rows={}
 for p in paths:
  k=str(p)
  if k in rows: continue
  rows[k],error=read(p)
  if error: errors[k]=error
 return rows,errors
def decide(rows,errors,now):
 global stopped_written,stopped_identity
 # Foreign evidence is a refusal even when another required receipt is unknown.
 a=rows.get(A); s=rows.get(S)
 if isinstance(a,dict) and type(a.get('highest_sequence')) is int and a['highest_sequence']>publication['sequence']:
  raise Refuse('foreign newer authority: no overwrite or force-stop')
 pubs=[v for k,v in rows.items() if k.endswith('/gpu-intent.json') and v is not None]
 for v in pubs:
  if v!=publication and not (v.get('requested_by')==publication['requested_by'] and type(v.get('sequence')) is int and v['sequence']<publication['sequence']):
   raise Refuse('foreign publication: reconcile')
 required_errors=[k for k in errors if k not in [L,*['/run/acx-write/'+e+'/describe-load.json' for e in ENVS]]]
 if required_errors or not isinstance(a,dict) or not isinstance(s,dict): raise Unknown('required state/authority/publication unreadable')
 if type(a.get('highest_sequence')) is not int or not isinstance(a.get('intents'),dict): raise Unknown('invalid authority schema')
 record=a['intents'].get(publication['nonce'])
 if not isinstance(record,dict) or record.get('sequence')!=publication['sequence'] or a['highest_sequence']!=publication['sequence'] or rows.get(D)!=publication or not pubs or not all(v==publication for v in pubs):
  raise Unknown('publication not yet exactly durably consumed')
 immutable={k:publication[k] for k in ('action','requested_at','expires_at','ttl_seconds','requested_by','sequence')}
 if record.get('publication')!=immutable: raise Refuse('immutable authority mismatch')
 try: boot=P('/proc/sys/kernel/random/boot_id').read_text().strip()
 except (OSError,UnicodeError) as exc: raise Unknown('backend boot identity unreadable') from exc
 if (not boot or record.get('boot_id')!=boot or record.get('expired') is not False
  or not number(record.get('monotonic_expires_at')) or record['monotonic_expires_at']<=time.monotonic()
  or not isinstance(a.get('sequences'),dict) or a['sequences'].get(str(publication['sequence']))!=publication['nonce']
  or not isinstance(a.get('rejected_sequences'),list) or publication['sequence'] in a['rejected_sequences']):
  raise Unknown('authority boot/monotonic/sequence fence unresolved or expired')
 if (not number(s.get('written_at')) or not 0<=now-s['written_at']<=120 or s['written_at']<requested
  or s.get('state') not in ('ready','warming','starting','degraded','stopped')
  or not number(s.get('since')) or s['since']>s['written_at']): raise Unknown('snapshot schema/freshness unresolved')
 if phase!='auto':
  for e in ENVS:
   q=rows.get('/run/acx-write/'+e+'/describe-load.json')
   # Optional demand is already counted in required in_flight; present values must be integer zero.
   if (not isinstance(q,dict) or not number(q.get('written_at')) or not 0<=now-q['written_at']<=120
    or type(q.get('queue_depth')) is not int or q['queue_depth']!=0
    or type(q.get('in_flight')) is not int or q['in_flight']!=0
    or q.get('batch_in_progress') is not False
    or ('lease_demand' in q and (type(q['lease_demand']) is not int or q['lease_demand']!=0))):
    raise Unknown('work/unknown load: no START/STOP advancement')
 if phase=='stop':
  # Reap may retire the lease, preserve last START nonce, then clear/omit
  # intent/honour fields. STOP ownership comes from durable authority above.
  if not canonical_stopped(s):
   stopped_written=None; stopped_identity=None; raise Unknown('waiting for canonical all-stopped snapshot')
  stable_rows,stable_errors=collect()
  if stable_rows!=rows or stable_errors!=errors:
   stopped_written=None; stopped_identity=None; raise Unknown('receipt generation changed during stopped observation')
  if stopped_written is None or stopped_identity!=s['instance_id']:
   stopped_written=s['written_at']; stopped_identity=s['instance_id']; raise Unknown('waiting for second distinct stopped snapshot')
  if s['written_at']<=stopped_written: raise Unknown('waiting for second distinct stopped snapshot')
  return record,'stopped-observation-only'
 if phase=='auto':
  if s['state']=='stopped':
   if canonical_stopped(s): return record,'owned-AUTO-withdrawal/stopped-observation-only'
   raise Unknown('waiting for AUTO or canonical stopped snapshot')
  if s.get('intent')=='auto': return record,'owned-AUTO-withdrawal/not-a-stop-attestation'
  raise Unknown('waiting for AUTO or canonical stopped snapshot')
 if s.get('intent')!='start' or s.get('honoured_nonce')!=publication['nonce'] or s.get('intent_status')!='honoured':
  raise Unknown('waiting for current honoured START')
 if s['state']=='starting': raise Unknown('START pending ('+str(s.get('reason'))+'): guest capacity entry not yet eligible')
 if s['state']=='degraded' and s.get('reason') not in ('readiness_timeout','readiness_stall'):
  raise Refuse('controller failure: '+str(s.get('reason'))+'; preserve receipts, no guest probe')
 if s['state'] not in ('ready','warming','degraded'): raise Unknown('START has no capacity-entry candidate')
 if s['state']!='degraded' and s.get('reason') is not None: raise Unknown('invalid state reason')
 identity=s.get('instance_id'); lease=rows.get(L)
 if not isinstance(identity,str) or not identity or not isinstance(lease,dict) or lease.get('schema_version')!=2 or not isinstance(lease.get('instances'),dict):
  raise Unknown('required START lease/identity unreadable; absence is not death')
 origin=lease['instances'].get(identity)
 if (not isinstance(origin,dict) or origin.get('honoured_nonce')!=publication['nonce'] or origin.get('boot_id')!=boot
  or not number(origin.get('monotonic_since')) or not 0<=time.monotonic()-origin['monotonic_since']<3600
  or epoch(origin.get('since'))!=epoch(s.get('instance_running_since')) or epoch(s.get('lease_expires_at'))-now<180):
  raise Unknown('START lease origin/remaining budget unresolved')
 return record,('failure-diagnostic/NOTrawready' if s['state']=='degraded' else 'capacity-entry-candidate/NOTrawready')
for attempt in range(60):
 now=time.time(); rows,errors=collect(); status='unknown'; result=None; refusal=None
 try:
  result=decide(rows,errors,now)
  # Recheck the complete inventory and bytes before publishing a coherent observation.
  again,again_errors=collect()
  if again!=rows or again_errors!=errors: raise Unknown('receipt generation changed during observation')
  status='observed'
 except Unknown as exc: status='unknown: '+str(exc)
 except Refuse as exc: refusal=str(exc); status='refused: '+refusal
 save(phase+'-observation-%02d.json'%attempt,dict(observed_at=now,files=rows,read_errors=errors,status=status))
 if refusal: raise SystemExit(refusal)
 if status=='observed':
  log=P('/var/lib/acx-gpu/decision-log.jsonl'); matching=[]; log_errors=[]
  try:
   with log.open('rb') as f:
    size=f.seek(0,2); f.seek(max(0,size-2097152)); raw=f.read(2097152)
   with (out/(phase+'-decision-tail.raw')).open('xb') as f: f.write(raw)
   lines=raw.splitlines()[1:] if size>2097152 else raw.splitlines()
   for i,line in enumerate(lines):
    if not line.strip(): continue
    try:
     j=json.loads(line)
     if isinstance(j,dict) and j.get('nonce')==publication['nonce'] and j.get('sequence')==publication['sequence']: matching.append(j)
    except (UnicodeError,ValueError) as exc: log_errors.append(dict(line=i,kind=type(exc).__name__))
  except OSError as exc: log_errors.append(dict(kind=type(exc).__name__,detail=str(exc)))
  save(phase+'-decisions.json',matching)
  save(phase+'-decision-errors.json',log_errors)
  save(phase+'-observed.json',dict(publication=publication,state=rows[S],authority_record=result[0],capacity_observation=result[1]))
  print('observed',phase,result[1]); sys.exit()
 if time.monotonic()>=limit: break
 time.sleep(min(5,max(0,limit-time.monotonic())))
raise SystemExit('receipt deadline: unknown; preserve all files and do not infer stopped/unloaded')
