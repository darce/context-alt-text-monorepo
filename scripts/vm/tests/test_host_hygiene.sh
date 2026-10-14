#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SWEEP=${HYGIENE_TEST_SWEEP:-$SCRIPT_DIR/../host-hygiene.sh}
INSTALLER=${HYGIENE_TEST_INSTALLER:-$SCRIPT_DIR/../install-host-hygiene.sh}
[[ -f "$SWEEP" ]] || { printf 'FAIL: host-hygiene sweep missing\n'; exit 1; }
[[ -f "$INSTALLER" ]] || { printf 'FAIL: host-hygiene installer missing\n'; exit 1; }
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
"${HYGIENE_TEST_PYTHON:-/home/gate/.workbay/gtmburst-runtime/python-fx-async/bin/python}" - "$SWEEP" "$INSTALLER" <<'PY'
import contextlib
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SWEEP, INSTALLER = map(Path, sys.argv[1:])
OLD = time.time() - 96 * 3600
ANON = [str(i) * 64 for i in range(1, 5)]
passed = 0
CASES = {}
GROUPS = {
    'tmp_exclusions': {'sandbox_marker', 'scratch_marker', 'live_cwd', 'live_root', 'live_fd',
                       'recent_nested', 'git_repo', 'git_worktree', 'other_uid', 'uv_cache'},
    'tmp_safety_1': {'pytest_newest_old', 'report_reclaim_bytes', 'pytest_children',
                     'live_prefix_boundary', 'symlink', 'default_report', 'delete_mode'},
    'tmp_safety_2': {'scan_subtree_only', 'git_subtree_only', 'pytest_recent_nonnewest',
                     'bare_git', 'top_level_mount_held', 'invalid_mode', 'tmp_report_only'},
    'tmp_safety_3': {'malformed_mode', 'quoted_delete_mode', 'report_mode',
                     'unreadable_proc_held', 'liveness_recheck', 'acx_build'},
    'docker_journal': {'old_anonymous_removed', 'named_volume', 'in_use_volume', 'young_volume',
                       'dangling_but_in_use', 'volume_recheck', 'metrics_and_no_image_deletion',
                       'journal_binary_units'},
    'installer': {'installer_idempotent', 'installer_uninstall', 'installer_refuses_nonroot',
                   'installer_failure_recovery', 'installer_preserves_operator_mode'},
    'failures': {'class_failure_continues', 'class_timeouts'},
}

STUB = r'''#!PYTHON
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
base = Path(os.environ['FAKE_BASE'])
with (base / 'calls').open('a') as f:
    f.write(json.dumps([name, *args]) + '\n')
if name == 'id':
    print(os.environ.get('FAKE_UID', '0')); sys.exit(0)
if name == 'systemctl':
    sys.exit(1 if os.environ.get('FAIL_SYSTEMCTL') in ('1', args[0]) else 0)
if name == 'journalctl':
    print('Archived and active journals take up ' + os.environ.get('JOURNAL_SIZE', '8192B') + ' in the file system.'); sys.exit(0)
if name != 'docker':
    sys.exit(90)
if (args[:2] in (['image','rm'], ['image','prune'], ['system','prune'])
        or args[:1] in (['rmi'], ['rm'])):
    (base / 'forbidden').touch(); sys.exit(91)
if os.environ.get('FAIL_DOCKER') == '1':
    sys.exit(92)
if os.environ.get('SLOW_DOCKER') == '1':
    import time
    time.sleep(10)
state_path = base / 'docker.json'
state = json.loads(state_path.read_text())
if args[:2] == ['system', 'df']:
    for kind, size in [('Build Cache',state['cache']), ('Local Volumes',len(state['volumes']) * 4096), ('Images',65536)]:
        print(json.dumps({'Type':kind, 'Size':str(size)+'B'}))
elif args[:2] == ['builder','prune']:
    assert args[2:] == ['-f','--filter','until=168h']
    state['cache'] = 0
elif args[:2] == ['volume','ls']:
    assert '--quiet' in args
    for key, vol in state['volumes'].items():
        if 'dangling=true' not in args or vol['dangling']:
            print(key)
elif args[:2] == ['volume','inspect']:
    key = args[-1]
    vol = state['volumes'][key]
    print(json.dumps([{'Name':key, 'CreatedAt':vol['created']}]))
elif args[:1] == ['ps']:
    key = next(a[7:] for a in args if a.startswith('volume='))
    if state['volumes'][key]['in_use'] or os.environ.get('RACE_VOLUME') == key:
        print('container-fixture')
elif args[:2] == ['volume','rm']:
    assert len(args) == 3
    del state['volumes'][args[2]]
else:
    sys.exit(93)
state_path.write_text(json.dumps(state))
'''


@contextlib.contextmanager
def fixture(mode='report'):
    with tempfile.TemporaryDirectory(prefix='acx-hygiene-test.', dir='/tmp') as scratch:
        base = Path(scratch)
        for name in ['bin', 'tmp', 'proc', 'etc/default', 'usr', 'shim']:
            (base / name).mkdir(parents=True, exist_ok=True)
        for name in ['docker', 'systemctl', 'journalctl', 'id']:
            path = base / 'bin' / name
            path.write_text(STUB.replace('#!PYTHON', '#!' + sys.executable))
            path.chmod(0o755)
        (base / 'bin/python3').symlink_to(sys.executable)
        # A syscall fixture supplies a foreign owner without requiring chown/root.
        (base / 'shim/sitecustomize.py').write_text('''
import os
from types import SimpleNamespace
original = os.lstat
def fake_lstat(path, *args, **kwargs):
    result = original(path, *args, **kwargs)
    if os.path.basename(os.fspath(path)) == 'other-uid':
        attrs = {key: getattr(result, key) for key in dir(result) if key.startswith('st_')}
        attrs['st_uid'] = result.st_uid + 1
        return SimpleNamespace(**attrs)
    return result
os.lstat = fake_lstat
''')
        (base / 'docker.json').write_text(json.dumps({'cache': 16384, 'volumes': {
            ANON[0]: {'dangling': True, 'in_use': False, 'created': '2020-01-01T00:00:00Z'},
            'named-data': {'dangling': True, 'in_use': False, 'created': '2020-01-01T00:00:00Z'},
            ANON[1]: {'dangling': False, 'in_use': True, 'created': '2020-01-01T00:00:00Z'},
            ANON[2]: {'dangling': True, 'in_use': False, 'created': '2099-01-01T00:00:00Z'},
            ANON[3]: {'dangling': True, 'in_use': True, 'created': '2020-01-01T00:00:00Z'},
        }}))
        (base / 'etc/default/acx-host-hygiene').write_text('ACX_HYGIENE_TMP_MODE=' + mode + '\n')
        env = dict(os.environ, PATH=str(base / 'bin') + ':' + os.environ['PATH'],
                   FAKE_BASE=str(base), HYGIENE_TMP_ROOT=str(base / 'tmp'),
                   HYGIENE_PROC_ROOT=str(base / 'proc'), HYGIENE_ETC_ROOT=str(base / 'etc'),
                   HYGIENE_USR_ROOT=str(base / 'usr'), HYGIENE_GATE_UID=str(os.getuid()),
                   HYGIENE_CLASS_TIMEOUT='20', PYTHONPATH=str(base / 'shim'))
        yield base, env
        assert not (base / 'forbidden').exists(), 'docker image/container deletion was attempted'


def old_tree(base, name):
    path = base / 'tmp' / name
    path.mkdir()
    (path / 'data').write_bytes(b'x' * 8192)
    age(path)
    return path


def age(path):
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            os.utime(Path(root) / name, (OLD, OLD), follow_symlinks=False)
        os.utime(root, (OLD, OLD))


def run(base, env, installer=False, args=(), ok=True):
    result = subprocess.run(['bash', str(INSTALLER if installer else SWEEP), *args],
                            env=env, capture_output=True, text=True, timeout=30)
    assert not (base / 'forbidden').exists(), 'forbidden Docker operation'
    assert (result.returncode == 0) == ok, f'unexpected exit {result.returncode}: {result.stdout} {result.stderr}'
    if installer or not ok:
        return result
    lines = result.stdout.splitlines()
    summary = json.loads(lines[-1])
    import re
    for kind in ['build_cache', 'volumes', 'images', 'tmp', 'journald']:
        assert any(re.fullmatch(r'HYGIENE ' + kind + r' before=\d+ freed=\d+ held=\d+ mode=\w+', line) for line in lines), kind
        for key in ['before', 'freed', 'held', 'mode', 'errors']:
            assert key in summary[kind], (kind, key)
    return summary


def case(name, callback):
    assert name not in CASES, f'duplicate case definition: {name}'
    CASES[name] = callback


def run_case(name, callback):
    global passed
    group = os.environ.get('HYGIENE_TEST_GROUP')
    if group and name not in GROUPS[group]:
        return
    if os.environ.get('HYGIENE_TEST_CASE') not in (None, '', name):
        return
    try:
        callback()
    except Exception as exc:
        print('FAIL: ' + name + ': ' + str(exc), flush=True)
        raise
    passed += 1
    print('PASS: ' + name, flush=True)


def tmp_case(name, setup=lambda b, p, e: None, held=True, mode='delete'):
    with fixture(mode) as (base, env):
        path = old_tree(base, name)
        setup(base, path, env)
        summary = run(base, env)
        assert path.exists() == held, 'temporary tree retention incorrect'
        if held:
            assert summary['tmp']['held'] >= 1, 'held tree not counted'
        else:
            assert summary['tmp']['freed'] > 0
        return summary


def marker_setup(marker):
    def setup(base, path, env):
        (path / 'nested').mkdir()
        (path / 'nested' / marker).touch()
        age(path)
    return setup


def live_setup(kind):
    def setup(base, path, env):
        proc = base / 'proc/123'
        (proc / 'fd').mkdir(parents=True)
        (proc / kind).symlink_to(path / 'data' if kind.startswith('fd/') else path)
    return setup


case('report_mode', lambda: tmp_case('old-report', held=True, mode='report'))
case('delete_mode', lambda: tmp_case('old-delete', held=False))
case('sandbox_marker', lambda: tmp_case('marker', marker_setup('.workbay-lane-sandbox')))
case('scratch_marker', lambda: tmp_case('marker', marker_setup('.workbay-scratch')))
case('live_cwd', lambda: tmp_case('live', live_setup('cwd')))
case('live_root', lambda: tmp_case('live', live_setup('root')))
case('live_fd', lambda: tmp_case('live', live_setup('fd/7')))


def recent(base, path, env):
    (path / 'data').touch()
    os.utime(path, (OLD, OLD))


case('recent_nested', lambda: tmp_case('recent', recent))


def git_case(directory=False):
    def setup(base, path, env):
        (path / 'nested').mkdir()
        if directory:
            (path / 'nested/.git').mkdir()
        else:
            (path / 'nested/.git').write_text('gitdir: /fixture/worktrees/lane\n')
        age(path)
    summary = tmp_case('git-tree', setup)
    assert summary['tmp']['held_git'] == 1


case('git_repo', lambda: git_case(True))
case('git_worktree', git_case)


def bare_git(base, path, env):
    (path / 'HEAD').write_text('ref: refs/heads/main\n')
    (path / 'objects').mkdir()
    (path / 'refs').mkdir()
    age(path)


case('bare_git', lambda: tmp_case('bare', bare_git))
case('other_uid', lambda: tmp_case('other-uid'))
case('uv_cache', lambda: tmp_case('workbay-uv-cache'))
case('acx_build', lambda: tmp_case('acx-build'))


def symlink_case():
    with fixture('delete') as (base, env):
        external = base / 'external'
        external.mkdir()
        (external / 'data').write_text('keep')
        (base / 'tmp/link').symlink_to(external)
        os.utime(base / 'tmp/link', (OLD, OLD), follow_symlinks=False)
        run(base, env)
        assert (base / 'tmp/link').is_symlink() and (external / 'data').exists()


case('symlink', symlink_case)


def prefix_case():
    def setup(base, path, env):
        proc = base / 'proc/124'
        proc.mkdir()
        (proc / 'cwd').symlink_to(str(path) + '-sibling')
    tmp_case('prefix', setup, held=False)


case('live_prefix_boundary', prefix_case)


def race_case():
    with fixture('delete') as (base, env):
        path = old_tree(base, 'race')
        # The first probe is quiet; the second resolves a newly live cwd.
        with (base / 'shim/sitecustomize.py').open('a') as f:
            f.write('''
readlink_original = os.readlink
readlink_calls = 0
def race_readlink(path, *args, **kwargs):
    global readlink_calls
    if str(path).endswith('/123/cwd'):
        readlink_calls += 1
        if readlink_calls >= 2:
            return os.environ['HYGIENE_TMP_ROOT'] + '/race'
        raise FileNotFoundError(path)
    return readlink_original(path, *args, **kwargs)
os.readlink = race_readlink
''')
        (base / 'proc/123/fd').mkdir(parents=True)
        summary = run(base, env)
        assert path.exists() and summary['tmp']['held'] == 1, 'liveness was not rechecked'


case('liveness_recheck', race_case)


def unreadable_proc():
    with fixture('delete') as (base, env):
        path = old_tree(base, 'unreadable')
        with (base / 'shim/sitecustomize.py').open('a') as f:
            f.write('''
scandir_original = os.scandir
def blocked_scandir(path):
    if os.fspath(path) == os.environ['HYGIENE_PROC_ROOT']:
        raise PermissionError('fixture')
    return scandir_original(path)
os.scandir = blocked_scandir
''')
        result = run(base, env, ok=False)
        summary = json.loads(result.stdout.splitlines()[-1])
        assert path.exists() and summary['tmp']['held'] == 1 and summary['tmp']['errors'] == 1


case('unreadable_proc_held', unreadable_proc)


def mount_case():
    def setup(base, path, env):
        with (base / 'shim/sitecustomize.py').open('a') as f:
            f.write('''
lstat_original = os.lstat
def mount_lstat(path, *args, **kwargs):
    result = lstat_original(path, *args, **kwargs)
    mount = os.path.join(os.environ['HYGIENE_TMP_ROOT'], 'mount')
    if os.fspath(path) == mount or os.fspath(path).startswith(mount + os.sep):
        attrs = {key: getattr(result, key) for key in dir(result) if key.startswith('st_')}
        attrs['st_dev'] = result.st_dev + 1
        return SimpleNamespace(**attrs)
    return result
os.lstat = mount_lstat
''')
    tmp_case('mount', setup)


case('top_level_mount_held', mount_case)


def volumes_case(check):
    with fixture() as (base, env):
        summary = run(base, env)
        state = json.loads((base / 'docker.json').read_text())
        check(base, env, summary, state)


def assert_that(value, message):
    assert value, message


case('old_anonymous_removed', lambda: volumes_case(lambda b, e, s, state: (
    assert_that(ANON[0] not in state['volumes'], 'old anonymous volume retained'))))


def kept_volume(key):
    volumes_case(lambda b, e, s, state: assert_that(key in state['volumes'], 'protected volume removed'))


case('named_volume', lambda: kept_volume('named-data'))
case('in_use_volume', lambda: kept_volume(ANON[1]))
case('young_volume', lambda: kept_volume(ANON[2]))
case('dangling_but_in_use', lambda: kept_volume(ANON[3]))


def volume_race():
    with fixture() as (base, env):
        env['RACE_VOLUME'] = ANON[0]
        run(base, env)
        assert ANON[0] in json.loads((base / 'docker.json').read_text())['volumes']


case('volume_recheck', volume_race)


def metrics():
    with fixture() as (base, env):
        summary = run(base, env)
        assert summary['build_cache']['before'] == 16384 and summary['build_cache']['freed'] == 16384
        assert summary['volumes']['freed'] == 4096
        assert summary['images']['before'] == 65536 and summary['images']['freed'] == 0
        assert summary['journald']['before'] == 8192 and summary['journald']['freed'] == 0
        assert all(s['errors'] == 0 for s in summary.values())


case('metrics_and_no_image_deletion', metrics)


def journal_units():
    with fixture() as (base, env):
        env['JOURNAL_SIZE'] = '2K'
        assert run(base, env)['journald']['before'] == 2048


case('journal_binary_units', journal_units)


def install_case():
    with fixture() as (base, env):
        (base / 'etc/default/acx-host-hygiene').unlink()
        run(base, env, installer=True)
        targets = [base / 'usr/local/sbin/acx-host-hygiene',
                   base / 'etc/systemd/system/acx-host-hygiene.service',
                   base / 'etc/systemd/system/acx-host-hygiene.timer',
                   base / 'etc/systemd/journald.conf.d/60-acx-size.conf',
                   base / 'etc/default/acx-host-hygiene']
        assert all(p.exists() for p in targets)
        assert 'ACX_HYGIENE_TMP_MODE=report' in targets[-1].read_text()
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in targets]
        run(base, env, installer=True)
        assert before == [(p.read_bytes(), p.stat().st_mtime_ns) for p in targets], 'reinstall changed declared files'
        service, timer, journal = [p.read_text() for p in targets[1:4]]
        for setting in ['Type=oneshot', 'User=root', 'Nice=19', 'IOSchedulingClass=idle', 'TimeoutStartSec=1800', 'ExecStart=/usr/local/sbin/acx-host-hygiene']:
            assert setting in service, setting
        for setting in ['OnCalendar=daily', 'Persistent=true', 'RandomizedDelaySec=1h']:
            assert setting in timer, setting
        assert 'SystemMaxUse=512M' in journal
        calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
        assert calls.count(['systemctl', 'restart', 'systemd-journald']) == 1
        assert ['systemctl', 'enable', '--now', 'acx-host-hygiene.timer'] in calls
        assert not any(p.name.startswith('.acx-') for p in base.rglob('*')), 'installer leaked scratch'


case('installer_idempotent', install_case)


def uninstall_case():
    with fixture() as (base, env):
        run(base, env, installer=True)
        unrelated = base / 'etc/systemd/journald.conf.d/unrelated.conf'
        unrelated.write_text('keep')
        run(base, env, installer=True, args=['--uninstall'])
        run(base, env, installer=True, args=['--uninstall'])
        for rel in ['usr/local/sbin/acx-host-hygiene', 'etc/default/acx-host-hygiene',
                    'etc/systemd/system/acx-host-hygiene.service', 'etc/systemd/system/acx-host-hygiene.timer',
                    'etc/systemd/journald.conf.d/60-acx-size.conf']:
            assert not (base / rel).exists(), 'uninstall retained ' + rel
        assert unrelated.read_text() == 'keep'
        calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
        assert ['systemctl', 'disable', '--now', 'acx-host-hygiene.timer'] in calls
        assert ['systemctl', 'stop', 'acx-host-hygiene.service'] in calls
        assert calls.count(['systemctl', 'restart', 'systemd-journald']) == 2


case('installer_uninstall', uninstall_case)


def nonroot():
    with fixture() as (base, env):
        env['FAKE_UID'] = '1000'
        run(base, env, ok=False)
        run(base, env, installer=True, ok=False)
        run(base, env, installer=True, args=['--uninstall'], ok=False)
        assert not (base / 'usr/local').exists()
        assert not (base / 'calls').read_text().count('systemctl')


case('installer_refuses_nonroot', nonroot)


def install_recovery():
    with fixture() as (base, env):
        env['FAIL_SYSTEMCTL'] = 'restart'
        run(base, env, installer=True, ok=False)
        pending = base / 'etc/systemd/journald.conf.d/.acx-size-restart-pending'
        assert pending.exists()
        env.pop('FAIL_SYSTEMCTL')
        run(base, env, installer=True)
        assert not pending.exists()
        env['FAIL_SYSTEMCTL'] = '1'
        run(base, env, installer=True, args=['--uninstall'], ok=False)
        assert (base / 'etc/systemd/system/acx-host-hygiene.timer').exists()
        env.pop('FAIL_SYSTEMCTL')
        env['FAIL_SYSTEMCTL'] = 'restart'
        run(base, env, installer=True, args=['--uninstall'], ok=False)
        assert not (base / 'etc/systemd/system/acx-host-hygiene.timer').exists()
        assert pending.exists()
        env.pop('FAIL_SYSTEMCTL')
        run(base, env, installer=True, args=['--uninstall'])
        assert not pending.exists()


case('installer_failure_recovery', install_recovery)


def preserve_delete():
    with fixture('delete') as (base, env):
        run(base, env, installer=True)
        assert (base / 'etc/default/acx-host-hygiene').read_text() == 'ACX_HYGIENE_TMP_MODE=delete\n'


case('installer_preserves_operator_mode', preserve_delete)


def invalid_mode():
    with fixture('invalid') as (base, env):
        path = old_tree(base, 'old')
        run(base, env, ok=False)
        assert path.exists()


case('invalid_mode', invalid_mode)


def malformed_mode():
    for mode in ["'delete\"", 'delete#invalid']:
        with fixture(mode) as (base, env):
            path = old_tree(base, 'malformed')
            run(base, env, ok=False)
            assert path.exists(), 'malformed defaults enabled deletion'


case('malformed_mode', malformed_mode)


def quoted_delete_mode():
    for mode in ["'delete'", '"delete"']:
        with fixture(mode) as (base, env):
            path = old_tree(base, 'quoted')
            run(base, env)
            assert not path.exists(), 'quoted delete mode did not enable deletion'


case('quoted_delete_mode', quoted_delete_mode)


def default_report():
    with fixture() as (base, env):
        (base / 'etc/default/acx-host-hygiene').unlink()
        env['ACX_HYGIENE_TMP_MODE'] = 'delete'
        path = old_tree(base, 'default')
        summary = run(base, env)
        assert path.exists() and summary['tmp']['mode'] == 'report'


case('default_report', default_report)


def docker_failure():
    with fixture() as (base, env):
        env['FAIL_DOCKER'] = '1'
        result = run(base, env, ok=False)
        summary = json.loads(result.stdout.splitlines()[-1])
        assert summary['build_cache']['errors'] > 0 and summary['volumes']['errors'] > 0
        assert summary['journald']['errors'] == 0


case('class_failure_continues', docker_failure)


def timeout_case():
    with fixture() as (base, env):
        env.update(SLOW_DOCKER='1', HYGIENE_CLASS_TIMEOUT='1')
        start = time.monotonic()
        result = run(base, env, ok=False)
        assert time.monotonic() - start < 8
        summary = json.loads(result.stdout.splitlines()[-1])
        assert summary['images']['errors'] > 0 and summary['journald']['errors'] == 0


case('class_timeouts', timeout_case)
# GTMC-C81V-HH-M1: independently eligible children and local barriers.
def child_reclaim(kind, mode='delete'):
    with fixture(mode) as (base, env):
        container = base / 'tmp' / ('pytest-of-fixture' if kind.startswith('pytest') else 'mixed')
        container.mkdir()
        old = container / 'old'
        old.mkdir()
        (old / 'data').write_bytes(b'x' * 8192)
        protected = container / 'protected'
        protected.mkdir()
        (protected / 'data').write_bytes(b'y' * 4096)
        if kind == 'git':
            (protected / '.git').mkdir()
        age(container)
        if kind == 'pytest':
            (protected / 'data').touch()
        if kind == 'pytest-old':
            os.utime(protected / 'data', (OLD + 100, OLD + 100))
        if kind == 'scan':
            # Trigger the real 100000-entry boundary without allocating that debris.
            with (base / 'shim/sitecustomize.py').open('a') as f:
                f.write("""
scandir_original = os.scandir
class RepeatedEntries:
    def __enter__(self):
        self.source = scandir_original(os.environ['HYGIENE_TMP_ROOT'] + '/mixed/protected')
        self.entry = next(self.source)
        return iter([self.entry] * 100001)
    def __exit__(self, *args):
        self.source.close()
def limit_scandir(path):
    if os.fspath(path).endswith('/mixed/protected'):
        return RepeatedEntries()
    return scandir_original(path)
os.scandir = limit_scandir
""")
        summary = run(base, env)['tmp']
        assert protected.exists(), 'HH-M1 protected child removed'
        assert old.exists() == (mode == 'report'), 'HH-M1 eligible sibling retained'
        if mode == 'report':
            assert summary['would_reclaim'] >= 8192, 'HH-M1 reclaim bytes missing'
            assert summary['entries'][container.name]['would_reclaim'] >= 8192
            assert summary['skip_reasons']['newest_child']['bytes'] >= 4096
        if kind in ('git', 'scan'):
            reason = 'git' if kind == 'git' else 'scan_limit'
            assert summary['skip_reasons'][reason]['count'] == 1, 'HH-M1 local skip not logged'

case('pytest_children', lambda: child_reclaim('pytest'))
case('git_subtree_only', lambda: child_reclaim('git'))
case('scan_subtree_only', lambda: child_reclaim('scan'))
case('report_reclaim_bytes', lambda: child_reclaim('pytest', 'report'))

case('pytest_newest_old', lambda: child_reclaim('pytest-old'))


def pytest_recent_nonnewest():
    with fixture('delete') as (base, env):
        root = base / 'tmp/pytest-of-fixture'
        root.mkdir()
        children = []
        for name in ('old', 'recent', 'newest'):
            child = root / name
            child.mkdir()
            (child / 'data').write_bytes(b'x' * 4096)
            children.append(child)
        age(root)
        os.utime(children[1] / 'data', (time.time() - 3600, time.time() - 3600))
        (children[2] / 'data').touch()
        summary = run(base, env)['tmp']
        assert not children[0].exists(), 'HH-M1 old pytest child retained'
        assert children[1].exists(), 'HH-M1 recent non-newest child removed'
        assert children[2].exists(), 'HH-M1 newest pytest child removed'
        assert summary['skip_reasons']['recent']['count'] == 1
        assert summary['skip_reasons']['newest_child']['count'] == 1


case('pytest_recent_nonnewest', pytest_recent_nonnewest)


def tmp_report_only():
    with fixture('delete') as (base, env):
        path = old_tree(base, 'old')
        result = subprocess.run(['bash', str(SWEEP), '--tmp-report'], env=env,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        summary = json.loads(result.stdout.splitlines()[-1])
        assert set(summary) == {'tmp'}, 'HH-M1 report ran other classes'
        assert summary['tmp']['mode'] == 'report' and path.exists()
        assert summary['tmp']['would_reclaim'] >= 8192
        assert not (base / 'calls').exists(), 'HH-M1 report ran host operations'


case('tmp_report_only', tmp_report_only)
membership = Counter(name for names in GROUPS.values() for name in names)
assert set(membership) == set(CASES), (
    f'group coverage mismatch: missing={sorted(set(CASES) - set(membership))}, '
    f'unknown={sorted(set(membership) - set(CASES))}'
)
assert all(count == 1 for count in membership.values()), 'cases belong to multiple groups'
for name, callback in CASES.items():
    run_case(name, callback)
assert passed > 0, 'case selector matched no tests'
print(f'host hygiene cases passed: {passed}')
print('all cases passed, 0 skipped')
PY
