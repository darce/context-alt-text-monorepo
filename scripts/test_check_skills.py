from __future__ import annotations

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
    return repo


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
