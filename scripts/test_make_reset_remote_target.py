from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_make(
    args: list[str], env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    for key in (
        "CONFIRM",
        "CONFIRM_REMOTE_RESET",
        "ACX_RESET_DRY_RUN",
        "ACX_RESET_SITE_URL",
        "ACX_RESET_TENANT_ID",
        "ENV",
    ):
        env.pop(key, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["make", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_reset_remote_target_is_listed_in_deploy_help() -> None:
    result = _run_make(["deploy-help"])
    assert result.returncode == 0, result.stderr
    assert "reset-remote" in result.stdout
    assert "CONFIRM_REMOTE_RESET=RESET" in result.stdout


def test_reset_remote_without_env_fails_with_usage() -> None:
    result = _run_make(["reset-remote"])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "ENV" in combined


def test_reset_remote_dev_dry_run_succeeds_and_summarizes_plan() -> None:
    result = _run_make(
        ["reset-remote", "ENV=dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "https://dev.altcontext.local",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "DRY-RUN" in out or "dry-run" in out
    assert "acx-dev" in out
    assert "https://dev.api.altcontext.com/ready" in out


def test_reset_remote_dev_dry_run_without_site_url_fails_closed() -> None:
    """E15-12-BR-06: reset must fail when ACX_RESET_SITE_URL is missing."""
    result = _run_make(
        ["reset-remote", "ENV=dev"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
        },
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "ACX_RESET_SITE_URL" in combined


def test_reset_remote_prod_dry_run_requires_both_confirmations() -> None:
    result = _run_make(
        ["reset-remote", "ENV=prod"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "https://altcontext.com",
        },
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "CONFIRM=PROMOTE" in combined


def test_reset_remote_prod_dry_run_with_both_confirmations_succeeds() -> None:
    result = _run_make(
        ["reset-remote", "ENV=prod"],
        env_overrides={
            "CONFIRM_REMOTE_RESET": "RESET",
            "CONFIRM": "PROMOTE",
            "ACX_RESET_DRY_RUN": "1",
            "ACX_RESET_SITE_URL": "https://altcontext.com",
        },
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "acx-prod" in out
    assert "https://api.altcontext.com/ready" in out
