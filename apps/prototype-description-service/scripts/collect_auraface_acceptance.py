"""Bounded offline capture acquisition. No live producer/resource operations.

Each explicit path is opened by one isolated serial reader process. The caller
wait has a freshly computed timeout and attempts to kill/reap on expiration.
Nonblocking opens avoid FIFO waits; the regular-file check refuses devices,
directories and FIFOs. Every path component is opened no-follow, including
parent directories. Popen launch and the in-process join are not interruptible;
Cleanup gets a separate fixed reap ceiling, independent of the caller deadline:
elapsed time can exceed the deadline when launch or scheduling overruns it.
No record or acquisition exception is logged. No producer path is written.
RES-02: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#res-02
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

# Import only the sibling pure module without settings/package initialization.
_spec = importlib.util.spec_from_file_location('_offline_face_join', Path(__file__).with_name('auraface_acceptance_join.py'))
_join = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_join)

MAX_RECORD_BYTES = 1024 * 1024
MAX_RECORD_COUNT = 128

# Keep the launch/communication reserve distinct from the cleanup ceiling.
READER_REAP_RESERVE_SECONDS = 0.15
READER_REAP_GRACE_SECONDS = 0.1
# One second bounds real-child cleanup while allowing scheduling headroom.
READER_REAP_CEILING_SECONDS = 1.0
READER_LAUNCH_MARGIN_SECONDS = 0.01
_REAL_POPEN = subprocess.Popen

# stdout is bounded to max_bytes plus a small status envelope; stderr is empty.
# A path/exception/input payload is never emitted on failure.
_READ_SCRIPT = r'''
import json, os, stat, sys
request = json.loads(sys.stdin.read())
path, cap = request['path'], request['cap']
fd = None
total = 0
try:
    # Walk from a fixed directory descriptor; never follow a parent symlink.
    parts = path.split('/')
    parent = os.open('/' if path.startswith('/') else '.', os.O_PATH | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            if not part or part == '.':
                continue
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        result = {'status':'unreadable'}
    elif before.st_size > cap:
        result = {'status':'oversized'}
    else:
        pieces, total = [], 0
        while total <= cap:
            piece = os.read(fd, min(65536, cap + 1 - total))
            if not piece:
                break
            pieces.append(piece)
            total += len(piece)
        after = os.fstat(fd)
        if total > cap:
            result = {'status':'oversized'}
        elif (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or total != before.st_size:
            result = {'status':'contradictory_binding'}
        else:
            # Hex avoids undecodable bytes/JSON expansion, with a strict 2x cap.
            result = {'status':'acquired','data_hex':b''.join(pieces).hex()}
except FileNotFoundError:
    result = {'status':'missing'}
except (OSError,ValueError):
    result = {'status':'unreadable'}
finally:
    if fd is not None:
        os.close(fd)
result['bytes_read'] = total
sys.stdout.write(json.dumps(result,separators=(',',':')))
'''


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError('nonfinite JSON value')


def _reap_os_child(process):
    # Fakes retain the reserve contract; OS children also get a bounded reap.
    if not isinstance(process, _REAL_POPEN):
        return False
    hard_deadline = time.monotonic() + READER_REAP_CEILING_SECONDS
    while time.monotonic() < hard_deadline:
        try:
            pid, status = os.waitpid(process.pid, os.WNOHANG)
        except InterruptedError:
            continue
        except ChildProcessError:
            return process.returncode is not None
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return True
        remaining = hard_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.001, remaining))
    return False


def _reap_reader(process, caller_deadline, kill_time, ledger_row):
    try:
        process.wait(timeout=READER_REAP_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        # A timeout is not an exit observation. Popen can still reap via poll.
        poll = getattr(process, 'poll', None)
        if poll is not None and poll() is not None:
            return
        remaining = min(READER_REAP_RESERVE_SECONDS - READER_REAP_GRACE_SECONDS,
                        caller_deadline - (kill_time + READER_REAP_GRACE_SECONDS))
        if poll is not None and remaining > 0:
            try:
                process.wait(timeout=remaining)
                return
            except subprocess.TimeoutExpired:
                if poll() is not None:
                    return
        if _reap_os_child(process):
            return
        if isinstance(process, _REAL_POPEN):
            ledger_row['leaked_child_pid'] = process.pid
            ledger_row['leaked_child_residual'] = 'r3_class_edge:CON-22'
        raise _join.RecordError('reader_unkillable') from None


def collect_auraface_acceptance(record_paths, *, captured_inputs,
                                expected_contract, freshness_policy,
                                isolation_policy, now, max_record_bytes,
                                deadline_monotonic, max_record_count=MAX_RECORD_COUNT):
    """Acquire only explicit captured files; never glob/discover/recollect.

    Count and per-file byte caps have hard upper bounds. The deadline is an
    absolute monotonic timestamp checked during serial acquisition and around
    the join. Popen launch and in-process work cannot be interrupted; this is
    not a total caller wall-time guarantee.
    Producer join digests use canonical JSON; acquisition digests use raw bytes.
    Each acquired entry preserves the raw acquisition digest separately from
    its canonical join digest and pure join verdict.
    """
    if expected_contract != 'candidate512':
        raise ValueError('expected_contract must explicitly be candidate512')
    if type(max_record_bytes) is not int or not 1 <= max_record_bytes <= MAX_RECORD_BYTES:
        raise ValueError('max_record_bytes outside explicit bounded range')
    if type(max_record_count) is not int or not 0 <= max_record_count <= MAX_RECORD_COUNT:
        raise ValueError('max_record_count outside explicit bounded range')
    if type(deadline_monotonic) not in (float,int) or not math.isfinite(deadline_monotonic):
        raise ValueError('finite monotonic deadline required')
    if not isinstance(record_paths, (list,tuple)) or len(record_paths) > max_record_count:
        _join._validate_policy(freshness_policy, isolation_policy, now)
        result = _join.empty_result()
        result['gaps'].append('oversized')
        result['acquisition_ledger'] = [dict(record_index=None,status='oversized',reason_code='record_count_limit',bytes_read=0,record_sha256=None)]
        return result
    acquired, ledger, failures = [], [], set()
    for index, path in enumerate(record_paths):
        row = dict(record_index=index,status='unreadable',reason_code='unreadable',bytes_read=0,record_sha256=None)
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            row['status'] = row['reason_code'] = 'deadline_exceeded'
        elif not isinstance(path, Path):
            row['status'] = row['reason_code'] = 'malformed'
        else:
            try:
                # Remaining time is calculated at launch, not before prior work.
                remaining = deadline_monotonic - time.monotonic()
                if remaining < READER_REAP_RESERVE_SECONDS + READER_LAUNCH_MARGIN_SECONDS:
                    raise subprocess.TimeoutExpired('captured-reader', 0)
                process = subprocess.Popen([sys.executable,'-I','-c',_READ_SCRIPT],
                    stdin=subprocess.PIPE,text=True,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL)
                try:
                    # Kill at deadline minus the fixed reap grace, never shrink it.
                    budget = max(0, deadline_monotonic - time.monotonic())
                    output, _ = process.communicate(
                        input=json.dumps(dict(path=str(path),cap=max_record_bytes)),
                        timeout=max(0, budget - READER_REAP_RESERVE_SECONDS))
                except BaseException:
                    try:
                        process.kill()
                    except OSError:
                        # A failed signal does not justify abandoning cleanup.
                        # The bounded wait below determines whether it exited.
                        pass
                    kill_time = time.monotonic()
                    _reap_reader(process, deadline_monotonic, kill_time, row)
                    raise
                finally:
                    for pipe in (process.stdin, process.stdout):
                        if pipe is not None:
                            pipe.close()
                if process.returncode != 0 or len(output) > 2 * max_record_bytes + 256:
                    row['status'] = row['reason_code'] = 'unreadable'
                else:
                    payload = json.loads(output)
                    status = payload.get('status')
                    receipt = payload['bytes_read']
                    if type(receipt) is not int or receipt < 0:
                        raise ValueError('invalid read receipt')
                    row['bytes_read'] = receipt
                    if status != 'acquired':
                        if status not in ('missing','unreadable','oversized','contradictory_binding'):
                            status = 'unreadable'
                        row['status'] = row['reason_code'] = status
                    else:
                        raw = bytes.fromhex(payload['data_hex'])
                        row['bytes_read'] = len(raw)
                        row['record_sha256'] = hashlib.sha256(raw).hexdigest()
                        if len(raw) > max_record_bytes:
                            row['status'] = row['reason_code'] = 'oversized'
                        else:
                            record = json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_pairs,parse_constant=_reject_constant)
                            _join._bounded_json(record)
                            row['status'] = 'acquired'; row['reason_code'] = None
                            acquired.append(record)
            except subprocess.TimeoutExpired:
                row['status'] = row['reason_code'] = 'deadline_exceeded'
            except _join.RecordError as exc:
                row['status'] = row['reason_code'] = str(exc)
            except (OSError,ValueError,KeyError,RecursionError):
                row['status'] = row['reason_code'] = 'malformed'
        if row['status'] != 'acquired':
            failures.add(row['status'])
        ledger.append(row)
    # Policies govern the pure join; byte/count/deadline caps govern acquisition.
    _join._validate_policy(freshness_policy, isolation_policy, now)
    result = _join.empty_result()
    if time.monotonic() >= deadline_monotonic:
        failures.add('deadline_exceeded')
    else:
        result = _join.join_auraface_acceptance(acquired,captured_inputs=captured_inputs,expected_contract=expected_contract,freshness_policy=freshness_policy,isolation_policy=isolation_policy,now=now)
        # Join indices refer to acquired records; retain input indices explicitly.
        joined = iter(result['acquisition_ledger'])
        for row in ledger:
            if row['status'] == 'acquired':
                detail = next(joined, None)
                row['join_status'] = detail['status'] if detail else 'incomplete'
                row['join_reason_code'] = detail['reason_code'] if detail else 'incomplete'
                row['canonical_record_sha256'] = detail['record_sha256'] if detail else None
    if time.monotonic() >= deadline_monotonic:
        failures.add('deadline_exceeded')
    result['acquisition_ledger'] = ledger
    result['gaps'] = sorted(set(result['gaps']) | failures)
    # Projection is always unavailable. No implicit producer/validator invocation.
    return result
