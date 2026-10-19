"""See checkpoint_fixture_plan.py for protected-input contract and invocation.

Selected native qualification driver. Crash-injection qualification remains
separate. No ordinary tests or selected pass certify full recovery safety.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

FLOW_SHA = '369c120b901b1ee3faeb642d6d498ef2ae0e5b98904c44d0b1a9c64c3a51e062'
NEW_ENVS = ('dev', 'dev-fir', 'prod', 'staging', 'dev-auraface')
ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root',
       'LANG': 'C', 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def protected(path):
    """Open every component without following links, retain bytes before import."""
    p = Path(path)
    require(p.is_absolute() and '..' not in p.parts, 'canonical absolute input')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in p.parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            s = os.fstat(fd)
            require(s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o700,
                    'Root0700 input ancestry required')
        f = os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            s = os.fstat(f)
            require(stat.S_ISREG(s.st_mode) and s.st_uid == 0 and s.st_nlink == 1
                    and stat.S_IMODE(s.st_mode) == 0o400 and s.st_size <= 2097152,
                    'Root0400 single-link bounded input required')
            return os.read(f, 2097153)
        finally:
            os.close(f)
    finally:
        os.close(fd)


def module(name, raw):
    import types
    m = types.ModuleType(name)
    sys.modules[name] = m
    exec(compile(raw, name, 'exec'), m.__dict__)
    return m


def remaining(deadline, cap):
    value = min(cap, deadline - time.monotonic())
    if value <= 0:
        raise TimeoutError('fixed 180s qualification deadline')
    return value


def snapshot(roots):
    result = {}
    for root in roots:
        root = Path(root)
        members = [root] + sorted(root.rglob('*')) if root.is_dir() else [root]
        require(len(members) <= 8192, 'snapshot inventory bound')
        for p in members:
            s = p.lstat()
            require(stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode), 'unexpected fixture link/type')
            result[str(p)] = [s.st_dev, s.st_ino, s.st_uid, s.st_gid, s.st_mode,
                              None if p.is_dir() else digest(p.read_bytes())]
    return result


def fifth_load(h, demand, revision):
    """Controlled private fixture input, under its real persistent load fence."""
    path = Path('/run/acx-write/dev-auraface')
    lock = os.open(path / 'describe-load.json.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = dict(written_at=time.time(), queue_depth=0, in_flight=0,
                     batch_in_progress=False, lease_demand=demand, revision=revision)
        temporary = path / ('fixture-load-' + uuid.uuid4().hex)
        h.put(temporary, value, 0o644)
        fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fchown(fd, 10001, 10001)
            s = os.fstat(fd)
            require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == s.st_gid == 10001
                    and stat.S_IMODE(s.st_mode) == 0o644, 'private fifth load ownership/mode')
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path / 'describe-load.json')
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return value
    finally:
        os.close(lock)


def provision_fifth(h, d, run, overlay_fd):
    """Only after legacy history, extend the proven private /run fixture."""
    overlay = d.sealed_overlay_receipt(overlay_fd)
    prefix = h.directory('/run/acx-write', private=False)
    try:
        s = os.fstat(prefix)
        require(d.descriptor_mount(prefix) == overlay['after']['targets']['/run']['mount_id']
                and s.st_uid == s.st_gid == 0 and stat.S_IMODE(s.st_mode) == 0o755,
                'fifth setup requires proven private Root0755 runtime prefix')
        require(set(os.listdir(prefix)) == set(NEW_ENVS[:-1]), 'exact legacy four-environment fixture')
        h.mkdir('/run/acx-write/dev-auraface', 0o770, 0, 10001)
        fd = os.open('dev-auraface', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=prefix)
        try:
            for name in ('gpu-intent.json.lock', 'describe-load.json.lock'):
                fence = os.open(name, os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                0o600, dir_fd=fd)
                try:
                    os.fchown(fence, 0, 10001)
                    os.fchmod(fence, 0o660)
                    s = os.fstat(fence)
                    require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_uid == 0
                            and s.st_gid == 10001 and stat.S_IMODE(s.st_mode) == 0o660,
                            'exclusive Root10001 persistent fifth fence')
                    os.fsync(fence)
                finally:
                    os.close(fence)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(prefix)
    finally:
        os.close(prefix)
    value = fifth_load(h, 0, 1)
    require(not os.path.lexists('/run/acx-write/dev-auraface/gpu-intent.json'),
            'fifth fixture must have no intent publication')
    h.put(run / 'fifth-fixture-setup.json', dict(environments=NEW_ENVS,
          private_run_mount=overlay['after']['targets']['/run'], load=value,
          custody=snapshot(['/run/acx-write'])))


def namespace(args, base, inputs, h, d, deadline):
    """Only entered as fresh namespace PID1. All effectful failures retain custody."""
    require(os.getpid() == 1, 'fresh namespace PID1 required')
    parent = json.loads(protected(args.parent_namespaces))
    require(all(h.ns()[n] != parent[n] for n in ('mnt', 'pid', 'net')), 'fresh namespace identities')
    nspid = next(x.split()[1:] for x in Path('/proc/self/status').read_text().splitlines()
                 if x.startswith('NSpid:'))
    require(len(nspid) >= 2 and nspid[-1] == '1', 'nested PID before privateproc')
    run = Path(args.output)
    try:
        h.command(['/usr/bin/mount', '--make-rprivate', '/'], remaining(deadline, 4))
        h.command(['/usr/bin/mount', '-t', 'proc', '-o', 'nosuid,nodev,noexec', 'proc', '/proc'], remaining(deadline, 4))
        require(not h.children(), 'empty privateproc')
        # Reuse qualified START predecessor parser; never rerun the obsolete parser bug.
        h.MANIFEST_SHA = '991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406'
        h.PINS = dict(h.PINS, **{'owner-window.py': '1983f8684de3d03a59c090b1b469e65f5b84ad201283e787bdf5fb872b8b6600'})
        scripts, ids = h.stage_read(base / 'old-procedure')
        raw = h.bundle_read(base / 'source-bundle')
        with d.held_inventory(before_fixture=True) as before:
            stage = h.fixture(base / 'old-procedure', scripts, ids, run)
            with d.held_inventory() as after:
                d.fresh_overlays(before, after)
                overlay_fd = os.memfd_create('checkpoint-overlay-proof', os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
                h.HELD.append(overlay_fd)
                receipt = dict(version=1, creator=d.creator_identity(), creator_fd=overlay_fd,
                               before=before, after=after)
                os.write(overlay_fd, json.dumps(receipt, sort_keys=True).encode())
                os.fchmod(overlay_fd, 0o400)
                fcntl.fcntl(overlay_fd, 1033, d.RECEIPT_SEALS)
                require(d.sealed_overlay_receipt(overlay_fd) == receipt, 'native sealed memfd identity')
                h.put(run / 'overlay-proof.json', receipt)
        installed = h.install_adapters(stage, run, raw, scripts)
        h.credential_preflight(stage, run, installed)
        reaper = h.public_modules(raw, base / 'source-bundle')
        lifecycle = h.Lifecycle(reaper, run)
        h.put('/var/lib/acx-gpu/lifecycle.lock', b'', 0o660)
        os.chown('/var/lib/acx-gpu/lifecycle.lock', 0, 10001)
        counter = 0

        def cli(source, action, *tail, reap_children=True):
            nonlocal counter
            counter += 1
            argv = ['/usr/bin/sudo', '-n', '-H', '-u', 'ubuntu', '/usr/bin/sudo', '-n',
                    '/usr/bin/python3', '-I', '-B', str(source / 'owner-window.py'), action, *map(str, tail)]
            prefix = run / ('cli-%03d' % counter)
            with Path(str(prefix) + '.stdout').open('xb') as out, Path(str(prefix) + '.stderr').open('xb') as err:
                p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=ENV)
                h.put(Path(str(prefix) + '.launch.json'), dict(argv=argv, identity=h.identity(p.pid)))
                end = time.monotonic() + remaining(deadline, 38)
                while p.poll() is None:
                    require(time.monotonic() < end, 'native CLI UNKNOWN deadline')
                    time.sleep(.02)
                rc = p.wait(timeout=remaining(deadline, 1))
                out.flush(); err.flush()
                os.fsync(out.fileno()); os.fsync(err.fileno())
            h.put(Path(str(prefix) + '.wait.json'), dict(exit_code=rc, native_reaped=True))
            # Guardians are genuine adopted children. Never treat frontend exit as reaping.
            if reap_children:
                h.reap_adopted(run / ('reap-%03d' % counter))
            return rc, Path(str(prefix) + '.stdout').read_text().strip(), Path(str(prefix) + '.stderr').read_text()

        # reap_adopted writes into an existing directory.
        original_reap = h.reap_adopted
        def reap(destination):
            h.mkdir(destination)
            return original_reap(destination)
        h.reap_adopted = reap
        rc, text, _ = cli(stage, 'new-window')
        require(rc == 0, 'native window creation')
        window = Path(text)
        require(window.parent == Path('/tmp') and window in h.windows(), 'private native window')
        require(cli(stage, 'inspect', window)[0] == 0, 'native source inspection')
        meta = h.read_json(window / 'window.json')
        previous = '-'
        for index in range(32 if args.case == 'selected' else 2):
            remaining(deadline, 1)
            rc, op, _ = cli(stage, 'start' if index % 2 == 0 else 'auto', window, previous)
            require(rc == 0, 'native history publication')
            stopped = h.read_json(window / 'ops' / op / 'writer-stopped.json')
            require(stopped['native_reaped'] and stopped['native_publish_completed'], 'real writer completion')
            previous = op
            lifecycle.tick()
        if args.case == 'selected':
            require(len(list((window / 'ops').iterdir())) == 32, 'genuine32 inventory')
            rc, _, _ = cli(stage, 'start', window, previous)
            require(rc != 0 and len(list((window / 'ops').iterdir())) == 33, 'native33 RED')
            refused = [p for p in (window / 'ops').iterdir()
                       if h.read_json(p / 'result.json')['outcome'] == 'refused']
            require(len(refused) == 1 and 'operation budget exhausted' in
                    h.read_json(refused[0] / 'result.json')['error'], 'exact budget causation')
            require(cli(stage, 'reconcile', window, meta['id'])[0] != 0, 'legacy reconcile33 RED')
        legacy = [stage, window, '/var/lib/acx-gpu'] + [Path('/run/acx-write', e) for e in NEW_ENVS[:-1]]
        legacy_before = snapshot(legacy)
        provision_fifth(h, d, run, overlay_fd)
        require(snapshot(legacy) == legacy_before, 'fifth fixture setup changed legacy custody/state/fences')
        # Keep the pinned old helper untouched; only the new stage uses five.
        new_custody = module('checkpoint_new_topology', inputs['new-procedure/owner-custody.py'])
        require(new_custody.ENVS == NEW_ENVS, 'new stage requires exact fixed five-environment order')
        lifecycle.load = reaper.AggregateJobLoadSource(Path('/run/acx-write'), stale_seconds=120,
                                                     expected_environments=NEW_ENVS)
        new = Path('/tmp/checkpoint-qualified-stage')
        h.mkdir(new)
        for name in scripts:
            h.put(new / name, inputs['new-procedure/' + name])
        pins = json.loads(inputs['new-procedure/approved-scripts.json'])
        require(set(pins) == set(scripts) - {'approved-scripts.json'} and
                all(digest(inputs['new-procedure/' + n]) == sha for n, sha in pins.items()), 'complete new-stage pins')
        proof = dict(schema='acx-owner-procedure-predecessor/v1', window_id=meta['id'],
                     window_path=str(window), procedure=str(stage),
                     manifest_sha256=digest(scripts['approved-scripts.json']),
                     owner_window_sha256=digest(scripts['owner-window.py']),
                     owner_custody_sha256=digest(scripts['owner-custody.py']))
        stable = [window, stage, '/run/acx-write', '/var/lib/acx-gpu']
        if args.case != 'selected':
            h.put(new / 'procedure-predecessor.json', proof)
            c = module('checkpoint_legacy_custody', scripts['owner-custody.py'])
            writer = c.load_writer(raw['apps/prototype-description-service/scene/application/gpu_intent.py'],
                                   raw['apps/prototype-description-service/scene/application/describe_load.py'])
            native = None
            lock = None
            if args.case == 'pending':
                op = str(uuid.uuid4())
                h.mkdir(window / 'ops' / op)
                h.put(window / 'ops' / op / 'intent.json',
                      dict(id=op, window=meta['id'], action='start', previous=previous))
            elif args.case == 'foreign-current':
                native = h.Native(lambda: writer.write_gpu_intent('/run/acx-write/prod/gpu-intent.json',
                                  action='auto', requested_by='private-foreign-owner', ttl_seconds=600).to_payload(), 10001)
                result = native.finish(seconds=remaining(deadline, 6))
                h.put(run / 'foreign-native-writer.json', result)
                require(result['native_reaped'] and result['result']['ok'], 'real foreign writer')
                native = None
            else:
                # A genuine UID10001 public writer is stopped only after it has
                # entered the real persistent intent-fence wait. No fake PID,
                # writer receipt or ACK. This is isolated private scheduling.
                lock = os.open('/run/acx-write/prod/gpu-intent.json.lock', os.O_RDONLY)
                h.HELD.append(lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                native = h.Native(lambda: writer.write_gpu_intent('/run/acx-write/prod/gpu-intent.json',
                                  action='auto', requested_by='private-live-writer', ttl_seconds=600).to_payload(), 10001)
                end = time.monotonic() + remaining(deadline, 2)
                while True:
                    status = Path('/proc', str(native.pid), 'status').read_text()
                    fds = h.fd_inventory(native.pid)
                    if ('Uid:\t10001\t10001\t10001\t10001' in status and
                            any(v['target'] == '/run/acx-write/prod/gpu-intent.json.lock' for v in fds.values())):
                        break
                    require(time.monotonic() < end, 'real writer fence entry missing')
                    time.sleep(.01)
                signal.pidfd_send_signal(native.fd, signal.SIGSTOP)
                end = time.monotonic() + remaining(deadline, 1)
                while '\nState:\tT' not in '\n' + Path('/proc', str(native.pid), 'status').read_text():
                    require(time.monotonic() < end, 'native writer not stopped')
                    time.sleep(.01)
                h.put(run / 'live-writer-held.json', dict(identity=native.ident,
                      uid=10001, fds=fds, signal='SIGSTOP', fence_held=True))
            before = snapshot(stable)
            rc, _, stderr = cli(new, 'checkpoint', window, meta['id'], reap_children=native is None)
            require(rc != 0 and snapshot(stable) == before, 'negative checkpoint mutated state')
            if native is not None:
                require(h.identity(native.pid) == native.ident, 'native writer identity changed')
                fcntl.flock(lock, fcntl.LOCK_UN)
                h.HELD.remove(lock)
                os.close(lock)
                signal.pidfd_send_signal(native.fd, signal.SIGCONT)
                result = native.finish(seconds=remaining(deadline, 6))
                require(result['native_reaped'] and result['result']['ok'], 'native writer closure')
                h.put(run / 'live-writer-reaped.json', result)
            require(not h.children(), 'negative native child closure')
            h.archive_owned(run)
            h.put(run / 'selected-result.json', dict(status='ROOT_SELECTED_CHECKPOINT_PASS',
                  case=args.case, full_qualification=False, refusal=stderr, window_id=meta['id']))
            h.close_held()
            return 0
        before = snapshot(stable)
        # Deliberately invalid, still protected proof. Replace only this private negative-control receipt.
        h.put(new / 'procedure-predecessor.json', dict(proof, window_id='invalid'))
        require(cli(new, 'checkpoint', window, meta['id'])[0] != 0 and snapshot(stable) == before,
                'invalid protected proof must refuse without mutation')
        os.unlink(new / 'procedure-predecessor.json')
        h.put(new / 'procedure-predecessor.json', proof)
        immutable = snapshot([stage, window / 'window.json', window / 'writer-source.py',
                              window / 'load-source.py', '/run/acx-write', '/var/lib/acx-gpu'])
        oldfiles = {str(p.relative_to(window)): p.read_bytes() for p in window.rglob('*') if p.is_file()}
        oldcurrent = h.read_json(window / 'ops' / previous / 'candidate.json')
        current_proof = snapshot([window / 'ops' / previous])
        rc, receipt, _ = cli(new, 'checkpoint', window, meta['id'])
        require(rc == 0 and isinstance(json.loads(receipt), dict), 'structured checkpoint receipt')
        require(snapshot([window / 'ops' / previous]) == current_proof, 'current predecessor proof moved or changed')
        require(snapshot([stage, window / 'window.json', window / 'writer-source.py',
                          window / 'load-source.py', '/run/acx-write', '/var/lib/acx-gpu']) == immutable,
                'checkpoint mutated authority/publications/immutable source')
        # Every original byte must remain represented; relocation is permitted only inside this window.
        from collections import Counter
        afterbytes = Counter(p.read_bytes() for p in window.rglob('*') if p.is_file())
        require(not (Counter(oldfiles.values()) - afterbytes), 'archived original bytes missing')
        require(cli(new, 'reconcile', window, meta['id'])[:2] == (0, previous), 'checkpoint predecessor preserved')
        demand = fifth_load(h, 1, 2)
        before = snapshot(stable + [new])
        oldops = {p.name for p in (window / 'ops').iterdir()}
        rc, _, _ = cli(new, 'start', window, previous)
        added = {p.name for p in (window / 'ops').iterdir()} - oldops
        require(rc != 0 and len(added) == 1, 'fifth demand must refuse exactly one native START')
        refused = window / 'ops' / added.pop()
        result = h.read_json(refused / 'result.json')
        require(result['outcome'] == 'refused' and 'work/demand' in result['error'],
                'fifth demand must be the actual refusal cause')
        preflight = h.read_json(refused / 'preflight.json')
        require(len(preflight['loads']) == 5 and preflight['loads'][-1] == demand,
                'actual START must consume fifth load')
        require(not any((refused / n).exists() for n in
                        ('candidate.json', 'writer-started.json', 'writer-stopped.json', 'publication.json'))
                and not h.children(), 'refused START must never start a publication writer')
        after = snapshot(stable + [new])
        require({p: v for p, v in after.items() if not Path(p).is_relative_to(refused)} == before,
                'fifth demand refusal changed state outside its diagnostic operation')
        require(cli(new, 'reconcile', window, meta['id'])[:2] == (0, previous),
                'demand refusal advanced the predecessor')
        h.put(run / 'fifth-demand-refused.json', dict(load=demand, operation=refused.name,
              result=result, same_predecessor=previous, no_writer=True, unchanged_custody=True))
        zero_load = fifth_load(h, 0, 3)
        for action in ('start', 'auto'):
            rc, op, _ = cli(new, action, window, previous)
            require(rc == 0 and cli(new, 'reconcile', window, meta['id'])[:2] == (0, op), 'resumed native publication')
            candidate = h.read_json(window / 'ops' / op / 'candidate.json')
            stopped = h.read_json(window / 'ops' / op / 'writer-stopped.json')
            require(stopped['native_reaped'] and stopped['native_publish_completed'], 'resumed native writer proof')
            if action == 'start':
                loads = h.read_json(window / 'ops' / op / 'preflight.json')['loads']
                require(len(loads) == 5 and loads[-1] == zero_load, 'resumed START consumes fresh fifth zero load')
            require(candidate['requested_by'] == oldcurrent['requested_by'] and
                    candidate['sequence'] == oldcurrent['sequence'] + 1, 'same actor and next sequence')
            oldcurrent = candidate
            previous = op
            lifecycle.tick()
        require(not h.children(), 'all native children reaped')
        h.archive_owned(run)
        h.put(run / 'selected-result.json', dict(status='ROOT_SELECTED_CHECKPOINT_PASS',
              full_qualification=False, case=args.case, remaining_controls=['crash-injection'],
              environments=NEW_ENVS, fifth_demand_refusal=refused.name,
              window_id=meta['id'], predecessor_proof=proof, checkpoint=json.loads(receipt)))
        h.close_held()
        return 0
    except BaseException as exc:
        h.put(run / 'UNKNOWN.json', dict(status='UNKNOWN', detail=repr(exc), pid1=h.identity(1),
              children=h.children(), held_descriptors=list(h.HELD), policy='retain; no retry/adoption/teardown'))
        # An ancestor namespace must deliver SIGSTOP: namespace PID1 cannot
        # rely on receiving its own default-action signal. The launcher polls
        # this sealed evidence and stops the exact host PID1 through a pidfd.
        # This bounded rendezvous is within the original deadline.
        while time.monotonic() < deadline:
            time.sleep(.02)
        # Launcher normally stopped us already. Never silently return/teardown
        # on a missed rendezvous: retain in a stopped native child initiated by
        # the ancestor. Reaching this assertion is itself unresolved evidence.
        raise RuntimeError('ancestor retention rendezvous missed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--input-root')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--case', choices=('selected', 'pending', 'foreign-current', 'writer-live'), help=argparse.SUPPRESS)
    parser.add_argument('--namespace', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--parent-namespaces', help=argparse.SUPPRESS)
    parser.add_argument('--output', help=argparse.SUPPRESS)
    parser.add_argument('--deadline', type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.plan:
        # Read-only; no candidate imports or subprocesses.
        p = Path(__file__).with_name('checkpoint_fixture_plan.py')
        print(json.dumps(module('checkpoint_plan', p.read_bytes()).PLAN, sort_keys=True, indent=2))
        return 0
    if os.getuid() != 0 or os.geteuid() != 0:
        return 77
    if not args.run or not args.input_root or not args.manifest_sha256:
        return 65
    deadline = args.deadline if args.namespace else time.monotonic() + 180
    base = Path(args.input_root)
    require(base.is_absolute() and str(base).startswith('/root/') and '..' not in base.parts, 'sealed /root input required')
    raw = protected(base / 'input-manifest.json')
    require(digest(raw) == args.manifest_sha256, 'protected manifest digest')
    manifest = json.loads(raw)
    require(set(manifest) == {'schema', 'files'} and manifest['schema'] == 'acx-checkpoint-fixture-input/v1', 'input schema')
    require(len(manifest['files']) <= 64, 'input count bound')
    inputs = {}
    for name, sha in manifest['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'relative input')
        inputs[name] = protected(base / name)
        require(digest(inputs[name]) == sha, 'input hash')
    require(digest(inputs['OWNER-FLOW-CONTROLS-R2.py']) == FLOW_SHA, 'fixed original fixture pin')
    require(inputs['checkpoint_fixture_coordinator.py'] == protected(Path(__file__).absolute()), 'self pin')
    required = {'checkpoint_fixture_coordinator.py', 'checkpoint_fixture_plan.py',
                'root_fixture_plan.py', 'OWNER-FLOW-CONTROLS-R2.py'}
    require(required <= set(inputs), 'complete coordinator inputs')
    for stage in ('old-procedure', 'new-procedure'):
        pins = json.loads(inputs[stage + '/approved-scripts.json'])
        require(len(pins) == 7 and all('/' not in n and n not in ('.', '..') for n in pins), 'seven-script manifest')
        require(all(digest(inputs[stage + '/' + n]) == sha for n, sha in pins.items()), 'stage input hashes')
    require(digest(inputs['old-procedure/approved-scripts.json']) ==
            '991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406', 'qualified legacy stage')
    h = module('checkpoint_original_fixture', inputs['OWNER-FLOW-CONTROLS-R2.py'])
    d = module('checkpoint_mount_proofs', inputs['root_fixture_plan.py'])
    h.capabilities()
    original_command = h.command
    def command(argv, seconds=4, data=None):
        return original_command(argv, remaining(deadline, seconds), data)
    h.command = command
    # Verify all fixed source pins before any mount or namespace launch.
    h.bundle_read(base / 'source-bundle')
    if args.namespace:
        return namespace(args, base, inputs, h, d, deadline)
    output = base / 'checkpoint-output'
    h.mkdir(output)
    parent = output / 'parent-namespaces.json'
    h.put(parent, h.ns())
    results = {}
    for case in ('selected', 'pending', 'foreign-current', 'writer-live'):
        run = output / case
        h.mkdir(run)
        argv = ['/usr/bin/unshare', '--propagation', 'unchanged', '--mount', '--pid', '--net', '--fork',
                '/usr/bin/python3', '-I', '-B', str(base / 'checkpoint_fixture_coordinator.py'), '--run',
                '--input-root', str(base), '--manifest-sha256', args.manifest_sha256, '--namespace',
                '--case', case, '--parent-namespaces', str(parent), '--output', str(run), '--deadline', str(deadline)]
        with (run / 'launcher.stdout').open('xb') as out, (run / 'launcher.stderr').open('xb') as err:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=ENV)
            h.put(run / 'launcher.json', h.identity(child.pid))
            init_pidfd = None
            init_identity = None
            # Reserve custody rendezvous inside, never beyond, the 180s budget.
            end = deadline - .25
            while child.poll() is None:
                if init_pidfd is None:
                    pids = Path('/proc', str(child.pid), 'task', str(child.pid), 'children').read_text().split()
                    require(len(pids) <= 1, 'one namespace init required')
                    if pids:
                        init_identity = h.identity(int(pids[0]))
                        init_pidfd = os.pidfd_open(int(pids[0]))
                if (run / 'UNKNOWN.json').exists() or time.monotonic() >= end:
                    if init_pidfd is not None:
                        signal.pidfd_send_signal(init_pidfd, signal.SIGSTOP)
                    h.put(run / 'launcher-UNKNOWN.json', dict(status='UNKNOWN', launcher_pid=child.pid,
                          namespace_init=init_identity, retention_signal='SIGSTOP via ancestor pidfd',
                          policy='retain PID1/children/fences; no terminating signal, retry, adoption or teardown'))
                    if init_pidfd is not None:
                        os.close(init_pidfd)
                    return 124
                time.sleep(.02)
            rc = child.returncode  # poll() already performed the native reap
            if init_pidfd is not None:
                os.close(init_pidfd)
        h.put(run / 'launcher-wait.json', dict(exit_code=rc, native_reaped=True))
        if rc != 0:
            return 65 if rc == 65 else 124
        result = json.loads((run / 'selected-result.json').read_bytes())
        require(result['case'] == case and result['status'] == 'ROOT_SELECTED_CHECKPOINT_PASS', 'case evidence')
        results[case] = digest((run / 'selected-result.json').read_bytes())
    h.put(output / 'aggregate.json', dict(status='ROOT_SELECTED_CHECKPOINT_PASS',
          full_qualification=False, remaining_controls=['crash-injection'], cases=results,
          input_manifest_sha256=args.manifest_sha256))
    return 0



if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('SETUP_REFUSED: ' + repr(exc), file=sys.stderr)
        raise SystemExit(65)
