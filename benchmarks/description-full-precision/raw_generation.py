"""Prospective RAW-GENERATION v1: offline preparation and explicit paired execution."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

SCHEMA = 'description-full-precision-raw-generation/v1'
SELECTED = '76ba20901ab36ad225e86cbd1a121d4cb275dcde51a0e13b0ec436b2657e0f5e'
PLANNER = 'f89a76b34b4104d1f345a6ab2b576d597bbda2f9489775ddfa2846c994bbe617'
MANIFEST = '2eab8102506bce422eeb8d7d5f780402f838e65aab4d308fc8df9d08876c0138'
ORIGINAL = '5c89754916884fc3448e00067e40afab4fd0f850bb430200a7a74c82bafc1838'
BAKEOFF = '87c58a41cb0a9421605dd9adf80aaee91bdde7eb5b6e54c39cde540f97e3ca66'
R2 = '710a6798653ef868338136da63e2c176e892d73bac342e395bf0df640e70022e'
COHORTS = {2: 'integration2', 20: 'exploratory20', 120: 'full120'}
HERE = Path(__file__).resolve().parent
PATH_ARGS = ('references', 'service', 'planner', 'input_manifest', 'original_producer',
             'canon_root', 'loader', 'selected_models', 'image_map')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, limit=16 * 1024**2):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit, 'input exceeds bounded read')
    return raw


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            need(k not in result, 'duplicate JSON key')
            result[k] = v
        return result
    def nonfinite(_):
        raise ValueError('nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def pin(path, digest):
    need(sha(read(path)) == digest, 'source digest mismatch: ' + str(path))


def module(path, name, digest):
    pin(path, digest)
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    # These are actual modules executed from pinned files, never service stubs.
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def validate_binding(profile, binding, timeout_s, extraction_lexicon):
    need(type(timeout_s) is int and 60 <= timeout_s <= 1800, 'timeout must be integer 60..1800')
    need(type(extraction_lexicon) is bool, 'extraction treatment must be boolean')
    need(type(binding) is dict and set(binding) == {'endpoint', 'model_id', 'model_version', 'revision'},
         'explicit endpoint/model_id/model_version/revision required')
    need(all(type(v) is str and v and v == v.strip() for v in binding.values()), 'invalid binding string')
    need(binding['model_version'] == profile['model'], 'wrong model version')
    need(binding['revision'] == profile['revision'], 'wrong model revision')
    url = urlsplit(binding['endpoint'])
    need(url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password
         and url.path in ('', '/') and not url.query and not url.fragment, 'endpoint must be a root HTTP URL without credentials')
    need(url.port is None or 1 <= url.port <= 65535, 'invalid endpoint port')


def prepare(paths, *, size, bindings, keyfile, timeout_s=600):
    """Metadata only: no clients, image reads, key reads, HTTP or service imports."""
    need(type(size) is int and size in COHORTS, 'cohort must be 2/20/120')
    need(set(paths) == set(PATH_ARGS), 'explicit source paths required')
    paths = {k: str(Path(v).resolve()) for k, v in paths.items()}
    need(Path(keyfile).is_absolute(), 'keyfile path must be absolute')
    pin(paths['selected_models'], SELECTED)
    pin(paths['input_manifest'], MANIFEST)
    pin(paths['original_producer'], ORIGINAL)
    planner = module(paths['planner'], '_raw_generation_planner', PLANNER)
    inputs = planner.load_inputs(paths['references'], input_manifest=paths['input_manifest'],
                                 service=paths['service'])
    need(sha(read(Path(paths['service']) / 'scripts/eval_harness/bakeoff.py')) == BAKEOFF, 'bakeoff pin')
    selected = strict_json(read(paths['selected_models']))['models']
    need(selected == inputs['models'], 'selected profiles differ from current input manifest')
    need(type(bindings) is dict and set(bindings) == {p['model'] for p in selected}, 'both selected profiles required')
    pin(paths['loader'], planner.LOADER)
    loader = module(paths['loader'], '_raw_generation_lexicon', planner.LOADER)
    lex = loader.load_depiction_lexicon(paths['canon_root'])
    need(lex.sha256 == inputs['pins']['canon/lexicons/depiction.md']
         and lex.version == 'canon v0.26.2' and len(lex.rules) == 17, 'canon identity')
    ids = planner.cohort_ids(inputs, COHORTS[size])
    image_map = strict_json(read(paths['image_map']))
    need(type(image_map) is dict and set(ids) <= set(image_map)
         and set(image_map) <= {i['image_id'] for i in inputs['images']}, 'image map must cover frozen cohort only')
    frozen = {i['image_id']: i for cfg in inputs['batches'] for i in cfg['images']}
    images = []
    for row in inputs['images']:
        iid = row['image_id']
        if iid not in ids:
            continue
        path = image_map[iid]
        need(type(path) is str and Path(path).is_absolute(), 'absolute image path required')
        if iid == 'original-038':
            need(row['sha256'] == R2, 'R2 original-038 digest')
        images.append(dict(image_id=iid, path=path, sha256=row['sha256'],
                           source_cluster=frozen[iid]['source_cluster'],
                           historical_path=planner.R2_PATH if iid == 'original-038' else frozen[iid]['path']))
    operations, cells = [], []
    for profile in selected:
        binding = bindings[profile['model']]
        for enabled in (False, True):
            validate_binding(profile, binding, timeout_s, enabled)
            for offset in range(0, size, 20):
                chunk = images[offset:offset + 20]
                oid = f"{profile['model']}/E{int(enabled)}/{offset:03d}"
                cfg = dict(service_dir=paths['service'], loader_override=paths['loader'],
                           loader_sha256=planner.LOADER, canon_root=paths['canon_root'], canon_sha256=lex.sha256,
                           endpoint=binding['endpoint'], model_version=binding['model_version'],
                           model_revision=binding['revision'], extraction_lexicon=enabled, timeout_s=timeout_s,
                           images=[{k: i[k] for k in ('image_id', 'path', 'sha256', 'source_cluster')} for i in chunk])
                operations.append(dict(operation_id=oid, model=profile['model'], model_id=binding['model_id'],
                                       nominal_POSTs=3*len(chunk), config=cfg))
                for image in chunk:
                    eid = f"{profile['model']}/{image['image_id']}/E{int(enabled)}"
                    for writing in (False, True):
                        cells.append(dict(bundle_id=f'{eid}/W{int(writing)}', extraction_id=eid,
                                          operation_id=oid, image_id=image['image_id'],
                                          extraction_lexicon=enabled, writing_lexicon=writing,
                                          state='planned', raw_facts_sha256='UNOBSERVED',
                                          actual_writer_messages_sha256='UNOBSERVED'))
    own = {p.name: sha(read(p)) for p in (Path(__file__), HERE / 'extraction_paired_client_v2.py')}
    contract = dict(schema=SCHEMA, purpose='RAW-GENERATION_ONLY',
                    preparation=dict(paths=paths, size=size, bindings=copy.deepcopy(bindings),
                                     keyfile=str(keyfile), timeout_s=timeout_s),
                    lineage=dict(own_sources=own, original_producer_sha256=ORIGINAL,
                                 producer_version='raw-generation-paired/v2', planner_sha256=PLANNER,
                                 input_manifest_sha256=MANIFEST, selected_models_sha256=SELECTED,
                                 bakeoff_sha256=BAKEOFF, input_contract=inputs['contract'],
                                 source_manifest=inputs['pins'],
                                 explicit_files={k: sha(read(paths[k])) for k in ('image_map', 'loader', 'selected_models', 'planner', 'input_manifest', 'original_producer')}),
                    profiles=selected, cohort=dict(name=COHORTS[size], image_ids=ids), images=images,
                    behavior=dict(prompt_variant='v3', two_pass=True, caption_length='standard',
                                  extraction_max_tokens=1536, writer_max_tokens=512, seed=0,
                                  temperature=0, no_think=True, retries=0, timeout_s=timeout_s,
                                  shared_extraction_per_writer_pair=True, context_pack={}, present_identities=[]),
                    limits=dict(max_images_per_operation=20, one_model_resident_at_a_time=True,
                                model_lifecycle_managed=False, admission_managed=False),
                    evidence={k: 'UNOBSERVED' for k in ('native', 'runtime', 'model_serving', 'served_weights', 'quality')},
                    quality_consumer_adoption='SEPARATE_LATER_JOIN', speed_based_winner=False,
                    denominators=dict(images=size, models=2, bundles=8*size, extraction_POSTs=4*size,
                                      writing_POSTs=8*size, nominal_POSTs=12*size),
                    operations=operations, cells=cells)
    contract['seal'] = sha(canonical(contract))
    return contract


def write_new(path, value):
    """Exclusive artifact creation; never overwrite an earlier attempt."""
    raw = canonical(value) + b'\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def load_contract(path, expected_sha256):
    raw = read(path)
    need(sha(raw) == expected_sha256, 'contract file pin mismatch')
    contract = strict_json(raw)
    need(contract.get('schema') == SCHEMA, 'contract schema')
    args = contract['preparation']
    rebuilt = prepare(args['paths'], size=args['size'], bindings=args['bindings'],
                      keyfile=args['keyfile'], timeout_s=args['timeout_s'])
    need(canonical(rebuilt) == canonical(contract), 'contract/source validation mismatch')
    return contract


def execute(contract, *, operation_id, binding, keyfile, out, dry_run=False, transport=None):
    """One explicit model/E/chunk. CLI callers must use load_contract first."""
    operation = next((o for o in contract['operations'] if o['operation_id'] == operation_id), None)
    need(operation is not None, 'unknown operation')
    profile = next(p for p in contract['profiles'] if p['model'] == operation['model'])
    validate_binding(profile, binding, contract['behavior']['timeout_s'], operation['config']['extraction_lexicon'])
    need(binding == contract['preparation']['bindings'][profile['model']], 'execution binding differs from contract')
    need(str(keyfile) == contract['preparation']['keyfile'], 'execution keyfile path differs from contract')
    cells = [copy.deepcopy(c) for c in contract['cells'] if c['operation_id'] == operation_id]
    report = dict(schema='description-raw-generation-operation/v1', contract_seal=contract['seal'],
                  operation_id=operation_id, cells=cells, nominal_POSTs=operation['nominal_POSTs'],
                  post_attempts=0, client_pass_records=0, completed=False, dry_run=dry_run,
                  evidence=copy.deepcopy(contract['evidence']), error=None)
    # Preparation of an execution consumes no credential and imports no service.
    if dry_run:
        write_new(out, report)
        return report
    output = Path(out)
    need(not output.exists(), 'output exists')
    raw_path = output.with_name(output.name + '.producer.json')
    need(not raw_path.exists() and not raw_path.with_suffix('.partial.tmp').exists(), 'raw output exists')
    producer = module(HERE / 'extraction_paired_client_v2.py', '_raw_generation_producer_v2',
                      contract['lineage']['own_sources']['extraction_paired_client_v2.py'])
    raw = producer.run(operation['config'], out=raw_path, keyfile=keyfile,
                       model_id=binding['model_id'], transport=transport)
    report.update(post_attempts=raw['post_attempts'], completed=raw['completed'], error=raw['error'],
                  raw_artifact=dict(path=str(raw_path), sha256=sha(read(raw_path))))
    rows = {row['image_id']: row for row in raw['items']}
    for cell in cells:
        row = rows.get(cell['image_id'])
        cell['state'] = 'unattempted'
        if row is None:
            continue
        arm = 'on' if cell['writing_lexicon'] else 'off'
        result = row['arms'].get(arm)
        cell['raw_facts_sha256'] = row.get('raw_facts_sha256', 'UNOBSERVED')
        cell['actual_writer_messages_sha256'] = row['stage_prompts'].get('writing_' + arm, {}).get('messages_sha256', 'UNOBSERVED')
        if result is not None:
            success = not result['error'] and 'surfaces' in result
            cell['state'] = 'success' if success else 'failed'
            cell['error'] = None if success else (result['error'] or row['error'] or 'Incomplete writer')
        elif row['error']:
            # A stopped writer leaves its sibling unattempted; failed extraction
            # invalidates both dependent cells before either writer can start.
            cell['state'] = 'unattempted' if row['arms'] else 'failed'
            cell['error'] = row['error']
    report['client_pass_records'] = sum(len(r['shared_extraction']) + sum(len(a['passes']) for a in r['arms'].values()) for r in rows.values())
    write_new(out, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for name in PATH_ARGS:
        prep.add_argument('--' + name.replace('_', '-'), required=True)
    prep.add_argument('--size', type=int, choices=COHORTS, required=True)
    prep.add_argument('--bindings', required=True, help='JSON object keyed by both selected profiles')
    prep.add_argument('--timeout', type=int, default=600)
    prep.add_argument('--keyfile', required=True)
    prep.add_argument('--out', required=True)
    run = sub.add_parser('execute')
    for name in ('contract', 'contract-sha256', 'operation-id', 'endpoint', 'model-id', 'model-version', 'revision', 'keyfile', 'out'):
        run.add_argument('--' + name, required=True)
    run.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            contract = prepare({k: getattr(args, k) for k in PATH_ARGS}, size=args.size,
                               bindings=strict_json(read(args.bindings)), keyfile=args.keyfile, timeout_s=args.timeout)
            digest = write_new(args.out, contract)
            print(json.dumps(dict(status='PREPARED_RAW_GENERATION', contract_sha256=digest,
                                  denominators=contract['denominators'], evidence=contract['evidence'])))
            return 0
        contract = load_contract(args.contract, args.contract_sha256)
        report = execute(contract, operation_id=args.operation_id,
                         binding=dict(endpoint=args.endpoint, model_id=args.model_id,
                                      model_version=args.model_version, revision=args.revision),
                         keyfile=args.keyfile, out=args.out, dry_run=args.dry_run)
        print(json.dumps({k: report[k] for k in ('completed', 'dry_run', 'post_attempts', 'client_pass_records')}))
        return 0 if args.dry_run or report['completed'] else 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # No exception text: third party errors may contain private source paths.
        print(json.dumps(dict(status='REFUSED', error_type=type(exc).__name__)), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
