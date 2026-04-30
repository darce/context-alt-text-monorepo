from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROOF_PATH = REPO_ROOT / "docs" / "tasks" / "17.0" / "E17-14-slice2-verification-proof.md"
WORKFLOW_PATH = REPO_ROOT / "docs" / "agentic" / "consumer-root-verification.md"

REQUIRED_PROOF_HEADINGS = (
    "# E17-14 Slice 2 Verification Proof",
    "## Recorded Inputs",
    "## Scratch Consumer Fixture",
    "## Probe Commands",
    "## Pass-Criteria Checklist",
    "## Current Status",
)

REQUIRED_PROOF_SNIPPETS = (
    "/tmp/e17-14-scratch-consumer/",
    "agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.4",
    "task_plan_path",
    "DASHBOARD.txt",
    "render_handoff(kind='current_task', task_ref='E17-14-A')",
    "CURRENT_TASK.json",
    "must not be auto-written",
    "git init",
    "set_handoff_state",
)

REQUIRED_WORKFLOW_HEADINGS = (
    "# Consumer Root Verification",
    "## Goal",
    "## Fixture",
    "## Probe",
    "## Recording Results",
)

REQUIRED_WORKFLOW_SNIPPETS = (
    "/tmp/e17-14-scratch-consumer/",
    "agentic-bootstrap install --target /tmp/e17-14-scratch-consumer --remote-ref v0.1.4",
    "task_plan_path",
    "DASHBOARD.txt",
    "render_handoff(kind='current_task'",
    "CURRENT_TASK.json",
    "must not be auto-written",
    "E17-14-slice2-verification-proof.md",
)


def test_e17_14_slice2_docs_exist_and_cover_runtime_probe() -> None:
    assert PROOF_PATH.exists(), "Slice 2 proof artifact is missing"
    assert WORKFLOW_PATH.exists(), "Consumer root verification doc is missing"

    proof_text = PROOF_PATH.read_text(encoding="utf-8")
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_PROOF_HEADINGS:
        assert heading in proof_text, f"Proof artifact is missing heading: {heading}"

    for snippet in REQUIRED_PROOF_SNIPPETS:
        assert snippet in proof_text, f"Proof artifact is missing snippet: {snippet}"

    recorded_inputs = proof_text.split("## Recorded Inputs", 1)[1].split("## Scratch Consumer Fixture", 1)[0]
    assert len(re.findall(r"\b[0-9a-f]{40}\b", recorded_inputs)) >= 2, (
        "Proof artifact should record both the rebased branch SHA and the reviewed overlay SHA"
    )

    for heading in REQUIRED_WORKFLOW_HEADINGS:
        assert heading in workflow_text, f"Workflow doc is missing heading: {heading}"

    for snippet in REQUIRED_WORKFLOW_SNIPPETS:
        assert snippet in workflow_text, f"Workflow doc is missing snippet: {snippet}"

    forbidden_auto_write = re.compile(
        r"CURRENT_TASK\.json\s+is\s+(auto[- ]?written|automatically\s+(written|rendered|generated))",
        re.IGNORECASE,
    )
    assert not forbidden_auto_write.search(proof_text)
    assert not forbidden_auto_write.search(workflow_text)
