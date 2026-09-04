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
GPU_LIFECYCLE_CONTRACT = REPO_ROOT / "docs/workbay/contracts/gpu-lifecycle.md"
GPUUX_TASK_PLAN = REPO_ROOT / "docs/tasks/v0.5.0/GPUUX-1-gpu-tier-state-and-toasts-task-plan.md"
DESCRIBE_LOAD_PRODUCER = REPO_ROOT / "apps/prototype-description-service/scene/application/describe_load.py"
GPU_STATE_WRITER = REPO_ROOT / "infra/oci/gpu_lifecycle/state_snapshot.py"
DESCRIBE_RUN_CONTRACT_TEST = REPO_ROOT / "apps/prototype-description-service/scene/tests/test_describe_run_contract.py"
GPU_TOAST_HOOK = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/hooks/useGpuStateToasts.ts"
GPU_TOAST_TEST = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useGpuStateToasts.test.tsx"
GPU_TOAST_MOUNT = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/App.tsx"

# The suite spawns seven `make` processes, and this repo's `make` startup
# resolves the active task through four `uvx` package launches. That costs
# ~6s per process on a warm cache and ~15s cold, so the suite legitimately
# needs ~70-120s on a developer laptop while the CI gate host finishes in
# ~30s. This budget exists to catch a hang, not to police wall-clock speed;
# a host-tuned value turns the suite into a hardware-dependent flake.
_DEFAULT_TIMEOUT_SECONDS = 300.0


def test_gpu_lifecycle_contract_tracks_batch_in_progress_producer() -> None:
    contract = GPU_LIFECYCLE_CONTRACT.read_text(encoding="utf-8")
    producer = DESCRIBE_LOAD_PRODUCER.read_text(encoding="utf-8")

    assert '"batch_in_progress": await batch_in_progress(session)' in producer
    assert re.search(r"The current describe-service\s+producer writes this key\.", contract)
    assert "producer does not write this key" not in contract
    assert "unprotected until the producer writes `batch_in_progress`" not in contract


def test_gpuux_task_plan_is_static_and_matches_delivered_contract() -> None:
    plan = GPUUX_TASK_PLAN.read_text(encoding="utf-8")
    writer = GPU_STATE_WRITER.read_text(encoding="utf-8")
    schema_test = DESCRIBE_RUN_CONTRACT_TEST.read_text(encoding="utf-8")
    toast_hook = GPU_TOAST_HOOK.read_text(encoding="utf-8")
    toast_test = GPU_TOAST_TEST.read_text(encoding="utf-8")
    toast_mount = GPU_TOAST_MOUNT.read_text(encoding="utf-8")

    assert "GpuStateSnapshot" not in writer
    assert "test_run_response_matches_shared_schema_via_actual_builder" in schema_test
    assert "useGpuStateToasts" in toast_hook
    assert "useGpuStateToasts" in toast_test
    assert "useGpuStateToasts();" in toast_mount

    for mutable_or_stale_claim in (
        "Review Coverage Target",
        "No RED gate was recorded",
        "GpuStateSnapshot",
        "schema parity — **not done**",
        "still unbuilt",
        "— not started",
    ):
        assert mutable_or_stale_claim not in plan


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
    command_env.update({key: _fixture_value(key, value, tmp_path) for key, value in assignments.items()})
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
        f"{source_name} remote checker environment drifted: expected {sorted(expected_keys)}, got {sorted(assignments)}"
    )
    assert list(assignments) == sorted(assignments), (
        f"{source_name} remote checker environment must remain alphabetically ordered"
    )
    assert result.returncode == 0, f"{source_name} remote checker invocation exited with {result.returncode}\n{output}"
    assert "lifecycle install script is missing or unreadable" not in output, (
        f"{source_name} remote checker invocation fell back to the absent repo install script\n{output}"
    )


@pytest.mark.parametrize(("source_name", "block"), _transport_blocks())
def test_each_transport_frames_and_bounds_the_checker_payload(source_name: str, block: str) -> None:
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


def test_make_gate_names_a_missing_digest_tool_before_opening_ssh(tmp_path: Path) -> None:
    """The digest tool is preflighted like `timeout`, not discovered mid-pipeline.

    `sha256sum` is absent from a stock macOS PATH. Without a preflight the
    recipe's `set -eu` aborted somewhere inside the payload pipeline, after the
    SSH connection had already been opened, with no hint about which tool was
    missing.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_marker = tmp_path / "ssh-reached"
    _write_executable(
        fake_bin / "ssh",
        f"#!/bin/sh\ntouch '{ssh_marker}'\ncat >/dev/null\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "check-gpu-snapshots-live",
            "GPU_SNAPSHOT_ENV=dev",
            "GPU_SNAPSHOT_SHA256=acx-absent-digest-tool",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    assert "acx-absent-digest-tool command is required" in result.stderr
    assert not ssh_marker.exists(), "the gate opened SSH before preflighting the digest tool"


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
        timeout=float(os.environ.get("ACX_GPU_SHELL_SUITE_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)),
    )
    finished = time.time()

    assert ssh_marker.exists(), "the fake SSH command never reached its connected stall"
    assert result.returncode != 0
    # Measure the deadline window itself, from the moment the SSH command
    # reached its stall. Timing the whole `make` invocation would fold in
    # Makefile parse cost (lane-config `uvx` shell-outs), which varies per
    # worktree and has nothing to do with the outer deadline.
    stalled_for = finished - ssh_marker.stat().st_mtime
    assert stalled_for < 6, f"outer deadline did not bound the SSH command ({stalled_for:.2f}s)"


def test_check_gpu_snapshots_shell_suite() -> None:
    suite = REPO_ROOT / "scripts/deploy/tests/test-check-gpu-snapshots.sh"

    result = subprocess.run(
        ["/bin/bash", str(suite)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=float(os.environ.get("ACX_GPU_SHELL_SUITE_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, f"{suite} exited with {result.returncode}\n{output}"
    # WBUX6-W4-F-03: under root this case is a documented `skip_covered` (uid 0
    # bypasses mode 0555), so pinning only the PASS form makes this guard
    # unrunnable on the privileged CI job. Accept either, never absence.
    case = "each environment directory must be API-writable"
    assert f"PASS: {case}" in output or f"SKIP: {case}" in output, output
    # WBUX6-L5-NEW-04: a skip must not land under an unqualified "ALL PASS", but
    # the qualified summary is still a clean run.
    tail = output.rstrip()
    assert tail.endswith("ALL PASS") or "PASSED WITH" in tail, output


def test_oci_readme_gpu_lifecycle_flags_exist_in_the_cli() -> None:
    """rg-006 guard for GPUUX1-RB-09 / GPUUX1-L-05.

    The README documented `--load-json` long after the CLI had replaced it with
    `--load-dir`, so both production operator commands failed with
    "unrecognized arguments" exactly during manual recovery or first install.
    """
    readme = (REPO_ROOT / "infra" / "oci" / "README.md").read_text(encoding="utf-8")
    reaper = (REPO_ROOT / "infra" / "oci" / "gpu_lifecycle" / "reaper.py").read_text(encoding="utf-8")

    known_flags = set(re.findall(r'"(--[a-z0-9-]+)"', reaper))
    assert "--load-dir" in known_flags, "the CLI no longer registers --load-dir; update this guard"

    documented: set[str] = set()
    in_invocation = False
    for line in readme.splitlines():
        # Operator commands are wrapped across backslash continuations, so the
        # flag that regressed last time was never on the `gpu_lifecycle` line.
        if "gpu_lifecycle" in line:
            in_invocation = True
        if not in_invocation:
            continue
        documented.update(re.findall(r"(--[a-z0-9-]+)", line))
        in_invocation = line.rstrip().endswith("\\")

    assert documented, "no gpu_lifecycle invocation found in infra/oci/README.md"
    unknown = sorted(documented - known_flags)
    assert not unknown, f"infra/oci/README.md documents flags the CLI does not accept: {unknown}"
