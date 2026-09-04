"""Pytest entry point for the GPU snapshot checker shell contract suite."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts/deploy/check-gpu-snapshots.sh"
MAKEFILE = REPO_ROOT / "Makefile"
RECOGNITION_DEPLOY = REPO_ROOT / "scripts/deploy/recognition-service.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"

# The suite spawns seven `make` processes, and this repo's `make` startup
# resolves the active task through four `uvx` package launches. That costs
# ~6s per process on a warm cache and ~15s cold, so the suite legitimately
# needs ~70-120s on a developer laptop while the CI gate host finishes in
# ~30s. This budget exists to catch a hang, not to police wall-clock speed;
# a host-tuned value turns the suite into a hardware-dependent flake.
_DEFAULT_TIMEOUT_SECONDS = 300.0


def _assignment_block(path: Path, start: str, end: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    section = text.split(start, 1)[1].split(end, 1)[0]
    # A remote variable inside a locally double-quoted SSH command is escaped
    # in source so the remote shell, rather than the laptop shell, expands it.
    section = section.replace(r"\$", "$")
    assignments = re.findall(
        r"\b(ACX_[A-Z0-9_]+)=(?:\"([^\"]*)\"|'([^']*)'|([^\s\\]+))",
        section,
    )
    return {key: double or single or bare for key, double, single, bare in assignments}


def _remote_callsite_assignments() -> list[tuple[str, dict[str, str]]]:
    return [
        (
            "Makefile",
            _assignment_block(
                MAKEFILE,
                "check-gpu-snapshots-live:",
                "\n# Default target",
            ),
        ),
        (
            "scripts/deploy/recognition-service.sh",
            _assignment_block(
                RECOGNITION_DEPLOY,
                "verify_live_gpu_snapshots() {",
                "\n}\n",
            ),
        ),
    ]


def _transport_blocks() -> list[tuple[str, str]]:
    return [
        (
            "Makefile",
            MAKEFILE.read_text(encoding="utf-8")
            .split("check-gpu-snapshots-live:", 1)[1]
            .split("\n# Default target", 1)[0],
        ),
        (
            "scripts/deploy/recognition-service.sh",
            RECOGNITION_DEPLOY.read_text(encoding="utf-8")
            .split("verify_live_gpu_snapshots() {", 1)[1]
            .split("\n}\n", 1)[0],
        ),
    ]


def _fixture_value(key: str, value: str, fixture_root: Path) -> str:
    state_dir = fixture_root / "run/acx"
    load_dir = fixture_root / "run/acx-write"
    if key == "ACX_GPU_COMPOSE_FILE":
        return str(fixture_root / "compose.yml")
    if key == "ACX_GPU_DEPLOYMENTS":
        return ",".join(DEPLOYMENTS.read_text(encoding="utf-8").splitlines())
    if value.startswith("/run/acx-write"):
        return value.replace("/run/acx-write", str(load_dir), 1)
    if value.startswith("/run/acx"):
        return value.replace("/run/acx", str(state_dir), 1)
    return value


@pytest.mark.parametrize(("source_name", "assignments"), _remote_callsite_assignments())
def test_remote_snapshot_callsite_executes_without_repo_checkout(
    tmp_path: Path,
    source_name: str,
    assignments: dict[str, str],
) -> None:
    expected_keys = {
        "ACX_DESCRIBE_LOAD_DIR",
        "ACX_GPU_COMPOSE_FILE",
        "ACX_GPU_DEPLOYMENTS",
        "ACX_GPU_SNAPSHOT_DIR",
        "ACX_GPU_STATE_PATH",
        "ACX_GPU_UNIT_LOAD_DIR",
        "ACX_GPU_UNIT_STATE_PATH",
    }

    state_dir = tmp_path / "run/acx"
    load_dir = tmp_path / "run/acx-write"
    state_dir.mkdir(parents=True)
    for env_name in ("dev", "dev-fir", "staging", "prod"):
        (load_dir / env_name).mkdir(parents=True)
        (load_dir / env_name / "describe-load.json").write_text(
            '{"queue_depth":0,"in_flight":0,"batch_in_progress":false,"written_at":900}\n',
            encoding="utf-8",
        )
    state_path = state_dir / "gpu-state.json"
    state_path.write_text('{"state":"ready","written_at":900}\n', encoding="utf-8")
    compose_path = tmp_path / "compose.yml"
    compose_path.write_text(
        "services:\n"
        "  api:\n"
        "    environment:\n"
        f"      - ACX_GPU_STATE_PATH={state_path}\n"
        f"      - ACX_DESCRIBE_LOAD_PATH={load_dir}/${{ACX_ENV}}/describe-load.json\n"
        "    volumes:\n"
        f"      - {load_dir}/${{ACX_ENV}}:{load_dir}/${{ACX_ENV}}\n"
        f"      - {state_dir}:{state_dir}:ro\n",
        encoding="utf-8",
    )

    command_env = os.environ.copy()
    command_env.update(
        {
            key: _fixture_value(key, value, tmp_path)
            for key, value in assignments.items()
        }
    )
    command_env.update(
        {
            "ACX_GPU_SNAPSHOT_CONFIG_ONLY": "1",
            "ACX_GPU_STATE_STALE_SECONDS": "180",
            "ACX_DESCRIBE_LOAD_STALE_SECONDS": "120",
            "ACX_GPU_READER_UID": str(os.getuid()),
            "ACX_NOW_EPOCH": "1000",
        }
    )
    result = subprocess.run(
        ["/bin/bash", "-s"],
        cwd=tmp_path,
        env=command_env,
        input=CHECKER.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr

    assert set(assignments) == expected_keys, (
        f"{source_name} remote checker environment drifted: "
        f"expected {sorted(expected_keys)}, got {sorted(assignments)}"
    )
    assert list(assignments) == sorted(assignments), (
        f"{source_name} remote checker environment must remain alphabetically ordered"
    )
    assert result.returncode == 0, (
        f"{source_name} remote checker invocation exited with {result.returncode}\n{output}"
    )
    assert "lifecycle install script is missing or unreadable" not in output, (
        f"{source_name} remote checker invocation fell back to the absent repo install script\n"
        f"{output}"
    )


@pytest.mark.parametrize(("source_name", "block"), _transport_blocks())
def test_each_transport_frames_and_bounds_the_checker_payload(
    source_name: str, block: str
) -> None:
    for required in (
        "ACX_GPU_CHECKER_V1",
        "expected_bytes",
        "expected_sha",
        "sha256sum",
        "truncated GPU checker payload",
        "timeout --foreground",
        "BatchMode=yes",
        "ConnectTimeout=10",
        "ServerAliveInterval=5",
        "ServerAliveCountMax=2",
    ):
        assert required in block, f"{source_name} is missing transport guard {required}"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def test_make_transport_does_not_hide_a_missing_checker_producer(tmp_path: Path) -> None:
    """Regression: the old pipeline executed an empty checker and exited zero."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_marker = tmp_path / "ssh-reached"
    _write_executable(
        fake_bin / "ssh",
        f"#!/bin/sh\ntouch '{ssh_marker}'\ncat >/dev/null\n",
    )
    _write_executable(
        fake_bin / "timeout",
        """#!/usr/bin/env bash
while (( $# )); do
  case "$1" in
    --foreground|--signal=*|--kill-after=*) shift ;;
    *s) shift; break ;;
    *) break ;;
  esac
done
exec "$@"
""",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "check-gpu-snapshots-live",
            "GPU_SNAPSHOT_ENV=dev",
            f"GPU_SNAPSHOT_CHECKER={tmp_path / 'missing-checker.sh'}",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not ssh_marker.exists(), "receiver ran even though the checker producer failed"


def test_make_outer_deadline_terminates_a_post_connection_stall(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_marker = tmp_path / "ssh-connected"
    _write_executable(
        fake_bin / "ssh",
        f"#!/bin/sh\ntouch '{ssh_marker}'\nexec sleep 10\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    started = time.monotonic()
    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "check-gpu-snapshots-live",
            "GPU_SNAPSHOT_ENV=dev",
            "GPU_SNAPSHOT_GATE_TIMEOUT_SECONDS=1",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    elapsed = time.monotonic() - started

    assert ssh_marker.exists(), "the fake SSH command never reached its connected stall"
    assert result.returncode != 0
    assert elapsed < 6, f"outer deadline did not bound the SSH command ({elapsed:.2f}s)"


def test_check_gpu_snapshots_shell_suite() -> None:
    suite = REPO_ROOT / "scripts/deploy/tests/test-check-gpu-snapshots.sh"

    result = subprocess.run(
        ["/bin/bash", str(suite)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=float(
            os.environ.get(
                "ACX_GPU_SHELL_SUITE_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS
            )
        ),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, f"{suite} exited with {result.returncode}\n{output}"
    assert "PASS: each environment directory must be API-writable" in output
    assert output.rstrip().endswith("ALL PASS")
