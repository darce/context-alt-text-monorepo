"""Narrow custody settlement. No model execution or automatic retry.

Allowlist: LEXICON-QWEN-UD-{PILOT,30}-Rn and the exact legacy GSQ
[PILOT,C01..C06,R2-038] forms (optional legacy 20 prefix). Rn is positive.
CLI requires explicit canonical operational repo, prepared directory and pinned
capacity module root/hash; importing this module never imports the controller.
"""
import argparse
import ast
import base64
import contextlib
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile
import uuid

class Refused(RuntimeError):
    pass

def need(value, message):
    if not value:
        raise Refused(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def identity(name):
    exact = {'LEXICON-QWEN-GSQ-MISSING-C064-R1': ('gsq', 'missing-c064', 'qwen-gsq-missing-c064-r1'),
             'LEXICON-QWEN-UD-MISSING-04-R1': ('ud', 'missing-04', 'qwen-ud-missing-04-r1')}
    if name in exact:
        return exact[name]
    m = re.fullmatch(r"LEXICON-QWEN-(UD)-(PILOT|30)-(R[1-9][0-9]*)", name)
    if not m:
        m = re.fullmatch(r"LEXICON-QWEN-(GSQ)-(?:20-)?(PILOT|C0[1-6]|R2-038)-(R[1-9][0-9]*)", name)
    need(m, 'operation outside strict allowlist')
    candidate, mode, revision = (x.lower() for x in m.groups())
    return candidate, mode, f'qwen-{candidate}-{mode}-{revision}'

class Fence:
    """Read-only, no-follow, held descriptors for every component and leaf."""
    def __init__(self, path):
        self.path = Path(path)
        need(self.path.is_absolute() and '..' not in self.path.parts, 'noncanonical path')
        self.held = []
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            self.held.append((Path('/'), fd))
            current = Path('/')
            for part in self.path.parts[1:]:
                current = current / part
                fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=fd)
                self.held.append((current, fd))
            need(stat.S_ISREG(os.fstat(fd).st_mode) or stat.S_ISDIR(os.fstat(fd).st_mode), 'nonregular fence')
            self.check()
        except BaseException:
            self.close()
            raise
    def check(self):
        for path, fd in self.held:
            a, b = os.fstat(fd), os.stat(path, follow_symlinks=False)
            need((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) and not stat.S_ISLNK(b.st_mode), 'held inode replaced: '+str(path))
    def read(self):
        self.check()
        fd = self.held[-1][1]
        os.lseek(fd, 0, 0)
        chunks = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        self.check()
        return b''.join(chunks)
    def close(self):
        for _, fd in reversed(self.held):
            os.close(fd)
        self.held = []

class Namespace:
    def __init__(self, repo):
        self.root = Path(repo)
        self.p = self.root / '.task-state/bakeoff-rounds-20261017'
        self.shared = self.root / '.task-state/auraface-deploy-20261017'
        self.ledger = self.shared / 'shared-capacity-reservations-20261018.json'
        self.owner = self.shared / 'sibling-capacity/bakeoff.json'
        self.lease = self.p / 'bakeoff-ready-frontier.self-reservation.json'
        self.phases = self.p / 'bakeoff-ready-frontier.phases.json'
        self.out = self.root / 'benchmark'
        self.locks = [self.root / '.task-state/gtm-continue-20261012/vm-launch.lock',
                      self.shared / 'shared-capacity-reservations-20261018.owner-update.lock']
    def bind(self, module):
        canonical = dict(ROOT=self.root, P=self.p, SHARED=self.shared, LEDGER=self.ledger,
                         OWNER=self.owner, LEASE=self.lease, PHASES=self.phases)
        for key, value in canonical.items():
            setattr(module, key, value)
        # Any other Path global would still name the private module copy's state.
        stray = sorted(key for key, value in vars(module).items()
                       if isinstance(value, PurePosixPath) and canonical.get(key) != value)
        need(not stray, 'capacity Path globals outside canonical namespace: '+', '.join(stray))

def load_capacity(root, digest, ns):
    path = Path(root) / 'bakeoff_frontier_capacity.py'
    with contextlib.ExitStack() as stack:
        fence = Fence(path); stack.callback(fence.close)
        raw = fence.read()
        need(sha(raw) == digest, 'capacity module pin mismatch')
        # Execute exactly the checked bytes, never an ambient module or pycache.
        spec = importlib.util.spec_from_loader('_settler_pinned_capacity', loader=None)
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), module.__dict__)
    ns.bind(module)
    return module

PROGRAM = r"""import pathlib,subprocess,json,hashlib,tarfile,io,sys,shutil
base=pathlib.Path(BASE);unit=UNIT
assert(base/'permanent'/'owned-window-return.json').is_file(),'Public owned return is required before settlement'
assert(base/'permanent'/'completed-physical-lease-closed.json').is_file(),'Public STOP receipt is required before settlement'
returned=json.loads((base/'permanent'/'owned-window-return.json').read_bytes());assert returned['Qwen_restored']and returned['owned_client_reaped']and returned['owned_candidate_reaped'],returned
records=[]
for path in(base/'permanent').rglob('raw*.json'):
 value=json.loads(path.read_bytes())
 if value.get('schema')=='description-lexicon-paired-run/v1':records.append(value)
items=[item for record in records for item in record.get('items',[])]
execution=dict(raw_records=len(records),recorded_completion_POST_attempts=sum(r.get('post_attempts',0)for r in records),persisted_image_rows=len(items),contract_valid_pairs=sum(r.get('valid_pairs',0)for r in records),request_count_scope='Persisted raw records only; absence of raw records does not establish zero requests',human_quality_verified=False)
window=pathlib.Path(WINDOW);assert not(base/'post-recovery-window-snapshot').exists();shutil.copytree(window,base/'post-recovery-window-snapshot',symlinks=True)
u=dict(x.split('=',1)for x in subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','ControlGroup'],text=True,timeout=8).splitlines());cg=pathlib.Path('/sys/fs/cgroup')/pathlib.Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/');assert u['ActiveState']=='active'and str(cg)=='/sys/fs/cgroup'+u['ControlGroup'];assert(cg/'memory.max').read_text().strip()=='2147483648'
files={}
for p in sorted(base.rglob('*')):
 assert not p.is_symlink(),p
 if p.is_file():files[str(p.relative_to(base))]=dict(bytes=p.stat().st_size,sha256=hashlib.file_digest(p.open('rb'),'sha256').hexdigest())
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|')as t:
 for name,meta in files.items():
  p=base/name;assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==meta['sha256'];t.add(p,arcname=name,recursive=False)
 data=json.dumps(dict(files=files,base=str(base),execution_evidence=execution,owned_START_STOP_AUTO_published=True)).encode();m=tarfile.TarInfo('custody-manifest.json');m.size=len(data);m.mode=0o600;t.addfile(m,io.BytesIO(data))
"""

PROBE = r"""import pathlib,subprocess,json,errno,os,time
base=BASE;unit=UNIT;roots=[base,WINDOW,*STAGES]
u=dict(x.split('=',1)for x in subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','ControlGroup'],text=True,timeout=8).splitlines());assert u['ActiveState']=='inactive'and not u['ControlGroup'],u
hits=[];errors=[];zombie_mountinfo=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdecimal()or int(p.name)==os.getpid():continue
 try:
  for f in [p/'cwd',p/'root',p/'exe',*(p/'fd').iterdir()]:
   try:
    s=os.readlink(f).removesuffix(' (deleted)')
    if any(s==b or s.startswith(b+'/')for b in roots):hits.append([p.name,str(f)])
   except OSError as e:
    if e.errno not in [errno.ENOENT,errno.ESRCH,errno.EINVAL]:errors.append([p.name,e.errno])
  for name in ['maps','mountinfo']:
   before=(p/'stat').read_text().rsplit(') ',1)[1].split()
   try:
    if any(b in(p/name).read_text(errors='replace')for b in roots):hits.append([p.name,name])
   except OSError as e:
    after=(p/'stat').read_text().rsplit(') ',1)[1].split()
    if name=='mountinfo'and e.errno==errno.EINVAL and before[0]==after[0]=='Z'and before[19]==after[19]:zombie_mountinfo.append(dict(pid=p.name,start=before[19],state='Z',file='mountinfo',errno=e.errno))
    else:raise
 except OSError as e:
  if e.errno not in [errno.ENOENT,errno.ESRCH]:errors.append([p.name,e.errno])
assert not hits and not errors,(hits,errors)
s=json.loads(pathlib.Path('/run/acx/gpu-state.json').read_bytes());assert s['state']=='stopped'and s.get('lease_expires_at')is None,s
print(json.dumps(dict(at=time.time(),unit=u,UID0_hits=0,UID0_errors=0,GPU_stopped=True,zombie_mountinfo_observations=zombie_mountinfo)))
"""

CAPACITY_SHA256 = '03f28439b70d40ef64584d8cbad2dc392c3da16c7dda258d72107c07a4ffe2f3'
MODEL = {
    'ud': ('Qwen3.8-27B-UD-Q4_K_XL', 'bee238bbeb3dc0a34bde4d0dedbaee1f98c009e8bb4226f03070054c12fb1372', 'cbb841a9ee0636b2ec172f5bb8df2ea8dfeb01e90fe7c6126581d662a0b4e43e'),
    'gsq': ('Qwen3.8-27B-GSQ-RCO-IQ3_S', '64b53b64c7aa39f20a7e54bd80582fe595b1d745624ee8a72e92508c0326d810', '13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16'),
}
GSQ_CONFIGS = {'qwen-gsq-01.json': '928cf319e30998de2cd15f24efc547db983f336b47c9d23e2917938d9ff22327', 'qwen-gsq-02.json': 'a716982076e94fd98524b68325cf48fbabe6c1631c5a8d059efc1701a6e00611', 'qwen-gsq-03.json': '2502ad2b7e931b92da02d2534ad47b01c51379d6dcb65762eaed6407f14ae47c', 'qwen-gsq-04.json': 'bb33a87dd025f166100b452d300c9ffc1b8d8f653f75bfad35fef024c31e4a59', 'qwen-gsq-05.json': '36341b56c72f48872b59db5dacba054947b5f924cc179d2a36e082129ddd63ea', 'qwen-gsq-06.json': 'ed540c7404a20fa58a09b61cd710dea402f760adf863a5e7d88c9224a65bff02'}
UD_CONFIGS = {'qwen-ud-01.json': '8aade2c85b6ad2815c99e32ca5c8e75314411e16e7cd83071a3bab82f48b4056',
              'qwen-ud-02.json': '3eed8b0d0547dba8cb2459ea181d33cbc7769b138b92d84cc79612cb4fc31d32'}
UD_PILOT = '00e6870e7857cda9328fb9fb4a229b02a3bfb87d91848e6aa9fd023c75c303f4'
HOST = 'ubuntu@acx-backend.tail1a44b8.ts.net'
WINDOW = '/tmp/qwen-owner-window.rcqmefq9'
STAGES = ['/root/bakeoff-owner-long-window-20261019-45c86daf3bc3', '/root/bakeoff-owner-long-window-20261020-cd399f1f0d55']

def integer(value, label):
    need(type(value) is int and value >= 0, 'invalid integer '+label)
    return value

def safe_member(name):
    p = PurePosixPath(name)
    need(not p.is_absolute() and '..' not in p.parts and str(p) == name and name != '.', 'unsafe archive member')
    return name

# Typed evidence. Every consumed JSON value is shape-checked before it is indexed,
# summed or compared; malformed input is Refused, never TypeError or KeyError.
def strict_json(raw, label):
    """One UTF-8 JSON document; duplicate keys and non-finite numbers are refused."""
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, 'duplicate JSON key in '+label)
            value[key] = item
        return value
    def finite(token):
        value = float(token)
        need(-float('inf') < value < float('inf'), 'non-finite JSON number in '+label)
        return value
    def constant(token):
        raise Refused('non-finite JSON number in '+label)
    try:
        return json.loads(raw.decode(), object_pairs_hook=pairs, parse_float=finite, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise Refused('malformed JSON in '+label+': '+type(exc).__name__) from None

def shape(value, label, **fields):
    """Exact JSON object whose named fields are present and pass their type check."""
    need(type(value) is dict, 'invalid object '+label)
    for key, kind in fields.items():
        need(key in value, 'missing field '+label+'.'+key)
        kind(value[key], label+'.'+key)
    return value

def text(value, label):
    need(type(value) is str, 'invalid string '+label)
    return value

def optional_text(value, label):
    need(value is None or type(value) is str, 'invalid string or null '+label)
    return value

def boolean(value, label):
    need(type(value) is bool, 'invalid boolean '+label)
    return value

def signed_int(value, label):
    need(type(value) is int, 'invalid integer '+label)
    return value

def sha256_hex(value, label):
    need(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'invalid sha256 '+label)
    return value

def json_dict(value, label):
    need(type(value) is dict, 'invalid object '+label)
    return value

def json_list(value, label):
    need(type(value) is list, 'invalid list '+label)
    return value

def profile_map(value, label):
    need(type(value) is dict and all(type(v) is dict for v in value.values()), 'invalid profiles '+label)
    return value

def config_images(raw, label):
    cfg = shape(strict_json(raw, label), label, model_version=text, model_revision=text, images=json_list)
    for image in cfg['images']:
        shape(image, label+' image', image_id=text, sha256=text)
        need(type(image.get('source_cluster', '')) is str, 'invalid source_cluster '+label)
    return cfg

def validate_prepared(name, prepared):
    """Receipt fields consumed by settle and prepared_contract, typed before any use."""
    candidate, _, _ = identity(name)
    shape(prepared, 'prepared', name=text, candidate=text, mode=text, unit=text, recipe_sha256=sha256_hex,
        model_contract=json_dict, configs=json_dict, immutable_candidate_configs=json_dict, source_binding=json_dict,
        total_distinct_images=integer, completion_POST_budget=integer, per_image_POST_cap=integer)
    for filename, pin in prepared['configs'].items():
        need(re.fullmatch('qwen-'+candidate+r'-0[1-6]\.json', filename), 'config name')
        sha256_hex(pin, 'prepared config '+filename)
    binding = shape(prepared['source_binding'], 'prepared source_binding', source=text)
    need(re.fullmatch('[0-9a-f]{40}', binding['source']) and all(type(v) is str for v in binding.values()),
         'invalid prepared source_binding')
    if candidate == 'ud':
        shape(prepared, 'prepared', candidate_runtime_seconds=integer, intent_seconds=integer,
            whole_client_seconds=integer)

def validate_claim(claim):
    """Capacity claim fields settle consumes before the canonical state is read."""
    shape(claim, 'capacity claim', captured_at=text, native_unit=text)
    if 'remaining_actor_claim' in claim:
        integer(claim['remaining_actor_claim'], 'capacity claim remaining_actor_claim')

def validate_claim_states(claim, ledger, owner, lease):
    """Typed claim/ledger/owner/lease fields consumed by settle; never mutates them."""
    validate_claim(claim)
    allocation = dict(captured_at=text, profiles=profile_map, remaining_actor_claim=integer,
                      native_unit=optional_text)
    shape(ledger, 'ledger', Bakeoff=json_dict, setup_owner=optional_text, pending_reservations=json_list)
    shape(ledger['Bakeoff'], 'ledger Bakeoff', **allocation)
    for reservation in ledger['pending_reservations']:
        shape(reservation, 'ledger pending reservation', owner=text)
    shape(lease, 'lease', **allocation)
    shape(owner, 'owner', captured_at=text, remaining_actor_claim=integer,
        exact_self_reserved_profiles=profile_map)

NATIVE_PROOF = ('at', 'unit', 'UID0_hits', 'UID0_errors', 'GPU_stopped', 'zombie_mountinfo_observations')

def validate_native_proof(proof):
    """Exact PROBE output shape; semantic inactive/zero checks stay with the caller."""
    shape(proof, 'native proof', unit=json_dict, UID0_hits=integer, UID0_errors=integer, GPU_stopped=boolean)
    need(set(proof) <= set(NATIVE_PROOF), 'unknown native proof field')
    shape(proof['unit'], 'native proof unit', ActiveState=text, ControlGroup=text)
    need(set(proof['unit']) == {'ActiveState', 'ControlGroup'}, 'unknown native proof unit field')
    if 'at' in proof:
        at = proof['at']
        need(type(at) in (int, float) and -float('inf') < at < float('inf'), 'invalid native proof at')
    for row in json_list(proof.get('zombie_mountinfo_observations', []), 'native proof zombie_mountinfo_observations'):
        shape(row, 'zombie mountinfo observation', pid=text, start=text, state=text, file=text, errno=integer)
        need(set(row) == {'pid', 'start', 'state', 'file', 'errno'}, 'unknown zombie mountinfo field')

# Runtime binding is derived from the checked recipe bytes with the coordinator's
# source_binding rules (text lines plus static AST), never executing the recipe.
SOURCE_ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/source'
RESULTS_ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/results'
BINDING_LINES = dict(
    SOURCE=re.compile(r"^SOURCE='([0-9a-f]{40})'$", re.MULTILINE),
    repo=re.compile(r"^repo=Path\('" + re.escape(SOURCE_ROOT) + r"'\)/SOURCE$", re.MULTILINE),
    python=re.compile(r"^python=repo\.parent/\(SOURCE\+'\.venv'\)/'bin/python'$", re.MULTILINE),
    workspace=re.compile(r"^workspace=Path\('(" + re.escape(RESULTS_ROOT) + r"/[^'\n]+)'\);", re.MULTILINE),
)
REPO_EXPR = ast.dump(ast.parse(f"Path('{SOURCE_ROOT}')/SOURCE", mode='eval').body)
PYTHON_EXPR = ast.dump(ast.parse("repo.parent/(SOURCE+'.venv')/'bin/python'", mode='eval').body)

def bound_names(node):
    # Same static coverage as coordinator.bound_names: every name a node binds in the text.
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

def recipe_tree(recipe):
    need(type(recipe) is bytes, 'invalid recipe bytes')
    try:
        code = recipe.decode()
        return code, ast.parse(code)
    except (ValueError, SyntaxError, RecursionError) as exc:
        raise Refused('recipe does not parse: '+type(exc).__name__) from None

def recipe_binding(recipe):
    """Runtime source binding named by the recipe, equivalent to coordinator.source_binding."""
    code, tree = recipe_tree(recipe)
    need('/home/gate/workbay-sandbox' not in code and '.venv-lane-' not in code, 'recipe binds a reaped lane')
    hits = {key: pattern.findall(code) for key, pattern in BINDING_LINES.items()}
    need(all(len(found) == 1 for found in hits.values()), 'recipe binding lines must appear exactly once')
    source, workspace = hits['SOURCE'][0], hits['workspace'][0]
    parts = PurePosixPath(workspace).parts
    need(len(parts) == 7 and parts == ('/', 'home', 'gate', 'bakeoff-rounds-20261017-inputs', 'results', parts[5], 'workspace')
         and re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', parts[5]) and os.path.normpath(workspace) == workspace,
         'recipe workspace identity')
    need(not any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names) for n in ast.walk(tree)),
         'recipe imports *')
    counts = dict.fromkeys(BINDING_LINES, 0)
    for node in ast.walk(tree):
        for bound in bound_names(node):
            if bound in counts:
                counts[bound] += 1
    assigned = {stmt.targets[0].id: stmt.value for stmt in tree.body
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)}
    need(all(counts[key] == 1 and key in assigned for key in BINDING_LINES), 'recipe binding names bound once at module level')
    value, ws = assigned['SOURCE'], assigned['workspace']
    need(isinstance(value, ast.Constant) and type(value.value) is str and value.value == source, 'recipe SOURCE constant')
    need(ast.dump(assigned['repo']) == REPO_EXPR and ast.dump(assigned['python']) == PYTHON_EXPR, 'recipe repo/python expression')
    need(isinstance(ws, ast.Call) and isinstance(ws.func, ast.Name) and ws.func.id == 'Path' and len(ws.args) == 1
         and not ws.keywords and isinstance(ws.args[0], ast.Constant) and ws.args[0].value == workspace, 'recipe workspace expression')
    return dict(source=source, repo=SOURCE_ROOT+'/'+source, python=SOURCE_ROOT+'/'+source+'.venv/bin/python', workspace=workspace)

def recipe_configs(recipe):
    """The recipe's own embedded config literal, read without execution."""
    _, tree = recipe_tree(recipe)
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'configs' for t in n.targets)]
    need(len(nodes) == 1, 'recipe must embed exactly one configs literal')
    try:
        return json_dict(ast.literal_eval(nodes[0].value), 'recipe configs')
    except (ValueError, TypeError, SyntaxError, RecursionError):
        raise Refused('recipe configs are not a literal') from None

def validate_recipe_binding(recipe, prepared):
    """Receipt runtime binding and config pins must be the ones the checked recipe names."""
    shape(prepared, 'prepared', recipe_sha256=sha256_hex, source_binding=json_dict, configs=json_dict)
    need(type(recipe) is bytes and sha(recipe) == prepared['recipe_sha256'], 'recipe identity')
    need(prepared['source_binding'] == recipe_binding(recipe), 'runtime source binding differs from the checked recipe')
    embedded = recipe_configs(recipe)
    need(list(embedded) == list(prepared['configs']), 'recipe config selection')
    for filename, pin in embedded.items():
        shape(pin, 'recipe config '+filename, b64=text, sha256=sha256_hex)
        try:
            raw = base64.b64decode(pin['b64'], validate=True)
        except ValueError:
            raise Refused('recipe config encoding '+filename) from None
        need(sha(raw) == pin['sha256'] == prepared['configs'][filename], 'recipe config pin '+filename)

def prepared_contract(name, prepared, configs):
    candidate, mode, _ = identity(name)
    validate_prepared(name, prepared)
    need(type(configs) is dict and all(type(raw) is bytes for raw in configs.values()), 'selected config bytes')
    need(prepared['name'] == name and prepared['candidate'] == candidate, 'prepared identity')
    version, model, _ = MODEL[candidate]
    need(prepared['model_contract'] == dict(model_version=version, model_revision='sha256:'+model,
                                          wire_model_id='/models/'+version+'.gguf'), 'prepared model contract')
    need(set(configs) == set(prepared['configs']), 'selected config set')
    images = []; counts = []
    for filename, raw in configs.items():
        need(re.fullmatch('qwen-'+candidate+r'-0[1-6]\.json', filename), 'config name')
        need(sha(raw) == prepared['configs'][filename], 'prepared config hash')
        cfg = config_images(raw, filename)
        need(cfg['model_version'] == version and cfg['model_revision'] == 'sha256:'+model, 'config model')
        images.extend(cfg['images']); counts.append(len(cfg['images']))
    ids = [i['image_id'] for i in images]
    need(len(set(ids)) == len(ids), 'duplicate prepared image')
    if mode.startswith('missing-'):
        # Reuse offline canonical caller validation; publication/custody paths stay unchanged.
        import sys
        helper_root = Path(__file__).resolve().parent.parent / 'qwen-ab'
        spec = importlib.util.spec_from_file_location('qwen_missing_caller', helper_root / 'run_qwen_cohort_operation.py')
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(helper_root))
        try:
            spec.loader.exec_module(module)
            module.verify_missing(prepared)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise Refused('missing contract: ' + str(exc)) from None
        finally:
            sys.path.pop(0)
        expected = 1 if candidate == 'gsq' else 4
        need(len(ids) == expected, 'missing image count')
        return candidate, expected
    expected = 2 if mode == 'pilot' else 30 if mode == '30' else 1 if mode == 'r2-038' else 20
    need(len(ids) == prepared['total_distinct_images'] == expected, 'prepared image count')
    need(prepared['completion_POST_budget'] == 3*expected and prepared['per_image_POST_cap'] == 3, 'prepared budget')
    need(prepared['mode'] == ('pilot' if mode == 'pilot' else 'replacement' if mode == 'r2-038' else 'full'), 'prepared mode')
    if candidate == 'gsq':
        need(prepared['immutable_candidate_configs'] == GSQ_CONFIGS, 'GSQ frozen config pins')
        selected = 'qwen-gsq-02.json' if mode == 'r2-038' else 'qwen-gsq-01.json' if mode == 'pilot' else 'qwen-gsq-'+mode[1:]+'.json'
        need(list(configs) == [selected], 'GSQ selected config')
        if mode.startswith('c'):
            need(prepared['configs'][selected] == GSQ_CONFIGS[selected], 'GSQ selected config pin')
        if mode == 'r2-038':
            need(ids == ['original-038'] and images[0]['sha256'] == '710a6798653ef868338136da63e2c176e892d73bac342e395bf0df640e70022e', 'original-038 replacement identity')
    if candidate == 'ud':
        need(prepared['immutable_candidate_configs'] == UD_CONFIGS, 'UD frozen config pins')
        need(prepared['configs'] == ({'qwen-ud-01.json': UD_PILOT} if mode == 'pilot' else UD_CONFIGS), 'UD selected config pins')
        need(prepared['candidate_runtime_seconds'] == 1500 and prepared['intent_seconds'] == 1800
             and 0 < prepared['whole_client_seconds'] <= 1000, 'UD time bounds')
        need(counts == ([2] if mode == 'pilot' else [20, 10]), 'UD cohort selection')
        need(list(configs) == (['qwen-ud-01.json'] if mode == 'pilot' else ['qwen-ud-01.json', 'qwen-ud-02.json']), 'UD config selection')
        need('original-038' not in ids, 'original-038 is outside UD')
        if mode == 'pilot':
            need(ids == ['c001', 'c002'], 'UD pilot images')
    return candidate, expected

def verify_archive(path, name, prepared, configs, base, recipe=None):
    """Validate collected custody. With recipe, the runtime binding is also checked against it."""
    candidate, expected = prepared_contract(name, prepared, configs)
    if recipe is not None:
        validate_recipe_binding(recipe, prepared)
    try:
        with tarfile.open(path, 'r:') as archive:
            members = archive.getmembers()
            names = [safe_member(m.name) for m in members]
            need(len(names) == len(set(names)) and all(m.isfile() for m in members), 'duplicate or nonregular archive member')
            data = {m.name: archive.extractfile(m).read() for m in members}
    except (tarfile.TarError, EOFError) as exc:
        raise Refused('unreadable custody archive: '+type(exc).__name__) from None
    def document(member):
        need(member in data, 'missing archive member '+member)
        return strict_json(data[member], member)
    manifest = document('custody-manifest.json'); del data['custody-manifest.json']
    shape(manifest, 'custody manifest', base=text, owned_START_STOP_AUTO_published=boolean, files=json_dict,
        execution_evidence=json_dict)
    need(manifest['base'] == base and manifest['owned_START_STOP_AUTO_published'] is True, 'custody base/publication')
    need(set(data) == set(manifest['files']), 'manifest member set')
    for filename, raw in data.items():
        meta = shape(manifest['files'][filename], 'manifest file '+filename, bytes=integer, sha256=sha256_hex)
        need(meta['bytes'] == len(raw) and meta['sha256'] == sha(raw), 'member size/hash')
    result = shape(document('permanent/candidate-result.json'), 'candidate result', complete=boolean, execution_complete=boolean,
                 status=text, quality_or_winner=boolean, isolated_performance=boolean, source_head=text,
                 one_model_residency=boolean, authenticated_header_present=boolean, model_sha256=text,
                 projector_sha256=text, requested_images=integer, evaluated_images=integer, raw_passes=integer,
                 item_errors=integer, cohorts=json_list)
    need(result['execution_complete'] is True, 'NOT_EVALUATED/UNKNOWN: partial execution')
    need(result['status'] == ('COHORT_RAW_COMPLETE' if result['complete'] else 'COHORT_ATTEMPT_RECORDED'), 'candidate result status')
    need(result['quality_or_winner'] is False and result['isolated_performance'] is False, 'quality claim refused')
    need(result['source_head'] == prepared['source_binding']['source'], 'runtime source binding')
    source = shape(document('permanent/source-and-input.json'), 'source and input', source_head=text,
                 model_version=text, model_revision=text, request_budget=integer, candidate_configs=json_list,
                 input_manifest_sha256=text)
    need(source['source_head'] == prepared['source_binding']['source']
         and source['model_version'] == MODEL[candidate][0]
         and source['model_revision'] == prepared['model_contract']['model_revision']
         and source['request_budget'] == prepared['completion_POST_budget'], 'source/input contract')
    need(len(source['candidate_configs']) == len(configs), 'input cohort count')
    for cohort, (filename, raw) in zip(source['candidate_configs'], configs.items()):
        shape(cohort, 'input cohort', id=text, sha256=text, manifest=text, count=integer)
        need(cohort['id'] == Path(filename).stem and cohort['sha256'] == sha(raw)
             and cohort['manifest'] == base+'/batch-inputs/'+filename
             and cohort['count'] == len(config_images(raw, filename)['images']), 'input cohort identity')
    need(source['input_manifest_sha256'] == sha(next(iter(configs.values()))), 'input manifest identity')
    need(result['one_model_residency'] is True and result['authenticated_header_present'] is True, 'candidate runtime identity')
    need(result['model_sha256'] == MODEL[candidate][1] and result['projector_sha256'] == MODEL[candidate][2], 'candidate model hashes')
    need(result['requested_images'] == result['evaluated_images'] == expected, 'candidate image count')
    errors = result['item_errors']
    need(errors <= expected and result['complete'] == (errors == 0), 'candidate completion/errors')
    cohorts = result['cohorts']
    need(len(cohorts) == len(configs), 'cohort count')
    raw_names = {k for k in data if PurePosixPath(k).name.startswith('raw') and k.endswith('.json')
                 and k.startswith('permanent/')}
    expected_raw = set()
    seen = set(); posts = valid = row_errors = total_passes = 0
    for cohort, (filename, cfg_raw) in zip(cohorts, configs.items()):
        images = config_images(cfg_raw, filename)['images']; count = len(images)
        cid = Path(filename).stem
        shape(cohort, 'cohort '+cid, id=text, requested_images=integer, evaluated_images=integer, item_errors=integer,
            execution_complete=boolean, owned_client_exit=signed_int, owned_client_timed_out=boolean,
            owned_client_natively_reaped=boolean, raw_path=text, raw_sha256=text, raw_passes=integer)
        need(cohort['id'] == cid and cohort['requested_images'] == cohort['evaluated_images'] == count, 'cohort identity/count')
        need(cohort['execution_complete'] is True and cohort['owned_client_exit'] == 0
             and cohort['owned_client_timed_out'] is False
             and cohort['owned_client_natively_reaped'] is True, 'NOT_EVALUATED/UNKNOWN: client transport')
        raw_name = 'permanent/'+cid+'/raw.json'
        need(cohort['raw_path'] == base+'/'+raw_name, 'raw path identity')
        expected_raw.add(raw_name)
        need(raw_name in data and sha(data[raw_name]) == cohort['raw_sha256'], 'cohort raw hash')
        # Config bytes must be the exact selected, prepared input, not a reserialization.
        need(data.get('batch-inputs/'+filename) == cfg_raw, 'archived config identity')
        raw = shape(document(raw_name), raw_name, schema=text, completed=boolean, dry_run=boolean, model_id=text,
                  model_revision=text, items=json_list, post_attempts=integer, request_budget=integer, valid_pairs=integer)
        need(raw['schema'] == 'description-lexicon-paired-run/v1' and raw['completed'] is True
             and raw['dry_run'] is False, 'raw schema/completion')
        need(raw['model_id'] == prepared['model_contract']['wire_model_id']
             and raw['model_revision'] == prepared['model_contract']['model_revision'], 'raw model identity')
        items = raw['items']; need(len(items) == count, 'raw row count')
        good = bad = passes = 0
        for item, image in zip(items, images):
            shape(item, raw_name+' row', image_id=text, input_sha256=text, source_cluster=text,
                error=optional_text, describe=json_dict)
            need(item['image_id'] == image['image_id'] and item['input_sha256'] == image['sha256']
                 and item['source_cluster'] == image.get('source_cluster', image['image_id']), 'raw input identity')
            need(item['image_id'] not in seen, 'duplicate raw image'); seen.add(item['image_id'])
            need(item['error'] is None or bool(item['error']), 'row error type')
            row_passes = shape(item['describe'], raw_name+' row describe', passes=json_list)['passes']
            need(1 <= len(row_passes) <= 3, 'per-image pass budget')
            # A pass is one recorded completion exchange; null or scalar entries are not passes.
            need(all(type(entry) is dict for entry in row_passes), 'invalid pass entry')
            need(item['error'] is not None or len(row_passes) == 3, 'valid row passes')
            passes += len(row_passes)
            good += item['error'] is None; bad += item['error'] is not None
        attempts = raw['post_attempts']
        need(count <= attempts <= 3*count and raw['request_budget'] == 3*count, 'POST budget')
        need(raw['valid_pairs'] == good and cohort['item_errors'] == bad
             and cohort['raw_passes'] == passes and passes <= attempts, 'row errors/valid count')
        posts += attempts; valid += good; row_errors += bad; total_passes += passes
    need(raw_names == expected_raw, 'raw record set')
    need(not result['complete'] or total_passes == posts == 3*expected, 'complete pass count')
    need(row_errors == errors and result['raw_passes'] == total_passes and posts <= prepared['completion_POST_budget'], 'aggregate evidence')
    ev = dict(raw_records=len(cohorts), recorded_completion_POST_attempts=posts, persisted_image_rows=expected,
              contract_valid_pairs=valid, request_count_scope='Persisted raw records only; absence of raw records does not establish zero requests', human_quality_verified=False)
    collected = shape(manifest['execution_evidence'], 'execution evidence', raw_records=integer,
                    recorded_completion_POST_attempts=integer, persisted_image_rows=integer,
                    contract_valid_pairs=integer, request_count_scope=text, human_quality_verified=boolean)
    need(collected['human_quality_verified'] is False, 'human quality assertion')
    need(collected == ev, 'collector execution evidence')
    returned = shape(document('permanent/owned-window-return.json'), 'owned window return', Qwen_restored=boolean,
                   owned_client_reaped=boolean, owned_candidate_reaped=boolean)
    need(all(returned[k] is True for k in ('Qwen_restored', 'owned_client_reaped', 'owned_candidate_reaped')), 'owned return')
    closed = shape(document('permanent/completed-physical-lease-closed.json'), 'public STOP', canonical_stopped=boolean,
                 after_Qwen_restore=boolean, no_actor_or_request_active=boolean)
    need(closed['canonical_stopped'] is True and closed['after_Qwen_restore'] is True
         and closed['no_actor_or_request_active'] is True, 'public STOP')
    return result, ev, len(data)

class Transport:
    def collect(self, file, base, unit):
        program = PROGRAM.replace('BASE', repr(base)).replace('UNIT', repr(unit)).replace('WINDOW', repr(WINDOW))
        r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', HOST,
                            'sudo -n systemd-run --scope --quiet --collect --unit='+unit+' --property=CPUQuota=50% --property=MemoryMax=2147483648 /usr/bin/python3 -I -B -'],
                           input=program.encode(), stdout=file, stderr=subprocess.PIPE, timeout=180)
        need(r.returncode == 0, 'collection failed: '+r.stderr.decode(errors='replace'))
    def probe(self, base, unit):
        program = PROBE.replace('BASE', repr(base)).replace('UNIT', repr(unit)).replace('WINDOW', repr(WINDOW)).replace('STAGES', repr(STAGES))
        r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', HOST, 'sudo -n python3 -I -B -'],
                           input=program, text=True, capture_output=True, timeout=60)
        need(r.returncode == 0, 'native proof failed: '+r.stderr)
        proof = strict_json(r.stdout.encode(), 'native proof')
        validate_native_proof(proof)
        need(proof['unit'] == dict(ActiveState='inactive', ControlGroup='') and proof['GPU_stopped'] is True
             and proof['UID0_hits'] == proof['UID0_errors'] == 0, 'native inactive/procrefs/GPU proof')
        return proof

def dumped(value):
    return (json.dumps(value, indent=2)+'\n').encode()

def exclusive_json(path, value):
    # Serialize first, then no-follow exclusive create; mode is fixed through the descriptor.
    data = dumped(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush(); os.fsync(stream.fileno())

def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

class Content:
    """Publication only: the validated archive bytes, bound to one held inode.

    The SHA-256 is read through the held descriptor and accepted only if inode,
    size, mtime, ctime and link count are unchanged across that read. verify()
    requires the same inode, size, mtime and digest at every later boundary;
    strict also requires unchanged ctime/link count (no write, link or chmod).
    """
    def __init__(self, fence, collected):
        self.fence = fence
        self.stat, self.sha256 = self.measure()
        need((self.stat.st_dev, self.stat.st_ino, self.stat.st_size)
             == (collected.st_dev, collected.st_ino, collected.st_size), 'pending archive is not the collected inode')
    @staticmethod
    def quiescent(st):
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink
    def measure(self):
        self.fence.check()
        fd = self.fence.held[-1][1]
        before, digest, offset = os.fstat(fd), hashlib.sha256(), 0
        need(stat.S_ISREG(before.st_mode), 'archive is not a regular file')
        while True:
            block = os.pread(fd, 1024 * 1024, offset)
            if not block:
                break
            digest.update(block); offset += len(block)
        after = os.fstat(fd)
        need(offset == after.st_size and self.quiescent(before) == self.quiescent(after), 'archive changed while hashing')
        self.fence.check()
        return after, digest.hexdigest()
    def verify(self, strict=False):
        current, digest = self.measure()
        keys = ['st_dev', 'st_ino', 'st_size', 'st_mtime_ns'] + (['st_ctime_ns', 'st_nlink'] if strict else [])
        need(digest == self.sha256 and all(getattr(current, k) == getattr(self.stat, k) for k in keys),
             'validated archive content changed: '+str(self.fence.path))
    def publish(self, fence):
        # The published name must be the validated inode with the validated bytes.
        self.fence = fence
        self.verify()

def record(directory, name, value):
    """Exclusive fsynced sidecar created through a held directory descriptor,
    so it lands beside the retained custody even after a path fence was lost."""
    data = dumped(value)
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush(); os.fsync(stream.fileno())
    os.fsync(directory)

def withdraw(path, value):
    """Before the commit decision only: remove a success marker while it still
    holds this settlement's exact, possibly partial, bytes. Never raises."""
    expected = dumped(value)
    try:
        fence = Fence(path)
    except FileNotFoundError:
        return 'ABSENT'
    except Exception as exc:
        return 'RETAINED_UNVERIFIED: '+type(exc).__name__
    try:
        raw = fence.read()
        if raw != expected[:len(raw)]:
            return 'RETAINED_FOREIGN_BYTES'
        fence.check()
        os.unlink(path)
    except Exception as exc:
        return 'RETAINED_WITHDRAWAL_FAILED: '+type(exc).__name__
    finally:
        fence.close()
    try:
        sync_directory(path.parent)
    except Exception as exc:
        return 'WITHDRAWN_DIRECTORY_SYNC_FAILED: '+type(exc).__name__
    return 'WITHDRAWN'

def settle(name, ns, prepared_dir, transport, capacity, before_write=lambda path: None):
    """Dependency injected only for private tests; CLI always uses pinned controller.

    The collected tar is bound to its held inode and SHA-256 before validation;
    exactly those bytes must stay bound at publication, after the fresh probe,
    inside both mutexes and around every dependent write.

    One visible commit decision: atomically link the fsynced receipt into its
    exclusive final name, after durable canonical/custody writes and
    final fence, mutex, input and archive checks. Before this link, even denied
    preparation withdrawal leaves no legacy-consumable success. Afterwards directory
    fsync confirms crash durability; its failure reports COMMITTED with explicit
    durability-unconfirmed diagnostics, never an uncommitted visible success.
    Any earlier failure withdraws only this call's uncommitted preparation records,
    never rolls back canonical state, and records UNKNOWN (claim retained) or
    ARCHIVE_PUBLISHED_CLAIM_UNCERTAIN beside the retained pending custody. A
    later cleanup failure is recorded as COMMITTED_CLEANUP_INCOMPLETE and the
    committed receipt is returned, never reported UNKNOWN. A published archive
    with uncertain claim requires operator reconciliation, never a model rerun.
    """
    _, _, tag = identity(name)
    ns.bind(capacity)
    pending = None; published = False; content = None
    with contextlib.ExitStack() as stack:
        fences = []
        def hold(path):
            f = Fence(path); fences.append(f); stack.callback(f.close); return f
        # Hold canonical directories throughout collection and commit.
        hold(ns.p); out = hold(ns.out); hold(ns.shared); hold(ns.owner.parent)
        inputs = {}; bound = []
        def read(path):
            f = hold(path); raw = f.read(); inputs[f] = raw; return raw
        def check():
            for f in fences:
                f.check()
            for f, raw in inputs.items():
                need(f.read() == raw, 'input changed while settling')
            for validated in bound:
                validated.verify()
        def snapshot(path):
            f = Fence(path)
            try:
                return f.read()
            finally:
                f.close()
        prepared = json.loads(read(Path(prepared_dir)/(name+'.prepared.json')))
        need(type(prepared) is dict and type(prepared.get('configs')) is dict
             and all(re.fullmatch(r'qwen-(?:ud|gsq)-0[1-6]\.json', k) for k in prepared['configs']), 'prepared config names')
        configs = {k: read(Path(prepared_dir)/k) for k in prepared['configs']}
        prepared_contract(name, prepared, configs)
        recipe = read(ns.p/(name+'.remote.py'))
        need(sha(recipe) == prepared.get('recipe_sha256'), 'recipe identity')
        validate_recipe_binding(recipe, prepared)
        claim = json.loads(read(ns.p/(name+'.capacity-claim.json')))
        # Typed preflight before any dereference: both mutexes must already exist and
        # the claim is checked with current canonical state, re-read inside the mutexes.
        for path in ns.locks:
            Fence(path).close()
        validate_claim_states(claim, *(json.loads(snapshot(p)) for p in (ns.ledger, ns.owner, ns.lease)))
        terminal = json.loads(read(ns.p/(name+'.transport-terminal.json')))
        unit = claim['native_unit']
        need(type(unit) is str and re.fullmatch(r'workbay-[a-z0-9][a-z0-9.-]*\.scope', unit), 'native unit name')
        need(type(terminal) is dict and prepared.get('unit') == terminal.get('unit') == unit
             and type(terminal.get('exit_code')) is int and terminal['exit_code'] == 0, 'NOT_EVALUATED/UNKNOWN: transport terminal')
        rows = [json.loads(line) for line in read(ns.p/(name+'.stdout.log')).decode().splitlines()
                if line.strip().startswith('{')]
        final = [r for r in rows if r.get('status') == 'CANDIDATE_ATTEMPT_RECORDED']
        need(len(final) == 1, 'candidate terminal count')
        base = final[0].get('directory')
        need(type(base) is str and re.fullmatch(re.escape('/home/gate/bakeoff-rounds-20261017-inputs/results/'+name+'-')+r'[0-9a-f]{32}', base), 'candidate directory identity')
        need(all(r.get('directory') == base for r in rows if r.get('directory')), 'ambiguous candidate directories')
        archive = ns.out/(tag+'-final-custody.tar')
        custody = ns.out/(tag+'-final-custody.json')
        receipt_path = ns.p/(name+'.actual-capacity-return.json')
        markers = {}; replaced = []; publication_diagnostic = None
        try:
            fd, tmp = tempfile.mkstemp(prefix='.'+tag+'-pending-', suffix='.tar', dir=ns.out)
            pending = Path(tmp)
            with os.fdopen(fd, 'wb') as stream:
                transport.collect(stream, base, unit)
                stream.flush(); os.fsync(stream.fileno())
                collected = os.fstat(stream.fileno())
            # Bind the exact collected bytes (held inode and SHA-256) before validating them.
            pending_fence = hold(pending)
            content = Content(pending_fence, collected)
            result, ev, files = verify_archive(pending, name, prepared, configs, base)
            content.verify(strict=True)  # validation read the bound bytes: no write, link or chmod meanwhile
            bound.append(content)
            need(final[0].get('complete') is result['complete'], 'stdout/result completion mismatch')
            check()
            # Atomic no-overwrite publication. Validation failure never creates final custody.
            os.link(pending, archive, follow_symlinks=False)
            published = True
            sync_directory(ns.out)
            content.publish(hold(archive))
            proof = transport.probe(base, unit)  # fresh after archive publication
            validate_native_proof(proof)
            need(proof['unit'] == dict(ActiveState='inactive', ControlGroup='')
                 and proof['GPU_stopped'] is True and proof['UID0_hits'] == proof['UID0_errors'] == 0, 'native proof')
            lock_fences = []
            for path in ns.locks:
                fence = hold(path)
                fcntl.flock(fence.held[-1][1], fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_fences.append(fence)
            check()  # validated bytes still bound after the fresh probe, now inside both mutexes
            # The receipt check belongs inside BOTH existing cooperating mutexes.
            need(not os.path.lexists(receipt_path) and not os.path.lexists(custody), 'already settled')
            state_fences = {}
            def state(path):
                f = hold(path); state_fences[path] = f
                return json.loads(f.read())
            d, owner, lease = state(ns.ledger), state(ns.owner), state(ns.lease)
            validate_claim_states(claim, d, owner, lease)
            own = d['Bakeoff']
            need(d['setup_owner'] == 'Bakeoff' and set(own['profiles']) == {name}
                 and own['remaining_actor_claim'] == 1 and own['captured_at'] == claim['captured_at']
                 and own['native_unit'] == unit, 'ledger claim ownership/captured_at')
            need(lease['captured_at'] == claim['captured_at'] and set(lease['profiles']) == {name}
                 and lease['remaining_actor_claim'] == 1 and lease['native_unit'] == unit, 'lease claim ownership')
            need(owner['captured_at'] == claim['captured_at'] and owner['remaining_actor_claim'] == 1
                 and set(owner['exact_self_reserved_profiles']) == {name}, 'owner claim ownership')
            receipt = dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), archive=str(archive),
                           archive_sha256=content.sha256, verified_files=files, native=proof,
                           remaining_actor_claim=0, returned_CPU=.5, returned_RAM_bytes=2147483648,
                           returned_unused_forward_bytes=1073741824, source_files_retained_in_df=True,
                           pilot_inputs_retained=True, execution_evidence=ev, claim_captured_at=claim['captured_at'],
                           recipe_sha256=sha(recipe), candidate_complete=result['complete'], item_errors=result['item_errors'],
                           human_quality_verified=False, status='VALIDATED_COMPLETED_ATTEMPT_SETTLED')
            own.update(reserved_now=False, profiles={}, aggregate_cpu_cores_max=0, aggregate_memory_bytes_max=0,
                       forward_disk_bytes=0, actual_models=0, remaining_actor_claim=0, setup_granted=False,
                       native_unit=None, actual_handles=[], guest_GPU_setup_retained=False, settlement=receipt)
            d['setup_owner'] = None
            d['pending_reservations'] = [x for x in d['pending_reservations'] if x['owner'] != 'Bake-'+name]
            d['updated_at'] = receipt['at']
            owner.update(captured_at=receipt['at'], remaining_forward_disk_bytes=0, exact_self_reserved_profiles={},
                         reserved_now=False, setup_in_progress=False, remaining_actor_claim=0,
                         actual_own_model_processes=0, active_own_handles_nonces=[], settlement=receipt)
            def write(path, value, exclusive=False):
                before_write(path)
                check()  # both actual mutex inodes, inputs and validated archive bytes, immediately before EACH write
                if exclusive:
                    markers[path] = value  # withdrawable until the commit decision
                    exclusive_json(path, value)
                    check()  # a success marker stands only while everything it attests is still bound
                else:
                    # Unique private scratch, atomic replacement; never helper's shared .tmp.
                    scratch = path.with_name('.'+path.name+'.settle-'+uuid.uuid4().hex)
                    exclusive_json(scratch, value)
                    check()
                    os.replace(scratch, path)
                    replaced.append(str(path))
                    previous = state_fences[path]
                    fences.remove(previous)
                    state_fences[path] = hold(path)
                sync_directory(path.parent)
            # The legacy consumer cannot interpret this preparation record as success.
            # It reserves the name exclusively, including across failed withdrawal.
            preparing = dict(status='SETTLEMENT_PREPARING', operation=name,
                             nonce=uuid.uuid4().hex, automatic_retry=False)
            write(ns.lease, own); write(ns.owner, owner); write(ns.ledger, d)
            write(custody, receipt, True)
            write(receipt_path, preparing, True)
            preparation = hold(receipt_path)
            custody_fence = hold(custody)
            # Build success off the consumable path. A failed file fsync here also
            # leaves only the rejected preparation record, regardless of unlink.
            ready_path = receipt_path.with_name('.'+receipt_path.name+'.commit-'+uuid.uuid4().hex)
            exclusive_json(ready_path, receipt)
            ready = hold(ready_path)
            # The published archive now owns the validated bytes. Loss/replacement
            # of its redundant pending name is a cleanup fault, not a lost input.
            fences.remove(pending_fence)
            def commit_check():
                check()
                need(ready.read() == dumped(receipt), 'commit receipt bytes changed')
                need(custody_fence.read() == dumped(receipt), 'custody record changed')
                for path, value in ((ns.lease, own), (ns.owner, owner), (ns.ledger, d)):
                    need(state_fences[path].read() == dumped(value), 'canonical settlement bytes changed')
            commit_check()
            need(preparation.read() == dumped(preparing), 'preparation record changed')
            # Both canonical mutexes remain held. Remove only our checked,
            # non-consumable reservation; denied unlink cannot expose success.
            os.unlink(receipt_path)
            fences.remove(preparation)
            commit_check()
            # A racing foreign name is never overwritten. This no-overwrite
            # link is the sole point at which legacy success becomes visible.
            try:
                os.link(ready_path, receipt_path, follow_symlinks=False)
            except BaseException as exc:
                # A reported publication error is not proof that visibility did
                # not change. Recognize only our exact fsynced inode and bytes;
                # a missing/foreign/partial marker still takes the failure path.
                visible = None
                try:
                    visible = Fence(receipt_path)
                    a, b = os.fstat(visible.held[-1][1]), os.fstat(ready.held[-1][1])
                    committed = (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) and visible.read() == dumped(receipt)
                except Exception:
                    committed = False
                finally:
                    if visible is not None:
                        visible.close()
                if not committed:
                    raise
                publication_diagnostic = dict(stage='receipt-link-reported-error', exception_type=type(exc).__name__, detail=str(exc))
        except BaseException as exc:
            if pending is not None:
                # Private evidence stays in place even when transport wrote a partial tar.
                # No canonical claim rewrite or rollback on failure, especially after a lost fence.
                withdrawn = {str(path): withdraw(path, value) for path, value in reversed(markers.items())}
                status = dict(status='ARCHIVE_PUBLISHED_CLAIM_UNCERTAIN' if published else 'NOT_EVALUATED_UNKNOWN',
                              operation=name, archive=str(archive) if published else None,
                              pending=str(pending), exception_type=type(exc).__name__, detail=str(exc),
                              claim_retained_or_uncertain=True, automatic_retry=False, commit_decision='NOT_COMMITTED',
                              bound_archive_sha256=content and content.sha256, validated=bool(bound),
                              canonical_state_replaced=replaced, success_markers=withdrawn,
                              receipt_present=os.path.lexists(receipt_path),
                              recovery='Reconcile existing artifact and canonical state explicitly; do not rerun model')
                try:
                    record(out.held[-1][1], pending.with_suffix('.status.json').name, status)
                except Exception:
                    pass
            raise
        # Committed visibility is irreversible here. Directory persistence is a
        # separate fact: never pretend a failed fsync proved crash durability.
        diagnostics = [publication_diagnostic] if publication_diagnostic else []
        receipt_directory_durable = False
        try:
            sync_directory(receipt_path.parent)
            receipt_directory_durable = True
        except Exception as exc:
            diagnostics.append(dict(stage='receipt-directory-fsync', exception_type=type(exc).__name__, detail=str(exc)))
        try:
            ready.check()
            os.unlink(ready_path)
            sync_directory(receipt_path.parent)
            receipt_directory_durable = True
            pending_fence.check()
            os.unlink(pending)
            sync_directory(ns.out)
        except Exception as exc:
            diagnostics.append(dict(stage='pending-cleanup', exception_type=type(exc).__name__, detail=str(exc)))
        if diagnostics:
            outcome_status = ('COMMITTED_DURABILITY_UNCONFIRMED' if not receipt_directory_durable else
                              'COMMITTED_CLEANUP_INCOMPLETE' if any(d['stage'] == 'pending-cleanup' for d in diagnostics) else
                              'COMMITTED_WITH_DIAGNOSTICS')
            status = dict(status=outcome_status,
                          operation=name, archive=str(archive), archive_sha256=content.sha256,
                          receipt=str(receipt_path), pending=str(pending), commit_decision='COMMITTED',
                          commit_point='EXCLUSIVE_RECEIPT_LINK', receipt_directory_durable=receipt_directory_durable,
                          receipt_file_durable=True, canonical_state_durable=True, diagnostics=diagnostics,
                          exception_type=diagnostics[0]['exception_type'], detail=diagnostics[0]['detail'],
                          claim_retained_or_uncertain=False, automatic_retry=False,
                          recovery='Settlement is visibly committed; do not rerun model. '
                                   'Reconcile directory durability explicitly if unconfirmed; pending is redundant custody')
            try:
                record(out.held[-1][1], pending.with_suffix('.status.json').name, status)
            except Exception as exc:
                status['diagnostic_record_error'] = dict(exception_type=type(exc).__name__, detail=str(exc))
            # Actual CLI callers still receive diagnostics if sidecar persistence
            # also fails. The returned receipt stays identical to stored bytes.
            import sys
            print(json.dumps(status), file=sys.stderr)
        return receipt

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--operational-repo', type=Path, required=True)
    parser.add_argument('--prepared-dir', type=Path, required=True)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--capacity-sha256', required=True)
    args = parser.parse_args(argv)
    identity(args.name)
    need(args.capacity_sha256 == CAPACITY_SHA256, 'CLI requires the supplied real capacity module pin')
    ns = Namespace(args.operational_repo)
    capacity = load_capacity(args.module_root, args.capacity_sha256, ns)
    receipt = settle(args.name, ns, args.prepared_dir, Transport(), capacity)
    print(json.dumps(receipt))


# Collect the window into private remote scratch; frozen process predicates above
# remain byte-for-byte. Never create a snapshot inside the completed result tree.
PROGRAM = PROGRAM.replace("window=pathlib.Path(WINDOW);assert not(base/'post-recovery-window-snapshot').exists();shutil.copytree(window,base/'post-recovery-window-snapshot',symlinks=True)",
    "import tempfile\nwindow=pathlib.Path(WINDOW);scratch=tempfile.TemporaryDirectory(prefix='qwen-custody-');snapshot=pathlib.Path(scratch.name)/'post-recovery-window-snapshot';shutil.copytree(window,snapshot,symlinks=True)")
PROGRAM = PROGRAM.replace("with tarfile.open(fileobj=sys.stdout.buffer,mode='w|')as t:",
    "sources={name:base/name for name in files}\nfor p in sorted(snapshot.rglob('*')):\n assert not p.is_symlink(),p\n if p.is_file():\n  name=str(p.relative_to(snapshot.parent));sources[name]=p;files[name]=dict(bytes=p.stat().st_size,sha256=hashlib.file_digest(p.open('rb'),'sha256').hexdigest())\nwith tarfile.open(fileobj=sys.stdout.buffer,mode='w|')as t:")
PROGRAM = PROGRAM.replace("p=base/name;assert", "p=sources[name];assert")

if __name__ == '__main__':
    main()
