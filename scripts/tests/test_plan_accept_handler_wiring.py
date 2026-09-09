from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_MK = REPO_ROOT / "Makefile.d" / "lifecycle.mk"
TRACKED_HANDLER = "scripts/workstate/lifecycle/handlers/plan_baseline.py"


def test_plan_accept_recipe_names_tracked_handler() -> None:
    recipe = LIFECYCLE_MK.read_text(encoding="utf-8")
    body = "\n".join(line[1:] for line in recipe.splitlines() if line.startswith("\t"))
    assert "ACX_LIFECYCLE_HANDLERS" in recipe
    assert TRACKED_HANDLER in body.replace("$(ACX_LIFECYCLE_HANDLERS)", "scripts/workstate/lifecycle/handlers")
    assert "workbay_lifecycle" not in body


def test_plan_accept_dry_run_names_tracked_handler() -> None:
    completed = subprocess.run(
        ["make", "-n", "-f", str(LIFECYCLE_MK), "plan-accept", "TASK=ISSUEDAG-1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert TRACKED_HANDLER in combined
    assert "workbay_lifecycle" not in combined
