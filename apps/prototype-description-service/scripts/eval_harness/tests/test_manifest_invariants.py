"""FIR-11 Slice 1 — provenance-required loader invariants.

Every negative case has a paired positive (TEST-15): the green can go red.
Existing loader invariants (sha256 form, media_id/path uniqueness, roster
membership) are re-asserted so making provenance required does not weaken them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import (
    AnnotationMode,
    ManifestError,
    load_legacy_manifest,
    load_manifest,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROVENANCED = FIXTURES / "provenanced_min.json"
MISSING_PROVENANCE = FIXTURES / "missing_provenance.json"

# golden150 unprovenanced rows (re-verified on sha256 4ae541dc…).
GOLDEN150_UNPROVENANCED_PATHS = (
    "personal/alicia_graff_375.jpg",
    "personal/barbara_fransen_438.jpg",
    "personal/erika_lind_484.jpg",
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
    manifest = load_manifest(str(PROVENANCED))
    assert len(manifest.entries) == 2
    assert all(entry.provenance is not None for entry in manifest.entries)
    assert {entry.media_id for entry in manifest.entries} == {101, 102}


def test_missing_provenance_key_raises_manifest_error() -> None:
    """Negative pair: fixture entry with no provenance key raises ManifestError."""
    with pytest.raises(ManifestError, match="provenance is required") as exc_info:
        load_manifest(str(MISSING_PROVENANCE))
    message = str(exc_info.value)
    assert "fixtures/bea_example_102.jpg" in message
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
    legacy = load_legacy_manifest(str(path))
    assert legacy.manifest_version == 2
    assert legacy.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert len(legacy.entries) == 150


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
    assert "fixtures/bea_example_102.jpg" in message
    assert "2 entries" in message


# --- existing invariants not weakened ----------------------------------------


def test_valid_sha256_loads() -> None:
    """Positive pair: 64 lowercase hex sha256 is accepted."""
    manifest = load_manifest(str(PROVENANCED))
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
    manifest = load_manifest(str(PROVENANCED))
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
    manifest = load_manifest(str(PROVENANCED))
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
    source = (
        Path(__file__).resolve().parents[1] / "manifest.py"
    ).read_text(encoding="utf-8")
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
    manifest = load_manifest(str(PROVENANCED))
    assert manifest.manifest_version == 3
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert all(box.lineage is not None for e in manifest.entries for box in e.face_boxes)


def test_cli_gate_commands_do_not_call_load_legacy_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavioural: CLI score never reaches the legacy loader.

    Replaces the source-text grep (FIR-11-S2-03). The sentinel must fire on
    the audit-arm path and must stay silent on the gate path.
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
    man_path.write_text(PROVENANCED.read_text(encoding="utf-8"), encoding="utf-8")
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
                        "media_id": 101,
                        "path": "fixtures/ada_example_101.jpg",
                        "describe": {"alt_text_draft": "Ada Example.", "visual_facts": {"objects": []}},
                        "identities": ["Ada Example"],
                        "face_count": 1,
                        "error": None,
                    },
                    {
                        "media_id": 102,
                        "path": "fixtures/bea_example_102.jpg",
                        "describe": {"alt_text_draft": "Bea Example.", "visual_facts": {"objects": []}},
                        "identities": ["Bea Example"],
                        "face_count": 1,
                        "error": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    assert hits == []

    with pytest.raises(RuntimeError, match="legacy-sentinel-hit"):
        man_mod.load_legacy_manifest(str(_golden150_path()))
    assert hits, "audit-arm path must reach load_legacy_manifest"


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
    manifest = load_manifest(str(path))
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert manifest.manifest_version == 3
    assert len(manifest.entries) == 646
    for entry in manifest.entries:
        assert len(entry.face_boxes) <= entry.face_count
        for box in entry.face_boxes:
            assert box.lineage is not None
            assert box.lineage.label_source.value == "legacy_import"
