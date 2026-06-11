"""REFA-10 slice 2: merge-result characterization gate contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "apps" / "prototype-wp-alt-context"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "php-characterization.yml"
RUNNER = REPO_ROOT / "scripts" / "consumer-hooks" / "run-php-characterization.sh"
PRE_PUSH = REPO_ROOT / "scripts" / "consumer-hooks" / "git" / "pre-push"
CHARACTERIZATION_FILTER = (
    "AnalysisJobsControllerCharacterizationTest|"
    "ClusterMutationsCharacterizationTest|"
    "ClustersControllerCharacterizationTest"
)
OVERLAY_LIFECYCLE_HOOKS = (
    "post-checkout",
    "post-commit",
    "post-merge",
    "post-rewrite",
    "pre-commit",
)
HOOK_DIR = REPO_ROOT / "scripts" / "consumer-hooks" / "git"


def test_ci_workflow_runs_characterization_suites_on_main_prs() -> None:
    assert WORKFLOW.is_file(), "missing php-characterization CI workflow"
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in content
    assert "main" in content
    assert "vendor/bin/phpunit" in content
    assert CHARACTERIZATION_FILTER in content


def test_consumer_hooks_delegate_overlay_lifecycle_hooks() -> None:
    for hook_name in OVERLAY_LIFECYCLE_HOOKS:
        hook_path = HOOK_DIR / hook_name
        assert hook_path.exists(), f"missing consumer hook delegate: {hook_name}"
        target = hook_path.resolve()
        overlay_hook = (REPO_ROOT / "scripts" / "hooks" / "git" / hook_name).resolve()
        assert target == overlay_hook, f"{hook_name} must delegate to overlay hook"


def test_git_merge_can_retain_stale_slash_escaping(tmp_path: Path) -> None:
    """Prove the forked-before-fix vector: merge can land stale \\/ bytes in the tree."""
    base = tmp_path / "base.json"
    ours = tmp_path / "ours.json"
    theirs = tmp_path / "theirs.json"
    base.write_text('{"url":"http://example.test"}', encoding="utf-8")
    ours.write_text('{"url":"http:\\/\\/example.test"}', encoding="utf-8")
    theirs.write_text('{"url":"http://example.test"}', encoding="utf-8")
    proc = subprocess.run(
        ["git", "merge-file", str(ours), str(base), str(theirs)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    merged = ours.read_text(encoding="utf-8")
    assert "http:\\/\\/" in merged


def test_consumer_pre_push_extension_delegates_overlay_and_runs_gate() -> None:
    assert PRE_PUSH.is_file(), "missing consumer pre-push wrapper"
    content = PRE_PUSH.read_text(encoding="utf-8")
    assert "scripts/hooks/git/pre-push" in content
    assert "run-php-characterization.sh" in content


def test_characterization_runner_fails_on_injected_slash_escape_drift() -> None:
    assert RUNNER.is_file(), "missing characterization runner script"
    fixture = (
        PLUGIN_DIR
        / "tests"
        / "fixtures"
        / "clusters-read"
        / "list_top_unlabeled_local_projection"
        / "response.json"
    )
    original = fixture.read_text(encoding="utf-8")
    drifted = original.replace("http://", "http:\\/\\/")
    fixture.write_text(drifted, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["sh", str(RUNNER)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, proc.stdout + proc.stderr
    finally:
        fixture.write_text(original, encoding="utf-8")
        subprocess.run(
            [
                "sh",
                str(RUNNER),
            ],
            cwd=REPO_ROOT,
            check=True,
        )