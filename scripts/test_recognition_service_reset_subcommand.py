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


def test_reset_dev_dry_run_includes_ready_verification_and_bootstrap_steps() -> None:
    """Slice 2d: dry-run must surface the post-reset bootstrap command and the
    /ready verification curl so the operator can audit both before a real run."""
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # /ready verification curl, not just /health
    assert "curl" in out
    assert "https://dev.api.altcontext.com/ready" in out
    # Bootstrap step references the canonical credential-recreation entry point.
    assert "manage_api_keys" in out
    assert "create" in out


def test_reset_dev_dry_run_bootstrap_uses_canonical_cli_contract() -> None:
    """Slice 3 / E15-12-BR-03: the bootstrap shape must match the real
    manage_api_keys.py CLI contract.

    The earlier slice-2d implementation used flags that do not exist
    (--tenant-id, --name) and omitted the mandatory top-level --env, which
    would make the destructive reset path unrecoverable: postgres wiped, then
    the bootstrap exits with argparse usage error and the operator is left
    without a service-mode key.

    Real contract (apps/prototype-description-service/scripts/manage_api_keys.py):
        python -m scripts.manage_api_keys --env {prod,dev,local} \
            tenant create --tenant <uuid> --site-url <url>
        python -m scripts.manage_api_keys --env {prod,dev,local} \
            create --tenant <uuid>
    """
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    # Mandatory top-level env flag with a valid choice.
    assert "--env prod" in out or "--env dev" in out or "--env local" in out, (
        "bootstrap is missing the mandatory --env flag from manage_api_keys CLI"
    )

    # Tenant bootstrap (idempotent) before key creation.
    assert "tenant create" in out, (
        "bootstrap must run `tenant create` before `create` so the FK exists"
    )
    assert "--site-url" in out, "tenant create requires --site-url per the CLI contract"

    # Key creation uses --tenant <uuid>, NOT --tenant-id, and there is no --name.
    assert "--tenant " in out, "create must use --tenant <uuid>, not --tenant-id"
    assert "--tenant-id" not in out, (
        "the CLI has no --tenant-id flag; use --tenant <uuid>"
    )
    assert "--name " not in out, (
        "the CLI has no --name flag; remove it from the bootstrap command"
    )

    # The OCI postgres lives inside the compose project on the remote VM. The
    # bootstrap must run there (via docker compose exec or equivalent), not
    # locally, because the local DSN points at the operator's laptop DB.
    assert "docker compose" in out and "exec" in out, (
        "bootstrap must run inside the api container on the remote VM "
        "(the local DSN is not the OCI db that was just reset)"
    )


def test_reset_dev_dry_run_bootstrap_redirects_exec_stdin() -> None:
    """E15-12-BR-05: each `docker compose exec -T` line in the bootstrap
    must redirect its stdin from /dev/null.

    The bootstrap is delivered to the remote shell via
    `ssh ... bash -s <<<"${bootstrap_cmd}"`. Without `< /dev/null` on each
    `exec -T` invocation, the first exec call reads from bash's stdin and
    consumes the remaining bootstrap lines, so the second exec — the one
    that prints the `api_key=` line — silently never runs.

    This was caught against a real `make reset-remote ENV=dev` on
    2026-05-02: tenant create succeeded, key create did not, and the
    operator was left with no way to authenticate the plugin against the
    freshly reset env.
    """
    result = _run(
        ["reset", "dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    exec_lines = [
        line
        for line in out.splitlines()
        if "docker compose" in line and "exec -T" in line
    ]
    assert len(exec_lines) >= 2, (
        f"expected at least two `docker compose exec -T` lines (tenant + "
        f"key create); got {len(exec_lines)}: {exec_lines!r}"
    )
    for line in exec_lines:
        assert "< /dev/null" in line, (
            "bootstrap exec line must redirect stdin from /dev/null so the "
            "first exec does not swallow the remaining bootstrap heredoc "
            f"lines (E15-12-BR-05); offender: {line!r}"
        )


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
