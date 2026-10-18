from __future__ import annotations

from pathlib import Path


def test_e15_13_contract_docs_adopt_curation_refresh_status() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    doc_paths = [
        repo_root / "docs" / "tasks" / "15.0" / "E15-13-roster-curation-loop-task-plan.md",
        repo_root / "docs" / "specs" / "recognition-roster-curation-loop-spec.md",
        repo_root / "docs" / "adrs" / "ADR-009-recognition-curation-refresh-and-person-review-projection.md",
        repo_root / "docs" / "workbay" / "contracts" / "curation-sync-api.md",
    ]

    for doc_path in doc_paths:
        content = doc_path.read_text(encoding="utf-8")
        assert "CurationRefreshStatus" in content, f"expected CurationRefreshStatus in {doc_path}"
        assert "SuggestionRefreshStatus" not in content, f"unexpected SuggestionRefreshStatus in {doc_path}"


def test_e15_13_fixture_docs_do_not_require_named_entity_examples() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    doc_paths = [
        repo_root / "docs" / "tasks" / "15.0" / "E15-13-roster-curation-loop-task-plan.md",
        repo_root / "docs" / "specs" / "recognition-roster-curation-loop-spec.md",
    ]
    banned_literals = [
        "Flaxen Yarrow",
        "4f7236f5-55ed-4b55-8eae-51e5b7d256f4",
        "cluster-e22d355c86504443896d9bd73c54b80e",
    ]

    for doc_path in doc_paths:
        content = doc_path.read_text(encoding="utf-8")
        for literal in banned_literals:
            assert literal not in content, f"unexpected named-entity acceptance literal {literal!r} in {doc_path}"
