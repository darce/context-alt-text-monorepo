import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "worker_daemon.py"
SCRIPT_DIR = ORCHESTRATION_DIR


def _load_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("worker_daemon", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("dry_run", [True])
def test_review_fix_cycle_e2e(tmp_path: Path, dry_run: bool) -> None:
    """Test that a review finding correctly triggers a fix cycle and then converges."""
    mod = _load_module()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    result_dir = tmp_path / "results"
    result_dir.mkdir()
    result_file = result_dir / "result.json"

    # 1. First execution produces merge_ready but with a bug
    # 2. Review discovers the bug (converged=False)
    # 3. Worker triggers a fix
    # 4. Second execution fix produces merge_ready
    # 5. Review passes (converged=True)
    # 6. Handoff

    side_effects = [
        # First exec result
        {"handoff_action": "merge_ready", "summary": "Buggy implementation."},
        # Second exec result (post-fix)
        {"handoff_action": "merge_ready", "summary": "Fixed implementation."},
    ]

    def mock_exec(*args, **kwargs):
        data = side_effects.pop(0)
        result_file.write_text(json.dumps(data))
        return result_file

    review_side_effects = [
        # First review: finding found
        {
            "findings": [{"severity": "high", "category": "GAP", "file_path": "x.py", "description": "Bug."}],
            "summary": "Found a bug.",
            "converged": False,
            "changed_files": ["x.py"],
            "stack_guides": [],
        },
        # Second review: clean
        {
            "findings": [],
            "summary": "All good now.",
            "converged": True,
            "changed_files": ["x.py"],
            "stack_guides": [],
        },
    ]

    with (
        mock.patch.object(mod, "poll_lane_state", side_effect=["actionable", "actionable", "idle"]),
        mock.patch("lane_exec.run_lane_exec", side_effect=mock_exec),
        mock.patch("lane_exec.build_fix_prompt", return_value="fix it"),
        mock.patch("review_runner.run_review", side_effect=review_side_effects),
        mock.patch("review_runner.findings_converged", side_effect=[False, True]),
        mock.patch.object(mod, "_run_final_handoff", return_value=0) as mock_handoff,
        mock.patch("subprocess.run") as mock_subprocess,
        mock.patch("time.sleep", return_value=None),
    ):
        mock_subprocess.return_value = mock.Mock(returncode=0, stdout="base prompt")

        rc = mod.worker_loop(
            mod.WorkerConfig(
                orchestrator_root=REPO_ROOT,
                task_ref="test-task",
                lane_id="test-lane",
                session="test-session",
                worktree_path=tmp_path,
                single_pass=True,
                dry_run=dry_run,
            )
        )

    assert rc == 0
    # Should have called handoff exactly once at the very end
    mock_handoff.assert_called_once()
    # Check that it went through two execution turns
    assert len(side_effects) == 0
