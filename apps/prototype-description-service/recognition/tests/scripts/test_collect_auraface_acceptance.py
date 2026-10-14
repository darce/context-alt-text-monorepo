"""Captured-file acquisition controls; no producer or live resources."""
import json
import time
from pathlib import Path

import pytest
import importlib.util
_fixture_spec = importlib.util.spec_from_file_location('offline_fixture', Path(__file__).with_name('test_auraface_acceptance_join.py'))
_fixture = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)
load, pair, NOW = _fixture.load, _fixture.pair, _fixture.NOW


def collect(paths, inputs, **overrides):
    options = dict(captured_inputs=inputs,expected_contract='candidate512',freshness_policy=dict(max_age_seconds=60,future_skew_seconds=2),isolation_policy=dict(resource_policy_id='candidate-target',database_instance_id='instance-opaque',database_name='candidate_store',database_role='serving_role',storage_identity='store-opaque',tenant_context_id='tenant-opaque'),now=NOW,max_record_bytes=65536,max_record_count=4,deadline_monotonic=time.monotonic()+5)
    options.update(overrides)
    return load('collect_auraface_acceptance').collect_auraface_acceptance(paths,**options)


def test_captured_pair_has_bounded_acquisition_ledger(tmp_path):
    records, inputs = pair(); paths=[]
    for i, record in enumerate(records):
        path=tmp_path / str(i); path.write_text(json.dumps(record)); paths.append(path)
    result=collect(paths,inputs)
    assert set(result['gaps']) == {'GAP-V1-REPAIR','GAP-BRANCH-ARTIFACTS'}
    assert len(result['acquisition_ledger']) == 2
    assert all(row['status']=='acquired' and row['bytes_read'] > 0 and len(row['record_sha256'])==64 for row in result['acquisition_ledger'])


@pytest.mark.parametrize('kind',['missing','directory','oversized','malformed','duplicate_key','nonfinite','symlink','fifo','deadline','count'])
def test_acquisition_failures_are_bounded_and_sanitized(tmp_path,kind):
    records,inputs=pair(); path=tmp_path/'captured'; options={}
    if kind=='directory': path.mkdir()
    elif kind=='oversized': path.write_bytes(b' ' * 65537)
    elif kind=='malformed': path.write_text('rejected-sentinel')
    elif kind=='duplicate_key': path.write_text('{"role":"api","role":"worker"}')
    elif kind=='nonfinite': path.write_text('{"value":NaN}')
    elif kind=='symlink': path.symlink_to(tmp_path/'missing')
    elif kind=='fifo':
        import os
        os.mkfifo(path)
    elif kind not in ('missing',): path.write_text(json.dumps(records[0]))
    if kind=='deadline': options['deadline_monotonic']=time.monotonic()-1
    if kind=='count': options['max_record_count']=0
    result=collect([path],inputs,**options)
    assert result['snapshot'] is None
    expected = {'missing':'missing','directory':'unreadable','oversized':'oversized',
                'malformed':'malformed','duplicate_key':'malformed','nonfinite':'malformed',
                'symlink':'unreadable','fifo':'unreadable','deadline':'deadline_exceeded','count':'oversized'}[kind]
    assert result['acquisition_ledger'][0]['status'] == expected
    assert 'rejected-sentinel' not in str(result)
    assert str(path) not in str(result)


def test_sources_are_stdlib_only():
    import ast
    SCRIPTS = _fixture.SCRIPTS
    for name in ('collect_auraface_acceptance','auraface_acceptance_join'):
        load(name)
        tree=ast.parse((SCRIPTS/(name+'.py')).read_text())
        allowed={'__future__','collections','datetime','hashlib','json','math','os','pathlib','stat','time','typing','auraface_acceptance_join','importlib','subprocess','sys'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                assert all(alias.name.split('.')[0] in allowed for alias in node.names)
            elif isinstance(node,ast.ImportFrom): assert node.module.split('.')[0] in allowed


@pytest.mark.timing
def test_actual_reader_timeout_is_bounded(tmp_path,monkeypatch,request):
    module=load('collect_auraface_acceptance')
    _,inputs=pair()
    monkeypatch.setattr(module,'_READ_SCRIPT','import time; time.sleep(60)')
    real_popen = module.subprocess.Popen
    # Start the actual stalled reader before measuring its timeout/reap budget.
    reader = real_popen([module.sys.executable, '-I', '-c', module._READ_SCRIPT],
                        stdin=module.subprocess.PIPE, text=True,
                        stdout=module.subprocess.PIPE, stderr=module.subprocess.DEVNULL)
    readers = []

    def popen(*args, **kwargs):
        readers.append(reader)
        return reader

    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    try:
        started=time.monotonic()
        result=module.collect_auraface_acceptance([tmp_path/'captured'],captured_inputs=inputs,expected_contract='candidate512',freshness_policy=dict(max_age_seconds=60,future_skew_seconds=2),isolation_policy=dict(resource_policy_id='candidate-target',database_instance_id='instance-opaque',database_name='candidate_store',database_role='serving_role',storage_identity='store-opaque',tenant_context_id='tenant-opaque'),now=NOW,max_record_bytes=1024,deadline_monotonic=started+0.2)
        elapsed = time.monotonic() - started
        request.node.user_properties.append(('collector_elapsed_seconds', elapsed))
        request.node.user_properties.append(('deadline_overshoot_seconds', max(0, elapsed - 0.2)))
        assert elapsed < 0.5
        assert result['acquisition_ledger'][0]['status']=='deadline_exceeded'
        assert len(readers) == 1 and reader.returncode == -9
    finally:
        if reader.returncode is None:
            reader.kill()
            reader.wait(timeout=1)
        for pipe in (reader.stdin, reader.stdout):
            if pipe is not None:
                pipe.close()


def test_oversized_file_reports_actual_bounded_reads(tmp_path):
    _, inputs = pair()
    path = tmp_path / 'large'
    path.write_bytes(b' ' * (4 * 65536))
    row = collect([path], inputs)['acquisition_ledger'][0]
    assert row['status'] == 'oversized'
    assert row['bytes_read'] == 0  # size precheck avoids even one read


def run_reader(path, cap, monkeypatch, *, before_change=None, after_change=None):
    """Run the exact child program with fixture-only fstat race injection."""
    import io
    import os
    import sys
    from types import SimpleNamespace

    module = load('collect_auraface_acceptance')
    real_stat, real_read = os.fstat, os.read
    calls, observed = [], []
    output = io.StringIO()

    def fstat(fd):
        actual = real_stat(fd)
        values = {key: getattr(actual, key) for key in
                  ('st_mode', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        changes = before_change if not calls else after_change
        calls.append(fd)
        if changes:
            for key, value in changes.items():
                values[key] = value(values[key])
        return SimpleNamespace(**values)

    def read(fd, count):
        data = real_read(fd, count)
        observed.append(len(data))
        return data

    with monkeypatch.context() as patch:
        patch.setattr(os, 'fstat', fstat)
        patch.setattr(os, 'read', read)
        patch.setattr(sys, 'stdin', io.StringIO(json.dumps(dict(path=str(path), cap=cap))))
        patch.setattr(sys, 'stdout', output)
        exec(module._READ_SCRIPT, {})
    result = json.loads(output.getvalue())
    assert result['bytes_read'] == sum(observed)
    assert str(path) not in output.getvalue()
    return result, calls


def test_growing_file_read_is_capped_at_cap_plus_one(tmp_path, monkeypatch):
    path = tmp_path / 'growing'
    path.write_bytes(b' ' * 262144)
    cap = 1024
    # Simulate growth after the initial stat without defeating the read cap.
    result, _ = run_reader(path, cap, monkeypatch,
                           before_change={'st_size': lambda _: cap})
    assert result['status'] == 'oversized'
    assert result['bytes_read'] == cap + 1


@pytest.mark.parametrize('field', ['st_size', 'st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns'])
def test_fstat_change_is_refused(tmp_path, monkeypatch, field):
    path = tmp_path / 'changing'
    path.write_bytes(b'{}')
    result, calls = run_reader(path, 1024, monkeypatch,
                               after_change={field: lambda value: value + 1})
    assert len(calls) == 2
    assert result['status'] == 'contradictory_binding'
    assert result['bytes_read'] == 2
    assert 'data_hex' not in result


def test_read_size_must_agree_with_stable_fstat(tmp_path, monkeypatch):
    path = tmp_path / 'short'
    path.write_bytes(b'{}')
    change = {'st_size': lambda value: value + 1}
    result, _ = run_reader(path, 1024, monkeypatch,
                           before_change=change, after_change=change)
    assert result['status'] == 'contradictory_binding'


@pytest.mark.parametrize('option,value', [
    ('max_record_bytes', 1024 * 1024 + 1),
    ('max_record_count', 129),
])
def test_hard_acquisition_ceilings(option, value):
    _, inputs = pair()
    with pytest.raises(ValueError, match='bounded range'):
        collect([], inputs, **{option: value})


def test_hard_acquisition_ceiling_boundaries_are_allowed():
    _, inputs = pair()
    result = collect([], inputs, max_record_bytes=1024 * 1024, max_record_count=128)
    assert 'oversized' not in result['gaps']
    assert result['snapshot'] is None and result['sidecar'] is None


def test_129_paths_are_refused_before_launch(tmp_path, monkeypatch):
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: pytest.fail('reader launched'))
    _, inputs = pair()
    result = collect([tmp_path / 'unused'] * 129, inputs, max_record_count=128)
    assert result['acquisition_ledger'][0]['reason_code'] == 'record_count_limit'
    assert 'oversized' in result['gaps']


@pytest.mark.parametrize('unkillable', [False, True])
def test_post_kill_wait_is_bounded_and_sanitized(tmp_path, monkeypatch, unkillable):
    import io
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    calls, readers = [], []
    clock = [10.0]
    deadline, reap_reserve, reap_grace = 11.0, 0.15, 0.1
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])

    class Reader:
        def __init__(self, *args, **kwargs):
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
            self.killed = False
            readers.append(self)
            clock[0] = 10.2  # launch consumes budget

        def communicate(self, *, input, timeout=None):
            budget = deadline - clock[0]
            assert timeout is not None and 0 < timeout <= budget - reap_reserve
            calls.append('communicate')
            clock[0] += timeout
            raise module.subprocess.TimeoutExpired('fixture-only-canary', timeout)

        def kill(self):
            self.killed = True
            calls.append('kill')

        def wait(self, timeout=None):
            assert self.killed
            assert timeout == pytest.approx(reap_grace)
            assert timeout <= deadline - clock[0]
            calls.append('wait')
            if unkillable:
                clock[0] += timeout
                raise module.subprocess.TimeoutExpired('fixture-only-canary', timeout)
            return -9

    monkeypatch.setattr(module.subprocess, 'Popen', Reader)
    _, inputs = pair()
    result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=deadline)
    code = 'reader_unkillable' if unkillable else 'deadline_exceeded'
    assert calls == ['communicate', 'kill', 'wait']
    assert readers[0].stdin.closed and readers[0].stdout.closed
    assert result['acquisition_ledger'][0]['status'] == code
    assert result['acquisition_ledger'][0]['reason_code'] == code
    assert code in result['gaps']
    assert 'fixture-only-canary' not in str(result)
    assert str(tmp_path) not in str(result)


@pytest.mark.parametrize('remaining', [0.05, 0.15, 0.155])
def test_short_budget_refuses_reader_launch(tmp_path, monkeypatch, remaining):
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 0.0)
    monkeypatch.setattr(module.subprocess, 'Popen',
                        lambda *a, **k: pytest.fail('reader launched without reap reserve plus margin'))
    _, inputs = pair()
    result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=remaining)
    row = result['acquisition_ledger'][0]
    assert row['status'] == row['reason_code'] == 'deadline_exceeded'
    assert row['bytes_read'] == 0 and 'deadline_exceeded' in result['gaps']


@pytest.mark.parametrize('launch_time', [0.97, 1.0, 1.02])
def test_launch_overrun_cannot_establish_reader_unkillable(tmp_path, monkeypatch, launch_time):
    import io
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    clock, calls = [0.0], []
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])

    class Reader:
        def __init__(self, *args, **kwargs):
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
            clock[0] = launch_time

        def communicate(self, *, input, timeout=None):
            assert timeout == 0
            calls.append('communicate')
            raise module.subprocess.TimeoutExpired('fixture-only-canary', timeout)

        def kill(self):
            calls.append('kill')

        def wait(self, timeout=None):
            assert timeout == max(0, 1.0 - launch_time)
            calls.append('wait')
            clock[0] += timeout
            raise module.subprocess.TimeoutExpired('fixture-only-canary', timeout)

    monkeypatch.setattr(module.subprocess, 'Popen', Reader)
    _, inputs = pair()
    result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=1.0)
    assert calls == ['communicate', 'kill', 'wait']
    row = result['acquisition_ledger'][0]
    assert row['status'] == row['reason_code'] == 'deadline_exceeded'
    assert 'reader_unkillable' not in result['gaps']
    assert 'fixture-only-canary' not in str(result) and str(tmp_path) not in str(result)


def test_expired_deadline_prevents_join(monkeypatch):
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 11.0)
    monkeypatch.setattr(module._join, 'join_auraface_acceptance',
                        lambda *a, **k: pytest.fail('join started after deadline'))
    _, inputs = pair()
    assert 'deadline_exceeded' in collect([], inputs, deadline_monotonic=10.0)['gaps']


def test_deadline_crossed_during_join_is_reported(monkeypatch):
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    clock = [9.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])

    def join(*args, **kwargs):
        clock[0] = 11.0
        return module._join.empty_result()

    monkeypatch.setattr(module._join, 'join_auraface_acceptance', join)
    _, inputs = pair()
    assert 'deadline_exceeded' in collect([], inputs, deadline_monotonic=10.0)['gaps']


def test_symlinked_parent_directory_is_refused(tmp_path):
    _, inputs = pair()
    directory = tmp_path / 'real'
    directory.mkdir()
    (directory / 'record').write_text('{}')
    link = tmp_path / 'link'
    link.symlink_to(directory, target_is_directory=True)
    result = collect([link / 'record'], inputs)
    assert result['acquisition_ledger'][0]['status'] == 'unreadable'
    assert result['acquisition_ledger'][0]['bytes_read'] == 0


@pytest.mark.parametrize('wait_expires', [False, True])
def test_kill_error_still_attempts_bounded_reap(tmp_path, monkeypatch, wait_expires):
    # GTMC-FG3C80-F3 / C82R-G3C2-01: cleanup errors are typed and sanitized.
    import io
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 0.0)
    calls, readers = [], []

    class Reader:
        def __init__(self, *args, **kwargs):
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
            readers.append(self)

        def communicate(self, **kwargs):
            raise module.subprocess.TimeoutExpired('private-canary', 0)

        def kill(self):
            calls.append('kill')
            raise PermissionError('private-canary')

        def wait(self, timeout=None):
            calls.append('wait')
            assert timeout == 0.1
            if wait_expires:
                raise module.subprocess.TimeoutExpired('private-canary', timeout)
            return 0

    monkeypatch.setattr(module.subprocess, 'Popen', Reader)
    _, inputs = pair()
    result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=1.0)
    assert calls == ['kill', 'wait']
    code = 'reader_unkillable' if wait_expires else 'deadline_exceeded'
    assert result['acquisition_ledger'][0]['status'] == code
    assert result['acquisition_ledger'][0]['reason_code'] == code
    assert code in result['gaps']
    assert 'private-canary' not in str(result) and str(tmp_path) not in str(result)
    assert readers[0].stdin.closed and readers[0].stdout.closed


@pytest.mark.parametrize('receipt,status,expected,accounted', [
    (-7, 'missing', 'malformed', 0),
    (True, 'missing', 'malformed', 0),
    ('7', 'missing', 'malformed', 0),
    (7, 'oversized', 'oversized', 7),
])
def test_collector_receipt_validation_and_propagation(tmp_path, monkeypatch, receipt, status, expected, accounted):
    # GTMC-FG3C80-F5 / C82R-G3C2-02: child receipts must reach the collector.
    import io
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    readers = []

    class Reader:
        returncode = 0
        def __init__(self, *args, **kwargs):
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
            readers.append(self)
        def communicate(self, **kwargs):
            return json.dumps(dict(status=status, bytes_read=receipt)), None

    monkeypatch.setattr(module.subprocess, 'Popen', Reader)
    _, inputs = pair()
    result = collect([tmp_path / 'unused'], inputs)
    row = result['acquisition_ledger'][0]
    assert row['status'] == row['reason_code'] == expected
    assert row['bytes_read'] == accounted
    assert expected in result['gaps']
    assert readers[0].stdin.closed and readers[0].stdout.closed


def test_search_only_parent_is_acquired(tmp_path, monkeypatch):
    # GTMC-FG3C80-F8 / C82R-G3C2-04: search permission suffices for directory walk.
    import os
    directory = tmp_path / 'search-only'
    directory.mkdir()
    path = directory / 'record'
    path.write_bytes(b'{}')
    real_open = os.open
    directory_flags = []
    def checked_open(name, flags, *args, **kwargs):
        if flags & os.O_DIRECTORY:
            directory_flags.append(flags)
            assert flags & os.O_PATH, 'directory walk requires O_PATH'
        return real_open(name, flags, *args, **kwargs)
    directory.chmod(0o311)
    try:
        monkeypatch.setattr(os, 'open', checked_open)
        result, _ = run_reader(path, 1024, monkeypatch)
        assert directory_flags
        assert result['status'] == 'acquired' and result['bytes_read'] == 2
    finally:
        directory.chmod(0o700)


def test_exact_launch_reserve_boundary_is_allowed(tmp_path, monkeypatch):
    # C82R-G3C2-05: equality must launch, independent of float subtraction.
    import io
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 0.0)
    calls = []
    class Reader:
        returncode = 0
        def __init__(self, *args, **kwargs):
            calls.append('launch')
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
        def communicate(self, **kwargs):
            return '{"status":"missing","bytes_read":0}', None
    monkeypatch.setattr(module.subprocess, 'Popen', Reader)
    _, inputs = pair()
    boundary = module.READER_REAP_RESERVE_SECONDS + module.READER_LAUNCH_MARGIN_SECONDS
    result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=boundary)
    assert calls == ['launch']
    assert result['acquisition_ledger'][0]['status'] == 'missing'


@pytest.mark.timing
def test_actual_launch_is_in_total_caller_timing(tmp_path, monkeypatch):
    # C82R-G3C2-06: complementary launch-inclusive smoke, not a universal bound.
    module = load('collect_auraface_acceptance')
    monkeypatch.setitem(collect.__globals__, 'load', lambda _: module)
    monkeypatch.setattr(module, '_READ_SCRIPT', 'import time; time.sleep(60)')
    real_popen, readers = module.subprocess.Popen, []
    def popen(*args, **kwargs):
        reader = real_popen(*args, **kwargs)
        readers.append(reader)
        return reader
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    _, inputs = pair()
    started = time.monotonic()
    try:
        result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=started + 0.2)
        assert time.monotonic() - started < 0.5
        assert result['acquisition_ledger'][0]['status'] == 'deadline_exceeded'
        assert len(readers) == 1 and readers[0].returncode == -9
        assert readers[0].stdin.closed and readers[0].stdout.closed
    finally:
        for reader in readers:
            if reader.poll() is None:
                reader.kill()
                reader.wait(timeout=1)
            reader.stdin.close()
            reader.stdout.close()
