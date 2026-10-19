"""Stdlib tests: private temporary files and a Docker-inspect-shaped fake only."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).parent
loader = importlib.util.spec_from_file_location('maintenance', HERE / 'gpu_vllm_maintenance.py')
m = importlib.util.module_from_spec(loader)
loader.loader.exec_module(m)
OP = '12345678-1234-4234-8234-123456789abc'


def original():
    # Shape from reference_maintenance_template.py's actual docker inspect consumer.
    return {'Id': 'original-container', 'Image': m.ORIGINAL_IMAGE,
            'Config': {'Image': 'original-reference', 'Cmd': ['serve'],
                       'Entrypoint': None, 'Env': ['PRIVATE=not-exported'],
                       'WorkingDir': '/', 'User': '', 'Labels': {}},
            'HostConfig': {'AutoRemove': True, 'NetworkMode': 'host', 'PortBindings': {}},
            'State': {'Running': True, 'Pid': 123}}


class Fake:
    def __init__(self):
        self.old = original()
        self.candidate = None
        self.calls = []
        self.fail_start = False
        self.fail_restore = False
        self.now = 0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def run(self, args, timeout, env=None):
        assert 0 < timeout <= 120
        self.calls.append((list(args), env))
        rc, out, err = 0, '', ''
        if args[:3] == ['docker', 'image', 'inspect']:
            out = json.dumps([{'Id': m.CANDIDATE_IMAGE, 'RepoDigests': [m.CANDIDATE_REF]}])
        elif args[:2] == ['docker', 'inspect']:
            obj = self.old if args[2] == 'acx-gpu-vlm' else self.candidate
            if obj is None:
                rc, err = 1, 'Error: No such object: ' + args[2]
            else:
                out = json.dumps([obj])
        elif args[:2] == ['docker', 'stop']:
            self.candidate = None
        elif args[:2] == ['systemctl', 'show']:
            out = ('ActiveState=active\nUnitFileState=enabled\n' if args[2] == m.ORIGINAL_SERVICE
                   else ('LoadState=loaded\nActiveState=deactivating\nSubState=stop-post\nMainPID=0\n'
                         if 'MainPID' in args else 'LoadState=not-found\n'))
        elif args[:2] == ['systemctl', 'stop']:
            if args[2] == m.ORIGINAL_SERVICE:
                self.old = None
        elif args[:2] == ['systemctl', 'start']:
            if self.fail_restore:
                rc = 1
            else:
                self.old = original()
        elif args[0] == 'systemd-run':
            if self.fail_start:
                rc = 1
            else:
                self.candidate = {'Id': 'candidate-container',
                                  'Name': '/workbay-bakeoff-vllm-' + OP,
                                  'Image': m.CANDIDATE_IMAGE,
                                  'Config': {'Labels': {'workbay.owner': 'Bakeoff',
                                                       'workbay.operation': OP}},
                                  'State': {'Running': True, 'Pid': 456}}
        elif args[0] == 'nvidia-smi':
            out = 'GPU-unique, NVIDIA A10\n'
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, rc, out, err)


class Harness(m.Runtime):
    def validate_assets(self):
        self.assets_checked = True

    def weight_stats(self):
        return [{'path': p, 'bytes': 42, 'ino': i, 'mtime_ns': 99}
                for i, p in enumerate(m.ORIGINAL_WEIGHTS)]

    def binary_hash(self, container):
        return m.ORIGINAL_BINARY

    def host_capacity(self):
        pass


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / ('bakeoff-vllm-' + OP.replace('-', ''))
        self.root.mkdir(mode=0o700)
        self.spec = {'version': 1, 'operation': OP, 'original_network_mode': 'host',
                     'original_port_bindings': {}}
        for name, data in [('gpu_vllm_maintenance.py', b'# reviewed helper'),
                           ('spec.json', json.dumps(self.spec).encode()),
                           ('api-key', os.urandom(32).hex().encode())]:
            p = self.root / name
            p.write_bytes(data)
            p.chmod(0o400)
        self.fake = Fake()
        self.policy = m.FilePolicy(os.getuid(), os.getgid(), Path(self.tmp.name))
        self.runtime = Harness(self.root, OP, self.root / 'spec.json',
                               runner=self.fake.run, clock=self.fake.clock,
                               sleep=self.fake.sleep,
                               http=lambda path, key, timeout: (200, {'data': [{'id': m.MODEL}]}),
                               policy=self.policy)
        self.pin = patch.object(m, 'ORIGINAL_CONFIG', m.config_hash(original()))
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def test_prepare_and_restore_distinct_images_idempotent(self):
        receipt = self.runtime.prepare()
        self.assertEqual(receipt['status'], 'ready')
        before = json.loads((self.root / 'before.json').read_text())
        self.assertNotEqual(before['original_image_id'], before['candidate_image_id'])
        self.assertNotIn('Env', json.dumps(before))
        self.assertEqual(self.runtime.restore()['status'], 'restored')
        calls = len(self.fake.calls)
        self.assertEqual(self.runtime.restore()['status'], 'restored')
        self.assertEqual(calls, len(self.fake.calls))
        self.assertFalse((self.root / 'api-key').exists())
        self.assertEqual(self.fake.old['Image'], m.ORIGINAL_IMAGE)

    def test_foreign_candidate_untouched(self):
        self.runtime.prepare()
        for field in ('label', 'image'):
            candidate = copy.deepcopy(self.fake.candidate)
            if field == 'label':
                self.fake.candidate['Config']['Labels']['workbay.owner'] = 'foreign'
            else:
                self.fake.candidate['Image'] = m.ORIGINAL_IMAGE
            start = len(self.fake.calls)
            with self.assertRaises(m.Refusal):
                self.runtime.restore()
            self.assertFalse(any(c[0][:2] in (['docker', 'stop'], ['systemctl', 'start'])
                                 for c in self.fake.calls[start:]))
            self.fake.candidate = candidate
        self.assertTrue((self.root / 'api-key').exists())

    def test_original_drift_refused_before_stop(self):
        for kind in ('Image', 'Config'):
            self.fake.old = original()
            if kind == 'Image':
                self.fake.old['Image'] = m.CANDIDATE_IMAGE
            else:
                self.fake.old['Config']['Cmd'] = ['changed']
            with self.assertRaises(m.Refusal):
                self.runtime.prepare()
            (self.root / 'restore.lock').unlink()
            self.assertFalse(any(c[0][:2] == ['systemctl', 'stop'] for c in self.fake.calls))

    def test_start_failure_restores_and_preserves_uncertainty(self):
        self.fake.fail_start = True
        self.fake.fail_restore = True
        with self.assertRaisesRegex(m.Refusal, 'launch failed.*restoration unknown'):
            self.runtime.prepare()
        self.assertTrue((self.root / 'before.json').exists())
        self.assertTrue((self.root / 'api-key').exists())
        self.assertFalse((self.root / 'restored.json').exists())
        self.fake.fail_restore = False
        self.assertEqual(self.runtime.restore()['status'], 'restored')

    def test_secret_not_in_argv_or_receipts(self):
        key = (self.root / 'api-key').read_text()
        receipt = self.runtime.prepare()
        self.assertNotIn(key, json.dumps([c[0] for c in self.fake.calls]))
        self.assertNotIn(key, json.dumps(receipt))
        for p in self.root.glob('*.json'):
            self.assertNotIn(key, p.read_text())
        launch = next(c for c in self.fake.calls if c[0][0] == 'systemd-run')
        self.assertEqual(launch[1]['VLLM_API_KEY'], key)
        self.assertIn('--setenv=VLLM_API_KEY', launch[0])
        self.assertIn('--env', launch[0])

    def test_readiness_has_fixed_deadline_and_checks_models(self):
        self.runtime.http = lambda path, key, timeout: (200, {'data': [{'id': 'wrong'}]})
        with self.assertRaises(m.Refusal):
            self.runtime.prepare()
        self.assertLessEqual(self.fake.now, 240)
        self.assertTrue((self.root / 'restored.json').exists())

    def test_invalid_paths_specs_and_partial_launch(self):
        with self.assertRaises(m.Refusal):
            m.Runtime(self.root, '../bad', self.root / 'spec.json', policy=self.policy)
        self.spec['extra_flags'] = ['untrusted']
        (self.root / 'spec.json').chmod(0o600)
        (self.root / 'spec.json').write_text(json.dumps(self.spec))
        (self.root / 'spec.json').chmod(0o400)
        with self.assertRaises(m.Refusal):
            self.runtime.prepare()
        self.assertEqual(self.fake.calls, [])

    def test_secure_files_reject_symlink_hardlink_and_permissions(self):
        p = self.root / 'api-key'
        p.chmod(0o600)
        with self.assertRaises(m.Refusal):
            self.runtime.prepare()
        p.chmod(0o400)
        os.link(p, self.root / 'other')
        with self.assertRaises(m.Refusal):
            self.policy.read(p, 4096)
        (self.root / 'other').unlink()
        p.unlink()
        p.symlink_to(self.root / 'spec.json')
        with self.assertRaises((m.Refusal, OSError)):
            self.runtime.prepare()

    def test_candidate_pin_checked_before_incumbent_stop(self):
        delegate = self.fake.run
        for wrong in ({'Id': m.ORIGINAL_IMAGE, 'RepoDigests': [m.CANDIDATE_REF]},
                      {'Id': m.CANDIDATE_IMAGE, 'RepoDigests': ['mutable:latest']}):
            def run(args, timeout, env=None):
                result = delegate(args, timeout, env)
                if args[:3] == ['docker', 'image', 'inspect']:
                    result.stdout = json.dumps([wrong])
                return result
            self.runtime.runner = run
            with self.assertRaisesRegex(m.Refusal, 'candidate image pin drift'):
                self.runtime.prepare()
            (self.root / 'restore.lock').unlink()
        self.assertFalse(any(c[0][:2] == ['systemctl', 'stop'] for c in self.fake.calls))
        self.assertFalse((self.root / 'before.json').exists())

    def test_assets_corruption_before_stop(self):
        def corrupted():
            raise m.Refusal('model asset digest refused')
        self.runtime.validate_assets = corrupted
        with self.assertRaisesRegex(m.Refusal, 'asset digest'):
            self.runtime.prepare()
        self.assertFalse(any(c[0][:2] == ['systemctl', 'stop'] for c in self.fake.calls))

    def test_real_asset_hash_length_and_symlink_validation(self):
        path = Path(self.tmp.name) / 'asset'
        data = b'private temporary model stand-in'
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.runtime.validate_asset(path, len(data), digest)
        path.write_bytes(data[:-1] + b'X')
        with self.assertRaisesRegex(m.Refusal, 'digest'):
            self.runtime.validate_asset(path, len(data), digest)
        with self.assertRaisesRegex(m.Refusal, 'size/type'):
            self.runtime.validate_asset(path, len(data) + 1, digest)
        other = Path(self.tmp.name) / 'link'
        other.symlink_to(path)
        with self.assertRaises(OSError):
            self.runtime.validate_asset(other, len(data), digest)
        self.assertEqual(len(m.ASSETS), 14)

    def test_no_partial_prepare_adoption_or_receipt_overwrite(self):
        self.runtime.prepare()
        sealed = (self.root / 'before.json').read_bytes()
        calls = len(self.fake.calls)
        with self.assertRaisesRegex(m.Refusal, 'existing operation'):
            self.runtime.prepare()
        self.assertEqual(calls, len(self.fake.calls))
        with self.assertRaises(FileExistsError):
            self.policy.publish(self.root / 'before.json', {'replace': True})
        self.assertEqual((self.root / 'before.json').read_bytes(), sealed)

    def test_restore_checks_config_route_weights_and_binary(self):
        self.runtime.prepare()
        delegate = self.fake.run
        for kind in ('config', 'route', 'weights', 'binary'):
            def run(args, timeout, env=None):
                result = delegate(args, timeout, env)
                if args[:2] == ['systemctl', 'start']:
                    if kind == 'config':
                        self.fake.old['Config']['Entrypoint'] = ['different']
                    if kind == 'route':
                        self.fake.old['HostConfig']['NetworkMode'] = 'bridge'
                return result
            self.runtime.runner = run
            with patch.object(self.runtime, 'weight_stats', wraps=self.runtime.weight_stats) as stats:
                with patch.object(self.runtime, 'binary_hash', return_value=m.ORIGINAL_BINARY) as binary:
                    if kind == 'weights':
                        stats.return_value = []
                        stats.side_effect = lambda: []
                    if kind == 'binary':
                        binary.return_value = '0' * 64
                    with self.assertRaises(m.Refusal):
                        self.runtime.restore()
            self.assertTrue((self.root / 'api-key').exists())
            self.assertFalse((self.root / 'restored.json').exists())
        self.runtime.runner = delegate
        self.assertEqual(self.runtime.restore()['status'], 'restored')

    def test_daemon_outage_is_not_absence(self):
        delegate = self.fake.run
        def run(args, timeout, env=None):
            result = delegate(args, timeout, env)
            if args[:2] == ['docker', 'inspect']:
                result.returncode, result.stdout, result.stderr = 1, '', 'Cannot connect to daemon'
            return result
        self.runtime.runner = run
        with self.assertRaisesRegex(m.Refusal, 'absence unknown'):
            self.runtime.prepare()
        self.assertFalse(any(c[0][:2] == ['systemctl', 'stop'] for c in self.fake.calls))

    def test_reap_waits_for_auto_remove(self):
        self.runtime.prepare()
        delegate = self.fake.run
        stopped = []
        pending = []
        def run(args, timeout, env=None):
            if args[:2] == ['docker', 'stop']:
                stopped.append(copy.deepcopy(self.fake.candidate))
            result = delegate(args, timeout, env)
            if args[:2] == ['docker', 'inspect'] and args[2] == self.runtime.name and stopped:
                if not pending:
                    result.returncode, result.stdout, result.stderr = 0, json.dumps(stopped), ''
                    pending.append(True)
            return result
        self.runtime.runner = run
        self.assertEqual(self.runtime.restore()['status'], 'restored')
        self.assertGreaterEqual(self.fake.now, .5)

    def test_restore_deadline_includes_command_time(self):
        self.runtime.prepare()
        delegate = self.fake.run
        def run(args, timeout, env=None):
            self.fake.now += min(timeout, 7)
            return delegate(args, timeout, env)
        self.runtime.runner = run
        self.runtime.http = lambda path, key, timeout: (503, None)
        start = self.fake.now
        with self.assertRaises(m.Refusal):
            self.runtime.restore()
        self.assertLessEqual(self.fake.now - start, 110)
        self.assertTrue((self.root / 'api-key').exists())
        self.assertFalse((self.root / 'restored.json').exists())

    def test_preflight_rejects_multiple_gpus_and_foreign_unit(self):
        delegate = self.fake.run
        for kind in ('gpu', 'unit'):
            def run(args, timeout, env=None):
                result = delegate(args, timeout, env)
                if kind == 'gpu' and args[0] == 'nvidia-smi':
                    result.stdout += 'GPU-other, NVIDIA A10\n'
                if kind == 'unit' and args[:3] == ['systemctl', 'show', self.runtime.unit]:
                    result.stdout = 'LoadState=loaded\n'
                return result
            self.runtime.runner = run
            with self.assertRaises(m.Refusal):
                self.runtime.prepare()
            (self.root / 'restore.lock').unlink()
        self.assertFalse(any(c[0][:2] == ['systemctl', 'stop'] for c in self.fake.calls))

    def test_root_owner_and_oversized_spec_rejected_without_commands(self):
        wrong = m.FilePolicy(os.getuid() + 1, os.getgid(), Path(self.tmp.name))
        with patch.object(self.runtime, 'policy', wrong):
            with self.assertRaisesRegex(m.Refusal, 'ownership'):
                self.runtime.prepare()
        path = self.root / 'spec.json'
        path.chmod(0o600)
        path.write_bytes(b' ' * 16385)
        path.chmod(0o400)
        with self.assertRaisesRegex(m.Refusal, 'size'):
            self.runtime.prepare()
        self.assertEqual(self.fake.calls, [])

    def test_automatic_restore_can_take_lock_during_readiness(self):
        triggered = []
        def http(path, key, timeout):
            if key and not triggered:
                triggered.append(True)
                self.assertEqual(self.runtime.restore()['status'], 'restored')
                return 503, None
            return 200, {'data': [{'id': m.MODEL}]}
        self.runtime.http = http
        with self.assertRaisesRegex(m.Refusal, 'original restored'):
            self.runtime.prepare()
        self.assertEqual(triggered, [True])
        self.assertIsNotNone(self.fake.old)
        self.assertFalse((self.root / 'prepared.json').exists())

    def test_foreign_identity_discovered_after_launch_is_never_stopped(self):
        def http(path, key, timeout):
            self.fake.candidate['Config']['Labels']['workbay.owner'] = 'foreign'
            return 200, {'data': [{'id': m.MODEL}]}
        self.runtime.http = http
        with self.assertRaisesRegex(m.Refusal, 'restoration unknown'):
            self.runtime.prepare()
        self.assertFalse(any(c[0][:2] == ['docker', 'stop'] or
                             c[0][:3] == ['systemctl', 'stop', self.runtime.unit]
                             for c in self.fake.calls))
        self.assertIsNotNone(self.fake.candidate)
        self.assertTrue((self.root / 'api-key').exists())

    def test_fixed_service_and_container_contract(self):
        self.runtime.prepare()
        args = next(c[0] for c in self.fake.calls if c[0][0] == 'systemd-run')
        for item in ('--property=RuntimeMaxSec=1500', '--property=TimeoutStopSec=120',
                     '--property=CPUQuota=25%', '--property=MemoryMax=268435456',
                     '--property=Restart=no', '--property=User=root', '--rm', '--pull=never'):
            self.assertIn(item, args)
        for flag, value in (('--gpus', 'all'), ('--network', 'host'), ('--cpus', '8'),
                            ('--memory', str(64 * 1024**3)), ('--shm-size', str(8 * 1024**3)),
                            ('--dtype', 'bfloat16'), ('--max-model-len', '8192'),
                            ('--mm-processor-kwargs', '{"max_pixels":1572864}')):
            self.assertEqual(args[args.index(flag) + 1], value)
        stop_post = next(x for x in args if x.startswith('--property=ExecStopPost='))
        self.assertIn(str(self.root / 'gpu_vllm_maintenance.py') + ' restore', stop_post)
        self.assertIn('--spec ' + str(self.root / 'spec.json'), stop_post)
        self.assertIn('type=bind,src=' + str(m.MODEL_DIR) + ',dst=/models,readonly', args)
        self.assertIn('type=bind,src=' + str(self.root / 'cache') + ',dst=/root/.cache', args)

    def test_http_entire_exchange_has_absolute_deadline(self):
        fake = self.fake
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def settimeout(self, timeout):
                self.timeout = timeout
                assert 0 < timeout <= 1
            def connect(self, target):
                self.target = target
            def sendall(self, data):
                self.request = data
            def recv(self, count):
                fake.now += .4
                return b'x'
        with patch.object(m.socket, 'socket', return_value=Socket()):
            with patch.object(m.time, 'monotonic', self.fake.clock):
                with self.assertRaisesRegex(m.Refusal, 'deadline'):
                    m.get_http('/health', None, 1)
        self.assertLessEqual(self.fake.now, 1.3)

    def test_http_decodes_openai_shape_without_proxy_or_redirect(self):
        body = json.dumps({'data': [{'id': m.MODEL, 'object': 'model'}]}).encode()
        response = b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
        class Socket:
            def __init__(self):
                self.parts = [response, b'']
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def settimeout(self, timeout):
                assert 0 < timeout <= 3
            def connect(self, target):
                self.target = target
            def sendall(self, data):
                self.request = data
            def recv(self, count):
                return self.parts.pop(0)
        connection = Socket()
        with patch.object(m.socket, 'socket', return_value=connection):
            status, decoded = m.get_http('/v1/models', None, 3)
        self.assertEqual(status, 200)
        self.assertEqual(decoded['data'][0]['id'], m.MODEL)
        self.assertEqual(connection.target, ('127.0.0.1', 8000))
        self.assertIn(b'Connection: close', connection.request)

    def test_pending_launcher_cannot_restore_over_later_candidate(self):
        self.runtime.prepare()
        delegate = self.fake.run
        def run(args, timeout, env=None):
            result = delegate(args, timeout, env)
            if args[:3] == ['systemctl', 'show', self.runtime.unit] and 'MainPID' in args:
                result.stdout = ('LoadState=loaded\nActiveState=activating\n'
                                 'SubState=start\nMainPID=0\n')
            return result
        self.runtime.runner = run
        start = len(self.fake.calls)
        with self.assertRaises(m.Refusal):
            self.runtime.restore()
        self.assertFalse(any(c[0][:2] == ['systemctl', 'start'] for c in self.fake.calls[start:]))
        self.assertTrue((self.root / 'api-key').exists())
        self.assertFalse((self.root / 'restored.json').exists())


if __name__ == '__main__':
    unittest.main()
