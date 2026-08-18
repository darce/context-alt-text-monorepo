"""VLM-2C Slice 3: phrase-box fixture — E19-4a containment coordination seam."""

import os
import warnings

from scripts.eval_harness.manifest import RubricEmptyWarning, load_manifest
from scripts.eval_harness.phrase_boxes import PHRASE_BOXES_SCHEMA, PhraseBoxesError, load_phrase_boxes

_SEED_DIR = os.path.join(os.path.dirname(__file__), "seed")
_FIXTURE = os.path.join(_SEED_DIR, "phrase_boxes.json")


def _load():
    return load_phrase_boxes(_FIXTURE)


def _seed_manifest():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RubricEmptyWarning)
        return load_manifest(os.path.join(_SEED_DIR, "golden.json"))


def _resolve(center, phrase_boxes):
    """E19-4a containment rule: smallest-area phrase box containing the face center."""
    x, y = center
    best = None
    best_area = None
    for pb in phrase_boxes:
        x_min, y_min, x_max, y_max = pb["box"]
        if x_min <= x <= x_max and y_min <= y <= y_max:
            area = (x_max - x_min) * (y_max - y_min)
            if best_area is None or area < best_area:
                best, best_area = pb["phrase"], area
    return best


def test_phrase_boxes_schema_and_geometry():
    data = _load()
    assert data["schema"] == PHRASE_BOXES_SCHEMA
    assert data["axis"] == {
        "origin": "top-left",
        "x": "right",
        "y": "down",
        "units": "image_fraction_[0,1]",
    }
    manifest = _seed_manifest()
    by_id = {e.media_id: e for e in manifest.entries}
    roster = set(manifest.roster)
    assert data["scenes"], "fixture defines no scenes"
    for key, scene in data["scenes"].items():
        entry = by_id[scene["media_id"]]
        assert key == str(scene["media_id"])
        assert scene["path"] == entry.path
        assert len(scene["face_centers"]) == entry.face_count
        for fc in scene["face_centers"]:
            x, y = fc["center"]
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        for pb in scene["phrase_boxes"]:
            assert pb["phrase"] in roster
            x_min, y_min, x_max, y_max = pb["box"]
            assert 0.0 <= x_min < x_max <= 1.0
            assert 0.0 <= y_min < y_max <= 1.0


def test_phrase_boxes_containment_is_one_to_one():
    data = _load()
    manifest = _seed_manifest()
    by_id = {e.media_id: e for e in manifest.entries}
    for scene in data["scenes"].values():
        expected = scene["expected_containment"]
        assert [e["face_center"] for e in expected] == [fc["center"] for fc in scene["face_centers"]], (
            "expected_containment must echo face_centers 1:1"
        )
        entry = by_id[scene["media_id"]]
        named = []
        for exp in expected:
            resolved = _resolve(exp["face_center"], scene["phrase_boxes"])
            assert resolved == exp["resolved_identity"], (
                f"media {scene['media_id']}: center {exp['face_center']} -> {resolved}"
            )
            if resolved is not None:
                assert resolved in entry.present_identities
                named.append(resolved)
        # VLM-2C-S3-BR-03: one face per identity, every present identity resolved,
        # and exactly the stranger faces resolve to no name.
        assert len(named) == len(set(named)), f"media {scene['media_id']}: identity resolved twice"
        assert set(named) == set(entry.present_identities)
        assert len(expected) - len(named) == entry.face_count - len(entry.present_identities)


def test_phrase_boxes_include_stranger_null_case():
    data = _load()
    stranger = data["scenes"].get("38")
    assert stranger, "designated stranger fixture (media_id 38) missing"
    nulls = [e for e in stranger["expected_containment"] if e["resolved_identity"] is None]
    assert len(nulls) == 1, "stranger face must resolve to no name (never a guessed name)"
    named = [e for e in stranger["expected_containment"] if e["resolved_identity"]]
    assert [e["resolved_identity"] for e in named] == ["Muted Yarrow"]


def test_phrase_boxes_loader_rejects_bad_schema(tmp_path):
    bad = tmp_path / "phrase_boxes.json"
    bad.write_text('{"schema": "phrase_boxes/v0", "axis": {}, "scenes": {}}')
    import pytest

    with pytest.raises(PhraseBoxesError):
        load_phrase_boxes(bad)
