"""E15-33 Slice 4: pre-promote boot smoke contract.

`recognition-service.sh deploy <env>` must boot the freshly-built :SHA image in a
throwaway container BEFORE the live restart, so a bad image (missing package,
import error, failed boot) aborts the deploy with prod still serving the old
image. A rollback tag is preserved before the promote.

These are structural assertions over the script; the live smoke behavior (bad
build aborts, prod stays green) is proven on the VM.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
SCRIPT_TEXT = SCRIPT.read_text()


def _deploy_body() -> str:
    return SCRIPT_TEXT.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]


def test_defines_boot_smoke_and_rollback_functions() -> None:
    assert "do_boot_smoke()" in SCRIPT_TEXT
    assert "preserve_rollback_tag()" in SCRIPT_TEXT


def test_boot_smoke_runs_import_and_health_checks() -> None:
    start = SCRIPT_TEXT.index("do_boot_smoke()")
    end = SCRIPT_TEXT.index("do_restart()", start)
    body = SCRIPT_TEXT[start:end]
    assert "import api.main" in body, "boot smoke must run the import smoke"
    assert "/health" in body, "boot smoke must probe /health"
    assert "--rm" in body, "smoke must use a throwaway container"


def test_boot_smoke_gated_by_env_flag_default_on() -> None:
    assert "ACX_BOOT_SMOKE:-1" in SCRIPT_TEXT


def test_smoke_and_rollback_run_before_restart() -> None:
    body = _deploy_body()
    assert "do_boot_smoke" in body
    assert "preserve_rollback_tag" in body
    assert body.index("preserve_rollback_tag") < body.index("do_boot_smoke")
    assert body.index("do_boot_smoke") < body.index("do_restart"), (
        "boot smoke must run before the live restart"
    )


def test_smoke_failure_aborts_before_restart() -> None:
    body = _deploy_body()
    # The smoke must be a hard gate: a non-zero result fails the deploy.
    smoke_call = body.index("do_boot_smoke")
    guard = body[smoke_call - 40 : smoke_call + 200]
    assert "if !" in guard and "fail " in body[smoke_call:smoke_call + 260], (
        "a failing boot smoke must call fail (abort) before do_restart"
    )


def test_rollback_tag_uses_rollback_prefix() -> None:
    start = SCRIPT_TEXT.index("preserve_rollback_tag()")
    end = SCRIPT_TEXT.index("do_boot_smoke()", start)
    assert "rollback-" in SCRIPT_TEXT[start:end]
