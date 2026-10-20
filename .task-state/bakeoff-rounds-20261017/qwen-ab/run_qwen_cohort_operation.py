"""Qwen cohort operation runner v2: late-bound predecessor, landed-generator binding (decision 18673)."""
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BAKEOFF = HERE.parent
HOST = 'ubuntu@acx-backend.tail1a44b8.ts.net'
PREPARER = '.task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py'
CUSTODY_SOURCE = '22b61b6c7bc3932378dcb7e795a99f3ab288ff58'
WINDOW = re.compile(r"window=Path\('(/tmp/qwen-owner-window\.[A-Za-z0-9_-]+)'\)")
G = 1024**3


def need(ok, why):
    if not ok:
        raise ValueError(why)


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--name', required=True)
    p.add_argument('--dir', required=True, help='holds <name>.prepared.json and <name>.remote.py')
    p.add_argument('--gate-commit', required=True)
    p.add_argument('--pilot', help='required iff the prepared mode is full')
    return p.parse_args(argv)


def verify_prepared(prepared, raw):
    need(hashlib.sha256(raw).hexdigest() == prepared.get('recipe_sha256'), 'recipe sha256 does not match the prepared record')
    try:
        ast.parse(raw)
    except SyntaxError as e:
        raise ValueError(f'recipe does not parse: {e}') from e
    need(prepared.get('predecessor_binding') == 'late_bound_at_claim_refresh', 'predecessor must be late_bound_at_claim_refresh')
    need('actual_previous_AUTO' not in prepared, 'pinned actual_previous_AUTO is not allowed')
    need(prepared.get('mode') in ('pilot', 'full'), f"mode must be pilot or full, got {prepared.get('mode')!r}")
    windows = WINDOW.findall(raw.decode())
    need(len(windows) == 1, f'recipe must contain exactly one owner window line, found {len(windows)}')
    return windows[0]


def bind_generator(prepared, gate_commit, git):
    try:
        git('merge-base', '--is-ancestor', gate_commit, 'main')
    except Exception as e:
        raise ValueError(f'gate commit {gate_commit} is not an ancestor of main') from e
    try:
        source = git('show', gate_commit + ':' + PREPARER)
    except Exception as e:
        raise ValueError(f'gate commit {gate_commit} has no {PREPARER}') from e
    need(hashlib.sha256(source).hexdigest() == prepared.get('preparer_sha256'), 'generator sha256 differs from the gate commit')


def run_git(*args):
    return subprocess.check_output(['git', *args], cwd=HERE, timeout=40)


def preclaim_script(window):
    # Read-only. Reports the GPU state and the newest publication; no TTL is judged here, because the recipe refreshes AUTO.
    return '''import glob,json,pathlib
w=pathlib.Path(WINDOW)
gpu=json.loads(pathlib.Path('/run/acx/gpu-state.json').read_bytes())
pubs=[]
for p in glob.glob(str(w/'ops'/'*'/'publication.json')):
 d=json.loads(pathlib.Path(p).read_bytes());pubs.append(dict(op=pathlib.Path(p).parent.name,action=d.get('action'),expires_at=d.get('expires_at'),sequence=d.get('sequence',-1)))
print(json.dumps(dict(gpu=dict(state=gpu.get('state'),lease_expires_at=gpu.get('lease_expires_at')),publication=max(pubs,key=lambda x:x['sequence'],default=None))))
'''.replace('WINDOW', repr(window))


def classify_preclaim(report):
    import cohort_admission as ca
    gpu, pub = report['gpu'], report['publication']
    if gpu['state'] != 'stopped' or gpu.get('lease_expires_at') is not None:
        raise ca.AdmissionRefusal('gpu_not_stopped', json.dumps(gpu, sort_keys=True))
    if pub is None:
        raise ca.AdmissionRefusal('predecessor_unsettled', 'no publication under window/ops')
    if pub['action'] == 'start':
        raise ca.AdmissionRefusal('live_start', pub['op'])
    if pub['action'] not in ('auto', 'stop'):
        raise ca.AdmissionRefusal('predecessor_unsettled', f"latest action {pub['action']!r} in op {pub['op']}")
    return report


def bootstrap_source(raw, name, gate_token, pilot_sha):
    lines = ['import os', 'os.environ["QWEN_AB_SOL_XHIGH_GATE"]=' + repr(gate_token)]
    if pilot_sha is not None:
        lines.append('os.environ["QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256"]=' + repr(pilot_sha))
    lines.append('exec(compile(' + repr(raw.decode()) + ',' + repr(name + '.remote.py') + ',"exec"))')
    return '\n'.join(lines) + '\n'


def pilot_checks(d, prepared, name):
    raw = (BAKEOFF/(name + '.actual-capacity-return.json')).read_bytes()
    pilot = json.loads(raw)
    native, evidence = pilot['native'], pilot['execution_evidence']
    need(pilot['remaining_actor_claim'] == 0 and native['GPU_stopped'] and native['UID0_hits'] == native['UID0_errors'] == 0,
         'pilot capacity was not returned cleanly')
    need((evidence['persisted_image_rows'], evidence['contract_valid_pairs'], evidence['recorded_completion_POST_attempts']) == (2, 2, 6),
         'pilot execution evidence changed')
    pr = json.loads((d/(name + '.prepared.json')).read_bytes())
    need(pr['mode'] == 'pilot' and pr['candidate'] == prepared['candidate'], 'pilot is not a pilot of this candidate')
    for key in ('asset_spec_sha256', 'model_contract', 'sources', 'immutable_candidate_configs'):
        need(pr[key] == prepared[key], f'pilot {key} differs from the full recipe')
    archive = Path(pilot['archive'])
    with archive.open('rb') as f:
        need(hashlib.file_digest(f, 'sha256').hexdigest() == pilot['archive_sha256'], 'pilot archive sha256 mismatch')
    with tarfile.open(archive) as t:
        result = json.load(t.extractfile('permanent/candidate-result.json'))
        need(result['complete'] and result['evaluated_images'] == 2 and result['item_errors'] == 0 and result['raw_passes'] == 6,
             'pilot candidate result is incomplete')
        records = [json.load(t.extractfile(x)) for x in t.getnames() if x.startswith('permanent/') and x.endswith('/raw.json')]
        need(len(records) == 1, 'pilot must contain exactly one raw record')
        contract = prepared['model_contract']
        need(records[0]['model_id'] == contract['wire_model_id'] and records[0]['model_revision'] == contract['model_revision']
             and records[0]['valid_pairs'] == 2, 'pilot raw record disagrees with the model contract')
    return hashlib.sha256(raw).hexdigest(), pilot['archive_sha256']


def main(argv=None):
    a = parse_args(argv)
    sys.path[:0] = [str(HERE), str(BAKEOFF)]
    import cohort_admission as ca
    import run_selected_root_resume_qualification as runner
    base, cap = runner.admission, runner.cap
    d = Path(a.dir)
    prepared = json.loads((d/(a.name + '.prepared.json')).read_bytes())
    raw = (d/(a.name + '.remote.py')).read_bytes()
    try:
        need(prepared.get('name') == a.name, f"prepared record is for {prepared.get('name')!r}, not --name {a.name!r}")
        window = verify_prepared(prepared, raw)
        bind_generator(prepared, a.gate_commit, run_git)
        with tarfile.open(d/'QWEN-AB-G2.custody.tar') as t:
            g = json.load(t.extractfile('output/result.json'))
        need(g['status'] == 'PASS' and g['source_sha'] == CUSTODY_SOURCE, 'QWEN-AB-G2 custody is not PASS at the pinned source')
        need(json.loads((BAKEOFF/'QWEN-AB-G2.actual-capacity-return.json').read_bytes())['remaining_actor_claim'] == 0,
             'QWEN-AB-G2 capacity was not returned')
        need((a.pilot is not None) == (prepared['mode'] == 'full'), '--pilot is required iff the prepared mode is full')
        pilot_sha = pilot_custody = None
        if a.pilot is not None:
            pilot_sha, pilot_custody = pilot_checks(d, prepared, a.pilot)
    except ValueError as e:
        raise SystemExit(f'preflight refused: {e}')
    helper = json.loads((d/'LEXICON-MIMO-40-LAST40-R1.prepared.json').read_bytes())
    receipt = dict(prepared, source_head=g['source_sha'], gate='QWEN-AB-G2', stage=helper['stage'],
                   manifest_sha256=helper['manifest_sha256'], helper_source_head=helper['source_head'],
                   helper_independent_gate=helper['gate'], remote_orchestration_sha256=prepared['recipe_sha256'],
                   actual_pilot=a.pilot, actual_pilot_receipt_sha256=pilot_sha, actual_pilot_custody_sha256=pilot_custody,
                   predecessor_binding=prepared['predecessor_binding'], gate_commit=a.gate_commit)
    # Bind the operation identity before admit(): the guard persists under base.N and evaluates base.PROFILE,
    # and r6's defaults would otherwise write over its receipt.
    base.N = runner.N = a.name
    runner.UNIT = prepared['unit']
    runner.ROLE = f"actual_frozen_Qwen_{prepared['candidate']}_paired_lexicon_{prepared['mode']}_cohort"
    base.PROFILE = dict(lane=a.name, role=runner.ROLE, model=None, aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=2*G,
                        forward_disk_bytes=G, native_unit=runner.UNIT, native_namespace='system', no_auto_retry=True,
                        source_commit=receipt['source_head'])
    remote = BAKEOFF/(a.name + '.remote.py')

    def inputs(head, gate):
        if remote.exists():
            need(remote.read_bytes() == raw, 'existing remote recipe differs from the prepared bytes')
        else:
            remote.write_bytes(raw)
        cap.persist(BAKEOFF/(a.name + '.prepared-inputs.json'), receipt)
        return {}, receipt

    try:
        probe = subprocess.run(['ssh', '-oBatchMode=yes', HOST, 'sudo -n /usr/bin/python3 -I -B -'],
                               input=preclaim_script(window), text=True, capture_output=True, timeout=30)
        if probe.returncode:
            raise SystemExit(f'preclaim probe failed: {probe.stderr.strip()}')
        report = json.loads(probe.stdout)
        cap.persist(BAKEOFF/(a.name + '.preclaim.json'), report)
        receipt['preclaim'] = classify_preclaim(report)
        ca.admit()
        runner.admission.guard = ca.guard
        runner.inputs = inputs
        runner.bootstrap = lambda files, rc: bootstrap_source(raw, a.name, prepared['gate_token'], pilot_sha)
        runner.run(receipt['source_head'], receipt['gate'])
    except ca.AdmissionRefusal as e:
        print(json.dumps(dict(status='ADMISSION_REFUSED', refusal=str(e), transient=e.transient)))
        return 75 if e.transient else 3


if __name__ == '__main__':
    sys.exit(main())
