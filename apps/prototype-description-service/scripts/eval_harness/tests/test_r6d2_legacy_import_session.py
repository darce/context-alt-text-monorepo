"""S2R6-01: the unknown-occasion sentinel must not clear the exhaustive gate.

``legacy_import_lineage`` mints ``LEGACY_IMPORT_CAPTURE_SESSION_ID`` because
pre-v3 boxes have no recoverable occasion key. That token is not a session.
A truthy check in ``_capture_session_required_when_exhaustive`` would let
every legacy_import box satisfy an invariant whose purpose is to require a
real occasion key (rg-015).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import (
    AnnotationMode,
    LEGACY_IMPORT_CAPTURE_SESSION_ID,
    ManifestError,
    legacy_import_lineage,
    load_manifest,
)

HARNESS_DIR = Path(__file__).resolve().parents[1]
REFETCH6 = HARNESS_DIR / "refetch6-manifest-20260716.json"
REAL_SESSION = "capture-session-2026-08-14-pass-1"


def _write(tmp_path: Path, doc: dict, name: str = "manifest.json") -> Path:
    out = tmp_path / name
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out


def _exhaustive_doc(*, session: str | None, label_source: str = "legacy_import") -> dict:
    lineage = legacy_import_lineage(name="Alice Example")
    lineage["capture_session_id"] = session
    lineage["label_source"] = label_source
    return {
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
                        "source": "iptc",
                        "lineage": lineage,
                    }
                ],
            }
        ],
    }


def test_legacy_import_sentinel_does_not_satisfy_exhaustive_gate(tmp_path: Path) -> None:
    """Pin: a legacy_import box must NOT satisfy the exhaustive gate."""
    path = _write(tmp_path, _exhaustive_doc(session=LEGACY_IMPORT_CAPTURE_SESSION_ID))
    with pytest.raises(ManifestError, match="capture_session") as exc_info:
        load_manifest(str(path))
    err = exc_info.value
    assert err.invariant == "capture_session_id_required"
    assert "legacy-import-unknown-session" in str(err) or "unknown-occasion" in str(err)
    assert err.entry_index == 0
    assert err.entry_path == "mock_images/alice.jpg"


def test_helper_lineage_unmodified_does_not_load_exhaustive(tmp_path: Path) -> None:
    """The helper's minted sentinel is the defect, not a hand-edited token."""
    doc = _exhaustive_doc(session=LEGACY_IMPORT_CAPTURE_SESSION_ID)
    # Restore the helper's exact block (no post-edit of the session key).
    doc["entries"][0]["face_boxes"][0]["lineage"] = legacy_import_lineage(name="Alice Example")
    path = _write(tmp_path, doc, "helper-exhaustive.json")
    with pytest.raises(ManifestError, match="capture_session") as exc_info:
        load_manifest(str(path))
    assert exc_info.value.invariant == "capture_session_id_required"


def test_refetch6_flipped_to_exhaustive_is_rejected(tmp_path: Path) -> None:
    """In-tree boxed corpus cannot be flipped to exhaustive on the sentinel."""
    doc = json.loads(REFETCH6.read_text(encoding="utf-8"))
    assert doc["annotation_mode"] == "roster_only"
    doc["annotation_mode"] = "exhaustive"
    path = _write(tmp_path, doc, "refetch6-exhaustive.json")
    with pytest.raises(ManifestError, match="capture_session") as exc_info:
        load_manifest(str(path))
    assert exc_info.value.invariant == "capture_session_id_required"
    assert "legacy-import-unknown-session" in str(exc_info.value) or "unknown-occasion" in str(
        exc_info.value
    )


def test_real_capture_session_still_loads_exhaustive(tmp_path: Path) -> None:
    """Positive pair: a real occasion key still clears the gate."""
    path = _write(tmp_path, _exhaustive_doc(session=REAL_SESSION, label_source="operator_blind"))
    manifest = load_manifest(str(path))
    assert manifest.annotation_mode is AnnotationMode.EXHAUSTIVE
    assert manifest.entries[0].face_boxes[0].lineage.capture_session_id == REAL_SESSION


def test_real_session_on_legacy_import_source_still_loads_exhaustive(tmp_path: Path) -> None:
    """The pin is the sentinel, not label_source=legacy_import."""
    path = _write(tmp_path, _exhaustive_doc(session=REAL_SESSION, label_source="legacy_import"))
    manifest = load_manifest(str(path))
    assert manifest.annotation_mode is AnnotationMode.EXHAUSTIVE
    assert manifest.entries[0].face_boxes[0].lineage.capture_session_id == REAL_SESSION
    assert manifest.entries[0].face_boxes[0].lineage.label_source.value == "legacy_import"


def test_one_sentinel_box_among_real_sessions_is_rejected(tmp_path: Path) -> None:
    """A single unknown-occasion box is enough; mixed sessions must not pass."""
    doc = _exhaustive_doc(session=REAL_SESSION, label_source="operator_blind")
    doc["entries"][0]["face_count"] = 2
    real_box = doc["entries"][0]["face_boxes"][0]
    sentinel_box = {
        "x": 0.2,
        "y": 0.2,
        "w": 0.1,
        "h": 0.1,
        "name": None,
        "source": "iptc",
        "lineage": legacy_import_lineage(name=None),
    }
    doc["entries"][0]["face_boxes"] = [real_box, sentinel_box]
    path = _write(tmp_path, doc, "mixed-session.json")
    with pytest.raises(ManifestError, match="capture_session") as exc_info:
        load_manifest(str(path))
    assert exc_info.value.invariant == "capture_session_id_required"
    assert exc_info.value.entry_index == 0


def test_sentinel_still_loads_under_roster_only(tmp_path: Path) -> None:
    """The sentinel remains a legal unknown-occasion marker on roster_only."""
    doc = _exhaustive_doc(session=LEGACY_IMPORT_CAPTURE_SESSION_ID)
    doc["annotation_mode"] = "roster_only"
    path = _write(tmp_path, doc, "roster-sentinel.json")
    manifest = load_manifest(str(path))
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert (
        manifest.entries[0].face_boxes[0].lineage.capture_session_id
        == LEGACY_IMPORT_CAPTURE_SESSION_ID
    )
