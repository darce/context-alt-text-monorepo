#!/usr/bin/env python3
"""Coordinator-only isolated fixture continuation; never a live-window runner.

--plan prints the executable contract. --run requires an already prepared,
root-protected full fixture from OWNER-FLOW-CONTROLS-R2 concepts, not host state.
Exit 77 = actual root required, 65 = prerequisite/control refusal, 124 = UNKNOWN:
coordinator PID1 MUST retain namespace/guardians/fences and reconcile quiescence.
No namespace setup, writer substitution, authority reset or deployment is done.
"""
import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys

MANIFESTS = {'old-red': '70831dc4247ebd31b34094f915aadf36534116ff0aaa26339ad3abdaccbfef26',
             'new-green': '991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406'}
TARGETS = ('/run', '/var/lib', '/var/log', '/tmp', '/opt')
# Linux memfd seal ABI; keep read-only --plan importable on other platforms.
RECEIPT_SEALS = 0x000f  # SEAL, SHRINK, GROW, WRITE
CONTRACT = {
    'status': 'PLAN_ONLY_ROOT_PENDING',
    'prepare': [
        'Root seals this driver root0400 in root0700 custody; verify report SHA256 before execution.',
        'Reuse complete supplied OWNER-FLOW-CONTROLS-R2.py fixture concepts, pin 369c120b901b1ee3faeb642d6d498ef2ae0e5b98904c44d0b1a9c64c3a51e062.',
        'Coordinator PID1 owns fresh MNT/PID/NET namespaces, recursive-private propagation and private proc; retain namespace on any UNKNOWN.',
        'Mount private tmpfs over /run,/var/lib,/var/log,/tmp,/opt; real ubuntu1001->sudo, real UID10001 producer, root0700 stage/root0400 pins; no host changes.',
        'Trusted PID1 captures held-descriptor mount inventories immediately before/after the complete original fixture(), in the SAME fixture namespace with no native children. Before capture permits ordinary directories within their containing mounts and records the complete mount inventory; after/current capture requires exact target mountpoints. Seal JSON in root0400 memfd with WRITE/GROW/SHRINK/SEAL seals; retain it in PID1 and pass only that FD to this direct child using --overlay-receipt-fd. New mount IDs AND fresh backing devices must be absent from the pre-fixture inventory; namespace-copy ID changes alone are insufficient.',
        'Use complete pinned native writer/load sources and real persistent fences; no fake ACK, production prefix or replacement writer.',
        'Prepare one isolated window with genuine first-use START1/AUTO2/STOP3/AUTO4 custody and consumed authority/publications; current fresh four idle load receipts.',
        'Use independent old/new fixtures with their exact complete seven-script manifests. Preserve each fixture window/procedure identity throughout continuation.',
        'Provide root0400 parent-namespaces.json captured OUTSIDE these namespaces; output directory must already exist inside isolated /tmp.',
    ],
    'commands': [
        'PID1 passes sealed receipt FD N: python3 -I -B /ROOT_SEALED/root_fixture_plan.py --run --overlay-receipt-fd N --expect old-red --stage /tmp/PRIVATE_OLD_STAGE --window /tmp/EXISTING_FIXTURE_WINDOW --parent-namespaces /ROOT_SEALED/parent-namespaces.json --output /tmp/PRIVATE_EVIDENCE',
        'PID1 passes sealed receipt FD N: python3 -I -B /ROOT_SEALED/root_fixture_plan.py --run --overlay-receipt-fd N --expect new-green --stage /tmp/PRIVATE_NEW_STAGE --window /tmp/EXISTING_FIXTURE_WINDOW --parent-namespaces /ROOT_SEALED/parent-namespaces.json --output /tmp/PRIVATE_EVIDENCE',
    ],
    'bounded_waits': 'Each public CLI has timeout45s and outer wait50s; no timeout kills/retries by this driver. PID1 retains custody on rc124 or incomplete evidence.',
    'assertions': 'old: rc1 exact parser error, unchanged ops/view; new: genuine START5 and AUTO6 receipts in the SAME fixture window, candidate=publication, native reaped/completed, reconcile exact operation.',
    'remaining_root_matrix': 'Coordinator should also replay first-use and foreign/unknown/newer/unpublished predecessor, rejected/deferred/unknown/busy load and live-handle refusal controls in independent isolated fixtures. Unit evidence is not privileged qualification.',
    'live_upgrade': 'See ROOT-HANDOFF.md; never use this fixture driver against the existing live window.',
}


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def namespaces(pid='self'):
    return {n: os.readlink('/proc/' + str(pid) + '/ns/' + n) for n in ('mnt', 'pid', 'net')}


def creator_identity():
    status = Path('/proc/1/status').read_text().splitlines()
    require(next(x.split()[1:] for x in status if x.startswith('Uid:')) == ['0'] * 4,
            'Root creator required')
    start = Path('/proc/1/stat').read_text().rpartition(') ')[2].split()[19]
    return dict(pid=1, starttime=start, namespaces=namespaces(1))


def mount_rows():
    rows = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ')
        fields = left.split()
        require(not any(p.startswith(('shared:', 'master:')) for p in fields[6:]),
                'private propagation required')
        rows.append(dict(mount_id=int(fields[0]), device=fields[2], root=fields[3],
                         target=fields[4], fstype=right.split()[0]))
    require(len({r['mount_id'] for r in rows}) == len(rows), 'duplicate mount ID')
    return rows


def descriptor_mount(fd):
    fields = Path('/proc/self/fdinfo/' + str(fd)).read_text().splitlines()
    ids = [int(line.split()[1]) for line in fields if line.startswith('mnt_id:')]
    require(len(ids) == 1, 'descriptor mount ID required')
    return ids[0]


@contextmanager
def held_inventory(*, before_fixture=False):
    """Hold visible directory FDs; only before creation allow containing mounts.

    The complete mount list is retained in both modes. After/current callers
    keep the exact-target contract; before directories need not be mountpoints.
    """
    with ExitStack() as held:
        rows = mount_rows()
        targets = {}
        for target in TARGETS:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                for part in Path(target).parts[1:]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    os.close(fd)
                    fd = nxt
                held.callback(os.close, fd)
            except BaseException:
                os.close(fd)
                raise
            mid = descriptor_mount(fd)
            matching = [r for r in rows if r['mount_id'] == mid]
            require(len(matching) == 1 and (matching[0]['target'] == target or
                    before_fixture and Path(matching[0]['target']) in Path(target).parents),
                    'visible descriptor mount mismatch: ' + target)
            st = os.fstat(fd)
            device = f'{os.major(st.st_dev)}:{os.minor(st.st_dev)}'
            require(stat.S_ISDIR(st.st_mode) and device == matching[0]['device'],
                    'visible descriptor device mismatch: ' + target)
            targets[target] = dict(matching[0], ino=st.st_ino)
        yield dict(namespaces=namespaces(), mounts=rows, targets=targets)


def fresh_overlays(before, after):
    require(before['namespaces'] == after['namespaces'], 'same-namespace fresh inventory required')
    require(set(before['targets']) == set(after['targets']) == set(TARGETS), 'complete overlay targets required')
    old_ids = {r['mount_id'] for r in before['mounts']}
    old_devices = {r['device'] for r in before['mounts']}
    for target in TARGETS:
        visible = after['targets'][target]
        require(visible['target'] == target and visible['fstype'] == 'tmpfs' and visible['root'] == '/',
                'fresh tmpfs root required: ' + target)
        require(visible['mount_id'] not in old_ids and visible['device'] not in old_devices,
                'fresh overlay backing required: ' + target)
        require(any(dict(r, ino=visible['ino']) == visible for r in after['mounts']),
                'receipt visible mount mismatch: ' + target)


def sealed_overlay_receipt(fd):
    require(isinstance(fd, int) and fd >= 0, 'sealed overlay receipt FD required')
    st = os.fstat(fd)
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o400
            and st.st_nlink == 0 and 0 < st.st_size <= 1048576, 'sealed Root memfd receipt required')
    require(fcntl.fcntl(fd, getattr(fcntl, 'F_GET_SEALS', 1034)) & RECEIPT_SEALS == RECEIPT_SEALS,
            'immutable overlay receipt required')
    receipt = json.loads(os.pread(fd, 1048577, 0))
    number = receipt['creator_fd']
    require(type(number) is int and number >= 0, 'creator receipt FD required')
    owner = os.stat('/proc/1/fd/' + str(number))
    require((owner.st_dev, owner.st_ino) == (st.st_dev, st.st_ino), 'creator-held receipt mismatch')
    return receipt


def private_fixture(receipt_fd, parent):
    require(os.getppid() == 1, 'sole coordinator PID1 parent required')
    require(Path('/proc/1/task/1/children').read_text().split() == [str(os.getpid())],
            'sole native child required')
    receipt = sealed_overlay_receipt(receipt_fd)
    creator = creator_identity()
    require(receipt['version'] == 1 and receipt['creator'] == creator, 'stale or mismatched creator receipt')
    with held_inventory() as current:
        require(creator['namespaces'] == current['namespaces'] == receipt['before']['namespaces']
                == receipt['after']['namespaces'], 'receipt namespace mismatch')
        require(all(current['namespaces'][n] != parent[n] for n in parent), 'fresh MNT/PID/NET required')
        fresh_overlays(receipt['before'], receipt['after'])
        require(current['targets'] == receipt['after']['targets'], 'visible descriptor receipt mismatch')


def run(args):
    require(os.getuid() == os.geteuid() == 0, 'actual Root required')
    require(pwd.getpwnam('ubuntu').pw_uid == pwd.getpwnam('ubuntu').pw_gid == 1001, 'actual ubuntu1001 required')
    require(os.getpid() != 1, 'coordinator PID1 must retain this fixture independently')
    parent = Path(args.parent_namespaces)
    ps = parent.lstat()
    require(stat.S_ISREG(ps.st_mode) and ps.st_uid == 0 and stat.S_IMODE(ps.st_mode) == 0o400
            and ps.st_nlink == 1 and ps.st_size <= 4096, 'sealed parent namespace evidence required')
    before = json.loads(parent.read_bytes())
    require(set(before) == {'mnt', 'pid', 'net'}, 'parent namespace inventory')
    require(all(os.readlink('/proc/self/ns/' + n) != before[n] for n in before), 'fresh MNT/PID/NET required')
    lines = Path('/proc/self/mountinfo').read_text().splitlines()
    require(all(not any(p.startswith(('shared:', 'master:')) for p in line.split(' - ')[0].split()[6:]) for line in lines), 'private propagation required')
    private_fixture(args.overlay_receipt_fd, before)
    stage, window, output = map(Path, (args.stage, args.window, args.output))
    for p in (stage, window, output):
        require(p.is_absolute() and '..' not in p.parts and str(p).startswith('/tmp/'), 'fixture path must be inside private /tmp')
    spec = importlib.util.spec_from_file_location('fixture_custody', stage / 'owner-custody.py')
    # Validate protected source ancestry/manifest BEFORE executing any candidate.
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in stage.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = nxt
            s = os.fstat(fd)
            require(s.st_uid == 0 and (not s.st_mode & 0o022 or stat.S_IMODE(s.st_mode) == 0o1777), 'unsafe stage ancestor')
        require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700, 'root0700 stage required')

        def sealed(name):
            f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
            try:
                s = os.fstat(f)
                require(s.st_uid == 0 and stat.S_ISREG(s.st_mode) and stat.S_IMODE(s.st_mode) == 0o400 and s.st_nlink == 1 and s.st_size <= 1048576, 'sealed stage file required')
                return os.read(f, 1048577)
            finally: os.close(f)

        raw = sealed('approved-scripts.json')
        require(hashlib.sha256(raw).hexdigest() == MANIFESTS[args.expect], 'exact stage manifest required')
        pins = json.loads(raw)
        require(set(os.listdir(fd)) == set(pins) | {'approved-scripts.json'}, 'complete stage only')
        for name, pin in pins.items():
            require('/' not in name and hashlib.sha256(sealed(name)).hexdigest() == pin, 'stage pin mismatch')
    finally: os.close(fd)
    c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
    outfd = c.directory(output, 0)
    wfd, w = c.validate_window(window)
    paths = c.Paths('/run/acx-write', '/var/lib/acx-gpu', '/var/lib/acx-gpu/lifecycle.lock', '/run/acx-gpu', 10001, 10001)
    try:
        require(w['procedure'] == str(stage), 'path-bound fixture procedure mismatch')
        previous = c.reconcile(wfd, paths)
        known = c.known_candidates(wfd)
        require(previous in known and known[previous]['sequence'] == 4 and known[previous]['action'] == 'auto', 'genuine AUTO4 fixture required')
        initial = c.view(paths, 'start')
        require(initial['authority']['highest_sequence'] == 4, 'consumed authority4 required')
        ops_before = sorted((window / 'ops').iterdir())

        def command(action, prior):
            argv = ['/usr/bin/sudo', '-n', '-H', '-u', 'ubuntu', '/usr/bin/sudo', '-n', '/usr/bin/timeout', '45s', '/usr/bin/python3', '-B', str(stage / 'owner-window.py'), action, str(window), prior]
            stdout = os.open(output / (action + '.stdout'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            stderr = os.open(output / (action + '.stderr'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, close_fds=True)
                c.seal(outfd, action + '-launch.json', dict(argv=argv, pid=child.pid))
                try: rc = child.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    c.seal(outfd, 'UNKNOWN.json', dict(pid=child.pid, policy='PID1 retain namespace/guardians/fences; no retry or teardown'))
                    raise SystemExit(124)
                c.seal(outfd, action + '-wait.json', dict(exit_code=rc, native_reaped=True))
                if rc == 124:
                    c.seal(outfd, 'UNKNOWN.json', dict(pid=child.pid, policy='CLI timed out; PID1 retain namespace/guardians/fences; no retry or teardown'))
                    raise SystemExit(124)
                return rc
            finally:
                for f in (stdout, stderr): os.fsync(f); os.fchmod(f, 0o400); os.close(f)

        rc = command('start', previous)
        if args.expect == 'old-red':
            require(rc == 1 and 'explicit previous operation required' in (output / 'start.stderr').read_text(), 'exact parser RED required')
            require(sorted((window / 'ops').iterdir()) == ops_before and c.view(paths, 'start') == initial, 'old RED changed state')
        else:
            require(rc == 0, 'START failed; retain custody and inspect exact window')
            start = (output / 'start.stdout').read_text().strip()
            require(c.reconcile(wfd, paths) == start, 'START missing native publication proof')
            p = c.known_candidates(wfd)[start]
            require(p['sequence'] == 5 and p['action'] == 'start' and p['requested_by'] == known[previous]['requested_by'], 'resumed identity/sequence mismatch')
            require(command('auto', start) == 0, 'AUTO failed; retain custody')
            auto = (output / 'auto.stdout').read_text().strip()
            require(c.reconcile(wfd, paths) == auto, 'AUTO missing native publication proof')
            q = c.known_candidates(wfd)[auto]
            require(q['sequence'] == 6 and q['action'] == 'auto' and q['requested_by'] == p['requested_by'], 'withdrawal identity/sequence mismatch')
        c.seal(outfd, 'selected-fixture-result.json', dict(status='SELECTED_ISOLATED_CONTROL_PASS', expect=args.expect, window=w, manifest_sha256=MANIFESTS[args.expect], no_live_qualification=True))
    finally: os.close(wfd); os.close(outfd)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--expect', choices=tuple(MANIFESTS))
    parser.add_argument('--overlay-receipt-fd', type=int)
    for name in ('stage', 'window', 'parent-namespaces', 'output'): parser.add_argument('--' + name)
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(CONTRACT, indent=2)); raise SystemExit(0)
    if os.getuid() != 0 or os.geteuid() != 0:
        print('ROOT_REQUIRED: no fixture executed', file=sys.stderr); raise SystemExit(77)
    if not args.run or args.overlay_receipt_fd is None or not all((args.expect, args.stage, args.window, args.parent_namespaces, args.output)):
        parser.error('--run requires --expect/--stage/--window/--parent-namespaces/--output/--overlay-receipt-fd')
    try: raise SystemExit(run(args))
    except Exception as exc:
        print('REFUSED_OR_UNRESOLVED: retain fixture custody; ' + repr(exc), file=sys.stderr)
        raise SystemExit(65)
