from __future__ import annotations

import json
import re
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
    "uv tool install --no-sources",
    "workbay install --target . --remote-ref",
    "workbay update --target . --remote-ref",
    "workbay doctor --target .",
    "workbay repair --target .",
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
    "uv tool install --no-sources",
    "workbay update --target . --remote-ref",
)

WORKBAY_REF_RE = re.compile(r"workbay-v\d+\.\d+\.\d+")


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
    """MAINT-FB-B-02: plugin_overrides_path must be documented and pinned.

    The generated overlay contract is a bootstrap-managed ignored surface in this
    consumer. The tracked source of truth is the install ledger plus the consumer
    setup guide.
    """
    ledger_path = REPO_ROOT / ".workbay-bootstrap.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["plugin_overrides_path"] == "workbay-overrides/workbay-system"

    text = DOC_PATH.read_text(encoding="utf-8")
    plugin_overrides_section = text.split("## Plugin Overrides", 1)[1].split(
        "## Troubleshooting",
        1,
    )[0]
    assert "plugin_overrides_path" in plugin_overrides_section
    assert "workbay-overrides/workbay-system" in plugin_overrides_section
    assert "APD-07" in plugin_overrides_section
    assert "workstate-stack-v0.1.12" not in plugin_overrides_section


def test_consumer_setup_doc_pins_one_coherent_workbay_ref() -> None:
    """The guide must pin a workbay tag, and every live mention must agree.

    Deliberately version-agnostic. Asserting one exact tag couples this gate to
    the release cadence: the ref appears three times in the guide and nothing
    derives it, so every upgrade needed a matching edit here and the gate went
    red in between ([REF-26] one fact across prose and code; [DATA-04] the check
    must accept N and N+1 during a rollout). What needs guarding is that a pin
    still exists and that a half-finished bump cannot pass.

    Retros under "## Lessons Learned" are exempt: they name the ref that was
    current when they were written.
    """
    text = DOC_PATH.read_text(encoding="utf-8")
    live = text.split("## Lessons Learned", 1)[0]

    refs = set(WORKBAY_REF_RE.findall(live))
    assert refs, "consumer-setup doc no longer pins a workbay-v<semver> tag"
    assert len(refs) == 1, f"consumer-setup doc pins disagreeing workbay refs: {sorted(refs)}"

    assert live.count("REF=workbay-v") >= 2, (
        "both the install and update snippets must pin REF=workbay-v<semver>"
    )
    update_section = live.split("## Update Workflow", 1)[1].split("## Doctor and Repair", 1)[0]
    assert "REF=workbay-v" in update_section, "update workflow lost its REF= pin"
