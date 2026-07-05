"""E15-33 Slice 4: pre-promote boot smoke + rollback contract.

`recognition-service.sh` must boot the freshly-built image in a throwaway
container BEFORE the live restart, so a bad image aborts the deploy with prod
still serving the old image; a rollback tag is preserved first. Both do_deploy
and do_promote route through the shared `promote_gate`, so the prod path is
uniform.

Structural assertions parse the script; the two execution tests source the
script and run `do_boot_smoke` with fake `ssh` on PATH (no VM required).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
SCRIPT_TEXT = SCRIPT.read_text()

# A fake ssh: fails the import-smoke command when FAKE_FAIL_IMPORT is set,
# succeeds otherwise; always drains heredoc stdin so gate 2 does not hang.
FAKE_SSH = """#!/bin/sh
for a in "$@"; do
  case "$a" in
    *"import api.main"*) [ -n "$FAKE_FAIL_IMPORT" ] && exit 1 ;;
  esac
done
cat >/dev/null 2>&1 || true
exit 0
"""


def _fn_body(name: str) -> str:
    start = SCRIPT_TEXT.index(f"{name}()")
    end = SCRIPT_TEXT.index("\n}\n", start)
    return SCRIPT_TEXT[start:end]


def _deploy_body() -> str:
    return SCRIPT_TEXT.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]


def _promote_body() -> str:
    return SCRIPT_TEXT.split("do_promote()", 1)[1].split("\ndo_verify()", 1)[0]


# ---- structural contract ------------------------------------------------


def test_defines_smoke_rollback_and_gate() -> None:
    assert "do_boot_smoke()" in SCRIPT_TEXT
    assert "preserve_rollback_tag()" in SCRIPT_TEXT
    assert "promote_gate()" in SCRIPT_TEXT


def test_boot_smoke_runs_import_and_health_and_is_throwaway() -> None:
    body = _fn_body("do_boot_smoke")
    assert "import api.main" in body
    assert "/health" in body
    assert "--rm" in body


def test_boot_smoke_full_probe_does_not_migrate_prod_db() -> None:
    # H2 fix: the full-boot probe overrides the entrypoint to uvicorn-only, so it
    # never runs `alembic upgrade head`/create_all against the live prod DB.
    body = _fn_body("do_boot_smoke")
    assert "--entrypoint sh" in body and "uvicorn api.main:app" in body
    assert "alembic" not in body, "smoke must not run migrations against prod"
    # Network is read (grep), not bash-sourced from the docker env-file.
    assert "grep -E '^ACX_NETWORK_NAME=" in body
    assert ". ./.env" not in body


def test_gate_gated_by_env_flag_default_on() -> None:
    assert "ACX_BOOT_SMOKE:-1" in _fn_body("promote_gate")


def test_gate_runs_smoke_and_rollback_before_converge() -> None:
    gate = _fn_body("promote_gate")
    assert gate.index("preserve_rollback_tag") < gate.index("do_boot_smoke")
    assert gate.index("do_boot_smoke") < gate.index("converge_runtime")


def test_smoke_failure_aborts_the_gate() -> None:
    gate = _fn_body("promote_gate")
    assert "if ! do_boot_smoke" in gate and "fail " in gate


def test_both_deploy_and_promote_gate_before_restart() -> None:
    for name, body in (("do_deploy", _deploy_body()), ("do_promote", _promote_body())):
        assert "promote_gate" in body, f"{name} must run promote_gate"
        assert body.index("promote_gate") < body.index("do_restart"), (
            f"{name} must gate before the live restart"
        )


def test_rollback_tag_uses_rollback_prefix() -> None:
    assert "rollback-" in _fn_body("preserve_rollback_tag")


def test_env_tag_promoted_after_smoke_in_deploy() -> None:
    # BR-04: :sha pushed before the gate, env tag (:latest) only after it passes.
    body = _deploy_body()
    assert body.index("do_push_sha") < body.index("promote_gate") < body.index("do_push_tag")


# ---- behavioral (hermetic, sourced) ------------------------------------


def _run_boot_smoke(tmp_path: Path, *, fail_import: bool) -> int:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text(FAKE_SSH)
    (bindir / "ssh").chmod(0o755)
    (bindir / "scp").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "scp").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    if fail_import:
        env["FAKE_FAIL_IMPORT"] = "1"
    script = f'source "{SCRIPT}"; if do_boot_smoke prod "img:candidate"; then exit 0; else exit $?; fi'
    return subprocess.run(
        ["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=30
    ).returncode


def test_boot_smoke_returns_nonzero_when_import_smoke_fails(tmp_path: Path) -> None:
    assert _run_boot_smoke(tmp_path, fail_import=True) == 1


def test_boot_smoke_returns_zero_when_ssh_ok(tmp_path: Path) -> None:
    assert _run_boot_smoke(tmp_path, fail_import=False) == 0
