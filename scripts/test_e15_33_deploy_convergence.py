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


def test_converge_runs_before_restart_via_gate() -> None:
    # Convergence now runs inside promote_gate; do_deploy must gate before restart.
    deploy = SCRIPT_TEXT.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    assert deploy.index("promote_gate") < deploy.index("do_restart")
    gate = SCRIPT_TEXT.split("promote_gate()", 1)[1].split("\n}\n", 1)[0]
    assert "converge_runtime" in gate


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


# ---- converge_runtime mutation path (hermetic, sourced) -----------------


def _run_converge_runtime(env_arg: str, tmp_path: Path) -> str:
    """Source the script and run `converge_runtime <env>` with recording fakes.

    Returns the recorded ssh/scp command log so tests can assert which files
    were shipped (env compose always, admin overlay only for prod, never Caddy).
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    scp_log = tmp_path / "ship.log"
    (bindir / "ssh").write_text(f'#!/bin/sh\necho "$@" >> {scp_log}\ncat >/dev/null 2>&1 || true\nexit 0\n')
    (bindir / "scp").write_text(f'#!/bin/sh\necho "SCP $@" >> {scp_log}\nexit 0\n')
    for name in ("ssh", "scp"):
        (bindir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    subprocess.run(
        ["/bin/bash", "-c", f'source "{SCRIPT}"; converge_runtime {env_arg}'],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return scp_log.read_text() if scp_log.exists() else ""


def test_converge_runtime_ships_both_compose_files_for_prod(tmp_path: Path) -> None:
    log = _run_converge_runtime("prod", tmp_path)
    assert "sudo cp '/tmp/docker-compose.env.yml'" in log
    assert "sudo cp '/tmp/docker-compose.admin.yml'" in log, "prod must ship the admin overlay"
    assert "SCP " not in log, "compose files must not travel via direct scp (root-owned targets)"
    for caddy in ("Caddyfile", "docker-compose.caddy.yml", "acx-caddy"):
        assert caddy not in log, f"converge_runtime must never ship {caddy}"


def test_converge_runtime_ships_only_env_compose_for_dev(tmp_path: Path) -> None:
    log = _run_converge_runtime("dev", tmp_path)
    assert "sudo cp '/tmp/docker-compose.env.yml'" in log
    assert "docker-compose.admin.yml" not in log, "dev must not ship the admin overlay"


def test_check_passes_clean_when_deployed_matches_repo(tmp_path: Path) -> None:
    # BR2-11: the no-drift branch of converge_check must exit 0 — a fake ssh
    # cats the repo's own compose/admin/rendered-unit content back, so every
    # diff matches.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text(
        """#!/bin/sh
case "$*" in
  *docker-compose.env.yml*) cat "$REPO_ENV_COMPOSE" ;;
  *docker-compose.admin.yml*) cat "$REPO_ADMIN_COMPOSE" ;;
  *.service*) cat "$RENDERED_UNIT" ;;
esac
exit 0
"""
    )
    (bindir / "ssh").chmod(0o755)
    unit_file = tmp_path / "unit.txt"
    script = (
        f'source "{SCRIPT}"; '
        f'render_unit prod > "{unit_file}"; '
        f'export REPO_ENV_COMPOSE="$SERVICE_DIR/docker-compose.env.yml"; '
        f'export REPO_ADMIN_COMPOSE="$SERVICE_DIR/docker-compose.admin.yml"; '
        f'export RENDERED_UNIT="{unit_file}"; '
        "converge_check prod"
    )
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    proc = subprocess.run(
        ["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=30
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "no runtime drift" in combined


def test_converge_ships_compose_files_via_sudo_install(tmp_path: Path) -> None:
    # E15-34-DEPLOYFIX: compose files on the VM can be root-owned (the E15-29
    # admin overlay was installed via sudo), so a plain `scp` to the final path
    # fails with Permission denied. Both compose ships must go through the same
    # /tmp + `sudo cp` pattern the unit file uses.
    body = SCRIPT_TEXT.split("converge_runtime()", 1)[1].split("\n}\n", 1)[0]
    assert 'scp "' not in body, "converge_runtime must not scp directly to the target path"
    # Structural: the shared ship helper stages under /tmp and installs with
    # sudo cp; the behavioral tests above assert the expanded per-file commands.
    assert "sudo cp '/tmp/" in body, "compose ship must go via /tmp + sudo cp"
