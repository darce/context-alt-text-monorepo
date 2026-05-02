"""Doc-lock for the destructive reset operator workflow in infra/oci/README.md.

The operator-facing doc is the contract that pairs with the do_reset() shell
implementation. If the destructive flow changes (new confirmation lever, new
verification step, new safety guard) and the doc is not updated in the same
slice, this test fails.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "infra" / "oci" / "README.md"


def test_readme_documents_reset_remote_operator_command() -> None:
    text = README.read_text()
    assert "make reset-remote" in text
    assert "CONFIRM_REMOTE_RESET=RESET" in text
    assert "ENV=dev" in text
    assert "ENV=prod CONFIRM_REMOTE_RESET=RESET CONFIRM=PROMOTE" in text


def test_readme_documents_dry_run_lever_before_destructive_run() -> None:
    text = README.read_text()
    assert "ACX_RESET_DRY_RUN=1" in text
    assert "dry-run" in text.lower() or "DRY-RUN" in text


def test_readme_documents_safety_contract() -> None:
    text = README.read_text()
    # destructive semantics are stated, not implied
    assert "destructive" in text.lower()
    # the env-scoped pgdata reset boundary is named so the operator can verify it
    assert "ACX_PGDATA_PATH" in text


def test_readme_documents_post_reset_verification() -> None:
    text = README.read_text()
    # /ready (not /health) is the destructive-reset verification surface
    assert "/ready" in text
    # post-reset bootstrap step references the credential CLI
    assert "manage_api_keys.py" in text


def test_readme_destructive_reset_section_appears_with_anchor_heading() -> None:
    text = README.read_text()
    # Find the section header so future readers can navigate.
    assert (
        "### Destructive Remote Reset" in text or "## Destructive Remote Reset" in text
    )
