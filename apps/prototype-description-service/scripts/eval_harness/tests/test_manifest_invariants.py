"""FIR-11 Slice 1 — provenance-required loader invariants.

Every negative case has a paired positive (TEST-15): the green can go red.
Existing loader invariants (sha256 form, media_id/path uniqueness, roster
membership) are re-asserted so making provenance required does not weaken them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import ManifestError, load_manifest

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
    """Real-data proof: unmodified golden150-draft fails and names all 6 paths."""
    path = _golden150_path()
    assert path.is_file()
    with pytest.raises(ManifestError, match="provenance is required") as exc_info:
        load_manifest(str(path))
    message = str(exc_info.value)
    for rel_path, media_id in zip(
        GOLDEN150_UNPROVENANCED_PATHS, GOLDEN150_UNPROVENANCED_MEDIA_IDS, strict=True
    ):
        assert rel_path in message, f"missing path {rel_path} in: {message}"
        assert f"media_id={media_id}" in message, f"missing media_id {media_id} in: {message}"
    assert "6 entries" in message


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


def test_manifest_module_does_not_import_ingest_checks() -> None:
    """R3P-10 / R4P-08: loader surface must not call the scrape heuristic."""
    source = (
        Path(__file__).resolve().parents[1] / "manifest.py"
    ).read_text(encoding="utf-8")
    assert "ingest_checks" not in source
