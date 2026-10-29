"""Finite, read-only SQLite observation evidence. Stdlib; never quality acceptance.

Canon v0.26.2 [RES-31] bounds reads; [AGT-10] fails loudly; [TEST-15]
requires behavioral negative controls. See docs/runbooks/evalops-capture.md.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

# Reuse the runner's proven duplicate-key parser and strict payload validator.
from run import parse_json, validate_recurrence

SCHEMA = 'evalops.capture.v1'
MAX_FILE = 256 * 1024 * 1024
MAX_LEDGER = 32 * 1024 * 1024
MAX_EVENTS = 50000
MAX_RETAINED_IDS = 100000
TABLES = ('agent_errors', 'decisions')
FIELDS = {
    'agent_errors': ('id', 'task_ref', 'error_class', 'created_at'),
    'decisions': ('id', 'task_ref', 'decision', 'rationale', 'created_at'),
}
REQUIRED = {
    'agent_errors': {'id':'INTEGER', 'task_ref':'TEXT', 'error_class':'TEXT',
                     'created_at':'TEXT', 'occurrence_count':'INTEGER', 'last_seen_at':'TEXT'},
    'decisions': {'id':'INTEGER', 'task_ref':'TEXT', 'decision':'TEXT',
                  'rationale':'TEXT', 'created_at':'TEXT'},
}
ARTIFACT = re.compile(r'[0-9]{8}-[0-9a-f]{32}\.(batch\.json|errors\.jsonl|lessons\.jsonl|report\.json)\Z')
SOURCE_CONTRACT = {
    'source_number': 1, 'task': 'EVALOPS-2-CAPTURE',
    'base': 'b4f52e7b822551c05cb3bb90bbcb7b48dfa5db20',
    'tree': '481773a3a4682d501a30462c7b85a4b37baaec46',
    'partial_upstream_snapshot': True,
    'sha256': {
        'replay_inventory_result.json': '27639510e64fc2b7c1da8116dea62da55f539354489f4be7329cf663ba6bd91a',
        'db-schema.json': 'f17368813b4bd559d97c213cff2037474ee3b8d2e4d99d745d9b56a7119701ad',
        'agent_errors.py': '4b21ee41833a4a92ca1514a13eef7710323a106ec9abaf2b9b3f550d05ed9234',
        'decisions.py': 'b0fdb21f4380e12012d05ffb09f00cfea5c5d8bef9b0e6470be567c4531579fa',
        'import_export.py': '717352111ab5ea8e5b04055f23bb2b6e9819a35ee9a4c8bde856516c9aacb136',
    },
}
LIMITATIONS = [
    'Polling observes states, not intermediate changes between polls or deletions before first read.',
    'Deduplicated source error rows are not individual error occurrences.',
    'Decision records and recurrence markers are not independently validated lessons or causal evidence.',
    'Producer delivery, retention and event-time completeness are not proven.',
    'Raw source times may be naive, delayed or imported; observation time never replaces event time.',
    'Deleted IDs retain their last observed record in exports; see deleted_ids and tombstones.',
    'Hash chains detect accidental tampering; they do not authenticate the producer or attest completeness.',
    'WAL sources are read with mode=ro; SQLite may create or update normal -wal/-shm files for that reader.',
    'duration_completed means only finite observation time elapsed; no accepted QC or mature replay.',
]


class CaptureError(ValueError):
    """Fail closed, leaving existing evidence intact."""


def require(condition, message):
    if not condition:
        raise CaptureError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict(data):
    result = parse_json(data)
    encoded(result)  # Reject float overflow (1e999), beyond parse_constant's NaN/Infinity.
    return result


def iso(value):
    require(isinstance(value, datetime) and value.tzinfo is not None, 'collector clock must be aware UTC')
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def parsed(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, 'stored collector time must be aware')
    return result.astimezone(UTC)


@dataclass(frozen=True)
class Limits:
    max_rows: int = 50000
    max_bytes: int = 64 * 1024 * 1024
    page_size: int = 1000
    read_seconds: float = 5.0
    busy_seconds: float = 1.0
    max_run_bytes: int = 4 * 1024 * 1024 * 1024

    def validate(self):
        for key, cap in [('max_rows',100000), ('max_bytes',MAX_FILE),
                         ('page_size',1000), ('max_run_bytes',16 * 1024**3)]:
            value = getattr(self, key)
            require(type(value) is int and 0 < value <= cap, f'{key}: limit must be in 1..{cap}')
        for key in ('read_seconds', 'busy_seconds'):
            value = getattr(self, key)
            require(type(value) in (float,int) and math.isfinite(value) and 0 < value <= 30,
                    f'{key}: deadline must be positive and <=30 seconds')


class Clock:
    def now(self):
        return datetime.now(UTC)
    def monotonic(self):
        return time.monotonic()
    def sleep(self, seconds):
        time.sleep(seconds)


def boot_id():
    # Monotonic values are comparable across process restarts only on this boot.
    if sys.platform == 'linux':
        authority = 'Linux /proc/sys/kernel/random/boot_id'
    elif sys.platform == 'darwin':
        authority = 'Darwin kern.bootsessionuuid'
    else:
        raise CaptureError(f'boot identity unsupported platform: {sys.platform}')
    try:
        if sys.platform == 'linux':
            value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        else:
            result = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'],
                                    check=True, capture_output=True, text=True, timeout=2)
            value = result.stdout.strip()
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CaptureError(f'boot identity unavailable from {authority}: {exc}') from exc
    require(re.fullmatch(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}', value)
            is not None, f'boot identity from {authority} is not a UUID')
    return value if sys.platform == 'linux' else 'darwin:' + value.lower()


def code_hashes():
    return {name: digest(Path(__file__).with_name(name).read_bytes())
            for name in ('capture.py', 'run.py')}


@contextmanager
def directory(path):
    """Pin every parent descriptor without following a symlink (runner publication pattern)."""
    path = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def regular(info, label, private=False):
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            f'{label}: expected regular file with one link')
    if private:
        require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.geteuid(),
                f'{label}: expected owned 0600 file')


def source_identity(path):
    """Read only a fixed header, never a backup or whole-file hash per poll."""
    with directory(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            regular(info, 'source')
            header = os.read(fd, 32)
        finally:
            os.close(fd)
        require(header[:16] == b'SQLite format 3\x00', 'read: source is not SQLite')
        # Journal version bytes: 1,1 rollback; 2,2 WAL (the native producer mode).
        require(header[18:20] in (b'\x01\x01', b'\x02\x02'), 'read: unsupported SQLite journal version bytes')
        wal = header[18:20] == b'\x02\x02'
        for suffix in ('-wal','-shm','-journal'):
            try:
                aux = os.stat(path.name + suffix, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            # Healthy WAL -wal/-shm come and go with SQLite's own lifecycle, so they are
            # not part of identity; they must still be real single-link files, not aliases.
            require(wal and suffix != '-journal',
                    f'source sidecar {suffix} present outside WAL mode; refuse recovery')
            regular(aux, f'source sidecar {suffix}')
    return {'path': str(path), 'device': info.st_dev, 'inode': info.st_ino}


def read_snapshot(db, limits, clock, deadline):
    """One consistent, bounded transaction; full rows from exactly two PK-indexed tables."""
    identity = source_identity(db)
    start = clock.monotonic()
    end = min(deadline, start + limits.read_seconds)

    def check():
        require(clock.monotonic() < end, 'SQLite read deadline exceeded')

    check()
    con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True,
                          timeout=min(limits.busy_seconds, max(.001, end-start)))
    try:
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limits.max_bytes)
        con.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 128)
        con.set_progress_handler(lambda: int(clock.monotonic() >= end), 1000)
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        schema, result, cursors = {}, {}, {}
        total_rows = total_bytes = 0
        for table in TABLES:
            check()
            ddl = con.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', ('table',table)).fetchone()
            require(ddl is not None and ddl[0].lstrip().upper().startswith('CREATE TABLE'),
                    f'unsupported schema: {table} must be a native table')
            columns = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            types = {r[1]:r[2].upper() for r in columns}
            require(all(types.get(k) == v for k,v in REQUIRED[table].items()),
                    f'incompatible required schema: {table}')
            require([r[1] for r in columns if r[5]] == ['id'], f'{table}: integer id primary key required')
            schema[table] = {'ddl':ddl[0], 'columns':[list(r) for r in columns]}
            require(len(encoded(schema)) <= 256*1024, 'schema byte limit exceeded')
            names = [r[1] for r in columns]
            current, cursor, pages = {}, None, 0
            while True:
                check()
                query = f'SELECT * FROM "{table}"'
                args = []
                if cursor is not None:
                    query += ' WHERE id > ?'
                    args.append(cursor)
                query += ' ORDER BY id LIMIT ?'
                args.append(min(limits.page_size, limits.max_rows - total_rows + 1))
                found = 0
                for values in con.execute(query, args):
                    check()
                    row = dict(zip(names, values))
                    require(type(row['id']) is int, f'{table}: id must be integer')
                    require(cursor is None or row['id'] > cursor, 'keyset ordering failure')
                    total_rows += 1
                    require(total_rows <= limits.max_rows, 'snapshot row limit exceeded')
                    total_bytes += len(encoded(row))
                    require(total_bytes <= limits.max_bytes, 'snapshot byte limit exceeded')
                    cursor = row['id']
                    current[cursor] = row
                    found += 1
                pages += 1
                if found < args[-1]:
                    break
            result[table] = current
            cursors[table] = {'last_id':cursor, 'rows':len(current), 'pages':pages}
        check()
        require(source_identity(db) == identity, 'source replacement during read')
        return {'rows':result, 'source':identity, 'schema':schema,
                'schema_sha256':digest(encoded(schema)), 'cursors':cursors,
                'row_count':total_rows, 'row_bytes':total_bytes,
                'read_seconds':clock.monotonic()-start}
    except sqlite3.DataError as exc:
        raise CaptureError(f'SQLite read size limit exceeded: {exc}') from exc
    finally:
        # Close read transaction; no commit, checkpoint, vacuum, journal_mode or SQL writes.
        # The main file is opened O_RDONLY, so a closing reader cannot checkpoint into it.
        con.close()


class Store:
    """Single-writer, descriptor-pinned, exclusively published private artifacts."""
    def __init__(self, output, resume, limits):
        self.output, self.limits = output, limits
        self.fd = self.lock = None
        with directory(output.parent) as parent:
            if not resume:
                os.mkdir(output.name, mode=0o700, dir_fd=parent)
                os.fsync(parent)
            self.fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(self.fd)
            require(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid(),
                    'run root must be owned 0700 directory')
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            if not resume:
                flags |= os.O_CREAT | os.O_EXCL
            self.lock = os.open('.lock', flags, 0o600, dir_fd=self.fd)
            regular(os.fstat(self.lock), '.lock', True)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CaptureError('single writer lock already held') from exc
            self.used = 0
            self.names = set()
            with os.scandir(self.fd) as entries:
                for entry in entries:
                    require(len(self.names) < MAX_EVENTS * 4 + 3, 'stored file count limit exceeded')
                    self.names.add(entry.name)
            for name in self.names:
                require(name in {'.lock','run.json','ledger.jsonl'} or ARTIFACT.fullmatch(name),
                        f'unknown artifact: {name}; never overwrite or repair it')
                regular(os.stat(name, dir_fd=self.fd, follow_symlinks=False), name, True)
                self.used += os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_size
            initial_cap = 16 * 1024**3 if resume else limits.max_run_bytes
            require(self.used <= initial_cap, 'stored run byte limit exceeded')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def reserve(self, size):
        require(self.used + size <= self.limits.max_run_bytes, 'run byte limit exceeded')
        self.used += size

    def write(self, name, data):
        require(len(data) <= MAX_FILE, 'artifact byte limit exceeded')
        self.reserve(len(data))
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        self.names.add(name)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(self.fd)
        return {'name':name, 'bytes':len(data), 'sha256':digest(data)}

    def read(self, name, cap=MAX_FILE):
        require('/' not in name and name not in ('.','..'), 'unsafe stored artifact name')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, 'rb') as stream:
            regular(os.fstat(stream.fileno()), name, True)
            data = stream.read(cap + 1)
        require(len(data) <= cap, f'{name}: stored byte limit exceeded')
        return data


def append_event(store, event):
    """All referenced data and their directory entries are fsynced BEFORE the ledger."""
    payload = encoded(event)
    store.reserve(len(payload))
    fd = os.open('ledger.jsonl', os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
                 dir_fd=store.fd)
    with os.fdopen(fd, 'ab') as stream:
        regular(os.fstat(stream.fileno()), 'ledger.jsonl', True)
        require(os.fstat(stream.fileno()).st_size + len(payload) <= MAX_LEDGER, 'ledger byte limit exceeded')
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


class History:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.events = []
        self.latest = {t:{} for t in TABLES}
        self.present = {t:{} for t in TABLES}
        self.deleted = {t:set() for t in TABLES}
        self.schema = None
        self.snapshot_hashes = {t:snapshot_hash({}) for t in TABLES}
        self.last_observation = None
        self.head = digest(encoded(config))
        self.referenced = {'.lock','run.json','ledger.jsonl'}

    def apply(self, event, batch=None):
        if event['kind'] == 'observation':
            require(batch['source'] == self.config['source'], 'batch source identity mismatch')
            require(batch['schema_sha256'] == digest(encoded(batch['schema'])), 'batch schema hash mismatch')
            if self.schema is not None:
                require(self.schema == batch['schema_sha256'], 'batch schema changed')
            self.schema = batch['schema_sha256']
            changed_tables = set()
            for change in batch['changes']:
                table, key, kind, row = (change[k] for k in ('table','id','kind','row'))
                require(table in TABLES and type(key) is int and row['id'] == key, 'invalid change identity')
                require(change['row_sha256'] == digest(encoded(row)), 'row hash mismatch')
                if kind == 'delete':
                    require(self.present[table].get(key) == row, 'invalid tombstone')
                    del self.present[table][key]
                    self.deleted[table].add(key)
                else:
                    require(kind in ('insert','update'), 'unknown change kind')
                    require((key in self.present[table]) == (kind == 'update'), 'change state mismatch')
                    self.present[table][key] = row
                    self.deleted[table].discard(key)
                self.latest[table][key] = row
                changed_tables.add(table)
            require(sum(len(r) for r in self.latest.values()) <= MAX_RETAINED_IDS, 'retained ID count limit exceeded')
            for table in TABLES:
                if table in changed_tables:
                    self.snapshot_hashes[table] = snapshot_hash(self.present[table])
                require(batch['snapshot_hashes'][table] == self.snapshot_hashes[table], 'snapshot replay hash mismatch')
                require(batch['cursors'][table]['rows'] == len(self.present[table]), 'snapshot replay count mismatch')
            self.last_observation = event
        self.events.append(event)
        self.head = event['hash']
        self.referenced.update(v['name'] for v in event['files'].values())

    def add(self, kind, now, mono, payload, files=None, batch=None):
        require(len(self.events) < MAX_EVENTS, 'event count limit exceeded')
        event = {'sequence':len(self.events)+1, 'previous':self.head, 'kind':kind,
                 'time':iso(now), 'monotonic':mono, 'payload':payload, 'files':files or {}}
        event['hash'] = digest(encoded(event))
        append_event(self.store, event)
        self.apply(event, batch)
        return event

    def gap(self, reason, now, mono, **detail):
        prior = self.last_observation['time'] if self.last_observation else self.config['started_at']
        gap = {'reason':reason, 'since':prior, 'until':iso(now), **detail}
        self.add('gap', now, mono, gap)

    def validate(self):
        validation_deadline = time.monotonic() + 30
        raw = self.store.read('ledger.jsonl', MAX_LEDGER)
        require(not raw or raw.endswith(b'\n'), 'truncated ledger; refuse silent repair')
        for line in raw.splitlines():
            require(time.monotonic() < validation_deadline, 'resume validation deadline exceeded')
            require(len(self.events) < MAX_EVENTS, 'stored event limit exceeded')
            event = strict(line)
            require(set(event) == {'sequence','previous','hash','kind','time','monotonic','payload','files'},
                    'invalid ledger fields')
            require(event['sequence'] == len(self.events)+1 and event['previous'] == self.head,
                    'ledger sequence/hash chain mismatch')
            unsigned = {k:v for k,v in event.items() if k != 'hash'}
            require(event['hash'] == digest(encoded(unsigned)), 'ledger hash mismatch')
            require(event['kind'] in ('observation','gap','publication'), 'invalid event kind')
            parsed(event['time'])
            require(type(event['monotonic']) in (int,float) and math.isfinite(event['monotonic']), 'invalid monotonic clock')
            batch = None
            for role, ref in event['files'].items():
                require(role in ('batch','errors','lessons','report') and ARTIFACT.fullmatch(ref['name']),
                        'invalid artifact reference')
                require(ref['name'] not in self.referenced, 'artifact referenced twice')
                data = self.store.read(ref['name'])
                require(len(data) == ref['bytes'] and digest(data) == ref['sha256'], 'artifact hash mismatch')
                if ref['name'].endswith('.jsonl'):
                    values = [strict(x) for x in data.splitlines()]
                    validate_recurrence(values, lessons=role == 'lessons')
                else:
                    value = strict(data)
                    if role == 'batch': batch = value
            require((batch is not None) == (event['kind'] == 'observation'), 'observation batch missing')
            self.apply(event, batch)
        # Recognized unreferenced artifacts can follow a killed publication. Preserve them;
        # malformed JSON or unknown names fail, rather than repairing any stored bytes.
        orphans = sorted(self.store.names - self.referenced)
        for name in orphans:
            require(time.monotonic() < validation_deadline, 'resume validation deadline exceeded')
            data = self.store.read(name)
            if name.endswith('.jsonl'):
                for line in data.splitlines(): strict(line)
            else: strict(data)
        return orphans


def snapshot_hash(rows):
    return digest(encoded([[key,digest(encoded(rows[key]))] for key in sorted(rows)]))


def changed_batch(snapshot, history, now):
    changes = []
    for table in TABLES:
        before, current = history.present[table], snapshot['rows'][table]
        for key in sorted(before.keys() | current.keys()):
            old, new = before.get(key), current.get(key)
            if old is not None and new is not None and digest(encoded(old)) == digest(encoded(new)):
                continue
            row = old if new is None else new
            changes.append({'table':table, 'id':key,
                            'kind':'delete' if new is None else ('insert' if old is None else 'update'),
                            'row':row, 'row_sha256':digest(encoded(row))})
    return {k:v for k,v in snapshot.items() if k != 'rows'} | {
        'observed_at':iso(now), 'changes':changes,
        'snapshot_hashes':{t:snapshot_hash(snapshot['rows'][t]) for t in TABLES},
    }


def source_time(value):
    if not isinstance(value, str) or not value:
        return 'unknown'
    try:
        date = datetime.fromisoformat(value)
    except ValueError:
        return 'unknown'
    return 'naive' if date.tzinfo is None else 'aware'


def publish_exports(history, status, now, mono):
    prefix = f'{len(history.events)+1:08d}-{uuid.uuid4().hex}'
    files, support = {}, {'aware':0, 'naive':0, 'unknown':0}
    for table, kind in zip(TABLES, ('errors','lessons')):
        projection = []
        for key in sorted(history.latest[table]):
            row = history.latest[table][key]
            item = {k:row[k] for k in FIELDS[table]}
            timing = source_time(item['created_at'])
            support[timing] += 1
            if timing == 'unknown':
                item['created_at'] = None  # Raw unparseable value remains in immutable row history.
            projection.append(item)
        validate_recurrence(projection, lessons=kind == 'lessons')
        files[kind] = history.store.write(f'{prefix}.{kind}.jsonl', b''.join(encoded(r) for r in projection))
    observations = [e for e in history.events if e['kind'] == 'observation']
    report = {
        'schema':SCHEMA, 'run_id':history.config['run_id'], 'status':status,
        'started_at':history.config['started_at'], 'deadline':history.config['deadline'],
        'reported_at':iso(now), 'expected_poll_seconds':history.config['poll_seconds'],
        'expected_observations':math.ceil(history.config['duration_seconds']/history.config['poll_seconds']),
        'observations':len(observations),
        'observation_times':[e['time'] for e in observations],
        'gaps':[e['payload'] for e in history.events if e['kind'] == 'gap'],
        'deleted_ids':{t:sorted(history.deleted[t]) for t in TABLES},
        'latest_observed_counts':{t:len(history.latest[t]) for t in TABLES},
        'timestamp_support':support, 'exports':files,
        'ledger_head_before_publication':history.head,
        'source':history.config['source'], 'required_schema':REQUIRED,
        'schema_sha256':history.schema, 'executed_code_sha256':history.config['code_sha256'],
        'source_contract':SOURCE_CONTRACT, 'limits':history.config['limits'],
        'measured_read_seconds':[e['payload']['read_seconds'] for e in observations],
        'quality_acceptance':False, 'seven_day_replay_ready':False,
        'source_guarantees_proven':False, 'limitations':LIMITATIONS,
    }
    files = dict(files)
    files['report'] = history.store.write(f'{prefix}.report.json', encoded(report))
    history.add('publication', now, mono, {'status':status}, files)
    return report


@contextmanager
def stop_signals():
    """SIGTERM/SIGINT request a durable stop after the bounded active read."""
    stopped = [False]
    previous = {}
    def stop(_signum, _frame): stopped[0] = True
    try:
        # Library calls from worker threads cannot install signal handlers.
        import threading
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM,signal.SIGINT):
                previous[sig] = signal.signal(sig, stop)
        yield stopped
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


def run_capture(db, output_dir, *, duration_seconds=604800, poll_seconds=60,
                once=False, resume=False, limits=None, clock=None, reader=None):
    """Start/resume one finite run. Return the last durable report; errors raise loudly.

    reader(db, limits, clock, absolute_monotonic_deadline) is injectable for tests.
    Initial start validates a real source inside the run; failed starts leave evidence.
    """
    clock = clock or Clock()
    limits = limits or Limits()
    reader = reader or read_snapshot
    limits.validate()
    for value, label in [(duration_seconds,'duration'),(poll_seconds,'cadence')]:
        require(type(value) in (int,float) and math.isfinite(value) and value > 0,
                f'{label} must be positive finite seconds')
    require(duration_seconds <= 604800 and poll_seconds <= 86400, 'finite duration/cadence bound exceeded')
    db, output = Path(os.path.abspath(db)), Path(os.path.abspath(output_dir))
    require(output != db and output not in [Path(str(db)+s) for s in ('-wal','-shm','-journal')],
            'output collides with source or sidecar')
    store = None
    try:
        store = Store(output, resume, limits)
        now, mono = clock.now(), clock.monotonic()
        iso(now)
        if resume:
            config_data = store.read('run.json', 256 * 1024)
            config = strict(config_data)
            require(config['schema'] == SCHEMA and encoded(config) == config_data, 'unsupported/noncanonical run manifest')
            require(config['source']['path'] == str(db), 'resume source path mismatch')
            require(config['code_sha256'] == code_hashes(), 'executed code changed; resume refused')
            saved_limits = Limits(**config['limits'])
            saved_limits.validate()
            # Resume cannot enlarge any run budget, nor change cadence/duration.
            store.limits = limits = saved_limits
            require(store.used <= limits.max_run_bytes, 'stored run byte limit exceeded')
            history = History(store, config)
            orphans = history.validate()  # No writes at all until every stored byte validates.
        else:
            identity = source_identity(db)
            config = {'schema':SCHEMA, 'run_id':uuid.uuid4().hex,
                      'started_at':iso(now), 'deadline':iso(now+timedelta(seconds=duration_seconds)),
                      'start_monotonic':mono, 'boot_id':boot_id(),
                      'duration_seconds':duration_seconds, 'poll_seconds':poll_seconds,
                      'limits':asdict(limits), 'source':identity,
                      'required_schema':REQUIRED, 'code_sha256':code_hashes(),
                      'source_contract':SOURCE_CONTRACT}
            store.write('run.json', encoded(config))
            store.write('ledger.jsonl', b'')
            history = History(store, config)
            orphans = []
        start_wall, wall_deadline = parsed(config['started_at']), parsed(config['deadline'])
        require(wall_deadline == start_wall+timedelta(seconds=config['duration_seconds']), 'original deadline mismatch')
        if config['boot_id'] == boot_id():
            baseline_wall, baseline_mono = start_wall, config['start_monotonic']
            stop_mono = config['start_monotonic'] + config['duration_seconds']
        else:
            baseline_wall, baseline_mono = now, mono
            stop_mono = mono + max(0,(wall_deadline-now).total_seconds())

        def timing():
            wall, tick = clock.now(), clock.monotonic()
            iso(wall)
            require(math.isfinite(tick), 'clock monotonic is not finite')
            require(tick >= baseline_mono and abs((wall-baseline_wall).total_seconds()-(tick-baseline_mono)) <= 2,
                    'clock rollback/jump against monotonic time')
            if history.events:
                require(wall >= parsed(history.events[-1]['time']), 'wall clock rollback since last event')
                if config['boot_id'] == boot_id():
                    require(tick >= history.events[-1]['monotonic'], 'monotonic clock rollback since last event')
            return wall, tick

        try:
            now, mono = timing()
            if resume:
                history.gap('restart_offline', now, mono, prior_boot=config['boot_id'], current_boot=boot_id())
            if orphans:
                history.gap('interrupted_publication', now, mono, preserved_artifacts=orphans)
            next_due = mono
            with stop_signals() as stopped:
                while True:
                    now, mono = timing()
                    if now >= wall_deadline or mono >= stop_mono:
                        return publish_exports(history, 'duration_completed', now, mono)
                    if stopped[0]:
                        history.gap('operator_stop', now, mono)
                        return publish_exports(history, 'stopped', now, mono)
                    if mono < next_due:
                        clock.sleep(min(30, next_due-mono, stop_mono-mono))
                        continue
                    if mono > next_due + .05:
                        history.gap('missed_cadence', now, mono, due_monotonic=next_due,
                                    missed_polls=int((mono-next_due)//config['poll_seconds'])+1)
                    require(source_identity(db) == config['source'], 'source replacement detected before read')
                    snapshot = reader(db, limits, clock, min(stop_mono, mono+limits.read_seconds))
                    now, mono = timing()
                    require(mono < stop_mono and now < wall_deadline, 'read crossed original hard deadline')
                    require(snapshot['source'] == config['source'], 'source replacement detected')
                    require(history.schema is None or history.schema == snapshot['schema_sha256'],
                            'source schema incompatibility/change detected')
                    require(sum(len(history.latest[t].keys() | snapshot['rows'][t].keys()) for t in TABLES)
                            <= MAX_RETAINED_IDS, 'retained ID count limit exceeded')
                    batch = changed_batch(snapshot, history, now)
                    prefix = f'{len(history.events)+1:08d}-{uuid.uuid4().hex}'
                    ref = store.write(f'{prefix}.batch.json', encoded(batch))
                    history.add('observation', now, mono,
                                {k:snapshot[k] for k in ('row_count','row_bytes','read_seconds','cursors')},
                                {'batch':ref}, batch)
                    if once:
                        return publish_exports(history, 'observed_once', now, mono)
                    # Fixed cadence grid. Do not silently shift the schedule after a slow read.
                    elapsed_slots = max(1, math.floor((mono-next_due)/config['poll_seconds'])+1)
                    if elapsed_slots > 1:
                        history.gap('missed_cadence', now, mono, missed_polls=elapsed_slots-1,
                                    due_monotonic=next_due+config['poll_seconds'])
                    next_due += elapsed_slots*config['poll_seconds']
        except (CaptureError, sqlite3.Error, OSError, ValueError) as exc:
            # Corrupt stored evidence never enters this block: validation precedes all append paths.
            now, mono = clock.now(), clock.monotonic()
            reason = 'clock_failure' if 'clock' in str(exc) else 'source_read_or_publication_failure'
            history.gap(reason, now, mono, error=str(exc))
            publish_exports(history, 'failed', now, mono)
            raise CaptureError(str(exc)) from exc
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        if isinstance(exc, CaptureError):
            raise
        raise CaptureError(f'capture read/state failure: {exc}') from exc
    finally:
        if store is not None: store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--duration-seconds', type=float, default=604800)
    parser.add_argument('--poll-seconds', type=float, default=60)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-rows-per-poll', type=int, default=50000)
    parser.add_argument('--max-bytes-per-poll', type=int, default=64*1024*1024)
    parser.add_argument('--page-size', type=int, default=1000)
    parser.add_argument('--read-deadline-seconds', type=float, default=5)
    parser.add_argument('--sqlite-timeout-seconds', type=float, default=1)
    parser.add_argument('--max-run-bytes', type=int, default=4*1024**3)
    args = parser.parse_args(argv)
    try:
        report = run_capture(args.db, args.output_dir,
            duration_seconds=args.duration_seconds, poll_seconds=args.poll_seconds,
            once=args.once, resume=args.resume,
            limits=Limits(args.max_rows_per_poll,args.max_bytes_per_poll,args.page_size,
                          args.read_deadline_seconds,args.sqlite_timeout_seconds,args.max_run_bytes))
    except CaptureError as exc:
        print(f'EVALOPS capture failed: {exc}', file=sys.stderr)
        return 1
    print(encoded(report).decode(), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
