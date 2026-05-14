from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = REPO_ROOT / "docs" / "tasks" / "15.0" / "E15-3a-localwp-proof-bundle-capture-checklist.md"
RUN_LOG = REPO_ROOT / "docs" / "tasks" / "15.0" / "E15-3a-localwp-oci-run-log.md"

REQUIRED_HEADINGS = (
    "## Phase 0: Local PostgreSQL First",
    "## Before You Start",
    "## Slice 2 Capture Sequence",
    "## Checkpoint 1: Pre-Scan State",
    "## Checkpoint 2: Avatar Evidence",
    "## Checkpoint 3: Mid-Run Progress",
    "## Checkpoint 4: UI-Ready Completion",
    "## Checkpoint 5: Backend Evidence Packet",
    "## After the Scan",
)

REQUIRED_SNIPPETS = (
    "proof-bundle artifact bundle ID",
    "source scan run identifier",
    "Seeded-Media Proof-Bundle Capture Packet",
    "localhost:5432",
    "make postgres-start",
    "./scripts/db_shell.sh --admin",
    "PGPORT=55432 make reset",
    "cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f",
    "GET /metrics",
    "representative avatar",
    "processed count",
    "Scan complete",
    "E15-3a-localwp-oci-run-log.md",
)


def test_e15_3a_capture_checklist_exists_and_covers_operator_flow() -> None:
    assert CHECKLIST.exists(), "LocalWP proof-bundle capture checklist is missing"

    text = CHECKLIST.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"capture checklist missing heading: {heading}"

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, f"capture checklist missing snippet: {snippet}"


def test_e15_3a_run_log_points_to_capture_checklist() -> None:
    text = RUN_LOG.read_text(encoding="utf-8")

    assert "E15-3a-localwp-proof-bundle-capture-checklist.md" in text
    assert "Use the operator checklist" in text