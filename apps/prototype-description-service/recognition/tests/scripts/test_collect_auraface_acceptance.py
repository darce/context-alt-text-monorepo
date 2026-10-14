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
