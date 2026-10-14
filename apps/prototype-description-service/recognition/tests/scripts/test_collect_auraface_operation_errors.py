"""Offline real-reader lifecycle controls; no captured runtime evidence."""

import importlib.util
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


def load(name):
    scripts = Path(__file__).resolve().parents[3] / 'scripts'
    spec = importlib.util.spec_from_file_location(name, scripts / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(module, path):
    return module.collect_auraface_acceptance(
        [path],
        # No record can be acquired; these inputs are intentionally incomplete.
        captured_inputs={},
        expected_contract='candidate512',
        freshness_policy=dict(max_age_seconds=60, future_skew_seconds=2),
        isolation_policy=dict(
            resource_policy_id='candidate-target', database_instance_id='instance-opaque',
            database_name='candidate_store', database_role='serving_role',
            storage_identity='store-opaque', tenant_context_id='tenant-opaque'),
        now=datetime(2026, 10, 13, tzinfo=timezone.utc),
        max_record_bytes=1024, max_record_count=4,
        deadline_monotonic=time.monotonic() + 5)


@pytest.mark.parametrize('error_type', [OSError, ValueError], ids=['oserror', 'valueerror'])
def test_non_timeout_operation_error_kills_and_reaps_reader(tmp_path, monkeypatch, error_type):
    """Both types share the collector's cleanup and malformed classification."""
    module = load('collect_auraface_acceptance')
    reader = module.subprocess.Popen(
        [module.sys.executable, '-I', '-c',
         "import sys, time; print('ready', flush=True); time.sleep(60)"],
        stdin=module.subprocess.PIPE, stdout=module.subprocess.PIPE,
        stderr=module.subprocess.DEVNULL, text=True)
    launches = []
    operations = []

    def popen(*args, **kwargs):
        launches.append(reader)
        return reader

    def communicate(*args, **kwargs):
        operations.append(reader)
        assert reader.poll() is None
        raise error_type('synthetic reader operation failure')

    try:
        # Readiness proves the real child is running before operation injection.
        assert reader.stdout.readline() == 'ready\n'
        monkeypatch.setattr(module.subprocess, 'Popen', popen)
        monkeypatch.setattr(reader, 'communicate', communicate)
        result = collect(module, tmp_path / 'captured')
        assert launches == [reader] and operations == [reader]
        # Inspect before finally cleanup: poll() here would hide a missing reap.
        assert reader.returncode == -9
        assert reader.stdin.closed and reader.stdout.closed
        assert len(result['acquisition_ledger']) == 1
        row = result['acquisition_ledger'][0]
        assert row['status'] == row['reason_code'] == 'malformed'
        assert row['bytes_read'] == 0 and row['record_sha256'] is None
        assert 'malformed' in result['gaps']
        assert result['snapshot'] is None and result['sidecar'] is None
        assert result['status'] == 'incomplete'
    finally:
        if reader.returncode is None:
            reader.kill()
            reader.wait(timeout=1)
        for pipe in (reader.stdin, reader.stdout):
            if pipe is not None:
                pipe.close()
