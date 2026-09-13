"""Check runner and CI ownership using only Python test dependencies."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_remote_runner_declaration_is_narrow() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    remote_test = config["tool"]["workbay"]["remote_test"]
    assert remote_test["runner_commands"] == ["vitest", "phpunit", "tsc", "playwright"]
    assert remote_test["runner_selecting_wrappers"] == ["npx"]


def test_collection_has_an_independent_dependency_owning_gate() -> None:
    root_tests = ast.parse(Path(__file__).read_text())
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "test_public_guide_collects_desktop_and_phone_cases"
        for node in ast.walk(root_tests)
    ), "Real Playwright collection belongs in the app integration gate"
    workflow = (REPO_ROOT / ".github/workflows/gates-harness.yml").read_text()
    assert "  playwright-collection:\n" in workflow
    harness, collection = workflow.split("  playwright-collection:\n", 1)
    assert "npm ci" not in harness
    assert "needs:" not in collection
    assert "continue-on-error:" not in collection
    assert "timeout-minutes: 10" in collection
    assert 'python-version: "3.12"' in collection
    assert 'node-version: "22.18.0"' in collection
    assert "npm install --global npm@11.14.1" in collection
    assert "python -m pip install pytest" in collection
    provision = collection.index("npm ci --ignore-scripts")
    selected = collection.index(
        "python -m pytest apps/prototype-wp-alt-context/tests/contracts/test_playwright_collection.py"
    )
    assert provision < selected
    assert "working-directory: apps/prototype-wp-alt-context" in collection[:provision]
    triggers = workflow.split("permissions:", 1)[0]
    pull_request, push = triggers.split("  push:", 1)
    for event in (pull_request, push):
        assert '      - "apps/prototype-wp-alt-context/**"' in event
