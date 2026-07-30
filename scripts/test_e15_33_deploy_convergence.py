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
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
SCRIPT_TEXT = SCRIPT.read_text()
SERVICE_DIR = REPO_ROOT / "apps" / "prototype-description-service"
CADDYFILE = SERVICE_DIR / "Caddyfile"
CADDY_COMPOSE = SERVICE_DIR / "docker-compose.caddy.yml"
ENV_FIR_EXAMPLE = SERVICE_DIR / ".env.fir.example"


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


def _source_env_map(fn: str, env_arg: str) -> str:
    """Invoke an env_to_* helper from recognition-service.sh and return stdout."""
    proc = subprocess.run(
        ["/bin/bash", "-c", f'source "{SCRIPT}"; {fn} {env_arg}'],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_defines_converge_functions() -> None:
    assert "converge_runtime()" in SCRIPT_TEXT
    assert "converge_check()" in SCRIPT_TEXT
    assert "render_unit()" in SCRIPT_TEXT


def test_dev_fir_env_mappings() -> None:
    """FIR23-STACK Slice 1: acx-dev-fir isolated FIR/SFace stack identity."""
    assert _source_env_map("env_to_tag", "dev-fir") == "dev"
    assert _source_env_map("env_to_unit", "dev-fir") == "acx-dev-fir"
    assert _source_env_map("env_to_remote_dir", "dev-fir") == "/opt/acx-backend/dev-fir"
    assert (
        _source_env_map("env_to_health_url", "dev-fir")
        == "https://fir.dev.api.altcontext.com/health"
    )
    assert (
        _source_env_map("env_to_ready_url", "dev-fir")
        == "https://fir.dev.api.altcontext.com/ready"
    )
    assert (
        _source_env_map("env_to_compose_files", "dev-fir")
        == "-f docker-compose.env.yml"
    )


def _parse_env_example_key(text: str, key: str) -> str:
    """Return the value of KEY= from a dotenv-style file (first match)."""
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise AssertionError(f"{key} not found in env example")


def _caddy_site_block_for_host(caddyfile: str, host: str) -> str:
    """Extract the Caddy site block whose address list includes host.

    Fails if no site address line names the host (vhost missing).
    """
    lines = caddyfile.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Site address lines end with "{" and list hosts (comma-separated).
        if stripped.endswith("{"):
            addresses = stripped[:-1].strip()
            host_tokens = [h.strip() for h in addresses.split(",")]
            if host in host_tokens:
                start = i
                break
    assert start is not None, f"Caddyfile has no vhost for host {host!r}"
    depth = 0
    block_lines: list[str] = []
    for line in lines[start:]:
        block_lines.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            break
    return "\n".join(block_lines)


def test_dev_fir_ready_url_routable_via_caddy() -> None:
    """Ready URL host must be a Caddy vhost whose upstream network Caddy joins.

    Host is taken from env_to_ready_url (script); network from .env.fir.example
    (ACX_NETWORK_NAME). Neither is hard-coded as a parallel expected string, so
    a missing vhost or missing network attachment fails this test (C1+C3).
    """
    ready_url = _source_env_map("env_to_ready_url", "dev-fir")
    host = urlparse(ready_url).hostname
    assert host, f"could not parse host from ready URL {ready_url!r}"

    caddyfile = CADDYFILE.read_text()
    site_block = _caddy_site_block_for_host(caddyfile, host)

    fir_env = ENV_FIR_EXAMPLE.read_text()
    acx_env = _parse_env_example_key(fir_env, "ACX_ENV")
    network = _parse_env_example_key(fir_env, "ACX_NETWORK_NAME")
    expected_upstream = f"{acx_env}-api:8000"
    assert (
        f"reverse_proxy {expected_upstream}" in site_block
    ), f"vhost {host} must reverse_proxy to {expected_upstream} (compose alias ${{ACX_ENV}}-api)"

    compose = CADDY_COMPOSE.read_text()
    # Caddy service must attach to the network the fir upstream lives on.
    # Parse the services.caddy.networks list only (not a free-text greps-anywhere).
    caddy_svc = re.search(
        r"(?ms)^  caddy:\n(.*?)(?=^  \w|\Z)",
        compose,
    )
    assert caddy_svc, "docker-compose.caddy.yml missing caddy service"
    nets_match = re.search(r"(?ms)^\s+networks:\n((?:^\s+-\s+\S+\n)+)", caddy_svc.group(1))
    assert nets_match, "caddy service has no networks list"
    caddy_nets = re.findall(r"-\s+(\S+)", nets_match.group(1))
    assert network in caddy_nets, (
        f"caddy is not attached to {network} (fir stack network from "
        f".env.fir.example ACX_NETWORK_NAME); attached={caddy_nets}"
    )
    # External network declaration must exist so compose can join it.
    assert re.search(
        rf"(?m)^\s*{re.escape(network)}:\n\s+external:\s+true",
        compose,
    ), f"{network} must be declared external: true under top-level networks"


def test_dev_fir_remote_dir_basename_matches_env() -> None:
    # systemd template hardcodes WorkingDirectory=/opt/acx-backend/{{ENV}};
    # remote dir basename MUST equal the ENV token (not a short alias like "fir").
    remote = _source_env_map("env_to_remote_dir", "dev-fir")
    assert remote.endswith("/dev-fir"), remote
    assert remote == f"/opt/acx-backend/dev-fir"


def test_dev_fir_status_loop_includes_env() -> None:
    # do_status hardcodes the env list; unknown envs stay fail-closed elsewhere.
    status_body = SCRIPT_TEXT.split("do_status()", 1)[1].split("\n}\n", 1)[0]
    assert "for env in dev dev-fir staging prod" in status_body


def test_legacy_env_mappings_unchanged() -> None:
    assert _source_env_map("env_to_tag", "dev") == "dev"
    assert _source_env_map("env_to_tag", "staging") == "staging"
    assert _source_env_map("env_to_tag", "prod") == "latest"
    assert _source_env_map("env_to_unit", "dev") == "acx-dev"
    assert _source_env_map("env_to_unit", "prod") == "acx-prod"
    assert (
        _source_env_map("env_to_compose_files", "prod")
        == "-f docker-compose.env.yml -f docker-compose.admin.yml"
    )


def test_unknown_env_still_fails_closed() -> None:
    for fn in (
        "env_to_tag",
        "env_to_unit",
        "env_to_remote_dir",
        "env_to_health_url",
        "env_to_ready_url",
        "env_to_compose_files",
    ):
        proc = subprocess.run(
            ["/bin/bash", "-c", f'source "{SCRIPT}"; {fn} bogus'],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert proc.returncode != 0, f"{fn} must fail closed for unknown env"
        assert "Unknown env" in (proc.stdout + proc.stderr)


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


# ---- face_pipeline models deploy preflight (FIR stack) -----------------


def test_defines_face_pipeline_models_preflight() -> None:
    assert "preflight_remote_face_pipeline_models()" in SCRIPT_TEXT
    # Weights stay excluded from rsync; preflight is the gate, not bake-in.
    assert (
        "--exclude='recognition/infrastructure/face_pipeline/models/*.onnx'"
        in SCRIPT_TEXT
    )
    assert "face_detection_yunet_2026may.onnx" in SCRIPT_TEXT
    assert "face_recognition_sface_2021dec.onnx" in SCRIPT_TEXT


def test_deploy_calls_face_pipeline_preflight_before_build() -> None:
    deploy = SCRIPT_TEXT.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    # Read-only --check path returns early; the mutation path must preflight models.
    assert "preflight_remote_face_pipeline_models" in deploy
    assert deploy.index("preflight_remote_face_pipeline_models") < deploy.index(
        "do_build"
    )


def _run_face_pipeline_preflight(
    env_arg: str, tmp_path: Path, ssh_script: str
) -> subprocess.CompletedProcess[str]:
    """Source the deploy script and run the models preflight with a fake ssh."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text(ssh_script)
    (bindir / "ssh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'source "{SCRIPT}"; preflight_remote_face_pipeline_models {env_arg}',
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_face_pipeline_preflight_skips_non_fir(tmp_path: Path) -> None:
    # Non-fir envs must not require face_pipeline ONNX on the host.
    proc = _run_face_pipeline_preflight(
        "dev",
        tmp_path,
        "#!/bin/sh\necho 'ssh should not run for non-fir' >&2\nexit 99\n",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_face_pipeline_preflight_fails_when_models_dir_missing(tmp_path: Path) -> None:
    # Fail closed: missing/unreadable dir is a failure (never a silent pass).
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  # Remote .env value only (preflight runs grep|cut|tr on the host).
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
# Remote bash -s body: directory missing/unreadable.
cat >/dev/null
echo "DIR_FAIL:/opt/acx-backend/data/dev-fir-models/face_pipeline"
exit 1
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "face_pipeline" in combined
    assert "missing or unreadable" in combined.lower()
    assert "/opt/acx-backend/data/dev-fir-models/face_pipeline" in combined


def test_face_pipeline_preflight_fails_when_onnx_missing(tmp_path: Path) -> None:
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
cat >/dev/null
echo "FILE_FAIL:face_recognition_sface_2021dec.onnx:/opt/acx-backend/data/dev-fir-models/face_pipeline"
exit 1
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "face_recognition_sface_2021dec.onnx" in combined
    assert "/opt/acx-backend/data/dev-fir-models/face_pipeline" in combined


def test_face_pipeline_preflight_fails_when_models_path_unset(tmp_path: Path) -> None:
    ssh = r"""#!/bin/sh
# Empty ACX_MODELS_PATH (missing key) must fail closed.
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo ""
  exit 0
fi
exit 0
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "ACX_MODELS_PATH" in combined


def test_face_pipeline_preflight_passes_when_models_present(tmp_path: Path) -> None:
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
cat >/dev/null
echo "OK"
exit 0
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "face_pipeline ONNX weights present" in combined


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


def test_converge_runtime_ships_only_env_compose_for_dev_fir(tmp_path: Path) -> None:
    log = _run_converge_runtime("dev-fir", tmp_path)
    assert "sudo cp '/tmp/docker-compose.env.yml'" in log
    assert "docker-compose.admin.yml" not in log, "dev-fir must not ship the admin overlay"
    assert "/opt/acx-backend/dev-fir" in log


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
