"""Prepare prospective Qwen paired A/B recipes; never execute generated code.

Example: python3 prepare_qwen_ab.py --references ../references --candidate gsq
 --mode pilot --name QWEN-PILOT-R1 --unit workbay-qwen-pilot.scope --out /tmp/qwen-prepared

Replacement-038 (one image, gsq only): --mode replacement --revision <corpus-revision-r2.json>.

The predecessor AUTO is late-bound at claim time by refresh (stop, withdraw,
reconcile), not pinned at preparation. Coordinator must verify
late-bound-predecessor.json after the run.
Coordinator execution requires independent Sol XHIGH review. Full cohorts also
require an actual paired pilot and predecessor settlement, checked by operator.
"""
import argparse
import ast
import base64
import hashlib
import json
import posixpath
from pathlib import Path
import re

PINS = {
 'LEXICON-MIMO-40-LAST40-R1.remote.py': 'd5e180d72fbbf2d53418ced03f7ba30be1f1bb488db1c2cdd10b1c727467c921',
 'QWEN38-GSQ-ALL38-LONG-R20C.execution.remote.py': 'cd9540c3c0ae8e02337880d850ed744bcd140d03ea98e29f479782ce4cf4e583',
 'QWEN38-27B-ALL38-LONG-R21.execution.remote.py': '53661a3cdc666bef36d9cddd122f1e9a0e77dfdd8b9614eb0df8b1f04e436542',
 'paired_client.py': '1206b7e94f05910efa7ffb838feeb3e21bb99a3979201440f4043c690b858555',
 'batch-plan.json': '10dbdd551c41b998521dc9716e808320951c128c38a665f2dc4c899acdd2dd06',
 'qwen-remote-preparation.json': '54cb6533129d6eeb454f43e48be95f080cc6456d770326690eaeab22a329d5cd',
}
SOURCES = {'gsq': 'QWEN38-GSQ-ALL38-LONG-R20C.execution.remote.py',
           'ud': 'QWEN38-27B-ALL38-LONG-R21.execution.remote.py'}
# Owner-custody stage rebind (RLSE-21, FLOW-01). The immutable references keep the
# pre-fix stage; only the prepared recipe moves to the restaged, reviewed procedure.
OLD_OWNER_STAGE = '/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure'
OWNER_STAGE = '/root/bakeoff-owner-long-window-20261020-cd399f1f0d55/procedure'
OLD_OWNER_WINDOW_SHA256 = '033d187835c9243bd486b185167563c16ef24812eb26f174ea062fc46fe798e9'
OWNER_WINDOW_SHA256 = '60c0cfdceedbf778be717300d7d0d5c071a07860be333abcd694e4e0c430281b'
OLD_OWNER_MANIFEST_SHA256 = '45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca'
OWNER_MANIFEST_SHA256 = 'cd399f1f0d55fd1dbf4eb980d0accbdb6b2ac27536f4f11a222b3262bdcbb495'
OWNER_STAGE_SOURCE_COMMIT = '27bf69d5349c44033f419ec4fa73e893b4dd6b2d'
# Replacement-038 (decision 18687, RLSE-21): corpus revision R2 replaces original-038 only. The record is
# pinned by digest; the frozen qwen-gsq-02.json still carries the R1 bytes and is never edited.
R1_IMAGES_DIR = '/home/gate/bakeoff-rounds-20261017-inputs/results/LEXICON-AB-FROZEN-120-R1/images'
R2_ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/results/LEXICON-AB-FROZEN-120-R2'
R2_REVISION_SHA256 = '66a2efb3c2bdeea52baa28ec8570336a20aed21e3c32f646ab9d7a7911f8b240'
R2_IMAGE_SHA256 = '710a6798653ef868338136da63e2c176e892d73bac342e395bf0df640e70022e'
REPLACED_IMAGE_ID = 'original-038'
REPLACEMENT_SOURCE = 'qwen-gsq-02.json'
REVISION_SCHEMA = 'bakeoff-corpus-revision/v1'
SELECTION = {'pilot': 'first-two', 'full': 'whole-cohort', 'replacement': 'r2-replacement-original-038', 'missing': 'canonical-pending-only'}
# Claim-time predecessor binding (decision 18673): the recipe refreshes the
# owned window's AUTO before START, so the fresh publication is the fencing
# token. Replaces the pinned template line `assert previous=='aa048fdb...'`.
LATE_BIND_BLOCK = """\
    safe_withdraw=False
    assert previous!='none' and str(uuid.UUID(previous))==previous,'Owned window operation unknown; retain state and reconcile explicitly'
    def late_sealed(name):
        p=window/'ops'/previous/name;s=p.lstat()
        assert stat.S_ISREG(s.st_mode)and not stat.S_IMODE(s.st_mode)&0o222 and s.st_uid==0,'Unsealed or foreign predecessor evidence'
        return json.loads(p.read_bytes())
    def late_settled(what):
        gpu=json.loads(Path('/run/acx/gpu-state.json').read_bytes());assert gpu['state']=='stopped' and gpu.get('lease_expires_at')is None,what
    late_result=late_sealed('result.json');late_publication=late_sealed('publication.json')
    assert late_result.get('operation')==previous and late_result.get('window')==wid and late_result.get('outcome')=='published','Predecessor linkage changed; retain exact window'
    late_action=late_publication.get('action')
    if late_action not in('auto','stop'):raise RuntimeError('Predecessor is not a settled AUTO/STOP publication; retain exact window')
    late_from=previous;refresh_stop=None
    if late_action=='stop':late_settled('STOP predecessor not settled; retain exact window')
    safe_withdraw=True
    if late_action=='auto':
        refresh_stop=public(['stop',str(window),previous],'refresh-stop',75);observe(refresh_stop,'stop','refresh-stop-observe',195)
        late_settled('Refresh STOP did not settle')
    previous=public(['withdraw',str(window),wid],'refresh-auto',75)
    assert previous!='none' and str(uuid.UUID(previous))==previous and previous not in(late_from,refresh_stop),'Fresh AUTO not published; retain exact window'
    save('late-bound-predecessor.json',dict(reconciled=late_from,reconciled_action=late_action,refresh_stop=refresh_stop,fresh_auto=previous,binding='late_bound_at_claim_refresh',at=time.time()))
    observe(previous,'auto','actual-previous-auto-observe',190)
    assert public(['reconcile',str(window),wid],'actual-previous-auto-reconcile',45)==previous,'Actual predecessor changed'
"""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def pinned(root, name):
    path = root / name
    require(path.is_file() and not path.is_symlink(), 'not a regular source: ' + name)
    raw = path.read_bytes()
    require(sha(raw) == PINS[name], 'source hash mismatch: ' + name)
    return raw


def assignment(source, name):
    nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    require(len(nodes) == 1, 'ambiguous producer: ' + name)
    return nodes[0]


def producer(source):
    """Read literal spec and setup template without evaluating source code."""
    spec = ast.literal_eval(assignment(source, 'spec').value)
    value = assignment(source, 'setup_program').value
    require(isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
            and value.func.attr == 'replace', 'unexpected setup producer')
    template = ast.literal_eval(value.func.value)
    return spec, template


def function_bytes(source, name):
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node)


def replace_once(source, old, new):
    require(source.count(old) == 1, 'transformation drift: ' + old[:70])
    return source.replace(old, new, 1)


def rebind_owner_stage(recipe):
    """Exactly three substitutions; each target must occur once in the recipe."""
    recipe = replace_once(recipe, OLD_OWNER_STAGE, OWNER_STAGE)
    recipe = replace_once(recipe, OLD_OWNER_WINDOW_SHA256, OWNER_WINDOW_SHA256)
    return replace_once(recipe, OLD_OWNER_MANIFEST_SHA256, OWNER_MANIFEST_SHA256)


def validate_configs(root, plan, candidate):
    model = plan['models']['qwen-' + candidate]
    rows = [r for r in plan['batches'] if r['model'] == 'qwen-' + candidate]
    configs = []
    seen = set()
    for row in rows:
        path = root / row['config']
        require(not path.is_symlink(), 'config symlink')
        raw = path.read_bytes()
        require(sha(raw) == row['config_sha256'], 'config hash mismatch')
        cfg = json.loads(raw)
        require(all(cfg[k] == model[k] for k in ('model_version', 'model_revision')),
                'wrong model contract')
        require(len(cfg['images']) == row['images'] and row['images'] <= 20,
                'wrong cohort count')
        for image in cfg['images']:
            require(image['image_id'] not in seen, 'duplicate image ID')
            seen.add(image['image_id'])
            require(not image.get('context_pack') and not image.get('present_identities'),
                    'identity context must be empty')
        configs.append((Path(row['config']).name, raw))
    require(len(seen) == (120 if candidate == 'gsq' else 30), 'frozen cohort changed')
    return model, configs


def read_regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'not a regular file: ' + str(path))
    return path.read_bytes()


def replacement_path(revision_raw, previous):
    """Check the R2 revision record against the frozen original-038 entry; return its VM image path."""
    require(sha(revision_raw) == R2_REVISION_SHA256, 'revision record is not the pinned R2 record')
    rev = json.loads(revision_raw)
    require(isinstance(rev, dict) and rev.get('schema') == REVISION_SCHEMA and rev.get('revision') == 'r2',
            'revision must be bakeoff-corpus-revision/v1 r2')
    require(rev.get('image_id') == REPLACED_IMAGE_ID, 'wrong image id')
    require('replacements' not in rev, 'two replacements requested; the revision names one original-038 replacement')
    old, new = rev.get('previous'), rev.get('replacement')
    require(isinstance(old, dict) and isinstance(new, dict), 'revision needs previous and replacement records')
    require(old.get('image_id') == new.get('image_id') == REPLACED_IMAGE_ID, 'wrong image id')
    require(new.get('dataset_revision') == 'r2', 'replacement is not dataset revision r2')
    require(old.get('sha256') == new.get('replaces_sha256') == previous['sha256'],
            'wrong old sha256: revision does not replace the frozen original-038 bytes')
    require(new.get('sha256') == R2_IMAGE_SHA256, 'wrong new sha256: not the sealed R2 original-038 bytes')
    require(new.get('context_pack') == {} and new.get('present_identities') == [], 'identity context must be empty')
    require(rev.get('old_outputs_reused_for_replacement') is False, 'old outputs must not be reused for the replacement')
    models = rev.get('required_GPU_models')
    require(isinstance(models, list) and 'qwen-gsq' in models, 'qwen-gsq must be a required GPU model')
    rel = new.get('path')
    require(isinstance(rel, str), 'replacement path is missing')
    image = posixpath.join(R2_ROOT, rel)
    require(image == posixpath.normpath(image) and image.startswith(R2_ROOT + '/'), 'replacement path outside the R2 dir')
    return image


# PROV-01 / AGT-08: these are current report inputs, separate from frozen config ancestry.
MISSING_INPUTS = Path(__file__).resolve().parent / 'missing-inputs'
MISSING_INVENTORY_SHA256 = '17f5c9906badaaa3142fdc749f8603f33d8b8fb89e1552762360bb901bc781ae'
PROTOCOL_SHA256 = '9e33cf5284c2eef1947015d61efa31eae7a70d0b00901a68bef9ea6ad1764250'
CORPUS_SHA256 = '05fe1b169be22c6a8e25d97769ef9aeb143dea1a5ffa7d0b09a48b25cc444a63'
MISSING_NAMES = {'gsq': 'LEXICON-QWEN-GSQ-MISSING-C064-R1',
                 'ud': 'LEXICON-QWEN-UD-MISSING-04-R1'}


def missing_selection(configs, candidate, inventory, protocol_sha256, corpus_sha256):
    """Select only the pinned pending model rows, in original config/image order."""
    raw = read_regular(inventory)
    require(sha(raw) == MISSING_INVENTORY_SHA256, 'not the canonical missing inventory')
    require(protocol_sha256 == PROTOCOL_SHA256 and corpus_sha256 == CORPUS_SHA256,
            'current protocol/corpus digest required')
    protocol_raw = read_regular(MISSING_INPUTS / 'protocol.json')
    corpus_raw = read_regular(MISSING_INPUTS / 'corpus-active-120-r2.json')
    require(sha(protocol_raw) == protocol_sha256 and sha(corpus_raw) == corpus_sha256,
            'current protocol/corpus bytes drifted')
    doc = json.loads(raw)
    require(doc['official_protocol_sha256'] == protocol_sha256
            and doc['active_manifest_sha256'] == corpus_sha256, 'inventory report binding drift')
    row = next(r for r in doc['model_rows'] if r['model_key'] == 'qwen-' + candidate)
    ids = row['missing_ids']
    require(len(ids) == len(set(ids)) and len(ids) == (1 if candidate == 'gsq' else 4),
            'duplicate or wrong pending count')
    records = {r['image_id']: r for r in row['input_records']}
    corpus = {r['image_id']: r for r in json.loads(corpus_raw)['images']}
    require(set(records) == set(ids) and all(records[i] == corpus.get(i) for i in ids),
            'pending record outside current corpus or image hash drift')
    selected = []; seen = []
    for filename, frozen in configs:
        cfg = json.loads(frozen)
        images = [im for im in cfg['images'] if im['image_id'] in ids]
        if not images:
            continue
        for im in images:
            ident = im['image_id']
            require(im['sha256'] == records[ident]['sha256']
                    and im['path'] == R1_IMAGES_DIR + '/' + ident + '.jpg',
                    'pending frozen image path/hash drift')
            seen.append(ident)
        cfg['images'] = images
        selected.append((filename, (json.dumps(cfg, indent=2) + '\n').encode()))
    require(seen == ids, 'pending IDs not in immutable candidate/order')
    binding = dict(inventory_sha256=sha(raw), official_protocol_sha256=protocol_sha256,
                   active_manifest_sha256=corpus_sha256, selected_ids=seen,
                   prespecified_target=row['prespecified_target'], evaluated_before=row['evaluated_before'],
                   planned_max_completion_POSTs=3*len(seen), execution_status='PROSPECTIVE_NOT_EXECUTED',
                   prior_failed_attempts_retained=True, existing_model_output_errors_are_not_retry_targets=True)
    return selected, binding


def prepare(root, candidate, mode, name, unit, cohorts=None, client_seconds=None, revision=None,
            missing_inventory=None, protocol_sha256=None, corpus_sha256=None):
    require(candidate in SOURCES and mode in SELECTION, 'candidate/mode required')
    require((revision is not None) == (mode == 'replacement'), 'revision is required in replacement mode only')
    require((missing_inventory is not None and protocol_sha256 is not None and corpus_sha256 is not None)
            if mode == 'missing' else all(v is None for v in (missing_inventory, protocol_sha256, corpus_sha256)),
            'missing inventory and current digests are required in missing mode only')
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,90}', name or '')), 'explicit safe name required')
    require(bool(re.fullmatch(r'workbay-[A-Za-z0-9_-]+\.scope', unit or '')), 'explicit scope unit required')
    root = Path(root)
    inputs = {key: pinned(root, key) for key in PINS}
    source = inputs['LEXICON-MIMO-40-LAST40-R1.remote.py'].decode()
    prior = inputs[SOURCES[candidate]].decode()
    plan = json.loads(inputs['batch-plan.json'])
    model, configs = validate_configs(root, plan, candidate)
    revision_raw = replacement = missing = None
    if mode == 'missing':
        require(not cohorts and name == MISSING_NAMES[candidate] and unit.startswith('workbay-bakeoff-'),
                'missing mode requires exact operation name, bakeoff unit and no cohort selection')
        selected, missing = missing_selection(configs, candidate, missing_inventory, protocol_sha256, corpus_sha256)
    elif mode == 'pilot':
        require(not cohorts, 'pilot uses first immutable config only')
        cfg = json.loads(configs[0][1]); cfg['images'] = cfg['images'][:2]
        selected = [(configs[0][0], (json.dumps(cfg, indent=2) + '\n').encode())]
    elif mode == 'replacement':
        require(candidate == 'gsq' and not cohorts, 'replacement is gsq only and takes the revision, not cohorts')
        revision_raw = read_regular(revision)
        frozen = dict(configs)[REPLACEMENT_SOURCE]
        matches = [im for im in json.loads(frozen)['images'] if im['image_id'] == REPLACED_IMAGE_ID]
        require(len(matches) == 1, 'frozen qwen-gsq-02 must hold exactly one original-038 entry')
        image = replacement_path(revision_raw, matches[0])
        cfg = json.loads(frozen); cfg['images'] = [dict(matches[0], path=image, sha256=R2_IMAGE_SHA256)]
        selected = [(REPLACEMENT_SOURCE, (json.dumps(cfg, indent=2) + '\n').encode())]
        replacement = dict(image_id=REPLACED_IMAGE_ID, old_sha256=matches[0]['sha256'], new_sha256=R2_IMAGE_SHA256,
                           path=image, revision_sha256=sha(revision_raw))
    else:
        require(bool(cohorts) and len(set(cohorts)) == len(cohorts), 'explicit unique full cohorts required')
        available = dict(configs)
        require(all(c in available for c in cohorts), 'unknown candidate config')
        require(cohorts == [c for c, _ in configs if c in cohorts], 'preserve frozen cohort order')
        selected = [(c, available[c]) for c in cohorts]
    count = sum(len(json.loads(raw)['images']) for _, raw in selected)
    require(mode != 'replacement' or count == 1, 'replacement is exactly one image')
    short_run = mode in ('pilot', 'replacement', 'missing')
    client = client_seconds if client_seconds is not None else (420 if short_run else 650)
    # Fixed phase reservations, not a promise every request will finish. The
    # native client deadline preserves incomplete/invalid attempts without retry.
    START_RESERVE = 300  # lease counts from START publication; START->ready took 145-195 s on owner-window ops
    floors = dict(identity=60, setup=300, metadata=30, client=client, restore=270, control=80)
    require(isinstance(client, int) and 3 * 5 * count <= client <= (420 if short_run else 1000),
            'cohort impossible under client floor/cap (15 seconds per image)')
    require(START_RESERVE + sum(floors.values()) <= 1800, 'phase floors plus START reserve exceed fixed lease 1800')
    require(150 + 30 + client + 270 <= 1500, 'phase floors exceed native1500')
    spec, template = producer(prior)
    prep = json.loads(inputs['qwen-remote-preparation.json'])['candidates']['qwen-' + candidate]
    require(sha(template.encode()) == prep['setup_sha256'], 'qualified setup hash mismatch')
    require(all(spec[k] == v for k, v in prep['asset_spec'].items()), 'qualified spec mismatch')
    revision_pin = {} if revision_raw is None else dict(revision_sha256=sha(revision_raw))
    encoded = {c: dict(b64=base64.b64encode(raw).decode(), sha256=sha(raw),
                       immutable_source_sha256=sha(dict(configs)[c]),
                       selection=SELECTION[mode], **revision_pin)
               for c, raw in selected}
    # Replace only AST-identified producer statements, preserving effect helpers.
    edits = []
    for key, value in [('configs', repr(encoded)), ('spec', repr(spec))]:
        n = assignment(source, key)
        edits.append((n.lineno, n.end_lineno, '    ' + key + '=' + value + '\n'))
    n = assignment(source, 'setup_program')
    edits.append((n.lineno, n.end_lineno, "    setup_program=" + repr(template) + ".replace('v=CONFIG','v='+repr(spec))\n"))
    lines = source.splitlines(keepends=True)
    for start, end, text in sorted(edits, reverse=True):
        lines[start - 1:end] = [text]
    recipe = ''.join(lines)
    recipe = rebind_owner_stage(recipe)
    recipe = replace_once(recipe, "N='LEXICON-MIMO-40-LAST40-R1'", 'N=' + repr(name))
    recipe = replace_once(recipe, "N=" + repr(name), "assert " + repr(unit) + " in cg.parts, 'Declared root scope mismatch'\nN=" + repr(name))
    recipe = replace_once(recipe, "    assert previous=='aa048fdb-01cc-405d-9e2c-5af0063093fb','Continuation ownership changed; retain state and reconcile explicitly'\n", LATE_BIND_BLOCK)
    # Refusals before LATE_BIND_BLOCK must not reach the finally holding a predecessor it never owned (RES-10).
    recipe = replace_once(recipe, "owned_start=None;safe_withdraw=True;key_bytes=None;maintenance_attempted=False;child=None;maintenance_root=None",
                          "owned_start=None;safe_withdraw=False;key_bytes=None;maintenance_attempted=False;child=None;maintenance_root=None")
    # RLSE-31/STOR-13: a reaped lane sandbox is not a durable input; bind the durable source root instead.
    recipe = replace_once(recipe, "repo=Path('/home/gate/workbay-sandbox')/KEY", "repo=Path('/home/gate/bakeoff-rounds-20261017-inputs/source')/SOURCE")
    recipe = replace_once(recipe, "python=repo.parent/('.venv-lane-'+KEY)/'bin/python'", "python=repo.parent/(SOURCE+'.venv')/'bin/python'")
    # Shared captured controls are checked separately from actual model input.
    recipe = replace_once(recipe, "batch_cfg=json.loads(raw);assert len(batch_cfg['images'])==20",
                          "batch_cfg=json.loads(raw);assert 0<len(batch_cfg['images'])<=20")
    recipe = replace_once(recipe, "assert batch_cfg['model_revision']==cfg['model_revision']and batch_cfg['model_version']==cfg['model_version']",
                          "assert batch_cfg['model_revision']==" + repr(model['model_revision']) + " and batch_cfg['model_version']==" + repr(model['model_version']))
    recipe = replace_once(recipe, "count=20)", "count=len(batch_cfg['images']),sha256=pin['sha256'],immutable_source_sha256=pin['immutable_source_sha256'],selection=pin['selection'])")
    recipe = replace_once(recipe, 'assert len(seen)==40', 'assert len(seen)==' + str(count))
    recipe = replace_once(recipe, "    data=dict(images_dir=", "    manifest=Path(cohorts[0]['manifest']);cfg=json.loads(manifest.read_bytes())\n    data=dict(images_dir=")
    recipe = recipe.replace("input_manifest_sha256='ba81e101f1ee9f17e0dc426844785072fdbee15cfa6423b0b4f677cb0d9e70e4',loader_sha256=cfg", "input_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),loader_sha256=cfg")
    recipe = replace_once(recipe, "manifest=str(manifest),input_manifest_sha256=", "manifest=str(manifest),candidate_configs=cohorts,model_version=cfg['model_version'],model_revision=cfg['model_revision'],input_manifest_sha256=")
    recipe = recipe.replace('request_budget=120', 'request_budget=' + str(3 * count)).replace('total_HTTP_budget=123', 'total_HTTP_budget=' + str(3 * count + 3))
    recipe = recipe.replace('total_distinct_images=40', 'total_distinct_images=' + str(count))
    recipe = recipe.replace('pilot_only=False', 'pilot_only=' + repr(mode == 'pilot'))
    # Copy the actual qualified outer setup command, including resource limits.
    prior_lines = prior.splitlines()
    command_line = next(x for x in prior_lines if "command='sudo -n systemd-run --scope" in x)
    old_line = next(x for x in recipe.splitlines() if "command='sudo -n systemd-run --scope" in x)
    recipe = replace_once(recipe, old_line, command_line)
    recipe = replace_once(recipe, 'serving=json.loads(guest(command,125))', 'serving=json.loads(guest(command,570))')
    recipe = recipe.replace('>=1600,', '>=' + str(sum(floors.values())) + ',')
    recipe = recipe.replace('>=1420,', '>=' + str(floors['setup'] + floors['metadata'] + client + floors['restore']) + ',')
    recipe = recipe.replace('>=1270,', '>=' + str(30 + client + 270) + ',')
    recipe = replace_once(recipe, 'min(1000,int(expires-time.time()-270));assert deadline-time.monotonic()>=990',
                          'min(' + str(client) + ',int(expires-time.time()-270));assert deadline-time.monotonic()>=' + str(client - 1))
    mimo_weight = 'MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf'
    mimo_proj = 'mmproj-MiMo-V2.6-Distill-Qwen-9B-f16.gguf'
    weight = model['wire_model_id'].split('/')[-1]
    projector = next(k for k in spec['components'] if k != weight)
    recipe = recipe.replace(mimo_weight, weight).replace(mimo_proj, projector)
    recipe = recipe.replace("model_version='mimo-v2.6-distill-qwen-9b-gguf-Q4_K_M'", 'model_version=' + repr(model['model_version']))
    recipe = recipe.replace('len(all_items)==40', 'len(all_items)==' + str(count)).replace('len(all_passes)==120', 'len(all_passes)==' + str(3 * count)).replace('requested_images=40', 'requested_images=' + str(count))
    recipe = recipe.replace('BATCH40_', 'COHORT_').replace('fixed40-image', 'fixed-cohort').replace('bounded40-image', 'bounded-cohort').replace('bounded1000-second', 'bounded-client').replace('for40-image', 'for-cohort')
    client_raw = inputs['paired_client.py']
    materialize = "    client_raw=base64.b64decode(" + repr(base64.b64encode(client_raw).decode()) + ",validate=True)\n"
    materialize += "    assert hashlib.sha256(client_raw).hexdigest()==" + repr(PINS['paired_client.py']) + "\n"
    materialize += "    paired_client=batch_input/'paired_client.py'\n    with paired_client.open('xb')as f:f.write(client_raw);f.flush();os.fsync(f.fileno())\n    paired_client.chmod(0o440);os.chown(paired_client,0,1002)\n"
    recipe = replace_once(recipe, '    cohorts=[];seen=set()', materialize + '    cohorts=[];seen=set()')
    recipe = replace_once(recipe, "str(pilot_input/'paired_client.py')", 'str(paired_client)')
    if replacement is not None:
        # The replacement is the only image: its parent dir is the R2 revision dir, which the recipe reads as images_dir.
        revision_dir = posixpath.dirname(replacement['path'])
        recipe = replace_once(recipe, "path_image.parent==Path('" + R1_IMAGES_DIR + "')", "path_image.parent==Path('" + revision_dir + "')")
        recipe = replace_once(recipe, "data=dict(images_dir='" + R1_IMAGES_DIR + "')", "data=dict(images_dir='" + revision_dir + "')")
    # This guard is deliberately unresolved until independent review. The CLI
    # cannot certify review or a live pilot by generating a recipe.
    guard = "assert os.environ.get('QWEN_AB_SOL_XHIGH_GATE')==" + repr(sha(recipe.encode())) + ", 'Independent Sol XHIGH gate required; coordinator execution only'\n"
    if mode in ('full', 'replacement', 'missing'):
        guard += "assert os.environ.get('QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256') and re.fullmatch(r'[0-9a-f]{64}',os.environ['QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256']), 'Actual pilot receipt required before full; coordinator must verify contents'\n"
    recipe = replace_once(recipe, "assert os.geteuid()==os.getuid()==0", guard + "assert os.geteuid()==os.getuid()==0")
    for func in ('public', 'observe', 'guest'):
        require(function_bytes(source, func) == function_bytes(recipe, func), 'effect helper changed')
    compile(recipe, '<prospective-recipe>', 'exec')
    receipt = dict(status='PROSPECTIVE_NOT_EXECUTED_NOT_QUALIFIED', name=name, unit=unit,
                   candidate=candidate, mode=mode, predecessor_binding='late_bound_at_claim_refresh',
                   owner_stage=dict(path=OWNER_STAGE, manifest_sha256=OWNER_MANIFEST_SHA256,
                                    owner_window_sha256=OWNER_WINDOW_SHA256,
                                    source_commit=OWNER_STAGE_SOURCE_COMMIT),
                   model_contract=model, asset_spec_sha256=sha(json.dumps(spec, sort_keys=True).encode()),
                   preparer_sha256=sha(Path(__file__).read_bytes()),
                   recipe_sha256=sha(recipe.encode()), sources=PINS, configs={c: sha(r) for c, r in selected},
                   immutable_candidate_configs={c: sha(r) for c, r in configs},
                   total_distinct_images=count, completion_POST_budget=3 * count,
                   per_image_POST_cap=3, whole_client_seconds=client,
                   candidate_runtime_seconds=1500, intent_seconds=1800,
                   resource_contracts=dict(
                       host_root=dict(scope='host', phase='root', cpu_max='50000 100000',
                                      cpu_quota_percent=50, memory_max_bytes=2147483648),
                       host_clients=dict(scope='host', phase='paired_clients', inherits='host_root'),
                       host_metadata=dict(scope='host', phase='metadata', inherits='host_root'),
                       guest_setup=dict(scope='guest', phase='setup', cpu_quota_percent=200,
                                        memory_max_bytes=42949672960),
                       guest_model=dict(scope='guest', phase='model', cpus=4,
                                        memory_bytes=34359738368, memory_swap_bytes=34359738368,
                                        gpus='device=0', tmpfs='/tmp:rw,nosuid,nodev,size=268435456'),
                       guest_control=dict(scope='guest', phase='model_control_and_automatic_restore',
                                          cpu_quota_percent=25, memory_max_bytes=268435456),
                       guest_cleanup=dict(scope='guest', phase='cleanup', cpu_quota_percent=50,
                                          memory_max_bytes=536870912)),
                   phase_floors_seconds=floors,
                   start_reserve_seconds=START_RESERVE,
                   predecessor_refresh_seconds=dict(stop=75, stop_observe=195, withdraw=75, auto_observe=190, reconcile=45),
                   public_STOP_AUTO_cleanup_seconds=580,
                   public_cleanup_clock='Separate fixed public observation clocks after restore; never extend intent/native',
                   setup_native_seconds=540, setup_outer_seconds=570,
                   shared_client_sha256=PINS['paired_client.py'], no_execution=True,
                   gate_token=sha(recipe.replace(guard, '').encode()),
                   limitations=['Independent Sol XHIGH review required before coordinator execution',
                                'Actual paired pilot and actual capacity-return settlement required before full',
                                'No live qualification, independent acceptance, or quality claim',
                                'Client deadline can retain incomplete and invalid pairs; no selective retries',
                                '15 seconds per image is a scheduling floor, not measured Qwen latency or a completion guarantee',
                                'Predecessor is bound at claim by stop/withdraw refresh; coordinator must verify late-bound-predecessor.json and actual pilot receipt contents after the run; a digest alone is not acceptance'])
    if replacement is not None:
        receipt['replacement'] = replacement
    if missing is not None:
        receipt['missing_only'] = missing
    return recipe, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--candidate', choices=SOURCES, required=True)
    parser.add_argument('--mode', choices=tuple(SELECTION), required=True)
    parser.add_argument('--revision', type=Path, help='corpus-revision-r2.json; replacement mode only')
    parser.add_argument('--missing-inventory', type=Path)
    parser.add_argument('--protocol-sha256')
    parser.add_argument('--corpus-sha256')
    parser.add_argument('--name', required=True)
    parser.add_argument('--unit', required=True)
    parser.add_argument('--cohort', action='append', dest='cohorts')
    parser.add_argument('--client-seconds', type=int)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.out.resolve().is_relative_to(args.references.resolve()), 'references are immutable; choose another output directory')
        recipe, receipt = prepare(args.references, args.candidate, args.mode, args.name,
                                  args.unit, args.cohorts, args.client_seconds, args.revision,
                                  args.missing_inventory, args.protocol_sha256, args.corpus_sha256)
        args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
        (args.out / 'recipe.remote.py').write_text(recipe)
        (args.out / 'prepared-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
