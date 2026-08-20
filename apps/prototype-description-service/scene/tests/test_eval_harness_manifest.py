"""VLM-2A Slice 1: golden-manifest loader — structure + sha256 fail-fast (rg-008)."""

import hashlib
import json
import os
import unicodedata
import warnings

import pytest
from pydantic import ValidationError

from scripts.eval_harness.manifest import (
    AnnotationMode,
    GoldenEntry,
    GoldenManifest,
    ManifestError,
    ReferenceFact,
    RubricEmptyWarning,
    ScoreInvariant,
    SliceTag,
    load_manifest,
)


_MOCK_PROVENANCE = {
    "source": "fixture",
    "license": "fixture",
    "note": "vendored eval-corpus fixture",
}


def _test_lineage(*, decision: str = "named", capture_session_id: str | None = "test-session") -> dict:
    """Explicit test lineage — every field comes from this helper (rg-015)."""
    return {
        "labeler_id": "test-labeler",
        "batch_id": "test-batch",
        "capture_session_id": capture_session_id,
        "pass_index": 0,
        "labeled_at": "2026-08-14T00:00:00Z",
        "tool_version": "test",
        "saw_machine_proposals": False,
        "label_source": "operator_blind",
        "decision": decision,
        "confidence": "high",
        "arbitration_of": None,
    }


def _valid_manifest_dict() -> dict:
    img_hash = hashlib.sha256(b"fake image bytes").hexdigest()
    return {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        "roster": ["Alice Example", "Bob Example"],
        "entries": [
            {
                "path": "mock_images/scene-001.jpg",
                "sha256": img_hash,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "A title", "caption": "A caption"},
                "base_caption": "Alice Example by the water.",
                "must_right": ["Alice Example"],
                "easy_wrong": ["Bob Example"],
                "policy": {"recognition_enabled": True},
                "provenance": dict(_MOCK_PROVENANCE),
            },
            {
                "path": "mock_images/scene-002.jpg",
                "sha256": img_hash,
                "media_id": 2,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {},
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": dict(_MOCK_PROVENANCE),
            },
        ],
    }


def test_v2_requires_base_caption_key(tmp_path):  # S6-01
    data = _valid_manifest_dict()
    del data["entries"][0]["base_caption"]
    with pytest.raises(ManifestError, match="base_caption"):
        load_manifest(_write_manifest(tmp_path, data))


def test_v2_rejects_null_base_caption(tmp_path):  # VLMFIX-S3-03
    data = _valid_manifest_dict()
    data["entries"][0]["base_caption"] = None
    with pytest.raises(ManifestError, match="null base_caption|base_caption"):
        load_manifest(_write_manifest(tmp_path, data))


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


def test_media_id_below_one_rejected(tmp_path):
    # media_id is synthetic and 1-based (analyze keys image_<media_id>); 0/negative must
    # fail schema, matching the 'continue from 39, never reset to zero' contract (E-06).
    data = _valid_manifest_dict()
    data["entries"][0]["media_id"] = 0
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, data))


def test_reference_fact_rejects_whitespace_only_phrases():
    # A whitespace-only phrase is not a matchable target (match_targets filters it to
    # [""] and matches nothing); reject it so scoring is never silently vacuous (E-07).
    with pytest.raises(ValueError):
        ReferenceFact(text="   ", kind="object", phrases=["   "])
    # sanity: a genuine phrase (with blank text) still validates and yields the phrase.
    assert ReferenceFact(text="", kind="object", phrases=["a red hat"]).match_targets() == ["a red hat"]


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


def test_face_count_below_labeled_rejected(tmp_path):  # boxes_cover_face_count boxed form
    """Boxed form: face_count=0 with one named box still fails coverage.

    Distinct from present_identities_fit_face_count (unboxed identity claim).
    """
    data = _valid_manifest_dict()
    data["annotation_mode"] = "roster_only"
    data["entries"][0]["face_count"] = 0
    data["entries"][0]["present_identities"] = []
    data["entries"][0]["must_right"] = []
    data["entries"][0]["face_boxes"] = [
        {
            "x": 0.5,
            "y": 0.4,
            "w": 0.2,
            "h": 0.3,
            "name": "Alice Example",
            "source": "operator",
            "lineage": _test_lineage(decision="named"),
        }
    ]
    with pytest.raises(ManifestError, match="boxes_cover_face_count") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    err = exc_info.value
    assert err.invariant == "boxes_cover_face_count"
    assert err.entry_index == 0
    assert err.entry_path == data["entries"][0]["path"]
    assert "scene-001.jpg" in str(err)


def test_face_count_below_present_identities_rejected_unboxed(tmp_path):
    """S2R2-05: face_count=0 + present identity + no boxes is rejected.

    The retired _face_count_covers_labeled predicate. Identification must
    not treat an unbacked identity claim as labeled ground truth.
    """
    data = _valid_manifest_dict()
    data["annotation_mode"] = "roster_only"
    data["entries"][0]["face_count"] = 0
    data["entries"][0]["present_identities"] = ["Alice Example"]
    data["entries"][0]["face_boxes"] = []
    with pytest.raises(ManifestError, match="present_identities_fit_face_count") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    err = exc_info.value
    assert err.invariant == "present_identities_fit_face_count"
    assert err.entry_index == 0
    assert err.entry_path == data["entries"][0]["path"]
    assert "scene-001.jpg" in str(err)


def test_face_count_below_present_identities_rejected_exhaustive(tmp_path):
    """S2R2-05: same unbacked claim is rejected under exhaustive."""
    data = _valid_manifest_dict()
    data["annotation_mode"] = "exhaustive"
    data["entries"][0]["face_count"] = 0
    data["entries"][0]["present_identities"] = ["Alice Example"]
    data["entries"][0]["face_boxes"] = []
    data["entries"][1]["face_count"] = 0
    data["entries"][1]["face_boxes"] = []
    with pytest.raises(ManifestError, match="present_identities_fit_face_count") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    assert exc_info.value.invariant == "present_identities_fit_face_count"


def test_face_count_one_two_identities_rejected(tmp_path):
    """S2R2-05 near-miss: face_count=1, two identities, one box. 1 < 2."""
    data = _valid_manifest_dict()
    data["annotation_mode"] = "roster_only"
    data["entries"][0]["face_count"] = 1
    data["entries"][0]["present_identities"] = ["Alice Example", "Bob Example"]
    data["entries"][0]["face_boxes"] = [
        {
            "x": 0.5,
            "y": 0.4,
            "w": 0.2,
            "h": 0.3,
            "name": "Alice Example",
            "source": "operator",
            "lineage": _test_lineage(decision="named"),
        }
    ]
    with pytest.raises(ManifestError, match="present_identities_fit_face_count") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    assert exc_info.value.invariant == "present_identities_fit_face_count"
    assert exc_info.value.entry_index == 0


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
# muted-party.jpg — Muted Yarrow + one genuine non-roster face on a
# recognition-enabled scene (the mixed true-rejection case E19-4a consumes).
_DESIGNATED_STRANGER_MEDIA_ID = 38


def _load_seed_manifest() -> GoldenManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RubricEmptyWarning)
        return load_manifest(_SEED_MANIFEST)


def test_seed_corpus_has_designated_stranger_entry():  # VLM-2C S1
    manifest = _load_seed_manifest()
    deltas = [e for e in manifest.entries if e.policy.recognition_enabled and e.face_count > len(e.present_identities)]
    assert deltas, "seed corpus must keep >=1 recognition-enabled stranger-delta entry"
    designated = [e for e in deltas if e.media_id == _DESIGNATED_STRANGER_MEDIA_ID]
    assert designated, (
        f"designated stranger fixture media_id={_DESIGNATED_STRANGER_MEDIA_ID} "
        "missing or no longer carries a stranger delta"
    )
    entry = designated[0]
    assert entry.path == "mock_images/muted-party.jpg"
    assert entry.present_identities == ["Muted Yarrow"]
    assert entry.face_count - len(entry.present_identities) == 1


def test_seed_corpus_reconciles_with_fixture_scan():  # VLM-2C S1
    images_dir = os.environ.get("GOLDEN_IMAGES_DIR")
    if not images_dir:
        pytest.skip("GOLDEN_IMAGES_DIR not set (fixture bytes not vendored)")
    from scripts.eval_harness.draft_labels import generate_draft_manifest, normalize_rel_path

    draft, _notes = generate_draft_manifest(images_dir)
    manifest = _load_seed_manifest()
    # auburn-boat_detected.jpg is a detection-annotated near-duplicate VLM-2A
    # removed deliberately (seed/README.md); the draft scan re-introduces it.
    excluded = {"mock_images/auburn-boat_detected.jpg"}
    draft_paths = {e["path"] for e in draft["entries"]}
    assert excluded <= draft_paths, (
        "excluded near-duplicate missing from fixture scan — exclusion is vacuous; "
        "re-bootstrap the fixtures or update the exclusion list"
    )
    # S7-03: NFC-normalize before set equality so an NFD golden path matches an
    # NFC-materialized fixture scan (same flip _resolve_image covers at read time).
    draft_by_path = {
        normalize_rel_path(e["path"]): e for e in draft["entries"] if normalize_rel_path(e["path"]) not in excluded
    }
    golden_by_path = {normalize_rel_path(e.path): e for e in manifest.entries}
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
    assert manifest.manifest_version == 3
    assert manifest.annotation_mode.value == "roster_only"
    for entry in manifest.entries:
        pack = entry.context_pack
        assert pack.title or pack.caption or pack.description, f"{entry.path}: empty context_pack"
        assert entry.base_caption, f"{entry.path}: missing base_caption"
        for name in entry.present_identities:
            assert name in entry.base_caption, f"{entry.path}: base_caption misses {name}"
            assert any(name in field for field in (pack.title, pack.caption, pack.description) if field), (
                f"{entry.path}: context_pack never injects {name}"
            )
        assert set(entry.must_right) == set(entry.present_identities), (
            f"{entry.path}: must_right must equal the confirmed present identities"
        )
        assert entry.easy_wrong, f"{entry.path}: no wrong-name trap authored"
        assert not set(entry.easy_wrong) & set(entry.present_identities), (
            f"{entry.path}: easy_wrong may not contain a present identity"
        )


def test_seed_readme_documents_v2_corpus():  # VLM-2C S4
    with open(os.path.join(os.path.dirname(__file__), "seed", "README.md")) as handle:
        readme = handle.read()
    assert "are empty for every entry" not in readme, "stale VLM-2A rubric-empty claim"
    assert "manifest_version" in readme and "base_caption" in readme
    assert "phrase_boxes.json" in readme


# --- VLM-6 S1: Golden-100 additive schema -----------------------------------

# The pre-expansion golden-38 corpus, frozen by media_id so the historical
# face-P/R subset stays comparable after Golden-100 renumbers nothing below 39.
# Golden-100 additions MUST continue from media_id 39; this set is never edited.
GOLDEN_38_MEDIA_IDS = frozenset(
    {
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
    }
)


def test_legacy_entry_defaults_additive_fields(tmp_path):
    """A manifest predating Golden-100 loads; new fields default empty/None."""
    manifest = load_manifest(_write_manifest(tmp_path, _valid_manifest_dict()))
    e = manifest.entries[0]
    assert e.difficulty is None and e.domain is None
    assert e.reference_facts == [] and e.spatial_facts == []
    # provenance is required (FIR-11 Slice 1); remaining Golden-100 fields still default.
    assert e.provenance.source.value == "fixture"
    assert e.provenance.license.value == "fixture"
    # FIR-5 S1 / DATA-03: scalar domain + no tags/demographic_cohort still loads.
    assert e.tags == [] and e.demographic_cohort is None
    assert manifest.roster_cohorts == {}


def test_golden100_fields_roundtrip(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0].update(
        {
            "difficulty": "hard",
            "domain": "mirrors",
            "reference_facts": [
                {"text": "a mirror", "kind": "object", "phrases": ["mirror", "reflection"]},
                {"text": "two people", "kind": "count", "polarity": "false", "phrases": ["two people", "group"]},
            ],
            "spatial_facts": [{"subject": "Alice Example", "relation": "left_of", "reference": "Bob Example"}],
            "provenance": {"source": "wikimedia", "license": "cc0", "url": "http://example/x"},
        }
    )
    e = load_manifest(_write_manifest(tmp_path, data)).entries[0]
    assert e.difficulty.value == "hard" and e.domain.value == "mirrors"
    assert e.provenance.license.value == "cc0"
    false_facts = [f for f in e.reference_facts if f.polarity.value == "false"]
    assert false_facts and false_facts[0].match_targets() == ["two people", "group"]
    assert e.spatial_facts[0].reference == "Bob Example"


def test_reference_fact_phrases_fallback_to_text(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0]["reference_facts"] = [{"text": "a red bicycle", "kind": "object"}]
    e = load_manifest(_write_manifest(tmp_path, data)).entries[0]
    assert e.reference_facts[0].match_targets() == ["a red bicycle"]


def test_unknown_domain_rejected(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0]["domain"] = "not_a_real_stratum"
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, data))


def test_spatial_binary_relation_requires_reference(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0]["spatial_facts"] = [{"subject": "Alice Example", "relation": "left_of"}]
    with pytest.raises(ManifestError):
        load_manifest(_write_manifest(tmp_path, data))


def test_seed_corpus_uses_fixture_provenance():
    """Vendored seed pixels are fixture/fixture, not operator/mock_entity (PROV-01)."""
    seed_dir = os.path.join(os.path.dirname(__file__), "seed")
    for name in ("golden.json", "bakeoff_golden.json"):
        manifest = load_manifest(os.path.join(seed_dir, name))
        assert manifest.entries, f"{name} must not be empty"
        for entry in manifest.entries:
            assert entry.provenance.source.value == "fixture", entry.path
            assert entry.provenance.license.value == "fixture", entry.path
            assert entry.provenance.note == "vendored eval-corpus fixture", entry.path


def test_golden38_subset_pin():
    """The historical golden-38 media_ids are frozen (subset-pin, plan S1)."""
    path = os.path.join(os.path.dirname(__file__), "seed", "golden.json")
    manifest = load_manifest(path)
    ids = {e.media_id for e in manifest.entries}
    legacy = {i for i in ids if i <= 38}
    assert legacy == GOLDEN_38_MEDIA_IDS, (
        "golden-38 subset drifted; historical media_ids must never be renumbered — "
        "Golden-100 additions continue from media_id 39"
    )


# --- FIR-5 S1: SliceTag + cohort schema --------------------------------------


def test_multi_tag_roundtrip():
    """GoldenEntry with multiple SliceTags survives model_validate -> model_dump."""
    payload = {
        "path": "mock_images/scene-001.jpg",
        "sha256": "a" * 64,
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "base_caption": "",
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "tags": [SliceTag.MASKED, SliceTag.SUNGLASSES],
        "provenance": dict(_MOCK_PROVENANCE),
    }
    entry = GoldenEntry.model_validate(payload)
    assert entry.tags == [SliceTag.MASKED, SliceTag.SUNGLASSES]
    dumped = entry.model_dump()
    assert dumped["tags"] == [SliceTag.MASKED, SliceTag.SUNGLASSES]
    # JSON-mode dump preserves string values for enum members.
    dumped_json = entry.model_dump(mode="json")
    assert dumped_json["tags"] == ["masked", "sunglasses"]
    again = GoldenEntry.model_validate(dumped_json)
    assert again.tags == [SliceTag.MASKED, SliceTag.SUNGLASSES]


def test_legacy_domain_without_tags_or_cohort_loads(tmp_path):
    """DATA-03: scalar domain + omitted tags/demographic_cohort defaults cleanly."""
    data = _valid_manifest_dict()
    data["entries"][0]["domain"] = "people"
    # deliberately omit tags / demographic_cohort / roster_cohorts
    manifest = load_manifest(_write_manifest(tmp_path, data))
    e = manifest.entries[0]
    assert e.domain.value == "people"
    assert e.tags == []
    assert e.demographic_cohort is None
    assert manifest.roster_cohorts == {}


def test_unknown_tag_string_rejected_by_slicetag_enum():
    """Unknown tag strings fail SliceTag enum coercion — not extra='forbid'.

    extra='forbid' rejects unknown *fields*; enum validation rejects unknown
    *values* on a known field. These are distinct mechanisms (FIR-5 contract).
    """
    payload = {
        "path": "mock_images/scene-001.jpg",
        "sha256": "a" * 64,
        "media_id": 1,
        "face_count": 0,
        "present_identities": [],
        "base_caption": "",
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "tags": ["wearing_hat"],  # not a SliceTag member
        "provenance": dict(_MOCK_PROVENANCE),
    }
    with pytest.raises(ValidationError) as exc_info:
        GoldenEntry.model_validate(payload)
    err = exc_info.value
    # Enum coercion path: error is under tags, not an "extra_forbidden" on a field name.
    assert any(e["loc"][:1] == ("tags",) for e in err.errors())
    assert not any(e.get("type") == "extra_forbidden" for e in err.errors())


def test_unknown_tag_string_rejected_via_load_manifest(tmp_path):
    data = _valid_manifest_dict()
    data["entries"][0]["tags"] = ["wearing_hat"]
    with pytest.raises(ManifestError, match="schema violation"):
        load_manifest(_write_manifest(tmp_path, data))


def test_roster_cohorts_key_outside_roster_rejected(tmp_path):
    data = _valid_manifest_dict()
    data["roster_cohorts"] = {"Nobody Known": "cohort-a"}
    with pytest.raises(ManifestError, match="Nobody Known"):
        load_manifest(_write_manifest(tmp_path, data))


def test_valid_roster_cohorts_loads(tmp_path):
    data = _valid_manifest_dict()
    data["roster_cohorts"] = {
        "Alice Example": "cohort-a",
        "Bob Example": "cohort-b",
    }
    data["entries"][0]["demographic_cohort"] = "cohort-a"
    manifest = load_manifest(_write_manifest(tmp_path, data))
    assert manifest.roster_cohorts == {
        "Alice Example": "cohort-a",
        "Bob Example": "cohort-b",
    }
    assert manifest.entries[0].demographic_cohort == "cohort-a"


# --- FIR-11 Slice 2: annotation mode, coverage, lineage ----------------------


def test_exhaustive_face_count_mismatch_fails_validation(tmp_path):
    """Negative: exhaustive face_count=3 with one box fails coverage."""
    data = _valid_manifest_dict()
    data["annotation_mode"] = "exhaustive"
    data["entries"][0]["face_count"] = 3
    data["entries"][0]["face_boxes"] = [
        {
            "x": 0.5,
            "y": 0.4,
            "w": 0.2,
            "h": 0.3,
            "name": "Alice Example",
            "source": "operator",
            "lineage": _test_lineage(),
        }
    ]
    data["entries"][1]["face_count"] = 0
    with pytest.raises(ManifestError, match="boxes_cover_face_count") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    err = exc_info.value
    assert err.invariant == "boxes_cover_face_count"
    assert err.entry_index == 0
    assert err.entry_path == data["entries"][0]["path"]
    assert "scene-001.jpg" in str(err)


def test_roster_only_more_boxes_than_face_count_fails(tmp_path):
    """roster_only allows fewer boxes than face_count, never more."""
    data = _valid_manifest_dict()
    data["annotation_mode"] = "roster_only"
    data["entries"][0]["face_count"] = 1
    data["entries"][0]["face_boxes"] = [
        {
            "x": 0.2,
            "y": 0.2,
            "w": 0.1,
            "h": 0.1,
            "name": "Alice Example",
            "source": "operator",
            "lineage": _test_lineage(),
        },
        {
            "x": 0.7,
            "y": 0.7,
            "w": 0.1,
            "h": 0.1,
            "name": None,
            "source": "operator",
            "lineage": _test_lineage(decision="stranger"),
        },
    ]
    with pytest.raises(ManifestError, match="boxes_cover_face_count") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    err = exc_info.value
    assert err.invariant == "boxes_cover_face_count"
    assert err.entry_index == 0
    assert err.entry_path == data["entries"][0]["path"]
    assert "scene-001.jpg" in str(err)


def test_box_without_lineage_fails_validation(tmp_path):
    """Negative: a box without LabelLineage fails (PROV-01)."""
    data = _valid_manifest_dict()
    data["entries"][0]["face_boxes"] = [
        {"x": 0.5, "y": 0.4, "w": 0.2, "h": 0.3, "name": "Alice Example", "source": "operator"}
    ]
    with pytest.raises(ManifestError, match="label_lineage_required") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    err = exc_info.value
    assert err.invariant == "label_lineage_required"
    assert err.entry_index == 0
    assert err.entry_path == data["entries"][0]["path"]
    assert "scene-001.jpg" in str(err)


def test_exhaustive_box_missing_capture_session_id_fails(tmp_path):
    """Negative: exhaustive box without capture_session_id fails."""
    data = _valid_manifest_dict()
    data["annotation_mode"] = "exhaustive"
    data["entries"][0]["face_count"] = 1
    data["entries"][0]["face_boxes"] = [
        {
            "x": 0.5,
            "y": 0.4,
            "w": 0.2,
            "h": 0.3,
            "name": "Alice Example",
            "source": "operator",
            "lineage": _test_lineage(capture_session_id=None),
        }
    ]
    data["entries"][1]["face_count"] = 0
    with pytest.raises(ManifestError, match="capture_session_id_required") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    err = exc_info.value
    assert err.invariant == "capture_session_id_required"
    assert err.entry_index == 0
    assert err.entry_path == data["entries"][0]["path"]
    assert "scene-001.jpg" in str(err)


def test_missing_annotation_mode_fails(tmp_path):
    data = _valid_manifest_dict()
    del data["annotation_mode"]
    with pytest.raises(ManifestError, match="annotation_mode is required") as exc_info:
        load_manifest(_write_manifest(tmp_path, data))
    assert exc_info.value.invariant == "annotation_mode_required"
    assert "exhaustive|roster_only" in str(exc_info.value)


def test_exhaustive_matching_boxes_loads(tmp_path):
    """Positive pair: exhaustive with matching count and lineage+session loads."""
    data = _valid_manifest_dict()
    data["annotation_mode"] = "exhaustive"
    data["entries"][0]["face_count"] = 1
    data["entries"][0]["face_boxes"] = [
        {
            "x": 0.5,
            "y": 0.4,
            "w": 0.2,
            "h": 0.3,
            "name": "Alice Example",
            "source": "operator",
            "lineage": _test_lineage(),
        }
    ]
    data["entries"][1]["face_count"] = 0
    data["entries"][1]["face_boxes"] = []
    manifest = load_manifest(_write_manifest(tmp_path, data))
    assert manifest.annotation_mode is AnnotationMode.EXHAUSTIVE
    assert manifest.entries[0].face_boxes[0].lineage.capture_session_id == "test-session"


def test_retired_face_count_covers_labeled_is_gone():
    """The retired GoldenEntry check must not exist (replaced, not composed)."""
    assert not hasattr(GoldenEntry, "_face_count_covers_labeled")
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "scripts",
        "eval_harness",
        "manifest.py",
    )
    source = open(path, encoding="utf-8").read()
    assert "_face_count_covers_labeled" not in source
    assert "SUPPORTED_MANIFEST_VERSION = 3" in source


def test_seed_corpus_is_roster_only():
    manifest = _load_seed_manifest()
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert manifest.manifest_version == 3


def test_cli_gate_commands_do_not_reach_load_legacy_manifest(tmp_path, monkeypatch):
    """Behavioural: CLI score/score-face never call load_legacy_manifest.

    A source-text grep would stay green on a rename or a moved call.
    Audit-arm liveness is pinned by test_golden150_draft (legacy reader
    loads the frozen v2 artifact), not by invoking the patched sentinel.
    """
    import scripts.eval_harness.cli as cli_mod
    import scripts.eval_harness.manifest as man_mod

    hits: list[tuple] = []

    def _sentinel(*args, **kwargs):
        hits.append((args, kwargs))
        raise RuntimeError("legacy-sentinel-hit")

    monkeypatch.setattr(man_mod, "load_legacy_manifest", _sentinel)
    if hasattr(cli_mod, "load_legacy_manifest"):
        monkeypatch.setattr(cli_mod, "load_legacy_manifest", _sentinel)

    data = _valid_manifest_dict()
    man_path = tmp_path / "golden.json"
    man_path.write_text(json.dumps(data))
    record_path = tmp_path / "run.json"
    record_path.write_text(
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
                "items": [
                    {
                        "media_id": 1,
                        "path": data["entries"][0]["path"],
                        "describe": {"alt_text_draft": "Alice Example.", "visual_facts": {"objects": []}},
                        "identities": ["Alice Example"],
                        "face_count": 1,
                        "error": None,
                    },
                    {
                        "media_id": 2,
                        "path": data["entries"][1]["path"],
                        "describe": {"alt_text_draft": "empty.", "visual_facts": {"objects": []}},
                        "identities": [],
                        "face_count": 0,
                        "error": None,
                    },
                ],
            }
        )
    )
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    assert exc.value.code == 3
    assert hits == []

    face_record_path = tmp_path / "face-run.json"
    face_record_path.write_text(
        json.dumps(
            {
                "schema": "acx-eval/v1",
                "kind": "face_run_record",
                "provenance": {
                    "manifest_sha256": "m" * 64,
                    "head_sha": "0" * 40,
                    "started_at": "t",
                    "leg": "candidate",
                },
                "items": [],
            }
        )
    )
    # roster_only score-face raises via the CLI wrapper; pin the invariant.
    with pytest.raises(SystemExit, match=ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY) as exc_info:
        cli_mod.main(
            ["score-face", "--manifest", str(man_path), "--run-record", str(face_record_path)]
        )
    assert "score_face_run_record refuses roster_only" in str(exc_info.value)
    assert hits == []


def test_adjudication_rule_rejects_free_text():
    """MLDATA-03: a written rule is a closed enum, not unconstrained prose."""
    with pytest.raises(ValidationError, match="adjudication_rule"):
        ReferenceFact(
            text="wearing a red hat",
            kind="attribute",
            phrases=["red hat"],
            adjudicated_by="sme-03",
            adjudication_rule="coin-flip",
        )


def test_adjudicated_by_requires_written_rule():
    """MLDATA-03: claiming SME adjudication without a named rule is incomplete."""
    with pytest.raises(ValidationError, match="adjudication_rule"):
        ReferenceFact(
            text="wearing a red hat",
            kind="attribute",
            phrases=["red hat"],
            adjudicated_by="sme-03",
        )


def test_named_adjudication_rule_is_accepted():
    fact = ReferenceFact(
        text="wearing a red hat",
        kind="attribute",
        phrases=["red hat"],
        adjudicated_by="sme-03",
        adjudication_rule="disagreement-escalate-to-sme",
    )
    assert fact.adjudication_rule.value == "disagreement-escalate-to-sme"
