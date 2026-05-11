from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / "docs" / "agentic" / "consumer-root-verification.md"

REQUIRED_WORKFLOW_HEADINGS = (
    "# Consumer Root Verification",
    "## Goal",
    "## Fixture",
    "## Probe",
    "## Recording Results",
)

REQUIRED_WORKFLOW_SNIPPETS = (
    "/tmp/e17-14-scratch-consumer/",
    './.venv/bin/pip install "mcp-agent-handoff==0.11.2" "mcp-agent-orchestrator==0.4.6" "agentic-bootstrap==0.5.1"',
    "./.venv/bin/agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.14",
    "task_plan_path",
    "DASHBOARD.txt",
    "render_handoff(kind='current_task'",
    "CURRENT_TASK.json",
    "must not be auto-written",
    "owning task's proof artifact or slice-complete handoff decision",
)


def test_consumer_root_verification_doc_covers_runtime_probe() -> None:
    assert WORKFLOW_PATH.exists(), "Consumer root verification doc is missing"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_WORKFLOW_HEADINGS:
        assert heading in workflow_text, f"Workflow doc is missing heading: {heading}"

    for snippet in REQUIRED_WORKFLOW_SNIPPETS:
        assert snippet in workflow_text, f"Workflow doc is missing snippet: {snippet}"

    forbidden_auto_write = re.compile(
        r"CURRENT_TASK\.json\s+is\s+(auto[- ]?written|automatically\s+(written|rendered|generated))",
        re.IGNORECASE,
    )
    assert not forbidden_auto_write.search(workflow_text)

    assert "E17-14-slice2-verification-proof.md" not in workflow_text
    assert "earlier `v0.1.4` review set" not in workflow_text
