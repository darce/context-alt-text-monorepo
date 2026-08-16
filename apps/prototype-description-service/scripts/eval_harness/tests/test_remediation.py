"""FIR-11 Slice 1 — attestation schema/validator + emitters (synthetic only).

STOP: these tests never author a real golden150-attestation jsonl and never
run the golden150 emitter against the real draft.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import LicenseTag, ManifestError, ProvenanceSource, load_manifest
from scripts.eval_harness.remediation import (
    ATTESTATION_THIRD_PARTY_RATIONALE,
    ATTESTATION_UNKNOWN_RATIONALE,
    FIXED_CELEB_DROP_IDS,
    FIXED_CELEB_DROP_RATIONALE,
    FIXED_RETAG_IDS,
    FIXED_RETAG_RATIONALE,
    FIXED_SCRAPE_DROP_IDS,
    FIXED_SCRAPE_DROP_RATIONALE,
    V3_IDENTITY_CLAIM_DROP_IDS,
    V3_IDENTITY_CLAIM_DROP_RATIONALE,
    V3_SOURCE_SHA256,
    AttestationBasis,
    AttestationKind,
    AttestationRecord,
    MemoryRateCapError,
    RemediationError,
    emit_corpus_v3r,
    emit_remediated_manifest,
    load_and_validate_attestation,
    load_attestation_jsonl,
    validate_attestation_pass,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC_DRAFT = FIXTURES / "synthetic_draft.json"
SYNTHETIC_ATTESTATION = FIXTURES / "synthetic_attestation.jsonl"
V3_MIN = FIXTURES / "v3_min.json"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "benchmarks" / "manifests" / "corpus-manifest-v3.json").is_file():
            return parent
    raise RuntimeError("cannot locate repo root")


def _hex(tag: int) -> str:
    return f"{tag:03d}" + "0" * 58 + f"{tag:03d}"


def _entry(
    media_id: int,
    *,
    name: str | None = "Ada Example",
    sha: str | None = None,
) -> dict:
    identities = [name] if name else []
    return {
        "path": f"fixtures/item_{media_id}.jpg",
        "sha256": sha or _hex(media_id),
        "media_id": media_id,
        "face_count": 1 if name else 0,
        "present_identities": identities,
        "base_caption": "",
        "must_right": identities,
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "provenance": {
            "source": "operator",
            "license": "consented",
            "note": "synthetic",
        },
    }


def _draft(tmp_path: Path, media_ids: list[int], roster: list[str] | None = None) -> Path:
    doc = {
        "manifest_version": 3,
            "annotation_mode": "roster_only",
        "roster": roster or ["Ada Example"],
        "entries": [_entry(mid) for mid in media_ids],
    }
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def _record(
    media_id: int,
    *,
    attestation: str = "own_capture",
    basis: str = "pixels",
    attested_by: str = "fixture-operator",
    sha: str | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "media_id": media_id,
        "sha256": sha or _hex(media_id),
        "attestation": attestation,
        "basis": basis,
        "attested_by": attested_by,
        "note": "",
        "attested_at": "2026-08-14T00:00:00Z",
    }
    if extra:
        payload.update(extra)
    return payload


def _jsonl(tmp_path: Path, records: list[dict], name: str = "attestation.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


# --- D3 schema + validator ---------------------------------------------------


def test_valid_attestation_file_passes(tmp_path: Path) -> None:
    """Positive: a complete, well-formed jsonl joins the draft."""
    draft = load_manifest(str(_draft(tmp_path, [1, 2, 3])))
    path = _jsonl(tmp_path, [_record(1), _record(2), _record(3)])
    attested = load_and_validate_attestation(path, draft)
    assert attested.adjudicated == 3
    assert attested.memory_keeps == 0
    assert set(attested.by_media_id) == {1, 2, 3}


def test_unknown_field_rejected(tmp_path: Path) -> None:
    """Negative: unknown fields are rejected."""
    path = _jsonl(tmp_path, [_record(1, extra={"invented": True})])
    with pytest.raises(RemediationError, match="invented|extra"):
        load_attestation_jsonl(path)


def test_missing_attested_by_rejected(tmp_path: Path) -> None:
    """Negative: testimony without a named attester is rejected (R4P-20)."""
    payload = _record(1)
    del payload["attested_by"]
    path = _jsonl(tmp_path, [payload])
    with pytest.raises(RemediationError, match="attested_by"):
        load_attestation_jsonl(path)


def test_empty_attested_by_rejected(tmp_path: Path) -> None:
    """Negative: blank attested_by is the same hole as a missing field."""
    path = _jsonl(tmp_path, [_record(1, attested_by="   ")])
    with pytest.raises(RemediationError, match="attested_by"):
        load_attestation_jsonl(path)


def test_sha256_mismatch_rejected(tmp_path: Path) -> None:
    """Negative: record sha256 must match the manifest entry."""
    draft = load_manifest(str(_draft(tmp_path, [1])))
    path = _jsonl(tmp_path, [_record(1, sha="f" * 64)])
    records = load_attestation_jsonl(path)
    with pytest.raises(RemediationError, match="sha256"):
        validate_attestation_pass(records, draft)


def test_absent_media_id_rejected(tmp_path: Path) -> None:
    """Negative: a record for a media_id not in the manifest is rejected."""
    draft = load_manifest(str(_draft(tmp_path, [1])))
    path = _jsonl(tmp_path, [_record(1), _record(99)])
    records = load_attestation_jsonl(path)
    with pytest.raises(RemediationError, match="absent from manifest"):
        validate_attestation_pass(records, draft)


def test_duplicate_media_id_rejected(tmp_path: Path) -> None:
    """Negative: two records for one media_id are rejected."""
    draft = load_manifest(str(_draft(tmp_path, [1])))
    path = _jsonl(tmp_path, [_record(1), _record(1)])
    records = load_attestation_jsonl(path)
    with pytest.raises(RemediationError, match="duplicate"):
        validate_attestation_pass(records, draft)


def test_incomplete_pass_rejected(tmp_path: Path) -> None:
    """Negative: a complete pass requires exactly one record per entry."""
    draft = load_manifest(str(_draft(tmp_path, [1, 2])))
    path = _jsonl(tmp_path, [_record(1)])
    records = load_attestation_jsonl(path)
    with pytest.raises(RemediationError, match="incomplete"):
        validate_attestation_pass(records, draft)


def test_closed_vocabularies_are_strenum() -> None:
    """sr-007: attestation and basis are StrEnum, not free strings."""
    assert issubclass(AttestationKind, __import__("enum").StrEnum)
    assert issubclass(AttestationBasis, __import__("enum").StrEnum)
    with pytest.raises(ValueError):
        AttestationRecord.model_validate(
            _record(1, extra={"attestation": "looks_legit"})
        )


def test_memory_cap_fails_when_keeps_exceed_one_third(tmp_path: Path) -> None:
    """Negative: >1/3 memory-only keeps fail closed (not a warning)."""
    draft = load_manifest(str(_draft(tmp_path, [1, 2, 3])))
    records = [
        _record(1, basis="memory", attestation="own_capture"),
        _record(2, basis="memory", attestation="own_repost"),
        _record(3, basis="pixels", attestation="own_capture"),
    ]
    path = _jsonl(tmp_path, records)
    loaded = load_attestation_jsonl(path)
    with pytest.raises(MemoryRateCapError, match="one-third") as exc_info:
        validate_attestation_pass(loaded, draft)
    assert exc_info.value.memory_keeps == 2
    assert exc_info.value.adjudicated == 3
    assert isinstance(exc_info.value, RemediationError)


def test_memory_cap_passes_at_or_below_one_third(tmp_path: Path) -> None:
    """Positive: ≤1/3 memory-only keeps are accepted."""
    draft = load_manifest(str(_draft(tmp_path, [1, 2, 3])))
    records = [
        _record(1, basis="memory", attestation="own_capture"),
        _record(2, basis="pixels", attestation="own_capture"),
        _record(3, basis="metadata", attestation="own_repost"),
    ]
    attested = validate_attestation_pass(load_attestation_jsonl(_jsonl(tmp_path, records)), draft)
    assert attested.memory_keeps == 1
    assert attested.adjudicated == 3


def test_memory_drop_attestations_do_not_count_toward_cap(tmp_path: Path) -> None:
    """Memory + unknown/third_party is a drop, not a memory-only keep."""
    draft = load_manifest(str(_draft(tmp_path, [1, 2, 3])))
    records = [
        _record(1, basis="memory", attestation="unknown"),
        _record(2, basis="memory", attestation="third_party"),
        _record(3, basis="memory", attestation="own_capture"),
    ]
    attested = validate_attestation_pass(load_attestation_jsonl(_jsonl(tmp_path, records)), draft)
    assert attested.memory_keeps == 1


# --- D4 emitter (synthetic fixture end-to-end) --------------------------------


def test_emitter_end_to_end_on_synthetic_fixture(tmp_path: Path) -> None:
    """Fixed dispositions apply; unknown drops; retags land; output loads."""
    draft = load_manifest(str(SYNTHETIC_DRAFT))
    out = tmp_path / "golden150-remediated-fixture.json"
    sidecar = tmp_path / "golden150-remediated-fixture.gate_drops.json"
    result = emit_remediated_manifest(
        draft,
        SYNTHETIC_ATTESTATION,
        output_path=out,
        drop_sidecar_path=sidecar,
    )

    dropped_ids = {d.media_id for d in result.dropped}
    survivor_ids = {e.media_id for e in result.manifest.entries}

    # Every fixed-disposition id is exercised (kills `in FIXED_*` → `== one id`
    # and delete-retag-branch mutants).
    assert FIXED_SCRAPE_DROP_IDS <= dropped_ids
    assert all(
        d.rationale == FIXED_SCRAPE_DROP_RATIONALE
        for d in result.dropped
        if d.media_id in FIXED_SCRAPE_DROP_IDS
    )
    assert FIXED_CELEB_DROP_IDS <= dropped_ids
    assert all(
        d.rationale == FIXED_CELEB_DROP_RATIONALE
        for d in result.dropped
        if d.media_id in FIXED_CELEB_DROP_IDS
    )
    assert 102 in dropped_ids
    assert any(
        d.media_id == 102 and d.rationale == ATTESTATION_UNKNOWN_RATIONALE
        for d in result.dropped
    )
    assert 103 in dropped_ids
    assert any(
        d.media_id == 103 and d.rationale == ATTESTATION_THIRD_PARTY_RATIONALE
        for d in result.dropped
    )

    assert FIXED_RETAG_IDS <= survivor_ids
    for media_id in FIXED_RETAG_IDS:
        retagged = next(e for e in result.manifest.entries if e.media_id == media_id)
        assert retagged.provenance.source is ProvenanceSource.OPERATOR
        assert retagged.provenance.license is LicenseTag.MOCK_ENTITY
        assert retagged.provenance.note == FIXED_RETAG_RATIONALE

    ada = next(e for e in result.manifest.entries if e.media_id == 100)
    assert ada.provenance.source is ProvenanceSource.OPERATOR
    assert ada.provenance.license is LicenseTag.CONSENTED
    bea = next(e for e in result.manifest.entries if e.media_id == 101)
    assert bea.provenance.source is ProvenanceSource.OPERATOR
    assert bea.provenance.license is LicenseTag.CONSENTED

    # Output loads under the (now provenance-required) loader.
    reloaded = load_manifest(str(out))
    assert {e.media_id for e in reloaded.entries} == survivor_ids
    assert all(e.provenance is not None for e in reloaded.entries)

    # Draft file was not modified.
    assert SYNTHETIC_DRAFT.read_bytes()  # still there
    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_doc["scope"] == "fr_gate"
    assert {row["media_id"] for row in sidecar_doc["dropped"]} == dropped_ids


def test_retag_id_unknown_attestation_is_dropped(tmp_path: Path) -> None:
    """PROV-01: unknown on a FIXED_RETAG_ID drops; sidecar records the verdict."""
    draft = load_manifest(str(_draft(tmp_path, [603, 100])))
    records = [
        AttestationRecord.model_validate(_record(603, attestation="unknown")),
        AttestationRecord.model_validate(_record(100, attestation="own_capture")),
    ]
    sidecar = tmp_path / "gate_drops.json"
    result = emit_remediated_manifest(draft, records, drop_sidecar_path=sidecar)
    survivor_ids = {e.media_id for e in result.manifest.entries}
    assert 603 not in survivor_ids
    assert 100 in survivor_ids
    drop = next(d for d in result.dropped if d.media_id == 603)
    assert drop.rationale == ATTESTATION_UNKNOWN_RATIONALE
    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(
        row["media_id"] == 603 and row["rationale"] == ATTESTATION_UNKNOWN_RATIONALE
        for row in sidecar_doc["dropped"]
    )


def test_retag_id_third_party_attestation_is_dropped(tmp_path: Path) -> None:
    """PROV-01: third_party on a FIXED_RETAG_ID drops; sidecar records the verdict.

    Kills a mutant that re-inserts a retag keep between the UNKNOWN and
    THIRD_PARTY branches (FIR-11-SL1-R2-02).
    """
    draft = load_manifest(str(_draft(tmp_path, [633, 100])))
    records = [
        AttestationRecord.model_validate(_record(633, attestation="third_party")),
        AttestationRecord.model_validate(_record(100, attestation="own_capture")),
    ]
    sidecar = tmp_path / "gate_drops.json"
    result = emit_remediated_manifest(draft, records, drop_sidecar_path=sidecar)
    survivor_ids = {e.media_id for e in result.manifest.entries}
    assert 633 not in survivor_ids
    assert 100 in survivor_ids
    drop = next(d for d in result.dropped if d.media_id == 633)
    assert drop.rationale == ATTESTATION_THIRD_PARTY_RATIONALE
    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(
        row["media_id"] == 633 and row["rationale"] == ATTESTATION_THIRD_PARTY_RATIONALE
        for row in sidecar_doc["dropped"]
    )


def test_emitter_rejects_pass_bound_to_mutated_draft_sha(tmp_path: Path) -> None:
    """A pass validated against draft A must not emit draft B with a mutated sha256."""
    path_a = _draft(tmp_path, [1])
    draft_a = load_manifest(str(path_a))
    attested = validate_attestation_pass(
        [AttestationRecord.model_validate(_record(1))], draft_a
    )
    doc = json.loads(path_a.read_text(encoding="utf-8"))
    doc["entries"][0]["sha256"] = "b" * 64
    path_b = tmp_path / "draft_b.json"
    path_b.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    draft_b = load_manifest(str(path_b))
    with pytest.raises(RemediationError, match="sha256"):
        emit_remediated_manifest(draft_b, attested)


def test_zwsp_attested_by_rejected(tmp_path: Path) -> None:
    """attested_by that is empty after format/space strip is rejected."""
    path = _jsonl(tmp_path, [_record(1, attested_by="\u200b")])
    with pytest.raises(RemediationError, match="attested_by"):
        load_attestation_jsonl(path)


def test_empty_attestation_jsonl_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(RemediationError, match="empty"):
        load_attestation_jsonl(path)
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(RemediationError, match="empty"):
        load_attestation_jsonl(path)


def test_missing_attested_at_rejected(tmp_path: Path) -> None:
    payload = _record(1)
    del payload["attested_at"]
    path = _jsonl(tmp_path, [payload])
    with pytest.raises(RemediationError, match="attested_at"):
        load_attestation_jsonl(path)


def test_fixed_disposition_constants_match_plan() -> None:
    """The plan table is encoded as constants, not prose."""
    assert FIXED_SCRAPE_DROP_IDS == frozenset({375, 438, 484})
    assert FIXED_RETAG_IDS == frozenset({603, 633, 648})
    assert FIXED_CELEB_DROP_IDS == frozenset({11, 13, 14, 15, 21, 22, 23})
    assert "consent not attestable" in FIXED_SCRAPE_DROP_RATIONALE
    assert "operator/mock_entity" in FIXED_RETAG_RATIONALE
    assert "filename-derived identity" in FIXED_CELEB_DROP_RATIONALE


def test_emitter_does_not_run_against_real_golden150() -> None:
    """Guard: the real draft is frozen v2; the v3 gate loader must not accept it."""
    real = (
        _repo_root() / "benchmarks" / "manifests" / "golden150-draft-20260723.json"
    )
    with pytest.raises(ManifestError, match="manifest_version"):
        load_manifest(str(real))
    # No real attestation artifact was authored.
    manifests = _repo_root() / "benchmarks" / "manifests"
    assert list(manifests.glob("golden150-attestation-*.jsonl")) == []
    assert list(manifests.glob("golden150-remediated-*.json")) == []


# --- D5 v3r ------------------------------------------------------------------


def test_v3_source_sha256_unchanged() -> None:
    """Measurement source stays byte-identical (edit-then-freeze)."""
    path = _repo_root() / "benchmarks" / "manifests" / "corpus-manifest-v3.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == V3_SOURCE_SHA256


def test_emit_corpus_v3r_on_min_fixture(tmp_path: Path) -> None:
    """Identity claims drop; boxes stay; catalog stays consistent."""
    source_bytes = V3_MIN.read_bytes()
    out = tmp_path / "corpus-manifest-v3r-fixture.json"
    result = emit_corpus_v3r(
        V3_MIN,
        out,
        expected_source_sha256=None,
        require_all_drop_ids=False,
    )
    # Source fixture bytes unchanged.
    assert V3_MIN.read_bytes() == source_bytes

    doc = json.loads(out.read_text(encoding="utf-8"))
    by_id = {e["media_id"]: e for e in doc["entries"]}

    assert by_id[11]["primary_identity"] is None
    assert by_id[11]["named_identities"] == []
    assert by_id[11]["named_boxes"] == []
    assert by_id[11]["detected_boxes"] == [{"bbox": [1, 2, 3, 4]}]
    assert "identity_from_filename_only" not in by_id[11]["flags"]

    assert by_id[15]["primary_identity"] is None
    assert by_id[15]["named_identities"] == []
    assert by_id[15]["detected_boxes"] == [{"bbox": [5, 6, 7, 8]}]

    # Untouched keeper.
    assert by_id[99]["primary_identity"] == "Kept Person"
    assert by_id[99]["named_identities"] == ["Kept Person"]
    assert by_id[99]["named_boxes"] == [{"name": "Kept Person", "bbox": [0, 0, 1, 1]}]

    names = {i["name"]: i for i in doc["identities"]}
    assert "Anne Hathaway" not in names  # sole appearance dropped
    assert names["Audrey Hepburn"]["appearance_count"] == 1
    assert names["Audrey Hepburn"]["primary_of"] == ["celebs/audrey_hepburn_16.jpg"]
    assert names["Kept Person"]["appearance_count"] == 1
    assert doc["counts"]["identities"] == 2
    assert doc["counts"]["unlabeled"] == 2  # 11 and 15
    assert doc["counts"]["flags"]["identity_from_filename_only"] == 0
    assert result.identities_before == 3
    assert result.identities_after == 2
    assert {d.media_id for d in result.drops} == {11, 15}
    assert all(d.reason == V3_IDENTITY_CLAIM_DROP_RATIONALE for d in result.drops)
    # Trailing newline + reproducible hash.
    rendered = out.read_bytes()
    assert rendered.endswith(b"\n")
    assert result.sha256 == hashlib.sha256(rendered).hexdigest()


def test_v3_identity_claim_drop_ids_match_plan() -> None:
    assert V3_IDENTITY_CLAIM_DROP_IDS == frozenset({11, 12, 13, 14, 15, 375, 438, 484})


def test_committed_v3r_clears_eight_claims_and_preserves_boxes() -> None:
    """The frozen v3r artifact matches the emit contract on the real 8 ids."""
    root = _repo_root()
    v3_path = root / "benchmarks" / "manifests" / "corpus-manifest-v3.json"
    matches = sorted((root / "benchmarks" / "manifests").glob("corpus-manifest-v3r-*.json"))
    if not matches:
        pytest.skip("v3r artifact not yet emitted")
    v3 = json.loads(v3_path.read_text(encoding="utf-8"))
    v3r = json.loads(matches[-1].read_text(encoding="utf-8"))
    v3_by_id = {e["media_id"]: e for e in v3["entries"]}
    v3r_by_id = {e["media_id"]: e for e in v3r["entries"]}
    assert len(v3r["entries"]) == len(v3["entries"]) == 646
    for media_id in sorted(V3_IDENTITY_CLAIM_DROP_IDS):
        before = v3_by_id[media_id]
        after = v3r_by_id[media_id]
        assert after.get("named_identities") in ([], None)
        assert after.get("primary_identity") is None
        assert after.get("named_boxes") == before.get("named_boxes")
        assert after.get("detected_boxes") == before.get("detected_boxes")
        assert "identity_from_filename_only" not in (after.get("flags") or [])
