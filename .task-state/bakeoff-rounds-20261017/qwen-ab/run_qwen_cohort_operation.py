"""Qwen cohort operation runner v2: late-bound predecessor, landed-generator binding (decision 18673)."""
import argparse
import ast
import hashlib
import importlib.util
import json
import posixpath
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
BAKEOFF = HERE.parent
HOST = 'ubuntu@acx-backend.tail1a44b8.ts.net'
PREPARER = '.task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py'
CUSTODY_SOURCE = '22b61b6c7bc3932378dcb7e795a99f3ab288ff58'
WINDOW = re.compile(r"window=Path\('(/tmp/qwen-owner-window\.[A-Za-z0-9_-]+)'\)")
RUNNER_MODULES = ('run_selected_root_resume_qualification', 'run_owner_root_fixture_r6', 'bakeoff_frontier_capacity', 'orchestrate')
HELPER_SHA256 = 'f0ca0e59c1bc8db1dd83c99598f82c0fb3665a7dd443f66e44291f44f837a4cd'
SOURCE_ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/source'
RESULTS_ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/results'
REBUILD = 'rebuild: qwen-latebind/durable-source/build_durable_source.py'
RERUN = 're-run after checking VM load; rebuild only if it recurs'
SOURCE_LINES = dict(
    SOURCE=re.compile(r"^SOURCE='([0-9a-f]{40})'$", re.MULTILINE),
    repo=re.compile(r"^repo=Path\('" + re.escape(SOURCE_ROOT) + r"'\)/SOURCE$", re.MULTILINE),
    python=re.compile(r"^python=repo\.parent/\(SOURCE\+'\.venv'\)/'bin/python'$", re.MULTILINE),
    workspace=re.compile(r"^workspace=Path\('(" + re.escape(RESULTS_ROOT) + r"/[^'\n]+)'\);", re.MULTILINE),
)
BOUND = ('SOURCE', 'repo', 'python', 'workspace')
REPO_EXPR = ast.dump(ast.parse(f"Path('{SOURCE_ROOT}')/SOURCE", mode='eval').body)
PYTHON_EXPR = ast.dump(ast.parse("repo.parent/(SOURCE+'.venv')/'bin/python'", mode='eval').body)
RESULT_NAME = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*')
G = 1024**3


def need(ok, why):
    if not ok:
        raise ValueError(why)


# QDSG2-02..04, TEST-20: the uid 1002 clean check passes only these exact local config keys and untracked entries. Both are quoted into the DIFF
# shell text, so an entry with a quote or a newline would change that text.
KNOWN_REPO_CONFIG_KEYS = ('core.repositoryformatversion', 'core.filemode', 'core.bare', 'core.logallrefupdates')
KNOWN_RUNTIME_ENTRIES = ('apps/prototype-description-service/:memory:.ses', 'apps/prototype-description-service/prototype_description_service.egg-info/')
need(all("'" not in e and '\n' not in e for e in KNOWN_REPO_CONFIG_KEYS + KNOWN_RUNTIME_ENTRIES), 'a known entry cannot be quoted into the DIFF text')


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


def workspace_ok(p):
    # RLSE-33: the workspace is exactly <results root>/<NAME>/workspace. RESULT_NAME cannot start with '.', so '.' and '..' fail it;
    # normpath catches '//' and a trailing slash, which PurePosixPath would otherwise drop without a trace.
    parts = PurePosixPath(p).parts
    if len(parts) != 7:
        return False
    name = parts[5]
    return (parts == ('/', 'home', 'gate', 'bakeoff-rounds-20261017-inputs', 'results', name, 'workspace')
            and RESULT_NAME.fullmatch(name) is not None and posixpath.normpath(p) == p)


def bound_names(node):
    # Static AST coverage only: every name a node binds in the text, wherever it sits (stores and deletes, parameters, import aliases,
    # global and nonlocal, and any node that carries a name: defs, classes, except-as, match captures, type parameters, a mapping's **rest).
    # Runtime rebinding (globals(), exec, setattr on sys.modules) is out of scope: the recipe is generated and its sha256 is pinned.
    if isinstance(node, ast.Name):
        return [node.id] if isinstance(node.ctx, (ast.Store, ast.Del)) else []
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.alias):
        return [node.asname or node.name.split('.')[0]]
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    name = getattr(node, 'name', None) or getattr(node, 'rest', None)
    return [name] if isinstance(name, str) else []


def source_binding(raw):
    # RLSE-31/STOR-13: the recipe binds only the durable source root; a reaped lane sandbox is refused before any ssh.
    text = raw.decode()
    need('/home/gate/workbay-sandbox' not in text, 'recipe binds a reaped WorkBay lane sandbox')
    need('.venv-lane-' not in text, 'recipe binds a reaped lane venv (.venv-lane-)')
    hits = {name: pattern.findall(text) for name, pattern in SOURCE_LINES.items()}
    for name, found in hits.items():
        need(len(found) == 1, f'{name} line must appear exactly once, found {len(found)}')
    sha, workspace = hits['SOURCE'][0], hits['workspace'][0]
    need(workspace_ok(workspace), f'workspace must be {RESULTS_ROOT}/<NAME>/workspace, got {workspace!r}')
    # Static AST coverage only. The line checks above can be fooled (a second binding on the same line, a match inside a string), so the
    # module itself is counted too; runtime rebinding is out of scope (see bound_names).
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise ValueError(f'recipe does not parse: {e}') from e
    need(not any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names) for n in ast.walk(tree)),
         'recipe imports * and could rebind a bound name')
    counts = dict.fromkeys(BOUND, 0)
    for node in ast.walk(tree):
        for name in bound_names(node):
            if name in counts:
                counts[name] += 1
    assigned = {stmt.targets[0].id: stmt.value for stmt in tree.body
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)}
    for name in BOUND:
        need(counts[name] == 1, f'{name} must be bound exactly once, found {counts[name]} bindings')
        need(name in assigned, f'{name} is bound outside a module-level single-target assignment, found {counts[name]} binding')
    value = assigned['SOURCE']
    need(isinstance(value, ast.Constant) and isinstance(value.value, str) and re.fullmatch(r'[0-9a-f]{40}', value.value) is not None,
         'SOURCE must be a 40-hex str constant')
    need(ast.dump(assigned['repo']) == REPO_EXPR, 'repo must be exactly Path(<source root>)/SOURCE')
    need(ast.dump(assigned['python']) == PYTHON_EXPR, "python must be exactly repo.parent/(SOURCE+'.venv')/'bin/python'")
    ws = assigned['workspace']
    need(isinstance(ws, ast.Call) and isinstance(ws.func, ast.Name) and ws.func.id == 'Path' and len(ws.args) == 1 and not ws.keywords
         and isinstance(ws.args[0], ast.Constant) and isinstance(ws.args[0].value, str), 'workspace must be Path(<str constant>)')
    need(value.value == sha and ws.args[0].value == workspace, 'AST-derived SOURCE and workspace differ from the text-derived ones')
    return dict(source=sha, repo=f'{SOURCE_ROOT}/{sha}', python=f'{SOURCE_ROOT}/{sha}.venv/bin/python', workspace=workspace)


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


def preclaim_script(window, binding):
    # Read-only. Reports the GPU state, the newest publication, and the source roots as the recipe's uid 1002 children see them; no TTL is judged here, because the recipe refreshes AUTO.
    # The children share one 20 s deadline inside the caller's 30 s ssh. Root opens and creates nothing under a source tree: the diff child runs as
    # uid 1002, copies .git/index into its own private directory, and checks that copy against the worktree and the untracked entries.
    # Both allowlists are exact, not denylists (QDSG2-03, filters): a repo config key can name a filter or fsmonitor hook, so the child reads only the
    # local config and exits on any key outside KNOWN_REPO_CONFIG_KEYS before a git command can run one. Any untracked entry outside
    # KNOWN_RUNTIME_ENTRIES refuses, ignored ones too (no --exclude-standard), because those two are the observed known-good state (TEST-20).
    # Index bits that hide a change (assume-unchanged, skip-worktree) and tracked symlinks under the service directory refuse. hooksPath is pinned,
    # so no repo hook under .git/hooks runs when git writes the private copy.
    return '''import glob,json,os,pathlib,subprocess,time
DIFF="""set -e
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_OPTIONAL_LOCKS=0
idx=$(git -C "$1" rev-parse --path-format=absolute --git-path index)
d=$(mktemp -d)
trap 'rm -rf "$d"' EXIT
git -C "$1" config --local --no-includes --name-only --list > "$d/c"
rc=0; grep -v -x -F CONFIG_ARGS "$d/c" || rc=$?; [ "$rc" -le 1 ]
[ "$rc" -eq 1 ] || exit 0
cp -- "$idx" "$d/index"
export GIT_INDEX_FILE="$d/index"
git -c core.fsmonitor=false -c core.untrackedCache=false -c core.hooksPath=/dev/null -C "$1" ls-files -v > "$d/v"
rc=0; grep -E '^([a-z]|S) ' "$d/v" || rc=$?; [ "$rc" -le 1 ]
git -c core.fsmonitor=false -c core.untrackedCache=false -c core.hooksPath=/dev/null -C "$1" ls-files -s -- apps/prototype-description-service > "$d/s"
rc=0; grep -E '^120000 ' "$d/s" || rc=$?; [ "$rc" -le 1 ]
git -c core.fsmonitor=false -c core.untrackedCache=false -c core.hooksPath=/dev/null -C "$1" diff --cached --name-only HEAD
git -c core.fsmonitor=false -c core.untrackedCache=false -c core.hooksPath=/dev/null -C "$1" diff --name-only
git -c core.fsmonitor=false -c core.untrackedCache=false -c core.hooksPath=/dev/null -C "$1" ls-files --others --directory --no-empty-directory > "$d/o"
rc=0; grep -v -x -F ENTRY_ARGS "$d/o" || rc=$?; [ "$rc" -le 1 ]"""
w=pathlib.Path(WINDOW);b=BINDING
gpu=json.loads(pathlib.Path('/run/acx/gpu-state.json').read_bytes())
pubs=[]
for p in glob.glob(str(w/'ops'/'*'/'publication.json')):
 d=json.loads(pathlib.Path(p).read_bytes());pubs.append(dict(op=pathlib.Path(p).parent.name,action=d.get('action'),expires_at=d.get('expires_at'),sequence=d.get('sequence',-1)))
kw=dict(user=1002,group=1002,extra_groups=[],env=dict(PATH='/usr/local/bin:/usr/bin:/bin',HOME='/home/gate',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'),capture_output=True,text=True)
deadline=time.monotonic()+20
def left(own):return min(own,max(0.0,deadline-time.monotonic()))
def tree(root):
 s=dict(head=None,clean=False,head_rc=None,diff_rc=None,head_error=None,diff_error=None)
 t=left(10)
 if t<=0:s['head_error']='deadline_exhausted'
 else:
  try:h=subprocess.run(['git','-C',root,'rev-parse','HEAD'],timeout=t,**kw);s.update(head_rc=h.returncode,head=h.stdout.strip()if h.returncode==0 else None)
  except(OSError,subprocess.TimeoutExpired)as e:s['head_error']=type(e).__name__+': '+str(e)
 t=left(15)
 if t<=0:s['diff_error']='deadline_exhausted'
 else:
  try:d=subprocess.run(['/bin/sh','-c',DIFF,'sh',root],timeout=t,**kw);s.update(diff_rc=d.returncode,clean=d.returncode==0 and not d.stdout.strip())
  except(OSError,subprocess.TimeoutExpired)as e:s['diff_error']=type(e).__name__+': '+str(e)
 return s
repo=tree(b['repo']);workspace=tree(b['workspace'])
py=dict(executable=os.access(b['python'],os.X_OK),import_ok=None,stderr_tail=None,error=None)
if py['executable']:
 t=left(20)
 if t<=0:py['error']='deadline_exhausted'
 else:
  try:
   r=subprocess.run([b['python'],'-B','-c','import httpx,scripts.eval_harness.bakeoff'],cwd=b['workspace']+'/apps/prototype-description-service',timeout=t,**kw);py.update(import_ok=r.returncode==0,stderr_tail=r.stderr[-300:])
  except(OSError,subprocess.TimeoutExpired)as e:py['error']=type(e).__name__+': '+str(e)
print(json.dumps(dict(gpu=dict(state=gpu.get('state'),lease_expires_at=gpu.get('lease_expires_at')),publication=max(pubs,key=lambda x:x['sequence'],default=None),source=dict(repo=repo,workspace=workspace,python=py))))
'''.replace('WINDOW', repr(window)).replace('BINDING', repr(binding)).replace(
        'CONFIG_ARGS', ' '.join(f"-e '{k}'" for k in KNOWN_REPO_CONFIG_KEYS)).replace(
        'ENTRY_ARGS', ' '.join(f"-e '{e}'" for e in KNOWN_RUNTIME_ENTRIES))


ROOT_KEYS = ('head', 'clean', 'head_rc', 'diff_rc', 'head_error', 'diff_error')
PYTHON_KEYS = ('executable', 'import_ok', 'stderr_tail', 'error')


def classify_preclaim(report, binding):
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
    src = report.get('source')
    if not isinstance(src, dict):
        raise ca.AdmissionRefusal('malformed_payload', 'preclaim reply has no source mapping')
    for name, keys in (('repo', ROOT_KEYS), ('workspace', ROOT_KEYS), ('python', PYTHON_KEYS)):
        m = src.get(name)
        if not isinstance(m, dict) or any(k not in m for k in keys):
            raise ca.AdmissionRefusal('malformed_payload', f"preclaim source.{name} is not a mapping with {', '.join(keys)}")
    # NDM-06: a child that failed, timed out or was skipped reports an rc, an error or an unset field; each one refuses.
    # AGT-10, DIAG-07: an error is environmental until shown otherwise, so it names the field and the child where the fault stops and asks for a re-run.
    for name in ('repo', 'workspace'):
        r = src[name]
        observed = (f"observed head {r['head']!r} clean {r['clean']!r} head_rc {r['head_rc']!r} head_error {r['head_error']!r} "
                    f"diff_rc {r['diff_rc']!r} diff_error {r['diff_error']!r}")
        stops = [f"{field} {r[field]!r} stopped at {where}" for field, where in
                 (('head_error', 'git rev-parse HEAD'), ('diff_error', 'the diff child')) if r[field] is not None]
        if stops:
            raise ca.AdmissionRefusal('source_unavailable', f"environmental: {name} {binding[name]}: {'; '.join(stops)}; {observed}; {RERUN}")
        if not (r['head_rc'] == 0 and r['diff_rc'] == 0 and r['head'] == binding['source'] and r['clean'] is True):
            raise ca.AdmissionRefusal('source_unavailable', f"{name} {binding[name]}: expected HEAD {binding['source']} clean True rc 0 no error; "
                                      f"{observed}; {REBUILD}")
    py = src['python']
    if py['error'] is not None:
        raise ca.AdmissionRefusal('source_unavailable', f"environmental: python {binding['python']}: error {py['error']!r} stopped at the import child; "
                                  f"observed executable {py['executable']!r} import_ok {py['import_ok']!r} error {py['error']!r} "
                                  f"stderr_tail {py['stderr_tail']!r}; {RERUN}")
    if not (py['executable'] is True and py['import_ok'] is True):
        raise ca.AdmissionRefusal('source_unavailable', f"python {binding['python']}: expected executable True import_ok True no error; "
                                  f"observed executable {py['executable']!r} import_ok {py['import_ok']!r} error {py['error']!r} "
                                  f"stderr_tail {py['stderr_tail']!r}; {REBUILD}")
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
    need(pr.get('predecessor_binding') == 'late_bound_at_claim_refresh', 'pilot predates the late-bound generator; run a fresh pilot')
    need(pr.get('preparer_sha256') == prepared['preparer_sha256'], 'pilot was prepared by a different generator than the full recipe')
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


def module_digest(spec):
    # A namespace package has no file, so it has no bytes to digest; the receipt records None for it.
    return hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest() if spec.has_location else None


def main(argv=None):
    a = parse_args(argv)
    sys.path[:0] = [str(HERE), str(BAKEOFF)]
    import cohort_admission as ca
    d = Path(a.dir)
    prepared = json.loads((d/(a.name + '.prepared.json')).read_bytes())
    raw = (d/(a.name + '.remote.py')).read_bytes()
    try:
        # Pinned before the runner is imported: the runner bytes against the reviewed reference copy, and the helper record against its pinned sha256.
        # The leaf modules (run_owner_root_fixture_r6, bakeoff_frontier_capacity, orchestrate) are resolved here, not pinned. Two of them
        # (bakeoff_frontier_capacity, orchestrate) are untracked and have no reviewed copy; their sha256 is recorded as module_sha256 in the receipt.
        specs = {name: importlib.util.find_spec(name) for name in RUNNER_MODULES}
        for name in RUNNER_MODULES:
            need(specs[name] is not None, f'{name} is missing: not found on sys.path')
        module_sha256 = {name: module_digest(specs[name]) for name in RUNNER_MODULES}
        origin = specs['run_selected_root_resume_qualification'].origin
        reviewed = HERE/'references'/'admission'/'run_selected_root_resume_qualification.py'
        need(origin is not None and hashlib.sha256(Path(origin).read_bytes()).hexdigest() == hashlib.sha256(reviewed.read_bytes()).hexdigest(),
             'runner differs from the reviewed reference copy')
        helper_path = d/'LEXICON-MIMO-40-LAST40-R1.prepared.json'
        try:
            helper_raw = helper_path.read_bytes()
        except FileNotFoundError as e:
            raise ValueError(f'helper record is missing: {helper_path}') from e
        need(hashlib.sha256(helper_raw).hexdigest() == HELPER_SHA256, 'helper record sha256 differs from the pinned record')
        need(helper_raw == (HERE/'references'/'LEXICON-MIMO-40-LAST40-R1.prepared.json').read_bytes(),
             'helper record differs from the reviewed reference copy')
        import run_selected_root_resume_qualification as runner
        base, cap = runner.admission, runner.cap
        need(prepared.get('name') == a.name, f"prepared record is for {prepared.get('name')!r}, not --name {a.name!r}")
        window = verify_prepared(prepared, raw)
        binding = source_binding(raw)
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
    helper = json.loads(helper_raw)
    receipt = dict(prepared, source_head=g['source_sha'], gate='QWEN-AB-G2', stage=helper['stage'],
                   manifest_sha256=helper['manifest_sha256'], helper_source_head=helper['source_head'],
                   helper_independent_gate=helper['gate'], remote_orchestration_sha256=prepared['recipe_sha256'],
                   actual_pilot=a.pilot, actual_pilot_receipt_sha256=pilot_sha, actual_pilot_custody_sha256=pilot_custody,
                   predecessor_binding=prepared['predecessor_binding'], gate_commit=a.gate_commit, module_sha256=module_sha256,
                   source_binding=binding)
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
        report = ca.ssh_json(['ssh', '-oBatchMode=yes', HOST, 'sudo -n /usr/bin/python3 -I -B -'], preclaim_script(window, binding), 30)
        cap.persist(BAKEOFF/(a.name + '.preclaim.json'), report)
        receipt['preclaim'] = classify_preclaim(report, binding)
        ca.admit()
        runner.admission.guard = ca.guard
        runner.inputs = inputs
        runner.bootstrap = lambda files, rc: bootstrap_source(raw, a.name, prepared['gate_token'], pilot_sha)
        runner.run(receipt['source_head'], receipt['gate'])
        # The shared runner returns None; the remote exit code exists only in the terminal record it writes before returning.
        terminal = json.loads((runner.P/(runner.N + '.transport-terminal.json')).read_bytes())
    except ca.AdmissionRefusal as e:
        print(json.dumps(dict(status='ADMISSION_REFUSED', refusal=str(e), transient=e.transient)))
        return 75 if e.transient else 3
    if terminal['exit_code'] == 0:
        return 0
    print(json.dumps(dict(status='ROOT_TRANSPORT_FAILED', exit_code=terminal['exit_code'])))
    return 4


if __name__ == '__main__':
    sys.exit(main())
