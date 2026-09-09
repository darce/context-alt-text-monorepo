from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts/workstate/lifecycle/handlers/plan_baseline.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_baseline", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_tasks_are_planning_paths() -> None:
    module = _load()
    assert "docs/tasks/" in module.PLANNING_DIR_PREFIXES
    assert module.is_planning_path("docs/tasks/15.0/example-task-plan.md")
    assert module.is_planning_path("docs/plans/0117-example.md")
    assert not module.is_planning_path("apps/prototype-wp-alt-context/README.md")
