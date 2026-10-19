#!/usr/bin/env python3
"""Independent UNIT_ONLY controls; never Root/native qualification.

Run: timeout 55s python3 -B test_window_checkpoint.py [--source DIR]
Only checkpoint(wfd, paths, window) is a contracted Python API. Fixtures use
actual current-UID custody, real filesystem receipts and real private fences.
No writer, subprocess, installed path or service is used. Procedure positives
explicitly substitute current-UID ownership for root in directory/proof readers
on private fixtures only; all other guards and read-only CLI dispatch are real.
An unsubstituted control requires refusal of the actual unprivileged stage.
Controller-role units explicitly substitute only UID/GID in kernel stat results
for tracked private inodes. Modes, links, identity, bytes and still-named checks
remain real. Native UID1001 metadata is proved only by the separate Root driver.
"""
import argparse
import ast
import contextlib
import errno
import io
import sys
from unittest.mock import patch
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
import uuid

HERE = Path(__file__).absolute().parent
SOURCE = HERE
WINDOW = '223eb2de-b63a-4b19-a31e-a34d07a8e187'
ACTOR = 'ubuntu:QWEN-OWNER-ADMISSION:capacity-only:' + WINDOW
STAGE_SCRIPTS = ('owner-window.py', 'owner-custody.py', 'observe.py',
                 'capacity-read.sh', 'guest-read.sh', 'root-flow.sh', 'final-stop.sh')


def load():
    spec = importlib.util.spec_from_file_location('checkpoint_under_test', SOURCE / 'owner-custody.py')
    c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c)
    return c


def inventory(base):
    """Byte/identity snapshot; reads never follow a symlink."""
    result = {}
    for p in sorted(base.rglob('*')):
        s = p.lstat()
        value = os.readlink(p) if stat.S_ISLNK(s.st_mode) else (
            p.read_bytes() if stat.S_ISREG(s.st_mode) else None)
        result[str(p.relative_to(base))] = (s.st_dev, s.st_ino, s.st_uid,
                                            s.st_mode, s.st_nlink, s.st_gid, value)
    return result


class Checkpoint(unittest.TestCase):
    def setUp(self):
        self.c = load()
        self.tmp = tempfile.TemporaryDirectory(prefix='checkpoint-unit.')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for name in ('window', 'runtime', 'store', 'markers', 'procedure'):
            (self.base / name).mkdir(mode=0o700)
        self.w = dict(id=WINDOW, path=str(self.base / 'window'), procedure=str(self.base / 'procedure'))
        self.fd = self.c.directory(self.w['path'], os.geteuid())
        self.addCleanup(os.close, self.fd)
        self.c.seal(self.fd, 'window.json', self.w)
        os.close(self.c.subdir(self.fd, 'ops', create=True))
        self.paths = self.c.Paths(self.base / 'runtime', self.base / 'store',
                                  self.base / 'store/lifecycle.lock', self.base / 'markers')
        for env in self.c.ENVS:
            p = self.paths.runtime / env
            p.mkdir(mode=0o700)
            (p / 'describe-load.json').write_text(json.dumps(dict(
                written_at=time.time(), queue_depth=0, in_flight=0, batch_in_progress=False)))
        self.candidates = {}
        self.ids = []
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        # An absent PID is verified in this namespace; no process is launched.
        self.assertFalse(Path('/proc/1073741824').exists())
        self.dead = dict(pid=1073741824, boot=boot, start='0')
        for n in range(33):
            op = str(uuid.UUID(int=n + 1))
            self.ids.append(op)
            f = self.c.subdir(self.fd, 'ops')
            ofd = self.c.subdir(f, op, create=True)
            os.close(f)
            try:
                self.c.seal(ofd, 'intent.json', dict(id=op, window=WINDOW, action='auto',
                                                   previous=self.ids[n-1] if n else None))
                self.c.seal(ofd, 'guardian.json', self.dead)
                if n < 32:
                    p = dict(schema_version=1, sequence=n+1, action='auto',
                             requested_at='2026-10-18T17:56:00Z', expires_at='2026-10-18T18:06:00Z',
                             ttl_seconds=600, requested_by=ACTOR, nonce=str(uuid.UUID(int=100+n)))
                    self.candidates[op] = p
                    for name in ('candidate.json', 'publication.json'):
                        self.c.seal(ofd, name, p)
                    self.c.seal(ofd, 'writer-started.json', dict(self.dead, operation=op, window=WINDOW))
                    self.c.seal(ofd, 'writer-stopped.json', dict(wait_status=0, native_reaped=True,
                                                               native_publish_completed=True))
                    self.c.seal(ofd, 'preflight.json', dict(
                        authority=dict(highest_sequence=n, rejected_sequences=[], intents={}),
                        publications={}, loads=[], deferred=None))
                result = dict(outcome='published' if n < 32 else 'refused',
                              operation=op, window=WINDOW)
                if n < 32:
                    result['writer_wait_status'] = 0
                self.c.seal(ofd, 'result.json', result)
            finally:
                os.close(ofd)
        self.current = self.ids[31]
        # Two currently persisted candidates must survive, not just the maximum.
        for path, op in ((self.paths.target, self.current),
                         (self.paths.runtime / 'dev/gpu-intent.json', self.ids[30])):
            path.write_text(json.dumps(self.candidates[op]))
        p = self.candidates[self.current]
        self.authority = dict(highest_sequence=32, rejected_sequences=[], intents={p['nonce']: dict(
            sequence=32, publication={k:p[k] for k in ('action', 'requested_at', 'expires_at',
                                                       'ttl_seconds', 'requested_by', 'sequence')})})
        (self.paths.store / 'intent-authority.json').write_text(json.dumps(self.authority))
        # Provision real fences before snapshots; refusal may acquire but may not
        # create unrelated history/authority mutations.
        for path in [Path(self.w['path']) / 'window.lock'] + self.paths.fences('start'):
            self.c.unlock([self.c.lock_path(path, time.monotonic()+1)])

    def checkpoint(self):
        self.assertTrue(callable(getattr(self.c, 'checkpoint', None)),
                        'missing contracted checkpoint(wfd, paths, window) recovery API')
        return self.c.checkpoint(self.fd, self.paths, self.w)

    def assert_valid_baseline(self):
        """Prove every operation and current-state guard before damaging one."""
        records = {}
        for op in self.ids:
            fd = self.c.directory(Path(self.w['path']) / 'ops' / op, os.geteuid())
            try:
                records[op] = self.c.operation_snapshot(fd, op, self.w)
            finally:
                os.close(fd)
        state, _ = self.c.checkpoint_view(self.paths)
        self.assertEqual(self.c.checkpoint_selection(records, state, self.w),
                         (self.current, sorted((self.current, self.ids[30]))))

    def rewrite(self, path, value):
        if path.exists():
            path.chmod(0o600)
        path.write_text(json.dumps(value))
        path.chmod(0o400)

    def op(self, n, name):
        return Path(self.w['path']) / 'ops' / self.ids[n] / name

    def test_causal_cap_then_recovery_preserves_all_proof_bytes(self):
        with self.assertRaisesRegex(RuntimeError, 'operation budget exhausted'):
            self.c.known_candidates(self.fd)
        self.assertEqual(self.c.guard(self.c.view(self.paths, 'start'),
                                      self.candidates[self.current], self.candidates, ACTOR, 'start'), 32)
        before = inventory(Path(self.w['path']) / 'ops')
        state = self.c.view(self.paths, 'start')
        receipt = self.checkpoint()
        self.assert_checkpoint_result(before, state, receipt)

    def assert_checkpoint_result(self, before, state, receipt):
        self.assertIsInstance(receipt, dict, 'public receipt must be JSON serializable')
        json.dumps(receipt)
        self.assertEqual(receipt['schema'], 'acx-owner-window-checkpoint-receipt/v1')
        self.assertIs(receipt['durable'], True)
        self.assertEqual((receipt['window_id'], receipt['window_path'], receipt['previous']),
                         (WINDOW, self.w['path'], self.current))
        self.assertEqual(set(receipt['retained']), {self.current, self.ids[30]})
        self.assertEqual(set(receipt['archived']), set(self.ids)-set(receipt['retained']))
        self.assertEqual(self.c.view(self.paths, 'start'), state)
        known = self.c.known_candidates(self.fd)
        for op in (self.current, self.ids[30]):
            self.assertEqual(known[op], self.candidates[op])
        self.assertEqual(self.c.guard(state, known[self.current], known, ACTOR, 'start'), 32)
        window = Path(self.w['path'])
        transaction = window / 'checkpoints' / receipt['checkpoint_id']
        manifest = transaction / 'manifest.json'
        manifest_raw = manifest.read_bytes()
        self.assertEqual(hashlib.sha256(manifest_raw).hexdigest(), receipt['manifest_sha256'])
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o400)
        self.assertEqual(manifest.stat().st_nlink, 1)
        self.assertEqual(json.loads((transaction / 'complete.json').read_bytes()), receipt)
        self.assertFalse((window / 'checkpoints/pending.json').exists())
        active, archived = inventory(window / 'ops'), inventory(transaction / 'ops')
        self.assertEqual(set(active) | set(archived), set(before))
        self.assertFalse(set(active) & set(archived))
        for rel, proof in before.items():
            destination = active if Path(rel).parts[0] in receipt['retained'] else archived
            # Renames must preserve original directory/file inodes, modes,
            # ownership, link counts and every proof byte, not merely hashes.
            self.assertEqual(destination[rel], proof, 'lost original custody: '+rel)
            if stat.S_ISREG(proof[3]):
                self.assertIn(hashlib.sha256(proof[-1]).hexdigest(), manifest_raw.decode())

    def test_interrupted_checkpoint_recovers_same_manifest(self):
        before = inventory(Path(self.w['path']) / 'ops')
        state = self.c.view(self.paths, 'start')
        rename = os.rename
        moved = []

        def interrupt(src, dst, **kwargs):
            if moved:
                raise InterruptedError('unit interruption after first archive rename')
            rename(src, dst, **kwargs)
            moved.append(src)

        with patch.object(self.c.os, 'rename', side_effect=interrupt):
            with self.assertRaisesRegex(InterruptedError, 'unit interruption'):
                self.checkpoint()
        window = Path(self.w['path'])
        pending = json.loads((window / 'checkpoints/pending.json').read_bytes())
        transaction = window / 'checkpoints' / pending['id']
        self.assertEqual(len(list((window / 'ops').iterdir())), 32)
        self.assertEqual([p.name for p in (transaction / 'ops').iterdir()], moved)
        with self.assertRaisesRegex(RuntimeError, 'checkpoint pending'):
            self.c.known_candidates(self.fd)

        # Changed original bytes and changed actual resource state each refuse
        # recovery without another move. Restore only our private fixture bytes.
        proof = transaction / 'ops' / moved[0] / 'guardian.json'
        original = proof.read_bytes()
        proof.chmod(0o600); proof.write_bytes(original+b' '); proof.chmod(0o400)
        damaged = inventory(self.base)
        with self.assertRaisesRegex(RuntimeError, 'checkpoint original bytes/identity changed'):
            self.checkpoint()
        self.assertEqual(inventory(self.base), damaged)
        proof.chmod(0o600); proof.write_bytes(original); proof.chmod(0o400)
        authority = self.paths.store / 'intent-authority.json'
        original = authority.read_bytes()
        authority.write_text(json.dumps(dict(self.authority, highest_sequence=33)))
        damaged = inventory(self.base)
        with self.assertRaisesRegex(RuntimeError, 'checkpoint current state changed'):
            self.checkpoint()
        self.assertEqual(inventory(self.base), damaged)
        authority.write_bytes(original)

        receipt = self.checkpoint()
        self.assertEqual(receipt['checkpoint_id'], pending['id'])
        self.assertEqual(receipt['manifest_sha256'], pending['manifest_sha256'])
        self.assertEqual(set(p.name for p in (window / 'checkpoints').iterdir()), {pending['id']})
        self.assert_checkpoint_result(before, state, receipt)

    def test_ordinary_budget_stays_32(self):
        with self.assertRaisesRegex(RuntimeError, 'operation budget exhausted'):
            self.c.known_candidates(self.fd)
        self.op(32, 'result.json').unlink()
        # Removing an individual proof must not bypass inventory cap.
        with self.assertRaisesRegex(RuntimeError, 'operation budget exhausted'):
            self.c.known_candidates(self.fd)

    def test_paths_declared_controller_contract(self):
        values = (self.paths.runtime, self.paths.store, self.paths.lifecycle, self.paths.markers)
        now = lambda: 123
        defaults = self.c.Paths(*values, None, None, now)
        self.assertIs(defaults.now, now, 'existing now positional argument must remain compatible')
        self.assertEqual((defaults.controller_uid, defaults.controller_gid),
                         (os.geteuid(), os.getegid()))
        declared = self.c.Paths(*values, 10001, 10001, now,
                                controller_uid=1001, controller_gid=1001)
        self.assertEqual((declared.controller_uid, declared.controller_gid,
                          declared.writer_uid, declared.writer_gid), (1001, 1001, 10001, 10001))
        for name in ('controller_uid', 'controller_gid'):
            for value in (True, '1001', 1001.0):
                with self.subTest(field=name, value=repr(value)):
                    with self.assertRaises((RuntimeError, TypeError, ValueError)):
                        self.c.Paths(*values, **{name: value})

    @contextlib.contextmanager
    def controller_role_unit_fixture(self):
        """UNIT_ONLY UID/GID mapping; never a kernel ownership or Root claim."""
        paths = self.c.Paths(self.paths.runtime, self.paths.store, self.paths.lifecycle,
                             self.paths.markers, 10001, 10001,
                             controller_uid=1001, controller_gid=1001)
        durable = paths.store / 'intents/prod/gpu-intent.json'
        durable.parent.mkdir(parents=True, mode=0o755)
        durable.parent.parent.chmod(0o755)
        durable.parent.chmod(0o755)
        durable.write_bytes(paths.target.read_bytes())
        roles = {paths.store: (1001, 1001), durable.parent.parent: (1001, 1001),
                 durable.parent: (1001, 1001), durable: (1001, 1001),
                 paths.lifecycle: (1001, 1001),
                 paths.store / '.intent-authority.json.lock': (1001, 1001),
                 paths.store / 'intent-authority.json': (1001, 1001)}
        paths.lifecycle.chmod(0o600)
        for path in (durable, paths.store / 'intent-authority.json'):
            path.chmod(0o660)
        for env in self.c.ENVS:
            target = paths.runtime / env
            target.chmod(0o770)
            roles[target] = (os.geteuid(), 10001)
            roles[target / 'gpu-intent.json.lock'] = (os.geteuid(), 10001)
            publication = target / 'gpu-intent.json'
            if publication.exists():
                publication.chmod(0o660)
                roles[publication] = (10001, 10001)
        native_stat, native_fstat = os.stat, os.fstat
        mapped = {(s.st_dev, s.st_ino): roles[p] for p in roles for s in [native_stat(p)]}

        class RoleStat:
            def __init__(self, actual, role):
                self.actual = actual
                self.st_uid, self.st_gid = role

            def __getattr__(self, name):
                return getattr(self.actual, name)

        def substitute(s):
            role = mapped.get((s.st_dev, s.st_ino))
            return s if role is None else RoleStat(s, role)

        print('UNIT_ONLY: controller UID/GID stat substitution on private inodes; no Root proof', flush=True)
        with patch.object(self.c.os, 'stat', side_effect=lambda *a, **k: substitute(native_stat(*a, **k))), \
                patch.object(self.c.os, 'fstat', side_effect=lambda *a, **k: substitute(native_fstat(*a, **k))):
            yield paths, mapped, native_stat

    def test_declared_controller_metadata_acceptance_unit_only(self):
        with self.controller_role_unit_fixture() as (paths, _, _):
            self.paths = paths
            self.assertEqual(stat.S_IMODE(paths.lifecycle.stat().st_mode), 0o600)
            self.assertEqual((paths.lifecycle.stat().st_uid, paths.lifecycle.stat().st_gid), (1001, 1001))
            self.assert_valid_baseline()
            resources = inventory(paths.store), inventory(paths.runtime)
            before = inventory(Path(self.w['path']) / 'ops')
            state = self.c.view(paths, 'start')
            self.assert_checkpoint_result(before, state, self.checkpoint())
            self.assertEqual((inventory(paths.store), inventory(paths.runtime)), resources)

    def test_declared_controller_metadata_refusals_unit_only(self):
        # First prove the complete positive selection with these exact roles.
        # Damage one real private mode/link, or one explicitly mapped UID/GID.
        with self.controller_role_unit_fixture() as (paths, mapped, native_stat):
            self.paths = paths
            self.assert_valid_baseline()
            cases = [('lifecycle-owner', paths.lifecycle, (1003, 1001), None),
                     ('lifecycle-group', paths.lifecycle, (1001, 1002), None),
                     ('lifecycle-mode', paths.lifecycle, None, 0o640),
                     ('authority-fence-owner', paths.store / '.intent-authority.json.lock', (10001, 10001), None),
                     ('authority-fence-mode', paths.store / '.intent-authority.json.lock', None, 0o600),
                     ('store-owner', paths.store, (1003, 1001), None),
                     ('store-mode', paths.store, None, 0o770),
                     ('authority-state-owner', paths.store / 'intent-authority.json', (10001, 10001), None),
                     ('authority-state-group', paths.store / 'intent-authority.json', (1001, 10001), None),
                     ('durable-mode', paths.store / 'intents/prod/gpu-intent.json', None, 0o666),
                     ('runtime-fence-hardlink', paths.runtime / 'prod/gpu-intent.json.lock', None, None)]
            for name, path, role, mode in cases:
                with self.subTest(case=name):
                    self.assert_valid_baseline()
                    s = native_stat(path)
                    key = (s.st_dev, s.st_ino)
                    original_role = mapped[key]
                    extra = self.base / 'extra-fence-link'
                    if role is not None: mapped[key] = role
                    if mode is not None: path.chmod(mode)
                    if name == 'runtime-fence-hardlink': os.link(path, extra)
                    before = inventory(self.base)
                    try:
                        with self.assertRaisesRegex(RuntimeError, 'checkpoint fence|resource directory|resource file'):
                            self.checkpoint()
                        self.assertEqual(inventory(self.base), before, name+' mutated custody/state')
                        self.assertFalse((Path(self.w['path']) / 'checkpoints').exists())
                    finally:
                        mapped[key] = original_role
                        if mode is not None: path.chmod(stat.S_IMODE(s.st_mode))
                        extra.unlink(missing_ok=True)

    def test_fixed_fifth_fences_and_start_stop_load_guard(self):
        expected = ('dev', 'dev-fir', 'prod', 'staging', 'dev-auraface')
        self.assertEqual(self.c.ENVS, expected, 'all five fixed producers are required in order')
        fifth = self.paths.runtime / 'dev-auraface'
        for action in ('auto', 'start', 'stop'):
            fences = self.paths.fences(action)
            self.assertEqual(fences, [self.paths.lifecycle] + [
                self.paths.runtime / env / 'gpu-intent.json.lock' for env in expected] + ([] if action == 'auto' else [
                self.paths.runtime / env / 'describe-load.json.lock' for env in expected]) + [
                self.paths.store / '.intent-authority.json.lock'])
        load = fifth / 'describe-load.json'
        original = load.read_bytes()
        value = json.loads(original)
        load.write_text(json.dumps(dict(value, lease_demand=1)))
        before = inventory(self.base)
        for action in ('start', 'stop'):
            state = self.c.view(self.paths, action)
            self.assertEqual(len(state['loads']), 5)
            self.assertEqual(state['loads'][-1]['lease_demand'], 1)
            with self.assertRaisesRegex(RuntimeError, 'work/demand'):
                self.c.guard(state, self.candidates[self.current], self.candidates, ACTOR, action)
        self.assertEqual(inventory(self.base), before)
        load.write_bytes(original)
        for action in ('start', 'stop'):
            self.assertEqual(self.c.guard(self.c.view(self.paths, action), self.candidates[self.current],
                                          self.candidates, ACTOR, action), 32)
        self.assert_valid_baseline()
        before = inventory(Path(self.w['path']) / 'ops')
        state = self.c.view(self.paths, 'start')
        self.assert_checkpoint_result(before, state, self.checkpoint())

    def test_missing_fifth_intent_fence_refuses_checkpoint_read_only(self):
        fifth = self.paths.runtime / 'dev-auraface'
        # Explicit fixture addition makes the old four-environment source RED;
        # never derive the asserted fifth producer from the implementation.
        if not fifth.exists():
            fifth.mkdir(mode=0o700)
        fence = fifth / 'gpu-intent.json.lock'
        self.assertIn(fence, self.paths.fences('auto'), 'checkpoint must fence the actual fifth producer')
        fence.unlink(missing_ok=True)
        before = inventory(self.base)
        with self.assertRaises(FileNotFoundError) as caught:
            self.checkpoint()
        self.assertEqual(Path(caught.exception.filename), fence)
        self.assertEqual(inventory(self.base), before)
        self.c.unlock([self.c.lock_path(fence, time.monotonic()+1)])
        self.assert_valid_baseline()
        before = inventory(Path(self.w['path']) / 'ops')
        state = self.c.view(self.paths, 'start')
        self.assert_checkpoint_result(before, state, self.checkpoint())

    def test_refusal_matrix_is_read_only(self):
        cases = dict(over33='checkpoint operation budget exhausted',
                     pending='pending or unexpected operation inventory',
                     unknown='pending/UNKNOWN operation result',
                     unreaped='unproven writer reap',
                     **{'wait-status': 'writer wait status conflict',
                        'live-writer': 'live guardian/writer',
                        'live-guardian': 'live guardian/writer'},
                     foreign='foreign publication', newer='newer authority',
                     mutable='unsafe proof file: candidate.json', symlink=None,
                     hardlink='unsafe proof file: candidate.json',
                     incomplete='incomplete publication proof',
                     preflight='incomplete publication proof')
        # Each case gets independent real filesystem custody.
        for case in cases:
            with self.subTest(case=case):
                other = Checkpoint('test_ordinary_budget_stays_32')
                other.setUp()
                try:
                    other.assert_valid_baseline()
                    other.damage(case)
                    before = inventory(other.base)
                    if case == 'symlink':
                        with self.assertRaises(OSError) as caught:
                            other.checkpoint()
                        self.assertEqual(caught.exception.errno, errno.ELOOP)
                    else:
                        with self.assertRaisesRegex(RuntimeError, cases[case]):
                            other.checkpoint()
                    self.assertEqual(inventory(other.base), before, case+' mutated custody/state')
                finally:
                    other.doCleanups()

    def procedure_dispatch(self, stage, *, unit_ownership=True):
        """Real CLI dispatch/guards; omit privileged bootstrap and fixed topology.

        Only read-only `id` is dispatched. This does not qualify bootstrap or
        root ownership. Source statements and guards are otherwise unchanged.
        """
        tree = ast.parse((SOURCE / 'owner-window.py').read_bytes())
        start = next(i for i, node in enumerate(tree.body)
                     if isinstance(node, ast.Assign) and any(
                         isinstance(t, ast.Name) and t.id == 'mode' for t in node.targets))
        nodes = [n for n in tree.body[:start] if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        nodes += tree.body[start:]
        output = io.StringIO()
        namespace = dict(c=self.c, A=stage, P=Path, paths=self.paths, os=os,
                         sys=sys, json=json, time=time, uuid=uuid, hashlib=hashlib)
        with contextlib.ExitStack() as stack:
            if unit_ownership:
                stack.enter_context(self.procedure_unit_ownership())
            stack.enter_context(patch.object(sys, 'argv', ['owner-window.py', 'id', self.w['path']]))
            stack.enter_context(contextlib.redirect_stdout(output))
            exec(compile(ast.Module(body=nodes, type_ignores=[]), 'private-cli-dispatch', 'exec'), namespace)
        return output.getvalue().strip()

    @contextlib.contextmanager
    def procedure_unit_ownership(self):
        """Only root-owner arguments on this private tree map to actual euid."""
        directory, proof_file = self.c.directory, self.c.proof_file

        def unit_directory(path, uid):
            self.assertTrue(Path(path).is_relative_to(self.base))
            return directory(path, os.geteuid() if uid == 0 else uid)

        def unit_proof(fd, name, **kwargs):
            self.assertTrue(Path(os.readlink('/proc/self/fd/'+str(fd))).is_relative_to(self.base))
            if kwargs.get('uid') == 0:
                kwargs['uid'] = os.geteuid()
            return proof_file(fd, name, **kwargs)

        with patch.object(self.c, 'directory', side_effect=unit_directory), \
                patch.object(self.c, 'proof_file', side_effect=unit_proof):
            yield

    def predecessor_fixture(self):
        old = Path(self.w['procedure'])
        for name in sorted(STAGE_SCRIPTS):
            target = old / name
            target.write_bytes((SOURCE / name).read_bytes())
            target.chmod(0o400)
        manifest = old / 'approved-scripts.json'
        manifest.write_text(json.dumps({n: hashlib.sha256((old/n).read_bytes()).hexdigest()
                                       for n in sorted(STAGE_SCRIPTS)}))
        manifest.chmod(0o400)
        stage = self.base / 'new-procedure'
        stage.mkdir(mode=0o700)
        proof = dict(schema='acx-owner-procedure-predecessor/v1', window_id=WINDOW,
                     window_path=self.w['path'], procedure=str(old),
                     manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                     owner_window_sha256=hashlib.sha256((old/'owner-window.py').read_bytes()).hexdigest(),
                     owner_custody_sha256=hashlib.sha256((old/'owner-custody.py').read_bytes()).hexdigest())
        return stage, proof

    def test_procedure_predecessor_dispatch(self):
        stage, proof = self.predecessor_fixture()
        fd = self.c.directory(stage, os.geteuid())
        try: self.c.seal(fd, 'procedure-predecessor.json', proof)
        finally: os.close(fd)
        before = inventory(self.base)
        self.assertEqual(self.procedure_dispatch(stage), WINDOW)
        self.assertEqual(inventory(self.base), before)

    def test_actual_unprivileged_stage_refuses(self):
        if os.geteuid() == 0:
            self.skipTest('requires actual unprivileged UID; this is not Root qualification')
        stage, proof = self.predecessor_fixture()
        self.rewrite(stage / 'procedure-predecessor.json', proof)
        before = inventory(self.base)
        with self.assertRaisesRegex(RuntimeError, 'unsafe custody ancestor|expected-owner private directory required'):
            self.procedure_dispatch(stage, unit_ownership=False)
        self.assertEqual(inventory(self.base), before)
        self.assertEqual(self.procedure_dispatch(stage), WINDOW)

    def test_procedure_predecessor_refusals(self):
        stage, proof = self.predecessor_fixture()
        receipt = stage / 'procedure-predecessor.json'
        cases = dict(absent='window/procedure mismatch',
                     extra='bad procedure predecessor schema', schema='bad procedure predecessor schema',
                     window_id='procedure predecessor binding mismatch',
                     window_path='procedure predecessor binding mismatch',
                     procedure='procedure predecessor binding mismatch',
                     manifest_sha256='predecessor manifest mismatch',
                     owner_window_sha256='predecessor helper hash mismatch',
                     owner_custody_sha256='predecessor helper hash mismatch',
                     mutable='unsafe proof file: procedure-predecessor.json', symlink=None,
                     hardlink='unsafe proof file: procedure-predecessor.json',
                     **{'old-mutable': 'unsafe proof file: owner-custody.py',
                        'old-hash': 'predecessor script hash mismatch',
                        'old-missing': 'predecessor stage inventory',
                        'old-extra': 'extraneous predecessor stage file',
                        'two-file-manifest': 'predecessor manifest mismatch'})
        old = Path(self.w['procedure']) / 'owner-custody.py'
        original = old.read_bytes()
        manifest = old.parent / 'approved-scripts.json'
        manifest_bytes = manifest.read_bytes()
        missing = old.parent / 'observe.py'
        missing_bytes = missing.read_bytes()
        for case in cases:
            with self.subTest(case=case):
                if receipt.exists() or receipt.is_symlink(): receipt.unlink()
                extra = stage / 'linked-proof'
                if extra.exists(): extra.unlink()
                self.rewrite(receipt, proof)
                baseline = inventory(self.base)
                self.assertEqual(self.procedure_dispatch(stage), WINDOW)
                self.assertEqual(inventory(self.base), baseline)
                value = dict(proof)
                if case == 'extra': value['untrusted_adoption'] = True
                elif case in proof: value[case] = 'mismatch'
                if case == 'absent': receipt.unlink()
                else: self.rewrite(receipt, value)
                if case == 'mutable': receipt.chmod(0o600)
                elif case == 'symlink': receipt.unlink(); receipt.symlink_to(old)
                elif case == 'hardlink': os.link(receipt, extra)
                elif case == 'old-mutable': old.chmod(0o600)
                elif case == 'old-hash':
                    old.chmod(0o600); old.write_bytes(original+b'\n'); old.chmod(0o400)
                elif case == 'old-missing': missing.unlink()
                elif case == 'old-extra': (old.parent / 'unapproved.py').write_bytes(b'unapproved')
                elif case == 'two-file-manifest':
                    pins = json.loads(manifest_bytes)
                    self.rewrite(manifest, {n: pins[n] for n in ('owner-window.py', 'owner-custody.py')})
                    self.rewrite(receipt, dict(proof, manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()))
                before = inventory(self.base)
                try:
                    if case == 'symlink':
                        with self.assertRaises(OSError) as caught:
                            self.procedure_dispatch(stage)
                        self.assertEqual(caught.exception.errno, errno.ELOOP)
                    else:
                        with self.assertRaisesRegex(RuntimeError, cases[case]):
                            self.procedure_dispatch(stage)
                    self.assertEqual(inventory(self.base), before)
                finally:
                    old.chmod(0o600); old.write_bytes(original); old.chmod(0o400)
                    manifest.chmod(0o600); manifest.write_bytes(manifest_bytes); manifest.chmod(0o400)
                    if not missing.exists():
                        missing.write_bytes(missing_bytes); missing.chmod(0o400)
                    (old.parent / 'unapproved.py').unlink(missing_ok=True)

    def damage(self, case):
        if case == 'over33':
            (Path(self.w['path']) / 'ops' / str(uuid.UUID(int=999))).mkdir(mode=0o700)
        elif case == 'pending': self.op(32, 'result.json').unlink()
        elif case == 'unknown':
            self.rewrite(self.op(32, 'result.json'), dict(
                outcome='unknown', operation=self.ids[32], window=WINDOW))
        elif case == 'wait-status':
            self.rewrite(self.op(0, 'result.json'), dict(
                outcome='published', operation=self.ids[0], window=WINDOW, writer_wait_status=1))
        elif case == 'unreaped':
            self.rewrite(self.op(0, 'writer-stopped.json'), dict(native_reaped=False, native_publish_completed=True, wait_status=0))
        elif case in ('live-writer', 'live-guardian'):
            identity = dict(pid=os.getpid(), boot=self.dead['boot'],
                            start=Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19])
            self.rewrite(self.op(0, 'writer-started.json' if case == 'live-writer' else 'guardian.json'),
                         dict(identity, operation=self.ids[0], window=WINDOW))
        elif case == 'foreign':
            p = dict(self.candidates[self.ids[30]], requested_by='foreign')
            (self.paths.runtime / 'dev/gpu-intent.json').write_text(json.dumps(p))
        elif case == 'newer':
            self.authority['highest_sequence'] = 33
            (self.paths.store / 'intent-authority.json').write_text(json.dumps(self.authority))
        elif case == 'mutable': self.op(0, 'candidate.json').chmod(0o600)
        elif case == 'symlink':
            p = self.op(0, 'candidate.json'); p.unlink(); p.symlink_to(self.op(1, 'candidate.json'))
        elif case == 'hardlink': os.link(self.op(0, 'candidate.json'), self.base / 'extra-link')
        elif case == 'incomplete': self.op(0, 'publication.json').unlink()
        elif case == 'preflight': self.op(0, 'preflight.json').unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE)
    args = parser.parse_args()
    SOURCE = args.source.absolute()
    print(json.dumps(dict(qualification='UNIT_ONLY', uid=os.geteuid(), source=str(SOURCE))), flush=True)
    unittest.main(argv=[__file__], verbosity=2)
