"""Real SQLite/file contract tests; no production source or blind labels."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'benchmarks/tools/evalops'))
import capture as c
import run as runner

# Native producer shape, including the mutable dedup fields and decision metadata.
DDL = '''
CREATE TABLE agent_errors (
 id INTEGER PRIMARY KEY AUTOINCREMENT, repo_instance_id TEXT NOT NULL,
 task_ref TEXT, harness TEXT NOT NULL, error_class TEXT NOT NULL,
 summary TEXT NOT NULL, detail TEXT, tool_name TEXT, command_preview TEXT,
 package_name TEXT, package_version TEXT, workstate_release TEXT,
 occurrence_count INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 last_seen_at TEXT NOT NULL DEFAULT (datetime('now')), workbay_release TEXT);
CREATE TABLE decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_ref TEXT NOT NULL, lane_id TEXT,
 session TEXT NOT NULL, decision TEXT NOT NULL, rationale TEXT, agent TEXT,
 model TEXT, model_label TEXT, reasoning_level TEXT, input_tokens INTEGER,
 output_tokens INTEGER, total_tokens INTEGER, changed_files_json TEXT NOT NULL DEFAULT '[]',
 branch TEXT, commit_sha TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 slice_number INTEGER, harness TEXT, decision_origin TEXT);
'''

class FakeClock:
    def __init__(self, action=None):
        self.wall = datetime(2026, 10, 29, 20, tzinfo=UTC)
        self.mono = 100.0
        self.action = action
        self.sleeps = 0
    def now(self):
        return self.wall
    def monotonic(self):
        return self.mono
    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds
    def sleep(self, seconds):
        self.advance(seconds)
        self.sleeps += 1
        if self.action:
            self.action(self)

@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'source.sqlite'
    with sqlite3.connect(path) as con:
        con.executescript(DDL)
        con.execute("INSERT INTO agent_errors (repo_instance_id,task_ref,harness,error_class,summary,created_at,last_seen_at) VALUES ('r','T','codex','pytest','failure','2026-10-20 10:00:00','2026-10-20 10:00:00')")
        con.execute("INSERT INTO decisions (task_ref,session,decision,rationale,created_at) VALUES ('T','s','recur:pytest','observed','2026-10-20 09:00:00')")
    return path

def execute(db, sql):
    with sqlite3.connect(db) as con:
        con.executescript(sql)

def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]

def ledger(out):
    return rows(out / 'ledger.jsonl')

def batches(out):
    return [json.loads((out / e['files']['batch']['name']).read_text()) for e in ledger(out) if e['kind'] == 'observation']

def observe(db, out, **kw):
    return c.run_capture(db, out, clock=kw.pop('clock', FakeClock()), **kw)

def exported(out, report, kind):
    return rows(out / report['exports'][kind]['name'])

def test_observed_updates_deletion_import_and_unchanged_diff(db, tmp_path):
    out = tmp_path / 'capture'
    def mutate(clock):
        if clock.sleeps == 1:
            execute(db, "UPDATE agent_errors SET occurrence_count=2,last_seen_at='2026-10-29 20:00:01' WHERE id=1; UPDATE decisions SET commit_sha='new',changed_files_json='[\"a\"]' WHERE id=1;")
        if clock.sleeps == 2:
            execute(db, "DELETE FROM agent_errors WHERE id=1; INSERT INTO decisions (id,task_ref,session,decision,created_at) VALUES (-2,'T','import','late import','2000-01-01 01:00:00');")
    report = observe(db, out, duration_seconds=4, poll_seconds=1, clock=FakeClock(mutate))
    assert report['observations'] == 4
    history = batches(out)
    assert [len(b['changes']) for b in history] == [2, 2, 2, 0]
    assert history[1]['changes'][0]['row']['occurrence_count'] == 2
    assert {x['kind'] for x in history[2]['changes']} == {'delete', 'insert'}
    assert exported(out, report, 'errors') == [{'id': 1, 'task_ref': 'T', 'error_class': 'pytest', 'created_at': '2026-10-20 10:00:00'}]
    assert len(exported(out, report, 'lessons')) == 2
    assert report['deleted_ids']['agent_errors'] == [1]
    assert report['status'] == 'duration_completed'
    assert report['seven_day_replay_ready'] is False
    assert report['quality_acceptance'] is False
    assert report['timestamp_support']['naive'] == 3
    assert not (out / 'coverage.json').exists()

def test_exports_are_strict_runner_inputs_and_private_immutable(db, tmp_path):
    out = tmp_path / 'capture'
    report = observe(db, out, once=True)
    assert out.stat().st_mode & 0o777 == 0o700
    before = {p.name: p.read_bytes() for p in out.iterdir() if p.name != '.lock'}
    for kind in ('errors', 'lessons'):
        data = exported(out, report, kind)
        runner.validate_recurrence(data, lessons=kind == 'lessons')
        assert set(data[0]) == ({'id','task_ref','error_class','created_at'} if kind == 'errors' else {'id','task_ref','decision','rationale','created_at'})
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in out.iterdir())
    result = runner.replay_report(None, exported(out, report, 'errors'), report['exports']['errors'], {'maturity': {'observed_post_span_seconds': 999999}}, datetime(2026,10,1,tzinfo=UTC), datetime(2026,11,1,tzinfo=UTC), datetime(2026,11,1,tzinfo=UTC), False)
    assert result['seven_day_replay_ready'] is False
    observe(db, out, resume=True, once=True)
    for name, content in before.items():
        if name != 'ledger.jsonl':
            assert (out / name).read_bytes() == content

@pytest.mark.parametrize('collision', ['db','sidecar','symlink','parent_symlink','hardlink','existing'])
def test_no_input_or_sidecar_collisions(db, tmp_path, collision):
    sidecar = Path(str(db) + '-wal')
    sidecar.write_bytes(b'original sidecar')
    target = tmp_path / 'out'
    if collision == 'db': target = db
    elif collision == 'sidecar': target = sidecar
    elif collision == 'symlink': target.symlink_to(db)
    elif collision == 'parent_symlink':
        link = tmp_path / 'link'; link.symlink_to(tmp_path, target_is_directory=True); target = link / 'out'
    elif collision == 'hardlink': os.link(db, target)
    else: target.mkdir(); (target / 'unknown').write_text('keep')
    before = (db.read_bytes(), sidecar.read_bytes())
    with pytest.raises((c.CaptureError, OSError)):
        observe(db, target, once=True)
    assert (db.read_bytes(), sidecar.read_bytes()) == before

def test_read_only_does_not_change_db_or_sidecars(db, tmp_path):
    # DELETE journal mode is representative; WAL is separately checked below.
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    observe(db, tmp_path / 'capture', once=True)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before

@pytest.mark.parametrize('fault', ['replacement','schema','read'])
def test_source_failure_records_gap_and_retains_prior_export(db, tmp_path, fault):
    out = tmp_path / 'capture'
    report = observe(db, out, once=True)
    before = (out / report['exports']['errors']['name']).read_bytes()
    if fault == 'replacement':
        other = tmp_path / 'replacement'; other.write_bytes(db.read_bytes()); os.replace(other, db)
    elif fault == 'schema': execute(db, 'ALTER TABLE decisions ADD COLUMN surprising TEXT;')
    else: db.write_bytes(b'not a database')
    with pytest.raises(c.CaptureError): observe(db, out, resume=True, once=True)
    assert any(e['kind'] == 'gap' for e in ledger(out))
    assert (out / report['exports']['errors']['name']).read_bytes() == before

@pytest.mark.parametrize('limits', [c.Limits(max_rows=1), c.Limits(max_bytes=50)])
def test_snapshot_limits_fail_loudly(db, tmp_path, limits):
    with pytest.raises(c.CaptureError, match='limit|bound|overflow'):
        observe(db, tmp_path / 'capture', once=True, limits=limits)

def test_sqlite_lock_failure_is_bounded(db, tmp_path):
    con = sqlite3.connect(db)
    try:
        con.execute('BEGIN EXCLUSIVE')
        with pytest.raises(c.CaptureError, match='locked|deadline|read'):
            observe(db, tmp_path / 'capture', once=True, limits=c.Limits(busy_seconds=.01, read_seconds=.1))
    finally: con.close()

def test_single_writer_lock(db, tmp_path):
    import fcntl
    out = tmp_path / 'capture'; observe(db, out, once=True)
    with (out / '.lock').open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(c.CaptureError, match='writer|lock'):
            observe(db, out, resume=True, once=True)

@pytest.mark.parametrize('fault', ['hash','duplicate','nonfinite','truncated','batch','unknown','hardlink'])
def test_resume_rejects_corrupt_or_unsafe_stored_evidence(db, tmp_path, fault):
    out = tmp_path / 'capture'; observe(db, out, once=True)
    path = out / 'ledger.jsonl'
    if fault == 'hash':
        events = rows(path); events[-1]['hash'] = '0' * 64
        path.write_bytes(b''.join(c.encoded(e) for e in events))
    elif fault == 'duplicate': path.write_bytes(b'{"a":1,"a":2}\n')
    elif fault == 'nonfinite': path.write_bytes(b'{"a":NaN}\n')
    elif fault == 'truncated': path.write_bytes(path.read_bytes()[:-3])
    elif fault == 'batch':
        b = next(out.glob('*.batch.json')); b.write_text('{}')
    elif fault == 'unknown': (out / 'mystery').write_text('keep')
    else:
        path = next(out.glob('*.errors.jsonl')); original = path.read_bytes(); path.unlink(); os.link(db,path)
    before = {p.name:p.read_bytes() for p in out.iterdir()}
    with pytest.raises(c.CaptureError): observe(db, out, resume=True, once=True)
    assert {p.name:p.read_bytes() for p in out.iterdir()} == before

def test_resume_records_offline_gap_and_keeps_original_deadline(db, tmp_path):
    out = tmp_path / 'capture'; clock = FakeClock()
    first = observe(db, out, once=True, duration_seconds=10, poll_seconds=2, clock=clock)
    clock.advance(4)
    second = observe(db, out, resume=True, once=True, clock=clock)
    assert first['deadline'] == second['deadline']
    assert second['observations'] == 2
    assert any(g['reason'] == 'restart_offline' for g in second['gaps'])
    clock.advance(7)
    last = observe(db, out, resume=True, once=True, clock=clock)
    assert last['observations'] == 2
    assert last['status'] == 'duration_completed'
    assert last['seven_day_replay_ready'] is False

@pytest.mark.parametrize('jump', [-30,30])
def test_clock_jump_never_claims_completion(db, tmp_path, jump):
    def action(clock): clock.wall += timedelta(seconds=jump)
    out = tmp_path / 'capture'
    with pytest.raises(c.CaptureError, match='clock'):
        observe(db, out, duration_seconds=3, poll_seconds=1, clock=FakeClock(action))
    assert any('clock' in e['payload'].get('reason','') for e in ledger(out) if e['kind'] == 'gap')
    assert not any(e['payload'].get('status') == 'duration_completed' for e in ledger(out))

def test_missed_cadence_is_disclosed(db, tmp_path):
    def delay(clock):
        if clock.sleeps == 1: clock.advance(3)
    report = observe(db, tmp_path / 'capture', duration_seconds=6, poll_seconds=1, clock=FakeClock(delay))
    assert any(g['reason'] == 'missed_cadence' for g in report['gaps'])


def test_interrupted_publication_preserves_orphans_and_restart_gap(db, tmp_path, monkeypatch):
    out = tmp_path / 'capture'; clock = FakeClock()
    observe(db, out, once=True, clock=clock)
    original = c.append_event
    def interrupt(*args, **kwargs):
        if args[1]['kind'] == 'observation': raise KeyboardInterrupt
        return original(*args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(c, 'append_event', interrupt)
        with pytest.raises(KeyboardInterrupt): observe(db, out, resume=True, once=True, clock=clock)
    before = {p.name:p.read_bytes() for p in out.iterdir() if p.name != 'ledger.jsonl'}
    clock.advance(1)
    report = observe(db, out, resume=True, once=True, clock=clock)
    assert any(g['reason'] == 'interrupted_publication' for g in report['gaps'])
    assert all((out / name).read_bytes() == data for name,data in before.items())


def test_cli_once_real_fixture(db, tmp_path):
    result = subprocess.run([sys.executable,str(ROOT/'benchmarks/tools/evalops/capture.py'),'--db',str(db),'--output-dir',str(tmp_path/'capture'),'--once'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['observations'] == 1
    assert report['quality_acceptance'] is False


def test_wal_source_refuses_without_mutating_shared_memory(db, tmp_path):
    # SQLite can write WAL read marks even for mode=ro. This adapter refuses it.
    con = sqlite3.connect(db)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute("UPDATE decisions SET commit_sha='wal'"); con.commit()
        paths = [db, Path(str(db)+'-wal'), Path(str(db)+'-shm')]
        before = {p:p.read_bytes() for p in paths}
        with pytest.raises(c.CaptureError, match='WAL|sidecar'):
            observe(db, tmp_path / 'capture', once=True)
        assert {p:p.read_bytes() for p in paths} == before
    finally: con.close()


def test_progress_deadline_is_enforced_on_real_sqlite_read(db, tmp_path):
    class TickingClock(FakeClock):
        def monotonic(self):
            self.mono += .01
            self.wall += timedelta(seconds=.01)
            return self.mono
    with pytest.raises(c.CaptureError, match='deadline|read'):
        observe(db, tmp_path / 'capture', once=True, limits=c.Limits(read_seconds=.001), clock=TickingClock())


@pytest.mark.parametrize('raw', ['unknown source time', None])
def test_unknown_times_preserved_outside_strict_payload(db, tmp_path, raw):
    # Native NOT NULL still permits arbitrary text; NULL exercises stored history validation separately.
    if raw is None: raw = ''
    with sqlite3.connect(db) as con:
        con.execute('UPDATE decisions SET created_at=?', (raw,))
    out = tmp_path / 'capture'; report = observe(db, out, once=True)
    assert report['timestamp_support']['unknown'] == 1
    assert exported(out, report, 'lessons')[0]['created_at'] is None
    assert batches(out)[0]['changes'][1]['row']['created_at'] == raw
    runner.validate_recurrence(exported(out, report, 'lessons'), lessons=True)


def test_stored_oversize_and_float_overflow_are_rejected(db, tmp_path):
    out = tmp_path / 'capture'; observe(db, out, once=True)
    manifest = out / 'run.json'
    manifest.write_text('{"overflow":1e999}')
    with pytest.raises(c.CaptureError): observe(db, out, resume=True, once=True)


def test_real_keyset_paging_and_canonical_hash_difference(db, tmp_path):
    execute(db, "INSERT INTO decisions (id,task_ref,session,decision,created_at) VALUES (0,'T','import','lower','1999-01-01 00:00:00');")
    out = tmp_path / 'capture'; clock = FakeClock()
    first = observe(db, out, once=True, limits=c.Limits(page_size=1), clock=clock)
    first_batch = batches(out)[0]
    assert first_batch['cursors']['decisions']['rows'] == 2
    assert first_batch['cursors']['decisions']['pages'] == 3
    # A previously captured non-exported mutable decision field changes type/value.
    execute(db, "UPDATE decisions SET total_tokens=12 WHERE id=1;")
    observe(db, out, resume=True, once=True, clock=clock)
    second = batches(out)[1]
    assert len(second['changes']) == 1
    assert second['changes'][0]['kind'] == 'update'
    assert second['snapshot_hashes'] != first_batch['snapshot_hashes']


def test_durable_data_before_ledger_fsync(db, tmp_path, monkeypatch):
    real = os.fsync
    calls = []
    def tracked(fd):
        calls.append(os.readlink(f'/proc/self/fd/{fd}'))
        return real(fd)
    monkeypatch.setattr(os, 'fsync', tracked)
    out = tmp_path / 'capture'; observe(db, out, once=True)
    batch_index = next(i for i,p in enumerate(calls) if p.endswith('.batch.json'))
    ledger_indices = [i for i,p in enumerate(calls) if p.endswith('/ledger.jsonl')]
    assert any(i > batch_index for i in ledger_indices)
    assert ledger_indices[-1] > max(i for i,p in enumerate(calls) if p.endswith(('.errors.jsonl','.lessons.jsonl','.report.json')))


def test_run_byte_limit_bounds_publication_without_overwriting(db, tmp_path):
    with pytest.raises(c.CaptureError, match='limit'):
        observe(db, tmp_path / 'capture', once=True, limits=c.Limits(max_run_bytes=100))
    assert db.read_bytes().startswith(b'SQLite format 3')


def test_source_parent_symlink_and_incompatible_schema_refuse(db, tmp_path):
    link = tmp_path / 'alias'; link.symlink_to(tmp_path, target_is_directory=True)
    before = db.read_bytes()
    with pytest.raises(c.CaptureError): observe(link/db.name, tmp_path/'out', once=True)
    assert db.read_bytes() == before
    execute(db, 'DROP TABLE decisions; CREATE TABLE decisions(id TEXT PRIMARY KEY, decision TEXT);')
    with pytest.raises(c.CaptureError, match='schema'):
        observe(db, tmp_path/'bad-schema', once=True)


def test_actual_sqlite_uri_and_query_only_no_write_statements(db, tmp_path, monkeypatch):
    real = sqlite3.connect; statements = []; uris = []
    def connected(database, **kwargs):
        uris.append((database,kwargs))
        con = real(database, **kwargs)
        con.set_trace_callback(statements.append)
        return con
    monkeypatch.setattr(c.sqlite3, 'connect', connected)
    observe(db, tmp_path/'capture', once=True)
    assert uris[0][0].endswith('?mode=ro') and uris[0][1]['uri'] is True
    assert 'PRAGMA query_only=ON' in statements
    assert all(s.startswith(('PRAGMA table_info','PRAGMA query_only=ON','SELECT','BEGIN')) for s in statements)


def test_expired_run_does_not_read_source_or_extend_deadline(db, tmp_path):
    out = tmp_path/'capture'; clock = FakeClock()
    first = observe(db, out, once=True, duration_seconds=1, clock=clock)
    clock.advance(2)
    def forbidden(*args): pytest.fail('expired run performed source read')
    result = observe(db, out, resume=True, reader=forbidden, clock=clock)
    assert result['deadline'] == first['deadline']
    assert result['observations'] == 1
    assert result['status'] == 'duration_completed'


def test_stored_read_bound_rejects_large_manifest(db, tmp_path):
    out = tmp_path/'capture'; observe(db, out, once=True)
    with (out/'run.json').open('ab') as stream:
        stream.truncate(256*1024+1)
    with pytest.raises(c.CaptureError, match='byte limit'):
        observe(db, out, resume=True, once=True)


def test_inventory_sized_projection_fits_default_bounds(db, tmp_path):
    with sqlite3.connect(db) as con:
        con.executemany("INSERT INTO decisions (task_ref,session,decision,created_at) VALUES ('T','s',?,'2026-10-29 00:00:00')", ((f'inventory-sized decision {i}',) for i in range(19834)))
        con.executemany("INSERT INTO agent_errors (repo_instance_id,harness,error_class,summary) VALUES ('r','codex','pytest',?)", ((f'error {i}',) for i in range(1547)))
    out = tmp_path/'capture'
    result = observe(db, out, once=True)
    batch = batches(out)[0]
    assert batch['row_count'] == 19835+1548
    assert batch['row_bytes'] < c.Limits().max_bytes
    assert len(exported(out, result, 'lessons')) == 19835
    assert batch['cursors']['decisions']['pages'] == 20


def test_operator_stop_and_rollback_rehearsal_preserve_evidence(db, tmp_path):
    import signal
    out = tmp_path/'capture'
    before = db.read_bytes()
    def stop(clock): os.kill(os.getpid(), signal.SIGTERM)
    clock = FakeClock(stop)
    report = observe(db, out, duration_seconds=10, poll_seconds=1, clock=clock)
    assert report['status'] == 'stopped'
    assert any(g['reason'] == 'operator_stop' for g in report['gaps'])
    stored = {p.name:p.read_bytes() for p in out.iterdir() if p.name != 'ledger.jsonl'}
    clock.action = None
    observe(db, out, resume=True, once=True, clock=clock)
    assert all((out/name).read_bytes() == data for name,data in stored.items())
    assert db.read_bytes() == before


def test_retained_id_overflow_does_not_commit_an_invalid_event(db, tmp_path, monkeypatch):
    out = tmp_path/'capture'; clock = FakeClock()
    observe(db, out, once=True, clock=clock)
    execute(db, "DELETE FROM agent_errors; INSERT INTO decisions (id,task_ref,session,decision) VALUES (2,'T','s','new');")
    with monkeypatch.context() as m:
        m.setattr(c, 'MAX_RETAINED_IDS', 2)
        with pytest.raises(c.CaptureError, match='retained ID count'):
            observe(db, out, resume=True, once=True, clock=clock)
    assert len(batches(out)) == 1
    # Resume must still validate the full chain after overflow, then observe once.
    result = observe(db, out, resume=True, once=True, clock=clock)
    assert result['observations'] == 2


def test_read_crossing_original_deadline_never_commits_observation(db, tmp_path):
    out = tmp_path/'capture'; clock = FakeClock()
    def delayed(*args):
        snapshot = c.read_snapshot(*args)
        clock.advance(2)
        return snapshot
    with pytest.raises(c.CaptureError, match='hard deadline'):
        observe(db, out, reader=delayed, duration_seconds=1, clock=clock)
    assert not batches(out)
    assert not any(e['payload'].get('status') == 'duration_completed' for e in ledger(out))


def test_resume_uses_stored_budgets_cadence_and_duration(db, tmp_path):
    out = tmp_path/'capture'; clock = FakeClock()
    first = observe(db, out, once=True, duration_seconds=10, poll_seconds=1, clock=clock)
    result = observe(db, out, resume=True, once=True, duration_seconds=100, poll_seconds=4,
                     limits=c.Limits(max_run_bytes=100, max_rows=1), clock=clock)
    assert result['deadline'] == first['deadline']
    assert result['limits'] == first['limits']
    assert result['expected_poll_seconds'] == 1


def test_monotonic_rollback_between_observations_fails_within_drift_tolerance(db, tmp_path):
    def rollback(clock):
        if clock.sleeps == 2:
            clock.mono -= 1.5  # Behind the preceding observation, within wall drift tolerance.
    out = tmp_path/'capture'
    with pytest.raises(c.CaptureError, match='monotonic clock rollback'):
        observe(db, out, duration_seconds=4, poll_seconds=1, clock=FakeClock(rollback))
    assert any(e['payload'].get('reason') == 'clock_failure' for e in ledger(out))
