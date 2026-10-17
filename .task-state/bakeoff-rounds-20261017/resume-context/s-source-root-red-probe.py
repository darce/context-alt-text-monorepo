import json,pathlib,subprocess,os,hashlib,resource,time
base=pathlib.Path('/home/gate/workbay-sandbox/feature-bakerounds-20261017-s-whole-sour-8274b42b');service=base/'apps/prototype-description-service';a=pathlib.Path('/tmp/s-whole-source-g1');out=pathlib.Path('/tmp/bakerounds-root-subject-red-20261017T2208');out.mkdir(mode=0o700)
def cap():
 resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3));resource.setrlimit(resource.RLIMIT_CPU,(5,6))
inputs=[]
absence=json.loads((a/'absence-probe-results.json').read_text())
for role,kind in [('selection','empty-parent'),('selection','unnamed-face'),('reported','unnamed-face')]:
 row=next(x for x in absence if x['role']==role and x['kind']==kind)
 inputs.append((role+'-'+kind,row['argv'],0 if kind=='empty-parent' else 4,'' if kind=='empty-parent' else 'evidence_conflict'))
for row in json.loads((a/'native-public-results.json').read_text()):
 inputs.append((row['name'],row['command'][3:],0 if row['name']=='dated-absent' else 4,'' if row['name']=='dated-absent' else 'source_binding'))
rows=[]
for name,argv,expected,code in inputs:
 argv=argv[:];target=out/(name+'.html');argv[argv.index('--out')+1]=str(target)
 p=subprocess.run([str(base/'.venv/bin/python'),'-B','-m','scripts.eval_harness.build_bakeoff_report',*argv],cwd=service,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=15,preexec_fn=cap)
 (out/(name+'.stdout')).write_text(p.stdout);(out/(name+'.stderr')).write_text(p.stderr)
 row=dict(name=name,exit=p.returncode,expected_exit=expected,output=target.exists(),code_ok=(not code or ('subject evidence invalid: '+code)in p.stderr));row['meets_required_behavior']=p.returncode==expected and row['code_ok'] and target.exists()==(expected==0);rows.append(row)
summary=dict(observed_at=time.time(),source_hashes={str(x.relative_to(base)):hashlib.sha256(x.read_bytes()).hexdigest()for x in [service/'scripts/eval_harness/manifest.py',service/'scripts/eval_harness/build_bakeoff_report.py']},cases=rows,desired_contract_exit=0,actual_behavioral_exit=0 if all(x['meets_required_behavior']for x in rows) else 1,no_source_changes=True)
(out/'receipt.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));raise SystemExit(summary['actual_behavioral_exit'])
