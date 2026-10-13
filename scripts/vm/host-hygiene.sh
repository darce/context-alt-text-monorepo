#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
[[ "$(timeout --kill-after=2s 10s id -u)" == 0 ]] || {
  printf 'host-hygiene: run as root\n' >&2
  exit 1
}
exec python3 - <<'PY'
import datetime
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

# RES-07, RES-20, OBS-16, PERF-13: bounded reclaim, no retained scratch state.
TMP_ROOT = os.path.realpath(os.environ.get('HYGIENE_TMP_ROOT', '/tmp'))
PROC_ROOT = os.environ.get('HYGIENE_PROC_ROOT', '/proc')
ETC_ROOT = Path(os.environ.get('HYGIENE_ETC_ROOT', '/etc'))
GATE_UID = int(os.environ.get('HYGIENE_GATE_UID', '1000'))
CLASS_TIMEOUT = float(os.environ.get('HYGIENE_CLASS_TIMEOUT', '300'))
if not 0 < CLASS_TIMEOUT <= 300 or TMP_ROOT == '/':
    sys.exit('host-hygiene: invalid root or timeout')
deadline = 0
summary = {}


def alarm(signum, frame):
    raise TimeoutError('class deadline')


signal.signal(signal.SIGALRM, alarm)


def command(*args):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('class deadline')
    result = subprocess.run(args, capture_output=True, text=True, timeout=remaining,
                            check=False)
    if result.returncode:
        raise RuntimeError('command failed')
    return result.stdout.strip()


def bytes_value(value):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([KMGTPE]?)(i?B)?\s*', value, re.I)
    if not match:
        raise ValueError('unrecognized byte count')
    unit = match[2].upper()
    exponent = 'KMGTPE'.index(unit) + 1 if unit else 0
    base = 1024 if unit and (not match[3] or match[3].lower().startswith('i')) else 1000
    return int(float(match[1]) * base ** exponent)


def docker_bytes(kind):
    rows = command('docker', 'system', 'df', '--format', '{{json .}}').splitlines()
    matches = [json.loads(row) for row in rows if row.strip()]
    values = [bytes_value(row['Size']) for row in matches if row['Type'] == kind]
    if len(values) != 1:
        raise ValueError('missing Docker metric')
    return values[0]


def before_metric(result, value):
    result['before'] = value
    result['before_measured'] = True


def freed_metric(result, after):
    result['freed'] = max(0, result['before'] - after)
    result['freed_measured'] = True


def build_cache(result):
    before_metric(result, docker_bytes('Build Cache'))
    command('docker', 'builder', 'prune', '-f', '--filter', 'until=168h')
    freed_metric(result, docker_bytes('Build Cache'))


def volume_created(name):
    records = json.loads(command('docker', 'volume', 'inspect', name))
    if len(records) != 1 or records[0]['Name'] != name:
        raise ValueError('invalid volume inspection')
    created = datetime.datetime.fromisoformat(records[0]['CreatedAt'].replace('Z', '+00:00'))
    if created.tzinfo is None:
        raise ValueError('volume date has no timezone')
    return created.timestamp()


def volumes(result):
    before_metric(result, docker_bytes('Local Volumes'))
    names = command('docker', 'volume', 'ls', '--quiet').splitlines()
    dangling = set(command('docker', 'volume', 'ls', '--quiet', '--filter', 'dangling=true').splitlines())
    cutoff = time.time() - 72 * 3600
    for name in names:
        if not re.fullmatch(r'[0-9a-f]{64}', name) or name not in dangling:
            result['held'] += 1
            continue
        if volume_created(name) >= cutoff:
            result['held'] += 1
            continue
        # Include stopped containers and let Docker enforce the final use race.
        if command('docker', 'ps', '--all', '--quiet', '--filter', 'volume=' + name):
            result['held'] += 1
            continue
        command('docker', 'volume', 'rm', name)
    freed_metric(result, docker_bytes('Local Volumes'))


def images(result):
    before_metric(result, docker_bytes('Images'))
    result['freed_measured'] = True


def tree_guard(path, cutoff):
    root_stat = os.lstat(path)
    if root_stat.st_dev != os.lstat(TMP_ROOT).st_dev:
        return 'mount'
    if root_stat.st_uid != GATE_UID:
        return 'uid'
    if stat.S_ISLNK(root_stat.st_mode):
        return 'symlink'
    newest = root_stat.st_mtime
    stack = [path] if stat.S_ISDIR(root_stat.st_mode) else []
    scanned = 0
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            children = []
            for entry in entries:
                scanned += 1
                if scanned > 100000:
                    raise RuntimeError('tree scan limit')
                children.append(entry)
        names = {entry.name for entry in children}
        if names & {'.workbay-lane-sandbox', '.workbay-scratch'}:
            return 'marker'
        if '.git' in names or {'HEAD', 'objects', 'refs'} <= names:
            return 'git'
        for entry in children:
            info = os.lstat(entry.path)
            newest = max(newest, info.st_mtime)
            if info.st_dev != root_stat.st_dev:
                return 'mount'
            if info.st_uid != GATE_UID:
                return 'uid'
            if stat.S_ISDIR(info.st_mode):
                stack.append(entry.path)
    return 'recent' if newest > cutoff else None


def live_tree(path):
    # RES-21: an unreadable process is uncertainty, never evidence of death.
    with os.scandir(PROC_ROOT) as entries:
        processes = [entry.path for entry in entries if entry.name.isdigit()]
    for process in processes:
        probes = [process + '/cwd', process + '/root']
        try:
            with os.scandir(process + '/fd') as entries:
                probes.extend(entry.path for entry in entries)
        except FileNotFoundError:
            pass
        for probe in probes:
            try:
                target = os.readlink(probe)
            except FileNotFoundError:
                continue
            if target.endswith(' (deleted)'):
                target = target[:-10]
            target = os.path.normpath(target)
            if target == path or target.startswith(path + os.sep):
                return True
    return False


def tmp_bytes():
    output = command('du', '--summarize', '--block-size=1', '--one-file-system', '--', TMP_ROOT)
    return int(output.split()[0])


def tmp_mode():
    mode = 'report'
    config = ETC_ROOT / 'default/acx-host-hygiene'
    try:
        with config.open() as source:
            lines = source.readlines()
    except FileNotFoundError:
        return mode
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(
            r"""ACX_HYGIENE_TMP_MODE\s*=\s*(?:(report|delete)|"(report|delete)"|'(report|delete)')(?:\s+#.*)?\s*""",
            line,
        )
        if not match:
            raise ValueError('invalid defaults file')
        mode = next(value for value in match.groups() if value is not None)
    return mode


def tmp_sweep(result):
    result['held_git'] = 0
    result['held_live'] = 0
    result['mode'] = tmp_mode()
    before_metric(result, tmp_bytes())
    cutoff = time.time() - 72 * 3600
    with os.scandir(TMP_ROOT) as entries:
        paths = [entry.path for entry in entries]
    for path in paths:
        reason = None
        try:
            if os.path.basename(path) in {'workbay-uv-cache', 'acx-build'}:
                reason = 'excluded'
            else:
                reason = tree_guard(path, cutoff)
            if not reason and live_tree(path):
                reason = 'live'
            if not reason and result['mode'] == 'report':
                reason = 'report'
            if not reason:
                reason = tree_guard(path, cutoff)
                # The last check before removal must be a new liveness probe.
                if not reason and live_tree(path):
                    reason = 'live'
                if not reason:
                    command('rm', '-rf', '--one-file-system', '--', path)
        except FileNotFoundError:
            reason = 'vanished'
        except TimeoutError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            reason = 'uncertain'
            result['errors'] += 1
            result['error_types'].append(type(exc).__name__)
        if reason:
            result['held'] += 1
            result['held_git'] += reason == 'git'
            result['held_live'] += reason == 'live'
    freed_metric(result, tmp_bytes())


def journald(result):
    output = command('journalctl', '--disk-usage')
    match = re.search(r'take up\s+(\d+(?:\.\d+)?\s*[KMGTPE]?(?:i?B)?)\s+in', output, re.I)
    if not match:
        raise ValueError('missing journal metric')
    before_metric(result, bytes_value(match[1]))
    result['freed_measured'] = True


for name, mode, sweep in [('build_cache', 'delete', build_cache), ('volumes', 'delete', volumes),
                          ('images', 'report', images), ('tmp', 'report', tmp_sweep),
                          ('journald', 'report', journald)]:
    result = dict(before=0, freed=0, held=0, mode=mode, errors=0,
                  before_measured=False, freed_measured=False, error_types=[])
    deadline = time.monotonic() + CLASS_TIMEOUT
    signal.setitimer(signal.ITIMER_REAL, CLASS_TIMEOUT)
    try:
        sweep(result)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, TimeoutError, subprocess.TimeoutExpired) as exc:
        result['errors'] += 1
        result['error_types'].append(type(exc).__name__)
        print('host-hygiene: ' + name + ' incomplete (' + type(exc).__name__ +
              '); inspect command availability, deadlines and scan permissions', file=sys.stderr)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    summary[name] = result
    print('HYGIENE {} before={} freed={} held={} mode={}'.format(
        name, result['before'], result['freed'], result['held'], result['mode']), flush=True)
print(json.dumps(summary, sort_keys=True), flush=True)
sys.exit(1 if any(result['errors'] for result in summary.values()) else 0)
PY
