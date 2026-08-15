"""S2R3-02 pins: a raw-mapping parent mode is not per-entry evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import (
    AnnotationMode,
    ManifestError,
    ScoreInvariant,
    load_manifest,
)
from scripts.eval_harness.report import (
    _entries_as_dicts,
    score_face_run_record,
    score_run_record,
)

_LINEAGE = {
    "labeler_id": "test-labeler",
    "batch_id": "test-batch",
    "capture_session_id": "test-session",
    "pass_index": 0,
    "labeled_at": "2026-08-14T00:00:00Z",
    "tool_version": "test",
    "saw_machine_proposals": False,
    "label_source": "operator_blind",
    "decision": "named",
    "confidence": "high",
    "arbitration_of": None,
}


def _face_run(*, n_faces: int) -> dict:
    faces = [
        {
            "bbox_px": [float(i * 10), 0.0, 8.0, 8.0],
            "landmarks_px": [[0.0, 0.0]] * 5,
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "det_score": 0.9,
        }
        for i in range(n_faces)
    ]
    return {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "t",
            "leg": "candidate",
        },
        "items": [
            {
                "media_id": 1,
                "path": "x.jpg",
                "model_id": "m",
                "embedding_dim": 4,
                "image_size": [10, 10],
                "faces": faces,
            }
        ],
    }


def _raw_parent_exhaustive(*, annotation_mode: object | None, omit: bool) -> dict:
    entry: dict = {
        "path": "x.jpg",
        "media_id": 1,
        "face_count": 0,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
    }
    if not omit:
        entry["annotation_mode"] = annotation_mode
    return {
        "annotation_mode": "exhaustive",
        "roster": [],
        "entries": [entry],
    }


def test_r6e1_omitted_key_under_parent_exhaustive_refuses() -> None:
    """D1 hole: parent exhaustive + omitted entry stamp must not publish P/R."""
    manifest = _raw_parent_exhaustive(annotation_mode=None, omit=True)
    entries, _, _ = _entries_as_dicts(manifest)
    assert "annotation_mode" not in entries[0]
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_face_run(n_faces=3), manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE


def test_r6e1_none_key_under_parent_exhaustive_refuses() -> None:
    manifest = _raw_parent_exhaustive(annotation_mode=None, omit=False)
    entries, _, _ = _entries_as_dicts(manifest)
    assert entries[0]["annotation_mode"] is None
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_face_run(n_faces=3), manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE


def test_r6e1_explicit_exhaustive_on_same_unstamped_entries_also_refuses() -> None:
    """Parity: score_run_record(..., annotation_mode='exhaustive') already refuses."""
    entries = [
        {
            "path": "x.jpg",
            "media_id": 1,
            "face_count": 0,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [],
        }
    ]
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "x.jpg",
                "describe": {"alt_text_draft": "x", "visual_facts": {"objects": []}},
                "identities": [],
                "face_count": 3,
                "error": None,
            }
        ],
    }
    scored = score_run_record(record, entries, annotation_mode="exhaustive")
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE
    assert det["precision"] is None
    assert det["tp"] is None


def test_r6e1_typed_manifest_flatten_stamps_document_mode(tmp_path: Path) -> None:
    """CLI _face_score_once passes GoldenManifest; typed flatten must stamp."""
    doc = {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": [
            {
                "path": "mock_images/alice.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [
                    {
                        "x": 0.5,
                        "y": 0.4,
                        "w": 0.2,
                        "h": 0.3,
                        "name": "Alice Example",
                        "source": "operator",
                        "lineage": _LINEAGE,
                    }
                ],
            }
        ],
    }
    path = tmp_path / "exhaustive.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    typed = load_manifest(str(path))
    assert "annotation_mode" not in typed.entries[0].model_dump()
    entries, _, _ = _entries_as_dicts(typed)
    assert entries[0]["annotation_mode"] == AnnotationMode.EXHAUSTIVE.value


class _DuckManifest:
    """Duck-typed door: .entries + .roster, entries are plain dicts."""

    def __init__(self, entries: list) -> None:
        self.annotation_mode = "exhaustive"
        self.roster: list = []
        self.roster_cohorts: dict = {}
        self.entries = entries


def test_r6e1_duck_typed_pre_stamped_roster_only_is_not_overwritten() -> None:
    """Document exhaustive must not overwrite a genuine per-entry roster_only stamp."""
    stamped = [{"media_id": "m1", "annotation_mode": "roster_only", "face_count": 1}]
    out, _, _ = _entries_as_dicts(_DuckManifest([dict(e) for e in stamped]))
    assert out[0]["annotation_mode"] == "roster_only"


def test_r6e1_duck_typed_unstamped_entry_still_receives_document_mode() -> None:
    """Fill must still fire when a duck-typed entry has no stamp (RV3 load-bearing)."""
    unstamped = [{"media_id": "m1", "face_count": 1}]
    out, _, _ = _entries_as_dicts(_DuckManifest([dict(e) for e in unstamped]))
    assert out[0]["annotation_mode"] == "exhaustive"


class _DumpEntry:
    """Stand-in whose model_dump can carry annotation_mode (GoldenEntry cannot)."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return dict(self._payload)


class _CliScoreManifest:
    """Typed manifest wrapper so _cmd_score can see a per-entry dump stamp."""

    def __init__(self, inner: object, entries: list) -> None:
        self._inner = inner
        self.entries = entries
        self.annotation_mode = getattr(inner, "annotation_mode")
        self.roster = getattr(inner, "roster")

    def model_dump(self) -> dict:
        return getattr(self._inner, "model_dump")()


def _two_entry_exhaustive_doc() -> dict:
    box = {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": "Alice Example",
        "source": "operator",
        "lineage": _LINEAGE,
    }
    return {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": [
            {
                "path": "mock_images/stamped.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [box],
            },
            {
                "path": "mock_images/unstamped.jpg",
                "sha256": "b" * 64,
                "media_id": 2,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [box],
            },
        ],
    }


def test_cmd_score_fill_only_preserves_per_entry_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R6E-04 sibling: _cmd_score fills missing stamps and never overwrites.

    GoldenEntry has no annotation_mode field, so the collision uses a
    stand-in dump. Both halves are required: overwrite-all stays green
    on fill-only, and a no-op door stays green on preserve-only.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path = tmp_path / "golden.json"
    rec_path = tmp_path / "run.json"
    man_path.write_text(json.dumps(_two_entry_exhaustive_doc()), encoding="utf-8")
    rec_path.write_text(
        json.dumps(
            {
                "schema": "acx-eval/v1",
                "kind": "run_record",
                "provenance": {
                    "manifest_sha256": "m" * 64,
                    "base_url": "x",
                    "head_sha": "0" * 40,
                    "started_at": "t",
                },
                "items": [],
            }
        ),
        encoding="utf-8",
    )

    real_load = cli_mod.load_manifest

    def fake_load(path: str) -> _CliScoreManifest:
        typed = real_load(path)
        stamped = {**typed.entries[0].model_dump(), "annotation_mode": "roster_only"}
        return _CliScoreManifest(typed, [_DumpEntry(stamped), typed.entries[1]])

    captured: list[list] = []
    real_build = cli_mod.build_reports

    def wrap(record: dict, entries: list, **kwargs: object) -> tuple[str, str]:
        captured.append(entries)
        return real_build(record, entries, **kwargs)

    monkeypatch.setattr(cli_mod, "load_manifest", fake_load)
    monkeypatch.setattr(cli_mod, "build_reports", wrap)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.main(
            ["score", "--manifest", str(man_path), "--run-record", str(rec_path)]
        )

    assert captured, "build_reports was never called"
    rows = captured[0]
    assert rows[0]["annotation_mode"] == "roster_only"
    filled = rows[1]["annotation_mode"]
    assert (filled.value if hasattr(filled, "value") else filled) == "exhaustive"
    # Mixed stamps refuse by published invariant, not a zeroed metric block.
    assert exc_info.value.code != 0
    assert "detection_refuses_mixed_annotation_mode" in str(exc_info.value)
