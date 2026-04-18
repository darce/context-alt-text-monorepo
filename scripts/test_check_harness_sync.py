from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from scripts.check_harness_sync import (
    _check_branch_isolation,
    _check_cold_start,
    _check_dashboard_naming,
    _check_workspace_settings,
    _check_worktree_drift,
    _load_contract,
    run_checks,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
COPY_PATHS = (
    Path(".vscode/settings.json"),
    Path(".claude/settings.json"),
    Path(".github/hooks/guard-main-branch.py"),
    Path(".github/hooks/terminal-guard.json"),
    Path(".github/hooks/guard-worktree-drift.py"),
    Path("scripts/hooks/_branch_isolation_guard.py"),
    Path("scripts/hooks/_harness_protocol.py"),
    Path("scripts/hooks/_worktree_drift.py"),
    Path("scripts/hooks/guard-main-branch.sh"),
    Path("scripts/hooks/guard-worktree-drift.sh"),
)


def _valid_contract() -> dict:
    return {
        "version": 1,
        "cold_start": {
            "shared_steps": [
                {
                    "id": "make-context",
                    "description": "run make context at session start",
                    "phrase": "make context",
                    "references": ["CLAUDE.md", "copilot.md"],
                },
            ],
        },
        "branch_isolation": {
            "protected_branches": ["main", "master"],
            "code_roots": ["apps/", "packages/", "scripts/"],
            "protected_extensions": [".py", ".sh", ".ts"],
            "root_protected_files": ["Makefile"],
            "permitted_main_surfaces": [{"pattern": "docs/tasks/**/*.md", "reason": "Task plans"}],
            "enforcers": [
                {"path": ".github/hooks/guard-main-branch.py", "harness": "vscode"},
                {"path": "scripts/hooks/guard-main-branch.sh", "harness": "claude"},
            ],
        },
        "hooks": {"pre_tool_use": [], "post_tool_use": []},
    }


def _write_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("Run make context at session start.\n")
    (repo / "copilot.md").write_text("Remember: make context.\n")
    for relative in COPY_PATHS:
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
        if destination.suffix == ".sh":
            destination.chmod(0o755)
    package_src = repo / "packages" / "agent-handoff-mcp" / "src"
    package_src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "packages" / "agent-handoff-mcp" / "src", package_src)
    contract_path = repo / "docs" / "agentic" / "contracts" / "harness-protocol.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(_valid_contract(), sort_keys=False), encoding="utf-8")
    return repo


def test_cold_start_passes_when_phrase_present_in_references(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    errors = _check_cold_start(contract, repo_root=repo)
    assert errors == []


def test_cold_start_fails_when_phrase_missing_from_reference(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "copilot.md").write_text("no phrase here\n")
    contract = _valid_contract()
    errors = _check_cold_start(contract, repo_root=repo)
    assert any("copilot.md" in err and "make context" in err for err in errors)


def test_cold_start_fails_when_reference_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    contract["cold_start"]["shared_steps"][0]["references"].append("missing.md")
    errors = _check_cold_start(contract, repo_root=repo)
    assert any("missing.md" in err and "not found" in err for err in errors)


def test_cold_start_requires_phrase_and_references(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    contract["cold_start"]["shared_steps"] = [{"id": "broken"}]
    errors = _check_cold_start(contract, repo_root=repo)
    assert any("broken" in err and "phrase" in err for err in errors)


def test_branch_isolation_passes_against_both_harness_enforcers(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert errors == []


def test_branch_isolation_fails_when_enforcer_missing_loader_wiring(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "scripts" / "hooks" / "guard-main-branch.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    contract = _valid_contract()
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("guard-main-branch.sh" in err and "load policy" in err for err in errors)


def test_branch_isolation_fails_when_enforcer_file_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    contract["branch_isolation"]["enforcers"].append(
        {"path": "scripts/hooks/not_there.sh", "harness": "claude"}
    )
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("not_there.sh" in err and "not found" in err for err in errors)


def test_branch_isolation_requires_shared_loader_file(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "scripts" / "hooks" / "_harness_protocol.py").unlink()
    contract = _valid_contract()
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("_harness_protocol.py" in err for err in errors)


def test_branch_isolation_fails_when_permitted_surface_reason_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    contract["branch_isolation"]["permitted_main_surfaces"][0]["reason"] = ""
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("permitted_main_surfaces[0]" in err and "reason" in err for err in errors)


def test_worktree_drift_passes_fixture_harness(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    errors = _check_worktree_drift(contract, repo_root=repo)
    assert errors == []


def test_dashboard_naming_flags_live_surface_reference(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "agentic" / "rules").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "agentic" / "rules" / "workflow.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("workflow.md:1" in err for err in errors)


def test_dashboard_naming_ignores_task_plan_mentions(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "tasks" / "17.0").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "tasks" / "17.0" / "E17-8-sample-task-plan.md").write_text(
        "Historical DASHBOARD.md note\n",
        encoding="utf-8",
    )
    errors = _check_dashboard_naming(repo_root=repo)
    assert errors == []


def test_dashboard_naming_flags_docs_tasks_reference_outside_task_plans(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "tasks").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "tasks" / "README.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("docs/tasks/README.md:1" in err for err in errors)


def test_dashboard_naming_flags_docs_epics_reference_outside_epic_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "epics").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "epics" / "README.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("docs/epics/README.md:1" in err for err in errors)


def test_workspace_settings_pass_with_safe_defaults(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    settings_path = repo / ".vscode" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["files.autoSave"] = "off"
    payload["files.refactoring.autoSave"] = False
    payload["editor.formatOnSave"] = False
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    errors = _check_workspace_settings(repo_root=repo)
    assert errors == []


def test_workspace_settings_fail_when_format_on_save_is_enabled(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    settings_path = repo / ".vscode" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["files.autoSave"] = "off"
    payload["files.refactoring.autoSave"] = False
    payload["editor.formatOnSave"] = True
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    errors = _check_workspace_settings(repo_root=repo)
    assert any("editor.formatOnSave" in err for err in errors)


def test_branch_isolation_requires_vscode_main_guard_matcher(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    payload = json.loads((repo / ".github" / "hooks" / "terminal-guard.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in payload["hooks"]["PreToolUse"]
        if item.get("command") == "python3 .github/hooks/guard-main-branch.py"
    )
    entry.pop("matcher", None)
    (repo / ".github" / "hooks" / "terminal-guard.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    contract = _valid_contract()
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("guard-main-branch.py" in err and "scope" in err for err in errors)


def test_branch_isolation_requires_claude_main_guard_matcher(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    payload = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in payload["hooks"]["PreToolUse"]
        if any(
            hook.get("command") == 'bash "$CLAUDE_PROJECT_DIR/scripts/hooks/guard-main-branch.sh"'
            for hook in item.get("hooks", [])
        )
    )
    entry.pop("matcher", None)
    (repo / ".claude" / "settings.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    contract = _valid_contract()
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("guard-main-branch.sh" in err and "scope" in err for err in errors)


def test_real_contract_passes_run_checks() -> None:
    """Safety net: the committed harness-protocol.yaml plus real surfaces must pass."""
    contract = _load_contract()
    errors = run_checks(contract, check_api_surface=True)
    assert errors == [], errors
