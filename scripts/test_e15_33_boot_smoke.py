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
import re
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
    # INT-01 / H2 invariant: Gate 2 keeps the real image CMD (entrypoint migrate
    # + schema verify) but the smoke container's DB target must be provably not
    # the deployed/prod database. Assert the override, not entrypoint spelling.
    body = _fn_body("do_boot_smoke")
    # Real entrypoint retained (D4) — no uvicorn-only entrypoint override.
    assert "--entrypoint sh" not in body
    # Ephemeral throwaway Postgres for smoke migrations only.
    assert "acx-smoke-pg-" in body
    assert "pgvector/pgvector" in body
    # Explicit DSN overrides on the smoke container (beat --env-file).
    assert "POSTGRES_DSN=" in body
    assert "POSTGRES_SYNC_DSN=" in body
    # Host is the throwaway container, not a prod/service hostname from .env.
    assert "PGHOST=" in body and "${pg_name}" in body
    # Force env secret backend so oci_vault cannot inject live prod DSN.
    assert "RECOGNITION_SECRET_BACKEND=env" in body
    # DSN literals must not point at the live compose postgres service name.
    assert "@postgres:" not in body
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
        assert body.index("promote_gate") < body.index("do_restart"), f"{name} must gate before the live restart"


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
    return subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=30).returncode


def test_boot_smoke_returns_nonzero_when_import_smoke_fails(tmp_path: Path) -> None:
    assert _run_boot_smoke(tmp_path, fail_import=True) == 1


def test_boot_smoke_returns_zero_when_ssh_ok(tmp_path: Path) -> None:
    assert _run_boot_smoke(tmp_path, fail_import=False) == 0


def test_rollback_tag_preserved_even_when_smoke_bypassed(tmp_path: Path) -> None:
    # BR2-03: ACX_BOOT_SMOKE=0 must not silently skip rollback-tag creation.
    # Stub ship_remote_image_repo_env too — promote_gate always ships ACX_IMAGE_REPO and
    # must not open a real ssh session in this hermetic unit test.
    marker = tmp_path / "calls.log"
    script = (
        f'source "{SCRIPT}"; '
        f'preserve_rollback_tag() {{ echo "rollback $1" >> "{marker}"; }}; '
        f'do_boot_smoke() {{ echo "smoke $1" >> "{marker}"; }}; '
        f'ship_remote_image_repo_env() {{ echo "ship $1" >> "{marker}"; }}; '
        f'converge_runtime() {{ echo "converge $1" >> "{marker}"; }}; '
        "ACX_BOOT_SMOKE=0 promote_gate prod img:cand"
    )
    rc = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=30).returncode
    assert rc == 0
    calls = marker.read_text().splitlines() if marker.exists() else []
    assert "rollback prod" in calls, calls
    assert "smoke prod" not in calls


# ---- SMOKE heredoc body (hermetic, gate 2) ------------------------------

FAKE_DOCKER = """#!/bin/sh
echo "docker $@" >> "$FAKE_LOG"
case "$1" in
  port) echo "0.0.0.0:12345" ;;
esac
exit 0
"""

# Full 7-arg vector matching do_boot_smoke's bash -s invocation:
#   env image remote_dir budget_s poll_s attempts vlm_budget
# Small deterministic values so health-fail path completes quickly.
_SMOKE_HARNESS_ARGS_TAIL = ("4", "1", "2", "0")  # budget_s, poll_s, attempts, vlm_budget

# S2-A-08: the smoke body fails closed without this key, so every fixture that
# expects to reach `docker run` must supply it.
_MODELS_PATH_LINE = "ACX_MODELS_PATH=/opt/acx-models\n"


def _highest_positional_deref(body: str) -> int:
    """Highest $N the heredoc body dereferences (for arity drift guard)."""
    nums = [int(n) for n in re.findall(r"\$([1-9][0-9]*)\b", body)]
    return max(nums) if nums else 0


def _run_smoke_heredoc(tmp_path: Path, *, env_lines: str, curl_ok: bool) -> tuple[int, str]:
    # BR2-06 / INT-03: execute the remote SMOKE body itself with fake docker/curl/sleep.
    # Must pass the full 7-arg vector — under set -euo pipefail, missing $4..$7 aborts
    # before docker is ever invoked (dead-red behavioural gates).
    body = SCRIPT_TEXT.split("<<'SMOKE'\n", 1)[1].split("\nSMOKE\n", 1)[0]
    max_n = _highest_positional_deref(body)
    smoke = tmp_path / "smoke.sh"
    smoke.write_text(body + "\n")
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir / ".env").write_text(env_lines)
    log = tmp_path / "docker.log"
    log.write_text("")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER)
    (bindir / "curl").write_text(f"#!/bin/sh\nexit {0 if curl_ok else 1}\n")
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for f in ("docker", "curl", "sleep"):
        (bindir / f).chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    harness_args = ["prod", "img:cand", str(remote_dir), *_SMOKE_HARNESS_ARGS_TAIL]
    assert len(harness_args) >= max_n, (
        f"smoke harness passes {len(harness_args)} args but heredoc dereferences "
        f"${max_n}; cannot silently drift (INT-03)"
    )
    proc = subprocess.run(
        ["/bin/bash", str(smoke), *harness_args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, log.read_text()


def test_smoke_harness_arity_covers_heredoc_positionals() -> None:
    """INT-03: harness arg count must stay >= highest $N the SMOKE body uses."""
    body = SCRIPT_TEXT.split("<<'SMOKE'\n", 1)[1].split("\nSMOKE\n", 1)[0]
    max_n = _highest_positional_deref(body)
    # 3 fixed (env/image/remote_dir) + len(_SMOKE_HARNESS_ARGS_TAIL)
    harness_n = 3 + len(_SMOKE_HARNESS_ARGS_TAIL)
    assert max_n >= 7, f"expected 7-arg SMOKE body, highest $N is {max_n}"
    assert harness_n >= max_n, (
        f"harness supplies {harness_n} args but body needs ${max_n}"
    )


def test_smoke_body_defaults_network_when_env_key_missing(tmp_path: Path) -> None:
    # BR2-07: no ACX_NETWORK_NAME line must not abort under pipefail; the
    # acx-<env>-net fallback must be reachable.
    rc, log = _run_smoke_heredoc(
        tmp_path, env_lines=f"OTHER=1\n{_MODELS_PATH_LINE}", curl_ok=True
    )
    assert rc == 0
    assert "--network acx-prod-net" in log


def test_smoke_body_fails_closed_when_models_path_missing(tmp_path: Path) -> None:
    # S2-A-08: compose has no default for the :ro model-cache bind, so an .env
    # without ACX_MODELS_PATH cannot start the real stack. Smoke must refuse
    # BEFORE starting the api container rather than go green on it.
    rc, log = _run_smoke_heredoc(tmp_path, env_lines="OTHER=1\n", curl_ok=True)
    assert rc != 0, "smoke must fail closed without ACX_MODELS_PATH"
    assert not re.search(r"^docker run .*--name acx-smoke-prod-", log, re.MULTILINE), (
        f"guard must refuse before starting the api container; docker log was:\n{log}"
    )


def test_smoke_body_fails_and_tears_down_when_health_never_answers(tmp_path: Path) -> None:
    # BR2-06 / HARM-A-01: gate 2 must exit non-zero when /health never answers,
    # and the EXIT trap must reap the api container, ephemeral Postgres, and
    # the smoke blob volume — not just the api container.
    rc, log = _run_smoke_heredoc(
        tmp_path,
        env_lines=f"ACX_NETWORK_NAME=acx-x\n{_MODELS_PATH_LINE}",
        curl_ok=False,
    )
    assert rc == 1
    # Require trap *rm* lines, not mere create/run mentions of the same names.
    assert re.search(r"docker rm -f acx-smoke-prod-", log), (
        f"EXIT trap must docker rm the api smoke container; log:\n{log}"
    )
    assert re.search(r"docker rm -f acx-smoke-pg-", log), (
        "EXIT trap must docker rm the ephemeral Postgres (acx-smoke-pg-*); "
        f"docker log was:\n{log}"
    )
    assert re.search(r"docker volume rm(?: -f)? acx-smoke-blobs-", log) or (
        "volume rm" in log and "acx-smoke-blobs-" in log
    ), (
        "EXIT trap must docker volume rm the smoke blob volume "
        f"(acx-smoke-blobs-*); docker log was:\n{log}"
    )


def test_promote_gate_failure_blocks_converge_and_restart(tmp_path: Path) -> None:
    # BR2-09: a failing smoke must abort promote_gate (non-zero) BEFORE
    # converge/restart/push run — behaviorally, not just by source ordering.
    marker = tmp_path / "calls.log"
    script = (
        f'source "{SCRIPT}"; '
        f'preserve_rollback_tag() {{ echo "rollback $1" >> "{marker}"; }}; '
        f"do_boot_smoke() {{ return 1; }}; "
        f'converge_runtime() {{ echo "converge $1" >> "{marker}"; }}; '
        "promote_gate prod img:cand"
    )
    proc = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=30)
    calls = marker.read_text().splitlines() if marker.exists() else []
    assert proc.returncode != 0
    assert "converge prod" not in calls, calls
