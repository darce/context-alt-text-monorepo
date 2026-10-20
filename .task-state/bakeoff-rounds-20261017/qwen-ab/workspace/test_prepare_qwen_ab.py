"""Stdlib tests: preparation and extracted real source producers, no live effects."""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import types
import unittest

import prepare_qwen_ab as p

REF = Path(__file__).resolve().parent.parent / 'references'
AUTO = '11111111-1111-4111-8111-111111111111'


def make(candidate='gsq', mode='pilot', **kwargs):
    return p.prepare(REF, candidate, mode, 'QWEN-TEST-R1', 'workbay-qwen-test.scope',
                     AUTO, **kwargs)


def execute_producer(source):
    # Execute actual source assignment nodes only. No runtime/setup effects.
    nodes = [p.assignment(source, 'spec'), p.assignment(source, 'setup_program')]
    env = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<actual-producer>', 'exec'), env)
    return env['spec'], env['setup_program']


def command_resource_contracts(recipe):
    """Evaluate only actual command assignments, never the recipe or setup."""
    tree = ast.parse(recipe)
    spec, setup = execute_producer(recipe)
    outer = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'command' for t in node.targets)
                and any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and 'sudo -n systemd-run --scope' in n.value
                        for n in ast.walk(node.value))):
            env = dict(operation='test', setup_program=setup,
                       cleanup_program='cleanup-placeholder', shlex=shlex)
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<outer-command>', 'exec'), env)
            args = shlex.split(env['command'])
            phase = 'setup' if '-setup-' in env['command'] else 'cleanup'
            outer[phase] = args
    env = dict(v=dict(spec, unit='test.service', candidate_name='test', operation='test'),
               root=Path('/run/test'), cache=Path(spec['cache']))
    node = p.assignment(setup, 'command')
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<model-command>', 'exec'), env)
    model = env['command']

    def properties(args):
        values = dict(a.removeprefix('--property=').split('=', 1)
                      for a in args if a.startswith('--property='))
        return dict(cpu_quota_percent=int(values['CPUQuota'].removesuffix('%')),
                    memory_max_bytes=int(values['MemoryMax']))

    # Read the right-hand sides of the actual host cgroup assertions.
    host = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Call):
            text = ast.get_source_segment(recipe, node.left)
            for filename in ('cpu.max', 'memory.max'):
                if "cg/'" + filename + "'" in text:
                    host[filename] = ast.literal_eval(node.comparators[0])
    quota, period = map(int, host['cpu.max'].split())
    return dict(
        host_root=dict(scope='host', phase='root', cpu_max=host['cpu.max'],
                       cpu_quota_percent=100 * quota / period,
                       memory_max_bytes=int(host['memory.max'])),
        host_clients=dict(scope='host', phase='paired_clients', inherits='host_root'),
        host_metadata=dict(scope='host', phase='metadata', inherits='host_root'),
        guest_setup=dict(scope='guest', phase='setup', **properties(outer['setup'])),
        guest_model=dict(scope='guest', phase='model', cpus=float(model[model.index('--cpus') + 1]),
                         memory_bytes=int(model[model.index('--memory') + 1]),
                         memory_swap_bytes=int(model[model.index('--memory-swap') + 1]),
                         gpus=model[model.index('--gpus') + 1],
                         tmpfs=model[model.index('--tmpfs') + 1]),
        guest_control=dict(scope='guest', phase='model_control_and_automatic_restore',
                           **properties(model)),
        guest_cleanup=dict(scope='guest', phase='cleanup', **properties(outer['cleanup'])))


class PreparationTests(unittest.TestCase):
    def test_resource_contracts_match_actual_commands(self):
        for candidate in ('gsq', 'ud'):
            for mode in ('pilot', 'full'):
                with self.subTest(candidate=candidate, mode=mode):
                    cohorts = None if mode == 'pilot' else ['qwen-' + candidate + '-01.json']
                    recipe, receipt = make(candidate, mode, cohorts=cohorts)
                    self.assertEqual(receipt['resource_contracts'], command_resource_contracts(recipe))
                    # Client and metadata launchers retain their inherited host scope.
                    original = (REF / 'LEXICON-MIMO-40-LAST40-R1.remote.py').read_text()
                    self.assertEqual(p.function_bytes(recipe, 'gate'), p.function_bytes(original, 'gate'))
                    def launches(source):
                        return [ast.dump(n) for n in ast.walk(ast.parse(source))
                                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                and n.func.attr == 'Popen']
                    self.assertEqual(launches(recipe), launches(original))

    def test_resource_contract_receipt_mutations_are_detected(self):
        recipe, receipt = make()
        actual = command_resource_contracts(recipe)
        for phase, fields in actual.items():
            for field in fields:
                with self.subTest(phase=phase, field=field):
                    damaged = copy.deepcopy(receipt['resource_contracts'])
                    damaged[phase][field] = 'incorrect'
                    with self.assertRaises(AssertionError):
                        self.assertEqual(damaged, actual)
            with self.subTest(missing_phase=phase):
                damaged = copy.deepcopy(receipt['resource_contracts'])
                del damaged[phase]
                with self.assertRaises(AssertionError):
                    self.assertEqual(damaged, actual)

    def test_resource_contract_command_mutations_are_detected(self):
        recipe, receipt = make()
        for old, new in [('50000 100000', '60000 100000'),
                         ('2147483648', '2147483649'),
                         ('CPUQuota=200%', 'CPUQuota=201%'),
                         ('42949672960', '42949672961'),
                         ('CPUQuota=25%', 'CPUQuota=26%'),
                         ('268435456', '268435457'),
                         ('32*1024**3', '31*1024**3'),
                         ("\\'--cpus\\',\\'4\\'", "\\'--cpus\\',\\'3\\'"),
                         ('device=0', 'device=1'),
                         ('size=268435456', 'size=268435457'),
                         ('CPUQuota=50%', 'CPUQuota=51%'),
                         ('536870912', '536870913')]:
            with self.subTest(producer=old):
                self.assertIn(old, recipe)
                changed = recipe.replace(old, new)
                with self.assertRaises(AssertionError):
                    self.assertEqual(receipt['resource_contracts'], command_resource_contracts(changed))

    def test_both_candidates_and_modes_actual_producers(self):
        for candidate in ('gsq', 'ud'):
            prior = (REF / p.SOURCES[candidate]).read_text()
            prior_spec, prior_setup = execute_producer(prior)
            for mode in ('pilot', 'full'):
                with self.subTest(candidate=candidate, mode=mode):
                    cohorts = None if mode == 'pilot' else ['qwen-' + candidate + '-01.json',
                                                           'qwen-' + candidate + '-02.json']
                    recipe, receipt = make(candidate, mode, cohorts=cohorts)
                    spec, setup = execute_producer(recipe)
                    self.assertEqual(spec, prior_spec)
                    self.assertEqual(setup, prior_setup)
                    self.assertIn('time.monotonic()+110', setup)
                    self.assertIn('time.monotonic()+150', setup)
                    self.assertIn('RuntimeMaxSec=540', recipe)
                    self.assertIn('guest(command,570)', recipe)
                    self.assertIn("'Actual predecessor changed'", recipe)
                    self.assertIn("observe(previous,'auto'", recipe)
                    configs = ast.literal_eval(p.assignment(recipe, 'configs').value)
                    count = 0
                    for filename, pin in configs.items():
                        raw = base64.b64decode(pin['b64'], validate=True)
                        self.assertEqual(p.sha(raw), pin['sha256'])
                        frozen = (REF / 'batch-configs' / filename).read_bytes()
                        self.assertEqual(p.sha(frozen), pin['immutable_source_sha256'])
                        cfg = json.loads(raw)
                        expected = json.loads(frozen)
                        if mode == 'pilot':
                            expected['images'] = expected['images'][:2]
                        self.assertEqual(cfg, expected)
                        self.assertEqual(cfg['model_revision'], 'sha256:' + next(
                            v['sha256'] for k, v in spec['components'].items() if not k.startswith('mmproj')))
                        count += len(cfg['images'])
                    self.assertEqual(count, 2 if mode == 'pilot' else (40 if candidate == 'gsq' else 30))
                    self.assertEqual(receipt['completion_POST_budget'], count * 3)
                    self.assertEqual(receipt['recipe_sha256'], p.sha(recipe.encode()))
                    self.assertLessEqual(sum(receipt['phase_floors_seconds'].values()), 1800)
                    self.assertTrue(receipt['no_execution'])
                    self.assertIn('candidate_configs=cohorts', recipe)
                    self.assertIn("manifest=Path(cohorts[0]['manifest']);cfg=json.loads", recipe)
                    # The immutable client is embedded exactly, not rewritten.
                    raw_client = ast.literal_eval(p.assignment(recipe, 'client_raw').value.args[0])
                    self.assertEqual(base64.b64decode(raw_client), (REF / 'paired_client.py').read_bytes())

    def test_effect_functions_and_cleanup_unchanged(self):
        original = (REF / 'LEXICON-MIMO-40-LAST40-R1.remote.py').read_text()
        recipe, _ = make()
        for name in ('public', 'observe', 'guest', 'gate', 'save'):
            self.assertEqual(p.function_bytes(original, name), p.function_bytes(recipe, name))
        original_finally = next(n for n in ast.parse(original).body if isinstance(n, ast.Try)).finalbody
        candidate_finally = next(n for n in ast.parse(recipe).body if isinstance(n, ast.Try)).finalbody
        self.assertEqual(ast.dump(ast.Module(body=original_finally, type_ignores=[])),
                         ast.dump(ast.Module(body=candidate_finally, type_ignores=[])))

    def test_rejections(self):
        for cohorts, seconds in [(['qwen-gsq-01.json'], 1000),
                                 (['qwen-gsq-01.json'], 299),
                                 (['qwen-gsq-01.json'] * 2, None),
                                 (['qwen-ud-01.json'], None),
                                 (['qwen-gsq-02.json', 'qwen-gsq-01.json'], None),
                                 (['qwen-gsq-%02d.json' % i for i in range(1, 7)], None)]:
            with self.subTest(cohorts=cohorts, seconds=seconds), self.assertRaises(ValueError):
                make(mode='full', cohorts=cohorts, client_seconds=seconds)
        for auto in (None, '', 'AUTO', 'none'):
            with self.assertRaises((ValueError, AttributeError)):
                p.prepare(REF, 'gsq', 'pilot', 'TEST', 'workbay-test.scope', auto)
        for name, unit in [('', 'workbay-test.scope'), ('TEST', ''), ('x;echo', 'workbay-test.scope')]:
            with self.assertRaises(ValueError):
                p.prepare(REF, 'gsq', 'pilot', name, unit, AUTO)

    def test_wrong_hash_model_config_and_duplicate(self):
        plan = json.loads((REF / 'batch-plan.json').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'batch-configs').mkdir()
            for source in (REF / 'batch-configs').glob('qwen-gsq-*.json'):
                (root / 'batch-configs' / source.name).write_bytes(source.read_bytes())
            first = next(r for r in plan['batches'] if r['model'] == 'qwen-gsq')
            path = root / first['config']
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'hash'):
                p.validate_configs(root, plan, 'gsq')
            # Re-pin deliberately in this unit test to reach semantic checks.
            for change, error in [('model', 'model'), ('duplicate', 'duplicate'), ('identity', 'identity')]:
                cfg = json.loads(original)
                if change == 'model':
                    cfg['model_version'] = 'MiMo-wrong'
                elif change == 'duplicate':
                    cfg['images'][1]['image_id'] = cfg['images'][0]['image_id']
                else:
                    cfg['images'][0]['context_pack'] = {'identity': 'forbidden'}
                path.write_text(json.dumps(cfg))
                first['config_sha256'] = p.sha(path.read_bytes())
                with self.assertRaisesRegex(ValueError, error):
                    p.validate_configs(root, plan, 'gsq')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for key in p.PINS:
                (root / key).write_bytes((REF / key).read_bytes())
            (root / p.SOURCES['gsq']).write_text('altered')
            with self.assertRaisesRegex(ValueError, 'source hash'):
                p.prepare(root, 'gsq', 'pilot', 'TEST', 'workbay-test.scope', AUTO)

    def test_cli_receipt_and_no_overwrite_or_missing_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'prepared'
            command = [sys.executable, '-B', str(Path(p.__file__)), '--references', str(REF),
                       '--candidate', 'ud', '--mode', 'pilot', '--name', 'TEST',
                       '--unit', 'workbay-test.scope', '--out', str(out)]
            bad = subprocess.run(command, capture_output=True)
            self.assertEqual(bad.returncode, 2)
            self.assertFalse(out.exists())
            command += ['--actual-previous-auto', AUTO]
            run = subprocess.run(command, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            receipt = json.loads((out / 'prepared-receipt.json').read_bytes())
            raw = (out / 'recipe.remote.py').read_bytes()
            self.assertEqual(receipt['recipe_sha256'], p.sha(raw))
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual(raw, (out / 'recipe.remote.py').read_bytes())


    def test_actual_source_receipt_binds_candidate_config(self):
        for candidate in ('gsq', 'ud'):
            recipe, receipt = make(candidate)
            node = next(n for n in ast.walk(ast.parse(recipe))
                        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Name) and n.value.func.id == 'save'
                        and n.value.args and isinstance(n.value.args[0], ast.Constant)
                        and n.value.args[0].value == 'source-and-input.json')
            pins = ast.literal_eval(p.assignment(recipe, 'configs').value)
            filename, pin = next(iter(pins.items()))
            with tempfile.TemporaryDirectory() as tmp:
                manifest = Path(tmp) / filename
                manifest.write_bytes(base64.b64decode(pin['b64']))
                cfg = json.loads(manifest.read_bytes())
                saves = []
                env = dict(save=lambda *a: saves.append(a), SOURCE='shared-source',
                           workspace=Path('/shared'), manifest=manifest, cfg=cfg,
                           cohorts=[dict(manifest=str(manifest), sha256=pin['sha256'])],
                           hashlib=hashlib)
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-receipt-producer>', 'exec'), env)
                data = saves[0][1]
                self.assertEqual(data['manifest'], str(manifest))
                self.assertEqual(data['input_manifest_sha256'], p.sha(manifest.read_bytes()))
                self.assertEqual(data['model_revision'], cfg['model_revision'])
                self.assertEqual(data['model_version'], cfg['model_version'])
                self.assertTrue(data['pilot_only'])
                self.assertEqual(data['request_budget'], 6)

    def test_actual_post_hook_enforces_budget(self):
        source = (REF / 'paired_client.py').read_text()
        node = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef) and n.name == 'request_observed')
        record = dict(post_attempts=0, request_budget=3)
        env = dict(record=record)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-post-hook>', 'exec'), env)
        request = types.SimpleNamespace(method='POST', url=types.SimpleNamespace(path='/v1/chat/completions'))
        for _ in range(3):
            env['request_observed'](request)
        with self.assertRaises(AssertionError):
            env['request_observed'](request)
        self.assertEqual(record['post_attempts'], 3)
        with self.assertRaises(AssertionError):
            env['request_observed'](types.SimpleNamespace(method='GET', url=request.url))

    def test_qualified_stop_producer_causal_deadline_and_absence(self):
        _, template = p.producer((REF / p.SOURCES['gsq']).read_text())
        functions = [n for n in ast.parse(template).body if isinstance(n, ast.FunctionDef)
                     and n.name in ('stop_original', 'container_absent')]
        for absent, stop_elapsed, accepted in [('error: no such object: acx-gpu-vlm', 100, True),
                                               ('permission denied', 100, False),
                                               ('error: no such object: acx-gpu-vlm', 111, False)]:
            clock = [0]
            calls = []
            def run(args, timeout=15):
                calls.append((args, timeout))
                if args[1] == 'stop':
                    clock[0] += stop_elapsed
                    return types.SimpleNamespace(returncode=0)
                if args[1] == 'show':
                    return types.SimpleNamespace(returncode=0, stdout='ActiveState=inactive\nMainPID=0\nControlGroup=\nJob=\n')
                return types.SimpleNamespace(returncode=1, stderr=absent)
            env = dict(run=run, time=types.SimpleNamespace(monotonic=lambda: clock[0]))
            exec(compile(ast.Module(body=functions, type_ignores=[]), '<qualified-stop-functions>', 'exec'), env)
            if accepted:
                env['stop_original']()
                self.assertEqual(calls[0][1], 110)
            else:
                with self.assertRaises(AssertionError):
                    env['stop_original']()


class ActualObserverTests(unittest.TestCase):
    def run_case(self, outcomes, phase='start'):
        recipe, _ = make()
        node = next(n for n in ast.parse(recipe).body if isinstance(n, ast.FunctionDef) and n.name == 'observe')
        clock = [0]
        calls = []
        saves = []
        def run(*args, **kwargs):
            elapsed, rc, stderr = outcomes.pop(0)
            clock[0] += elapsed
            return types.SimpleNamespace(returncode=rc, stdout='', stderr=stderr)
        def public(args, *unused):
            calls.append(args)
            return '/tmp/mock-observer'
        env = dict(time=types.SimpleNamespace(monotonic=lambda: clock[0]), Path=Path,
                   subprocess=types.SimpleNamespace(run=run), public=public,
                   save=lambda *a: saves.append(a), stage=Path('/mock'), window=Path('/mock-window'))
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-observer>', 'exec'), env)
        error = None
        try:
            env['observe']('owned', phase, 'test', 910)
        except AssertionError as exc:
            error = exc
        return calls, saves, error

    def test_only_exact_readonly_unknown_retry(self):
        unknown = 'receipt deadline: unknown; preserve all files and do not infer stopped/unloaded'
        calls, saves, error = self.run_case([(300, 1, unknown), (10, 0, '')])
        self.assertIsNone(error)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c[0] == 'outdir' for c in calls))
        self.assertEqual(len(saves), 2)
        for phase, message in [('start', 'foreign newer authority'), ('stop', unknown)]:
            calls, saves, error = self.run_case([(1, 1, message)], phase)
            self.assertIsNotNone(error)
            self.assertEqual(len(calls), 1)
        calls, saves, error = self.run_case([(302, 1, unknown)] * 3)
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 3)


class ActualPairedClientTests(unittest.TestCase):
    def exercise(self, failure=None):
        source = (REF / 'paired_client.py').read_text()
        # The actual producer's complete image loop and finalization, with only
        # its service dependencies replaced by local recording doubles.
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.Try))
        writes = []
        persist_calls = []
        class Client:
            def __init__(self, arm):
                self.arm = arm
                self.prompt_sha256 = 'prompt'
            def _weave_messages(self, facts, context, image_part=None):
                if facts == '{"people": []}':
                    return [{'content': 'base' + ('\n\nLEX' if self.arm == 'on' else '')}, {'content': image_part}]
                writes.append((self.arm, facts, context, image_part))
                return ['messages']
            def _timed_chat(self, messages, pass_name, passes, max_tokens):
                passes.append(dict(raw='raw', latency_s=1))
                return 'facts' if pass_name == 'describe_facts' else 'surfaces'
            def _parse_response(self, parse, value):
                if value == 'facts' and failure == 'pass1':
                    raise ValueError('malformed extraction')
                if value == 'surfaces' and failure == 'writing' and self.arm == 'on':
                    raise ValueError('invalid surfaces')
                return dict(title='t', alt='a', caption='c')
            def _redact_response(self, value):
                return value
            def run_configuration(self):
                return {}
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'opaque.jpg'; image.write_bytes(b'pixels')
            cfg = dict(images=[dict(image_id='opaque', path=str(image), sha256=p.sha(b'pixels'))])
            record = dict(items=[])
            env = dict(cfg=cfg, Path=Path, hashlib=hashlib, time=__import__('time'),
                       clients={a: Client(a) for a in ('off', 'on')}, record=record,
                       args=types.SimpleNamespace(dry_run=False),
                       lex=types.SimpleNamespace(render=lambda: 'LEX'),
                       persist=lambda: persist_calls.append(copy.deepcopy(record)),
                       b=types.SimpleNamespace(_data_url=lambda *a: 'same-pixels',
                           _PASS1_SYSTEM_PROMPT='p', _PASS1_MAX_TOKENS=100,
                           _parse_pass1_json=None, _parse_three_surface_json=None,
                           WEAVE_MAX_TOKENS={'standard': 100}, _sum_usage=lambda x: {}))
            for client in env['clients'].values():
                client._pass1_user_text = lambda: 'shared extraction prompt'
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-paired-loop>', 'exec'), env)
            return record, writes, persist_calls

    def test_shared_facts_image_three_posts_and_retained_failures(self):
        good, writes, saves = self.exercise()
        self.assertTrue(good['completed'])
        self.assertEqual(good['valid_pairs'], 1)
        self.assertEqual(len(good['items'][0]['describe']['passes']), 3)
        self.assertEqual(writes[0][1:], writes[1][1:])
        self.assertEqual(writes[0][2], {})
        bad, writes, saves = self.exercise('pass1')
        self.assertTrue(bad['completed'])
        self.assertEqual(bad['valid_pairs'], 0)
        self.assertIn('malformed extraction', bad['items'][0]['error'])
        self.assertEqual(len(bad['items'][0]['shared_extraction']), 1)
        self.assertEqual(writes, [])
        invalid, writes, saves = self.exercise('writing')
        self.assertTrue(invalid['completed'])
        self.assertEqual(invalid['valid_pairs'], 0)
        self.assertEqual(len(invalid['items'][0]['describe']['passes']), 3)
        self.assertIn('invalid surfaces', invalid['items'][0]['error'])
        self.assertEqual(saves[-1], invalid)


if __name__ == '__main__':
    unittest.main()
