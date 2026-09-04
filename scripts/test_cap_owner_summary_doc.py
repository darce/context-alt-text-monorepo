from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "tasks" / "v0.5.0" / "E16-1-cap-owner-summary.md"
TASK_PLAN_PATH = REPO_ROOT / "docs" / "tasks" / "v0.5.0" / "E16-1-bounded-iteration-caps-task-plan.md"

REQUIRED_HEADINGS = (
    "# E16-1 Cap-Owner Summary",
    "## REST List Surfaces",
    "## Repository Seams",
    "## Lifecycle Migration",
    "## Multipart Owner Note",
)

REQUIRED_SNIPPETS = (
    "LIST_CLUSTERS_MAX_LIMIT",
    "LIST_CLUSTER_LABELS_MAX_LIMIT",
    "LIST_TOP_UNLABELED_CLUSTERS_MAX_LIMIT",
    "GET_CLUSTER_MEMBERS_MAX_LIMIT",
    "DEFAULT_CLUSTER_MEMBER_LIMIT",
    "MAX_SNAPSHOT_MERGE_BATCH",
    "MAX_LEGACY_MIGRATION_CHUNK",
    "MULTIPART_MAX_IMAGES",
    "maxMediaPerBatch",
    "E16-2",
)


def test_cap_owner_summary_doc_exists_with_required_surfaces() -> None:
    assert DOC_PATH.exists(), f"missing cap-owner summary doc: {DOC_PATH}"

    text = DOC_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"cap-owner summary doc missing heading: {heading}"

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, f"cap-owner summary doc missing snippet: {snippet}"


def test_task_plan_metadata_matches_active_feature_branch() -> None:
    text = TASK_PLAN_PATH.read_text(encoding="utf-8")

    assert "**Status**: Review Ready" in text
    assert "**Target Branch**: `feature/e16-1`" in text
    assert "feature/e16-1-bounded-iteration-caps" not in text
    assert "review-ready on commit `" not in text
