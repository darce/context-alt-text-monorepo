#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
[[ $# == 0 || ( $# == 1 && "$1" == --tmp-report ) ]] || {
  printf 'usage: host-hygiene.sh [--tmp-report]\n' >&2
  exit 2
}
export HYGIENE_TMP_REPORT_ONLY=0
if [[ ${1:-} == --tmp-report ]]; then
  export HYGIENE_TMP_REPORT_ONLY=1
fi
[[ "$HYGIENE_TMP_REPORT_ONLY" == 1 || "$(timeout --kill-after=2s 10s id -u)" == 0 ]] || {
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


def tree_guard(path, cutoff, metadata=None):
    root_stat = os.lstat(path)
    if os.path.basename(path) == '.git':
        return 'git'
    if os.path.basename(path) in {'.workbay-lane-sandbox', '.workbay-scratch'}:
        return 'marker'
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
                    if directory != path and metadata is not None:
                        metadata.update(barrier=directory, reason='scan_limit')
                    return 'scan_limit' if directory == path else 'split'
                children.append(entry)
        names = {entry.name for entry in children}
        if names & {'.workbay-lane-sandbox', '.workbay-scratch'}:
            return 'marker'
        if '.git' in names or {'HEAD', 'objects', 'refs'} <= names:
            if directory != path and metadata is not None:
                metadata.update(barrier=directory, reason='git')
            return 'git' if directory == path else 'split'
        for entry in children:
            info = os.lstat(entry.path)
            newest = max(newest, info.st_mtime)
            if info.st_dev != root_stat.st_dev:
                return 'mount'
            if info.st_uid != GATE_UID:
                return 'uid'
            if stat.S_ISDIR(info.st_mode):
                stack.append(entry.path)
    if metadata is not None:
        metadata['newest'] = newest
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
    result.update(held_git=0, held_live=0, would_reclaim=0, entries={}, skip_reasons={})
    result['mode'] = 'report' if os.environ.get('HYGIENE_TMP_REPORT_ONLY') == '1' else tmp_mode()
    before_metric(result, tmp_bytes())
    cutoff = time.time() - 72 * 3600

    def size(path):
        output = command('du', '--summarize', '--block-size=1', '--one-file-system',
                         '--', path)
        return int(output.split()[0])

    def record(path, top, reason):
        amount = 0 if reason == 'vanished' else size(path)
        entry = result['entries'][top]
        result['held'] += 1
        if reason == 'report':
            result['would_reclaim'] += amount
            entry['would_reclaim'] += amount
        else:
            result['held_git'] += reason == 'git'
            result['held_live'] += reason == 'live'
            for reasons in (result['skip_reasons'], entry['skip_reasons']):
                metric = reasons.setdefault(reason, dict(count=0, bytes=0, bytes_measured=True))
                metric['count'] += 1
                metric['bytes'] += amount

    barriers = {}

    def guarded(path):
        if path in barriers:
            return barriers[path]
        if any(barrier.startswith(path + os.sep) for barrier in barriers):
            return 'split'
        metadata = {}
        reason = tree_guard(path, cutoff, metadata)
        if 'barrier' in metadata:
            barriers[metadata['barrier']] = metadata['reason']
        return reason

    def sweep_path(path, top, force_reason=None):
        reason = force_reason
        try:
            reason = reason or guarded(path)
            if reason == 'split':
                # A protected descendant prevents removing its ancestors, not its siblings.
                with os.scandir(path) as entries:
                    children = [entry.path for entry in entries]
                for child in children:
                    sweep_path(child, top)
                return
            if not reason and live_tree(path):
                reason = 'live'
            if not reason and result['mode'] == 'report':
                reason = 'report'
            if not reason:
                reason = guarded(path)
                if reason == 'split':
                    sweep_path(path, top)
                    return
                # The last check before removal must be a new liveness probe.
                if not reason and live_tree(path):
                    reason = 'live'
                if not reason:
                    command('rm', '-rf', '--one-file-system', '--', path)
            if reason:
                record(path, top, reason)
        except FileNotFoundError:
            record(path, top, 'vanished')
        except TimeoutError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            result['errors'] += 1
            result['error_types'].append(type(exc).__name__)
            try:
                record(path, top, 'uncertain')
            except FileNotFoundError:
                record(path, top, 'vanished')
            except (OSError, RuntimeError, ValueError):
                result['held'] += 1
                for reasons in (result['skip_reasons'], result['entries'][top]['skip_reasons']):
                    metric = reasons.setdefault('uncertain', dict(count=0, bytes=0, bytes_measured=False))
                    metric['count'] += 1
                    metric['bytes_measured'] = False

    with os.scandir(TMP_ROOT) as entries:
        paths = [entry.path for entry in entries]
    for path in paths:
        top = os.path.basename(path)
        result['entries'][top] = dict(would_reclaim=0, skip_reasons={})
        if top in {'workbay-uv-cache', 'acx-build'}:
            sweep_path(path, top, 'excluded')
            continue
        pytest_container = False
        try:
            info = os.lstat(path)
            if (top.startswith('pytest-of-') and stat.S_ISDIR(info.st_mode)
                    and info.st_uid == GATE_UID and info.st_dev == os.lstat(TMP_ROOT).st_dev):
                pytest_container = True
                # pytest updates the container continuously; judge each run independently.
                with os.scandir(path) as entries:
                    children = []
                    for entry in entries:
                        children.append(entry.path)
                        if len(children) > 100000:
                            break
                names = {os.path.basename(child) for child in children}
                if len(children) > 100000:
                    sweep_path(path, top, 'scan_limit')
                    continue
                if names & {'.workbay-lane-sandbox', '.workbay-scratch'}:
                    sweep_path(path, top, 'marker')
                    continue
                if '.git' in names or {'HEAD', 'objects', 'refs'} <= names:
                    sweep_path(path, top, 'git')
                    continue
                newest = None
                newest_time = float('-inf')
                for child in children:
                    child_info = os.lstat(child)
                    if stat.S_ISDIR(child_info.st_mode):
                        metadata = {}
                        tree_guard(child, cutoff, metadata)
                        modified = metadata.get('newest', child_info.st_mtime)
                        if modified > newest_time:
                            newest, newest_time = child, modified
                for child in children:
                    sweep_path(child, top, 'newest_child' if child == newest else None)
                continue
        except (OSError, RuntimeError, ValueError) as exc:
            if pytest_container:
                result['errors'] += 1
                result['error_types'].append(type(exc).__name__)
                sweep_path(path, top, 'uncertain')
                continue
        sweep_path(path, top)
    freed_metric(result, tmp_bytes())


def journald(result):
    output = command('journalctl', '--disk-usage')
    match = re.search(r'take up\s+(\d+(?:\.\d+)?\s*[KMGTPE]?(?:i?B)?)\s+in', output, re.I)
    if not match:
        raise ValueError('missing journal metric')
    before_metric(result, bytes_value(match[1]))
    result['freed_measured'] = True


sweeps = [('build_cache', 'delete', build_cache), ('volumes', 'delete', volumes),
                          ('images', 'report', images), ('tmp', 'report', tmp_sweep),
                          ('journald', 'report', journald)]
if os.environ.get('HYGIENE_TMP_REPORT_ONLY') == '1':
    sweeps = [('tmp', 'report', tmp_sweep)]
for name, mode, sweep in sweeps:
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
