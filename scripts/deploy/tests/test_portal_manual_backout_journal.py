"""Exercise the runbook's journal/lock gate and recovery using isolated fakes."""

from __future__ import annotations

import fcntl
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest
import test_app_portal_deploy as deploy_helpers
from test_app_portal_deploy import (
    OVERLAY,
    REPO_ROOT,
    RUNBOOK,
    SCRIPT,
    SNIPPET,
    _frontend_index,
    _log,
    _rollback_tree_state,
    _run,
    _run_documented_rollback,
    _run_runbook_commands,
    _write_executable,
    _write_frontend,
)

JOURNAL_GUARD = """  if [ -e /opt/acx-backend/app/activation.journal ] || [ -L /opt/acx-backend/app/activation.journal ]; then
    echo 'STOP: activation journal present; recover interrupted activation before manual back-out' >&2
    exit 1
  fi
"""


def _manual_commands() -> str:
    section = RUNBOOK.read_text().split("### Frontend back-out", 1)[1]
    return section.split("```bash\n", 1)[1].split("```", 1)[0]


def _recovery_commands() -> str:
    section = RUNBOOK.read_text().split("### Recover an interrupted frontend activation", 1)[1]
    section = section.split("### Frontend back-out", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
    assert len(blocks) == 2, "expected workstation copy and VM recovery commands"
    return blocks[1]


def _manual_state(tmp_path: Path, phase: str) -> Path:
    backend = tmp_path / "opt/acx-backend"
    app = backend / "app"
    rollback = app / "rollback"
    rollback.mkdir(parents=True)
    (backend / "Caddyfile").write_text("live caddy\n")
    (app / "www").mkdir()
    (app / "www/index.html").write_text("live frontend\n")
    (app / "docker-compose.app.yml").write_text("live overlay\n")
    (app / "activation.journal.lock").write_text("existing lock inode\n")
    # Both sets are valid: bypassing the journal gate really can select and restore.
    for stamp in ("10", "20"):
        (rollback / f"Caddyfile.{stamp}").write_text(f"caddy {stamp}\n")
        (rollback / f"www.{stamp}").mkdir()
        (rollback / f"www.{stamp}/index.html").write_text(f"frontend {stamp}\n")
        (rollback / f"docker-compose.app.yml.{stamp}").write_text(f"overlay {stamp}\n")
    journal = app / "activation.journal"
    if phase == "dangling":
        journal.symlink_to(app / "missing-journal")
    else:
        journal.write_text(f"phase={phase}\n")
    return backend


def _assert_journal_refusal(result: subprocess.CompletedProcess[str], backend: Path, before: dict) -> None:
    assert result.returncode != 0, "manual back-out bypassed activation journal gate"
    assert "STOP: activation journal present" in result.stderr
    assert "Selected rollback timestamp" not in result.stdout, "snapshot selection preceded journal gate"
    assert _rollback_tree_state(backend) == before, "manual back-out changed live or rollback state"
    assert not (backend.parents[1] / "rollback-commands.log").exists(), "manual back-out ran rollback commands"


@pytest.mark.parametrize("phase", ["snapshotting", "prepared", "overlay_promoted", "restored", "dangling"])
def test_manual_backout_refuses_retained_journal_before_selection(tmp_path: Path, phase: str) -> None:
    backend = _manual_state(tmp_path, phase)
    before = _rollback_tree_state(backend)
    _assert_journal_refusal(_run_documented_rollback(tmp_path), backend, before)


@pytest.mark.parametrize("phase", ["prepared", "overlay_promoted", "restored", "dangling"])
def test_journal_guard_removal_mutant_is_detected(tmp_path: Path, phase: str) -> None:
    backend = _manual_state(tmp_path, phase)
    before = _rollback_tree_state(backend)
    commands = _manual_commands()
    assert JOURNAL_GUARD in commands, "mutant must remove the actual journal guard"
    result = _run_runbook_commands(tmp_path, commands.replace(JOURNAL_GUARD, ""))
    # Predicted regression: valid snapshots let the unguarded block succeed.
    with pytest.raises(AssertionError, match="bypassed activation journal gate"):
        _assert_journal_refusal(result, backend, before)
    assert "Selected rollback timestamp: 20" in result.stdout
    assert _rollback_tree_state(backend) != before
    assert (tmp_path / "rollback-commands.log").exists()


def test_dangling_journal_guard_mutant_is_detected(tmp_path: Path) -> None:
    backend = _manual_state(tmp_path, "dangling")
    before = _rollback_tree_state(backend)
    commands = _manual_commands()
    mutant = commands.replace(" || [ -L /opt/acx-backend/app/activation.journal ]", "")
    assert mutant != commands
    result = _run_runbook_commands(tmp_path, mutant)
    with pytest.raises(AssertionError, match="bypassed activation journal gate"):
        _assert_journal_refusal(result, backend, before)


@pytest.mark.parametrize("unsafe", ["symlink", "dangling", "directory", "fifo"])
def test_manual_backout_rejects_unsafe_lock_without_mutations(tmp_path: Path, unsafe: str) -> None:
    backend = _manual_state(tmp_path, "prepared")
    lock = backend / "app/activation.journal.lock"
    lock.unlink()
    external = tmp_path / "external-lock"
    external.write_text("untouched\n")
    if unsafe == "directory":
        lock.mkdir()
    elif unsafe == "fifo":
        os.mkfifo(lock)
    else:
        lock.symlink_to(external if unsafe == "symlink" else tmp_path / "missing-lock")
    before = _rollback_tree_state(backend)
    external_before = _rollback_tree_state(external)
    result = _run_documented_rollback(tmp_path)
    assert result.returncode != 0
    assert "STOP: deployment lock path unsafe" in result.stderr
    assert "Selected rollback timestamp" not in result.stdout
    assert _rollback_tree_state(backend) == before
    assert _rollback_tree_state(external) == external_before
    assert not (tmp_path / "rollback-commands.log").exists()


@pytest.mark.parametrize("parent", ["app/rollback", "app", "."])
def test_manual_backout_rejects_symlink_ancestors_before_opening_lock(tmp_path: Path, parent: str) -> None:
    backend = _manual_state(tmp_path, "prepared")
    target = backend / parent
    external = tmp_path / "external-parent"
    target.rename(external)
    target.symlink_to(external, target_is_directory=True)
    before = _rollback_tree_state(external)
    result = _run_documented_rollback(tmp_path)
    assert result.returncode != 0
    assert "STOP: rollback/live parent missing or unsafe" in result.stderr
    assert "Selected rollback timestamp" not in result.stdout
    assert _rollback_tree_state(external) == before
    assert not (tmp_path / "rollback-commands.log").exists()


def test_manual_backout_uses_actual_bounded_deploy_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = SCRIPT.read_text()
    assert 'ACTIVATION_JOURNAL="${APP_ROOT}/activation.journal"' in source
    assert 'DEPLOY_LOCK="${ACTIVATION_JOURNAL}.lock"' in source
    commands = _manual_commands()
    assert "lock=/opt/acx-backend/app/activation.journal.lock" in commands
    assert commands.index('flock -w "$lock_wait" 9') < commands.index(JOURNAL_GUARD) < commands.index("  ts=")
    backend = _manual_state(tmp_path, "prepared")
    (backend / "app/activation.journal").unlink()
    before = _rollback_tree_state(backend)
    monkeypatch.setenv("APP_DEPLOY_LOCK_WAIT", "1")
    with (backend / "app/activation.journal.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # The helper's five-second process timeout also catches an unbounded flock.
        result = _run_documented_rollback(tmp_path)
    assert result.returncode != 0
    assert "STOP: cannot acquire deployment lock within 1s" in result.stderr
    assert "Selected rollback timestamp" not in result.stdout
    assert _rollback_tree_state(backend) == before
    assert not (tmp_path / "rollback-commands.log").exists()
    unlocked = _run_documented_rollback(tmp_path)
    assert unlocked.returncode == 0, unlocked.stdout + unlocked.stderr
    assert "Selected rollback timestamp: 20" in unlocked.stdout


def _recovery_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mutant: bool = False, checkout: bool = False
) -> None:
    commands = _recovery_commands()
    assert "env -u FRONTEND_DIST" in commands
    # Model the workstation copies: the VM invocation has no repository checkout.
    copied_script = tmp_path / "app-portal-recovery.sh"
    copied_snippet = tmp_path / "app-portal-recovery.Caddyfile.app"
    copied_overlay = tmp_path / "app-portal-recovery.overlay.yml"
    for source, destination in ((SCRIPT, copied_script), (SNIPPET, copied_snippet), (OVERLAY, copied_overlay)):
        destination.write_bytes(source.read_bytes())
    replacements = {
        "/opt/acx-backend": str(tmp_path / "opt/acx-backend"),
        "/tmp/app-portal-recovery.sh": str(SCRIPT if checkout else copied_script),
        "/tmp/app-portal-recovery.Caddyfile.app": str(copied_snippet),
        "/tmp/app-portal-recovery.overlay.yml": str(copied_overlay),
        "/usr/local/bin/app-portal-health-check": str(tmp_path / "bin/health-check"),
    }
    for original, replacement in replacements.items():
        commands = commands.replace(original, replacement)
    if mutant:
        commands = commands.replace("env -u FRONTEND_DIST", "env")
    wrapper = tmp_path / "documented-recovery.sh"
    _write_executable(wrapper, "#!/bin/bash\n" + commands)
    # Replace only the harness entry point; the wrapper invokes the unchanged copied script.
    monkeypatch.setattr(deploy_helpers, "SCRIPT", wrapper)


@pytest.mark.parametrize("phase", ["prepared", "overlay_promoted", "restored"])
def test_exact_vm_recovery_runs_first_without_redeploying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    first = _run(tmp_path, args=["--apply"], extra_env={"BASH_ENV": ""})
    assert first.returncode == 0, first.stdout + first.stderr
    backend = tmp_path / "opt/acx-backend"
    live = backend / "Caddyfile"
    app = backend / "app"
    rollback = app / "rollback"
    first_set = _rollback_tree_state(rollback)
    first_stamp = next(rollback.glob("Caddyfile.*")).name.split(".")[1]
    live_before = live.read_bytes()
    inode_before = live.stat().st_ino
    www_before = {str(p.relative_to(app / "www")): p.read_bytes() for p in (app / "www").rglob("*") if p.is_file()}
    overlay_before = (app / "docker-compose.app.yml").read_bytes()
    kill_hook = tmp_path / "interrupt-overlay.sh"
    _write_executable(
        kill_hook,
        "sync() {\n"
        '  /bin/sync "$@" || return $?\n'
        '  if [ "${@: -1}" = "$APP_ROOT" ] && [ -f "$ACTIVATION_JOURNAL" ] && '
        f'grep -qx "phase={phase}" "$ACTIVATION_JOURNAL"; then\n'
        '    kill -KILL "$BASHPID"\n'
        "  fi\n}\n",
    )
    replacement = _write_frontend(tmp_path / "replacement", index=_frontend_index("replacement"))
    second_env = {"BASH_ENV": str(kill_hook), "APP_UPSTREAM": "replacement-api:8000"}
    if phase == "restored":
        failed_health = tmp_path / "failed-health"
        _write_executable(failed_health, "#!/bin/sh\nexit 1\n")
        second_env["APP_HEALTH_CMD"] = str(failed_health)
    second = _run(
        tmp_path,
        args=["--apply"],
        frontend=replacement,
        live_caddy=live,
        extra_env=second_env,
    )
    assert second.returncode == -9, second.stdout + second.stderr
    assert f"phase={phase}\n" in (app / "activation.journal").read_text()
    if phase == "overlay_promoted":
        assert live.read_bytes() != live_before
    before_log = _log(tmp_path)
    _recovery_wrapper(tmp_path, monkeypatch)
    # Deliberately inherit a valid build: env -u must prevent the implicit redeploy.
    recovered = _run(tmp_path, frontend=replacement, live_caddy=live, extra_env={"BASH_ENV": ""})
    assert recovered.returncode == 2, recovered.stdout + recovered.stderr
    assert "recovering interrupted activation" in recovered.stdout
    assert recovered.stderr.strip() == "ERROR: FRONTEND_DIST is required for --apply"
    assert not (app / "activation.journal").exists()
    assert not (app / "activation.journal").is_symlink()
    assert live.read_bytes() == live_before and live.stat().st_ino == inode_before
    assert {
        str(p.relative_to(app / "www")): p.read_bytes() for p in (app / "www").rglob("*") if p.is_file()
    } == www_before
    assert (app / "docker-compose.app.yml").read_bytes() == overlay_before
    assert _rollback_tree_state(rollback) == first_set, "recovery deleted earlier set or staged a new deploy"
    assert _log(tmp_path)[len(before_log) :].count(" reload ") == (0 if phase == "restored" else 1)
    manual = _run_documented_rollback(tmp_path)
    assert manual.returncode == 0, manual.stdout + manual.stderr
    assert f"Selected rollback timestamp: {first_stamp}" in manual.stdout
    assert not (app / "www").exists() and not (app / "docker-compose.app.yml").exists()
    assert live.stat().st_ino == inode_before


@pytest.mark.parametrize("mutant", [False, True])
def test_env_unset_prevents_redeploy_even_with_vm_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutant: bool
) -> None:
    first = _run(tmp_path, args=["--apply"], extra_env={"BASH_ENV": ""})
    assert first.returncode == 0, first.stdout + first.stderr
    # Give both variants the same full checkout: missing deploy-only repository
    # helpers must not mask the env-unset mutant's accidental redeploy.
    _recovery_wrapper(tmp_path, monkeypatch, mutant=mutant, checkout=True)
    result = _run(tmp_path, extra_env={"BASH_ENV": ""})
    if mutant:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "FRONTEND_DIST is required" not in result.stderr
        assert _log(tmp_path).count(" reload ") == 2, "mutant must demonstrate the unwanted redeploy"
    else:
        assert result.returncode == 2, result.stdout + result.stderr
        assert result.stderr.strip() == "ERROR: FRONTEND_DIST is required for --apply"
        assert _log(tmp_path).count(" reload ") == 1


def test_recovery_copy_and_bindings_match_source_flow() -> None:
    source = SCRIPT.read_text()
    commands = _recovery_commands()
    argv = shlex.split(commands.replace("\\\n", ""))
    assert argv[:3] == ["env", "-u", "FRONTEND_DIST"]
    assert argv[-3:] == ["bash", "/tmp/app-portal-recovery.sh", "--apply"]
    assert "FRONTEND_DIST=" not in commands
    for binding in (
        "APP_ROOT=/opt/acx-backend/app",
        "APP_WWW=/opt/acx-backend/app/www",
        "CADDYFILE=/opt/acx-backend/Caddyfile",
        "CADDY_COMPOSE=/opt/acx-backend/docker-compose.caddy.yml",
        "APP_OVERLAY=/tmp/app-portal-recovery.overlay.yml",
    ):
        assert binding in argv
    section = RUNBOOK.read_text().split("### Recover an interrupted frontend activation", 1)[1]
    copies = section.split("```bash\n", 1)[1].split("```", 1)[0]
    for local, remote in (
        ("scripts/deploy/app-portal.sh", "/tmp/app-portal-recovery.sh"),
        ("infra/oci/app/Caddyfile.app", "/tmp/app-portal-recovery.Caddyfile.app"),
        ("infra/oci/app/docker-compose.app.yml", "/tmp/app-portal-recovery.overlay.yml"),
    ):
        assert (REPO_ROOT / local).is_file()
        assert f"scp {local} acx-backend:{remote}" in copies
    # Source-backed order: recovery is invoked before missing-build refusal and staging.
    recovery = source.index("if ! recover_interrupted_activation; then")
    missing_dist = source.index('refuse "FRONTEND_DIST is required for --apply"')
    assert recovery < missing_dist < source.index('cp -a "${FRONTEND_DIST}/."')
    cleanup = source.split("finish_activation_rollback() {", 1)[1].split("\n}", 1)[0]
    assert cleanup.index("write_activation_journal restored") < cleanup.index("rm -rf --")
    assert cleanup.index('sync_path "$ROLLBACK_DIR"') < cleanup.index("clear_activation_journal")


def test_every_runbook_bash_block_parses() -> None:
    blocks = re.findall(r"```bash\n(.*?)```", RUNBOOK.read_text(), re.DOTALL)
    assert blocks
    for index, commands in enumerate(blocks):
        result = subprocess.run(["bash", "-n"], input=commands, capture_output=True, text=True, check=False, timeout=5)
        assert result.returncode == 0, f"bash block {index}: {result.stderr}"
