from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"


def _run(
    args: list[str], env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    # Strip prod confirmation + remote-build flag so tests start from a clean slate.
    env.pop("CONFIRM", None)
    env.pop("CONFIRM_REMOTE_RESET", None)
    env.pop("ACX_RESET_DRY_RUN", None)
    env.pop("REMOTE_BUILD", None)
    env.pop("ACX_REMOTE_BUILD", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_reset_without_env_fails_with_usage() -> None:
    result = _run(["reset"])
    assert result.returncode != 0
    assert (
        "reset requires <env>" in result.stderr
        or "reset requires <env>" in result.stdout
    )


def test_reset_with_unknown_env_fails() -> None:
    result = _run(["reset", "bogus"])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Unknown env" in combined


def test_reset_dev_without_confirmation_fails_and_names_lever() -> None:
    result = _run(["reset", "dev"])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "CONFIRM_REMOTE_RESET=RESET" in combined


def test_reset_prod_with_reset_confirm_but_no_promote_confirm_fails() -> None:
    result = _run(
        ["reset", "prod"],
        env_overrides={"CONFIRM_REMOTE_RESET": "RESET"},
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "CONFIRM=PROMOTE" in combined


def test_reset_dev_dry_run_with_confirmation_succeeds_and_summarizes_plan() -> None:
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "DRY-RUN" in out or "dry-run" in out
    assert "acx-dev" in out
    assert "/opt/acx-backend/dev" in out
    assert "https://dev.api.altcontext.com/ready" in out


def test_reset_prod_dry_run_with_both_confirmations_succeeds() -> None:
    result = _run(
        ["reset", "prod"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "CONFIRM": "PROMOTE",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "acx-prod" in out
    assert "https://api.altcontext.com/ready" in out


def test_reset_dev_dry_run_prints_canonical_remote_command_sequence() -> None:
    """The dry-run must print the exact remote shell sequence the operator can audit
    before allowing the destructive run. This is the verification surface for slice 2c
    since we cannot exercise the actual SSH path from CI."""
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # SSH target named (default OCI host or override echoed back)
    assert "ssh " in out or "SSH target" in out
    # Stop, clear, and start verbs visible in the remote command shape
    assert "systemctl stop acx-dev" in out
    assert "docker compose" in out and "down" in out
    assert "systemctl start acx-dev" in out
    # PGDATA reset boundary named explicitly
    assert "ACX_PGDATA_PATH" in out
    # Working directory for the remote compose project
    assert "/opt/acx-backend/dev" in out


def test_reset_dev_dry_run_does_not_open_ssh_connection() -> None:
    """The dry-run path must not actually invoke ssh — it announces what it would
    do and exits 0 cleanly."""
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            # If any code path tried to ssh, this fake host would fail loudly.
            "OCI_HOST": "definitely-not-a-real-host.invalid",
            "OCI_USER": "nobody",
        },
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    # No connection attempts surfaced.
    assert "Connection" not in combined
    assert "Could not resolve" not in combined
    # And the dry-run still echoes the configured target so operators can review it.
    assert "definitely-not-a-real-host.invalid" in combined
