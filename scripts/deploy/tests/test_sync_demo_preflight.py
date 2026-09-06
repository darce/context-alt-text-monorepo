"""Contract tests for the opt-in demo GPU environment preflight."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"


def _run_sync(
    tmp_path: Path,
    *,
    preflight: str | None = None,
    fail_preflight: bool = False,
    permission_aware: bool = False,
    describe_chunk: str | None = None,
    describe_max: str | None = None,
    with_plugin: bool = False,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    (bin_dir / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'ssh %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        f"if [[ \"${{PERMISSION_AWARE:-0}}\" == 1 && \"$*\" == *\"sudo install -d -m 700 '/tmp/acx-gpu-preflight/lib'\"* ]]; then exit 23; fi\n"
        f"if [[ \"${{PERMISSION_AWARE:-0}}\" == 1 && \"$*\" == *\"install -d -m 700 '/tmp/acx-gpu-preflight/lib'\"* ]]; then : > {log_path}.staging; fi\n"
        "if [[ \"$*\" == *--check-reaper* ]] && [[ \"${FAIL_PREFLIGHT:-0}\" == 1 ]]; then exit 17; fi\n"
        f"if [[ \"$1\" == *bash* || \"$*\" == *' bash -se'* ]]; then cat >> {log_path}.stdin; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "scp").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'scp %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        f"if [[ \"${{PERMISSION_AWARE:-0}}\" == 1 && \"$*\" == *'/tmp/acx-gpu-preflight/'* && ! -f {log_path}.staging ]]; then exit 24; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for shim in (bin_dir / "ssh", bin_dir / "scp"):
        shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if with_plugin:
        plugin_zip = tmp_path / "alt-context.zip"
        plugin_zip.write_bytes(b"test plugin")
        env["PLUGIN_ZIP"] = str(plugin_zip)
    else:
        env["PLUGIN_ZIP"] = ""
    env["OCI_HOST"] = "test-host.invalid"
    env["OCI_USER"] = "test-user"
    env["PERMISSION_AWARE"] = "1" if permission_aware else "0"
    if preflight is None:
        env.pop("ACX_DEMO_GPU_PREFLIGHT", None)
    else:
        env["ACX_DEMO_GPU_PREFLIGHT"] = preflight
    if describe_chunk is not None:
        env["ACX_DEMO_DESCRIBE_CHUNK"] = describe_chunk
    else:
        env.pop("ACX_DEMO_DESCRIBE_CHUNK", None)
    if describe_max is not None:
        env["ACX_DEMO_DESCRIBE_MAX"] = describe_max
    else:
        env.pop("ACX_DEMO_DESCRIBE_MAX", None)
    env["FAIL_PREFLIGHT"] = "1" if fail_preflight else "0"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    return (tmp_path / "commands.log").read_text(encoding="utf-8")


def test_gpu_preflight_runs_once_when_opted_in(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1")

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert log.count("--check-reaper") == 1
    assert "/opt/acx-backend/prod/secrets/.env" in log
    assert "/opt/acx-backend/demo/secrets/.env" in log
    assert log.count("docker-compose.demo.yml") >= 1


def test_gpu_preflight_staging_is_writable_by_oci_user(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1", permission_aware=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "commands.log.staging").exists()
    assert "sudo install -d -m 700 '/tmp/acx-gpu-preflight/lib'" not in _log(tmp_path)


def test_gpu_preflight_is_off_by_default(tmp_path: Path) -> None:
    result = _run_sync(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert "--check-reaper" not in log
    assert log.count("docker-compose.demo.yml") >= 1


def test_failed_gpu_preflight_aborts_before_demo_compose_scp(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1", fail_preflight=True)

    assert result.returncode == 4, result.stdout + result.stderr
    assert "GPU environment preflight failed" in result.stderr
    assert "docker-compose.demo.yml" not in _log(tmp_path)


def test_no_plugin_artifact_skips_first_burst_assertion(tmp_path: Path) -> None:
    result = _run_sync(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    bootstrap_input = (tmp_path / "commands.log.stdin").read_text(encoding="utf-8")
    assert 'BOOTSTRAP_RAN="0"' in bootstrap_input
    assert 'if [[ "$BOOTSTRAP_RAN" == "1" ]]; then' in bootstrap_input


def test_describe_bounds_are_forwarded_to_remote_bootstrap(tmp_path: Path) -> None:
    result = _run_sync(
        tmp_path,
        describe_chunk="7",
        describe_max="23",
        with_plugin=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    bootstrap_input = (tmp_path / "commands.log.stdin").read_text(encoding="utf-8")
    assert "ACX_DEMO_DESCRIBE_CHUNK='7'" in bootstrap_input
    assert "ACX_DEMO_DESCRIBE_MAX='23'" in bootstrap_input


def test_demo_env_template_uses_bootstrap_ci_keys_only() -> None:
    env_example = (REPO_ROOT / "infra" / "oci" / "demo" / ".env.example").read_text(encoding="utf-8")
    lines = env_example.splitlines()

    for key in ("WP_CI_USER", "WP_CI_PASSWORD", "WP_CI_EMAIL"):
        key_lines = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
        assert len(key_lines) == 1, f"{key} must have exactly one VM-template assignment"
        annotation = lines[key_lines[0] - 1]
        assert "domain: demo-wp" in annotation
        assert "source: operator secret" in annotation
        assert "consumer: bootstrap-wp.sh" in annotation

    assert "ACX_E2E_WP_CI_USER=" not in env_example
    assert "ACX_E2E_WP_CI_PASS=" not in env_example
