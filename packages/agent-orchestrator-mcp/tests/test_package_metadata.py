from __future__ import annotations

import tomllib
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _load_pyproject() -> dict:
    with (PACKAGE_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_pins_handoff_dependency_and_declares_hoisted_metadata() -> None:
    pyproject = _load_pyproject()

    assert "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0" in pyproject["project"][
        "dependencies"
    ]

    hoisted = pyproject["tool"]["hoisted"]
    assert hoisted["repository"] == "darce/mcp-agent-orchestrator"
    assert hoisted["install_url"] == "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v{version}"


def test_changelog_records_hoist_mvp_metadata_entry() -> None:
    changelog = (PACKAGE_ROOT / "CHANGELOG.md").read_text()

    assert "Hoist Agentic System MVP" in changelog
    assert "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v{version}" in changelog
