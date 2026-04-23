from __future__ import annotations

import json
import subprocess
import shutil
import sys
from pathlib import Path

from scripts.check_skills import check_skills


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _valid_skill() -> str:
    return """---
name: demo
description: demo skill
mode: execution
context_budget: 100
makefile_target: review-dispatch
mcp_tools:
  - review_findings
tdd_gate: false
disable-model-invocation: false
---

# Demo

## Overview

Short overview.

## Trigger

Trigger text.

## Goal

Goal text.

## Canonical Policy

Policy text.

## Core Process

1. Do the thing.

## Common Rationalizations

- Rationalization.

## Red Flags

- Red flag.

## Recovery

Recovery text.

## Convergence Criteria

- Done.

## See Also

- None.
"""


def _make_repo(tmp_path: Path, skill_content: str) -> Path:
    repo = tmp_path / "repo"
    _write(repo / "Makefile", "review-dispatch:\n\t@true\n")
    _write(
        repo / "docs" / "agentic" / "maps" / "mcp-tool-routing.yaml",
        "always:\n  - agent-handoff-mcp\non_demand: {}\n",
    )
    _write(
        repo / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp" / "api.py",
        'TOOL_DESCRIPTIONS: dict[str, str] = {"review_findings": "x"}\n',
    )
    _write(repo / ".claude" / "skills" / "demo" / "SKILL.md", skill_content)
    _write(repo / "scripts" / "check_skills.py", (Path(__file__).with_name("check_skills.py")).read_text())
    _write(repo / "scripts" / "overlay_resolver.py", (Path(__file__).with_name("overlay_resolver.py")).read_text())
    return repo


def _write_overlay_manifest(repo: Path) -> None:
    manifest = {
        "schema_version": 1,
        "remote_clone_path": str(repo / ".agentic" / "remote"),
        "surfaces": {
            "skills": {
                "shared_root": ".claude/skills",
                "local_root": "local/.claude/skills",
            }
        },
    }
    _write(repo / ".agentic-overlay.json", json.dumps(manifest, indent=2) + "\n")


def test_missing_frontmatter_fails_with_named_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "# Demo\n")
    failures, exit_code = check_skills(repo_root=repo)
    assert exit_code == 1
    assert any("missing YAML frontmatter block" in failure for failure in failures)


def test_non_boolean_tdd_gate_fails_with_named_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill().replace("tdd_gate: false", "tdd_gate: nope"))
    failures, exit_code = check_skills(repo_root=repo)
    assert exit_code == 1
    assert any("`tdd_gate` must be a boolean" in failure for failure in failures)


def test_missing_required_section_fails_with_named_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill().replace("\n## Goal\n\nGoal text.\n", "\n"))
    failures, exit_code = check_skills(repo_root=repo)
    assert exit_code == 1
    assert any("missing required section `## Goal`" in failure for failure in failures)


def test_local_only_skill_is_validated_when_overlay_manifest_exists(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill())
    (repo / ".claude" / "skills" / "demo").rename(repo / ".claude" / "skills" / "demo.shared")
    _write(repo / "local" / ".claude" / "skills" / "demo" / "SKILL.md", _valid_skill())
    _write_overlay_manifest(repo)

    failures, exit_code = check_skills(repo_root=repo)

    assert exit_code == 0
    assert failures == []


def test_local_skill_wins_when_shared_skill_is_invalid(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "# broken shared skill\n")
    _write(repo / "local" / ".claude" / "skills" / "demo" / "SKILL.md", _valid_skill())
    _write_overlay_manifest(repo)

    failures, exit_code = check_skills(repo_root=repo)

    assert exit_code == 0
    assert failures == []


def test_broken_shared_skill_symlink_reports_overlay_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill())
    broken_target = repo / ".agentic" / "remote" / ".claude" / "skills" / "demo"
    skill_dir = repo / ".claude" / "skills" / "demo"
    shutil.rmtree(skill_dir)
    skill_dir.symlink_to(broken_target)
    _write_overlay_manifest(repo)

    failures, exit_code = check_skills(repo_root=repo)

    assert exit_code == 1
    assert any("BrokenOverlayError" in failure for failure in failures)
    assert any("agentic-bootstrap repair" in failure for failure in failures)


def test_broken_local_skill_symlink_reports_overlay_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill())
    broken_target = repo / ".agentic" / "remote" / "local" / ".claude" / "skills" / "demo"
    local_skill_dir = repo / "local" / ".claude" / "skills" / "demo"
    local_skill_dir.parent.mkdir(parents=True, exist_ok=True)
    local_skill_dir.symlink_to(broken_target)
    _write_overlay_manifest(repo)

    failures, exit_code = check_skills(repo_root=repo)

    assert exit_code == 1
    assert any("BrokenOverlayError" in failure for failure in failures)
    assert any("agentic-bootstrap repair" in failure for failure in failures)


def test_main_reports_flat_skill_count_without_overlay_manifest(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill())
    _write(repo / ".claude" / "skills" / "shared-only" / "SKILL.md", _valid_skill().replace("name: demo", "name: shared-only"))
    script_path = repo / "scripts" / "check_skills.py"
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
    assert result.stdout.strip() == "check-skills: OK (2 skills)"


def test_main_reports_overlay_source_breakdown_when_manifest_exists(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill())
    _write(repo / ".claude" / "skills" / "shared-only" / "SKILL.md", _valid_skill().replace("name: demo", "name: shared-only"))
    _write(repo / "local" / ".claude" / "skills" / "local-only" / "SKILL.md", _valid_skill().replace("name: demo", "name: local-only"))
    _write(repo / "local" / ".claude" / "skills" / "demo" / "SKILL.md", _valid_skill())
    _write_overlay_manifest(repo)
    script_path = repo / "scripts" / "check_skills.py"
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
    assert result.stdout.strip() == "check-skills: OK (3 skills; shared=1 local=1 overlapping=1)"


def test_malformed_overlay_manifest_reports_infrastructure_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, _valid_skill())
    (repo / ".agentic-overlay.json").write_text("{bad json\n", encoding="utf-8")

    failures, exit_code = check_skills(repo_root=repo)

    assert exit_code == 1
    assert failures == [
        "infrastructure error: overlay manifest is not valid JSON: "
        "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
    ]
