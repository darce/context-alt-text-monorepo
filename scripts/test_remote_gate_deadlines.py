"""Exercise the actual remote body with isolated, bounded fake transports.

No network, shared clone, systemd manager, repository push or GPU is used.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("remote_gate.sh")


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def gate(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=5)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=gate-test",
            "-c",
            "user.email=gate@test.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
        timeout=5,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, timeout=5).strip()
    home = tmp_path / "remote-home"
    clone = home / "src" / "repo"
    clone.mkdir(parents=True)
    (clone / ".remote-gate-clone").touch()
    (clone / "pyproject.toml").touch()
    tools = tmp_path / "bin"
    tools.mkdir()
    events = tmp_path / "events"
    pids = tmp_path / "pids"
    real_git = subprocess.check_output(["which", "git"], text=True, timeout=5).strip()
    # The blocking fixture forks a TERM-ignoring child; all fixture-created
    # processes are recorded for bounded cleanup even when the red test fails.
    blocker = tmp_path / "blocker"
    executable(
        blocker,
        f"""#!{sys.executable}
import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(os.environ['PIDS'], 'a') as f:
    f.write(str(os.getpid()) + '\\n'); f.flush()
if os.fork() == 0:
    if os.environ.get('ESCAPE_SESSION') == 'yes': os.setsid()
    with open(os.environ['PIDS'], 'a') as f:
        f.write(str(os.getpid()) + '\\n'); f.flush()
while True: time.sleep(.1)
""",
    )
    executable(
        tools / "git",
        f"""#!/bin/bash
if [ "$1" = push ]; then
    echo push >> "$EVENTS"
    [ "$BLOCK" != push ] || exec "$BLOCKER"
    exit 0
fi
if [ "$PWD" = "$CLONE" ]; then
    echo "git:$1" >> "$EVENTS"
    [ "$BLOCK" != checkout ] || [ "$1" != checkout ] || exec "$BLOCKER"
    exit 0
fi
exec {real_git} "$@"
""",
    )
    executable(
        tools / "ssh",
        """#!/bin/bash
echo ssh >> "$EVENTS"
[ "$BLOCK" != transport ] || exec "$BLOCKER"
export HOME="$REMOTE_HOME"
exec bash -c "${@: -1}"
""",
    )
    executable(
        home / ".local/bin/uv",
        """#!/bin/bash
echo sync >> "$EVENTS"
[ "$BLOCK" != sync ] || exec "$BLOCKER"
sleep "${SYNC_DELAY:-0}"
""",
    )
    executable(
        home / ".local/bin/workbay-hostgov",
        """#!/bin/bash
echo admission >> "$EVENTS"
[ "$BLOCK" != admission ] || exec "$BLOCKER"
exit "${ADMISSION_RC:-0}"
""",
    )
    executable(
        tools / "make",
        """#!/bin/bash
if [ "$1" = -n ]; then
    echo probe >> "$EVENTS"
    [ "$BLOCK" != probe ] || exec "$BLOCKER"
    exit 0
fi
echo "make:$1" >> "$EVENTS"
if [ "$1" = gate-preflight ]; then
    [ "$BLOCK" != preflight ] || exec "$BLOCKER"
    if [ "${LINGER_SCOPE:-no}" = yes ]; then "$BLOCKER" >/dev/null 2>&1 & sleep .1; fi
    sleep "${PREFLIGHT_DELAY:-0}"
    exit "${PREFLIGHT_RC:-0}"
fi
if [ "$1" = first ]; then
    [ "$BLOCK" != import ] || exec "$BLOCKER"
    if [ "${BURST_OUTPUT:-no}" = yes ]; then
        python3 -c "import sys; sys.stdout.write('output-burst\\n' * 450000)"
    fi
    exit "${TARGET_RC:-0}"
fi
exit 0
""",
    )
    executable(
        tools / "systemd-run",
        """#!/bin/bash
echo systemd >> "$EVENTS"
[ "$BLOCK" != runner-probe ] || exec "$BLOCKER"
[ "$SYSTEMD" = yes ] || exit 1
while [ "$#" -gt 0 ]; do
    case "$1" in
        -p|--unit) shift 2 ;;
        --*) shift ;;
        *) break ;;
    esac
done
exec "$@"
""",
    )
    executable(
        tools / "systemctl",
        """#!/bin/bash
echo "systemctl:$*" >> "$EVENTS"
if [ "$2" = show ]; then
    for arg in "$@"; do case "$arg" in *.scope) echo inactive ;; esac; done
fi
""",
    )
    env = os.environ.copy()
    # Caller configuration must not accidentally select an external host.
    for key in tuple(env):
        if key.startswith("WORKBAY_REMOTE_GATE_"):
            env.pop(key)
    env.update(
        HOME=str(tmp_path / "local-home"),
        PATH=f"{tools}:{Path(sys.executable).parent}:{env['PATH']}",
        WORKBAY_REMOTE_GATE_HOST="fake.invalid",
        WORKBAY_REMOTE_GATE_DIR="src/repo",
        WORKBAY_REMOTE_GATE_BUDGET_SECONDS="1",
        WORKBAY_REMOTE_GATE_TERM_GRACE_SECONDS="1",
        REMOTE_HOME=str(home),
        CLONE=str(clone),
        EVENTS=str(events),
        PIDS=str(pids),
        BLOCKER=str(blocker),
        BLOCK="sync",
        SYSTEMD="no",
    )

    def run(external_bound=12, reader_pause=0, **updates):
        proc = subprocess.Popen(
            ["bash", str(SCRIPT), "run", "first", "later"],
            cwd=repo,
            env=env | updates,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            if reader_pause:
                time.sleep(reader_pause)
            output, _ = proc.communicate(timeout=external_bound)
        except subprocess.TimeoutExpired:
            # This external watchdog bounds the deliberately red regression.
            os.killpg(proc.pid, signal.SIGKILL)
            output, _ = proc.communicate(timeout=3)
            pytest.fail(f"external watchdog: gate exceeded {external_bound}s\n{output}")
        return proc.returncode, output

    yield run, clone, home, events, pids, sha, repo, env
    if pids.exists():
        for pid in pids.read_text().splitlines():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid), signal.SIGKILL)


def alive(pid: int) -> bool:
    try:
        # A zombie cannot run work or hold the lock. Native supervisor reaps
        # adopted children; the test watchdog may leave zombies under PID 1.
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_sync_deadline_kills_owned_tree_and_releases_lock(gate):
    run, clone, home, events, pids, sha, *_ = gate
    rc, output = run()
    assert rc == 124, output
    assert f"sha={sha}" in output
    assert "stage=sync" in output
    assert "reason=remote-deadline" in output
    assert "budget=1" in output
    assert "elapsed=" in output
    assert "make:later" not in events.read_text()
    assert len(pids.read_text().splitlines()) >= 2
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    lock = subprocess.run(["flock", "-n", str(clone / ".gate.lock"), "true"], timeout=3)
    assert lock.returncode == 0
    logs = list((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert len(logs) == 1
    assert "reason=remote-deadline" in logs[0].read_text()
    assert "stage=sync" in logs[0].read_text()


@pytest.mark.parametrize(
    "block,stage,target",
    [
        ("checkout", "checkout", "-"),
        ("admission", "admission", "-"),
        ("runner-probe", "runner-probe", "-"),
        ("probe", "preflight-probe", "gate-preflight"),
        ("preflight", "preflight", "gate-preflight"),
        ("import", "target", "first"),
    ],
)
@pytest.mark.parametrize("systemd", ["no", "yes"])
def test_remote_stage_deadlines(gate, block, stage, target, systemd):
    run, clone, home, events, pids, sha, *_ = gate
    rc, output = run(BLOCK=block, SYSTEMD=systemd)
    assert rc == 124, output
    assert f"stage={stage} target={target}" in output
    assert f"sha={sha}" in output
    assert "make:later" not in events.read_text()
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    assert subprocess.run(["flock", "-n", str(clone / ".gate.lock"), "true"], timeout=3).returncode == 0
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert "reason=remote-deadline" in terminal.read_text()
    assert terminal.with_name("worker.log").exists()
    if systemd == "yes" and block in ("preflight", "import"):
        assert "--signal=KILL remote-gate-" in events.read_text()


@pytest.mark.parametrize("systemd", ["no", "yes"])
@pytest.mark.parametrize("target_rc,expected", [("0", 0), ("9", 1)])
def test_healthy_and_target_aggregation(gate, systemd, target_rc, expected):
    run, _, home, events, _, sha, *_ = gate
    rc, output = run(BLOCK="none", SYSTEMD=systemd, TARGET_RC=target_rc, WORKBAY_REMOTE_GATE_BUDGET_SECONDS="10")
    assert rc == expected, output
    assert f"EXIT={target_rc} (first)" in output
    assert "EXIT=0 (later)" in output
    assert "DONE-ALL" in output
    assert "make:later" in events.read_text()
    assert "reason=remote-deadline" not in output
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert f"sha={sha}" in terminal.read_text()
    assert "reason=completed" in terminal.read_text()


@pytest.mark.parametrize("field", ["BUDGET", "TERM_GRACE"])
@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "inf", "nan", "999999999999999999999", "01"])
def test_invalid_deadline_input_never_pushes(gate, field, value):
    run, _, _, events, *_ = gate
    rc, output = run(**{f"WORKBAY_REMOTE_GATE_{field}_SECONDS": value})
    assert rc == 2, output
    assert f"{field}_SECONDS must be positive whole seconds" in output
    assert not events.exists()


@pytest.mark.parametrize("block,external_bound", [("push", 12), ("transport", 20)])
def test_local_transport_deadline(gate, block, external_bound):
    run, _, home, events, pids, sha, *_ = gate
    rc, output = run(external_bound=external_bound, BLOCK=block)
    assert rc == 76, output
    assert "reason=transport-deadline" in output
    assert f"sha={sha} stage={block}" in output
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    assert not (home / ".local/state/remote-gate").exists()
    if block == "push":
        assert "ssh" not in events.read_text()


@pytest.mark.parametrize("variable,expected", [("PREFLIGHT_RC", 73), ("ADMISSION_RC", 74)])
def test_existing_early_failure_statuses(gate, variable, expected):
    run, _, _, events, *_ = gate
    rc, output = run(BLOCK="none", **{variable: "1"})
    assert rc == expected, output
    assert "make:first" not in events.read_text()


def test_busy_clone_status(gate):
    run, clone, _, events, *_ = gate
    lock = (clone / ".gate.lock").open("w")
    import fcntl

    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        rc, output = run(BLOCK="none")
        assert rc == 75, output
        assert "git:checkout" not in events.read_text()
    finally:
        lock.close()


def test_file_budget_and_environment_precedence(gate):
    run, _, _, _, _, _, repo, _ = gate
    (repo / ".workbay").mkdir()
    (repo / ".workbay/remote-gate.env").write_text(
        'REMOTE_GATE_BUDGET_SECONDS="invalid"\nWORKBAY_REMOTE_GATE_BUDGET_SECONDS="999"\n'
    )
    rc, output = run()
    assert rc == 124, output  # captured caller budget 1 wins over both file namespaces


def test_file_deadline_configuration(gate):
    run, _, _, _, _, _, repo, env = gate
    env.pop("WORKBAY_REMOTE_GATE_BUDGET_SECONDS")
    env.pop("WORKBAY_REMOTE_GATE_TERM_GRACE_SECONDS")
    (repo / ".workbay").mkdir()
    (repo / ".workbay/remote-gate.env").write_text(
        'REMOTE_GATE_BUDGET_SECONDS="1"\nREMOTE_GATE_TERM_GRACE_SECONDS="1"\n'
    )
    rc, output = run()
    assert rc == 124, output
    assert "stage=sync target=-" in output
    assert "budget=1" in output


@pytest.fixture
def external_systemd(gate, tmp_path):
    """Manager parented to pytest, proving ancestry cleanup alone is insufficient."""
    *_, env = gate
    tools = Path(env["PATH"].split(":")[0])
    scopes = tmp_path / "scopes"
    scopes.mkdir()
    manager = tmp_path / "scope-manager"
    executable(
        manager,
        f"""#!{sys.executable}
import json, os, subprocess, time
from pathlib import Path
root = Path({str(scopes)!r})
tasks = {{}}
while True:
    for request in root.glob('*.request'):
        payload = json.loads(request.read_text())
        key = request.stem
        proc = subprocess.Popen(payload['argv'], cwd=payload['cwd'],
                                env=payload['env'], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (root / (payload['unit'] + '.pid')).write_text(str(proc.pid))
        tasks[key] = proc
        request.unlink()
    for key, proc in list(tasks.items()):
        result = proc.poll()
        if result is not None:
            (root / (key + '.result')).write_text(str(result if result >= 0 else 128 - result))
            del tasks[key]
    time.sleep(.02)
""",
    )
    executable(
        tools / "systemd-run",
        f"""#!{sys.executable}
import json, os, sys, time, uuid
from pathlib import Path
root = Path({str(scopes)!r})
args = sys.argv[1:]
unit = None
while args:
    if args[0] in ('-p', '--unit'):
        if args[0] == '--unit': unit = args[1]
        args = args[2:]
    elif args[0].startswith('--'): args = args[1:]
    else: break
assert unit and unit.startswith('remote-gate-')
if (root / (unit + '.pid')).exists():
    print('unit already loaded', file=sys.stderr)
    sys.exit(1)
key = uuid.uuid4().hex
request = root / (key + '.tmp')
request.write_text(json.dumps(dict(argv=args, env=dict(os.environ), cwd=os.getcwd(), unit=unit)))
request.rename(root / (key + '.request'))
result = root / (key + '.result')
end = time.monotonic() + 15
while not result.exists():
    if time.monotonic() >= end: sys.exit(90)
    time.sleep(.02)
sys.exit(int(result.read_text()))
""",
    )
    executable(
        tools / "systemctl",
        f"""#!{sys.executable}
import os, signal, sys
from pathlib import Path
root = Path({str(scopes)!r})
with open(os.environ['EVENTS'], 'a') as f: f.write('systemctl:' + ' '.join(sys.argv[1:]) + '\\n')
units = [arg.removesuffix('.scope') for arg in sys.argv[1:] if arg.endswith('.scope')]
for unit in units:
    assert unit.startswith('remote-gate-')
    path = root / (unit + '.pid')
    pid = int(path.read_text()) if path.exists() else None
    if 'show' in sys.argv:
        live = False
        if pid:
            # Manager-created session contains ONLY this unit's processes.
            for entry in Path('/proc').iterdir():
                if entry.name.isdigit():
                    try:
                        fields = (entry / 'stat').read_bytes().rsplit(b')', 1)[1].split()
                        if int(fields[2]) == pid and fields[0] != b'Z': live = True
                    except FileNotFoundError: pass
        print('active' if live else 'inactive')
    elif pid and os.environ.get('SCOPE_KILL_FAILURE') != 'yes':
        sig = signal.SIGKILL if '--signal=KILL' in sys.argv else signal.SIGTERM
        try: os.killpg(pid, sig)
        except ProcessLookupError: pass
""",
    )
    proc = subprocess.Popen([str(manager)], start_new_session=True)
    yield scopes
    proc.kill()
    proc.wait(timeout=3)
    # Test-only resources created by this manager, never live shared units.
    for path in scopes.glob("*.pid"):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(int(path.read_text()), signal.SIGKILL)


def test_external_systemd_children_are_killed(gate, external_systemd):
    run, clone, home, events, pids, _, *_ = gate
    rc, output = run(BLOCK="import", SYSTEMD="yes", WORKBAY_REMOTE_GATE_BUDGET_SECONDS="2")
    assert rc == 124, output
    assert "stage=target target=first" in output
    assert "make:later" not in events.read_text()
    assert len(pids.read_text().splitlines()) >= 2
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    assert subprocess.run(["flock", "-n", str(clone / ".gate.lock"), "true"], timeout=3).returncode == 0
    trace = events.read_text()
    assert "--signal=TERM remote-gate-" in trace
    assert "--signal=KILL remote-gate-" in trace
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert "exit=124" in terminal.read_text()


def test_scope_cleanup_failure_is_never_green(gate, external_systemd):
    run, _, home, _, _, _, *_ = gate
    rc, output = run(BLOCK="import", SYSTEMD="yes", SCOPE_KILL_FAILURE="yes", WORKBAY_REMOTE_GATE_BUDGET_SECONDS="2")
    assert rc == 79, output
    assert "reason=remote-deadline-cleanup-incomplete" in output
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert "exit=79" in terminal.read_text()


def test_session_detached_descendant_is_owned(gate):
    run, _, _, _, pids, *_ = gate
    rc, output = run(ESCAPE_SESSION="yes")
    assert rc == 124, output
    assert len(pids.read_text().splitlines()) == 2
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())


def test_disconnect_leaves_remote_terminal_evidence(gate):
    run, clone, home, _, pids, _, _, env = gate
    tools = Path(env["PATH"].split(":")[0])
    executable(
        tools / "ssh",
        f"""#!{sys.executable}
import os, signal, subprocess, sys, time
env = os.environ | {{'HOME': os.environ['REMOTE_HOME']}}
proc = subprocess.Popen(['bash', '-c', sys.argv[-1]], env=env,
                        start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(os.environ['PIDS'], 'a') as f: f.write(str(proc.pid) + '\\n')
time.sleep(.5)
os.kill(proc.pid, signal.SIGHUP)
# The fake server remains a local descendant; wait for its server-side
# cleanup rather than letting the LOCAL transport reaper kill that fake.
# Output has already been disconnected (DEVNULL), as on the real server.
proc.wait(timeout=6)
sys.exit(255)
""",
    )
    rc, output = run(WORKBAY_REMOTE_GATE_BUDGET_SECONDS="5")
    assert rc == 255, output
    end = time.monotonic() + 5
    while time.monotonic() < end:
        logs = list((home / ".local/state/remote-gate").glob("*/terminal.log"))
        if logs:
            break
        time.sleep(0.05)
    assert len(logs) == 1
    assert "reason=remote-cancelled" in logs[0].read_text()
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    assert subprocess.run(["flock", "-n", str(clone / ".gate.lock"), "true"], timeout=3).returncode == 0


def test_budget_is_shared_across_stages(gate):
    run, _, _, events, *_ = gate
    rc, output = run(BLOCK="none", SYNC_DELAY="1.2", PREFLIGHT_DELAY="1.2", WORKBAY_REMOTE_GATE_BUDGET_SECONDS="2")
    assert rc == 124, output
    assert "stage=preflight target=gate-preflight" in output
    assert "make:first" not in events.read_text()


def test_worker_start_failure_has_terminal_evidence(gate, tmp_path):
    run, _, home, events, _, sha, _, env = gate
    tools = Path(env["PATH"].split(":")[0])
    remote_tools = tmp_path / "remote-bin"
    remote_tools.mkdir()
    (remote_tools / "python3").symlink_to(sys.executable)
    # Launch the actual remote supervisor, but omit bash from its PATH so
    # starting its worker fails before lock acquisition or stage updates.
    executable(
        tools / "ssh",
        f"""#!{sys.executable}
import os, sys
env = os.environ | {{'HOME': os.environ['REMOTE_HOME'], 'PATH': {str(remote_tools)!r}}}
os.execve('/bin/bash', ['bash', '-c', sys.argv[-1]], env)
""",
    )
    rc, output = run()
    assert rc == 78, output
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    evidence = terminal.read_text()
    assert "reason=worker-start-failed" in evidence
    assert f"sha={sha} stage=lock target=-" in evidence
    assert "exit=78" in evidence
    assert "elapsed=" in evidence and "budget=1" in evidence
    assert "git:checkout" not in events.read_text()


def test_unrelated_process_tree_is_untouched(gate, tmp_path):
    run, _, _, _, _, _, _, env = gate
    unrelated_pids = tmp_path / "unrelated-pids"
    proc = subprocess.Popen([env["BLOCKER"]], env=env | {"PIDS": str(unrelated_pids)}, start_new_session=True)
    try:
        rc, output = run()
        assert rc == 124, output
        assert proc.poll() is None
        assert all(alive(int(pid)) for pid in unrelated_pids.read_text().splitlines())
    finally:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=3)


def supervisor_source():
    return SCRIPT.read_text().split("supervisor=\"$(cat <<'PY'\n", 1)[1].split("\nPY\n)", 1)[0]


def run_supervisor(gate, prelude="", worker=None, paused_until_exit=False):
    """Inject OS faults into the actual supervisor, with an external watchdog."""
    _, _, _, _, _, sha, _, env = gate
    proc = subprocess.Popen(
        [sys.executable, "-c", prelude + supervisor_source(), "remote", "1", "1",
         sha, "sync", *(worker or [env["BLOCKER"]])],
        env=env | {"HOME": env["REMOTE_HOME"]},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        if paused_until_exit:
            proc.wait(timeout=8)
        output, _ = proc.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate(timeout=3)
        pytest.fail(f"supervisor external watchdog\n{output!r}")
    return proc.returncode, output.decode()


def test_partial_writes_and_temporary_backpressure_retain_output(gate):
    prelude = """import os
original_write = os.write
write_calls = 0
def partial_write(fd, data):
    global write_calls
    write_calls += 1
    if write_calls % 3 == 0:
        raise BlockingIOError('temporary backpressure')
    return original_write(fd, data[:97])
os.write = partial_write
"""
    rc, output = run_supervisor(
        gate, prelude, [sys.executable, "-c", "print('output-burst\\n' * 500, end=''); print('DONE-ALL')"],
    )
    assert rc == 0, output
    assert output.count("output-burst\n") == 500
    assert "DONE-ALL\n" in output
    assert "TERMINAL reason=completed" in output


def test_paused_connected_reader_receives_complete_output(gate):
    run, _, home, _, _, _, *_ = gate
    rc, output = run(BLOCK="none", BURST_OUTPUT="yes", reader_pause=1.5,
                     WORKBAY_REMOTE_GATE_BUDGET_SECONDS="10")
    assert rc == 0, output[-2000:]
    assert output.count("output-burst\n") == 450000
    assert "EXIT=0 (first)" in output
    assert "EXIT=0 (later)" in output
    assert "DONE-ALL\n" in output
    worker_log = next((home / ".local/state/remote-gate").glob("*/worker.log"))
    assert worker_log.read_text().count("output-burst\n") == 450000


def test_persistently_backpressured_reader_cannot_block_cleanup(gate):
    _, _, home, _, pids, _, _, env = gate
    code = ("import os, sys; sys.stdout.write('output-burst\\n' * 450000); "
            f"sys.stdout.flush(); os.execv({env['BLOCKER']!r}, [{env['BLOCKER']!r}])")
    started = time.monotonic()
    rc, output = run_supervisor(gate, worker=[sys.executable, "-c", code], paused_until_exit=True)
    assert rc == 124, output
    assert time.monotonic() - started < 7
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert "reason=remote-deadline" in terminal.read_text()
    spool = terminal.with_name("worker.log").read_text()
    assert spool.count("output-burst\n") == 450000
    assert terminal.read_text() in spool


def test_non_utf8_unrelated_process_does_not_break_monitoring(gate):
    run, _, home, _, pids, _, *_ = gate
    proc = subprocess.Popen(
        [sys.executable, "-c", "import ctypes, time; ctypes.CDLL(None).prctl(15, b'bad-\\xff', 0, 0, 0); print('ready', flush=True); time.sleep(15)"],
        stdout=subprocess.PIPE, start_new_session=True,
    )
    try:
        import select

        assert select.select([proc.stdout], [], [], 3)[0]
        assert proc.stdout.readline() == b"ready\n"
        rc, output = run()
        assert rc == 124, output
        assert proc.poll() is None
        assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
        terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
        assert "reason=remote-deadline" in terminal.read_text()
    finally:
        proc.kill()
        proc.wait(timeout=3)
        proc.stdout.close()


@pytest.mark.parametrize("phase", ["running", "cleanup"])
def test_unexpected_monitor_failure_still_cleans_up_and_records_terminal(gate, phase):
    prelude = """import os
from pathlib import Path
original_iterdir = Path.iterdir
def broken_scan(path):
    fail = Path(os.environ['PIDS']).exists() if os.environ['FAIL_PHASE'] == 'running' else globals().get('reason') == 'remote-deadline'
    if str(path) == '/proc' and fail:
        raise RuntimeError('injected persistent monitor failure')
    return original_iterdir(path)
Path.iterdir = broken_scan
"""
    _, _, home, _, pids, sha, _, env = gate
    env['FAIL_PHASE'] = phase
    rc, output = run_supervisor(gate, prelude)
    assert rc == 79, output
    assert "reason=supervisor-error" in output
    assert f"sha={sha} stage=sync target=-" in output
    assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    terminal = next((home / ".local/state/remote-gate").glob("*/terminal.log"))
    assert "reason=supervisor-error" in terminal.read_text()
    assert "injected persistent monitor failure" in terminal.with_name("worker.log").read_text()


@pytest.mark.parametrize("linger", ["no", "yes"])
def test_unique_scopes_survive_delayed_collection(gate, external_systemd, linger):
    run, clone, _, events, pids, _, *_ = gate
    rc, output = run(BLOCK="none", SYSTEMD="yes", LINGER_SCOPE=linger,
                     WORKBAY_REMOTE_GATE_BUDGET_SECONDS="5")
    assert rc == 0, output
    assert "EXIT=0 (gate-preflight)" in output
    assert "EXIT=0 (first)" in output
    assert "EXIT=0 (later)" in output
    units = [path.stem for path in external_systemd.glob("*.pid")]
    assert len(units) == 4
    trace = events.read_text()
    for unit in units:
        for sig in ("TERM", "KILL"):
            assert any(f"--signal={sig} " in line and f"{unit}.scope" in line.split()
                       for line in trace.splitlines())
    if linger == "yes":
        assert len(pids.read_text().splitlines()) == 2
        assert not any(alive(int(pid)) for pid in pids.read_text().splitlines())
    assert subprocess.run(["flock", "-n", str(clone / ".gate.lock"), "true"], timeout=3).returncode == 0
