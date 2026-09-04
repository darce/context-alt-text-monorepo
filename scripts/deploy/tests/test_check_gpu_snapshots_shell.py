"""Pytest entry point for the GPU snapshot checker shell contract suite."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts/deploy/check-gpu-snapshots.sh"
MAKEFILE = REPO_ROOT / "Makefile"
RECOGNITION_DEPLOY = REPO_ROOT / "scripts/deploy/recognition-service.sh"

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


def _fixture_value(key: str, value: str, fixture_root: Path) -> str:
    state_dir = fixture_root / "run/acx"
    load_dir = fixture_root / "run/acx-write"
    if key == "ACX_GPU_COMPOSE_FILE":
        return str(fixture_root / "compose.yml")
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
