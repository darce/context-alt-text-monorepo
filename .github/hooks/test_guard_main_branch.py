"""Tests for the VS Code PreToolUse branch-isolation hook."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


HOOK_SCRIPT = Path(__file__).parent / "guard-main-branch.py"

_spec = importlib.util.spec_from_file_location("guard_main_branch", HOOK_SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_check_file_edit = _mod._check_file_edit
_extract_candidate_paths = _mod._extract_candidate_paths
HELPER_DIR = HOOK_SCRIPT.parents[2] / "scripts" / "hooks"
sys.path.insert(0, str(HELPER_DIR))

from _harness_protocol import BranchIsolationPolicy  # noqa: E402


POLICY = BranchIsolationPolicy(
    code_roots=("apps/", "packages/", "scripts/", ".github/hooks/", ".claude/", "mk/"),
    protected_extensions=(".py", ".ts", ".tsx", ".js", ".jsx", ".php", ".sql", ".sh", ".css", ".scss", ".mk"),
    root_protected_files=("Makefile",),
    permitted_main_surfaces=(),
)


def _run_hook(payload: dict, cwd: str | None = None) -> tuple[int, dict | None]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        cwd=cwd,
    )
    stdout_json = None
    if proc.stdout.strip():
        stdout_json = json.loads(proc.stdout)
    return proc.returncode, stdout_json


def test_extract_candidate_paths_from_apply_patch() -> None:
    patch = """*** Begin Patch
*** Update File: /repo/apps/prototype-description-service/api/main.py
@@
-old
+new
*** Add File: /repo/docs/notes.md
+hello
*** End Patch"""
    result = _extract_candidate_paths("apply_patch", {"input": patch})
    assert result == [
        "/repo/apps/prototype-description-service/api/main.py",
        "/repo/docs/notes.md",
    ]


def test_check_file_edit_blocks_code_paths_on_main() -> None:
    result = _check_file_edit(
        "create_file",
        {"filePath": "/repo/apps/prototype-description-service/api/main.py"},
        branch="main",
        repo_root="/repo",
        policy=POLICY,
    )
    assert result == ("main", ["apps/prototype-description-service/api/main.py"])


def test_check_file_edit_allows_docs_on_main() -> None:
    result = _check_file_edit(
        "create_file",
        {"filePath": "/repo/docs/agentic/rules/development-workflow.md"},
        branch="main",
        repo_root="/repo",
        policy=POLICY,
    )
    assert result is None


def test_check_file_edit_allows_code_on_feature_branch() -> None:
    patch = """*** Begin Patch
*** Update File: /repo/packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py
@@
-old
+new
*** End Patch"""
    result = _check_file_edit(
        "apply_patch",
        {"input": patch},
        branch="feature/e15-branch-guard",
        repo_root="/repo",
        policy=POLICY,
    )
    assert result is None


def test_check_file_edit_blocks_mixed_patch_when_code_file_present() -> None:
    patch = """*** Begin Patch
*** Update File: /repo/docs/agentic/rules/development-workflow.md
@@
-old
+new
*** Update File: /repo/packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py
@@
-old
+new
*** End Patch"""
    result = _check_file_edit(
        "apply_patch",
        {"input": patch},
        branch="main",
        repo_root="/repo",
        policy=POLICY,
    )
    assert result == ("main", ["packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py"])


def test_check_file_edit_blocks_root_makefile_on_main() -> None:
    result = _check_file_edit(
        "replace_string_in_file",
        {"filePath": "/repo/Makefile"},
        branch="main",
        repo_root="/repo",
        policy=POLICY,
    )
    assert result == ("main", ["Makefile"])


def test_check_file_edit_blocks_scripts_path_on_main() -> None:
    result = _check_file_edit(
        "multi_replace_string_in_file",
        {"file_path": "/repo/scripts/check_skills.py"},
        branch="main",
        repo_root="/repo",
        policy=POLICY,
    )
    assert result == ("main", ["scripts/check_skills.py"])


def test_hook_emits_block_json_for_create_file_on_main() -> None:
    payload = {
        "toolName": "create_file",
        "toolInput": {"filePath": "/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/api/main.py"},
    }
    exit_code, output = _run_hook(payload, cwd="/Users/daniel/Development/context-alt-text-monorepo")
    assert exit_code == 0
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "block"


def test_hook_allows_doc_create_on_main() -> None:
    payload = {
        "toolName": "create_file",
        "toolInput": {"filePath": "/Users/daniel/Development/context-alt-text-monorepo/docs/agentic/rules/development-workflow.md"},
    }
    exit_code, output = _run_hook(payload, cwd="/Users/daniel/Development/context-alt-text-monorepo")
    assert exit_code == 0
    assert output is None
