"""E15-33 Slice 3: deploy-time compose+unit convergence contract.

`recognition-service.sh deploy <env>` must converge the deployed
`docker-compose.env.yml` + systemd unit with the repo (or fail), instead of
restarting the image against whatever compose/unit already sit on the VM. A
read-only `deploy <env> --check` reports drift without mutating. The Caddy edge
is deliberately NOT reshipped here (E15-29 hazard: a Caddy restart can drop it
off acx-demo-net) — it stays owned by sync-compose.sh / sync-demo.sh.

Structural assertions parse the script; behavioral ones run it with fake
ssh/scp on PATH so no VM is required.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
SCRIPT_TEXT = SCRIPT.read_text()


def _fake_ssh_bin(tmp_path: Path) -> Path:
    """A bin dir whose `ssh` succeeds with empty stdout and `scp` records a call.

    Empty `ssh` stdout makes the drift diff in --check see "deployed != repo",
    and the scp marker lets a test assert --check never mutates the VM.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text("#!/bin/sh\nexit 0\n")
    marker = tmp_path / "scp-was-called"
    (bindir / "scp").write_text(f"#!/bin/sh\necho called >> {marker}\nexit 0\n")
    for name in ("ssh", "scp"):
        (bindir / name).chmod(0o755)
    return bindir


def _run(args: list[str], tmp_path: Path, extra_env: dict[str, str] | None = None):
    env = {k: v for k, v in os.environ.items() if k != "CONFIRM"}
    env["PATH"] = f"{_fake_ssh_bin(tmp_path)}:{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


# ---- structural contract ------------------------------------------------


def test_defines_converge_functions() -> None:
    assert "converge_runtime()" in SCRIPT_TEXT
    assert "converge_check()" in SCRIPT_TEXT
    assert "render_unit()" in SCRIPT_TEXT


def test_convergence_gated_by_env_flag_default_on() -> None:
    # Default-on: image-only restart only when ACX_CONVERGE_RUNTIME=0.
    assert "ACX_CONVERGE_RUNTIME:-1" in SCRIPT_TEXT


def test_converge_runs_before_restart_in_deploy() -> None:
    deploy = SCRIPT_TEXT.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    assert "converge_runtime" in deploy
    assert deploy.index("converge_runtime") < deploy.index("do_restart"), (
        "converge_runtime must run before the image restart"
    )


def test_caddy_edge_not_reshipped_by_converge() -> None:
    # The converge path must not touch the Caddy edge (carve-out).
    start = SCRIPT_TEXT.index("converge_runtime()")
    end = SCRIPT_TEXT.index("converge_check()")
    converge_body = SCRIPT_TEXT[start:end]
    for caddy_token in ("Caddyfile", "docker-compose.caddy.yml", "acx-caddy"):
        assert caddy_token not in converge_body, f"converge_runtime must not reship {caddy_token}"


# ---- behavioral (hermetic) ---------------------------------------------


def test_check_unknown_env_fails_fast() -> None:
    # Env validated before any network; unknown env fails with a clear message.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        result = _run(["deploy", "bogus", "--check"], Path(d))
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Unknown env" in combined


def test_check_reports_drift_without_mutating(tmp_path: Path) -> None:
    result = _run(["deploy", "prod", "--check"], tmp_path)
    combined = result.stdout + result.stderr
    # Deployed compose is empty (fake ssh) → drift detected → non-zero exit.
    assert result.returncode != 0
    assert "drift" in combined.lower()
    # Read-only: --check must never scp anything to the VM.
    assert not (tmp_path / "scp-was-called").exists(), "--check must not mutate the VM"


def test_check_does_not_require_promote_confirm(tmp_path: Path) -> None:
    # --check is read-only, so it must not demand CONFIRM=PROMOTE for prod.
    result = _run(["deploy", "prod", "--check"], tmp_path)
    combined = result.stdout + result.stderr
    assert "CONFIRM=PROMOTE" not in combined
