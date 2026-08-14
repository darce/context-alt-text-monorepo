"""VLM-2A Slice 1: draft-label generator — filename heuristics feeding operator confirmation."""

import hashlib

import pytest

from scripts.eval_harness.draft_labels import generate_draft_manifest
from scripts.eval_harness.manifest import GoldenManifest


@pytest.fixture()
def fixture_dirs(tmp_path):
    entities = tmp_path / "mock_entities"
    images = tmp_path / "mock_images"
    entities.mkdir()
    images.mkdir()
    for name in [
        "entity-alice-example.jpg",
        "entity-alice-example-2.jpg",
        "entity-bob-builder.png",
    ]:
        (entities / name).write_bytes(name.encode())
    for name in [
        "alice-pool.jpg",
        "alice-bob-beach.jpg",
        "glacier.jpg",
        "stranger-nina.jpg",
    ]:
        (images / name).write_bytes(name.encode())
    return tmp_path


def test_roster_derived_from_entity_filenames(fixture_dirs):
    draft, _notes = generate_draft_manifest(str(fixture_dirs))
    assert draft["roster"] == ["Alice Example", "Bob Builder"]


def test_scene_entries_get_stable_media_ids_and_hashes(fixture_dirs):
    draft, _notes = generate_draft_manifest(str(fixture_dirs))
    entries = draft["entries"]
    assert [e["media_id"] for e in entries] == list(range(1, len(entries) + 1))
    first = entries[0]
    expected = hashlib.sha256((fixture_dirs / "mock_images" / first["path"].split("/")[-1]).read_bytes()).hexdigest()
    assert first["sha256"] == expected


def test_identity_guesses_from_filename_tokens(fixture_dirs):
    draft, _notes = generate_draft_manifest(str(fixture_dirs))
    by_path = {e["path"]: e for e in draft["entries"]}
    assert by_path["mock_images/alice-pool.jpg"]["present_identities"] == ["Alice Example"]
    assert by_path["mock_images/alice-bob-beach.jpg"]["present_identities"] == [
        "Alice Example",
        "Bob Builder",
    ]
    assert by_path["mock_images/glacier.jpg"]["present_identities"] == []


def test_unmatched_tokens_flagged_for_operator_review(fixture_dirs):
    _draft, notes = generate_draft_manifest(str(fixture_dirs))
    joined = "\n".join(notes)
    assert "stranger-nina.jpg" in joined
    assert "glacier.jpg" in joined


def test_draft_stamps_fixture_provenance(fixture_dirs):
    """Draft default is fixture/fixture — not operator/mock_entity (PROV-01)."""
    draft, _notes = generate_draft_manifest(str(fixture_dirs))
    assert draft["entries"]
    for entry in draft["entries"]:
        assert entry["provenance"] == {
            "source": "fixture",
            "license": "fixture",
            "note": "vendored eval-corpus fixture",
        }


def test_draft_passes_strict_schema(fixture_dirs, tmp_path):
    import json

    draft, _notes = generate_draft_manifest(str(fixture_dirs))
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(draft))
    from scripts.eval_harness.manifest import load_manifest

    manifest = load_manifest(str(path), images_dir=str(fixture_dirs))
    assert isinstance(manifest, GoldenManifest)


def test_missing_fixture_dirs_actionable(tmp_path):
    from scripts.eval_harness.manifest import ManifestError

    with pytest.raises(ManifestError, match="GOLDEN_IMAGES_DIR"):
        generate_draft_manifest(str(tmp_path / "nope"))
