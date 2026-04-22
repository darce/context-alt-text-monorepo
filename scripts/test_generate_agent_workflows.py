from __future__ import annotations

from pathlib import Path

from scripts.generate_agent_workflows import (
    CODEX_ROUTER_BEGIN,
    CODEX_ROUTER_END,
    GENERATOR_TAG,
    _check_codex_skill_symlinks,
    _check_outputs,
    _expected_codex_skill_symlinks,
    _expected_outputs,
    _sync_codex_router_consumers,
    _write_codex_skill_symlinks,
)


def _manifest() -> dict:
    return {
        "version": 1,
        "commands": [
            {
                "command_id": "branch-review",
                "skill": "branch-review",
                "makefile_target": "make review-run",
                "description": "Implementation branch review workflow.",
                "execution_context": "Use for implementation branch diffs.",
                "argument_schema": [],
                "loop": ["run the branch review checklist"],
            },
            {
                "command_id": "planning-review",
                "skill": "planning-review",
                "makefile_target": "make plan-review DOC=<path>",
                "description": "Formal planning review workflow.",
                "execution_context": "Use for planning artifacts before implementation.",
                "argument_schema": [
                    {
                        "name": "doc",
                        "required": True,
                        "description": "Planning document path to review.",
                    }
                ],
                "loop": ["record findings and verdict in MCP"],
            },
        ],
    }


def test_expected_outputs_include_codex_router_artifact(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    claude_out = repo / ".claude" / "commands"
    prompts_out = repo / ".github" / "prompts"
    codex_out = repo / "docs" / "agentic" / "generated"

    outputs = _expected_outputs(_manifest(), claude_out, prompts_out, codex_out)

    router_path = codex_out / "codex-command-router.md"
    assert router_path in outputs
    assert outputs[router_path].startswith(GENERATOR_TAG)
    assert "/branch-review" in outputs[router_path]
    assert "/planning-review" in outputs[router_path]


def test_expected_outputs_render_planning_review_gap_id_and_dashboard_steps(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    claude_out = repo / ".claude" / "commands"
    prompts_out = repo / ".github" / "prompts"
    codex_out = repo / "docs" / "agentic" / "generated"
    manifest = _manifest()
    manifest["commands"][1]["loop"] = [
        "record findings and verdict in MCP",
        "print stable handoff gap ids (`finding_id`) when reporting findings",
        "refresh DASHBOARD.txt after state-changing handoff writes",
    ]

    outputs = _expected_outputs(manifest, claude_out, prompts_out, codex_out)

    planning_command = outputs[claude_out / "planning-review.md"]
    planning_prompt = outputs[prompts_out / "planning-review.prompt.md"]
    assert "print stable handoff gap ids (`finding_id`) when reporting findings" in planning_command
    assert "refresh DASHBOARD.txt after state-changing handoff writes" in planning_command
    assert "print stable handoff gap ids (`finding_id`) when reporting findings" in planning_prompt
    assert "refresh DASHBOARD.txt after state-changing handoff writes" in planning_prompt


def test_expected_outputs_render_branch_review_decision_and_dashboard_steps(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    claude_out = repo / ".claude" / "commands"
    prompts_out = repo / ".github" / "prompts"
    codex_out = repo / "docs" / "agentic" / "generated"
    manifest = _manifest()
    manifest["commands"][0]["loop"] = [
        "load the latest slice packet or branch diff",
        "when the review is packet-backed, print the handoff decision string (`decision`) and numeric row id (`decision_id`)",
        "refresh DASHBOARD.txt after state-changing handoff writes",
    ]

    outputs = _expected_outputs(manifest, claude_out, prompts_out, codex_out)

    branch_command = outputs[claude_out / "branch-review.md"]
    branch_prompt = outputs[prompts_out / "branch-review.prompt.md"]
    assert "print the handoff decision string (`decision`) and numeric row id (`decision_id`)" in branch_command
    assert "refresh DASHBOARD.txt after state-changing handoff writes" in branch_command
    assert "print the handoff decision string (`decision`) and numeric row id (`decision_id`)" in branch_prompt
    assert "refresh DASHBOARD.txt after state-changing handoff writes" in branch_prompt


def test_check_outputs_fails_when_codex_router_is_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    claude_out = repo / ".claude" / "commands"
    prompts_out = repo / ".github" / "prompts"
    codex_out = repo / "docs" / "agentic" / "generated"
    outputs = _expected_outputs(_manifest(), claude_out, prompts_out, codex_out)

    for path, content in outputs.items():
        if path == codex_out / "codex-command-router.md":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    exit_code = _check_outputs(outputs, claude_out, prompts_out, codex_out)

    assert exit_code == 1


def test_sync_codex_router_consumers_rewrites_marked_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    instructions = repo / "docs" / "agentic" / "instructions.md"
    claude = repo / "CLAUDE.md"
    instructions.parent.mkdir(parents=True, exist_ok=True)
    instructions.write_text(
        f"## Portable Command Router\n\n{CODEX_ROUTER_BEGIN}\nold\n{CODEX_ROUTER_END}\n"
    )
    claude.write_text(
        f"## Key Triggers\n\n{CODEX_ROUTER_BEGIN}\nold\n{CODEX_ROUTER_END}\n"
    )

    failures = _sync_codex_router_consumers(_manifest(), repo, check=False)

    assert failures == []
    assert "/branch-review" in instructions.read_text()
    assert "/planning-review" in claude.read_text()


def test_check_codex_router_consumers_detects_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    instructions = repo / "docs" / "agentic" / "instructions.md"
    claude = repo / "CLAUDE.md"
    instructions.parent.mkdir(parents=True, exist_ok=True)
    instructions.write_text(
        "## Portable Command Router\n\n"
        f"{CODEX_ROUTER_BEGIN}\nwrong\n{CODEX_ROUTER_END}\n"
    )
    claude.write_text(
        f"## Key Triggers\n\n{CODEX_ROUTER_BEGIN}\nwrong\n{CODEX_ROUTER_END}\n"
    )

    failures = _sync_codex_router_consumers(_manifest(), repo, check=True)

    assert len(failures) == 2


def _codex_skills_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a repo with .claude/skills/<slug>/SKILL.md for each manifest entry."""
    repo = tmp_path / "repo"
    claude_skills = repo / ".claude" / "skills"
    codex_skills = repo / ".codex" / "skills"
    for command in _manifest()["commands"]:
        skill_dir = claude_skills / command["skill"]
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {command['skill']}\n")
    return repo, claude_skills, codex_skills


def test_expected_codex_skill_symlinks_maps_every_manifest_entry(
    tmp_path: Path,
) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)

    mapping = _expected_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert set(mapping.keys()) == {
        codex_skills / "branch-review",
        codex_skills / "planning-review",
    }
    # Each symlink target is a relative path back to the canonical .claude/skills entry.
    assert mapping[codex_skills / "branch-review"] == Path(
        "../../.claude/skills/branch-review"
    )
    assert mapping[codex_skills / "planning-review"] == Path(
        "../../.claude/skills/planning-review"
    )


def test_write_codex_skill_symlinks_creates_correct_symlinks(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)

    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    for slug in ("branch-review", "planning-review"):
        link = codex_skills / slug
        assert link.is_symlink(), f"{link} should be a symlink"
        resolved = (link.parent / link.readlink()).resolve()
        assert resolved == (claude_skills / slug).resolve()
        # Symlink resolves through to an actual SKILL.md file.
        assert (link / "SKILL.md").is_file()


def test_write_codex_skill_symlinks_is_idempotent(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)

    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)
    first = {p: p.readlink() for p in codex_skills.iterdir() if p.is_symlink()}
    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)
    second = {p: p.readlink() for p in codex_skills.iterdir() if p.is_symlink()}

    assert first == second


def test_write_codex_skill_symlinks_removes_stale_entries(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    codex_skills.mkdir(parents=True, exist_ok=True)
    stale = codex_skills / "retired-skill"
    stale.symlink_to(Path("../../.claude/skills/retired-skill"))

    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert not stale.exists() and not stale.is_symlink()


def test_check_codex_skill_symlinks_passes_when_current(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert failures == []


def test_check_codex_skill_symlinks_flags_missing(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    codex_skills.mkdir(parents=True, exist_ok=True)

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert len(failures) == 2
    assert any("branch-review" in f for f in failures)
    assert any("planning-review" in f for f in failures)


def test_check_codex_skill_symlinks_flags_wrong_target(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    codex_skills.mkdir(parents=True, exist_ok=True)
    (codex_skills / "branch-review").symlink_to(
        Path("../../.claude/skills/planning-review")
    )
    (codex_skills / "planning-review").symlink_to(
        Path("../../.claude/skills/planning-review")
    )

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert any("branch-review" in f and "drift" in f.lower() for f in failures)


def test_check_codex_skill_symlinks_flags_stale_entries(tmp_path: Path) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)
    (codex_skills / "retired").symlink_to(Path("../../.claude/skills/retired"))

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert any("retired" in f for f in failures)


def test_check_codex_skill_symlinks_flags_plain_file_squatting_on_slug(
    tmp_path: Path,
) -> None:
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    codex_skills.mkdir(parents=True, exist_ok=True)
    # A plain directory (not a symlink) at the expected path should be flagged —
    # duplicated content would drift from the canonical .claude/skills entry.
    (codex_skills / "branch-review").mkdir()
    (codex_skills / "branch-review" / "SKILL.md").write_text("stale copy")
    (codex_skills / "planning-review").symlink_to(
        Path("../../.claude/skills/planning-review")
    )

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert any("branch-review" in f for f in failures)


def test_check_codex_skill_symlinks_flags_manifest_entry_with_missing_source(
    tmp_path: Path,
) -> None:
    """Manifest entry whose .claude/skills/<slug> source is gone must fail --check.

    Regression guard for E17-12-BR-01: previously the check silently skipped
    manifest entries with missing sources, allowing orphan /<skill> routes to
    escape the gate when both .claude/skills/<slug> and .codex/skills/<slug>
    were absent.
    """
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)
    # Delete the canonical source AND its generated symlink so neither the
    # first-loop missing-link check nor the stale-entry scan would catch it.
    import shutil as _sh

    _sh.rmtree(claude_skills / "branch-review")
    (codex_skills / "branch-review").unlink()

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert any("branch-review" in f and "source" in f.lower() for f in failures), (
        failures
    )


def test_check_codex_skill_symlinks_flags_source_missing_skill_md(
    tmp_path: Path,
) -> None:
    """Manifest skill whose source directory exists but lacks SKILL.md must fail --check.

    Regression guard for E17-12-BR-02: Codex only discovers
    <cwd>/.codex/skills/<slug>/SKILL.md, so a canonical .claude/skills/<slug>
    directory without SKILL.md yields a broken $-skill on a fresh clone even
    though the symlink resolves.
    """
    repo, claude_skills, codex_skills = _codex_skills_fixture(tmp_path)
    _write_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)
    (claude_skills / "branch-review" / "SKILL.md").unlink()

    failures = _check_codex_skill_symlinks(_manifest(), codex_skills, claude_skills)

    assert any("branch-review" in f and "SKILL.md" in f for f in failures), failures
