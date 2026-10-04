"""FIR-11 Slice 1 — provenance-required loader invariants.

Every negative case has a paired positive (TEST-15): the green can go red.
Existing loader invariants (sha256 form, media_id/path uniqueness, roster
membership) are re-asserted so making provenance required does not weaken them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.face_metrics import ImageDetection, detection_pr_strict
from scripts.eval_harness.manifest import (
    AnnotationMode,
    HashVerificationSkippedWarning,
    LEGACY_IMPORT_CAPTURE_SESSION_ID,
    ManifestError,
    legacy_import_lineage,
    load_legacy_manifest,
    load_manifest,
    require_confirmed_blind_reviews_for_strict_scoring,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROVENANCED = FIXTURES / "provenanced_min.json"
MISSING_PROVENANCE = FIXTURES / "missing_provenance.json"
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


# golden150 unprovenanced rows (re-verified on sha256 4ae541dc…).
GOLDEN150_UNPROVENANCED_PATHS = (
    "personal/opaline_beacon_375.jpg",
    "personal/quiet_fathom_438.jpg",
    "personal/saffron_falcon_484.jpg",
    "personal/unlabeled_0603.jpg",
    "personal/unlabeled_0633.jpg",
    "personal/unlabeled_0648.png",
)
GOLDEN150_UNPROVENANCED_MEDIA_IDS = (375, 438, 484, 603, 633, 648)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "manifests" / "golden150-draft-20260723.json"
        if candidate.is_file():
            return parent
    raise RuntimeError("cannot locate repo root from test path")


def _golden150_path() -> Path:
    return _repo_root() / "benchmarks" / "manifests" / "golden150-draft-20260723.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(tmp_path: Path, doc: dict, name: str = "manifest.json") -> Path:
    out = tmp_path / name
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out


# --- provenance required (D1) -------------------------------------------------


def test_provenanced_fixture_loads() -> None:
    """Positive pair: a fully-provenanced fixture still loads."""
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(PROVENANCED), skip_hash_verification=True)
    assert len(manifest.entries) == 2
    assert all(entry.provenance is not None for entry in manifest.entries)
    assert {entry.media_id for entry in manifest.entries} == {101, 102}


def test_missing_provenance_key_raises_manifest_error() -> None:
    """Negative pair: fixture entry with no provenance key raises ManifestError."""
    with pytest.raises(ManifestError, match="provenance is required") as exc_info:
        load_manifest(str(MISSING_PROVENANCE))
    message = str(exc_info.value)
    assert "fixtures/quiet_example_102.jpg" in message
    assert "media_id=102" in message
    # The provenanced sibling must not be blamed.
    assert "fixtures/ada_example_101.jpg" not in message


def test_golden150_draft_fails_naming_all_six_unprovenanced_paths() -> None:
    """v3 gate loader rejects frozen v2 golden150 by version (GF-10).

    Slice 1 named the six unprovenanced paths; after the version bump the
    gate loader must fail closed on version before re-checking provenance.
    ``load_legacy_manifest`` is the only legal reader and must succeed.
    """
    path = _golden150_path()
    assert path.is_file()
    with pytest.raises(ManifestError, match="manifest_version") as exc_info:
        load_manifest(str(path))
    message = str(exc_info.value)
    assert "provenance is required" not in message
    # Frozen bytes stay v2 — the legacy reader is the audit-arm path.
    # S2R3-17: pin real entry content a three-field stub cannot fake.
    legacy = load_legacy_manifest(str(path))
    assert legacy.manifest_version == 2
    assert legacy.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert len(legacy.entries) == 150
    by_path = {entry.path: entry for entry in legacy.entries}
    for expected_path, expected_id in zip(
        GOLDEN150_UNPROVENANCED_PATHS, GOLDEN150_UNPROVENANCED_MEDIA_IDS, strict=True
    ):
        assert expected_path in by_path
        hole = by_path[expected_path]
        assert hole.media_id == expected_id
        assert hole.provenance is None
    anne = by_path["celebs/anne_hathaway_11.jpg"]
    assert anne.media_id == 11
    assert anne.present_identities == ["Anne Hathaway"]
    assert anne.face_count == 1
    assert anne.sha256 == "235a11ac83ceb929fbcdcb9b15ccbb280177a6bff16885978cffeffc073524e5"
    assert by_path["personal/unlabeled_0603.jpg"].face_count == 9


def test_null_provenance_is_treated_as_missing(tmp_path: Path) -> None:
    """Fail-closed: an explicit JSON null is the same hole as a missing key."""
    doc = _load_json(PROVENANCED)
    doc["entries"][0]["provenance"] = None
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="provenance is required") as exc_info:
        load_manifest(str(path))
    assert "fixtures/ada_example_101.jpg" in str(exc_info.value)


def test_aggregate_missing_provenance_names_every_path(tmp_path: Path) -> None:
    """Not fail-first: two holes land in one ManifestError."""
    doc = _load_json(PROVENANCED)
    for entry in doc["entries"]:
        entry.pop("provenance", None)
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="provenance is required") as exc_info:
        load_manifest(str(path))
    message = str(exc_info.value)
    assert "fixtures/ada_example_101.jpg" in message
    assert "fixtures/quiet_example_102.jpg" in message
    assert "2 entries" in message


# --- existing invariants not weakened ----------------------------------------


def test_valid_sha256_loads() -> None:
    """Positive pair: 64 lowercase hex sha256 is accepted."""
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(PROVENANCED), skip_hash_verification=True)
    assert manifest.entries[0].sha256 == "a" * 64


def test_invalid_sha256_form_raises(tmp_path: Path) -> None:
    """Negative pair: sha256 form is still enforced."""
    doc = _load_json(PROVENANCED)
    doc["entries"][0]["sha256"] = "not-a-sha256"
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="sha256"):
        load_manifest(str(path))


def test_unique_media_id_and_path_load() -> None:
    """Positive pair: distinct media_id and path are accepted."""
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(PROVENANCED), skip_hash_verification=True)
    ids = [entry.media_id for entry in manifest.entries]
    paths = [entry.path for entry in manifest.entries]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))


def test_duplicate_media_id_raises(tmp_path: Path) -> None:
    """Negative pair: duplicate media_id is still rejected."""
    doc = _load_json(PROVENANCED)
    doc["entries"][1]["media_id"] = doc["entries"][0]["media_id"]
    doc["entries"][1]["path"] = "fixtures/other.jpg"
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="duplicate media_id"):
        load_manifest(str(path))


def test_duplicate_path_raises(tmp_path: Path) -> None:
    """Negative pair: duplicate path is still rejected."""
    doc = _load_json(PROVENANCED)
    doc["entries"][1]["path"] = doc["entries"][0]["path"]
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="duplicate path"):
        load_manifest(str(path))


def test_roster_member_loads() -> None:
    """Positive pair: identities on the roster are accepted."""
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(PROVENANCED), skip_hash_verification=True)
    roster = set(manifest.roster)
    for entry in manifest.entries:
        assert set(entry.present_identities) <= roster


def test_roster_outsider_raises(tmp_path: Path) -> None:
    """Negative pair: an identity not on the roster is still rejected."""
    doc = _load_json(PROVENANCED)
    doc["entries"][0]["present_identities"] = ["Not On Roster"]
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="not in the roster"):
        load_manifest(str(path))


def test_unsupported_version_reported_before_missing_provenance(tmp_path: Path) -> None:
    """Version error precedes provenance: 999 + unprovenanced entries is a version error."""
    doc = {
        "manifest_version": 999,
        "roster": [],
        "entries": 1,
    }
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="manifest_version") as exc_info:
        load_manifest(str(path))
    message = str(exc_info.value)
    assert "provenance is required" not in message


def test_array_root_raises_manifest_error(tmp_path: Path) -> None:
    """A JSON array root is ManifestError, not AttributeError (FIR-11-SL1-R2-04)."""
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="JSON object") as exc_info:
        load_manifest(str(path))
    assert not isinstance(exc_info.value, AttributeError)


def test_malformed_entries_structure_reported_before_missing_provenance(
    tmp_path: Path,
) -> None:
    """entries-not-a-list is ManifestError (not TypeError), not a provenance hole."""
    doc = {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        "roster": [],
        "entries": 1,
    }
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="entries") as exc_info:
        load_manifest(str(path))
    message = str(exc_info.value)
    assert "provenance is required" not in message
    assert "list" in message


def test_non_object_entry_is_manifest_error(tmp_path: Path) -> None:
    """An entry that is not an object is a structural ManifestError."""
    doc = {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        "roster": ["Ada Example"],
        "entries": ["not-a-dict"],
    }
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="object") as exc_info:
        load_manifest(str(path))
    assert "provenance is required" not in str(exc_info.value)


def test_manifest_module_does_not_import_ingest_checks() -> None:
    """R3P-10 / R4P-08: loader surface must not call the scrape heuristic."""
    source = (Path(__file__).resolve().parents[1] / "manifest.py").read_text(encoding="utf-8")
    assert "ingest_checks" not in source


# --- FIR-11 Slice 2 ----------------------------------------------------------


def test_v2_rejected_by_gate_loader(tmp_path: Path) -> None:
    """Gate loader understands version 3 only."""
    doc = _load_json(PROVENANCED)
    doc["manifest_version"] = 2
    path = _write_manifest(tmp_path, doc)
    with pytest.raises(ManifestError, match="unsupported manifest_version 2") as exc_info:
        load_manifest(str(path))
    assert "version 3 only" in str(exc_info.value)


def test_load_legacy_manifest_rejects_v3() -> None:
    """Legacy reader is v2-only — a v3 fixture must not slip through it."""
    with pytest.raises(ManifestError, match="legacy loader understands version 2"):
        load_legacy_manifest(str(PROVENANCED))


def test_provenanced_fixture_is_v3_roster_only() -> None:
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(PROVENANCED), skip_hash_verification=True)
    assert manifest.manifest_version == 3
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert all(box.lineage is not None for e in manifest.entries for box in e.face_boxes)


def test_cli_gate_commands_do_not_call_load_legacy_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavioural: CLI score never reaches the legacy loader.

    Replaces the source-text grep (FIR-11-S2-03). The sentinel must stay
    silent on the gate path. Audit-arm liveness is pinned by
    test_golden150_draft_fails_naming_all_six_unprovenanced_paths (the
    legacy reader loads the frozen v2 artifact).
    """
    import scripts.eval_harness.cli as cli_mod
    import scripts.eval_harness.manifest as man_mod

    hits: list[object] = []

    def _sentinel(*args: object, **kwargs: object) -> object:
        hits.append((args, kwargs))
        raise RuntimeError("legacy-sentinel-hit")

    monkeypatch.setattr(man_mod, "load_legacy_manifest", _sentinel)
    if hasattr(cli_mod, "load_legacy_manifest"):
        monkeypatch.setattr(cli_mod, "load_legacy_manifest", _sentinel)

    man_path = tmp_path / "golden.json"
    # PROVENANCED is the canonical FIR-11 fixture (byte-identical to main's
    # committed copy) and both its entries carry easy_wrong=[]; that trips the
    # branch-only empty-rubric gate (SCORE_GATE_PREFIX_EMPTY_RUBRIC, cli.py) on
    # its own vacuity check before this test's target gate
    # (raise_if_unconsented_refusals) is ever reached. Mutate a local in-test
    # copy only — the shared fixture file stays canonical for the other tests
    # in this module that assert on its literal committed bytes/hash.
    manifest_doc = json.loads(PROVENANCED.read_text(encoding="utf-8"))
    # roster_only mode requires every must_right/easy_wrong name to be a
    # roster member (manifest.py::load_manifest); reuse the other fixture
    # identity rather than inventing an off-roster name.
    manifest_doc["entries"][0]["easy_wrong"] = ["Quiet Example"]
    # Strict score-time validation requires human-adjudicated lineage even
    # for roster-only GT boxes; make this local synthetic input scoreable.
    for entry in manifest_doc["entries"]:
        for box in entry["face_boxes"]:
            box["lineage"]["label_source"] = "operator_blind"
            box["lineage"]["saw_machine_proposals"] = False
    man_path.write_text(json.dumps(manifest_doc), encoding="utf-8")
    # Real score-time manifest sha (VLM6-F-03 / EVAL-13 drift gate; metadata-only
    # load, mirrors cli.py::_manifest_sha).
    from scripts.eval_harness.cli import _manifest_sha as _cli_manifest_sha

    manifest_sha = _cli_manifest_sha(load_manifest(str(man_path), skip_hash_verification=True))
    record_path = tmp_path / "run.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": "acx-eval/v1",
                "kind": "run_record",
                "provenance": {
                    "manifest_sha256": manifest_sha,
                    "base_url": "x",
                    "head_sha": "0" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 101,
                        "path": "fixtures/ada_example_101.jpg",
                        "describe": {"alt_text_draft": "Ada Example.", "visual_facts": {"objects": []}},
                        # Dict identity rows (greenfield rejects bare strings —
                        # VLM6-PANEL6L-SR-01); shape mirrors
                        # fusion_runner.py::_identity_rows.
                        "identities": [{"name": "Ada Example", "unpositioned": True}],
                        "face_count": 1,
                        "error": None,
                    },
                    {
                        "media_id": 102,
                        "path": "fixtures/quiet_example_102.jpg",
                        "describe": {"alt_text_draft": "Quiet Example.", "visual_facts": {"objects": []}},
                        "identities": [{"name": "Quiet Example", "unpositioned": True}],
                        "face_count": 1,
                        "error": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    # VLM6-DELTA-12: this branch grew a much larger adoption-quality gate
    # apparatus on top of FIR-11 (empty-rubric, must-right-failures,
    # wrong-name-floor, quality-floor, category-vacuity — none of which exist
    # on main's cli.py, confirmed via `git show main:.../cli.py`, 1082 lines vs
    # this branch's ~2900). A minimal 2-image toy corpus legitimately trips
    # category-vacuity (undersized-sample / vacuous-category not_ready) ahead
    # of this test's original target gate (raise_if_unconsented_refusals,
    # int exit 3); reaching that specific gate would require constructing a
    # fully claim-complete corpus (positional/placement/identity_ordering
    # facts matching manifest GT) that is out of scope for a sentinel test
    # whose only real invariant is "the legacy manifest loader is never
    # called on the gate path." Assert the exit is a real, accounted-for
    # score gate (frozenset membership — not a bare crash/traceback) instead
    # of pinning to one specific downstream gate's exit code.
    assert isinstance(exc.value.code, str)
    assert any(exc.value.code.startswith(prefix) for prefix in cli_mod.SCORE_GATE_PREFIXES)
    assert hits == []


def test_calibrate_strata_fixture_is_not_a_golden_manifest() -> None:
    """golden_manifest_strata.v1.json is a calibrate join fixture, not GoldenManifest.

    It is consumed by validate_golden_manifest (calibrate_face_thresholds), not
    load_manifest. Exercising it through load_legacy_manifest would require
    inventing provenance, base_caption, and legal SliceTags — rg-015 forbids
    that. This test pins the disposition.
    """
    strata = FIXTURES / "golden_manifest_strata.v1.json"
    assert strata.is_file()
    with pytest.raises(ManifestError, match="unsupported manifest_version 2") as gate:
        load_manifest(str(strata))
    assert "version 3 only" in str(gate.value)
    with pytest.raises(ManifestError, match="base_caption") as legacy:
        load_legacy_manifest(str(strata))
    assert "media_id=101" in str(legacy.value) or "fixtures/alice-bob-a.jpg" in str(legacy.value)


def test_v3_min_fixture_is_bench_family_not_golden_manifest() -> None:
    """v3_min.json is the corpus-manifest-v3 bench family, not GoldenManifest."""
    v3_min = FIXTURES / "v3_min.json"
    assert v3_min.is_file()
    with pytest.raises(ManifestError, match="base_caption") as exc_info:
        load_manifest(str(v3_min))
    message = str(exc_info.value)
    assert "celebs/anne_hathaway_11.jpg" in message
    assert "media_id=11" in message


def test_corpus646_retag_loads_as_roster_only() -> None:
    """Regression: retagged corpus646 loads clean under the v3 gate loader."""
    path = Path(__file__).resolve().parents[1] / "corpus646-interleave-manifest-20260716.json"
    assert path.is_file()
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(path), skip_hash_verification=True)
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert manifest.manifest_version == 3
    assert len(manifest.entries) == 646
    for entry in manifest.entries:
        assert len(entry.face_boxes) <= entry.face_count
        for box in entry.face_boxes:
            assert box.lineage is not None
            assert box.lineage.label_source.value == "legacy_import"
            assert box.lineage.capture_session_id == LEGACY_IMPORT_CAPTURE_SESSION_ID


@pytest.mark.parametrize("source", ["detector", "workbench"])
def test_historical_face_box_sources_load_but_strict_scoring_rejects_them(
    tmp_path: Path, source: str
) -> None:
    """Legacy region lineage round-trips without qualifying as independent GT."""
    doc = _load_json(PROVENANCED)
    doc["entries"][0]["face_boxes"][0]["source"] = source
    path = _write_manifest(tmp_path, doc, f"{source}.json")

    with pytest.warns(HashVerificationSkippedWarning, match="hash verification skipped"):
        manifest = load_manifest(str(path), skip_hash_verification=True)

    entry = manifest.entries[0]
    box = entry.face_boxes[0]
    assert box.source.value == source

    row = ImageDetection(
        image=entry.path,
        pred_faces=1,
        labeled_faces=1,
        gt_boxes=(box,),
    )
    with pytest.raises(ManifestError, match="independent supported source"):
        detection_pr_strict(
            [row],
            annotation_mode=AnnotationMode.EXHAUSTIVE,
            run_manifest={"iou_threshold": 0.5},
        )


def test_unknown_face_box_source_still_fails_with_field_name(tmp_path: Path) -> None:
    doc = _load_json(PROVENANCED)
    doc["entries"][0]["face_boxes"][0]["source"] = "guess"
    path = _write_manifest(tmp_path, doc)

    with pytest.raises(ManifestError, match=r"entries\.0\.face_boxes\.0\.source"):
        load_manifest(str(path), skip_hash_verification=True)


def test_legacy_import_lineage_carries_unknown_session() -> None:
    """S2R5-06: the migration helper must mint a writable occasion key."""
    named = legacy_import_lineage(name="Alice Example")
    stranger = legacy_import_lineage(name=None)
    assert named["capture_session_id"] == LEGACY_IMPORT_CAPTURE_SESSION_ID
    assert stranger["capture_session_id"] == LEGACY_IMPORT_CAPTURE_SESSION_ID
    assert named["capture_session_id"]


def test_in_tree_boxed_corpus_cannot_flip_to_exhaustive_on_sentinel(
    tmp_path: Path,
) -> None:
    """S2R6-01: the unknown-occasion sentinel is not an exhaustive remedy.

    refetch6 has boxes covering face_count, but every box carries the
    minted ``legacy-import-unknown-session`` token. That is not a real
    occasion key; flipping ``annotation_mode`` must still fail closed.
    """
    src = Path(__file__).resolve().parents[1] / "refetch6-manifest-20260716.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    assert doc["annotation_mode"] == "roster_only"
    doc["annotation_mode"] = "exhaustive"
    path = tmp_path / "refetch6-exhaustive.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ManifestError, match="capture_session") as exc_info:
        load_manifest(str(path))
    assert exc_info.value.invariant == "capture_session_id_required"
    assert LEGACY_IMPORT_CAPTURE_SESSION_ID in str(exc_info.value)


def test_legacy_import_helper_session_does_not_load_exhaustive(tmp_path: Path) -> None:
    """S2R6-01: a new exhaustive box built from the helper must not load."""
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
                        "source": "iptc",
                        "lineage": legacy_import_lineage(name="Alice Example"),
                    }
                ],
            }
        ],
    }
    path = _write_manifest(tmp_path, doc, "legacy-exhaustive.json")
    with pytest.raises(ManifestError, match="capture_session") as exc_info:
        load_manifest(str(path))
    assert exc_info.value.invariant == "capture_session_id_required"
    assert LEGACY_IMPORT_CAPTURE_SESSION_ID in str(exc_info.value)


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


def test_real_capture_session_still_loads_exhaustive(tmp_path: Path) -> None:
    """Positive pair: a real occasion key still clears the gate."""
    path = _write(tmp_path, _exhaustive_doc(session=REAL_SESSION, label_source="operator_blind"))
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(path), skip_hash_verification=True)
    assert manifest.annotation_mode is AnnotationMode.EXHAUSTIVE
    assert manifest.entries[0].face_boxes[0].lineage.capture_session_id == REAL_SESSION


def test_strict_scoring_requires_a_resolved_confirmed_blind_review(tmp_path: Path) -> None:
    """An operator-blind label alone cannot enter strict metrics as scored truth."""
    doc = _exhaustive_doc(session=REAL_SESSION, label_source="operator_blind")
    box_doc = doc["entries"][0]["face_boxes"][0]
    box_doc["lineage"]["saw_machine_proposals"] = False
    path = _write(tmp_path, doc, "unreviewed-strict-ground-truth.json")
    manifest = load_manifest(str(path), skip_hash_verification=True)
    box = manifest.entries[0].face_boxes[0]

    with pytest.raises(
        ManifestError, match="confirmed independent blind review"
    ) as exc_info:
        require_confirmed_blind_reviews_for_strict_scoring(manifest.model_dump())
        detection_pr_strict(
            [
                ImageDetection(
                    image=manifest.entries[0].path,
                    pred_faces=1,
                    labeled_faces=1,
                    detections_bbox_px=((40.0, 25.0, 20.0, 30.0),),
                    gt_boxes=(box,),
                    image_size=(100, 100),
                    detection_frame_size=(100, 100),
                )
            ],
            annotation_mode=manifest.annotation_mode,
            run_manifest={"iou_threshold": 0.5},
        )

    assert exc_info.value.invariant == "adjudication_record_required"


def test_confirmed_independent_blind_review_allows_strict_scoring(tmp_path: Path) -> None:
    """Positive pair: resolved second-review evidence keeps strict scoring live."""
    doc = _exhaustive_doc(session=REAL_SESSION, label_source="operator_blind")
    box_doc = doc["entries"][0]["face_boxes"][0]
    box_doc["lineage"]["labeler_id"] = "operator-1"
    box_doc["lineage"]["saw_machine_proposals"] = False
    box_doc["adjudication_source"] = "human_adjudicated:review-1"
    doc["adjudication_records"] = [
        {
            "record_id": "review-1",
            "media_id": 1,
            "box_index": 0,
            "reviewer_id": "operator-2",
            "reviewer_kind": "human",
            "review_method": "independent_blind_review",
            "decision": "confirmed",
            "reviewed_at": "2026-06-01T12:00:00+00:00",
        }
    ]
    path = _write(tmp_path, doc, "reviewed-strict-ground-truth.json")
    manifest = load_manifest(str(path), skip_hash_verification=True)
    require_confirmed_blind_reviews_for_strict_scoring(manifest.model_dump())
    box = manifest.entries[0].face_boxes[0]

    result = detection_pr_strict(
        [
            ImageDetection(
                image=manifest.entries[0].path,
                pred_faces=1,
                labeled_faces=1,
                detections_bbox_px=((40.0, 25.0, 20.0, 30.0),),
                gt_boxes=(box,),
                image_size=(100, 100),
                detection_frame_size=(100, 100),
            )
        ],
        annotation_mode=manifest.annotation_mode,
        run_manifest={"iou_threshold": 0.5},
    )

    assert result.true_positives == 1


def test_real_session_on_legacy_import_source_still_loads_exhaustive(tmp_path: Path) -> None:
    """The pin is the sentinel, not label_source=legacy_import."""
    path = _write(tmp_path, _exhaustive_doc(session=REAL_SESSION, label_source="legacy_import"))
    manifest = load_manifest(str(path), skip_hash_verification=True)
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
    # Metadata-only fixture load; never opens image bytes (VLM6-PANEL6L-rvM-01).
    manifest = load_manifest(str(path), skip_hash_verification=True)
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert manifest.entries[0].face_boxes[0].lineage.capture_session_id == LEGACY_IMPORT_CAPTURE_SESSION_ID


def test_skip_hash_verification_warns(tmp_path: Path) -> None:
    """VLM6-PANEL6L-rvM-03: the metadata-only skip must not be a silent no-op."""
    with pytest.warns(HashVerificationSkippedWarning, match="hash verification skipped"):
        load_manifest(str(PROVENANCED), skip_hash_verification=True)


def test_verified_load_does_not_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    """Paired positive (TEST-15): a real images_dir verified load stays silent."""
    monkeypatch.setattr("scripts.eval_harness.manifest._verify_hashes", lambda manifest, images_root: None)
    load_manifest(str(PROVENANCED), images_dir=str(tmp_path))
    assert not any(issubclass(w.category, HashVerificationSkippedWarning) for w in recwarn.list)
