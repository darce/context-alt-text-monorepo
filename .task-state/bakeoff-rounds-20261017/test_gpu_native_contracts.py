"""Stdlib producer contracts; never execute a native command or whole recipe."""
import ast
import copy
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import urllib.request

import test_gpu_vllm_maintenance as old

HERE = Path(__file__).parent
NATIVE = json.loads((HERE.parents[1] / 'references/actual-native-producers.json').read_text())
RECIPES = sorted(HERE.glob('*.remote.py'))


def assignment(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def setup_tree(path):
    outer = ast.parse(path.read_text())
    literal = assignment(outer, 'setup_program').value.func.value
    return outer, ast.parse(ast.literal_eval(literal))


def execute(nodes, namespace):
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 '<actual-recipe-phase>', 'exec'), namespace)


class NativeProducer:
    """CompletedProcess/systemctl-show/inspect shapes from the captured producer.

    ControlGroup is explicitly supplied: its absence from the capture must never
    be interpreted as an empty group. A virtual clock models native stop at 90s.
    """
    def __init__(self, stop_rc=1, ready_after=0, stop_seconds=90):
        self.now = 0
        self.stop_rc = stop_rc
        self.ready_after = ready_after
        self.stop_seconds = stop_seconds
        self.http_seconds = 0
        self.inspect_seconds = 0
        self.fields = dict(NATIVE['original_unit'], ControlGroup='')
        self.absence = dict(NATIVE['absence'])
        self.calls = []
        self.launched = None
        self.show_rc = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def run(self, args, *, timeout, **kwargs):
        assert 0 < timeout <= 120
        self.calls.append((list(args), timeout))
        if args[:2] == ['systemctl', 'stop']:
            if args[2] == old.m.ORIGINAL_SERVICE:
                self.now += min(self.stop_seconds, timeout)
                if timeout < self.stop_seconds:
                    raise subprocess.TimeoutExpired(args, timeout)
                return subprocess.CompletedProcess(args, self.stop_rc, '', 'Job failed: timeout.\n')
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[:2] == ['systemctl', 'show']:
            properties = [args[i + 1] for i, arg in enumerate(args) if arg == '-p']
            return subprocess.CompletedProcess(args, self.show_rc,
                ''.join(k + '=' + self.fields[k] + '\n' for k in properties if k in self.fields), '')
        if args == ['docker', 'inspect', 'acx-gpu-vlm']:
            return subprocess.CompletedProcess(args, **self.absence)
        if args[0] == 'systemd-run':
            self.launched = self.now
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[:2] == ['docker', 'inspect']:
            self.now += min(self.inspect_seconds, timeout)
            return subprocess.CompletedProcess(args, 0, json.dumps([{
                'Id': 'candidate-container', 'State': {'Running': True, 'Pid': 456}}]), '')
        if args[0] == '/usr/bin/python3':
            return subprocess.CompletedProcess(args, 0, '{}', '')
        raise AssertionError(args)

    def urlopen(self, request, timeout):
        assert 0 < timeout <= 3
        self.now += min(self.http_seconds, timeout)
        if self.now - self.launched < self.ready_after:
            raise OSError('not ready')
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return Response()


class HelperNativeTests(unittest.TestCase):
    setUp = old.RuntimeTests.setUp

    def test_literal_native_image_identity(self):
        self.fake.image = copy.deepcopy(NATIVE['image_inspect'])
        receipt = self.runtime.prepare()
        actual = NATIVE['image_inspect']['Id']
        self.assertEqual(receipt['candidate_image_id'], actual)
        self.assertEqual(json.loads((self.root / 'before.json').read_text())['candidate_image_id'], actual)
        # A fresh ExecStopPost process must use the sealed residency identity.
        fresh = old.Harness(self.root, old.OP, self.root / 'spec.json',
            runner=self.fake.run, clock=self.fake.clock, sleep=self.fake.sleep,
            http=self.runtime.http, policy=self.policy)
        self.fake.candidate['Image'] = NATIVE['legacy_image_config_id']
        before_calls = len(self.fake.calls)
        with self.assertRaisesRegex(old.m.Refusal, 'foreign candidate'):
            fresh.restore()
        self.assertFalse(any(a[:2] in (['docker', 'stop'], ['systemctl', 'start'])
                             for a, _ in self.fake.calls[before_calls:]))
        self.fake.candidate['Image'] = actual
        # Even a subsequent image-inspect representation change cannot replace
        # the identity already observed/sealed for the running candidate.
        self.fake.image['Id'] = NATIVE['legacy_image_config_id']
        self.assertEqual(fresh.restore()['status'], 'restored')

    def test_image_allowlist_requires_exact_digest(self):
        for image_id in (NATIVE['image_inspect']['Id'], NATIVE['legacy_image_config_id']):
            self.fake.image = dict(Id=image_id, RepoDigests=[old.m.CANDIDATE_REF])
            self.runtime.image()
            self.assertEqual(self.runtime.candidate_image_id, image_id)
            for digests in ([], ['mutable:latest'], [old.m.CANDIDATE_REF, 'foreign@sha256:bad']):
                self.fake.image['RepoDigests'] = digests
                with self.assertRaisesRegex(old.m.Refusal, 'candidate image pin drift'):
                    self.runtime.image()
        self.fake.image = dict(Id=old.m.ORIGINAL_IMAGE, RepoDigests=[old.m.CANDIDATE_REF])
        with self.assertRaisesRegex(old.m.Refusal, 'candidate image pin drift'):
            self.runtime.image()

    def test_delayed_native_stop_failure_and_literal_absence(self):
        native = NativeProducer()
        delegate = self.fake.run
        def run(args, timeout, env=None):
            if args[:3] == ['systemctl', 'stop', old.m.ORIGINAL_SERVICE]:
                result = native.run(args, timeout=timeout)
                self.fake.now = native.now
                self.fake.old = None
                return result
            if args[:3] == ['systemctl', 'show', old.m.ORIGINAL_SERVICE] and 'MainPID' in args:
                return native.run(args, timeout=timeout)
            if args == ['docker', 'inspect', 'acx-gpu-vlm'] and self.fake.old is None:
                return native.run(args, timeout=timeout)
            return delegate(args, timeout, env)
        self.runtime.runner = run
        self.runtime.http = lambda path, key, timeout: (
            (200, {'data': [{'id': old.m.MODEL}]}) if self.fake.now >= 190 else (503, None))
        self.assertEqual(self.runtime.prepare()['status'], 'ready')
        self.assertEqual(native.calls[0][1], 110)
        self.assertEqual(self.fake.now, 190)
        self.assertEqual(self.runtime.restore()['status'], 'restored')

    def test_helper_rejects_unsettled_or_unknown_postconditions(self):
        for key, value in (('ActiveState', 'active'), ('ActiveState', 'deactivating'),
                           ('ActiveState', 'unknown'), ('MainPID', '12'),
                           ('ControlGroup', '/system.slice/acx-gpu-vlm.service'),
                           ('Job', '123'), ('Job', None), ('ControlGroup', None)):
            with self.subTest(key=key, value=value):
                producer = NativeProducer(stop_rc=0)
                if value is None:
                    producer.fields.pop(key)
                else:
                    producer.fields[key] = value
                self.runtime.runner = producer.run
                self.runtime.clock = producer.monotonic
                with self.assertRaisesRegex(old.m.Refusal, 'not quiescent'):
                    self.runtime.stop_original()
                self.assertIsNone(producer.launched)

    def test_helper_stop_phase_is_finite(self):
        producer = NativeProducer(stop_seconds=111)
        self.runtime.runner = producer.run
        self.runtime.clock = producer.monotonic
        with self.assertRaisesRegex(old.m.Refusal, 'command execution failed'):
            self.runtime.stop_original()
        self.assertEqual(producer.now, 110)
        self.assertEqual(len(producer.calls), 1)


class RecipeNativeTests(unittest.TestCase):
    def phase(self, path, producer, root):
        _, tree = setup_tree(path)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        phase = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.Try)))
        # Execute the actual stop/start/readiness phase and its actual recovery
        # handler. Later binary/probe/publication work is outside this contract.
        end = next(i for i, n in enumerate(phase.body) if isinstance(n, ast.Assert)
                   and isinstance(n.test, ast.Compare)
                   and isinstance(n.test.left, ast.Name) and n.test.left.id == 'candidate')
        phase.body = phase.body[:end + 1]
        namespace = dict(subprocess=SimpleNamespace(run=producer.run), json=json,
            time=producer, root=root, key=b'private-fake-key',
            urllib=SimpleNamespace(request=SimpleNamespace(Request=urllib.request.Request,
                                                          urlopen=producer.urlopen)),
            v=dict(candidate_name='candidate', unit='candidate.service', operation=old.OP,
                   image_id=old.m.ORIGINAL_IMAGE), cache=root / 'cache')
        execute(functions + [assignment(tree, 'command'), phase], namespace)
        return namespace

    def test_delayed_terminal_failure_and_literal_absence_accepted(self):
        for path in RECIPES:
            for state in ('failed', 'inactive'):
                with self.subTest(recipe=path.name, state=state), tempfile.TemporaryDirectory() as tmp:
                    producer = NativeProducer(ready_after=100)
                    producer.fields['ActiveState'] = state
                    namespace = self.phase(path, producer, Path(tmp))
                    self.assertEqual(namespace['candidate']['Id'], 'candidate-container')
                    self.assertEqual(producer.calls[0][1], 110)
                    self.assertEqual(producer.launched, 90)
                    self.assertEqual(namespace['deadline'] - producer.launched, 150)
                    launch = next(a for a, _ in producer.calls if a[0] == 'systemd-run')
                    self.assertIn('--property=RuntimeMaxSec=1500', launch)

    def test_unsettled_or_unknown_stop_refuses_launch_and_attempts_restore(self):
        changes = [('ActiveState', 'active'), ('ActiveState', 'deactivating'),
                   ('ActiveState', 'unknown'), ('MainPID', '12'),
                   ('ControlGroup', '/system.slice/acx-gpu-vlm.service'),
                   ('Job', '123'), ('Job', None), ('ControlGroup', None)]
        absences = [dict(returncode=1, stdout='[]\n', stderr=err) for err in (
            'error: no such object: acx-gpu-vlm-other\n',
            'Cannot connect to the Docker daemon\n', 'permission denied\n',
            'unknown response\n')]
        absences += [dict(NATIVE['absence'], returncode=2),
                     dict(returncode=0, stdout='[{}]', stderr='')]
        for path in RECIPES:
            cases = [('field', change) for change in changes]
            cases += [('absence', value) for value in absences] + [('show_rc', 1)]
            for kind, value in cases:
                with self.subTest(recipe=path.name, kind=kind, value=value), tempfile.TemporaryDirectory() as tmp:
                    producer = NativeProducer(stop_rc=0)
                    if kind == 'field':
                        key, entry = value
                        if entry is None:
                            producer.fields.pop(key)
                        else:
                            producer.fields[key] = entry
                    elif kind == 'absence':
                        producer.absence = value
                    else:
                        producer.show_rc = value
                    with self.assertRaises((AssertionError, RuntimeError)):
                        self.phase(path, producer, Path(tmp))
                    self.assertIsNone(producer.launched)
                    self.assertTrue(any(a[0] == '/usr/bin/python3' for a, _ in producer.calls))

    def test_readiness_is_finite_and_outer_bounds_are_executed(self):
        for path in RECIPES:
            with self.subTest(recipe=path.name), tempfile.TemporaryDirectory() as tmp:
                producer = NativeProducer(ready_after=1000)
                producer.http_seconds = 3
                producer.inspect_seconds = 5
                with self.assertRaisesRegex(AssertionError, 'Candidate readiness refused'):
                    self.phase(path, producer, Path(tmp))
                self.assertEqual(producer.now - producer.launched, 150)
                outer, _ = setup_tree(path)
                command = next(n for n in ast.walk(outer) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'command' for t in n.targets)
                    and 'setup-' in ast.unparse(n.value))
                calls = []
                def guest(command, timeout):
                    calls.append((shlex.split(command), timeout))
                    return '{}'
                execute([command, assignment(outer, 'serving')], dict(
                    operation=old.OP, setup_program='# inert', shlex=shlex, json=json, guest=guest))
                self.assertIn('--property=RuntimeMaxSec=540', calls[0][0])
                self.assertEqual(calls[0][1], 570)
                self.assertEqual(path.read_text().count('__PREVIOUS_AUTO__'), 1)

    def test_stop_timeout_is_finite_and_retains_recovery(self):
        for path in RECIPES:
            with self.subTest(recipe=path.name), tempfile.TemporaryDirectory() as tmp:
                producer = NativeProducer(stop_seconds=111)
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.phase(path, producer, Path(tmp))
                self.assertEqual(producer.now, 110)
                self.assertIsNone(producer.launched)
                self.assertTrue(any(a[0] == '/usr/bin/python3' for a, _ in producer.calls))


if __name__ == '__main__':
    unittest.main()
