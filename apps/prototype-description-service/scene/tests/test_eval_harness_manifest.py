"""VLM-2A Slice 1: golden-manifest loader — structure + sha256 fail-fast (rg-008)."""

import hashlib
import json
import os
import unicodedata
import warnings

import pytest

from scripts.eval_harness.manifest import (
    GoldenManifest,
    ManifestError,
    RubricEmptyWarning,
    load_manifest,
)


def _valid_manifest_dict() -> dict:
    img_hash = hashlib.sha256(b"fake image bytes").hexdigest()
    return {
        "manifest_version": 2,
        "roster": ["Alice Example", "Bob Example"],
        "entries": [
            {
                "path": "mock_images/scene-001.jpg",
                "sha256": img_hash,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "A title", "caption": "A caption"},
                "must_right": ["Alice Example"],
                "easy_wrong": ["Bob Example"],
                "policy": {"recognition_enabled": True},
            },
            {
                "path": "mock_images/scene-002.jpg",
                "sha256": img_hash,
                "media_id": 2,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {},
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
            },
        ],
    }


def _write_manifest(tmp_path, data) -> str:
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_valid_manifest_loads(tmp_path):
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    assert isinstance(manifest, GoldenManifest)
    assert len(manifest.entries) == 2
    assert manifest.entries[0].media_id == 1
    assert manifest.roster == ["Alice Example", "Bob Example"]


def test_missing_manifest_file_is_actionable(tmp_path):
    with pytest.raises(ManifestError, match="golden.json"):
        load_manifest(str(tmp_path / "golden.json"))


def test_malformed_json_fails_fast(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text("{not json")
    with pytest.raises(ManifestError):
        load_manifest(str(path))


def test_bad_sha256_rejected(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0]["sha256"] = "nothex"
    with pytest.raises(ManifestError, match="sha256"):
        load_manifest(_write_manifest(tmp_path, data))


def test_duplicate_media_id_rejected(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][1]["media_id"] = 1
    with pytest.raises(ManifestError, match="media_id"):
        load_manifest(_write_manifest(tmp_path, data))


def test_identity_not_in_roster_rejected(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0]["present_identities"] = ["Nobody Known"]
    with pytest.raises(ManifestError, match="roster"):
        load_manifest(_write_manifest(tmp_path, data))


def test_missing_required_entry_field_rejected(tmp_path):
    data = _valid_manifest_dict()
    del data["entries"][0]["media_id"]
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, data))


def test_hash_verification_against_images_dir(tmp_path):
    data = _valid_manifest_dict()
    images = tmp_path / "images"
    (images / "mock_images").mkdir(parents=True)
    (images / "mock_images" / "scene-001.jpg").write_bytes(b"fake image bytes")
    (images / "mock_images" / "scene-002.jpg").write_bytes(b"fake image bytes")
    manifest = load_manifest(_write_manifest(tmp_path, data), images_dir=str(images))
    assert len(manifest.entries) == 2


def test_hash_mismatch_names_offending_path(tmp_path):
    data = _valid_manifest_dict()
    images = tmp_path / "images"
    (images / "mock_images").mkdir(parents=True)
    (images / "mock_images" / "scene-001.jpg").write_bytes(b"tampered bytes")
    (images / "mock_images" / "scene-002.jpg").write_bytes(b"fake image bytes")
    with pytest.raises(ManifestError, match="scene-001.jpg"):
        load_manifest(_write_manifest(tmp_path, data), images_dir=str(images))


def test_missing_image_file_names_offending_path(tmp_path):
    data = _valid_manifest_dict()
    images = tmp_path / "images"
    (images / "mock_images").mkdir(parents=True)
    (images / "mock_images" / "scene-001.jpg").write_bytes(b"fake image bytes")
    with pytest.raises(ManifestError, match="scene-002.jpg"):
        load_manifest(_write_manifest(tmp_path, data), images_dir=str(images))


def test_missing_images_dir_is_actionable(tmp_path):
    data = _valid_manifest_dict()
    with pytest.raises(ManifestError, match="GOLDEN_IMAGES_DIR"):
        load_manifest(
            _write_manifest(tmp_path, data),
            images_dir=str(tmp_path / "nonexistent"),
        )


def test_duplicate_path_rejected(tmp_path):  # S1-04
    data = _valid_manifest_dict()
    data["entries"][1]["path"] = data["entries"][0]["path"]
    with pytest.raises(ManifestError, match="duplicate path"):
        load_manifest(_write_manifest(tmp_path, data))


def test_empty_entries_rejected(tmp_path):  # S1-04
    data = _valid_manifest_dict()
    data["entries"] = []
    with pytest.raises(ManifestError, match="no entries"):
        load_manifest(_write_manifest(tmp_path, data))


def test_unsupported_manifest_version_rejected(tmp_path):  # S1-04
    data = _valid_manifest_dict()
    data["manifest_version"] = 999
    with pytest.raises(ManifestError, match="manifest_version"):
        load_manifest(_write_manifest(tmp_path, data))


def test_face_count_below_labeled_rejected(tmp_path):  # HARM-04 / S3-01 schema
    data = _valid_manifest_dict()
    data["entries"][0]["face_count"] = 0  # but present_identities has 1 name
    with pytest.raises(ManifestError, match="face_count"):
        load_manifest(_write_manifest(tmp_path, data))


def test_must_right_name_not_in_roster_rejected(tmp_path):  # S1-05
    data = _valid_manifest_dict()
    data["entries"][0]["must_right"] = ["Nobody Known"]
    with pytest.raises(ManifestError, match="roster"):
        load_manifest(_write_manifest(tmp_path, data))


def test_easy_wrong_name_not_in_roster_rejected(tmp_path):  # S1-05
    data = _valid_manifest_dict()
    data["entries"][0]["easy_wrong"] = ["Nobody Known"]
    with pytest.raises(ManifestError, match="roster"):
        load_manifest(_write_manifest(tmp_path, data))


def test_unknown_entry_key_rejected(tmp_path):  # S1-05 extra='forbid'
    data = _valid_manifest_dict()
    data["entries"][0]["surprise"] = True
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, data))


def test_policy_missing_recognition_enabled_rejected(tmp_path):  # S1-03
    data = _valid_manifest_dict()
    data["entries"][0]["policy"] = {"recogntion_enabled": True}  # typo -> extra key + missing required
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, data))


def test_rubric_empty_warns(tmp_path):  # S1-02
    data = _valid_manifest_dict()
    for entry in data["entries"]:
        entry["must_right"] = []
        entry["easy_wrong"] = []
    with pytest.warns(RubricEmptyWarning):
        load_manifest(_write_manifest(tmp_path, data))


def test_non_ascii_path_resolves_across_normalization_forms(tmp_path):  # S1-07
    decomposed = unicodedata.normalize("NFD", "Breiðamerkurjökull.jpg")
    composed = unicodedata.normalize("NFC", "Breiðamerkurjökull.jpg")
    body = b"glacier bytes"
    data = _valid_manifest_dict()
    data["entries"][0]["path"] = f"mock_images/{decomposed}"  # manifest in NFD
    data["entries"][0]["sha256"] = hashlib.sha256(body).hexdigest()
    images = tmp_path / "images"
    (images / "mock_images").mkdir(parents=True)
    (images / "mock_images" / composed).write_bytes(body)  # file on disk in NFC
    (images / "mock_images" / "scene-002.jpg").write_bytes(b"fake image bytes")
    manifest = load_manifest(_write_manifest(tmp_path, data), images_dir=str(images))
    assert len(manifest.entries) == 2


# --- VLM-2C Slice 1: real seed-corpus ground truth (operator-confirmed) ---

_SEED_MANIFEST = os.path.join(os.path.dirname(__file__), "seed", "golden.json")

# Operator-designated stranger fixture (VLM-2C Slice 1 confirmation pass):
# ryann-party.jpg — Ryann Wiseman + one genuine non-roster face on a
# recognition-enabled scene (the mixed true-rejection case E19-4a consumes).
_DESIGNATED_STRANGER_MEDIA_ID = 38


def _load_seed_manifest() -> GoldenManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RubricEmptyWarning)
        return load_manifest(_SEED_MANIFEST)


def test_seed_corpus_has_designated_stranger_entry():  # VLM-2C S1
    manifest = _load_seed_manifest()
    deltas = [
        e
        for e in manifest.entries
        if e.policy.recognition_enabled and e.face_count > len(e.present_identities)
    ]
    assert deltas, "seed corpus must keep >=1 recognition-enabled stranger-delta entry"
    designated = [e for e in deltas if e.media_id == _DESIGNATED_STRANGER_MEDIA_ID]
    assert designated, (
        f"designated stranger fixture media_id={_DESIGNATED_STRANGER_MEDIA_ID} "
        "missing or no longer carries a stranger delta"
    )
    entry = designated[0]
    assert entry.path == "mock_images/ryann-party.jpg"
    assert entry.present_identities == ["Ryann Wiseman"]
    assert entry.face_count - len(entry.present_identities) == 1


def test_seed_corpus_reconciles_with_fixture_scan():  # VLM-2C S1
    images_dir = os.environ.get("GOLDEN_IMAGES_DIR")
    if not images_dir:
        pytest.skip("GOLDEN_IMAGES_DIR not set (fixture bytes not vendored)")
    from scripts.eval_harness.draft_labels import generate_draft_manifest

    draft, _notes = generate_draft_manifest(images_dir)
    manifest = _load_seed_manifest()
    # kirstie-boat_detected.jpg is a detection-annotated near-duplicate VLM-2A
    # removed deliberately (seed/README.md); the draft scan re-introduces it.
    excluded = {"mock_images/kirstie-boat_detected.jpg"}
    draft_by_path = {e["path"]: e for e in draft["entries"] if e["path"] not in excluded}
    golden_by_path = {e.path: e for e in manifest.entries}
    assert set(draft_by_path) == set(golden_by_path)
    for path, golden_entry in golden_by_path.items():
        assert draft_by_path[path]["sha256"] == golden_entry.sha256, path
        assert draft_by_path[path]["media_id"] == golden_entry.media_id, path


def test_seed_corpus_caption_fixtures_populated():  # VLM-2C S2
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        manifest = load_manifest(_SEED_MANIFEST)
    assert not [w for w in caught if issubclass(w.category, RubricEmptyWarning)], (
        "seed corpus must define Must-Right/Easy-Wrong rubrics (RubricEmptyWarning fired)"
    )
    assert manifest.manifest_version == 2
    for entry in manifest.entries:
        pack = entry.context_pack
        assert pack.title or pack.caption or pack.description, f"{entry.path}: empty context_pack"
        assert entry.base_caption, f"{entry.path}: missing base_caption"
        for name in entry.present_identities:
            assert name in entry.base_caption, f"{entry.path}: base_caption misses {name}"
            assert name in (pack.title or "") + (pack.caption or "") + (pack.description or ""), (
                f"{entry.path}: context_pack never injects {name}"
            )
        assert set(entry.must_right) == set(entry.present_identities), (
            f"{entry.path}: must_right must equal the confirmed present identities"
        )
        assert entry.easy_wrong, f"{entry.path}: no wrong-name trap authored"
        assert not set(entry.easy_wrong) & set(entry.present_identities), (
            f"{entry.path}: easy_wrong may not contain a present identity"
        )
