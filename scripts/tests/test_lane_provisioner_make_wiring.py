from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MK_LANE_LIFECYCLE_PATH = REPO_ROOT / "mk" / "lane-lifecycle.mk"
MK_LANE_WORKER_PATH = REPO_ROOT / "mk" / "lane-worker.mk"
PROVISIONER = "scripts/workstate/provision_lane_worktree.py"
BOOTSTRAP = "-m workbay_orchestrator_mcp.orchestration.bootstrap_lane"


def _recipe_for(path: Path, target: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(f"{target}:")), None)
    assert start is not None, f"missing target {target} in {path}"
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            body.append(line[1:])
            continue
        if not line.strip():
            continue
        break
    recipe = "\n".join(body)
    assert recipe, f"target {target} in {path} has no recipe"
    return recipe


def _normalized(recipe: str) -> str:
    return recipe.replace("\\\n", " ")


def _command_containing(recipe: str, needle: str) -> str:
    for command in _normalized(recipe).split(";"):
        if needle in command:
            return command.strip()
    raise AssertionError(f"{needle!r} not found in recipe:\n{recipe}")


def _assert_provisioner_after_bootstrap(recipe: str, *, worktree_var: str) -> None:
    normalized = _normalized(recipe)
    bootstrap_at = normalized.find(BOOTSTRAP)
    provision_at = normalized.find(PROVISIONER)
    assert bootstrap_at != -1, f"missing {BOOTSTRAP} in recipe:\n{recipe}"
    assert provision_at != -1, f"missing {PROVISIONER} in recipe:\n{recipe}"
    assert bootstrap_at < provision_at, "provisioner must run after bootstrap_lane"

    command = _command_containing(recipe, PROVISIONER)
    assert "python3" in command, command
    assert f'--worktree "$({worktree_var})"' in command, command
    assert '--primary "$(ORCHESTRATOR_ROOT)"' in command, command
    assert "||" not in command, f"provisioner exit must fail the recipe: {command}"
    assert ".acx-secure-offload" in recipe
    assert "--secure-offload" in recipe
    assert "Skipping overlay/dependency provision for secure-offload sandbox" in recipe


def test_lane_open_provisions_worktree_after_bootstrap() -> None:
    recipe = _recipe_for(MK_LANE_LIFECYCLE_PATH, "lane-open")
    _assert_provisioner_after_bootstrap(recipe, worktree_var="LANE_WORKTREE")
    command = _command_containing(recipe, PROVISIONER)
    assert "LANE_WORKTREE_TARGET" not in command


def test_lane_check_provisions_worktree_after_bootstrap() -> None:
    recipe = _recipe_for(MK_LANE_WORKER_PATH, "lane-check")
    _assert_provisioner_after_bootstrap(recipe, worktree_var="LANE_WORKTREE_TARGET")


def test_gates_harness_workflow_runs_provisioner_wiring_test() -> None:
    workflow = (REPO_ROOT / ".github/workflows/gates-harness.yml").read_text(encoding="utf-8")
    assert "python -m pytest scripts/tests" in workflow
    assert "mk/**" in workflow


def test_gates_harness_workflow_runs_reap_lane_bash_suite() -> None:
    workflow = (REPO_ROOT / ".github/workflows/gates-harness.yml").read_text(encoding="utf-8")
    assert "bash scripts/vm/tests/test_reap_lane.sh" in workflow
