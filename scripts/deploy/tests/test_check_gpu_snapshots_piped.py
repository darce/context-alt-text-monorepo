"""The checker must survive being piped to a VM over stdin.

GPUUX1-H-03: the deploy path ships this script with `bash -s`, which leaves
BASH_SOURCE unset. Under `set -u` the unguarded `${BASH_SOURCE[0]}` read printed
an `unbound variable` line, and the surrounding `cd ""/../..` silently resolved
repo_root to `/` — so a caller that forgot an env var got a baffling
`//scripts/deploy/...` path instead of the name of the variable to set.

The checker itself is the unit under test here; the call sites that build the
`bash -s` invocation are covered by test_check_gpu_snapshots_shell.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts/deploy/check-gpu-snapshots.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"

COMPOSE = """\
services:
  api:
    environment:
      - ACX_GPU_STATE_PATH={state_path}
      - ACX_DESCRIBE_LOAD_PATH={load_dir}/${{ACX_ENV}}/describe-load.json
    volumes:
      - {load_dir}/${{ACX_ENV}}:{load_dir}/${{ACX_ENV}}
      - {state_dir}:{state_dir}:ro
"""


@pytest.fixture
def fixture_env(tmp_path: Path) -> dict[str, str]:
    """A tree the checker considers healthy, addressed only by env vars."""
    state_dir = tmp_path / "run/acx"
    load_dir = tmp_path / "run/acx-write"
    state_dir.mkdir(parents=True)
    for env_name in DEPLOYMENTS.read_text(encoding="utf-8").splitlines():
        env_dir = load_dir / env_name
        env_dir.mkdir(parents=True)
        (env_dir / "describe-load.json").write_text(
            json.dumps(
                {
                    "queue_depth": 0,
                    "in_flight": 0,
                    "batch_in_progress": False,
                    "written_at": 900,
                }
            ),
            encoding="utf-8",
        )
    state_path = state_dir / "gpu-state.json"
    state_path.write_text(json.dumps({"state": "ready", "written_at": 900}), encoding="utf-8")

    compose = tmp_path / "compose.yml"
    compose.write_text(
        COMPOSE.format(state_path=state_path, state_dir=state_dir, load_dir=load_dir),
        encoding="utf-8",
    )
    return {
        "ACX_GPU_COMPOSE_FILE": str(compose),
        "ACX_GPU_UNIT_STATE_PATH": str(state_path),
        "ACX_GPU_UNIT_LOAD_DIR": str(load_dir),
        "ACX_GPU_STATE_PATH": str(state_path),
        "ACX_GPU_SNAPSHOT_DIR": str(state_dir),
        "ACX_DESCRIBE_LOAD_DIR": str(load_dir),
        "ACX_GPU_DEPLOYMENTS": ",".join(
            DEPLOYMENTS.read_text(encoding="utf-8").splitlines()
        ),
        "ACX_GPU_SNAPSHOT_CONFIG_ONLY": "1",
        "ACX_GPU_READER_UID": str(os.getuid()),
        "ACX_NOW_EPOCH": "1000",
    }


def _run_piped(env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the checker the way the deploy path does: over stdin."""
    return subprocess.run(
        ["/bin/bash", "-s"],
        cwd=cwd,
        input=CHECKER.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        env=env,
    )


def test_piped_invocation_succeeds_without_a_repo_checkout(
    fixture_env: dict[str, str], tmp_path: Path
) -> None:
    result = _run_piped(fixture_env, tmp_path)

    assert result.returncode == 0, result.stderr


def test_piped_invocation_emits_nothing_on_stderr(
    fixture_env: dict[str, str], tmp_path: Path
) -> None:
    """A passing check must stay silent; stray stderr masks real failures."""
    result = _run_piped(fixture_env, tmp_path)

    assert result.stderr == ""


@pytest.mark.parametrize(
    ("dropped", "expected_hint"),
    [
        ("ACX_GPU_COMPOSE_FILE", "ACX_GPU_COMPOSE_FILE"),
        ("ACX_GPU_DEPLOYMENTS", "ACX_GPU_DEPLOYMENTS"),
        ("ACX_GPU_UNIT_LOAD_DIR", "ACX_GPU_UNIT_LOAD_DIR"),
        ("ACX_GPU_UNIT_STATE_PATH", "ACX_GPU_UNIT_STATE_PATH"),
    ],
)
def test_a_missing_path_variable_is_named_rather_than_guessed(
    fixture_env: dict[str, str], tmp_path: Path, dropped: str, expected_hint: str
) -> None:
    """Without a checkout the checker cannot guess; it must say what to set."""
    env = {k: v for k, v in fixture_env.items() if k != dropped}

    result = _run_piped(env, tmp_path)

    assert result.returncode != 0
    assert expected_hint in result.stderr, result.stderr
    # `repo_root=/` used to turn every default into a `//`-rooted mystery path.
    assert "//" not in result.stderr, result.stderr


def test_checker_never_dereferences_bash_source_unguarded() -> None:
    """The guard is the fix; an unguarded read reintroduces the `set -u` abort."""
    source = CHECKER.read_text(encoding="utf-8")

    assert "${BASH_SOURCE[0]}" not in source
    assert "${BASH_SOURCE[0]:-}" in source


def test_piped_checker_rejects_gpu_state_outside_producer_enum(
    fixture_env: dict[str, str], tmp_path: Path
) -> None:
    state_path = Path(fixture_env["ACX_GPU_UNIT_STATE_PATH"])
    state_path.write_text(
        json.dumps({"state": "bogus", "written_at": 900}), encoding="utf-8"
    )
    fixture_env["ACX_GPU_SNAPSHOT_CONFIG_ONLY"] = "0"

    result = _run_piped(fixture_env, tmp_path)

    assert result.returncode != 0
    assert str(state_path) in result.stderr
    assert "state must be one of" in result.stderr


def test_piped_checker_rejects_load_snapshot_missing_required_counter(
    fixture_env: dict[str, str], tmp_path: Path
) -> None:
    load_path = Path(fixture_env["ACX_GPU_UNIT_LOAD_DIR"]) / "dev/describe-load.json"
    load_path.write_text(
        json.dumps({"in_flight": 0, "written_at": 900}), encoding="utf-8"
    )
    fixture_env["ACX_GPU_SNAPSHOT_CONFIG_ONLY"] = "0"

    result = _run_piped(fixture_env, tmp_path)

    assert result.returncode != 0
    assert str(load_path) in result.stderr
    assert "queue_depth is required" in result.stderr
