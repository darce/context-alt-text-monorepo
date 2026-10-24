"""Bounded offline regression checks using real corpus bytes and genuine service."""
import argparse
import ast
import copy
import json
import os
from pathlib import Path
import sys
import unittest

import raw_generation as r


def safety(output):
    def audit(event, args):
        if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind',
                     'os.system', 'os.exec', 'os.posix_spawn', 'subprocess.Popen'):
            raise RuntimeError('offline check blocks ' + event)
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            if path.suffix.lower() in ('.gguf', '.onnx', '.safetensors', '.pt', '.pth') or path.name.startswith('.env'):
                raise RuntimeError('offline check blocks protected input')
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                if not path.absolute().is_relative_to(output):
                    raise RuntimeError('offline check blocks write outside OUTPUT')
    sys.addaudithook(audit)


class RawGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(ARGS.output).resolve()
        cls.out.mkdir(parents=True, exist_ok=True)
        safety(cls.out)
        cls.packet = Path(ARGS.packet)
        cls.refs = Path(ARGS.references)
        cls.key = cls.out / 'PUBLIC-NONSECRET.key'
        cls.key.write_text('PUBLIC_NONSECRET_OFFLINE_FIXTURE')
        cls.key.chmod(0o400)
        batches = [r.strict_json(r.read(cls.refs / f'sealed-inputs/batch-configs/incumbent-{i:02d}.json')) for i in range(1, 7)]
        image_map = {i['image_id']: i['path'] for b in batches for i in b['images']}
        image_map['original-038'] = str(Path(ARGS.r2_image).resolve())
        cls.image_map = cls.out / 'image-map.json'
        r.write_new(cls.image_map, image_map)
        cls.paths = dict(references=str(cls.refs), service=str(cls.refs / 'service'),
                         planner=str(cls.packet / 'generation/FACTORIAL-R4/extraction_factorial_plan.py'),
                         input_manifest=str(cls.packet / 'generation/FACTORIAL-R4/fixtures/factorial/current-input-manifest.v2.json'),
                         original_producer=ARGS.original_producer, canon_root=str(cls.refs / 'canon'),
                         loader=str(cls.refs / 'baseline/depiction_lexicon.py'),
                         selected_models=str(Path(ARGS.immutable) / 'selected-models.json'), image_map=str(cls.image_map))
        cls.profiles = r.strict_json(r.read(cls.paths['selected_models']))['models']
        cls.bindings = {p['model']: dict(endpoint='http://offline.invalid', model_id='fixture-' + p['model'],
                                       model_version=p['model'], revision=p['revision']) for p in cls.profiles}
        r.write_new(cls.out / 'bindings.json', cls.bindings)
        cls.contracts = {size: r.prepare(cls.paths, size=size, bindings=cls.bindings, keyfile=str(cls.key)) for size in (2, 20, 120)}
        cls.contract_files = {}
        for size, contract in cls.contracts.items():
            path = cls.out / f'contract-{size}.json'
            cls.contract_files[size] = (path, r.write_new(path, contract))
        cls.producer = r.module(r.HERE / 'extraction_paired_client_v2.py', '_test_producer_v2',
                               cls.contracts[2]['lineage']['own_sources']['extraction_paired_client_v2.py'])
        # Genuine loader loads the actual service. No sys.modules fabrication.
        cls.b, cls.lex = cls.producer.load_resources(cls.contracts[2]['operations'][0]['config'])
        import httpx
        cls.httpx = httpx
        r.pin(cls.b.__file__, r.BAKEOFF)
        cls.facts = dict(people=[], setting='room', action='', legible_text=[], atmosphere='unknown')
        cls.surfaces = dict(title='Offline fixture', alt='A room.', caption='A room in an offline fixture.')

    def test_00_source_lineage_and_prior_art(self):
        raw = r.read(self.packet / 'input-manifest.json')
        self.assertEqual(r.sha(raw), 'e1531811f839409cc269fbf4a529f895ec2731e0dc082eafc282c0037306d80a')
        manifest = r.strict_json(raw)
        for name, pin in manifest.items():
            data = r.read(self.packet / name)
            self.assertEqual((r.sha(data), len(data)), (pin['sha256'], pin['bytes']), name)
        maps = {}
        for root, pin in ((self.packet / 'dispatch', 'be5d48b38350245a5c84499fc62b2e4f1ffd60536d4a3caca1974a06ef062db5'),
                          (Path(ARGS.startup), 'f5b234e2d77a544b77eec08cd24f0c254216db7fd5e63f8c95bab86366f2f995')):
            path = root / 'source-ast-codemap.json'
            r.pin(path, pin)
            count = 0
            for name, entries in r.strict_json(r.read(path)).items():
                tree = ast.parse(r.read(root / name).decode())
                actual = {(n.name, n.lineno, n.end_lineno) for n in ast.walk(tree)
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                for entry in entries:
                    self.assertIn((entry['name'], entry['start'], entry['end']), actual)
                    count += 1
            maps[str(path)] = dict(sha256=pin, symbols_checked=count)
        prior = Path(ARGS.audit_fixtures)
        index = r.strict_json(r.read(prior / 'evidence-index.json'))
        for name in ('verified-inputs.json', 'grid-results.json', 'fixture-results.json', 'topology-only.json'):
            r.pin(prior / name, index[name]['sha256'])
            r.strict_json(r.read(prior / name))
        r.write_new(self.out / 'verified-inputs.json', dict(primary_manifest_sha256=r.sha(raw),
                    entries_verified=len(manifest), codemaps=maps, prior_art=index,
                    native='UNOBSERVED', inference=False))

    def handler(self, cfg, binding, attempts, mode='valid'):
        def handle(request):
            body = json.loads(request.content)
            extraction = body['messages'][0]['content'] == self.producer.extraction_prompt(self.b._PASS1_SYSTEM_PROMPT, self.lex, cfg['extraction_lexicon'])
            arm = None if extraction else ('on' if self.lex.render() in body['messages'][0]['content'] else 'off')
            self.assertEqual(request.headers['authorization'], 'Bearer PUBLIC_NONSECRET_OFFLINE_FIXTURE')
            self.assertEqual(body['max_tokens'], 1536 if extraction else 512)
            self.assertEqual(body['model'], binding['model_id'])
            attempts.append(dict(extraction=extraction, arm=arm, body=body,
                                 timeout=request.extensions['timeout']))
            if mode == 'deadline' and request.extensions['timeout']['read'] < 80.34:
                raise self.httpx.ReadTimeout('offline simulated 80.34-second response', request=request)
            text = json.dumps(self.facts if extraction else self.surfaces)
            if mode == 'bad-extraction' and extraction:
                text = '{}'
            if mode == 'bad-writer' and not extraction:
                text = '{}'
            mismatch = mode == 'mismatch' or mode == 'mismatch-writer' and not extraction
            envelope = dict(model='wrong-model' if mismatch else binding['model_id'],
                            choices=[dict(message=dict(content=text))],
                            usage=dict(prompt_tokens=2, completion_tokens=3, total_tokens=5))
            return self.httpx.Response(503 if mode == 'http503' else 200, json=envelope)
        return handle

    def run_operation(self, oid, mode='valid', size=2):
        contract = self.contracts[size]
        op = next(o for o in contract['operations'] if o['operation_id'] == oid)
        binding = self.bindings[op['model']]
        attempts = []
        out = self.out / (oid.replace('/', '-') + '-' + mode + f'-{size}.json')
        report = r.execute(contract, operation_id=oid, binding=binding, keyfile=str(self.key), out=out,
                           transport=self.httpx.MockTransport(self.handler(op['config'], binding, attempts, mode)))
        raw = r.strict_json(r.read(report['raw_artifact']['path']))
        # Requests contain real frozen pixels; retain only hashes and stage metadata.
        r.write_new(out.with_name(out.stem + '-transport.json'), [dict(extraction=a['extraction'], arm=a['arm'],
                    messages_sha256=self.producer.message_sha(a['body']['messages']), timeout=a['timeout']) for a in attempts])
        self.assertEqual(report['post_attempts'], len(attempts))
        return report, raw, attempts

    def test_10_original_red_and_new_green(self):
        original = r.module(ARGS.original_producer, '_test_original_producer', r.ORIGINAL)
        tree = ast.parse(r.read(ARGS.original_producer).decode())
        timeouts = [kw.value.value for n in ast.walk(tree) if isinstance(n, ast.Call)
                    for kw in n.keywords if kw.arg == 'timeout_s' and isinstance(kw.value, ast.Constant)]
        self.assertEqual(timeouts, [60])
        old_path = self.packet / 'generation/CAUSAL-R4/prepare_extraction_native.py'
        old = r.module(old_path, '_test_old_preparer', '2c00c78c61678ab7ad5c0866dd587f4dca40eae6e906a63cc2ff6cc29a14477d')
        with self.assertRaisesRegex(ValueError, 'Eon'):
            old.cohort_config(self.refs, size=20, treatment=False, batch=1)
        cfg = old.cohort_config(self.refs, size=2, treatment=False)
        self.assertIn('q4', cfg['model_version'])
        old_tree = ast.parse(r.read(old_path).decode())
        main = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        self.assertIsInstance(main.body[-1], ast.Return)
        self.assertEqual(main.body[-1].value.value, 2)
        op = self.contracts[2]['operations'][0]
        binding = self.bindings[op['model']]
        attempts = []
        raw = original.run(op['config'], out=self.out / 'original-timeout-red.json', keyfile=str(self.key),
                           model_id=binding['model_id'], b=self.b, lex=self.lex,
                           transport=self.httpx.MockTransport(self.handler(op['config'], binding, attempts, 'deadline')))
        self.assertFalse(raw['completed'])
        self.assertTrue(all(a['timeout']['read'] == 60 for a in attempts))
        report, _, attempts = self.run_operation(op['operation_id'], 'deadline')
        self.assertTrue(report['completed'])
        self.assertTrue(all(a['timeout']['read'] == 600 for a in attempts))
        r.write_new(self.out / 'causal-red-green.json', dict(original_completed=False, revised_completed=True,
                    original_timeout=60, revised_timeout=600, synthetic_deadline_seconds=80.34,
                    network_calls=0, inference=False))

    def test_20_profile_validation(self):
        profile = self.profiles[0]
        binding = self.bindings[profile['model']]
        for key, value in (('model_version', 'Q4'), ('revision', 'wrong'), ('model_id', True), ('endpoint', 'http://user:key@host')):
            bad = dict(binding, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                r.validate_binding(profile, bad, 600, False)
        for timeout in (True, 59, 1801, 600.0, float('nan')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                r.validate_binding(profile, binding, timeout, False)
        for treatment in (0, 1, 'off', None):
            with self.assertRaises(ValueError):
                r.validate_binding(profile, binding, 600, treatment)

    def test_30_cohorts_and_contract_pins(self):
        for size, contract in self.contracts.items():
            self.assertEqual(contract['denominators']['bundles'], 8*size)
            self.assertEqual(contract['denominators']['nominal_POSTs'], 12*size)
            self.assertEqual(len(contract['cells']), 8*size)
            self.assertTrue(all(len(op['config']['images']) <= 20 for op in contract['operations']))
            self.assertEqual(len(contract['operations']), 24 if size == 120 else 4)
            self.assertEqual({(c['extraction_lexicon'], c['writing_lexicon']) for c in contract['cells']},
                             {(False, False), (False, True), (True, False), (True, True)})
            path, digest = self.contract_files[size]
            self.assertEqual(r.load_contract(path, digest), contract)
        r2 = next(i for i in self.contracts[120]['images'] if i['image_id'] == 'original-038')
        self.assertEqual(r2['sha256'], r.R2)
        self.assertEqual(r.sha(r.read(r2['path'])), r.R2)
        with self.assertRaises(ValueError):
            r.load_contract(self.contract_files[2][0], '0'*64)
        changed = copy.deepcopy(self.contracts[2])
        changed['behavior']['retries'] = 1
        path = self.out / 'tampered.json'
        digest = r.write_new(path, changed)
        with self.assertRaises(ValueError):
            r.load_contract(path, digest)

    def test_40_dry_run_no_auth_or_posts(self):
        contract = self.contracts[2]
        # The metadata-only path accepts a configured, nonexistent keyfile; execution cannot.
        contract = copy.deepcopy(contract)
        contract['preparation']['keyfile'] = str(self.out / 'DOES-NOT-EXIST.key')
        op = contract['operations'][0]
        def forbidden(_):
            self.fail('dry-run sent a POST')
        report = r.execute(contract, operation_id=op['operation_id'], binding=self.bindings[op['model']],
                           keyfile=contract['preparation']['keyfile'], out=self.out / 'dry-run.json', dry_run=True,
                           transport=self.httpx.MockTransport(forbidden))
        self.assertEqual(report['post_attempts'], 0)
        self.assertTrue(all(c['state'] == 'planned' for c in report['cells']))
        bad_key = self.out / 'PUBLIC-UNSAFE.key'
        bad_key.write_text('PUBLIC_NONSECRET_OFFLINE_FIXTURE')
        bad_key.chmod(0o644)
        contract['preparation']['keyfile'] = str(bad_key)
        with self.assertRaises(ValueError):
            r.execute(contract, operation_id=op['operation_id'], binding=self.bindings[op['model']],
                      keyfile=str(bad_key), out=self.out / 'unsafe-key.json', transport=self.httpx.MockTransport(forbidden))

    def test_50_actual_grid_and_post_facts_hashes(self):
        posts = 0
        for op in self.contracts[2]['operations']:
            report, raw, attempts = self.run_operation(op['operation_id'])
            posts += len(attempts)
            self.assertTrue(report['completed'])
            self.assertTrue(all(c['state'] == 'success' for c in report['cells']))
            self.assertEqual(raw['producer_version'], 'raw-generation-paired/v2')
            self.assertNotEqual(raw['producer_sha256'], r.ORIGINAL)
            for index, row in enumerate(raw['items']):
                sent = attempts[3*index:3*index+3]
                self.assertEqual(sum(a['extraction'] for a in sent), 1)
                facts = row['shared_extraction'][0]['raw']
                self.assertEqual(row['raw_facts_sha256'], self.producer.sha(facts))
                part = sent[0]['body']['messages'][1]['content'][0]
                for a in sent[1:]:
                    arm = a['arm']
                    actual = a['body']['messages']
                    self.assertEqual(row['stage_prompts']['writing_' + arm]['messages_sha256'], self.producer.message_sha(actual))
                    client = self.b.BakeoffClient('http://offline.invalid', model_id='fixture', prompt_variant='v3',
                                                  caption_length='standard', two_pass=True, seed=0, no_think=True,
                                                  depiction_lexicon=self.lex if arm == 'on' else None,
                                                  transport=self.httpx.MockTransport(lambda _: self.fail('builder POST')))
                    try:
                        self.assertEqual(client._weave_messages(facts, {}, image_part=part), actual)
                    finally:
                        client.close()
        self.assertEqual(posts, 24)
        r.write_new(self.out / 'grid-results.json', dict(profiles=list(self.bindings), cells=16,
                    nominal_POSTs=24, actual_transport_POSTs=posts, hashes_match_actual_messages=True,
                    inference=False, native='UNOBSERVED'))

    def test_60_failures_and_unattempted_cells(self):
        oid = self.contracts[2]['operations'][1]['operation_id']
        for mode in ('bad-extraction', 'bad-writer', 'mismatch', 'mismatch-writer'):
            report, raw, attempts = self.run_operation(oid, mode)
            self.assertFalse(report['completed'])
            self.assertFalse(any(c['state'] == 'success' for c in report['cells']))
            self.assertEqual(len(report['cells']), 4)
            self.assertTrue(any(c['state'] == 'failed' for c in report['cells']))
            if mode == 'mismatch':
                self.assertEqual(len(attempts), 1)
                self.assertEqual(sum(c['state'] == 'unattempted' for c in report['cells']), 2)
            if mode == 'mismatch-writer':
                self.assertEqual(len(attempts), 2)
                self.assertEqual(sum(c['state'] == 'unattempted' for c in report['cells']), 3)
            if mode == 'bad-extraction':
                self.assertEqual(len(attempts), 2)
                self.assertTrue(all(a['extraction'] for a in attempts))
        report, raw, attempts = self.run_operation(oid, 'http503', size=20)
        self.assertFalse(report['completed'])
        self.assertEqual(len(attempts), 3)  # Real service breaker, zero retries.
        self.assertEqual(report['client_pass_records'], 20)
        self.assertEqual(len(report['cells']), 40)
        self.assertTrue(all(c['state'] == 'failed' for c in report['cells']))
        r.write_new(self.out / 'failure-results.json', dict(planned_bundles=40, client_pass_records=20,
                    actual_transport_POSTs=3, automatic_retries=0, completed=False, inference=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'packet', 'references', 'original-producer', 'immutable', 'startup', 'audit-fixtures', 'r2-image'):
        parser.add_argument('--' + name, required=True)
    ARGS, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0]] + remaining)
