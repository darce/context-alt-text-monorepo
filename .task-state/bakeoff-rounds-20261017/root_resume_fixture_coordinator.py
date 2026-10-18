"""Remote Root test orchestration using complete, pinned existing fixture modules."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import types

FLOW_SHA256 = '369c120b901b1ee3faeb642d6d498ef2ae0e5b98904c44d0b1a9c64c3a51e062'


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sealed(path, expected=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        require(st.st_uid == 0 and stat.S_ISREG(st.st_mode)
                and stat.S_IMODE(st.st_mode) == 0o400 and st.st_nlink == 1,
                'Root0400 single-link regular file required')
        require(st.st_size <= 2 * 1024**2, 'fixture input bound')
        data = os.read(fd, 2 * 1024**2 + 1)
        require(expected is None or hashlib.sha256(data).hexdigest() == expected,
                'fixture source pin mismatch')
        return data
    finally:
        os.close(fd)


def main():
    if os.getuid() != 0 or os.geteuid() != 0:
        print('ROOT_REQUIRED', file=sys.stderr)
        return 77
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--case', choices=['old-red', 'new-green'])
    parser.add_argument('--output')
    parser.add_argument('--parent-namespaces')
    args = parser.parse_args()
    base = Path(args.input_root)
    require(base.is_absolute() and '..' not in base.parts
            and str(base).startswith('/root/'), 'Root custody outside fixture overlays')
    manifest = json.loads(sealed(base / 'input-manifest.json', args.manifest_sha256))
    for name, expected in manifest['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts,
                'relative fixture member')
        sealed(base / name, expected)
    sealed(base / 'OWNER-FLOW-CONTROLS-R2.py', FLOW_SHA256)
    h = load('complete_prior_root_flow', base / 'OWNER-FLOW-CONTROLS-R2.py')
    h.capabilities()
    h.HARNESS_SHA = hashlib.sha256(sealed(base / 'OWNER-FLOW-CONTROLS-R2.py')).hexdigest()
    h.HELD.append(h.directory(base))
    os.umask(0o077)

    if args.case:
        require(os.getpid() == 1, 'new namespace PID1 required')
        scripts, ids = h.stage_read(base / 'old-procedure')
        raw = h.bundle_read(base / 'source-bundle')
        prior_flow = h.flow
        d = load('sealed_root_fixture_driver', base / 'root_fixture_plan.py')
        prior_fixture = h.fixture
        receipt_fd = None

        def receipted_fixture(*fixture_args):
            # Passive bracketing only: execute the WHOLE original fixture,
            # without replacing its mounts, writers, or other production paths.
            nonlocal receipt_fd
            require(receipt_fd is None and not h.children(), 'sole fresh fixture creator required')
            creator = d.creator_identity()
            with d.held_inventory(before_fixture=True) as before:
                stage = prior_fixture(*fixture_args)
                require(not h.children() and creator == d.creator_identity(), 'fixture creator changed')
                with d.held_inventory() as after:
                    d.fresh_overlays(before, after)
                    receipt_fd = os.memfd_create('flow-fresh-overlays', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
                    h.HELD.append(receipt_fd)
                    receipt = dict(version=1, creator=creator, creator_fd=receipt_fd,
                                   before=before, after=after)
                    data = (json.dumps(receipt, sort_keys=True) + '\n').encode()
                    pending = memoryview(data)
                    while pending:
                        written = os.write(receipt_fd, pending)
                        require(written > 0, 'receipt write progress')
                        pending = pending[written:]
                    os.fchmod(receipt_fd, 0o400)
                    fcntl.fcntl(receipt_fd, getattr(fcntl, 'F_ADD_SEALS', 1033), d.RECEIPT_SEALS)
                    h.put(Path(fixture_args[3]) / 'fresh-overlay-receipt.json', data)
            return stage

        h.fixture = receipted_fixture

        def selected_flow(control, stage, source, native, reaper, run):
            prior_flow(control, stage, source, native, reaper, run)
            require(not h.children(), 'prior genuine AUTO4 fixture must be quiescent')
            require(receipt_fd is not None, 'creator overlay receipt required')
            windows = h.windows()
            require(len(windows) == 1, 'one genuine retained fixture window')
            phase = run / 'resume-selected'
            h.mkdir(phase)
            if args.case == 'new-green':
                # The sole namespace PID1 owns admission; there are no other
                # native children or callers during this private stage swap.
                # Existing window identity, receipts and authority stay intact.
                for name in ['owner-window.py', 'approved-scripts.json']:
                    data = sealed(base / 'new-procedure' / name,
                                  manifest['files']['new-procedure/' + name])
                    tmp = stage / ('.resume-' + name)
                    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
                    try:
                        with os.fdopen(fd, 'wb', closefd=False) as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                    finally:
                        os.close(fd)
                    os.replace(tmp, stage / name)
                directory = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            output = Path('/tmp/resume-selected-output')
            h.mkdir(output)
            argv = ['/usr/bin/python3', '-I', '-B', str(base / 'root_fixture_plan.py'),
                    '--run', '--expect', args.case, '--stage', str(stage),
                    '--window', str(windows[0]), '--output', str(output),
                    '--parent-namespaces', str(args.parent_namespaces),
                    '--overlay-receipt-fd', str(receipt_fd)]
            with (phase / 'driver.stdout').open('xb') as stdout, (phase / 'driver.stderr').open('xb') as stderr:
                child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout,
                                         stderr=stderr, close_fds=True, pass_fds=(receipt_fd,), env=h.ENV)
                h.put(phase / 'driver-launch.json', h.identity(child.pid))
                # Popen.wait never kills the child on timeout. The complete
                # prior namespace supervisor retains PID1 and all children on
                # any exception, including an uncertain native publication.
                rc = child.wait(timeout=115)
                stdout.flush(); stderr.flush()
                os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
            h.put(phase / 'driver-wait.json', {'exit_code': rc, 'native_reaped': True})
            require(rc == 0, 'selected Root continuation failed; retain namespace')
            result = json.loads((output / 'selected-fixture-result.json').read_bytes())
            require(result['status'] == 'SELECTED_ISOLATED_CONTROL_PASS'
                    and result['expect'] == args.case, 'selected Root result binding')
            h.put(phase / 'selected-result.json', result)
            h.reap_adopted(phase)
            require(not h.children(), 'selected continuation native closure')
            h.archive_owned(phase)

        h.flow = selected_flow
        fixture = types.SimpleNamespace(stage=str(base / 'old-procedure'),
                                        bundle=str(base / 'source-bundle'),
                                        run=str(args.output), controls='positive',
                                        parent_namespaces=sealed(Path(args.parent_namespaces)).decode())
        return h.namespace_child(fixture, scripts, ids, raw)

    output = base / 'output'
    h.mkdir(output)
    h.put(output / 'parent-namespaces.json', h.ns())
    children = []
    for case in ['old-red', 'new-green']:
        run = output / case
        h.mkdir(run)
        stdout = (run / 'launcher.stdout').open('xb')
        stderr = (run / 'launcher.stderr').open('xb')
        child = subprocess.Popen(['/usr/bin/unshare', '--propagation', 'unchanged',
                                  '--mount', '--pid', '--net', '--fork',
                                  '/usr/bin/python3', '-I', '-B', str(Path(__file__).absolute()),
                                  '--input-root', str(base), '--manifest-sha256', args.manifest_sha256,
                                  '--case', case, '--output', str(run), '--parent-namespaces',
                                  str(output / 'parent-namespaces.json')],
                                 stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                 close_fds=True, env=h.ENV)
        pidfd = os.pidfd_open(child.pid)
        h.put(run / 'launcher.json', h.identity(child.pid))
        children.append((case, child, pidfd, stdout, stderr))
    end = time.monotonic() + 200
    results = {}
    try:
        for case, child, pidfd, stdout, stderr in children:
            rc = child.wait(timeout=max(.1, end - time.monotonic()))
            require(rc == 0, 'namespace refused; retain exact custody')
            stdout.flush(); stderr.flush()
            os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
            result_path = output / case / 'resume-selected/selected-result.json'
            result = json.loads(result_path.read_bytes())
            require(result['expect'] == case and result['status'] == 'SELECTED_ISOLATED_CONTROL_PASS',
                    'Root selected result missing')
            results[case] = {'exit_code': rc, 'native_reaped': True,
                             'result_sha256': hashlib.sha256(result_path.read_bytes()).hexdigest()}
        h.put(output / 'aggregate.json', {'status': 'ROOT_SELECTED_RESUME_PASS', 'cases': results,
                                        'manifest_sha256': args.manifest_sha256,
                                        'no_live_cloud_or_readiness_qualification': True})
    except BaseException as exc:
        h.put(output / 'UNKNOWN.json', {'status': 'UNKNOWN', 'detail': repr(exc),
                                      'policy': 'retain supervisor/PID1/guardians/handles; no signal or teardown'})
        while True:
            time.sleep(1)
    for _, _, pidfd, stdout, stderr in children:
        os.close(pidfd); stdout.close(); stderr.close()
    h.close_held()
    print(json.dumps({'status': 'ROOT_SELECTED_RESUME_PASS', 'output': str(output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
