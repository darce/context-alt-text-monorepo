from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _git_init_and_add(repo: Path) -> None:
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "HOME": str(repo)}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)

from scripts.check_harness_sync import (
    _format_success_message,
    _build_guard_fixture,
    _check_branch_isolation,
    _check_cold_start,
    _check_dashboard_naming,
    _check_hooks,
    _check_python_api_surface,
    _check_workspace_settings,
    _check_worktree_drift,
    _fixture_env,
    _load_contract,
    _load_python_exports,
    _main_guard_paths,
    _run_python_hook,
    _run_shell_hook,
    run_checks,
)
from scripts.overlay_resolver import resolve_surface


REPO_ROOT = Path(__file__).resolve().parents[1]
COPY_PATHS = (
    Path("scripts/check_harness_sync.py"),
    Path("scripts/overlay_resolver.py"),
    Path(".vscode/settings.json"),
    Path(".claude/settings.json"),
    Path(".codex/hooks.json"),
    Path(".github/hooks/guard-main-branch.py"),
    Path(".github/hooks/terminal-guard.json"),
    Path(".github/hooks/guard-worktree-drift.py"),
    Path("scripts/hooks/_active_task_context.py"),
    Path("scripts/hooks/_branch_isolation_guard.py"),
    Path("scripts/hooks/_guard_main_branch_inline.py"),
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
            "protected_main_surfaces": [
                {"pattern": "docs/tasks/**/*.md", "reason": "Task plans require feature branches"},
                {"pattern": "docs/assessments/**", "reason": "Assessments require feature branches"},
                {"pattern": "docs/scopes/**", "reason": "Scope notes require feature branches"},
                {"pattern": "docs/epics/**", "reason": "Epics require feature branches"},
                {"pattern": "docs/specs/**", "reason": "Specs require feature branches"},
                {"pattern": "docs/adrs/**", "reason": "ADRs require feature branches"},
                {"pattern": "packages/*/docs/tasks/**", "reason": "Package task plans require feature branches"},
                {"pattern": "packages/*/docs/assessments/**", "reason": "Package assessments require feature branches"},
                {"pattern": "packages/*/docs/specs/**", "reason": "Package specs require feature branches"},
                {"pattern": "packages/*/docs/epics/**", "reason": "Package epics require feature branches"},
                {"pattern": "packages/*/docs/adrs/**", "reason": "Package ADRs require feature branches"},
            ],
            "permitted_main_surfaces": [{"pattern": "CLAUDE.md", "reason": "Agent dispatcher"}],
            "enforcers": [
                {"path": ".github/hooks/guard-main-branch.py", "harness": "vscode"},
                {"path": "scripts/hooks/guard-main-branch.sh", "harness": "claude"},
            ],
        },
        "hooks": {
            "pre_tool_use": [],
            "post_tool_use": [],
        },
    }


def _contract_with_codex_hook() -> dict:
    """A contract that declares a codex-specific hook, for codex-detection tests."""
    contract = _valid_contract()
    contract["hooks"]["post_tool_use"] = [
        {
            "id": "regenerate-task-views",
            "matcher": "mcp__workbay-handoff-mcp__record_event|mcp__workbay-handoff-mcp__review_findings|mcp__workbay-handoff-mcp__review_runs|mcp__workbay-handoff-mcp__set_handoff_state|mcp__workbay-handoff-mcp__update_task_status",
            "claude_command": 'bash "$CLAUDE_PROJECT_DIR/scripts/hooks/regenerate-task-views.sh"',
            "vscode_command": "bash scripts/hooks/regenerate-task-views.sh",
            "codex_command": 'bash "$(git rev-parse --show-toplevel)/scripts/hooks/regenerate-task-views.sh"',
        }
    ]
    return contract


def _copy_handoff_package_src(destination: Path) -> None:
    local_src = REPO_ROOT / "packages" / "workbay-handoff-mcp" / "src"
    if local_src.exists():
        shutil.copytree(local_src, destination)
        return

    spec = importlib.util.find_spec("workbay_handoff_mcp")
    if spec is None:
        raise FileNotFoundError("workbay_handoff_mcp package source is not available for fixture setup")

    package_dir: Path | None = None
    if spec.submodule_search_locations:
        package_dir = Path(next(iter(spec.submodule_search_locations))).resolve()
    elif spec.origin:
        package_dir = Path(spec.origin).resolve().parent

    if package_dir is None:
        raise FileNotFoundError("workbay_handoff_mcp package source is not available for fixture setup")

    # Copy only the package directory itself — never `package_dir.parent`, which
    # for an installed (non-vendored) package is the entire site-packages tree.
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        package_dir,
        destination / package_dir.name,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
    )


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
    package_src = repo / "packages" / "workbay-handoff-mcp" / "src"
    package_src.parent.mkdir(parents=True, exist_ok=True)
    _copy_handoff_package_src(package_src)
    contract_path = repo / "docs" / "workbay" / "contracts" / "harness-protocol.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(_valid_contract(), sort_keys=False), encoding="utf-8")
    return repo


def _write_overlay_manifest(repo: Path) -> None:
    manifest = {
        "schema_version": 2,
        "remote_clone_path": str(repo / ".workstate" / "remote"),
        "surfaces": {
            "contracts": {
                "shared_root": ".workbay/remote/docs/workbay/contracts",
                "local_root": "local/docs/workbay/contracts",
            }
        },
    }
    (repo / ".workbay-bootstrap.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _write_importable_handoff_package(site_packages: Path, *, exports: list[str]) -> None:
    package_root = site_packages / "workbay_handoff_mcp"
    package_root.mkdir(parents=True, exist_ok=True)
    exported = ", ".join(repr(name) for name in exports)
    (package_root / "__init__.py").write_text(f"__all__ = [{exported}]\n", encoding="utf-8")


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


def test_branch_isolation_blocks_protected_main_surface(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    tmpdir, fixture_repo = _build_guard_fixture(contract, repo_root=repo)
    try:
        env = _fixture_env(fixture_repo)
        vscode_path, claude_path = _main_guard_paths(contract)
        vscode_guard = fixture_repo / vscode_path
        claude_guard = fixture_repo / claude_path
        planning_path = fixture_repo / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
        planning_path.parent.mkdir(parents=True, exist_ok=True)

        _, output, _ = _run_python_hook(
            vscode_guard,
            {"toolName": "create_file", "toolInput": {"filePath": str(planning_path)}},
            cwd=fixture_repo,
            env=env,
        )
        assert output is not None
        assert output["hookSpecificOutput"]["permissionDecision"] == "block"

        shell_code, _, shell_stderr = _run_shell_hook(
            claude_guard,
            {"tool_input": {"file_path": str(planning_path)}},
            cwd=fixture_repo,
            env=env,
        )
        assert shell_code == 2
        assert "BLOCKED" in shell_stderr
    finally:
        tmpdir.cleanup()


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


def test_branch_isolation_fails_when_protected_surface_reason_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    contract["branch_isolation"]["protected_main_surfaces"][0]["reason"] = ""
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("protected_main_surfaces[0]" in err and "reason" in err for err in errors)


def test_branch_isolation_fails_when_planning_surface_is_permitted_on_main(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    contract["branch_isolation"]["permitted_main_surfaces"] = [
        {"pattern": "docs/specs/**/*.md", "reason": "stale policy"}
    ]
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("must not include planning pattern" in err for err in errors)


def test_worktree_drift_passes_fixture_harness(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    errors = _check_worktree_drift(contract, repo_root=repo)
    assert errors == []


def test_dashboard_naming_flags_live_surface_reference(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "workbay" / "rules").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "workbay" / "rules" / "workflow.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    _git_init_and_add(repo)
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("workflow.md:1" in err for err in errors)


def test_dashboard_naming_ignores_untracked_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _git_init_and_add(repo)
    stray_dir = repo / ".claude" / "worktrees" / "stale"
    stray_dir.mkdir(parents=True, exist_ok=True)
    (stray_dir / "stray.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    errors = _check_dashboard_naming(repo_root=repo)
    assert errors == []


def test_dashboard_naming_flags_task_plan_mentions_without_allow_marker(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "tasks" / "17.0").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "tasks" / "17.0" / "E17-8-sample-task-plan.md").write_text(
        "Historical DASHBOARD.md note\n",
        encoding="utf-8",
    )
    _git_init_and_add(repo)
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("E17-8-sample-task-plan.md:1" in err for err in errors)


def test_dashboard_naming_honors_allow_marker(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "tasks" / "17.0").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "tasks" / "17.0" / "E17-8-sample-task-plan.md").write_text(
        "Historical DASHBOARD.md note <!-- lint-dashboard-txt: allow -->\n",
        encoding="utf-8",
    )
    _git_init_and_add(repo)
    errors = _check_dashboard_naming(repo_root=repo)
    assert errors == []


def test_dashboard_naming_flags_docs_tasks_reference_outside_task_plans(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "tasks").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "tasks" / "README.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    _git_init_and_add(repo)
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("docs/tasks/README.md:1" in err for err in errors)


def test_dashboard_naming_flags_docs_epics_reference_outside_epic_files(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "docs" / "epics").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "epics" / "README.md").write_text("Use DASHBOARD.md here\n", encoding="utf-8")
    _git_init_and_add(repo)
    errors = _check_dashboard_naming(repo_root=repo)
    assert any("docs/epics/README.md:1" in err for err in errors)


def test_workspace_settings_pass_with_safe_defaults(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    settings_path = repo / ".vscode" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["files.autoSave"] = "off"
    payload["files.refactoring.autoSave"] = False
    payload["editor.formatOnSave"] = False
    payload["terminal.integrated.agentHostProfile.osx"] = {"path": "/bin/bash"}
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    errors = _check_workspace_settings(repo_root=repo)
    assert errors == []


def test_workspace_settings_fail_when_format_on_save_is_enabled(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    settings_path = repo / ".vscode" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["files.autoSave"] = "off"
    payload["files.refactoring.autoSave"] = False
    payload["terminal.integrated.agentHostProfile.osx"] = {"path": "/bin/bash"}
    payload["editor.formatOnSave"] = True
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    errors = _check_workspace_settings(repo_root=repo)
    assert any("editor.formatOnSave" in err for err in errors)


def test_workspace_settings_fail_when_agent_host_profile_is_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    settings_path = repo / ".vscode" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["files.autoSave"] = "off"
    payload["files.refactoring.autoSave"] = False
    payload["editor.formatOnSave"] = False
    payload.pop("terminal.integrated.agentHostProfile.osx", None)
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    errors = _check_workspace_settings(repo_root=repo)
    assert any("terminal.integrated.agentHostProfile.osx" in err for err in errors)


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


def test_hooks_fail_when_codex_regenerate_task_views_hook_is_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    payload = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    payload["hooks"]["PostToolUse"] = [
        entry
        for entry in payload["hooks"]["PostToolUse"]
        if "regenerate-task-views.sh" not in json.dumps(entry)
    ]
    (repo / ".codex" / "hooks.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    errors = _check_hooks(_contract_with_codex_hook(), repo_root=repo)
    assert any("missing Codex hook `regenerate-task-views`" in err for err in errors)


def test_real_contract_passes_run_checks() -> None:
    """Safety net: the committed harness-protocol.yaml plus real surfaces must pass."""
    contract = _load_contract()
    errors = run_checks(contract, check_api_surface=True)
    assert errors == [], errors


def test_load_contract_falls_back_to_live_contract_surface_when_remote_root_is_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    _write_overlay_manifest(repo)

    contract = _load_contract(repo_root=repo)

    assert contract["version"] == 1
    assert _format_success_message(repo_root=repo) == "check-harness-sync: OK (contracts=1; shared=1 local=0 overlapping=0)"


def test_python_api_surface_falls_back_to_importable_package_when_local_source_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _write_repo(tmp_path)
    shutil.rmtree(repo / "packages" / "workbay-handoff-mcp")
    site_packages = tmp_path / "site-packages"
    _write_importable_handoff_package(site_packages, exports=["RuntimeConfig", "configure_runtime"])
    monkeypatch.syspath_prepend(str(site_packages))
    # The real package may already be imported by an earlier test; drop it so
    # find_spec re-scans sys.path and resolves the prepended fake fixture.
    monkeypatch.delitem(sys.modules, "workbay_handoff_mcp", raising=False)

    exports = _load_python_exports(repo_root=repo)

    assert exports == {"RuntimeConfig", "configure_runtime"}
    assert _check_python_api_surface(
        {"python_api_fallback": {"required_exports": ["RuntimeConfig", "configure_runtime"]}},
        repo_root=repo,
    ) == []


def test_load_contract_uses_overlay_manifest_with_top_level_replace_semantics(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    shared_contract = repo / ".workstate" / "remote" / "docs" / "workbay" / "contracts" / "harness-protocol.yaml"
    shared_contract.parent.mkdir(parents=True, exist_ok=True)
    shared_contract.write_text(yaml.safe_dump(_valid_contract(), sort_keys=False), encoding="utf-8")

    local_contract = repo / "local" / "docs" / "workbay" / "contracts" / "harness-protocol.yaml"
    local_contract.parent.mkdir(parents=True, exist_ok=True)
    local_contract.write_text(
        yaml.safe_dump(
            {
                "branch_isolation": {
                    "protected_branches": ["release"],
                    "code_roots": ["apps/"],
                    "protected_extensions": [".py"],
                    "root_protected_files": ["Makefile"],
                    "protected_main_surfaces": [
                        {"pattern": "docs/tasks/**/*.md", "reason": "Task plans require feature branches"}
                    ],
                    "permitted_main_surfaces": [{"pattern": "CLAUDE.md", "reason": "Agent dispatcher"}],
                    "enforcers": [
                        {"path": ".github/hooks/guard-main-branch.py", "harness": "vscode"},
                        {"path": "scripts/hooks/guard-main-branch.sh", "harness": "claude"},
                    ],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_overlay_manifest(repo)

    contract = _load_contract(repo_root=repo)

    assert contract["branch_isolation"]["protected_branches"] == ["release"]
    assert contract["cold_start"] == _valid_contract()["cold_start"]


def test_branch_isolation_allows_permitted_surface_when_unrelated_protected_paths_are_dirty(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract()
    tmpdir, fixture_repo = _build_guard_fixture(contract, repo_root=repo)
    try:
        env = _fixture_env(fixture_repo)
        vscode_path, claude_path = _main_guard_paths(contract)
        vscode_guard = fixture_repo / vscode_path
        claude_guard = fixture_repo / claude_path
        allowed_path = fixture_repo / "CLAUDE.md"

        dirty_code_path = fixture_repo / "apps" / "fixture.py"
        dirty_code_path.parent.mkdir(parents=True, exist_ok=True)
        dirty_code_path.write_text("print('dirty main')\n", encoding="utf-8")

        _, output, _ = _run_python_hook(
            vscode_guard,
            {"toolName": "create_file", "toolInput": {"filePath": str(allowed_path)}},
            cwd=fixture_repo,
            env=env,
        )
        assert output is None

        shell_code, _, _ = _run_shell_hook(
            claude_guard,
            {"tool_input": {"file_path": str(allowed_path)}},
            cwd=fixture_repo,
            env=env,
        )
        assert shell_code == 0
    finally:
        tmpdir.cleanup()


def test_overlay_manifest_contract_doc_example_round_trips_with_resolver(tmp_path: Path) -> None:
    contract_doc = REPO_ROOT / "docs" / "workbay" / "contracts" / "overlay-manifest.yaml"
    assert contract_doc.exists(), "overlay-manifest contract doc missing"

    payload = yaml.safe_load(contract_doc.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    example_manifest = payload.get("example_manifest")
    assert isinstance(example_manifest, dict), "overlay-manifest contract doc must define example_manifest"
    assert isinstance(example_manifest.get("remote_sha"), str) and example_manifest["remote_sha"]
    surfaces = example_manifest.get("surfaces")
    assert isinstance(surfaces, list)
    assert {surface["path"] for surface in surfaces} >= {
        ".claude/skills",
        "local/.claude/skills",
        ".github/hooks",
        "scripts/hooks",
        "docs/workbay/contracts",
    }

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".claude" / "skills" / "shared-only").mkdir(parents=True)
    (repo / ".claude" / "skills" / "shared-only" / "SKILL.md").write_text("# shared\n")
    (repo / "local" / ".claude" / "skills" / "local-only").mkdir(parents=True)
    (repo / "local" / ".claude" / "skills" / "local-only" / "SKILL.md").write_text("# local\n")
    (repo / ".workbay-bootstrap.json").write_text(json.dumps(example_manifest, indent=2) + "\n", encoding="utf-8")

    resolved = resolve_surface("skills", repo)

    assert [entry.effective_path.name for entry in resolved] == ["local-only", "shared-only"]
    assert [entry.source for entry in resolved] == ["local", "shared"]


def test_overlay_manifest_hooks_surface_includes_all_hook_subtrees(tmp_path: Path) -> None:
    contract_doc = REPO_ROOT / "docs" / "workbay" / "contracts" / "overlay-manifest.yaml"
    payload = yaml.safe_load(contract_doc.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    example_manifest = payload.get("example_manifest")
    assert isinstance(example_manifest, dict)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".github" / "hooks").mkdir(parents=True)
    (repo / ".github" / "hooks" / "terminal-guard.json").write_text("{}\n")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "hooks" / "guard-main-branch.sh").write_text("#!/usr/bin/env bash\n")
    (repo / "scripts" / "hooks" / "git").mkdir(parents=True)
    (repo / "scripts" / "hooks" / "git" / "pre-push").write_text("#!/bin/sh\n")
    (repo / ".workbay-bootstrap.json").write_text(json.dumps(example_manifest, indent=2) + "\n", encoding="utf-8")

    resolved = resolve_surface("hooks", repo)

    assert {
        entry.effective_path.relative_to(repo).as_posix(): entry.source
        for entry in resolved
    } == {
        ".github/hooks/terminal-guard.json": "shared",
        "scripts/hooks/guard-main-branch.sh": "shared",
        "scripts/hooks/git/pre-push": "shared",
    }


def test_hooks_surface_without_overlay_manifest_includes_github_and_scripts_hooks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".github" / "hooks").mkdir(parents=True)
    (repo / ".github" / "hooks" / "terminal-guard.json").write_text("{}\n", encoding="utf-8")
    (repo / "scripts" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "hooks" / "guard-main-branch.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    resolved = resolve_surface("hooks", repo)

    assert {
        entry.effective_path.relative_to(repo).as_posix(): entry.source
        for entry in resolved
    } == {
        ".github/hooks/terminal-guard.json": "shared",
        "scripts/hooks/guard-main-branch.sh": "shared",
    }


def test_main_reports_overlay_contract_source_breakdown_when_manifest_exists(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    shared_contract = repo / ".workstate" / "remote" / "docs" / "workbay" / "contracts" / "harness-protocol.yaml"
    shared_contract.parent.mkdir(parents=True, exist_ok=True)
    shared_contract.write_text(yaml.safe_dump(_valid_contract(), sort_keys=False), encoding="utf-8")

    local_contract = repo / "local" / "docs" / "workbay" / "contracts" / "harness-protocol.yaml"
    local_contract.parent.mkdir(parents=True, exist_ok=True)
    local_contract.write_text(yaml.safe_dump(_valid_contract(), sort_keys=False), encoding="utf-8")
    _write_overlay_manifest(repo)

    assert _format_success_message(repo_root=repo) == (
        "check-harness-sync: OK (contracts=1; shared=0 local=0 overlapping=1)"
    )


def test_main_runs_by_absolute_path_outside_repo_root(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    script_path = repo / "scripts" / "check_harness_sync.py"
    outside = tmp_path / "outside"
    outside.mkdir()

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=outside,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "check-harness-sync: OK"


def test_main_reports_malformed_overlay_manifest_as_infrastructure_error(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / ".workbay-bootstrap.json").write_text("{bad json\n", encoding="utf-8")
    script_path = repo / "scripts" / "check_harness_sync.py"
    outside = tmp_path / "outside"
    outside.mkdir()

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=outside,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "check-harness-sync: infrastructure error:" in result.stderr
