"""VLM-2A Slice 1: golden-manifest loader — structure + sha256 fail-fast (rg-008)."""

import hashlib
import json

import pytest

from scripts.eval_harness.manifest import (
    GoldenManifest,
    ManifestError,
    load_manifest,
)


def _valid_manifest_dict() -> dict:
    img_hash = hashlib.sha256(b"fake image bytes").hexdigest()
    return {
        "manifest_version": 1,
        "roster": ["Alice Example", "Bob Example"],
        "entries": [
            {
                "path": "mock_images/scene-001.jpg",
                "sha256": img_hash,
                "media_id": 1,
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
