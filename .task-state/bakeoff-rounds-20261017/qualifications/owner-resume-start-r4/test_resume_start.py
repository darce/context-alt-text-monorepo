#!/usr/bin/env python3
"""UNIT CONTROLS ONLY: complete CLI dispatch and unchanged custody refusal seams.

CLI dependencies explicitly substituted: euid assertion (0), custody bootstrap,
directory/window descriptors, and intent seal (raises DispatchReached before any
guardian launch). This never proves root, sudo, publication, or a live operation.
Guard/guardian refusal controls use the complete unchanged custody module, actual
author credentials, sealed author-owned temporary receipts and real local fences.
No writer is supplied: every guardian case must refuse before writer allocation.
No app modules, native writer source, network, service or deployed state is used.
Run in a bounded parent: timeout 30s python3 -B test_resume_start.py [--source DIR].
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).absolute().parent
SOURCE = HERE
WINDOW_ID = '223eb2de-b63a-4b19-a31e-a34d07a8e187'
PREVIOUS = 'e82a6426-4b05-4aad-8b53-92ec2ac2c9d9'
ACTOR = 'ubuntu:QWEN-OWNER-ADMISSION:capacity-only:' + WINDOW_ID


def load_custody():
    spec = importlib.util.spec_from_file_location('unit_exact_custody', SOURCE / 'owner-custody.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DispatchReached(Exception):
    pass


def dispatch(mode, predecessor):
    """Execute every byte of the CLI; stop at intent seal, before Popen."""
    c = load_custody()
    raw = (SOURCE / 'owner-window.py').read_bytes()
    with tempfile.TemporaryDirectory(prefix='resume-cli-unit.') as root:
        window = dict(id=WINDOW_ID, path=root, procedure=str(SOURCE))
        plan = {}
        fake = types.ModuleType('owner_custody')
        fake.check = c.check
        fake.Paths = c.Paths
        fake.directory = lambda *a, **k: os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        fake.read_at = lambda *a, **k: (SOURCE / 'owner-custody.py').read_bytes()
        fake.validate_window = lambda *a: (os.open(root, os.O_RDONLY | os.O_DIRECTORY), window)
        fake.subdir = lambda fd, *a, **k: os.dup(fd)

        def intent_seal(fd, name, value):
            os.close(fd)  # operation has not entered its own descriptor finally yet
            c.check(name == 'intent.json', 'unexpected dispatch seam')
            plan.update(value)
            raise DispatchReached()

        fake.seal = intent_seal

        class Loader:
            def create_module(self, spec):
                return fake

            def exec_module(self, module):
                pass

        spec = importlib.util.spec_from_loader('owner_custody', Loader())
        output = io.StringIO()
        with patch.object(os, 'geteuid', return_value=0), \
                patch.object(importlib.util, 'spec_from_file_location', return_value=spec), \
                patch.object(sys, 'argv', [str(SOURCE / 'owner-window.py'), mode, root, predecessor]), \
                patch('subprocess.Popen', side_effect=AssertionError('unit must never launch guardian')), \
                contextlib.redirect_stdout(output):
            try:
                exec(compile(raw, str(SOURCE / 'owner-window.py'), 'exec'),
                     {'__name__': '__main__', '__file__': str(SOURCE / 'owner-window.py')})
            except DispatchReached:
                result = dict(outcome='dispatch', action=plan['action'], previous=plan['previous'])
            except RuntimeError as exc:
                result = dict(outcome='refused', error=str(exc))
            else:
                raise AssertionError('CLI unexpectedly completed past intent seam')
        assert not output.getvalue(), 'no publication/success stdout is allowed at unit seam'
        return result


def payload():
    return dict(schema_version=1, sequence=4, action='auto', requested_at='2026-10-18T17:56:00Z',
                expires_at='2026-10-18T18:06:00Z', ttl_seconds=600, requested_by=ACTOR,
                nonce='16e62c2d-2a5f-46d4-8178-a636225c34f3')


def idle_view(previous):
    publication = {k: previous[k] for k in ('action', 'requested_at', 'expires_at',
                                           'ttl_seconds', 'requested_by', 'sequence')}
    return dict(authority=dict(highest_sequence=4, rejected_sequences=[],
                               intents={previous['nonce']: dict(sequence=4, publication=publication)}),
                publications={'unit/prod/gpu-intent.json': copy.deepcopy(previous)},
                loads=[dict(written_at=time.time(), queue_depth=0, in_flight=0,
                            batch_in_progress=False, revision=1) for _ in range(4)], deferred=None)


class ResumeControls(unittest.TestCase):
    def test_first_use_start(self):
        self.assertEqual(dispatch('start', '-'), dict(outcome='dispatch', action='start', previous=None))

    def test_resumed_start(self):
        result = dispatch('start', PREVIOUS)
        print('CAUSAL resumed START:', json.dumps(result, sort_keys=True), flush=True)
        self.assertEqual(result, dict(outcome='dispatch', action='start', previous=PREVIOUS),
                         'explicit predecessor must reach unchanged operation dispatch')

    def test_stop_auto_require_predecessor(self):
        for mode in ('stop', 'auto'):
            with self.subTest(mode=mode):
                self.assertEqual(dispatch(mode, '-'),
                                 dict(outcome='refused', error='explicit previous operation required'))
                self.assertEqual(dispatch(mode, PREVIOUS),
                                 dict(outcome='dispatch', action=mode, previous=PREVIOUS))

    def test_unchanged_guard_positive_controls(self):
        c = load_custody()
        p = payload()
        self.assertEqual(c.guard(idle_view(p), p, {PREVIOUS: p}, ACTOR, 'start'), 4)
        v = dict(authority=dict(highest_sequence=0, intents={}), publications={}, loads=idle_view(p)['loads'], deferred=None)
        self.assertEqual(c.guard(v, None, {}, ACTOR, 'start'), 0)
        with self.assertRaisesRegex(RuntimeError, 'first-use changed'):
            c.guard(idle_view(p), None, {}, ACTOR, 'start')

    def test_unchanged_guard_refusal_matrix(self):
        c = load_custody()
        for name, reason in (
                ('foreign-predecessor', 'other window'),
                ('noncustodied-predecessor', 'previous lacks immutable candidate custody'),
                ('newer-authority', 'newer authority'),
                ('newer-record', 'newer authority record'),
                ('unpersisted-predecessor', 'previous publication is not currently persisted'),
                ('foreign-publication', 'foreign publication'),
                ('rejected-authority', 'authority rejection history'),
                ('unknown-authority', 'unknown authority'),
                ('conflicting-authority', 'conflicting authority'),
                ('foreign-deferred', 'foreign deferred STOP'),
                ('busy-load', 'work/demand'),
                ('unknown-load', 'unknown load object'),
                ('unknown-load-inventory', 'unknown required load inventory'),
                ('unknown-load-counter', 'unknown load counter'),
                ('unknown-demand', 'unknown lease demand'),
                ('stale-load', 'unknown/stale load')):
            with self.subTest(case=name):
                p = payload()
                v = idle_view(p)
                known = {PREVIOUS: p}
                if name == 'foreign-predecessor': p['requested_by'] = 'foreign-window'
                elif name == 'noncustodied-predecessor': known = {}
                elif name == 'newer-authority': v['authority']['highest_sequence'] = 5
                elif name == 'newer-record': v['authority']['intents']['newer'] = dict(sequence=5)
                elif name == 'unpersisted-predecessor': v['publications'] = {}
                elif name == 'foreign-publication': v['publications']['foreign'] = dict(p, requested_by='foreign')
                elif name == 'rejected-authority': v['authority']['rejected_sequences'] = [3]
                elif name == 'unknown-authority': v['authority']['highest_sequence'] = None
                elif name == 'conflicting-authority': v['authority']['intents'][p['nonce']]['publication']['ttl_seconds'] = 1
                elif name == 'foreign-deferred': v['deferred'] = dict(nonce='foreign', sequence=4)
                elif name == 'busy-load': v['loads'][0]['in_flight'] = 1
                elif name == 'unknown-load': v['loads'][0] = None
                elif name == 'unknown-load-inventory': v['loads'] = []
                elif name == 'unknown-load-counter': v['loads'][0]['queue_depth'] = None
                elif name == 'unknown-demand': v['loads'][0]['lease_demand'] = None
                elif name == 'stale-load': v['loads'][0]['written_at'] -= 121
                with self.assertRaisesRegex(RuntimeError, reason):
                    c.guard(v, p, known, ACTOR, 'start')
                print('UNIT guard refused:', name, '/', reason)

    def test_unchanged_guardian_resolution_refusals(self):
        """Actual author UID, sealed temp receipts/fences; no writer or live paths."""
        for name, prior, outcome, reason in (
                ('unknown', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'published', 'KeyError'),
                ('malformed', '../not-owned', 'published', 'KeyError'),
                ('unpublished', PREVIOUS, 'not-published', 'previous operation unresolved'),
                ('unresolved', PREVIOUS, None, 'FileNotFoundError'),
                ('busy-marker', PREVIOUS, 'published', 'foreign activity marker')):
            with self.subTest(case=name), tempfile.TemporaryDirectory(prefix='resume-guardian-unit.') as root:
                c = load_custody()
                base = Path(root)
                for d in ('window', 'runtime', 'store', 'markers'):
                    (base / d).mkdir(mode=0o700)
                wfd = c.directory(base / 'window', os.geteuid())
                ops = c.subdir(wfd, 'ops', create=True)
                old = c.subdir(ops, PREVIOUS, create=True)
                p = payload()
                c.seal(old, 'candidate.json', p)
                if outcome is not None:
                    c.seal(old, 'result.json', dict(outcome=outcome))
                os.close(old)
                op = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
                ofd = c.subdir(ops, op, create=True)
                os.close(ops)
                paths = c.Paths(base / 'runtime', base / 'store', base / 'store/lifecycle.lock', base / 'markers')
                v = idle_view(p)
                (base / 'store/intent-authority.json').write_text(json.dumps(v['authority']))
                for env in c.ENVS:
                    target = base / 'runtime' / env
                    target.mkdir(mode=0o700)
                    (target / 'describe-load.json').write_text(json.dumps(v['loads'][0]))
                (base / 'runtime/prod/gpu-intent.json').write_text(json.dumps(p))
                if name == 'busy-marker': (base / 'markers/activity.lock').touch()
                before = c.view(paths, 'start')
                signals = {s: signal.getsignal(s) for s in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
                try:
                    c.guardian(wfd, ofd, paths, None, dict(id=op, action='start', previous=prior),
                               dict(path=str(base / 'window'), id=WINDOW_ID))
                    result = c.load_json(ofd, 'result.json')
                    self.assertEqual(result['outcome'], 'refused')
                    self.assertIn(reason, result['error'])
                    self.assertEqual(c.view(paths, 'start'), before)
                    self.assertNotIn('candidate.json', os.listdir(ofd))
                    self.assertNotIn('writer-started.json', os.listdir(ofd))
                    print('UNIT guardian refused:', name, '/', result['error'])
                finally:
                    for s, handler in signals.items(): signal.signal(s, handler)
                    os.close(ofd)
                    os.close(wfd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE)
    args = parser.parse_args()
    SOURCE = args.source.absolute()
    print(json.dumps(dict(qualification='UNIT_ONLY', actual_euid=os.geteuid(),
                          cli_euid_dependency_substitution=0, source=str(SOURCE),
                          pins={n: hashlib.sha256((SOURCE / n).read_bytes()).hexdigest()
                                for n in ('owner-window.py', 'owner-custody.py')})), flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ResumeControls)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
