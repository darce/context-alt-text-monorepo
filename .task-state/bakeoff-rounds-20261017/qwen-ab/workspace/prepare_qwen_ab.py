"""Prepare prospective Qwen paired A/B recipes; never execute generated code.

Example: python3 prepare_qwen_ab.py --references ../references --candidate gsq
 --mode pilot --name QWEN-PILOT-R1 --unit workbay-qwen-pilot.scope
 --actual-previous-auto UUID --out /tmp/qwen-prepared

Coordinator execution requires independent Sol XHIGH review. Full cohorts also
require an actual paired pilot and predecessor settlement, checked by operator.
"""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import uuid

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


def prepare(root, candidate, mode, name, unit, actual_previous_auto, cohorts=None,
            client_seconds=None):
    require(candidate in SOURCES and mode in ('pilot', 'full'), 'candidate/mode required')
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,90}', name or '')), 'explicit safe name required')
    require(bool(re.fullmatch(r'workbay-[A-Za-z0-9_-]+\.scope', unit or '')), 'explicit scope unit required')
    require(bool(actual_previous_auto) and str(uuid.UUID(actual_previous_auto)) == actual_previous_auto,
            'explicit canonical actual previous AUTO required')
    root = Path(root)
    inputs = {key: pinned(root, key) for key in PINS}
    source = inputs['LEXICON-MIMO-40-LAST40-R1.remote.py'].decode()
    prior = inputs[SOURCES[candidate]].decode()
    plan = json.loads(inputs['batch-plan.json'])
    model, configs = validate_configs(root, plan, candidate)
    if mode == 'pilot':
        require(not cohorts, 'pilot uses first immutable config only')
        cfg = json.loads(configs[0][1]); cfg['images'] = cfg['images'][:2]
        selected = [(configs[0][0], (json.dumps(cfg, indent=2) + '\n').encode())]
    else:
        require(bool(cohorts) and len(set(cohorts)) == len(cohorts), 'explicit unique full cohorts required')
        available = dict(configs)
        require(all(c in available for c in cohorts), 'unknown candidate config')
        require(cohorts == [c for c, _ in configs if c in cohorts], 'preserve frozen cohort order')
        selected = [(c, available[c]) for c in cohorts]
    count = sum(len(json.loads(raw)['images']) for _, raw in selected)
    client = client_seconds if client_seconds is not None else (420 if mode == 'pilot' else 650)
    # Fixed phase reservations, not a promise every request will finish. The
    # native client deadline preserves incomplete/invalid attempts without retry.
    floors = dict(identity=180, setup=570, metadata=30, client=client, restore=270, control=80)
    require(isinstance(client, int) and 3 * 5 * count <= client <= (420 if mode == 'pilot' else 1000),
            'cohort impossible under client floor/cap (15 seconds per image)')
    require(sum(floors.values()) <= 1800, 'phase floors exceed fixed intent1800')
    require(150 + 30 + client + 270 <= 1500, 'phase floors exceed native1500')
    spec, template = producer(prior)
    prep = json.loads(inputs['qwen-remote-preparation.json'])['candidates']['qwen-' + candidate]
    require(sha(template.encode()) == prep['setup_sha256'], 'qualified setup hash mismatch')
    require(all(spec[k] == v for k, v in prep['asset_spec'].items()), 'qualified spec mismatch')
    encoded = {c: dict(b64=base64.b64encode(raw).decode(), sha256=sha(raw),
                       immutable_source_sha256=sha(dict(configs)[c]),
                       selection='first-two' if mode == 'pilot' else 'whole-cohort')
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
    recipe = replace_once(recipe, "N='LEXICON-MIMO-40-LAST40-R1'", 'N=' + repr(name))
    recipe = replace_once(recipe, "N=" + repr(name), "assert " + repr(unit) + " in cg.parts, 'Declared root scope mismatch'\nN=" + repr(name))
    recipe = replace_once(recipe, "assert previous=='aa048fdb-01cc-405d-9e2c-5af0063093fb'",
                          'assert previous==' + repr(actual_previous_auto))
    recipe = replace_once(recipe, "    print(json.dumps(dict(status='PRIVATE_RAW_WORKSPACE_READY'", "    observe(previous,'auto','actual-previous-auto-observe',190)\n    assert public(['reconcile',str(window),wid],'actual-previous-auto-reconcile',45)==previous, 'Actual predecessor changed'\n    print(json.dumps(dict(status='PRIVATE_RAW_WORKSPACE_READY'")
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
    recipe = recipe.replace('>=1420,', '>=' + str(570 + 30 + client + 270) + ',')
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
    # This guard is deliberately unresolved until independent review. The CLI
    # cannot certify review or a live pilot by generating a recipe.
    guard = "assert os.environ.get('QWEN_AB_SOL_XHIGH_GATE')==" + repr(sha(recipe.encode())) + ", 'Independent Sol XHIGH gate required; coordinator execution only'\n"
    if mode == 'full':
        guard += "assert os.environ.get('QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256') and re.fullmatch(r'[0-9a-f]{64}',os.environ['QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256']), 'Actual pilot receipt required before full; coordinator must verify contents'\n"
    recipe = replace_once(recipe, "assert os.geteuid()==os.getuid()==0", guard + "assert os.geteuid()==os.getuid()==0")
    for func in ('public', 'observe', 'guest'):
        require(function_bytes(source, func) == function_bytes(recipe, func), 'effect helper changed')
    compile(recipe, '<prospective-recipe>', 'exec')
    receipt = dict(status='PROSPECTIVE_NOT_EXECUTED_NOT_QUALIFIED', name=name, unit=unit,
                   candidate=candidate, mode=mode, actual_previous_AUTO=actual_previous_auto,
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
                   phase_floors_seconds=floors, previous_AUTO_observation_seconds=190, public_STOP_AUTO_cleanup_seconds=580,
                   public_cleanup_clock='Separate fixed public observation clocks after restore; never extend intent/native',
                   setup_native_seconds=540, setup_outer_seconds=570,
                   shared_client_sha256=PINS['paired_client.py'], no_execution=True,
                   gate_token=sha(recipe.replace(guard, '').encode()),
                   limitations=['Independent Sol XHIGH review required before coordinator execution',
                                'Actual paired pilot and actual capacity-return settlement required before full',
                                'No live qualification, independent acceptance, or quality claim',
                                'Client deadline can retain incomplete and invalid pairs; no selective retries',
                                '15 seconds per image is a scheduling floor, not measured Qwen latency or a completion guarantee',
                                'Coordinator must verify actual pilot receipt contents and predecessor custody; a digest alone is not acceptance'])
    return recipe, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--candidate', choices=SOURCES, required=True)
    parser.add_argument('--mode', choices=('pilot', 'full'), required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--unit', required=True)
    parser.add_argument('--actual-previous-auto', required=True)
    parser.add_argument('--cohort', action='append', dest='cohorts')
    parser.add_argument('--client-seconds', type=int)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.out.resolve().is_relative_to(args.references.resolve()), 'references are immutable; choose another output directory')
        recipe, receipt = prepare(args.references, args.candidate, args.mode, args.name,
                                  args.unit, args.actual_previous_auto, args.cohorts, args.client_seconds)
        args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
        (args.out / 'recipe.remote.py').write_text(recipe)
        (args.out / 'prepared-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
