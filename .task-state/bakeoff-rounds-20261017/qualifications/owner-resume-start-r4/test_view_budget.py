#!/usr/bin/env python3
"""Bounded owner-custody view (RES-05) private unit controls.

The real pinned writer, the real guardian, real fences and real bounded reads run
on private temporary state. Only the native authority is emulated, by writing its
persisted records. No root, VM, service, live path or network is used.
Run: timeout 120s python3 -B -m pytest test_view_budget.py -q
"""
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

HERE = Path(__file__).resolve().parent
REPO = next(p for p in HERE.parents if (p / 'apps').is_dir())
WRITER = REPO / 'apps/prototype-description-service/scene/application'
spec = importlib.util.spec_from_file_location('view_budget_custody', HERE / 'owner-custody.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

WINDOW = '223eb2de-b63a-4b19-a31e-a34d07a8e187'
ACTOR = 'ubuntu:QWEN-OWNER-ADMISSION:capacity-only:' + WINDOW
FENCED = 340  # >=300 fenced records (>140 KB); fenced history alone exceeds the 60000-byte budget
PUBLICATION_KEYS = ('action', 'requested_at', 'expires_at', 'ttl_seconds', 'requested_by', 'sequence')


class Abort(Exception):
    """Ends the guardian's endless unknown-outcome retry loop in a unit control."""


def native_record(candidate):
    """Persisted intent-authority record for one publication."""
    return dict(sequence=candidate['sequence'], publication={k: candidate[k] for k in PUBLICATION_KEYS},
                monotonic_expires_at=12345.0)


def fenced_records():
    records = {}
    for n in range(1, FENCED + 1):
        nonce = str(uuid.UUID(int=0x1000 + n))
        candidate = dict(sequence=n, action='auto', requested_at='2026-10-18T17:56:00Z',
                         expires_at='2026-10-18T18:06:00Z', ttl_seconds=600, requested_by=ACTOR, nonce=nonce)
        records[nonce] = native_record(candidate)
    return records


class ViewBudget(unittest.TestCase):
    def setUp(self):
        self.writer = c.load_writer((WRITER / 'gpu_intent.py').read_bytes(),
                                    (WRITER / 'describe_load.py').read_bytes())
        self.tmp = tempfile.TemporaryDirectory(prefix='view-budget.')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.window = dict(id=WINDOW, path=str(self.root / 'window'))
        for name in ('window', 'store', 'markers', 'runtime'):
            (self.root / name).mkdir(mode=0o700)
        (self.root / 'window/ops').mkdir(mode=0o700)
        self.wfd = os.open(self.root / 'window', os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.wfd)
        for env in c.ENVS:
            (self.root / 'runtime' / env).mkdir(mode=0o700)
            (self.root / 'runtime' / env / 'describe-load.json').write_text(json.dumps(dict(
                written_at=time.time(), queue_depth=0, in_flight=0, batch_in_progress=False)))
        self.paths = c.Paths(self.root / 'runtime', self.root / 'store',
                             self.root / 'lifecycle.lock', self.root / 'markers')
        self.authority_path = self.paths.store / 'intent-authority.json'

    def write_authority(self, highest, records):
        raw = dict(highest_sequence=highest, rejected_sequences=[], intents=records)
        self.authority_path.write_text(json.dumps(raw, indent=2, sort_keys=True))

    def edit_authority(self, edit):
        """Emulate native authority writes; the guardian never edits this file."""
        raw = json.loads(self.authority_path.read_bytes())
        edit(raw)
        self.authority_path.write_text(json.dumps(raw, indent=2, sort_keys=True))

    def persist_native(self, candidate):
        """Native authority records a persisted publication; the guardian never does."""
        def record(raw):
            raw['intents'][candidate['nonce']] = native_record(candidate)
            raw['highest_sequence'] = candidate['sequence']
        self.edit_authority(record)

    def seed_operation(self, candidate):
        """Persisted, published operation whose candidate custody the guardian resumes."""
        op = str(uuid.uuid4())
        ops = c.subdir(self.wfd, 'ops')
        ofd = c.subdir(ops, op, create=True)
        os.close(ops)
        try:
            c.seal(ofd, 'candidate.json', candidate)
            c.seal(ofd, 'result.json', dict(outcome='published', operation=op, window=WINDOW, writer_wait_status=0))
        finally:
            os.close(ofd)
        return op

    def seed_predecessor(self):
        """Fenced history plus one published predecessor at FENCED+1 (the floor)."""
        now = datetime.now(UTC)
        candidate = self.writer.OperatorIntent(1, FENCED + 1, self.writer.IntentAction.AUTO, now,
                                               now + timedelta(seconds=1800), 1800, ACTOR,
                                               str(uuid.uuid4())).to_payload()
        op = self.seed_operation(candidate)
        self.paths.target.write_text(json.dumps(candidate, separators=(',', ':')))
        records = fenced_records()
        records[candidate['nonce']] = native_record(candidate)
        self.write_authority(FENCED + 1, records)
        return op, candidate

    def guardian(self, action, previous, op=None):
        """Real guardian for one operation; returns (operation id, sealed result)."""
        op = op or str(uuid.uuid4())
        ops = c.subdir(self.wfd, 'ops')
        ofd = c.subdir(ops, op, create=True)
        os.close(ops)
        try:
            with patch.object(c.signal, 'signal'):
                c.guardian(self.wfd, ofd, self.paths, self.writer,
                           dict(id=op, action=action, previous=previous), self.window)
            return op, c.load_json(ofd, 'result.json')
        finally:
            os.close(ofd)

    def operation_file(self, op, name):
        return self.root / 'window/ops' / op / name

    def test_stop_view_is_bounded_by_the_floor_not_the_authority(self):
        _, predecessor = self.seed_predecessor()
        raw = self.authority_path.read_bytes()
        self.assertGreater(len(raw), 140_000)
        v = c.view(self.paths, 'stop', predecessor['sequence'])
        self.assertLess(len(json.dumps(v).encode()), 60000)
        self.assertEqual(len(v['loads']), 5)
        self.assertEqual(v['authority']['intent_count'], FENCED + 1)
        self.assertEqual(list(v['authority']['intents']), [predecessor['nonce']])
        self.assertEqual(v['authority']['sha256'], hashlib.sha256(raw).hexdigest())

    def test_start_stop_auto_publish_over_fenced_authority(self):
        previous_op, predecessor = self.seed_predecessor()
        sequence = predecessor['sequence']
        for action in ('start', 'stop', 'auto'):
            op, result = self.guardian(action, previous_op)
            self.assertEqual(result['outcome'], 'published', result.get('error'))
            candidate = c.known_candidates(self.wfd)[op]
            sequence += 1
            self.assertEqual((candidate['action'], candidate['sequence']), (action, sequence))
            self.assertEqual(json.loads(self.paths.target.read_bytes()), candidate)
            self.persist_native(candidate)
            previous_op = op

    def test_first_use_empty_authority_publishes(self):
        self.write_authority(0, {})
        _, result = self.guardian('start', None)
        self.assertEqual(result['outcome'], 'published', result.get('error'))
        self.assertEqual(json.loads(self.paths.target.read_bytes())['sequence'], 1)

    def test_first_use_with_nonempty_authority_refused(self):
        self.write_authority(1, {str(uuid.UUID(int=0x2001)): dict(sequence=1, publication={})})
        op, result = self.guardian('start', None)
        self.assertEqual(result, dict(outcome='refused', operation=op, window=WINDOW,
                                      error='RuntimeError: first-use changed; preserve foreign state'))
        self.assertFalse(self.paths.target.exists())

    def test_first_use_refuses_on_intent_count_when_projection_is_empty(self):
        raw = b'{"highest_sequence":0,"intents":{"n":{"sequence":1,"publication":{}}}}'
        v = dict(authority=c.project_authority(raw, 2), publications={}, loads=[], deferred=None)
        self.assertEqual(v['authority']['intents'], {})
        with self.assertRaisesRegex(RuntimeError, 'first-use changed'):
            c.guard(v, None, {}, ACTOR, 'auto')

    def test_newer_authority_above_predecessor_refused(self):
        previous_op, predecessor = self.seed_predecessor()
        self.edit_authority(lambda raw: raw.__setitem__('highest_sequence', predecessor['sequence'] + 1))
        _, result = self.guardian('start', previous_op)
        self.assertEqual(result['outcome'], 'refused')
        self.assertEqual(result['error'], 'RuntimeError: newer authority')

    def test_newer_record_above_predecessor_refused(self):
        previous_op, predecessor = self.seed_predecessor()

        def add_newer_record(raw):
            raw['intents'][str(uuid.UUID(int=0x3001))] = dict(sequence=predecessor['sequence'] + 1, publication={})
        self.edit_authority(add_newer_record)
        _, result = self.guardian('start', previous_op)
        self.assertEqual(result['outcome'], 'refused')
        self.assertEqual(result['error'], 'RuntimeError: newer authority record')

    def test_conflicting_record_at_predecessor_refused(self):
        previous_op, predecessor = self.seed_predecessor()

        def replace_with_conflict(raw):
            del raw['intents'][predecessor['nonce']]
            other = dict(predecessor, nonce=str(uuid.uuid4()))
            raw['intents'][other['nonce']] = native_record(other)
        self.edit_authority(replace_with_conflict)
        _, result = self.guardian('start', previous_op)
        self.assertEqual(result['outcome'], 'refused')
        self.assertEqual(result['error'], 'RuntimeError: conflicting authority')

    def test_unchanged_authority_without_persisted_publication_is_not_published(self):
        # The native writer reports completion but the target is never replaced.
        previous_op, _ = self.seed_predecessor()
        with patch.object(self.writer, '_publish_atomic_json'):
            op, result = self.guardian('stop', previous_op)
        self.assertEqual(result['outcome'], 'not-published')
        stopped = json.loads(self.operation_file(op, 'writer-stopped.json').read_bytes())
        self.assertIs(stopped['native_publish_completed'], True)

    def test_authority_change_below_floor_is_not_not_published(self):
        previous_op, _ = self.seed_predecessor()
        fenced_one = str(uuid.UUID(int=0x1001))
        real_sleep = time.sleep

        def purge_fenced(path, payload):
            # Native purge of a fenced record: bytes change below the floor.
            self.edit_authority(lambda raw: raw['intents'].pop(fenced_one))

        def stop_retry_loop(seconds):
            if seconds >= 1:
                raise Abort()
            real_sleep(seconds)

        op = str(uuid.uuid4())
        with patch.object(self.writer, '_publish_atomic_json', side_effect=purge_fenced), \
                patch.object(c.time, 'sleep', side_effect=stop_retry_loop):
            with self.assertRaises(Abort):
                self.guardian('stop', previous_op, op=op)
        self.assertNotIn(fenced_one, json.loads(self.authority_path.read_bytes())['intents'])
        self.assertTrue(self.operation_file(op, 'unknown.json').exists())
        self.assertFalse(self.operation_file(op, 'result.json').exists())

    def test_projection_digest_covers_bytes_and_hides_only_fenced_records(self):
        _, predecessor = self.seed_predecessor()
        raw = self.authority_path.read_bytes()
        bounded = c.project_authority(raw, predecessor['sequence'])
        self.assertEqual(bounded['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(bounded['intent_count'], FENCED + 1)
        self.assertEqual(list(bounded['intents']), [predecessor['nonce']])
        self.assertEqual(list(c.project_authority(raw, None)['intents']), [predecessor['nonce']])
        tampered = json.loads(raw)
        del tampered['intents'][str(uuid.UUID(int=0x1001))]
        changed = c.project_authority(json.dumps(tampered, indent=2, sort_keys=True).encode(),
                                      predecessor['sequence'])
        self.assertNotEqual(changed['sha256'], bounded['sha256'])
        self.assertEqual(changed['intents'], bounded['intents'])


if __name__ == '__main__':
    unittest.main()
