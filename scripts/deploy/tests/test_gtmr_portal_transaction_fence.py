"""Ownership fence for the app-portal activation transaction (lane fix-portal-transaction-fence).

Finding F1 (P-EDGE-LEASE-EXPIRY-01). app-portal.sh checked the shared edge lock only before its
external commands. Its journal, snapshot, promotion and restore writes ran unchecked, so a holder
killed during validation, or a hold expired by the clock, still produced filesystem mutations
before the run exited. The contract pinned here:

  * a lost or expired hold stops the run before the next write of any kind;
  * a transaction budget 120 seconds below the hold cap stops the run before it can outlive the hold;
  * no rollback is attempted without the lock, and the activation journal is kept so that the next
    apply run recovers it under its own lock;
  * a healthy run with the same fences completes, keeps the inode and the bytes it promotes, and
    releases the lock.

Scratch command doubles stand in for caddy, docker, the health check and date. Nothing touches /opt,
a live Caddy, Docker, a database or secrets. The date double adds a fixture offset so that a hold can
expire without waiting 7200 seconds. Every subprocess runs under a bound and is reaped at the end.

Canon v0.25.6 rows: RES-02 Timeout on every blocking call (Release It!, ch. 5); RLSE-08 Rollback
written before ship (Continuous Delivery, ch. 10 and ch. 12); TEST-15 Prove the green can go red
(The Pragmatic Programmer, ch. 9).
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
from contextlib import suppress
from pathlib import Path

import pytest
from test_app_portal_deploy import (
    OVERLAY,
    SNIPPET,
    _write_caddy_compose,
    _write_executable,
    _write_frontend,
    _write_live_caddy,
    _write_test_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "app-portal.sh"
RUN_TIMEOUT = 150
HOLD_CAP = 7200  # EDGE_LOCK_MAX_HOLD in scripts/deploy/lib/shared-edge.sh
EXPIRY_OFFSET = HOLD_CAP + 1  # advances the fixture clock past the hold cap
BUDGET_OFFSET = HOLD_CAP - 200  # hold still alive, transaction budget (cap - 120) exhausted


def _q(value: object) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _kill_holders_snippet(state: Path) -> str:
    """Kill every shared-edge holder and return only after each one is dead or reaped."""
    return (
        f"for _holder_file in {_q(state)}/shared-edge-lock.*/holder.pid; do\n"
        '  [ -f "$_holder_file" ] || continue\n'
        '  _holder_pid="$(cat "$_holder_file")"\n'
        '  kill -KILL "$_holder_pid" 2>/dev/null || true\n'
        "  _waits=0\n"
        '  while [ -r "/proc/${_holder_pid}/stat" ] && '
        "[ \"$(sed -e 's/^.*) //' -e 's/ .*//' \"/proc/${_holder_pid}/stat\" 2>/dev/null)\" != Z ]; do\n"
        "    _waits=$((_waits + 1))\n"
        '    [ "$_waits" -le 200 ] || break\n'
        "    sleep 0.05\n"
        "  done\n"
        "done\n"
    )


def _tree(root: Path) -> dict[str, tuple[int, int, int, bytes | None]]:
    """Mode, size, mtime and bytes for every path. Inodes are excluded because cp -a re-creates them."""
    snapshot: dict[str, tuple[int, int, int, bytes | None]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        meta = path.lstat()
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        snapshot[str(path.relative_to(root))] = (meta.st_mode, meta.st_size, meta.st_mtime_ns, data)
    return snapshot


def _diff(before: dict, after: dict) -> list[str]:
    changed = sorted(set(before) ^ set(after))
    changed += sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
    return changed


def _lock_free(lock: Path) -> bool:
    fd = os.open(lock, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


class _Portal:
    """One scratch VM tree plus the doubles that drive a single `app-portal.sh --apply` run."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.opt = tmp / "opt"
        self.backend = self.opt / "acx-backend"
        self.app = self.backend / "app"
        self.caddyfile = self.backend / "Caddyfile"
        self.compose = self.backend / "docker-compose.caddy.yml"
        self.journal = self.app / "activation.journal"
        self.lock = self.app / "activation.journal.lock"
        self.state = tmp / "state"
        self.bin = tmp / "bin"
        self.scratch = tmp / "scratch"
        self.log = tmp / "commands.log"
        self.log_count = tmp / "log-count-at-fault"
        self.snap = tmp / "pre-fault-opt"
        self.offset = tmp / "clock-offset"
        self.bind_json = tmp / "caddy-bind.json"
        self.health = self.bin / "health-check"
        for directory in (self.app, self.state, self.bin, self.scratch):
            directory.mkdir(parents=True, exist_ok=True)
        _write_live_caddy(self.caddyfile)
        self.original_caddy = self.caddyfile.read_bytes()
        self.original_inode = self.caddyfile.stat().st_ino
        _write_caddy_compose(self.compose)
        self.frontend = _write_frontend(tmp)
        self.manifest = _write_test_manifest(tmp)
        self.log.write_text("", encoding="utf-8")
        self.bind_json.write_text(
            json.dumps(
                {
                    "services": {
                        "caddy": {
                            "volumes": [
                                {
                                    "type": "bind",
                                    "source": str(self.caddyfile),
                                    "target": "/etc/caddy/Caddyfile",
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def _snapshot_snippet(self) -> str:
        return f"rm -rf {_q(self.snap)}\ncp -a {_q(self.opt)} {_q(self.snap)} || exit 1\n"

    def _date_double(self) -> str:
        real = shutil.which("date") or "/usr/bin/date"
        return (
            "#!/usr/bin/env bash\n"
            "set -u\n"
            "offset=0\n"
            f"if [ -f {_q(self.offset)} ]; then offset=$(cat {_q(self.offset)}); fi\n"
            'if [ "$#" -eq 1 ] && [ "$1" = "+%s" ]; then\n'
            f"  echo $(( $({_q(real)} +%s) + offset ))\n"
            "  exit 0\n"
            "fi\n"
            f'exec {_q(real)} "$@"\n'
        )

    def _caddy_double(self, fault: str) -> str:
        hook = ""
        if fault in ("loss-validate", "loss-validate-fail"):
            hook = self._snapshot_snippet() + _kill_holders_snippet(self.state)
        elif fault == "expiry-validate":
            hook = self._snapshot_snippet() + f"echo {EXPIRY_OFFSET} > {_q(self.offset)}\n"
        elif fault == "budget-validate":
            hook = self._snapshot_snippet() + f"echo {BUDGET_OFFSET} > {_q(self.offset)}\n"
        return (
            "#!/usr/bin/env bash\n"
            "set -u\n"
            f"printf 'caddy %s\\n' \"$*\" >> {_q(self.log)}\n"
            'if [ "${1:-}" = validate ]; then\n'
            "  :\n" + hook + "fi\n" + ("exit 1\n" if fault == "loss-validate-fail" else "exit 0\n")
        )

    def _docker_double(self) -> str:
        return (
            "#!/usr/bin/env bash\n"
            "set -u\n"
            f"printf 'docker %s\\n' \"$*\" >> {_q(self.log)}\n"
            'if [ "${1:-}" = compose ] && [ "${2:-}" = version ]; then exit 0; fi\n'
            'case " $* " in *" config "*) cat ' + _q(self.bind_json) + "; exit 0 ;; esac\n"
            "exit 0\n"
        )

    def _health_double(self, fault: str) -> str:
        if fault in ("loss-health", "loss-health-success"):
            body = (
                self._snapshot_snippet()
                + f"wc -l < {_q(self.log)} > {_q(self.log_count)}\n"
                + _kill_holders_snippet(self.state)
                + ("exit 0\n" if fault.endswith("success") else "exit 1\n")
            )
        elif fault in ("expiry-health", "budget-health"):
            offset = EXPIRY_OFFSET if fault == "expiry-health" else BUDGET_OFFSET
            body = self._snapshot_snippet() + f"echo {offset} > {_q(self.offset)}\nexit 1\n"
        elif fault == "loss-restore":
            body = "exit 1\n"
        else:
            body = "exit 0\n"
        return "#!/usr/bin/env bash\nset -u\n" + body

    def _env(self) -> dict[str, str]:
        return {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "LC_ALL": "C",
            "LANG": "C",
            "HOME": str(self.tmp),
            "TMPDIR": str(self.scratch),
            "EDGE_LOCK_STATE_ROOT": str(self.state),
            "APP_HOSTNAME": "app.altcontext.com",
            "APP_UPSTREAM": "prod-api:8000",
            "APP_ROOT": str(self.app),
            "APP_WWW": str(self.app / "www"),
            "CADDY_COMPOSE": str(self.compose),
            "CADDYFILE": str(self.caddyfile),
            "APP_APPROVED_ROOTS": str(self.backend),
            "APP_FRONTEND_ROOT": "/srv/app-portal",
            "APP_SNIPPET": str(SNIPPET),
            "APP_OVERLAY": str(OVERLAY),
            "APP_RELOAD_CMD": "",
            "APP_HEALTH_CMD": str(self.health),
            "FRONTEND_DIST": str(self.frontend),
            "APP_PORTAL_ENV_ROOT": str(self.manifest),
            "APP_DEPLOY_LOCK_WAIT": "5",
        }

    def _reap_holders(self) -> None:
        """Release anything a failed run left behind, so no holder outlives its test."""
        for pid_file in self.state.glob("shared-edge-lock.*/holder.pid"):
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)

    def run(self, fault: str = "none") -> subprocess.CompletedProcess[str]:
        shutil.rmtree(self.snap, ignore_errors=True)
        self.offset.unlink(missing_ok=True)
        self.log_count.unlink(missing_ok=True)
        _write_executable(self.bin / "date", self._date_double())
        _write_executable(self.bin / "caddy", self._caddy_double(fault))
        _write_executable(self.bin / "docker", self._docker_double())
        _write_executable(self.health, self._health_double(fault))
        env = self._env()
        if fault == "loss-restore":
            hook = self.tmp / "sync-hook.sh"
            hook.write_text(
                'sync() {\n /bin/sync "$@" || return $?\n'
                ' if [ "${@: -1}" = "${ROLLBACK_CADDY:-}" ] && [ "${JOURNAL_PHASE:-}" = overlay_promoted ]; then\n'
                + self._snapshot_snippet()
                + _kill_holders_snippet(self.state)
                + " fi\n}\n"
            )
            env["BASH_ENV"] = str(hook)
        try:
            return subprocess.run(
                ["bash", str(SCRIPT), "--apply"],
                cwd=str(REPO_ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
                check=False,
            )
        finally:
            self._reap_holders()

    def log_lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def docker_lines(self) -> list[str]:
        return [line for line in self.log_lines() if line.startswith("docker ")]

    def mutating_docker_lines(self) -> list[str]:
        return [line for line in self.docker_lines() if " up " in line or " exec " in line]


def _assert_stopped_before_any_further_write(portal: _Portal, result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout + result.stderr
    assert result.returncode == 5, output
    assert "shared edge lock" in output.lower(), output
    changed = _diff(_tree(portal.snap), _tree(portal.opt))
    assert changed == [], (
        "writes landed after the shared edge lock stopped covering the run:\n" + "\n".join(changed) + "\n" + output
    )
    assert not portal.journal.exists(), output
    assert portal.caddyfile.read_bytes() == portal.original_caddy, output
    assert portal.caddyfile.stat().st_ino == portal.original_inode, output
    assert portal.mutating_docker_lines() == [], output
    assert _lock_free(portal.lock), output


def test_holder_killed_during_validation_writes_nothing_after_the_loss(tmp_path: Path) -> None:
    portal = _Portal(tmp_path)
    result = portal.run("loss-validate")
    _assert_stopped_before_any_further_write(portal, result)


def test_hold_expired_during_validation_writes_nothing_after_the_expiry(tmp_path: Path) -> None:
    portal = _Portal(tmp_path)
    result = portal.run("expiry-validate")
    _assert_stopped_before_any_further_write(portal, result)


def test_transaction_budget_refuses_the_next_step_while_the_hold_is_still_alive(tmp_path: Path) -> None:
    portal = _Portal(tmp_path)
    result = portal.run("budget-validate")
    output = result.stdout + result.stderr
    assert "transaction budget" in output.lower(), (
        "the refusal must come from the 120-second budget, not the hold\n" + output
    )
    _assert_stopped_before_any_further_write(portal, result)


def test_holder_killed_during_health_check_keeps_the_journal_and_skips_rollback(tmp_path: Path) -> None:
    portal = _Portal(tmp_path)
    result = portal.run("loss-health")
    output = result.stdout + result.stderr
    assert result.returncode == 5, output
    assert "shared edge lock" in output.lower(), output
    changed = _diff(_tree(portal.snap), _tree(portal.opt))
    assert changed == [], "rollback or journal writes landed after the loss:\n" + "\n".join(changed) + "\n" + output
    count_at_loss = int(portal.log_count.read_text(encoding="utf-8").strip())
    assert len(portal.log_lines()) == count_at_loss, "a protected command ran after the loss:\n" + "\n".join(
        portal.log_lines()[count_at_loss:]
    )
    assert "phase=overlay_promoted" in portal.journal.read_text(encoding="utf-8"), (
        "the promoted journal must stay for recovery"
    )
    assert _lock_free(portal.lock), output

    recovered = portal.run("none")
    recovery_output = recovered.stdout + recovered.stderr
    assert recovered.returncode == 0, recovery_output
    assert "recovering interrupted activation" in recovery_output.lower(), recovery_output
    assert not portal.journal.exists(), recovery_output
    assert "app.altcontext.com {" in portal.caddyfile.read_text(encoding="utf-8")


def test_healthy_apply_completes_under_the_fence_and_releases_the_lock(tmp_path: Path) -> None:
    portal = _Portal(tmp_path)
    result = portal.run("none")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "applied:" in output, output
    assert "app.altcontext.com {" in portal.caddyfile.read_text(encoding="utf-8")
    assert portal.caddyfile.stat().st_ino == portal.original_inode
    assert (portal.app / "www" / "index.html").read_bytes() == (portal.frontend / "index.html").read_bytes()
    assert str(portal.app / "www") in (portal.app / "docker-compose.app.yml").read_text(encoding="utf-8")
    assert not portal.journal.exists(), output
    docker = portal.docker_lines()
    assert any(" up -d --force-recreate --no-deps caddy" in line for line in docker), docker
    assert any(" exec -T caddy caddy reload " in line for line in docker), docker
    assert _lock_free(portal.lock), output


@pytest.mark.parametrize("fault", ["loss-validate-fail"])
def test_validation_failure_after_holder_loss_cannot_cleanup_staging(tmp_path: Path, fault: str) -> None:
    portal = _Portal(tmp_path)
    _assert_stopped_before_any_further_write(portal, portal.run(fault))


@pytest.mark.parametrize("fault", ["loss-health-success", "expiry-health", "budget-health", "loss-restore"])
def test_lost_ownership_stops_health_success_failure_and_restore_writes(tmp_path: Path, fault: str) -> None:
    portal = _Portal(tmp_path)
    result = portal.run(fault)
    output = result.stdout + result.stderr
    assert result.returncode == 5, output
    assert "shared edge lock" in output.lower(), output
    assert _diff(_tree(portal.snap), _tree(portal.opt)) == [], output
    assert "phase=overlay_promoted" in portal.journal.read_text(), output
    assert _lock_free(portal.lock), output
