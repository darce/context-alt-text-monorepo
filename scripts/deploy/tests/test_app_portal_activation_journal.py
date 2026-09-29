from __future__ import annotations

import fcntl
import stat
import time
from pathlib import Path

from test_app_portal_deploy import (
    OVERLAY,
    _log,
    _prior_www,
    _run,
    _write_executable,
    _write_live_caddy,
)


def _interrupt_after_caddy(tmp_path: Path, live: Path) -> tuple[str, Path, Path, Path, str]:
    _write_live_caddy(live)
    original_caddy = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    overlay = app_root / "docker-compose.app.yml"
    overlay.write_text("services: {}\n", encoding="utf-8")
    original_overlay = overlay.read_text(encoding="utf-8")

    kill_hook = tmp_path / "kill-after-caddy.sh"
    kill_hook.write_text(
        "sync() {\n"
        '  /bin/sync "$@" || return $?\n'
        '  if [ "${@: -1}" = "$APP_PORTAL_KILL_AFTER_CADDY" ]; then\n'
        '    kill -KILL "$BASHPID"\n'
        "  fi\n"
        "}\n",
        encoding="utf-8",
    )
    interrupted = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={
            "BASH_ENV": str(kill_hook),
            "APP_PORTAL_KILL_AFTER_CADDY": str(live),
        },
    )
    assert interrupted.returncode == -9, interrupted.stdout + interrupted.stderr
    return original_caddy, www, app_root, overlay, original_overlay


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, bytes | None]]:
    snapshot = {}
    for path in [root, *root.rglob("*")]:
        metadata = path.lstat()
        contents = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        snapshot[str(path.relative_to(root))] = (
            metadata.st_mode,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            contents,
        )
    return snapshot


def _write_failing_health(path: Path) -> None:
    _write_executable(path, "#!/bin/sh\nexit 1\n")


def test_interrupted_activation_is_recovered_once(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    original_caddy, www, app_root, overlay, original_overlay = _interrupt_after_caddy(tmp_path, live)
    assert live.read_text(encoding="utf-8") != original_caddy
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert overlay.read_text(encoding="utf-8") == original_overlay

    journal = app_root / "activation.journal"
    assert journal.is_file()
    recovered = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"BASH_ENV": ""})
    output = recovered.stdout + recovered.stderr
    assert recovered.returncode == 0, output
    assert live.read_text(encoding="utf-8") != original_caddy
    assert "app.altcontext.com {" in live.read_text(encoding="utf-8")
    assert str(www) in overlay.read_text(encoding="utf-8")
    assert (www / "index.html").is_file()
    assert not journal.exists()
    assert _log(tmp_path).count(" reload ") == 2
    recovered_mtime = live.stat().st_mtime_ns

    second_run = _run(tmp_path, args=["--dry-run"], live_caddy=live, extra_env={"BASH_ENV": ""})
    assert second_run.returncode == 0, second_run.stdout + second_run.stderr
    assert live.stat().st_mtime_ns == recovered_mtime
    assert _log(tmp_path).count(" reload ") == 2


def test_dry_run_leaves_interrupted_activation_pending_without_mutation(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _, _, app_root, _, _ = _interrupt_after_caddy(tmp_path, live)
    journal = app_root / "activation.journal"
    before = _tree_snapshot(tmp_path / "opt")
    before_log = _log(tmp_path)

    result = _run(tmp_path, args=["--dry-run"], live_caddy=live, extra_env={"BASH_ENV": ""})
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "recovery pending" in output.lower(), output
    assert str(journal) in output, output
    assert "phase=prepared" in output, output
    assert _tree_snapshot(tmp_path / "opt") == before
    assert _log(tmp_path) == before_log


def test_caddyfile_inode_is_preserved_on_promotion(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    original_inode = live.stat().st_ino

    result = _run(tmp_path, args=["--apply"], live_caddy=live)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert live.stat().st_ino == original_inode


def test_caddyfile_inode_is_preserved_on_rollback(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    original_content = live.read_bytes()
    original_inode = live.stat().st_ino
    health = tmp_path / "fail-health.sh"
    _write_failing_health(health)

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_HEALTH_CMD": str(health)},
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert live.read_bytes() == original_content
    assert live.stat().st_ino == original_inode


def test_rollback_uses_app_reload_command(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    health = tmp_path / "fail-health.sh"
    _write_failing_health(health)
    reload_log = tmp_path / "reload.log"
    reload_command = tmp_path / "reload.sh"
    _write_executable(reload_command, f"#!/bin/sh\nprintf 'reload\\n' >> '{reload_log}'\n")

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={
            "APP_HEALTH_CMD": str(health),
            "APP_RELOAD_CMD": str(reload_command),
        },
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert reload_log.read_text(encoding="utf-8").splitlines() == ["reload", "reload"]


def test_failed_rollback_reload_keeps_journal_for_recovery(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    health = tmp_path / "fail-health.sh"
    _write_failing_health(health)
    reload_count = tmp_path / "reload-count"
    reload_command = tmp_path / "reload.sh"
    _write_executable(
        reload_command,
        "#!/bin/sh\n"
        f"count=0\n[ ! -f '{reload_count}' ] || count=$(cat '{reload_count}')\n"
        "count=$((count + 1))\n"
        f"printf '%s\\n' \"$count\" > '{reload_count}'\n"
        '[ "$count" -eq 2 ] && exit 1\n'
        "exit 0\n",
    )

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={
            "APP_HEALTH_CMD": str(health),
            "APP_RELOAD_CMD": str(reload_command),
        },
    )
    output = result.stdout + result.stderr
    journal = tmp_path / "opt" / "acx-backend" / "app" / "activation.journal"

    assert result.returncode != 0, output
    assert reload_count.read_text(encoding="utf-8").strip() == "2"
    assert "rollback reload failed" in output.lower(), output
    assert journal.is_file()


def test_deploy_lock_refuses_concurrent_recovery_then_recovers(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _, www, app_root, _, _ = _interrupt_after_caddy(tmp_path, live)
    journal = app_root / "activation.journal"
    lock_path = Path(f"{journal}.lock")
    lock_path.touch()
    before = _tree_snapshot(tmp_path / "opt")
    before_log = _log(tmp_path)

    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        locked_run = _run(
            tmp_path,
            args=["--apply"],
            live_caddy=live,
            extra_env={"APP_DEPLOY_LOCK_WAIT": "1", "BASH_ENV": ""},
            timeout=5,
        )
        elapsed = time.monotonic() - started

        output = locked_run.stdout + locked_run.stderr
        assert locked_run.returncode != 0, output
        assert "deployment lock" in output.lower(), output
        assert str(lock_path) in output, output
        assert elapsed < 3, f"lock wait exceeded its bound: {elapsed:.2f}s"
        assert _tree_snapshot(tmp_path / "opt") == before
        assert _log(tmp_path) == before_log

    recovered = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_DEPLOY_LOCK_WAIT": "1", "BASH_ENV": ""},
    )
    output = recovered.stdout + recovered.stderr

    assert recovered.returncode == 0, output
    assert "recovering interrupted activation" in output.lower(), output
    assert not journal.exists()
    assert (www / "index.html").is_file()


def test_rollback_restores_overlay_mode_when_contents_match(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    app_root.mkdir(parents=True, exist_ok=True)
    www = app_root / "www"
    overlay = app_root / "docker-compose.app.yml"
    original_overlay = OVERLAY.read_text(encoding="utf-8").replace("__APP_WWW__", str(www))
    overlay.write_text(original_overlay, encoding="utf-8")
    original_mode = 0o600
    overlay.chmod(original_mode)

    expected = tmp_path / "expected-overlay.yml"
    expected.write_text(original_overlay, encoding="utf-8")
    health = tmp_path / "mode-only-health-failure.sh"
    _write_executable(
        health,
        "#!/bin/sh\n"
        f"cmp -s '{overlay}' '{expected}' || exit 3\n"
        f"chmod 644 '{overlay}' || exit 4\n"
        "exit 1\n",
    )

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_HEALTH_CMD": str(health)},
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "health check failed" in output.lower(), output
    assert overlay.read_text(encoding="utf-8") == original_overlay
    assert stat.S_IMODE(overlay.stat().st_mode) == original_mode
