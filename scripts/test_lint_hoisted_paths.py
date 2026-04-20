from __future__ import annotations

import json
from pathlib import Path

from scripts.lint_hoisted_paths import lint_hoisted_paths


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_lint_hoisted_paths_reports_monorepo_only_literals(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / ".github" / "prompts" / "bootstrap.md", "Use /Users/daniel/Development/context-alt-text-monorepo.\n")
    _write(repo / "scripts" / "hooks" / "git" / "pre-push", "#!/bin/sh\ncat .python-version\n")

    findings, exit_code = lint_hoisted_paths(repo_root=repo)

    assert exit_code == 1
    assert any(".github/prompts/bootstrap.md:1" in finding for finding in findings)
    assert any("hardcoded-user-home" in finding for finding in findings)
    assert any("repo-name-assumption" in finding for finding in findings)
    assert any("scripts/hooks/git/pre-push:2" in finding for finding in findings)
    assert any("python-version-probe" in finding for finding in findings)


def test_lint_hoisted_paths_ignores_hook_test_fixtures(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / ".github" / "hooks" / "test_guard_main_branch.py", 'HELPER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "hooks"\n')
    _write(repo / ".claude" / "commands" / "portable.md", "No monorepo literals here.\n")

    findings, exit_code = lint_hoisted_paths(repo_root=repo)

    assert findings == []
    assert exit_code == 0


def test_lint_hoisted_paths_scans_overlay_resolved_local_entries(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    manifest = {
        "schema_version": 1,
        "remote_clone_path": ".agentic/remote",
        "remote_sha": "0123456789abcdef0123456789abcdef01234567",
        "surfaces": {
            "skills": {
                "shared_root": ".agentic/remote/.claude/skills",
                "local_root": ".claude/skills",
            }
        },
    }
    _write(repo / ".agentic-overlay.json", json.dumps(manifest))
    _write(repo / ".agentic" / "remote" / ".claude" / "skills" / "demo" / "SKILL.md", "clean shared skill\n")
    _write(repo / ".claude" / "skills" / "demo" / "SKILL.md", "Use the context-alt-text-monorepo lane copy.\n")

    findings, exit_code = lint_hoisted_paths(repo_root=repo)

    assert exit_code == 1
    assert any(".claude/skills/demo/SKILL.md:1" in finding for finding in findings)
    assert any("repo-name-assumption" in finding for finding in findings)