"""Offline tests of the complete native source candidate, never a live CLI.

No pytest imports or service configuration. Implementations are compiled from
their complete source; only explicit test arguments select a sealed baseline,
the sealed source5 candidate or another subject for RED replay.
"""
import ast
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parent
SOURCE5_SHA = "42b03d88a7cf89b4fcc4bf6ac6ce2c84ba0789abfa67abdadcab6dc5f37a1ef9"


def load_control(original=False, subject=None):
    path = subject or ROOT / ("fixtures/original-owner-custody.py" if original else "owner-custody.py")
    module = types.ModuleType("native_control_under_test")
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def actual_view():
    return json.loads((ROOT / "fixtures/actual-view.json").read_bytes())


class NativeRealShapeTests(unittest.TestCase):
    # An explicit test argument selects original bytes; no ambient environment.
    original = False

    def setUp(self):
        self.c = load_control(self.original)

    def test_full_saved_view_round_trips_without_projection(self):
        value = actual_view()
        self.assertEqual(len(json.dumps(value).encode()), 137715)
        self.assertEqual(len(value["authority"]["intents"]), 261)
        status, returned = self.c.native_job(lambda: value, 5)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0,
                         "native full-view child must succeed")
        self.assertEqual(returned, value)
        self.assertEqual(returned["authority"]["sequences"], value["authority"]["sequences"])

    def test_small_cause_removal_same_native_control(self):
        value = dict(authority=dict(highest_sequence=261), publications={},
                     loads=[], deferred=None)
        self.assertEqual(len(json.dumps(value).encode()), 91)
        self.assertEqual(self.c.native_job(lambda: value, 5), (0, value))

    def test_actual_reconcile_auto_full_view_call_shape(self):
        c = self.c
        value = actual_view()
        candidate = max(value["publications"].values(), key=lambda p: p["sequence"])
        op = str(uuid.UUID(int=1))
        with tempfile.TemporaryDirectory() as tmp:
            window = Path(tmp)
            (window / "ops" / op).mkdir(parents=True, mode=0o700)
            (window / "ops").chmod(0o700)
            wfd = os.open(window, os.O_RDONLY | os.O_DIRECTORY)
            ofd = os.open(window / "ops" / op, os.O_RDONLY | os.O_DIRECTORY)
            try:
                c.seal(ofd, "candidate.json", candidate)
                c.seal(ofd, "publication.json", candidate)
                c.seal(ofd, "result.json", {"outcome": "published"})
                c.seal(ofd, "writer-stopped.json",
                       dict(native_reaped=True, native_publish_completed=True))
                paths = object()
                # view is the read-only input seam; reconcile, fork, guard,
                # immutable candidates and reconciliation receipts are actual.
                def saved_view(supplied_paths, mode):
                    if supplied_paths is not paths or mode != "auto":
                        raise AssertionError("reconcile must use view(paths, 'auto')")
                    return value
                with mock.patch.object(c, "view", saved_view):
                    self.assertEqual(c.reconcile(wfd, paths), op)
            finally:
                os.close(ofd)
                os.close(wfd)


    def test_actual_reconcile_reads_real_shape_from_private_files(self):
        c = self.c
        value = actual_view()
        candidate = max(value["publications"].values(), key=lambda p: p["sequence"])
        op = str(uuid.UUID(int=2))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, store = root / "runtime", root / "store"
            store.mkdir()
            runtime.mkdir()
            (store / "intent-authority.json").write_text(json.dumps(value["authority"]))
            # Relocate only the publication keys to this private test namespace.
            relocated = {}
            for index, publication in enumerate(value["publications"].values()):
                base = runtime if index == 0 else store / "intents"
                path = base / "prod" / "gpu-intent.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(publication))
                relocated[str(path)] = publication
            value["publications"] = relocated
            paths = c.Paths(runtime, store, root / "fence", root / "markers")
            window = root / "window"
            (window / "ops" / op).mkdir(parents=True, mode=0o700)
            (window / "ops").chmod(0o700)
            wfd = os.open(window, os.O_RDONLY | os.O_DIRECTORY)
            ofd = os.open(window / "ops" / op, os.O_RDONLY | os.O_DIRECTORY)
            try:
                c.seal(ofd, "candidate.json", candidate)
                c.seal(ofd, "publication.json", candidate)
                c.seal(ofd, "result.json", {"outcome": "published"})
                c.seal(ofd, "writer-stopped.json",
                       dict(native_reaped=True, native_publish_completed=True))
                self.assertEqual(c.view(paths, "auto"), value)
                self.assertGreater(len(json.dumps(value).encode()), 60000)
                self.assertEqual(c.reconcile(wfd, paths), op)
            finally:
                os.close(ofd)
                os.close(wfd)


class OwnedWorker:
    def assert_reaped(self, pid):
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)

    def run_owned(self, fn, seconds=5, after=None, before=None):
        pids = []
        def register(pid):
            pids.append(pid)
            if before:
                before(pid)
        result = self.c.native_job(fn, seconds, after=after, before=register)
        self.assertEqual(len(pids), 1)
        self.assert_reaped(pids[0])
        return result


class NativeBoundaryTests(OwnedWorker, unittest.TestCase):
    def setUp(self):
        self.c = load_control()

    def test_budget_matches_custody_read_limit_and_exact_boundary(self):
        self.assertEqual(self.c.MAX, 1048576)
        value = "x" * (self.c.MAX - 2)  # JSON's two quotes count in the budget.
        self.assertEqual(self.run_owned(lambda: value), (0, value))
        status, value = self.run_owned(lambda: "x" * (self.c.MAX - 1))
        self.assertEqual(os.waitstatus_to_exitcode(status), 71)
        self.assertIsNone(value)

    def test_short_writes_and_interrupted_write_deliver_complete_value(self):
        original_write = os.write
        calls = 0
        def short_write(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise InterruptedError()
            return original_write(fd, data[:997])
        value = actual_view()
        with mock.patch.object(self.c.os, "write", short_write):
            self.assertEqual(self.run_owned(lambda: value), (0, value))

    def test_interrupted_parent_read_and_wait_retry_without_losing_result(self):
        parent = os.getpid()
        real_read, real_wait = os.read, os.waitpid
        interrupted = set()
        def once(name, fn, *args):
            if os.getpid() == parent and name not in interrupted:
                interrupted.add(name)
                raise InterruptedError()
            return fn(*args)
        with mock.patch.object(self.c.os, "read", lambda *a: once("read", real_read, *a)), \
             mock.patch.object(self.c.os, "waitpid", lambda *a: once("wait", real_wait, *a)):
            value = actual_view()
            self.assertEqual(self.run_owned(lambda: value), (0, value))
        self.assertEqual(interrupted, {"read", "wait"})

    def test_zero_write_refuses_and_skips_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            after = Path(tmp) / "after"
            with mock.patch.object(self.c.os, "write", return_value=0):
                # No before gate here: inject failure in the result write.
                status, value = self.c.native_job(lambda: actual_view(), 5,
                                                  after=lambda: after.touch())
            self.assertNotEqual(status, 0)
            self.assertIsNone(value)
            self.assertFalse(after.exists())

    def test_nonserializable_and_child_exception_refuse(self):
        def failed():
            raise RuntimeError("intentional child failure")
        for fn in (failed, lambda: object(), lambda: float("nan"), lambda: float("inf")):
            with self.subTest(fn=fn):
                status, value = self.run_owned(fn)
                self.assertEqual(os.waitstatus_to_exitcode(status), 71)
                self.assertIsNone(value)

    def test_before_registers_native_identity_before_effect_then_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / "events"
            def append(text):
                with events.open("a") as stream:
                    stream.write(text + "\n")
            def before(pid):
                self.assertEqual(events.exists(), False)
                # A live native identity is readable before the gate opens.
                os.kill(pid, 0)
                append("before")
            def effect():
                if events.read_text() != "before\n":
                    raise AssertionError("effect preceded identity registration")
                append("effect")
                return dict(native_publish_completed=True)
            status, value = self.run_owned(effect, before=before,
                                            after=lambda: append("after"))
            self.assertEqual((status, value), (0, dict(native_publish_completed=True)))
            self.assertEqual(events.read_text(), "before\neffect\nafter\n")

    def test_failed_before_reaps_without_effect_or_after_and_closes_fds(self):
        with tempfile.TemporaryDirectory() as tmp:
            effect = Path(tmp) / "effect"
            after = Path(tmp) / "after"
            pids = []
            def refused(pid):
                pids.append(pid)
                raise RuntimeError("identity custody failed")
            with self.assertRaisesRegex(RuntimeError, "identity custody failed"):
                self.c.native_job(lambda: effect.touch(), 5,
                                  before=refused, after=lambda: after.touch())
            self.assert_reaped(pids[0])
            self.assertFalse(effect.exists())
            self.assertFalse(after.exists())

    def test_before_exhausts_deadline_does_not_release_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            effect = Path(tmp) / "effect"
            pids = []
            def slow_before(pid):
                pids.append(pid)
                time.sleep(.08)
            with self.assertRaisesRegex(RuntimeError, "deadline before release"):
                self.c.native_job(lambda: effect.touch(), .03, before=slow_before)
            self.assertFalse(effect.exists())
            self.assert_reaped(pids[0])

    def test_timeout_kills_reaps_and_never_accepts_partial_result(self):
        start = time.monotonic()
        status, value = self.run_owned(lambda: time.sleep(20), seconds=.12)
        self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
        self.assertIsNone(value)
        self.assertLess(time.monotonic() - start, 3)

    def test_deadline_is_checked_while_stream_is_incomplete(self):
        original_write = os.write
        parent = os.getpid()
        writes = 0
        def stalled_write(fd, data):
            nonlocal writes
            if os.getpid() != parent:
                writes += 1
                if writes == 2:
                    time.sleep(20)
            return original_write(fd, data)
        with mock.patch.object(self.c.os, "write", stalled_write):
            status, value = self.run_owned(lambda: actual_view(), seconds=.2)
        self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
        self.assertIsNone(value)

    def test_malformed_or_truncated_or_oversized_stream_refused(self):
        # Inject wire corruption at the OS write boundary of the actual worker.
        original_write = os.write
        for bad in (b'{"broken":', b'{}{}', b'\xff', b'', b'NaN', b'Infinity',
                    b'x' * (self.c.MAX + 1)):
            with self.subTest(size=len(bad)):
                def corrupt_write(fd, data):
                    rest = memoryview(bad)
                    while rest:
                        n = original_write(fd, rest)
                        rest = rest[n:]
                    return len(data)
                with mock.patch.object(self.c.os, "write", corrupt_write):
                    status, value = self.c.native_job(lambda: {}, 5)
                self.assertIsNone(value)
                # Malformed success may still have native wait status zero.
                # The value, never the status alone, must gate a caller.

    def test_parent_read_error_still_kills_reaps_and_closes_pipes(self):
        original_read = os.read
        original_pipe = os.pipe2
        pids, fds = [], []
        parent = os.getpid()
        def pipe(flags):
            pair = original_pipe(flags)
            fds.extend(pair)
            return pair
        def read(fd, count):
            if os.getpid() == parent:
                raise OSError("injected parent read failure")
            return original_read(fd, count)
        with mock.patch.object(self.c.os, "read", read), \
             mock.patch.object(self.c.os, "pipe2", pipe):
            with self.assertRaisesRegex(OSError, "injected parent read failure"):
                self.c.native_job(lambda: time.sleep(20), 5, before=pids.append)
        self.assert_reaped(pids[0])
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_unreaped_worker_retains_native_guardian(self):
        # No real child can be left behind by this fault injection. Simulate
        # uninterruptible waitpid, and stop only at the guardian's retain loop.
        class Retained(BaseException):
            pass
        ticks = iter(range(100))
        fds, sleeps = [], []
        original_pipe = os.pipe2
        def pipe(flags):
            pair = original_pipe(flags)
            fds.extend(pair)
            return pair
        def sleep(seconds):
            sleeps.append(seconds)
            if seconds == 1:
                raise Retained()
        try:
            with mock.patch.object(self.c.os, "fork", return_value=424242), \
                 mock.patch.object(self.c.os, "pipe2", pipe), \
                 mock.patch.object(self.c.os, "waitpid", return_value=(0, 0)), \
                 mock.patch.object(self.c.os, "kill") as kill, \
                 mock.patch.object(self.c.time, "monotonic", side_effect=lambda: next(ticks)), \
                 mock.patch.object(self.c.time, "sleep", side_effect=sleep):
                with self.assertRaises(Retained):
                    self.c.native_job(lambda: None, 0)
                kill.assert_called_once_with(424242, signal.SIGKILL)
                self.assertEqual(sleeps[-1], 1)
                os.fstat(fds[0])  # still held: native_job has not returned
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def test_unknown_reap_state_retains_native_guardian(self):
        class Retained(BaseException):
            pass
        ticks = iter(range(100))
        fds = []
        original_pipe = os.pipe2
        def pipe(flags):
            pair = original_pipe(flags)
            fds.extend(pair)
            return pair
        def sleep(seconds):
            if seconds == 1:
                raise Retained()
        try:
            with mock.patch.object(self.c.os, "fork", return_value=424242), \
                 mock.patch.object(self.c.os, "pipe2", pipe), \
                 mock.patch.object(self.c.os, "waitpid", side_effect=OSError("unknown reap state")), \
                 mock.patch.object(self.c.os, "kill", side_effect=OSError("unknown kill state")), \
                 mock.patch.object(self.c.time, "monotonic", side_effect=lambda: next(ticks)), \
                 mock.patch.object(self.c.time, "sleep", side_effect=sleep):
                with self.assertRaises(Retained):
                    self.c.native_job(lambda: None, 0)
                os.fstat(fds[0])
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def test_wait_status_for_another_pid_is_not_owned_reaping_proof(self):
        class Retained(BaseException):
            pass
        ticks = iter(range(100))
        def sleep(seconds):
            if seconds == 1:
                raise Retained()
        fds = []
        real_pipe = os.pipe2
        def pipe(flags):
            pair = real_pipe(flags)
            fds.extend(pair)
            return pair
        try:
            with mock.patch.object(self.c.os, "fork", return_value=424242), \
                 mock.patch.object(self.c.os, "pipe2", side_effect=pipe), \
                 mock.patch.object(self.c.os, "waitpid", return_value=(424243, 0)), \
                 mock.patch.object(self.c.os, "kill"), \
                 mock.patch.object(self.c.time, "monotonic", side_effect=lambda: next(ticks)), \
                 mock.patch.object(self.c.time, "sleep", side_effect=sleep):
                with self.assertRaises(Retained):
                    self.c.native_job(lambda: None, 0)
                os.fstat(fds[0])
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def test_fork_failure_closes_all_allocated_pipes(self):
        fds = []
        original_pipe = os.pipe2
        def pipe(flags):
            pair = original_pipe(flags)
            fds.extend(pair)
            return pair
        with mock.patch.object(self.c.os, "pipe2", pipe), \
             mock.patch.object(self.c.os, "fork", side_effect=OSError("fork failed")):
            with self.assertRaisesRegex(OSError, "fork failed"):
                self.c.native_job(lambda: None, 5, before=lambda pid: None)
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)


PREFIX_VALUE = 1234567890
PREFIX_PAYLOAD = json.dumps(PREFIX_VALUE).encode()


def fake_writer():
    """Stands in only for the pinned writer's allocate/payload/atomic-publish API."""
    class OperatorIntent:
        def __init__(self, **fields):
            self.fields = fields

        def to_payload(self):
            payload = dict(self.fields)
            for field in ("requested_at", "expires_at"):
                payload[field] = payload[field].isoformat()
            return payload

    def publish(target, text):
        staged = Path(str(target) + ".staged")
        staged.write_text(text)
        os.replace(staged, target)
    return types.SimpleNamespace(
        INTENT_SCHEMA_VERSION=1, OperatorIntent=OperatorIntent, IntentAction=str,
        _allocate_sequence=lambda target, previous: 1, _publish_atomic_json=publish)


class CompletionProofTests(OwnedWorker, unittest.TestCase):
    """Complete-result evidence is separate from post-result worker status.

    The subject defaults to the candidate; ``--subject PATH`` replays these
    exact probes against sealed source5, the baseline or a sabotaged copy.
    """
    subject = ROOT / "owner-custody.py"

    def setUp(self):
        self.c = load_control(subject=self.subject)

    def deliver(self, transform, then=None, seconds=5):
        """Run the actual worker; rewrite its one result write at the OS boundary.

        A small value leaves the child a single write_all() call carrying its
        whole stream (value, then any completion framing), which transform sees.
        """
        original_write = os.write
        parent = os.getpid()
        def write(fd, data):
            if os.getpid() == parent:
                return original_write(fd, data)
            rest = memoryview(transform(bytes(data)))
            while rest:
                rest = rest[original_write(fd, rest):]
            if then:
                then()
            return len(data)
        with mock.patch.object(self.c.os, "write", write):
            return self.run_owned(lambda: PREFIX_VALUE, seconds)

    def test_after_failure_keeps_complete_result_and_actual_status(self):
        def raised():
            raise RuntimeError("after failed")
        for after, code in ((raised, 71), (lambda: os._exit(23), 23)):
            with self.subTest(exit_code=code):
                value = actual_view()
                status, returned = self.run_owned(lambda: value, after=after)
                self.assertEqual(os.waitstatus_to_exitcode(status), code)
                self.assertEqual(returned, value,
                                 "complete 137715-byte result was delivered before after()")

    def test_after_timeout_keeps_complete_result_after_positive_reaping(self):
        value = actual_view()
        start = time.monotonic()
        status, returned = self.run_owned(lambda: value, seconds=1,
                                          after=lambda: time.sleep(20))
        self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGKILL)
        self.assertEqual(returned, value, "killed after delivery; result must survive")
        self.assertLess(time.monotonic() - start, 4)

    def test_injection_harness_delivers_unaltered_stream(self):
        # Positive control: refusals below come from the alteration alone.
        self.assertEqual(self.deliver(lambda stream: stream), (0, PREFIX_VALUE))

    def test_valid_json_prefix_is_not_completion(self):
        prefix = lambda stream: stream[:5]  # b'12345' is valid JSON yet a lie
        def failed():
            raise OSError("injected worker write failure")
        for name, then, seconds, code in (
                ("lying_success", None, 5, 0),
                ("failed_after_prefix", failed, 5, 71),
                ("killed_after_prefix", lambda: time.sleep(20), .3, -signal.SIGKILL)):
            with self.subTest(name):
                status, value = self.deliver(prefix, then, seconds)
                self.assertEqual(os.waitstatus_to_exitcode(status), code)
                self.assertIsNone(value, "syntactically valid prefix accepted as complete")

    def test_short_or_altered_finish_frame_refused(self):
        n = len(PREFIX_PAYLOAD)
        for name, transform in (
                ("payload_without_proof", lambda s: s[:n]),
                ("frame_short_by_one_byte", lambda s: s[:-1]),
                ("cut_payload_intact_proof", lambda s: s[:3] + s[n:]),
                ("same_length_other_payload", lambda s: b"1234567891" + s[n:]),
                ("digest_altered", lambda s: s[:-1] + bytes([s[-1] ^ 1])),
                ("byte_after_proof", lambda s: s + b"0"),
                ("frame_repeated", lambda s: s + s)):
            with self.subTest(name):
                status, value = self.deliver(transform)
                self.assertEqual(status, 0)
                self.assertIsNone(value)

    def test_finish_proof_keeps_one_mib_payload_bound(self):
        def forged(body):
            def transform(stream):
                tag = stream[len(PREFIX_PAYLOAD):-40]
                frame = lambda b: b + tag + len(b).to_bytes(8, "big") + hashlib.sha256(b).digest()
                if frame(PREFIX_PAYLOAD) != stream:
                    raise AssertionError("finish-proof layout assumption is wrong")
                return frame(body)
            return transform
        status, value = self.deliver(forged(b'"' + b"x" * (self.c.MAX - 2) + b'"'))
        self.assertEqual((status, value), (0, "x" * (self.c.MAX - 2)))
        # One byte over MAX with an equally self-consistent proof is refused.
        status, value = self.deliver(forged(b'"' + b"x" * (self.c.MAX - 1) + b'"'))
        self.assertIsNone(value)

    def test_complete_proof_cannot_make_malformed_json_usable(self):
        for body in (b'{"broken":', b'{}{}', b'\xff', b'NaN', b'Infinity'):
            with self.subTest(body=body):
                def malformed(stream):
                    tag = stream[len(PREFIX_PAYLOAD):-40]
                    return body + tag + len(body).to_bytes(8, "big") + hashlib.sha256(body).digest()
                status, value = self.deliver(malformed)
                self.assertEqual(status, 0)
                self.assertIsNone(value)

    def run_guardian(self, written_hook, replace_persisted=False):
        """Actual guardian, fences, native_job, view and receipts; fake writer only."""
        c = self.c
        class Retained(BaseException):
            pass
        real_sleep = time.sleep
        def bounded_sleep(seconds):
            # The 5 s unknown-retry and 1 s retention loops never end by design.
            if seconds >= 1:
                raise Retained()
            real_sleep(seconds)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, store, window = root / "runtime", root / "store", root / "window"
            for env in c.ENVS:
                (runtime / env).mkdir(parents=True)
            store.mkdir()
            (store / "intent-authority.json").write_text(json.dumps(
                dict(highest_sequence=0, intents={}, rejected_sequences=[])))
            op = str(uuid.UUID(int=3))
            operation = window / "ops" / op
            operation.mkdir(parents=True)
            for directory in (window, window / "ops", operation):
                directory.chmod(0o700)
            paths = c.Paths(runtime, store, root / "lifecycle.lock", root / "markers")
            plan = dict(id=op, action="auto", previous=None)
            owned = dict(id=str(uuid.UUID(int=4)), path=str(window))
            def hook(stage, candidate):
                if stage == "written":
                    if replace_persisted:
                        (runtime / "prod/gpu-intent.json").write_text('{"foreign":true}')
                    written_hook()
            handlers = {s: signal.getsignal(s) for s in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
            wfd = os.open(window, os.O_RDONLY | os.O_DIRECTORY)
            ofd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    with mock.patch.object(c.time, "sleep", side_effect=bounded_sleep):
                        c.guardian(wfd, ofd, paths, fake_writer(), plan, owned, hook=hook)
                    outcome = "returned"
                except Retained:
                    outcome = "retained"
                receipts = {name: json.loads((operation / name).read_bytes())
                            for name in os.listdir(operation)}
                held = []
                for fence in [window / "window.lock"] + paths.fences("auto"):
                    fd = os.open(fence, os.O_RDONLY)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        held.append(str(fence.relative_to(root)))
                    finally:
                        os.close(fd)
                persisted = json.loads((runtime / "prod/gpu-intent.json").read_bytes())
                return outcome, receipts, held, persisted
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
                # A retained guardian keeps its fence descriptors by design.
                for name in os.listdir("/proc/self/fd"):
                    try:
                        if int(name) not in (wfd, ofd) and os.readlink(
                                "/proc/self/fd/" + name).startswith(str(root) + "/"):
                            os.close(int(name))
                    except OSError:
                        pass
                os.close(ofd)
                os.close(wfd)

    def test_guardian_after_failure_reaches_persisted_byte_comparison(self):
        def failed():
            raise RuntimeError("written hook failed after publication")
        for name, hook, code in (("after_ok", lambda: None, 0), ("after_failed", failed, 71)):
            with self.subTest(name):
                outcome, receipts, held, persisted = self.run_guardian(hook)
                self.assertEqual(outcome, "returned",
                                 "completed publication discarded: guardian retains fences forever")
                self.assertEqual(held, [])
                self.assertNotIn("unknown.json", receipts)
                stopped = receipts["writer-stopped.json"]
                self.assertEqual(os.waitstatus_to_exitcode(stopped["wait_status"]), code)
                self.assertTrue(stopped["native_reaped"] and stopped["native_publish_completed"])
                self.assertEqual(receipts["result.json"]["outcome"], "published")
                self.assertEqual(receipts["publication.json"], receipts["candidate.json"])
                self.assertEqual(persisted, receipts["candidate.json"])

    def test_guardian_after_timeout_reaches_persisted_byte_comparison(self):
        # Keep the actual guardian's 12 s writer deadline. Bypass only the
        # test's retain-loop escape so the child really stalls and is killed.
        real_sleep = time.sleep
        outcome, receipts, held, persisted = self.run_guardian(lambda: real_sleep(20))
        self.assertEqual(outcome, "returned")
        self.assertEqual(held, [])
        stopped = receipts["writer-stopped.json"]
        self.assertEqual(os.waitstatus_to_exitcode(stopped["wait_status"]), -signal.SIGKILL)
        self.assertTrue(stopped["native_reaped"] and stopped["native_publish_completed"])
        self.assertEqual(receipts["result.json"]["outcome"], "published")
        self.assertEqual(receipts["publication.json"], persisted)
        self.assertEqual(persisted, receipts["candidate.json"])

    def test_guardian_complete_marker_still_requires_persisted_candidate(self):
        outcome, receipts, held, persisted = self.run_guardian(lambda: None, replace_persisted=True)
        self.assertEqual(outcome, "retained")
        self.assertTrue(held)
        self.assertTrue(receipts["writer-stopped.json"]["native_publish_completed"])
        self.assertIn("unknown.json", receipts)
        self.assertNotIn("result.json", receipts)
        self.assertNotIn("publication.json", receipts)
        self.assertNotEqual(persisted, receipts["candidate.json"])


class AuthorityPreservationTests(unittest.TestCase):
    def setUp(self):
        self.c = load_control()
        self.value = actual_view()
        self.previous = max(self.value["publications"].values(), key=lambda p: p["sequence"])
        self.known = {"owned": self.previous}

    def test_transport_preserves_all_fields_then_actual_guard_accepts(self):
        status, value = self.c.native_job(lambda: self.value, 5)
        self.assertEqual(status, 0)
        self.assertEqual(value, self.value)
        self.assertEqual(self.c.guard(value, self.previous, self.known,
                                     self.previous["requested_by"], "auto"), 261)
        self.assertEqual(set(value["authority"]),
                         {"highest_sequence", "intents", "last_wall_time",
                          "rejected_sequences", "schema_version", "sequences"})

    def test_foreign_publication_and_newer_authority_and_rejection_survive(self):
        def foreign(v):
            pub = copy.deepcopy(self.previous)
            pub["nonce"] = str(uuid.UUID(int=999999))
            v["publications"]["/offline/foreign/gpu-intent.json"] = pub
        def newer(v):
            v["authority"]["highest_sequence"] += 1
        def rejected(v):
            v["authority"]["rejected_sequences"] = [1]
        def conflict(v):
            v["authority"]["intents"][self.previous["nonce"]]["publication"]["requested_by"] = "foreign"
        def deferred(v):
            v["deferred"] = {"nonce": "foreign", "sequence": 261}
        def older_record(v):
            oldest = min(v["authority"]["intents"].values(), key=lambda r: r["sequence"])
            oldest["sequence"] = 262
        for mutation, message in ((foreign, "foreign publication"), (newer, "newer authority"),
                                  (rejected, "rejection history"), (conflict, "conflicting authority"),
                                  (deferred, "foreign deferred"), (older_record, "newer authority record")):
            with self.subTest(mutation=mutation.__name__):
                value = copy.deepcopy(self.value)
                mutation(value)
                status, returned = self.c.native_job(lambda: value, 5)
                self.assertEqual((status, returned), (0, value))
                with self.assertRaisesRegex(RuntimeError, message):
                    self.c.guard(returned, self.previous, self.known,
                                 self.previous["requested_by"], "auto")

    def test_owner_and_first_use_and_stop_load_proofs_unchanged(self):
        with self.assertRaisesRegex(RuntimeError, "other window"):
            self.c.guard(self.value, self.previous, self.known, "foreign", "auto")
        with self.assertRaisesRegex(RuntimeError, "first-use changed"):
            self.c.guard(self.value, None, {}, "foreign", "auto")
        with self.assertRaisesRegex(RuntimeError, "load inventory"):
            self.c.guard(self.value, self.previous, self.known,
                         self.previous["requested_by"], "stop")
        idle = dict(written_at=time.time(), queue_depth=0, in_flight=0,
                    batch_in_progress=False, lease_demand=0, revision=1)
        self.value["loads"] = [copy.deepcopy(idle) for _ in self.c.ENVS]
        status, returned = self.c.native_job(lambda: self.value, 5)
        self.assertEqual(status, 0)
        self.c.guard(returned, self.previous, self.known, self.previous["requested_by"], "stop")
        returned["loads"][0]["in_flight"] = 1
        with self.assertRaisesRegex(RuntimeError, "work/demand"):
            self.c.guard(returned, self.previous, self.known, self.previous["requested_by"], "stop")


def verify_production_scope(custody, client, reference="source5-owner-custody.py"):
    """A owns native_job; declared sibling B owns known_candidates/operation.

    The only additive global slot is new, literal positive integer constants
    <=1024, consumed exclusively by B's two functions. Existing globals (MAX,
    pins, imports), every other function/class and all signatures stay fixed.
    This recognizes B's constant names from actual uses, without allowing a
    wildcard function exemption or requiring B's source in A's workspace.
    """
    sources = {"custody": custody, "client": client}
    originals = {"custody": (ROOT / "fixtures" / reference).read_text(),
                 "client": (ROOT / "fixtures/source5-owner-window.py").read_text()}
    regions = {"custody": {"native_job", "known_candidates"}, "client": {"operation"}}
    sibling = {"custody": {"known_candidates"}, "client": {"operation"}}
    trees = {key: ast.parse(text) for key, text in sources.items()}
    bases = {key: ast.parse(text) for key, text in originals.items()}
    additions = {key: [] for key in sources}
    constants = set()
    for key, tree in trees.items():
        existing = {n.id for n in ast.walk(bases[key]) if isinstance(n, ast.Name)}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id not in existing):
                name = node.targets[0].id
                assert key == "custody", "new constants belong to custody budget scope"
                assert name.isupper() and name not in constants, "undeclared constant"
                assert (isinstance(node.value, ast.Constant) and type(node.value.value) is int
                        and 0 < node.value.value <= 1024), "budget constant must be bounded literal"
                constants.add(name)
                additions[key].append(node)
    used = set()
    for key, tree in trees.items():
        for node in tree.body:
            if node in additions[key]:
                continue
            references = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            references |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            found = references & constants
            if found:
                assert isinstance(node, ast.FunctionDef) and node.name in sibling[key], \
                    "budget constant escaped declared sibling functions"
                used |= found
    assert used == constants, "unused budget constant"

    def normalized(text, tree, key, new=False):
        lines = text.splitlines(keepends=True)
        spans = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in regions[key]:
                spans.append((node.lineno - 1, node.end_lineno, f"<body:{node.name}>\n"))
        if new:
            for node in additions[key]:
                start = node.lineno - 1
                # New constant documentation belongs to the same narrow slot.
                while start and lines[start - 1].lstrip().startswith("#"):
                    start -= 1
                spans.append((start, node.end_lineno, ""))
        for start, end, replacement in sorted(spans, reverse=True):
            lines[start:end] = [replacement]
        return "".join(line for line in lines if line.strip())

    for key, tree in trees.items():
        for name in regions[key]:
            old = next(n for n in bases[key].body if isinstance(n, ast.FunctionDef) and n.name == name)
            new = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
            assert len(new) == 1, "missing/duplicate declared function"
            for field in ("args", "decorator_list", "returns", "type_comment"):
                left, right = getattr(old, field), getattr(new[0], field)
                assert (ast.dump(left) if isinstance(left, ast.AST) else left) == \
                       (ast.dump(right) if isinstance(right, ast.AST) else right), "function interface changed"
        assert normalized(originals[key], bases[key], key) == normalized(sources[key], tree, key, True), \
            "production bytes outside declared regions changed"
    return sorted(constants)


class SourceCustodyTests(unittest.TestCase):
    def test_only_declared_production_regions_changed(self):
        for reference in ("original-owner-custody.py", "source5-owner-custody.py"):
            verify_production_scope((ROOT / "owner-custody.py").read_text(),
                                    (ROOT / "owner-window.py").read_text(), reference)

    def test_scope_verifier_allows_only_declared_sibling_budget_regions(self):
        custody = (ROOT / "fixtures/source5-owner-custody.py").read_text()
        client = (ROOT / "fixtures/source5-owner-window.py").read_text()
        # In-memory scope probe, never copied into the production tree.
        combined = custody.replace("MAX=1048576", "MAX=1048576\nOPERATION_LIMIT=1024\nCLEANUP_RESERVE=4")
        combined = combined.replace("len(names)<=32", "len(names)<=OPERATION_LIMIT")
        budget_client = client.replace("def operation(wfd,w,action,previous):",
                                      "def operation(wfd,w,action,previous):\n c.check(c.CLEANUP_RESERVE<c.OPERATION_LIMIT,'budget')")
        self.assertEqual(verify_production_scope(combined, budget_client),
                         ["CLEANUP_RESERVE", "OPERATION_LIMIT"])
        for bad, bad_client in ((combined.replace("MAX=1048576", "MAX=2097152"), budget_client),
                                (combined.replace("def guard(v,previous,known,actor,mode):",
                                                  "def guard(v,previous,known,actor,mode):\n return 0"), budget_client),
                                (combined.replace("OPERATION_LIMIT=1024", "OPERATION_LIMIT=999999"), budget_client),
                                (combined + "\ndef unrelated(): return OPERATION_LIMIT\n", budget_client),
                                (combined, budget_client.replace("def reconciled(wfd):", "def reconciled(wfd):\n return None"))):
            with self.subTest(bad=hashlib.sha256((bad + bad_client).encode()).hexdigest()):
                with self.assertRaises(AssertionError):
                    verify_production_scope(bad, bad_client)

    def test_sealed_source5_inputs_match_expected_hashes(self):
        source5 = (ROOT / "fixtures/source5-owner-custody.py").read_bytes()
        self.assertEqual(hashlib.sha256(source5).hexdigest(), SOURCE5_SHA)
        # A's actual tree leaves B's regions untouched; the composition-aware
        # check above still verifies all other production function bytes.
        self.assertEqual(hashlib.sha256((ROOT / "fixtures/source5-owner-window.py").read_bytes()).hexdigest(),
                         "1983f8684de3d03a59c090b1b469e65f5b84ad201283e787bdf5fb872b8b6600")

    def test_sealed_fixture_and_original_script_match_manifest(self):
        raw = (ROOT / "fixtures/input-manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "80f7267a090a69fbe05e8a55ce6dce4f9c958290db3a9c97f1efc67cda95e7fc")
        manifest = json.loads(raw)
        for row in manifest["files"]:
            name = row["path"]
            if name == "actual-view.json":
                path = ROOT / "fixtures/actual-view.json"
            elif name == "baseline/owner-custody.py":
                path = ROOT / "fixtures/original-owner-custody.py"
            elif name == "baseline/owner-window.py":
                path = ROOT / "fixtures/source5-owner-window.py"
            elif name.startswith("baseline/"):
                path = ROOT / Path(name).name
            else:
                continue
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
            self.assertEqual(path.stat().st_size, row["bytes"])


if __name__ == "__main__":
    if "--baseline" in sys.argv:
        NativeRealShapeTests.original = True
        sys.argv.remove("--baseline")
    if "--subject" in sys.argv:
        index = sys.argv.index("--subject")
        CompletionProofTests.subject = ROOT / sys.argv[index + 1]
        del sys.argv[index:index + 2]
    unittest.main()
