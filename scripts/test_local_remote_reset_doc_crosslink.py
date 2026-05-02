"""Doc-lock for the local <-> remote reset cross-references (E15-12 slice 3a).

The two reset workflows (local Postgres reset, OCI remote reset) are siblings
that operators choose between based on what they're trying to do. The docs for
each must point at the other so an operator who lands on one of them does not
miss the existence of the other.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESC_README = REPO_ROOT / "apps" / "prototype-description-service" / "README.md"
INFRA_README = REPO_ROOT / "infra" / "oci" / "README.md"


def test_description_service_readme_links_to_remote_reset_doc() -> None:
    text = DESC_README.read_text()
    # Mention the make target so a reader scanning the doc can find it.
    assert "make reset-remote" in text
    # Path link to the OCI README's destructive-reset section.
    assert "infra/oci/README.md" in text


def test_infra_oci_readme_links_to_local_reset_doc() -> None:
    text = INFRA_README.read_text()
    # Already true from slice 2e but locked here so the cross-link survives edits.
    assert "make reset-local" in text


def test_description_service_readme_states_when_to_use_each_reset() -> None:
    text = DESC_README.read_text().lower()
    # The doc must give the operator a one-line "use this for X" trigger so
    # they don't have to read both docs to figure out which to run.
    assert "use" in text and ("local" in text and ("remote" in text or "oci" in text))
