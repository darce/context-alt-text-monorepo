from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "generate_agent_config.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_agent_config", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load generate_agent_config module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_agent_config_passes_orchestrator_root(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_module()
    fake_get_lane_config = mock.Mock(
        return_value={
            "preferred_backend": "codex-subagent",
            "preferred_model": "gpt-5.4-mini",
            "reasoning_effort": "high",
            "title": "Frontend",
            "objective": "Implement frontend work",
            "branch": "codex/frontend",
        }
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_agent_config.py",
            "--orchestrator-root",
            str(tmp_path),
            "--task-ref",
            "task-1",
            "--lane-id",
            "frontend",
        ],
    )

    with mock.patch.object(module, "get_lane_config", fake_get_lane_config):
        module.main()

    fake_get_lane_config.assert_called_once_with(
        "task-1",
        "frontend",
        orchestrator_root=str(tmp_path.resolve()),
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["lane_id"] == "frontend"
    assert payload["task_ref"] == "task-1"
