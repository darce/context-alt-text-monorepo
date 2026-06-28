from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "workbay" / "consumer-setup.md"

REQUIRED_HEADINGS = (
    "## Prerequisites",
    "## Install",
    "## State Paths",
    "## Update Workflow",
    "## Doctor and Repair",
    "## Git Hooks",
    "## Daemons",
    "## Troubleshooting",
    "## Tenancy",
    "## Platform Support",
    "## Plugin Overrides",
)

REQUIRED_SNIPPETS = (
    './.venv/bin/pip install "workstate-stack==0.1.12"',
    "./.venv/bin/workbay-bootstrap install --target . --remote-ref workstate-stack-v0.1.12",
    "./.venv/bin/workbay-bootstrap update --remote-ref workstate-stack-v0.1.12",
    "./.venv/bin/workbay-bootstrap doctor",
    "./.venv/bin/workbay-bootstrap repair",
    "AGENT_HANDOFF_WORKSPACE_ROOT",
    "AGENT_HANDOFF_STATE_DIR",
    "AGENT_HANDOFF_DASHBOARD_PATH",
    "AGENT_HANDOFF_CURRENT_TASK_PATH",
    "AGENT_HANDOFF_EXPORTS_DIR",
    "optional explicit current-task export",
    "do not assume it exists or is current",
    "core.hooksPath",
    "scripts/hooks/git",
    "AmbiguousWorkspaceContextError",
    "ConsumerRootResolutionError",
    "orchestrator.daemons.enabled",
    ".task-state/handoff.db",
    "plugin_overrides_path",
    "workbay-overrides/workbay-system",
    "upstream_digest",
    "make check-overrides-digest",
    "SKILL.base.md",
)

REQUIRED_UPDATE_SNIPPETS = (
    './.venv/bin/pip install --upgrade "workstate-stack==0.1.12"',
    "./.venv/bin/workbay-bootstrap update --remote-ref workstate-stack-v0.1.12",
)


def test_consumer_setup_doc_exists_and_is_standalone() -> None:
    assert DOC_PATH.exists(), "docs/workbay/consumer-setup.md is missing"

    text = DOC_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"consumer-setup doc is missing heading: {heading}"

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, f"consumer-setup doc is missing required snippet: {snippet}"

    assert "default current-task snapshot: CURRENT_TASK.json" not in text

    update_section = text.split("## Update Workflow", 1)[1].split("## Doctor and Repair", 1)[0]
    for snippet in REQUIRED_UPDATE_SNIPPETS:
        assert snippet in update_section, f"consumer-setup doc is missing required update snippet: {snippet}"

    # Standalone-ness: live instructions must not reference the task plan or task IDs.
    # Historical retros under "## Lessons Learned" are exempt (they are dated, append-only
    # change-log entries that name the slice that produced them).
    pre_lessons = text.split("## Lessons Learned", 1)[0]
    assert 'mcp-agent-handoff>=0.6.0,<0.7' not in pre_lessons
    assert 'mcp-agent-orchestrator>=0.3.0,<0.4' not in pre_lessons
    assert 'agentic-bootstrap>=0.2.0,<0.3' not in pre_lessons
    assert 'git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.3' not in pre_lessons
    assert 'git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.4' not in pre_lessons
    assert 'git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0' not in pre_lessons
    assert 'mcp-agent-handoff==' not in pre_lessons
    assert 'mcp-agent-orchestrator==' not in pre_lessons
    assert 'agentic-bootstrap' not in pre_lessons
    assert "E17-10" not in pre_lessons, "consumer-setup live instructions must be standalone, not task-plan dependent"
    assert "task plan" not in pre_lessons.lower(), "consumer-setup live instructions must not tell readers to consult the task plan"


def test_overlay_manifest_contract_documents_plugin_overrides_path() -> None:
    """MAINT-FB-B-02: plugin_overrides_path must be documented in the manifest contract.

    The field is documented in the overlay manifest contract: workbay-bootstrap
    0.8.10+ (workstate-stack-v0.1.12) reads plugin_overrides_path when present.
    """
    contract_path = REPO_ROOT / "docs" / "workbay" / "contracts" / "overlay-manifest.yaml"
    text = contract_path.read_text(encoding="utf-8")
    assert "optional_fields" in text, "contract must declare an optional_fields section"
    assert "plugin_overrides_path" in text
    assert "APD-07" in text, "contract must name the recipe-overrides release"
    assert "workstate-stack-v0.1.12" in text, "contract must name the stack tag that adopts the field"
    optional_section = text.split("optional_fields", 1)[1]
    assert "plugin_overrides_path" in optional_section, (
        "plugin_overrides_path must be listed under optional_fields, not required_fields"
    )
    required_section = text.split("required_fields", 1)[1].split("optional_fields", 1)[0]
    assert "plugin_overrides_path" not in required_section
