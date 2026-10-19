#!/usr/bin/python3
"""Sealed, one-operation vLLM maintenance. See VLLM-RUNTIME-HANDOFF.md.

Only prepare/restore --operation UUID --spec /run/bakeoff-vllm-<uuidhex>/spec.json
are public. Runtime/FilePolicy injection is an in-process unit-test seam only.
No runner output, inspect Config.Env, HTTP body, or exception text is reported.
"""
import argparse
import contextlib
import fcntl
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time
import uuid

ORIGINAL_SERVICE = 'acx-gpu-vlm.service'
ORIGINAL_IMAGE = 'sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb'
ORIGINAL_CONFIG = '60b918fa38f308933e08bbbcf881d66336c2567b786764a095430c7313710849'
ORIGINAL_BINARY = '59a74a6528e0dcedfb89e6a3df41b8dbd593a2c3689096a2d030ad1c67ffe4d0'
CANDIDATE_IMAGE = 'sha256:ee2917e260bb5037ca93944bfcb845a8f867674c63de2284d28c541f1eaf3f08'
CANDIDATE_REF = 'vllm/vllm-openai@sha256:d8d39b59e909d2378ac4feeb191f7e7b6f1342477dc66b7c47cec89e9985ad8a'
MODEL = 'Qwen/Qwen3-VL-8B-Instruct'
MODEL_DIR = Path('/opt/acx-gpu/bakeoff-owned-cache/qwen3-vl-8b-0c351dd01ed87e9c1b53cbc748cba10e6187ff3b')
ORIGINAL_WEIGHTS = (
    '/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-q4.gguf',
    '/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-mmproj.gguf',
)
# All fourteen byte lengths and SHA256s from the supplied download spec. No URLs,
# download implementation, mutable tags, or external dependency on that export.
ASSETS = {
    'chat_template.json': (5499, '5c72a170d2a4a1a3bc5adad2e689ae28138a9700e5b8c96c0266331e86c0acce'),
    'config.json': (1474, '5cd452860dc1e9c29dd71cc3cef7f39b338b7a40793f7a260655c2d3568f3661'),
    'generation_config.json': (269, '8469742d1fce0de951c8909b26a2c0c0d8490837ce476efb114da9e0cefc4d44'),
    'merges.txt': (1671839, '599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3'),
    'model.safetensors.index.json': (67759, '520b2e05079402e9468a8701d03d1154d14b2599593afb6effa7fb60c1bff070'),
    'preprocessor_config.json': (390, '27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516'),
    'tokenizer.json': (7032403, 'a5d85b6dcc535e6b93115a9ef287e6132fdbf30270da6218194ba742261173c7'),
    'tokenizer_config.json': (10868, 'c2da771801886ad9ae98181793ffd3dfb7f1af30f6f7c6a4e15d7dbba52e2399'),
    'video_preprocessor_config.json': (385, '7768af27c1fafa9cc9011c1dc20067e03f8915e03b63504550e11d5066986d13'),
    'vocab.json': (2776833, 'ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910'),
    'model-00001-of-00004.safetensors': (4902275944, 'd5d0aef0eb170fc7453a296c43c0849a56f510555d3588e4fd662bb35490aefa'),
    'model-00002-of-00004.safetensors': (4915962496, '8be88fb5501e4d5719a6d4cc212e6a13480330e74f3e8c77daa1a68f199106b5'),
    'model-00003-of-00004.safetensors': (4999831048, '83de00eafe6e0d57ccd009dbcf71c9974d74df2f016c27afb7e95aafd16b2192'),
    'model-00004-of-00004.safetensors': (2716270024, '0a88b98e9f96270973f567e6a2c103ede6ccdf915ca3075e21c755604d0377a5'),
}


class Refusal(Exception):
    """Safe fixed diagnostic; never wrap raw external text."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def decode_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refusal('invalid JSON number')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal('invalid JSON') from None


def stable_stat(s):
    # Reads may update atime; only identity/content/permission metadata is sealed.
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
            s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def config_hash(container):
    # Deliberately identical canonical selection/serialization to the producer.
    fields = ['Image', 'Cmd', 'Entrypoint', 'Env', 'WorkingDir', 'User']
    return hashlib.sha256(json.dumps({k: container['Config'].get(k) for k in fields},
                                     sort_keys=True).encode()).hexdigest()


class FilePolicy:
    """Production defaults cannot be overridden through the CLI or spec."""
    def __init__(self, uid=0, gid=0, parent=Path('/run')):
        self.uid, self.gid, self.parent = uid, gid, Path(parent)

    def owned(self, st, mode, directory=False):
        require(st.st_uid == self.uid and st.st_gid == self.gid,
                'file ownership refused')
        require(stat.S_IMODE(st.st_mode) == mode, 'file mode refused')
        require(stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode),
                'file type refused')
        if not directory:
            require(st.st_nlink == 1, 'file link count refused')

    def directory(self, path):
        self.owned(path.lstat(), 0o700, True)

    def read(self, path, limit):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as f:
            before = os.fstat(f.fileno())
            self.owned(before, 0o400)
            require(0 < before.st_size <= limit, 'file size refused')
            data = f.read(limit + 1)
            after = os.fstat(f.fileno())
            require(stable_stat(before) == stable_stat(after) and len(data) == before.st_size, 'file changed during read')
            return data

    def sync(self, root):
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def publish(self, path, value):
        data = json.dumps(value, sort_keys=True, allow_nan=False).encode() + b'\n'
        require(len(data) <= 65536, 'receipt size refused')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), 0o400)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        self.sync(path.parent)


def run_command(args, timeout, env=None):
    # A fixed PATH and argument lists only. No shell; never return stdout to callers
    # outside this module. Exception details may contain argv, so CLI suppresses them.
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          env=env or {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})


def get_http(path, key, timeout):
    # A single absolute deadline covers connect, send, headers and body, including
    # slow trickling peers. No proxy, DNS, redirects or ambient credentials.
    require(path in ('/health', '/v1/models') and 0 < timeout <= 3, 'HTTP request refused')
    require(key is None or re.fullmatch(r'[A-Za-z0-9_-]{32,256}', key), 'HTTP key refused')
    deadline = time.monotonic() + timeout
    request = ('GET ' + path + ' HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n'
               'Connection: close\r\n' +
               ('Authorization: Bearer ' + key + '\r\n' if key else '') + '\r\n').encode('ascii')
    chunks, size = [], 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        def budget():
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'HTTP deadline exhausted')
            connection.settimeout(remaining)
        budget()
        connection.connect(('127.0.0.1', 8000))
        budget()
        connection.sendall(request)
        while True:
            budget()
            data = connection.recv(min(65536, 1048577 - size))
            if not data:
                break
            chunks.append(data)
            size += len(data)
            require(size <= 1048576, 'HTTP response too large')
    class BufferedResponse:
        def makefile(self, mode):
            return io.BytesIO(b''.join(chunks))
    response = http.client.HTTPResponse(BufferedResponse())
    response.begin()
    body = response.read(1048577)
    require(time.monotonic() < deadline, 'HTTP deadline exhausted')
    return response.status, decode_json(body) if path == '/v1/models' else None


class Runtime:
    def __init__(self, root, operation, spec_path, *, runner=run_command,
                 clock=time.monotonic, sleep=time.sleep, http=get_http, policy=None):
        try:
            parsed = uuid.UUID(operation)
        except (ValueError, AttributeError):
            raise Refusal('invalid operation UUID') from None
        require(str(parsed) == operation, 'operation must be canonical UUID')
        self.policy = policy or FilePolicy()
        self.root = Path(root)
        require(self.root == self.policy.parent / ('bakeoff-vllm-' + parsed.hex),
                'operation root refused')
        self.spec_path = Path(spec_path)
        require(self.spec_path == self.root / 'spec.json', 'spec path refused')
        self.operation = operation
        self.name = 'workbay-bakeoff-vllm-' + operation
        self.unit = self.name + '.service'
        self.runner, self.clock, self.sleep, self.http = runner, clock, sleep, http

    def files(self, key_required=True):
        # Reject symlink ancestors. Root itself must already have been transferred.
        for path in (self.root, *self.root.parents):
            require(not path.is_symlink(), 'symlink directory refused')
        self.policy.directory(self.root)
        self.policy.read(self.root / 'gpu_vllm_maintenance.py', 262144)
        spec = decode_json(self.policy.read(self.spec_path, 16384))
        require(isinstance(spec, dict) and set(spec) == {
            'version', 'operation', 'original_network_mode', 'original_port_bindings'},
            'spec fields refused')
        require(type(spec['version']) is int and spec['version'] == 1 and
                spec['operation'] == self.operation, 'spec identity refused')
        require(spec['original_network_mode'] in ('host', 'bridge'), 'original network refused')
        ports = spec['original_port_bindings']
        require(ports is None or isinstance(ports, dict), 'original ports refused')
        if spec['original_network_mode'] == 'host':
            require(ports in ({}, None), 'host ports refused')
        else:
            require(isinstance(ports, dict) and set(ports) == {'8000/tcp'} and
                    isinstance(ports['8000/tcp'], list) and len(ports['8000/tcp']) == 1,
                    'original port route refused')
            row = ports['8000/tcp'][0]
            require(isinstance(row, dict) and set(row) == {'HostIp', 'HostPort'} and
                    row['HostIp'] in ('', '0.0.0.0', '127.0.0.1') and row['HostPort'] == '8000',
                    'original port route refused')
        self.spec = spec
        if key_required:
            key = self.policy.read(self.root / 'api-key', 4096)
            require(re.fullmatch(rb'[A-Za-z0-9_-]{32,256}', key) is not None,
                    'private key encoding refused')
            return key.decode('ascii')
        return None

    @contextlib.contextmanager
    def lock(self, outer_deadline=None, new=False):
        path = self.root / 'restore.lock'
        flags = os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags | (os.O_EXCL if new else 0), 0o400)
        try:
            self.policy.owned(os.fstat(fd), 0o400)
            require(os.fstat(fd).st_size == 0, 'lock size refused')
            deadline = self.clock() + 60
            if outer_deadline is not None:
                deadline = min(deadline, outer_deadline)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(self.clock() < deadline, 'operation lock busy')
                    self.sleep(.1)
            yield
        finally:
            os.close(fd)

    def run(self, args, timeout=15, env=None):
        require(math.isfinite(timeout) and 0 < timeout <= 120, 'command deadline refused')
        try:
            result = self.runner(args, timeout=timeout, env=env)
        except Exception:
            raise Refusal('command execution failed') from None
        require(len(result.stdout or '') <= 1048576 and len(result.stderr or '') <= 1048576,
                'command response too large')
        return result

    def checked(self, args, timeout=15, env=None, message='command refused'):
        result = self.run(args, timeout, env)
        require(result.returncode == 0, message)
        return result

    def inspect(self, name, timeout=8):
        result = self.run(['docker', 'inspect', name], timeout)
        if result.returncode:
            # A daemon outage/permission error is NOT proof that a container is absent.
            require(result.returncode == 1 and
                    (result.stderr or '').strip() in ('Error: No such object: ' + name,
                                                      'Error: No such container: ' + name),
                    'container absence unknown')
            return None
        rows = decode_json(result.stdout)
        require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
                'inspect shape refused')
        return rows[0]

    def enabled(self, active=False, timeout=15):
        result = self.checked(['systemctl', 'show', ORIGINAL_SERVICE,
                               '-p', 'ActiveState', '-p', 'UnitFileState'], timeout)
        lines = result.stdout.splitlines()
        require('UnitFileState=enabled' in lines, 'original service not enabled')
        if active:
            require('ActiveState=active' in lines, 'original service not active')

    def binary_hash(self, container):
        pid = container['State']['Pid']
        require(type(pid) is int and pid > 0, 'original PID refused')
        with open('/proc/' + str(pid) + '/exe', 'rb') as f:
            return hashlib.file_digest(f, 'sha256').hexdigest()

    def weight_stats(self):
        result = []
        for name in ORIGINAL_WEIGHTS:
            path = Path(name)
            for parent in (path, *path.parents):
                require(not parent.is_symlink(), 'weight symlink refused')
            s = path.stat()
            require(stat.S_ISREG(s.st_mode) and s.st_size > 0, 'original weight refused')
            result.append(dict(path=name, bytes=s.st_size, ino=s.st_ino, mtime_ns=s.st_mtime_ns))
        return result

    def original(self, container, weight_stats=None):
        require(container is not None and container['State']['Running'] is True,
                'original container not running')
        require(container['Image'] == ORIGINAL_IMAGE and config_hash(container) == ORIGINAL_CONFIG,
                'original image/config drift')
        host = container['HostConfig']
        require(host['AutoRemove'] is True and
                host['NetworkMode'] == self.spec['original_network_mode'] and
                host['PortBindings'] == self.spec['original_port_bindings'],
                'original lifecycle/route drift')
        require(self.binary_hash(container) == ORIGINAL_BINARY, 'original binary drift')
        stats = self.weight_stats()
        if weight_stats is not None:
            require(stats == weight_stats, 'original weight stats drift')
        return stats

    def host_capacity(self):
        require((os.cpu_count() or 0) >= 8, 'insufficient host CPU')
        mem = Path('/proc/meminfo').read_text()
        available = next(int(x.split()[1]) * 1024 for x in mem.splitlines()
                         if x.startswith('MemAvailable:'))
        require(available >= 64 * 1024**3, 'insufficient host memory')

    def validate_assets(self):
        for path in (MODEL_DIR, *MODEL_DIR.parents):
            require(not path.is_symlink(), 'model directory symlink refused')
        require(MODEL_DIR.is_dir(), 'model directory missing')
        for path in (MODEL_DIR, *MODEL_DIR.parents):
            st = path.stat()
            require(st.st_uid == self.policy.uid and not (st.st_mode & 0o022),
                    'model directory ownership/mode refused')
        for name, (size, digest) in ASSETS.items():
            self.validate_asset(MODEL_DIR / name, size, digest)

    def validate_asset(self, path, size, digest):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as f:
            before = os.fstat(f.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                    before.st_uid == self.policy.uid and not (before.st_mode & 0o022) and
                    before.st_size == size, 'model asset size/type refused')
            require(hashlib.file_digest(f, 'sha256').hexdigest() == digest,
                    'model asset digest refused')
            require(stable_stat(os.fstat(f.fileno())) == stable_stat(before), 'model asset changed')

    def image(self):
        result = self.checked(['docker', 'image', 'inspect', CANDIDATE_REF])
        rows = decode_json(result.stdout)
        require(isinstance(rows, list) and len(rows) == 1 and
                rows[0]['Id'] == CANDIDATE_IMAGE and
                CANDIDATE_REF in (rows[0].get('RepoDigests') or []), 'candidate image pin drift')

    def owned_candidate(self, candidate):
        labels = candidate['Config'].get('Labels') or {}
        require(candidate.get('Name') == '/' + self.name, 'candidate name refused untouched')
        require(labels.get('workbay.owner') == 'Bakeoff' and
                labels.get('workbay.operation') == self.operation and
                candidate['Image'] == CANDIDATE_IMAGE, 'foreign candidate refused untouched')
        require(isinstance(candidate['Id'], str) and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', candidate['Id']),
                'candidate ID refused')

    def command(self):
        return [
            'systemd-run', '--quiet', '--collect', '--unit=' + self.unit,
            '--property=Type=exec', '--property=User=root', '--property=Group=root',
            '--property=CPUQuota=25%',
            '--property=MemoryMax=268435456', '--property=RuntimeMaxSec=1500',
            '--property=TimeoutStopSec=120', '--property=Restart=no',
            '--setenv=VLLM_API_KEY',
            '--property=ExecStopPost=/usr/bin/python3 -I -B ' +
            str(self.root / 'gpu_vllm_maintenance.py') + ' restore --operation ' +
            self.operation + ' --spec ' + str(self.spec_path),
            '--', '/usr/bin/docker', 'run', '--rm', '--pull=never',
            '--name', self.name, '--label', 'workbay.owner=Bakeoff',
            '--label', 'workbay.operation=' + self.operation, '--gpus', 'all',
            '--network', 'host', '--cpus', '8', '--memory', str(64 * 1024**3),
            '--memory-swap', str(64 * 1024**3), '--shm-size', str(8 * 1024**3),
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--mount', 'type=bind,src=' + str(MODEL_DIR) + ',dst=/models,readonly',
            '--mount', 'type=bind,src=' + str(self.root / 'cache') + ',dst=/root/.cache',
            '--env', 'VLLM_API_KEY', '--env', 'HF_HOME=/root/.cache/huggingface',
            '--env', 'TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers',
            '--env', 'XDG_CACHE_HOME=/root/.cache', '--env', 'VLLM_CACHE_ROOT=/root/.cache/vllm',
            '--env', 'CUDA_CACHE_PATH=/root/.cache/cuda', '--env', 'HF_HUB_OFFLINE=1',
            '--env', 'TRANSFORMERS_OFFLINE=1', '--env', 'VLLM_NO_USAGE_STATS=1',
            CANDIDATE_REF, '--model', '/models', '--tokenizer', '/models',
            '--served-model-name', MODEL, '--dtype', 'bfloat16', '--max-model-len', '8192',
            '--max-num-seqs', '1', '--gpu-memory-utilization', '0.9', '--enforce-eager',
            '--limit-mm-per-prompt', '{"image":1}',
            '--mm-processor-kwargs', '{"max_pixels":1572864}', '--port', '8000',
        ]

    def health(self, key, timeout):
        try:
            return self.http('/health', key, timeout)[0] == 200
        except Exception:
            return False

    def candidate_ready(self, key, deadline):
        while self.clock() < deadline:
            if (self.root / 'restored.json').exists():
                raise Refusal('candidate already restored')
            candidate = self.inspect(self.name, self.remaining(deadline, 8))
            if candidate is not None:
                self.owned_candidate(candidate)
                remaining = deadline - self.clock()
                if candidate['State']['Running'] and remaining > 0 and self.health(key, min(3, remaining)):
                    try:
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            break
                        status, body = self.http('/v1/models', key, min(3, remaining))
                        # OpenAI model rows also have object/created/owned_by fields.
                        data = body.get('data') if isinstance(body, dict) else None
                        if (status == 200 and isinstance(data, list) and len(data) == 1 and
                                isinstance(data[0], dict) and data[0].get('id') == MODEL):
                            require(self.clock() < deadline, 'candidate readiness deadline')
                            return candidate
                    except Exception:
                        pass
            self.sleep(min(.5, max(0, deadline - self.clock())))
        raise Refusal('candidate readiness refused')

    def before(self, stats, start):
        return dict(version=1, operation=self.operation, candidate_name=self.name, unit=self.unit,
                    labels={'workbay.owner': 'Bakeoff', 'workbay.operation': self.operation},
                    original_image_id=ORIGINAL_IMAGE, candidate_image_id=CANDIDATE_IMAGE,
                    candidate_image_ref=CANDIDATE_REF, qwen_config_sha256=ORIGINAL_CONFIG,
                    qwen_binary_sha256=ORIGINAL_BINARY, qwen_weight_stats=stats,
                    original_network_mode=self.spec['original_network_mode'],
                    original_port_bindings=self.spec['original_port_bindings'],
                    original_service=ORIGINAL_SERVICE, original_service_enabled=True,
                    runtime_max_seconds=1500, start_monotonic=start)

    def prepare(self):
        key = self.files()
        require({p.name for p in self.root.iterdir()} ==
                {'gpu_vllm_maintenance.py', 'spec.json', 'api-key'},
                'existing operation data refused')
        stopped = False
        launch_error = None
        try:
            with self.lock(new=True):
                entries = {p.name for p in self.root.iterdir()}
                require(entries == {'gpu_vllm_maintenance.py', 'spec.json', 'api-key', 'restore.lock'},
                        'existing operation data refused')
                self.enabled(active=True)
                stats = self.original(self.inspect('acx-gpu-vlm'))
                self.image()
                gpu = self.checked(['nvidia-smi', '--query-gpu=uuid,name', '--format=csv,noheader'], 10)
                rows = [x.strip() for x in gpu.stdout.splitlines() if x.strip()]
                require(len(rows) == 1 and re.fullmatch(r'GPU-[A-Za-z0-9-]+,\s*NVIDIA A10', rows[0]),
                        'exactly one A10 required')
                self.host_capacity()
                self.validate_assets()
                require(self.inspect(self.name) is None, 'existing candidate refused untouched')
                self.check_unit_absent()
                # Asset hashing can take time; reconfirm the incumbent immediately
                # before sealing/stopping, against the initially captured stats.
                self.enabled(active=True)
                self.original(self.inspect('acx-gpu-vlm'), stats)
                cache = self.root / 'cache'
                cache.mkdir(mode=0o700)
                self.policy.directory(cache)
                start = self.clock()
                self.policy.publish(self.root / 'before.json', self.before(stats, start))
                # Failed/timed-out stop may have had an effect and needs restore too.
                stopped = True
                self.checked(['systemctl', 'stop', ORIGINAL_SERVICE], 30,
                             message='original stop failed')
                require(self.inspect('acx-gpu-vlm') is None, 'original container still present')
                env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'VLLM_API_KEY': key}
                self.checked(self.command(), 20, env, 'candidate service start failed')
            # ExecStopPost must be able to take the lock while readiness is pending.
            candidate = self.candidate_ready(key, start + 150)
            with self.lock(start + 150):
                self.remaining(start + 150, 1)
                require(not (self.root / 'restored.json').exists(), 'candidate already restored')
                current = self.inspect(self.name, self.remaining(start + 150, 8))
                require(current is not None and current['Id'] == candidate['Id'] and
                        current['State']['Running'], 'candidate changed after readiness')
                self.owned_candidate(current)
                receipt = dict(status='ready', operation=self.operation, candidate_name=self.name,
                               candidate_image_id=CANDIDATE_IMAGE, candidate_image_ref=CANDIDATE_REF,
                               candidate_id=candidate['Id'], runtime_max_seconds=1500,
                               models_verified=True, owner_window_external=True)
                self.policy.publish(self.root / 'prepared.json', receipt)
                return receipt
        except BaseException as exc:
            if not stopped:
                raise
            launch_error = str(exc) if isinstance(exc, Refusal) else 'execution failed'
        # Release root lock before systemctl waits for ExecStopPost, which uses
        # the same lock. Refuse to stop even our service if its candidate is foreign.
        unit_stopped = False
        try:
            candidate = self.inspect(self.name)
            if candidate is not None:
                self.owned_candidate(candidate)
            self.checked(['systemctl', 'stop', self.unit], 120)
            unit_stopped = True
        except Exception:
            pass
        try:
            self.restore()
        except BaseException:
            raise Refusal('launch failed (' + launch_error +
                          '); restoration unknown; retain operation evidence') from None
        require(unit_stopped, 'launch failed (' + launch_error +
                '); restoration verified but service stop uncertain')
        raise Refusal('launch failed (' + launch_error + '); original restored') from None

    def check_unit_absent(self):
        result = self.run(['systemctl', 'show', self.unit, '-p', 'LoadState'], 10)
        require(result.returncode in (0, 1, 4) and result.stdout.strip() == 'LoadState=not-found',
                'existing candidate unit refused untouched')

    def load_before(self):
        value = decode_json(self.policy.read(self.root / 'before.json', 65536))
        require(isinstance(value, dict), 'before shape refused')
        stats = value.get('qwen_weight_stats')
        require(isinstance(stats, list) and len(stats) == len(ORIGINAL_WEIGHTS),
                'before weight stats refused')
        for row, path in zip(stats, ORIGINAL_WEIGHTS):
            require(isinstance(row, dict) and set(row) == {'path', 'bytes', 'ino', 'mtime_ns'} and
                    row['path'] == path and all(type(row[k]) is int and row[k] >= 0
                                               for k in ('bytes', 'ino', 'mtime_ns')),
                    'before weight stats refused')
        start = value.get('start_monotonic')
        require(type(start) in (int, float) and math.isfinite(start) and start >= 0,
                'before clock refused')
        require(value == self.before(stats, start), 'before identity/config refused')
        return value

    def restore(self):
        # Leave margin inside the service's 120-second stop deadline. The 90s
        # readiness ceiling is also capped by this total restoration budget.
        restore_deadline = self.clock() + 110
        self.files(key_required=False)
        with self.lock(restore_deadline):
            before = self.load_before()
            restored = self.root / 'restored.json'
            if restored.exists():
                receipt = decode_json(self.policy.read(restored, 65536))
                require(receipt == self.restored_receipt(), 'restored receipt refused')
                require(not (self.root / 'api-key').exists() and
                        not (self.root / 'api-key').is_symlink(), 'restored key unexpectedly present')
                return receipt
            # Key may be missing only after the final verified restoration unlink
            # succeeded but publishing the receipt failed. Never need it to restore.
            key_path = self.root / 'api-key'
            if key_path.exists() or key_path.is_symlink():
                self.policy.read(key_path, 4096)
            candidate = self.inspect(self.name, self.remaining(restore_deadline, 8))
            if candidate is not None:
                self.owned_candidate(candidate)
                self.checked(['docker', 'stop', '--time', '10', candidate['Id']],
                             self.remaining(restore_deadline, 25),
                             message='owned candidate stop failed')
            reap_deadline = min(restore_deadline, self.clock() + 10)
            while True:
                candidate = self.inspect(self.name, self.remaining(reap_deadline, 8))
                if candidate is None:
                    break
                self.owned_candidate(candidate)
                require(self.clock() < reap_deadline, 'owned candidate not reaped')
                self.sleep(min(.5, self.remaining(reap_deadline, .5)))
            # No original start while a detached Docker CLI could still create a
            # candidate. In ExecStopPost the main process is already gone. Manual
            # restore waits briefly for it to exit after docker stop, or fails closed.
            self.launcher_quiescent(restore_deadline)
            require(self.inspect(self.name, self.remaining(restore_deadline, 8)) is None,
                    'candidate reappeared after CLI exit')
            self.enabled(timeout=self.remaining(restore_deadline, 15))
            deadline = min(restore_deadline, self.clock() + 90)
            self.checked(['systemctl', 'start', ORIGINAL_SERVICE], self.remaining(deadline, 30),
                         message='original service restore failed')
            ready = False
            while self.clock() < deadline:
                container = self.inspect('acx-gpu-vlm', min(8, deadline - self.clock()))
                if container is not None and container['State']['Running']:
                    self.original(container, before['qwen_weight_stats'])
                    remaining = deadline - self.clock()
                    if remaining > 0 and self.health(None, min(3, remaining)):
                        self.enabled(active=True, timeout=self.remaining(deadline, 15))
                        ready = True
                        break
                self.sleep(min(.5, max(0, deadline - self.clock())))
            require(ready, 'original readiness unknown; retain evidence')
            # Recheck after HTTP to avoid certifying a stale prior observation.
            self.original(self.inspect('acx-gpu-vlm', self.remaining(deadline, 8)),
                          before['qwen_weight_stats'])
            require(self.inspect(self.name, self.remaining(deadline, 8)) is None, 'candidate reappeared')
            self.remaining(deadline, 1)
            key_path.unlink(missing_ok=True)
            self.policy.sync(self.root)
            receipt = self.restored_receipt()
            self.policy.publish(restored, receipt)
            return receipt

    def launcher_quiescent(self, restore_deadline):
        deadline = min(restore_deadline, self.clock() + 10)
        while True:
            result = self.run(['systemctl', 'show', self.unit, '-p', 'LoadState',
                               '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID'],
                              self.remaining(deadline, 5))
            fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            require(result.returncode in (0, 1, 4), 'candidate launcher state unknown')
            if fields.get('LoadState') == 'not-found':
                return
            require(fields.get('LoadState') == 'loaded', 'candidate launcher state unknown')
            if fields.get('MainPID') == '0' and (
                    fields.get('ActiveState') in ('inactive', 'failed') or
                    (fields.get('ActiveState') == 'deactivating' and
                     fields.get('SubState') == 'stop-post')):
                return
            require(self.clock() < deadline, 'candidate launcher still pending; retain evidence')
            self.sleep(min(.5, self.remaining(deadline, .5)))

    def remaining(self, deadline, maximum):
        remaining = deadline - self.clock()
        require(remaining > 0, 'readiness deadline exhausted')
        return min(maximum, remaining)

    def restored_receipt(self):
        return dict(status='restored', operation=self.operation, original_Qwen_restored=True,
                    original_image_id=ORIGINAL_IMAGE, qwen_config_sha256=ORIGINAL_CONFIG,
                    qwen_binary_sha256=ORIGINAL_BINARY, candidate_absent=True,
                    original_health_HTTP=200, weight_stats_unchanged=True,
                    guest_private_key_absent=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'restore'))
    parser.add_argument('--operation', required=True)
    parser.add_argument('--spec', required=True)
    args = parser.parse_args(argv)
    try:
        require(os.geteuid() == 0 and os.getegid() == 0, 'root UID/GID required')
        operation = uuid.UUID(args.operation)
        root = Path('/run') / ('bakeoff-vllm-' + operation.hex)
        runtime = Runtime(root, args.operation, args.spec)
        # ExecStopPost must call precisely this transferred file, never another copy.
        require(Path(__file__).absolute() == root / 'gpu_vllm_maintenance.py',
                'helper location refused')
        receipt = getattr(runtime, args.action)()
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except BaseException as exc:
        error = str(exc) if isinstance(exc, Refusal) else 'operation failed; retain evidence'
        print(json.dumps({'status': 'refused', 'error': error}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
