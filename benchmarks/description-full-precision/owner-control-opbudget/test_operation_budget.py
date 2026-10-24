"""Real capacity/admission functions; private files only, no production CLI.

Compile the unchanged operation AST from the selected complete client source to
avoid executing its root-only CLI bootstrap. Custody is loaded in full. Popen is
the external-effect seam; all count, custody, flock, read, fork and guard code is
real. Snapshot payloads are exact; missing publication/stopped proofs and source
view are explicitly synthesized for the isolated reconciliation fixture.
"""
import ast
import copy
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import uuid

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parent / 'owner-control'
FAILED = '07a7a618-2c61-4a06-84ff-07849c5426c7'
SNAPSHOT = json.loads((HERE / 'fixtures/window-operation-snapshot.json').read_bytes())
BASELINE = os.environ.get('OPBUDGET_BASELINE') == '1'


def load(original=BASELINE):
    custody = HERE / 'fixtures/source5-owner-custody.py' if original else CONTROL / 'owner-custody.py'
    client = HERE / 'fixtures/source5-owner-window.py' if original else CONTROL / 'owner-window.py'
    c = types.ModuleType('custody_under_test')
    exec(compile(custody.read_bytes(), str(custody), 'exec'), c.__dict__)
    tree = ast.parse(client.read_bytes())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'operation')
    ns = dict(c=c, os=os, P=Path, A=CONTROL, sys=sys, time=time, uuid=uuid,
              subprocess=types.SimpleNamespace(Popen=None, DEVNULL=subprocess.DEVNULL))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(client), 'exec'), ns)
    return c, ns


class Window:
    def __init__(self, root, c, include_failed=True):
        self.root, self.c = Path(root), c
        self.window = dict(id=SNAPSHOT['window_id'], path=str(root), procedure=str(CONTROL))
        self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        c.seal(self.fd, 'window.json', self.window)
        self.ops = c.subdir(self.fd, 'ops', create=True)
        for row in SNAPSHOT['operations']:
            if not include_failed and row['op'] == FAILED:
                continue
            ofd = c.subdir(self.ops, row['op'], create=True)
            try:
                for key in ('intent', 'result', 'candidate'):
                    if row[key] is not None:
                        c.seal(ofd, key + '.json', row[key])
                if row['result']['outcome'] == 'published':
                    c.seal(ofd, 'publication.json', row['candidate'])
                    c.seal(ofd, 'writer-stopped.json', dict(native_reaped=True, native_publish_completed=True))
            finally:
                os.close(ofd)
        candidates = [r['candidate'] for r in SNAPSHOT['operations'] if r['candidate']]
        latest = max(candidates, key=lambda p: p['sequence'])
        self.latest = next(r['op'] for r in SNAPSHOT['operations'] if r['candidate'] == latest)
        self.runtime, self.store = self.root / 'runtime', self.root / 'store'
        self.runtime.mkdir(); self.store.mkdir()
        authority = dict(highest_sequence=264, intents={p['nonce']: dict(sequence=p['sequence'], publication={k:p[k] for k in ('action','requested_at','expires_at','ttl_seconds','requested_by','sequence')}) for p in candidates})
        (self.store / 'intent-authority.json').write_text(json.dumps(authority))
        target = self.runtime / 'prod/gpu-intent.json'
        target.parent.mkdir(); target.write_text(json.dumps(latest))
        self.paths = c.Paths(self.runtime, self.store, self.root / 'lifecycle.lock', self.root / 'markers')

    def close(self):
        os.close(self.ops); os.close(self.fd)

    def fill(self, count):
        while len(os.listdir(self.ops)) < count:
            name = str(uuid.uuid4())
            ofd = self.c.subdir(self.ops, name, create=True)
            self.c.seal(ofd, 'result.json', dict(outcome='refused', fixture=True))
            os.close(ofd)

    def payloads(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file() and p.name != 'window.lock'}


def launch_mock(c, ns, window, calls):
    def popen(argv, **kwargs):
        # An independently opened flock must succeed here: admission released it.
        lock = c.lock_path(window.root / 'window.lock', time.monotonic() + .3)
        c.unlock([lock])
        op = argv[-1]
        ofd = c.subdir(window.ops, op)
        plan = c.load_json(ofd, 'intent.json')
        assert plan == dict(id=op, window=window.window['id'], action=plan['action'], previous=window.latest)
        calls.append(plan)
        # Only substitute the guardian process; never claim these are native proofs.
        c.seal(ofd, 'result.json', dict(outcome='published', fixture=True))
        os.close(ofd)
        return types.SimpleNamespace(pid=os.getpid())
    ns['subprocess'].Popen = popen


def contender(root, action, ready, release, out):
    c, ns = load()
    wfd, w = c.validate_window(root, SNAPSHOT['window_id'])
    ops = c.subdir(wfd, 'ops')
    latest = next(r['op'] for r in SNAPSHOT['operations'] if r['candidate'] and r['candidate']['sequence'] == 264)
    calls = []
    window = types.SimpleNamespace(root=Path(root), ops=ops, window=w, latest=latest)
    launch_mock(c, ns, window, calls)
    ready.put(os.getpid()); release.wait(5)
    try:
        op = ns['operation'](wfd, w, action, latest)
        out.put(('admitted', op, len(calls)))
    except Exception as e:
        out.put(('refused', str(e), len(calls)))
    finally:
        os.close(ops); os.close(wfd)


class OperationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.c, self.ns = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Window(self.tmp.name, self.c)
        self.calls = []
        launch_mock(self.c, self.ns, self.w, self.calls)

    def tearDown(self):
        self.w.close(); self.tmp.cleanup()

    def run_operation(self, action):
        return self.ns['operation'](self.w.fd, self.w.window, action, self.w.latest)

    def test_original_32_cause_removal(self):
        original, _ = load(True)
        with tempfile.TemporaryDirectory() as root:
            w = Window(root, original, include_failed=False)
            try:
                self.assertEqual(len(os.listdir(w.ops)), 32)
                self.assertEqual(len(original.known_candidates(w.fd)), 31)
                self.assertEqual(original.reconcile(w.fd, w.paths), w.latest)
            finally:
                w.close()
        with self.assertRaisesRegex(RuntimeError, 'operation budget exhausted'):
            original.known_candidates(self.w.fd)

    def test_actual_33_snapshot_retained_readback(self):
        before = self.w.payloads()
        self.assertEqual(len(os.listdir(self.w.ops)), 33)
        self.assertEqual(len(self.c.known_candidates(self.w.fd)), 31)
        self.assertEqual(self.c.reconcile(self.w.fd, self.w.paths), self.w.latest)
        self.assertEqual(self.c.known_candidates(self.w.fd)[self.w.latest]['sequence'], 264)
        failed = json.loads((self.w.root / 'ops' / FAILED / 'result.json').read_bytes())
        self.assertEqual(failed['error'], 'RuntimeError: operation budget exhausted')
        self.assertEqual(self.w.payloads(), before)

    def test_near_and_exact_capacity_readonly(self):
        self.assertEqual(self.c.MAX_WINDOW_OPERATIONS, 1024)
        self.assertEqual(self.c.MAX, 1048576)
        self.w.fill(1023)
        before = self.w.payloads()
        self.assertEqual(self.c.reconcile(self.w.fd, self.w.paths), self.w.latest)
        self.assertEqual(self.w.payloads(), before)
        self.w.fill(1024)
        before = self.w.payloads()
        self.assertEqual(len(self.c.known_candidates(self.w.fd)), 31)
        self.assertEqual(self.c.reconcile(self.w.fd, self.w.paths), self.w.latest)
        self.assertEqual(self.w.payloads(), before)
        for action in ('start', 'stop', 'auto'):
            with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                self.run_operation(action)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.w.payloads(), before)
        self.w.fill(1025)
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            self.c.known_candidates(self.w.fd)

    def test_full_candidate_history_at_near_and_exact_capacity(self):
        # Exercise the real read/IPC/guard with candidate-bearing history too,
        # rather than reaching capacity solely with refused-operation receipts.
        original = self.w.payloads()
        latest = self.c.known_candidates(self.w.fd)[self.w.latest]
        authority_path = self.w.store / 'intent-authority.json'
        authority = json.loads(authority_path.read_bytes())
        while len(os.listdir(self.w.ops)) < 1024:
            candidate = copy.deepcopy(latest)
            candidate['sequence'] += 1
            candidate['nonce'] = str(uuid.uuid4())
            op = str(uuid.uuid4())
            ofd = self.c.subdir(self.w.ops, op, create=True)
            try:
                self.c.seal(ofd, 'candidate.json', candidate)
                self.c.seal(ofd, 'publication.json', candidate)
                self.c.seal(ofd, 'result.json', dict(outcome='published', fixture=True))
                self.c.seal(ofd, 'writer-stopped.json', dict(native_reaped=True, native_publish_completed=True))
            finally:
                os.close(ofd)
            authority['intents'][candidate['nonce']] = dict(sequence=candidate['sequence'], publication={k:candidate[k] for k in ('action','requested_at','expires_at','ttl_seconds','requested_by','sequence')})
            latest = candidate
            if len(os.listdir(self.w.ops)) in (1023, 1024):
                authority['highest_sequence'] = candidate['sequence']
                authority_path.write_text(json.dumps(authority))
                (self.w.runtime / 'prod/gpu-intent.json').write_text(json.dumps(candidate))
                view = self.c.view(self.w.paths, 'auto')
                self.assertGreater(len(json.dumps(view)), 137715)
                self.assertLess(len(json.dumps(view)), self.c.MAX)
                self.assertEqual(self.c.reconcile(self.w.fd, self.w.paths), op)
        self.assertEqual(len(self.c.known_candidates(self.w.fd)), 1022)  # two historical failures remain
        after = self.w.payloads()
        for name, digest in original.items():
            if name.startswith('ops/') or name == 'window.json':
                self.assertEqual(after[name], digest)

    def test_start_refused_before_custody_or_guardian(self):
        self.w.fill(1022)
        before, names = self.w.payloads(), os.listdir(self.w.ops)
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            self.run_operation('start')
        self.assertEqual(self.calls, [])
        self.assertEqual(set(os.listdir(self.w.ops)), set(names))
        self.assertEqual(self.w.payloads(), before)
        lock = self.c.lock_path(self.w.root / 'window.lock', time.monotonic() + .2)
        self.c.unlock([lock])

    def test_start_last_regular_slot_then_stop_auto_cleanup(self):
        self.w.fill(1021)
        before = self.w.payloads()
        self.run_operation('start')
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            self.run_operation('start')
        self.run_operation('stop'); self.run_operation('auto')
        self.assertEqual([p['action'] for p in self.calls], ['start', 'stop', 'auto'])
        self.assertEqual(len(os.listdir(self.w.ops)), 1024)
        for action in ('stop', 'auto'):
            with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                self.run_operation(action)
        after = self.w.payloads()
        self.assertTrue(all(after[p] == digest for p, digest in before.items()))
        self.assertEqual(json.loads((self.w.root / 'window.json').read_bytes()), self.w.window)

    def test_cleanup_slots_shared_auto_can_use_both(self):
        self.w.fill(1022)
        self.run_operation('auto'); self.run_operation('auto')
        with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
            self.run_operation('stop')
        self.assertEqual(len(self.calls), 2)

    def test_foreign_guard_still_refuses_at_capacity(self):
        self.w.fill(1024)
        authority_path = self.w.store / 'intent-authority.json'
        authority = json.loads(authority_path.read_bytes()); authority['highest_sequence'] = 265
        authority_path.write_text(json.dumps(authority))
        with self.assertRaisesRegex(RuntimeError, 'newer authority'):
            self.c.reconcile(self.w.fd, self.w.paths)
        authority['highest_sequence'] = 264
        authority_path.write_text(json.dumps(authority))
        target = self.w.runtime / 'prod/gpu-intent.json'
        payload = json.loads(target.read_bytes()); payload['nonce'] = str(uuid.uuid4())
        target.write_text(json.dumps(payload))
        with self.assertRaisesRegex(RuntimeError, 'previous publication'):
            self.c.reconcile(self.w.fd, self.w.paths)

    def test_invalid_directory_fails_closed_before_creation(self):
        (self.w.root / 'ops/foreign').mkdir(mode=0o700)
        before = self.w.payloads(); names = set(os.listdir(self.w.ops))
        with self.assertRaises(ValueError):
            self.run_operation('start')
        self.assertEqual(self.calls, [])
        self.assertEqual(set(os.listdir(self.w.ops)), names)
        self.assertEqual(self.w.payloads(), before)

    def test_real_concurrent_start_contenders_share_last_regular_slot(self):
        self.concurrent('start', 1021, 1022)

    def test_real_concurrent_cleanup_contenders_share_last_slot(self):
        self.concurrent('stop', 1023, 1024)

    def concurrent(self, action, count, final):
        self.w.fill(count)
        before = self.w.payloads()
        ctx = multiprocessing.get_context('fork')
        ready, out, release = ctx.Queue(), ctx.Queue(), ctx.Event()
        children = [ctx.Process(target=contender, args=(str(self.w.root), action, ready, release, out)) for _ in range(4)]
        # Hold the actual shared fence while all contenders start, then release.
        fence = self.c.lock_path(self.w.root / 'window.lock', time.monotonic() + 1)
        try:
            for child in children: child.start()
            for _ in children: ready.get(timeout=5)
            release.set()
            time.sleep(.1)
            self.assertTrue(out.empty(), 'all contenders must wait for existing window.lock')
        finally:
            self.c.unlock([fence])
        try:
            results = [out.get(timeout=15) for _ in children]
            self.assertEqual(sum(r[0] == 'admitted' for r in results), 1, results)
            self.assertEqual(sum(r[2] for r in results), 1, results)
            self.assertTrue(all('budget exhausted' in r[1] for r in results if r[0] == 'refused'), results)
            self.assertEqual(len(os.listdir(self.w.ops)), final)
            after = self.w.payloads()
            self.assertTrue(all(after[p] == digest for p, digest in before.items()))
        finally:
            for child in children:
                child.join(5)
                if child.is_alive(): child.terminate(); child.join(5)
                self.assertEqual(child.exitcode, 0)
            for q in (ready, out): q.close(); q.join_thread()

# The B delta is verified against one of two explicitly named pre-B baselines.
# "b-only": B alone on the budget-source5 seed (B's first source 009030 custody).
# "composed": B on accepted callback A7 (commit 3a680fc622c41f0fb303b27275226280bd40fda9).
# Undoing B must reproduce the scope's exact baseline bytes; no other change passes.
B_ONLY_CUSTODY = HERE / 'fixtures/b-only-source009030-owner-custody.py'
B_ONLY_CUSTODY_SHA = 'f14b49bd0c3d645ababe72a2a6f39f37ef9e0a6f0cd61b4c374d2a11544d0056'
A7_CONTROL_FILES = HERE / 'fixtures/accepted-source7-control-files.json'
A7_SCRIPT_PINS = HERE / 'fixtures/accepted-source7-candidate-scripts.json'
SCOPES = {
    'b-only': (HERE / 'fixtures/source5-owner-custody.py', '42b03d88a7cf89b4fcc4bf6ac6ce2c84ba0789abfa67abdadcab6dc5f37a1ef9'),
    'composed': (HERE / 'fixtures/accepted-source7-owner-custody.py', '576bb83150af3f484996d3a49b05bc9b52d834215846030b64d4de022977f058'),
}
SOURCE5_CLIENT_SHA = '1983f8684de3d03a59c090b1b469e65f5b84ad201283e787bdf5fb872b8b6600'  # also A7's client
B_CONSTANT = b'MAX_WINDOW_OPERATIONS=1024\n'
B_BOUND = (b'len(names)<=MAX_WINDOW_OPERATIONS', b'len(names)<=32')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def undo_b(data):
    """Remove exactly the B constant (module level) and known_candidates bound."""
    if data.count(B_CONSTANT) != 1 or data.count(B_BOUND[0]) != 1:
        raise AssertionError('B regions must each occur exactly once')
    lines = data.splitlines(keepends=True)
    region = next(n for n in ast.parse(data).body if isinstance(n, ast.FunctionDef) and n.name == 'known_candidates')
    bound = next(i for i, line in enumerate(lines, 1) if B_BOUND[0] in line)
    if not region.lineno <= bound <= region.end_lineno or B_CONSTANT not in lines:
        raise AssertionError('B regions outside the declared constant/known_candidates scope')
    return data.replace(B_CONSTANT, b'', 1).replace(*B_BOUND, 1)


def without_operation(data):
    tree = ast.parse(data)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'operation')
    lines = data.splitlines(keepends=True)
    return b''.join(lines[:node.lineno-1] + lines[node.end_lineno:])


class ScopeAndCauseTests(unittest.TestCase):
    def assert_custody_scope(self, candidate, scope):
        baseline, digest = SCOPES[scope]
        self.assertEqual(sha256(baseline.read_bytes()), digest, scope + ' baseline pin')
        self.assertEqual(undo_b(candidate), baseline.read_bytes(), scope + ' custody scope')

    def assert_client_scope(self):
        # Both scopes share the source5 client (A7 did not change owner-window.py).
        old_client = (HERE / 'fixtures/source5-owner-window.py').read_bytes()
        self.assertEqual(sha256(old_client), SOURCE5_CLIENT_SHA)
        self.assertEqual(without_operation((CONTROL / 'owner-window.py').read_bytes()), without_operation(old_client))

    def test_declared_regions_only_b_only_against_source5(self):
        candidate = B_ONLY_CUSTODY.read_bytes()
        self.assertEqual(sha256(candidate), B_ONLY_CUSTODY_SHA)  # B's pinned source 009030 custody
        self.assert_custody_scope(candidate, 'b-only')
        self.assert_client_scope()
        # B alone predates A7: the composed baseline must not accept it.
        with self.assertRaises(AssertionError):
            self.assert_custody_scope(candidate, 'composed')
        manifest_path = Path('/home/gate/description-owner-ipc-repair-inputs-20261024T0532/manifest.json')
        manifest = json.loads(manifest_path.read_bytes())
        self.assertEqual(sha256(manifest_path.read_bytes()), '6038b6e69ddfb87248bcd44a320cf749a0e19d2088a69220d95042e925f9e123')
        self.assertEqual(manifest['files']['budget-source5/owner-custody.py'], SCOPES['b-only'][1])
        self.assertEqual(manifest['files']['budget-source5/owner-window.py'], SOURCE5_CLIENT_SHA)
        self.assertEqual(sha256((HERE / 'fixtures/window-operation-snapshot.json').read_bytes()), manifest['files']['window-operation-snapshot.json'])

    def test_declared_regions_only_composed_against_accepted_source7(self):
        # Production under test is the composed tree: undo-B must give exact A7.
        candidate = (CONTROL / 'owner-custody.py').read_bytes()
        self.assert_custody_scope(candidate, 'composed')
        self.assert_client_scope()
        # A7's native_job differs from source5, so the B-only baseline rejects it.
        with self.assertRaises(AssertionError):
            self.assert_custody_scope(candidate, 'b-only')
        a7 = json.loads(A7_CONTROL_FILES.read_bytes())
        self.assertEqual(a7['commit'], '3a680fc622c41f0fb303b27275226280bd40fda9')
        self.assertEqual(a7['files']['owner-custody.py'], SCOPES['composed'][1])
        self.assertEqual(a7['files']['owner-window.py'], SOURCE5_CLIENT_SHA)
        present = {str(p.relative_to(CONTROL)) for p in CONTROL.rglob('*') if p.is_file()}
        self.assertEqual(present, set(a7['files']))
        for name, digest in a7['files'].items():
            if name not in ('owner-custody.py', 'owner-window.py', 'candidate-scripts.json'):
                self.assertEqual(sha256((CONTROL / name).read_bytes()), digest, name)
        # Composition changes only the two B-owned script pins, to the actual bytes.
        accepted_pin_bytes = A7_SCRIPT_PINS.read_bytes()
        self.assertEqual(sha256(accepted_pin_bytes), a7['files']['candidate-scripts.json'])
        accepted_pins = json.loads(accepted_pin_bytes)
        pins = json.loads((CONTROL / 'candidate-scripts.json').read_bytes())
        self.assertEqual(set(pins), set(accepted_pins), 'accepted A7 script-pin keys')
        for name in ('owner-custody.py', 'owner-window.py'):
            self.assertEqual(pins.pop(name), sha256((CONTROL / name).read_bytes()))
        for name, digest in pins.items():
            self.assertEqual(sha256((CONTROL / name).read_bytes()), digest, name)
            self.assertEqual(a7['files'][name], digest, name)

    def test_composed_scope_rejects_script_pin_tampering(self):
        pins_path = CONTROL / 'candidate-scripts.json'
        pins = json.loads(pins_path.read_bytes())
        tampered = {
            'removed-guest-read': {name: digest for name, digest in pins.items() if name != 'guest-read.sh'},
            'removed-all-five-non-B': {name: digest for name, digest in pins.items() if name in ('owner-custody.py', 'owner-window.py')},
            'added-README': dict(pins, **{'README.md': sha256((CONTROL / 'README.md').read_bytes())}),
            'changed-guest-read-hash': dict(pins, **{'guest-read.sh': '0' * 64}),
        }
        read_bytes = Path.read_bytes
        for label, changed in tampered.items():
            with self.subTest(tamper=label):
                data = json.dumps(changed).encode()
                def candidate_pins_only(path):
                    return data if path == pins_path else read_bytes(path)
                with mock.patch.object(Path, 'read_bytes', candidate_pins_only):
                    with self.assertRaises(AssertionError):
                        self.test_declared_regions_only_composed_against_accepted_source7()

    def test_scope_proof_rejects_tampering(self):
        cases = {'b-only': B_ONLY_CUSTODY.read_bytes(), 'composed': (CONTROL / 'owner-custody.py').read_bytes()}
        for scope, good in cases.items():
            tree = ast.parse(good)
            lines = good.splitlines(keepends=True)
            tampered = {}
            # One extra byte in the first body line of each guarded function.
            for name in ('native_job', 'guard', 'guardian', 'reconcile'):
                node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
                edited = list(lines); edited[node.lineno] = edited[node.lineno].replace(b'\n', b' \n', 1)
                tampered[name] = b''.join(edited)
            tampered['bound-moved'] = good.replace(B_BOUND[0], B_BOUND[1], 1).replace(b'\ndef guard(', b'\nassert len([])<=MAX_WINDOW_OPERATIONS\ndef guard(', 1)
            tampered['bound-value'] = good.replace(B_CONSTANT, b'MAX_WINDOW_OPERATIONS=4096\n', 1)
            tampered['constant-duplicated'] = good.replace(B_CONSTANT, B_CONSTANT * 2, 1)
            tampered['b-removed'] = undo_b(good)
            for label, data in tampered.items():
                with self.subTest(scope=scope, tamper=label):
                    self.assertNotEqual(data, good)
                    with self.assertRaises(AssertionError):
                        self.assert_custody_scope(data, scope)

    def test_original_operation_33_real_guardian_refusal(self):
        c, ns = load(True)
        with tempfile.TemporaryDirectory() as root:
            w = Window(root, c, include_failed=False)
            before = w.payloads()
            ns['uuid'] = types.SimpleNamespace(uuid4=lambda: uuid.UUID(FAILED))
            launched = []
            def popen(argv, **kwargs):
                ofd = c.subdir(w.ops, argv[-1])
                plan = c.load_json(ofd, 'intent.json')
                # Actual guardian fails at known_candidates before any view,
                # writer or external fence; only local window.lock is real.
                paths = types.SimpleNamespace(fences=lambda action: [])
                ctx = multiprocessing.get_context('fork')
                child = ctx.Process(target=c.guardian, args=(w.fd, ofd, paths, None, plan, w.window))
                child.start(); child.join(3)
                if child.is_alive(): child.terminate(); child.join(3)
                self.assertEqual(child.exitcode, 0)
                launched.append(child.pid)
                os.close(ofd)
                return types.SimpleNamespace(pid=child.pid)
            ns['subprocess'].Popen = popen
            try:
                with self.assertRaisesRegex(RuntimeError, 'operation refused; retain custody'):
                    ns['operation'](w.fd, w.window, 'start', w.latest)
                self.assertEqual(len(launched), 1)
                self.assertEqual(len(os.listdir(w.ops)), 33)
                failed = json.loads((Path(root) / 'ops' / FAILED / 'result.json').read_bytes())
                snapshot_failed = next(r['result'] for r in SNAPSHOT['operations'] if r['op'] == FAILED)
                self.assertEqual(failed, snapshot_failed)
                with self.assertRaisesRegex(RuntimeError, 'operation budget exhausted'):
                    c.reconcile(w.fd, w.paths)
                after = w.payloads()
                self.assertTrue(all(after[p] == digest for p, digest in before.items()))
                print('ORIGINAL real operation/guardian: 32 -> 33; failed=' + FAILED + '; raw result=' + json.dumps(failed, sort_keys=True))
            finally:
                w.close()


if __name__ == '__main__':
    unittest.main()
