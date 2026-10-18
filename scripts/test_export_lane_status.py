"""Tests for the live lane-status exporter used by the overlap gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_lane_status as exporter  # noqa: E402


def _write(directory: Path, name: str, document: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(document))
    return path


def test_manifest_task_refs_prefers_the_document_key(tmp_path: Path) -> None:
    _write(tmp_path, "renamed.json", {"task_ref": "TASK-A", "lanes": {}})

    assert exporter.manifest_task_refs(tmp_path) == ["TASK-A"]


def test_manifest_task_refs_falls_back_to_the_file_stem(tmp_path: Path) -> None:
    _write(tmp_path, "TASK-B.json", {"lanes": {}})

    assert exporter.manifest_task_refs(tmp_path) == ["TASK-B"]


def test_manifest_task_refs_skips_unreadable_and_duplicate_manifests(
    tmp_path: Path,
) -> None:
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "broken.json").write_text("{not json")
    _write(tmp_path, "TASK-C.json", {"task_ref": "TASK-C", "lanes": {}})
    _write(tmp_path, "also-c.json", {"task_ref": "TASK-C", "lanes": {}})

    assert exporter.manifest_task_refs(tmp_path) == ["TASK-C"]


def test_normalise_rows_reads_a_flat_envelope() -> None:
    payload = {"lanes": [{"task_ref": "TASK-A", "lane_id": "lane-a", "status": "open"}]}

    assert exporter.normalise_rows("TASK-A", payload) == [{"task_ref": "TASK-A", "lane_id": "lane-a", "status": "open"}]


def test_normalise_rows_reads_a_nested_data_envelope() -> None:
    payload = {"data": {"lanes": [{"lane_id": "lane-a", "status": "merged"}]}}

    assert exporter.normalise_rows("TASK-A", payload) == [
        {"task_ref": "TASK-A", "lane_id": "lane-a", "status": "merged"}
    ]


def test_normalise_rows_defaults_a_status_less_lane_row_to_active() -> None:
    """A live lane row with a NULL status must not be dropped from the export.

    Dropping it would make the checker treat the lane as stale and hide a real
    owned-path overlap.
    """
    payload = {"lanes": [{"lane_id": "lane-a", "status": None}]}

    assert exporter.normalise_rows("TASK-A", payload) == [
        {"task_ref": "TASK-A", "lane_id": "lane-a", "status": "active"}
    ]


def test_normalise_rows_drops_rows_without_a_lane_id() -> None:
    payload = {"lanes": [{"status": "open"}, "not-a-row", {"lane_id": "  "}]}

    assert exporter.normalise_rows("TASK-A", payload) == []


def test_main_exits_two_when_the_manifest_directory_is_missing(tmp_path: Path) -> None:
    code = exporter.main(
        [
            "--manifest-dir",
            str(tmp_path / "absent"),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "status.json"),
        ]
    )

    assert code == 2
    assert not (tmp_path / "status.json").exists()


def test_main_writes_the_export_envelope(tmp_path: Path, monkeypatch) -> None:
    manifest_dir = tmp_path / "manifests"
    _write(manifest_dir, "TASK-A.json", {"task_ref": "TASK-A", "lanes": {}})
    output = tmp_path / "out" / "status.json"
    monkeypatch.setattr(
        exporter,
        "collect",
        lambda *_args, **_kwargs: [{"task_ref": "TASK-A", "lane_id": "lane-a", "status": "open"}],
    )

    code = exporter.main(
        [
            "--manifest-dir",
            str(manifest_dir),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(output),
        ]
    )

    assert code == 0
    assert json.loads(output.read_text()) == {"lanes": [{"task_ref": "TASK-A", "lane_id": "lane-a", "status": "open"}]}


def test_main_exits_two_when_the_backend_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    manifest_dir = tmp_path / "manifests"
    _write(manifest_dir, "TASK-A.json", {"task_ref": "TASK-A", "lanes": {}})

    def _boom(*_args, **_kwargs):
        raise RuntimeError("handoff database is locked")

    monkeypatch.setattr(exporter, "collect", _boom)

    code = exporter.main(
        [
            "--manifest-dir",
            str(manifest_dir),
            "--workspace-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "status.json"),
        ]
    )

    assert code == 2
