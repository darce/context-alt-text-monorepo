#!/usr/bin/env python3
"""Private stdlib guardian publication controls; no live paths or role adoption."""
import copy
from datetime import UTC, datetime, timedelta
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
spec = importlib.util.spec_from_file_location('ttl_custody', HERE / 'owner-custody.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
WRITER = REPO / 'apps/prototype-description-service/scene/application'


class PublicationTTL(unittest.TestCase):
    def run_publication(self, action, maximum=None):
        writer = c.load_writer((WRITER / 'gpu_intent.py').read_bytes(),
                               (WRITER / 'describe_load.py').read_bytes())
        now = datetime(2026, 10, 19, tzinfo=UTC)
        with tempfile.TemporaryDirectory(prefix='window-ttl.') as name:
            root = Path(name)
            window = dict(id=str(uuid.uuid4()), path=name)
            actor = 'ubuntu:QWEN-OWNER-ADMISSION:capacity-only:' + window['id']
            previous_id = str(uuid.uuid4())
            for directory in ('ops', 'ops/' + previous_id, 'next', 'store', 'markers'):
                (root / directory).mkdir(mode=0o700)
            for env in c.ENVS:
                (root / 'runtime' / env).mkdir(parents=True, mode=0o700)
                (root / 'runtime' / env / 'describe-load.json').write_text(json.dumps(
                    dict(written_at=time.time(), queue_depth=0, in_flight=0, batch_in_progress=False)))
            paths = c.Paths(root / 'runtime', root / 'store', root / 'lifecycle.lock',
                            root / 'markers', now=lambda: now)
            old = writer.OperatorIntent(1, 1, writer.IntentAction.START,
                now - timedelta(seconds=100), now + timedelta(seconds=500),
                600, actor, str(uuid.uuid4())).to_payload()
            paths.target.write_text(json.dumps(old))
            authority = dict(highest_sequence=1, intents={old['nonce']: dict(
                sequence=1, publication={k: old[k] for k in (
                    'action', 'requested_at', 'expires_at', 'ttl_seconds', 'requested_by', 'sequence')},
                monotonic_expires_at=12345)}, running_origin=dict(nonce=old['nonce'], monotonic_since=100))
            authority_path = paths.store / 'intent-authority.json'
            authority_path.write_text(json.dumps(authority))
            paths.store.joinpath('deferred-stop.json').write_text('null')
            before = authority_path.read_bytes()
            wfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            prior = c.subdir(cfd := c.subdir(wfd, 'ops'), previous_id)
            c.seal(prior, 'candidate.json', old)
            c.seal(prior, 'result.json', dict(outcome='published'))
            old_bytes = c.read_at(prior, 'candidate.json')
            ofd = c.subdir(wfd, 'next')
            if maximum is not None:
                writer.MAX_INTENT_TTL_SECONDS = maximum
            try:
                # Only replace inventory lookup: all guard comparisons, locks,
                # constructor, worker, atomic publication and reconciliation run.
                with patch.object(c, 'known_candidates', return_value={previous_id: copy.deepcopy(old)}), \
                     patch.object(c.signal, 'signal'):
                    c.guardian(wfd, ofd, paths, writer,
                               dict(id=str(uuid.uuid4()), action=action, previous=previous_id), window)
                result = c.load_json(ofd, 'result.json')
                self.assertEqual(authority_path.read_bytes(), before)
                self.assertEqual(c.read_at(prior, 'candidate.json'), old_bytes)
                self.assertEqual(c.load_json(prior, 'candidate.json'), old)
                self.assertEqual(old['ttl_seconds'], 600)
                if maximum is not None:
                    self.assertEqual(result['outcome'], 'refused')
                    self.assertIn('fixed publication TTL outside native writer bounds', result['error'])
                    self.assertFalse((root / 'next/candidate.json').exists())
                    self.assertEqual(json.loads(paths.target.read_bytes()), old)
                else:
                    self.assertEqual(result['outcome'], 'published')
                    payload = c.load_json(ofd, 'publication.json')
                    self.assertEqual(payload, json.loads(paths.target.read_bytes()))
                    self.assertEqual(payload, c.load_json(ofd, 'candidate.json'))
                    self.assertEqual(payload['ttl_seconds'], 1800)
                    self.assertEqual(datetime.fromisoformat(payload['requested_at']), now)
                    self.assertEqual(datetime.fromisoformat(payload['expires_at']) - now, timedelta(seconds=1800))
                    self.assertEqual(payload['action'], action)
                    self.assertEqual(payload['sequence'], 2)
                    self.assertNotEqual(payload['nonce'], old['nonce'])
            finally:
                for fd in (ofd, prior, cfd, wfd):
                    os.close(fd)

    def test_future_publications_preserve_previous_receipt_and_origin(self):
        for action in ('start', 'stop', 'auto'):
            with self.subTest(action=action):
                self.run_publication(action)

    def test_native_maximum_refuses_before_candidate_or_publication(self):
        self.run_publication('start', maximum=1799)


if __name__ == '__main__':
    unittest.main()
