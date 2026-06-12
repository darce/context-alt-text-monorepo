"""Artifact lock for E15-28 Slice 3 seed bundle, walkthrough, and epic topology revision."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_README = REPO_ROOT / "infra/oci/demo/seed/README.md"
SEED_IMPORT = REPO_ROOT / "infra/oci/demo/seed/import.sh"
WALKTHROUGH = REPO_ROOT / "infra/oci/demo/walkthrough-runbook.md"
SMOKE_LOG = REPO_ROOT / "docs/tasks/15.0/E15-28-demo-smoke-log.md"
EPIC = REPO_ROOT / "docs/epics/v0.4.0/public-demo-launch-readiness-epic.md"


def test_seed_bundle_documents_provenance_and_import_script() -> None:
    readme = SEED_README.read_text()
    assert "license" in readme.lower() or "provenance" in readme.lower()
    script = SEED_IMPORT.read_text()
    assert "wp media import" in script or "wp post" in script
    assert "seed/media" in script


def test_walkthrough_runbook_covers_scan_and_sovereignty_proof() -> None:
    text = WALKTHROUGH.read_text()
    assert "scan" in text.lower()
    assert "sovereign" in text.lower() or "degraded" in text.lower()
    assert "demo.altcontext.com" in text


def test_smoke_log_template_matches_e15_5_shape() -> None:
    text = SMOKE_LOG.read_text()
    assert "Run Metadata" in text
    assert "E15-28" in text
    assert "Proof-bundle" in text or "proof bundle" in text.lower()


def test_epic_phase3_reflects_oci_colocated_topology() -> None:
    text = EPIC.read_text()
    assert "E15-28" in text
    assert "demo.altcontext.com" in text
    assert "bulkhead" in text.lower() or "container" in text.lower()
    assert "acx-demo" in text
    # Shared-hosting purchase language removed from active deliverables.
    phase3 = text.split("### Phase 3:", 1)[1].split("### Phase 4:", 1)[0]
    assert "Hostinger" not in phase3
    assert "shared PHP hosting provisioned" not in phase3
