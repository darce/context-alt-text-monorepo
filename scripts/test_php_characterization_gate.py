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


def test_ci_workflow_runs_characterization_suites_on_main_prs() -> None:
    assert WORKFLOW.is_file(), "missing php-characterization CI workflow"
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in content
    assert "main" in content
    assert "vendor/bin/phpunit" in content
    assert CHARACTERIZATION_FILTER in content


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