from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
README_PATH = SCRIPTS_DIR / "README.md"

OBSOLETE_TASK_EPHEMERAL_TESTS = (
    "test_manage_api_keys_cli_contract.py",
)

REQUIRED_POLICY_SNIPPETS = (
    "## Test Placement Policy",
    "Root-level doc-lock tests",
    "test_rg014_external_package_scope.py",
    "Task-ephemeral guards",
)


def test_scripts_readme_documents_test_placement_policy() -> None:
    text = README_PATH.read_text(encoding="utf-8")

    for snippet in REQUIRED_POLICY_SNIPPETS:
        assert snippet in text, f"scripts README is missing test placement policy snippet: {snippet}"


def test_obsolete_task_ephemeral_tests_are_not_live_root_tests() -> None:
    for filename in OBSOLETE_TASK_EPHEMERAL_TESTS:
        assert not (SCRIPTS_DIR / filename).exists(), f"obsolete task-ephemeral test remains live: {filename}"