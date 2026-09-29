from __future__ import annotations

from pathlib import Path

from test_app_portal_deploy import _log, _prior_www, _run, _write_live_caddy


def test_interrupted_activation_is_recovered_once(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    original_caddy = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    overlay = app_root / "docker-compose.app.yml"
    overlay.write_text("services: {}\n", encoding="utf-8")
    original_overlay = overlay.read_text(encoding="utf-8")

    kill_hook = tmp_path / "kill-after-caddy.sh"
    kill_hook.write_text(
        "mv() {\n"
        '  /bin/mv "$@" || return $?\n'
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
    assert live.read_text(encoding="utf-8") != original_caddy
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert overlay.read_text(encoding="utf-8") == original_overlay

    journal = app_root / "activation.journal"
    assert journal.is_file()
    recovered = _run(tmp_path, live_caddy=live, extra_env={"BASH_ENV": ""})
    output = recovered.stdout + recovered.stderr
    assert recovered.returncode == 0, output
    assert live.read_text(encoding="utf-8") == original_caddy
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert overlay.read_text(encoding="utf-8") == original_overlay
    assert not journal.exists()
    assert _log(tmp_path).count(" reload ") == 1
    recovered_mtime = live.stat().st_mtime_ns

    second_recovery = _run(tmp_path, live_caddy=live, extra_env={"BASH_ENV": ""})
    assert second_recovery.returncode == 0, second_recovery.stdout + second_recovery.stderr
    assert live.read_text(encoding="utf-8") == original_caddy
    assert live.stat().st_mtime_ns == recovered_mtime
    assert _log(tmp_path).count(" reload ") == 1
