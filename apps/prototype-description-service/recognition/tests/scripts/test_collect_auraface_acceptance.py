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


def test_actual_reader_timeout_is_bounded(tmp_path,monkeypatch):
    module=load('collect_auraface_acceptance')
    _,inputs=pair()
    monkeypatch.setattr(module,'_READ_SCRIPT','import time; time.sleep(1)')
    started=time.monotonic()
    result=module.collect_auraface_acceptance([tmp_path/'captured'],captured_inputs=inputs,expected_contract='candidate512',freshness_policy=dict(max_age_seconds=60,future_skew_seconds=2),isolation_policy=dict(resource_policy_id='candidate-target',database_instance_id='instance-opaque',database_name='candidate_store',database_role='serving_role',storage_identity='store-opaque',tenant_context_id='tenant-opaque'),now=NOW,max_record_bytes=1024,deadline_monotonic=started+0.05)
    assert time.monotonic()-started < 0.5
    assert result['acquisition_ledger'][0]['status']=='deadline_exceeded'


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
    calls = []
    clock = [10.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])

    class Reader:
        def __init__(self, *args, **kwargs):
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
            self.killed = False
            clock[0] = 10.2  # launch consumes budget

        def communicate(self, *, input, timeout=None):
            assert timeout is not None and 0 < timeout <= 0.8
            calls.append('communicate')
            clock[0] = 10.95
            raise module.subprocess.TimeoutExpired('fixture-only-canary', timeout)

        def kill(self):
            self.killed = True
            calls.append('kill')

        def wait(self, timeout=None):
            assert self.killed
            assert timeout is not None and 0 <= timeout <= 0.051
            calls.append('wait')
            if unkillable:
                raise module.subprocess.TimeoutExpired('fixture-only-canary', timeout)
            return -9

    monkeypatch.setattr(module.subprocess, 'Popen', Reader)
    _, inputs = pair()
    result = collect([tmp_path / 'unused'], inputs, deadline_monotonic=11.0)
    code = 'reader_unkillable' if unkillable else 'deadline_exceeded'
    assert calls == ['communicate', 'kill', 'wait']
    assert result['acquisition_ledger'][0]['status'] == code
    assert result['acquisition_ledger'][0]['reason_code'] == code
    assert code in result['gaps']
    assert 'fixture-only-canary' not in str(result)
    assert str(tmp_path) not in str(result)


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
