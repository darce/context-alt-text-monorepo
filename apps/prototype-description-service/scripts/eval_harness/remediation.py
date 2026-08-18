"""FIR-11 Slice 1 remediation: attestation schema, validator, and emitters.

Module name is implementer-chosen. The plan names the artifacts
(``golden150-attestation-<YYYYMMDD>.jsonl``,
``golden150-remediated-<YYYYMMDD>.json``,
``corpus-manifest-v3r-<YYYYMMDD>.json``) and the record schema, but no
emitter symbol. This module lives in ``scripts/eval_harness`` next to the
loader it feeds.

STOP lines (binding):
    * Do not author a real ``golden150-attestation-*.jsonl``. The operator
      fills attestations later. Tests use synthetic fixtures only.
    * Do not run the golden150 emitter against the real draft — no real
      attestation input exists. Fabricating a provenance attestation is the
      defect this task exists to fix (FIR-11-PROV-01).
    * The v3r emitter *is* fully executable: it drops eight unsubstantiated
      identity claims by media_id constant, with no operator testimony.

sr-006: input validation raises typed errors, never ``assert``.
sr-007: closed vocabularies are StrEnum, never magic strings.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from scripts.eval_harness.manifest import (
    GoldenEntry,
    GoldenManifest,
    LicenseTag,
    Provenance,
    ProvenanceSource,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Closed vocabularies (sr-007)
# ---------------------------------------------------------------------------


class AttestationKind(StrEnum):
    """Per-entry attestation of how the image entered the operator's hands."""

    OWN_CAPTURE = "own_capture"
    OWN_REPOST = "own_repost"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class AttestationBasis(StrEnum):
    """What the attester looked at. Memory-only keeps are rate-capped."""

    PIXELS = "pixels"
    METADATA = "metadata"
    MEMORY = "memory"


# Attestations that drop the entry from the FR-gate pool (typed dataflow).
_DROP_ATTESTATIONS: frozenset[AttestationKind] = frozenset(
    {AttestationKind.UNKNOWN, AttestationKind.THIRD_PARTY}
)


# ---------------------------------------------------------------------------
# Plan-decided fixed dispositions (mechanical; rationale strings from the plan)
# ---------------------------------------------------------------------------


FIXED_SCRAPE_DROP_IDS: frozenset[int] = frozenset({375, 438, 484})
FIXED_SCRAPE_DROP_RATIONALE = (
    "Instagram handle + CDN filename; consent not attestable "
    "(FIR-11 Slice 1 disposition table)"
)

FIXED_RETAG_IDS: frozenset[int] = frozenset({603, 633, 648})
FIXED_RETAG_RATIONALE = (
    "camera-roll capture; plan disposition table assigns operator/mock_entity "
    "(FIR-11 Slice 1)"
)

FIXED_CELEB_DROP_IDS: frozenset[int] = frozenset({11, 13, 14, 15, 21, 22, 23})
FIXED_CELEB_DROP_RATIONALE = (
    "celeb/fixture; filename-derived identity is not attested labeling "
    "(FIR-11 Slice 1)"
)

ATTESTATION_UNKNOWN_RATIONALE = (
    "attestation=unknown; fail-closed drop (FIR-11 Slice 1)"
)
ATTESTATION_THIRD_PARTY_RATIONALE = (
    "attestation=third_party; mock_entity is never valid for a real "
    "third-party subject (FIR-11 Slice 1)"
)

# Survivors (own_capture / own_repost) get a truthful operator/consented pair.
# mock_entity is never derived for a third-party subject (those drop). The
# three camera-roll rows override to operator/mock_entity via FIXED_RETAG_*.
_SURVIVOR_PROVENANCE: dict[AttestationKind, tuple[ProvenanceSource, LicenseTag]] = {
    AttestationKind.OWN_CAPTURE: (ProvenanceSource.OPERATOR, LicenseTag.CONSENTED),
    AttestationKind.OWN_REPOST: (ProvenanceSource.OPERATOR, LicenseTag.CONSENTED),
}

V3_IDENTITY_CLAIM_DROP_IDS: frozenset[int] = frozenset(
    {11, 12, 13, 14, 15, 375, 438, 484}
)
V3_IDENTITY_CLAIM_DROP_RATIONALE = (
    "named identity with zero named boxes; identity claim unsubstantiated "
    "(FIR-11 Slice 1)"
)

V3_SOURCE_SHA256 = "d35b6670443f87bc25c2e72912182b58b6c8a45347209b79c0e1b0c1cbee5d44"


# ---------------------------------------------------------------------------
# Typed errors (sr-006)
# ---------------------------------------------------------------------------


class RemediationError(Exception):
    """Attestation or remediation input failed validation."""


class MemoryRateCapError(RemediationError):
    """Memory-only keeps exceed one-third of adjudicated entries.

    The pass must pause for a recorded disposition + review sign-off before
    any remediated manifest is emitted (R4P-21).
    """

    def __init__(self, memory_keeps: int, adjudicated: int) -> None:
        self.memory_keeps = memory_keeps
        self.adjudicated = adjudicated
        super().__init__(
            f"memory-only keeps {memory_keeps}/{adjudicated} exceed the "
            f"one-third cap; pause for recorded disposition + review "
            f"sign-off before emitting a manifest"
        )


# ---------------------------------------------------------------------------
# Attestation record (fields exactly as the plan Files table)
# ---------------------------------------------------------------------------


class AttestationRecord(BaseModel):
    """One ``golden150-attestation-<YYYYMMDD>.jsonl`` line.

    Fields exactly: media_id, sha256, attestation, basis, attested_by, note,
    attested_at. Unknown fields are rejected (``extra='forbid'``).
    ``attested_by`` is required and non-empty — testimony needs a named
    attester (R4P-20).
    """

    model_config = ConfigDict(extra="forbid")

    media_id: int = Field(ge=1)
    sha256: str
    attestation: AttestationKind
    basis: AttestationBasis
    attested_by: str
    note: str = ""
    attested_at: str

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return value

    @field_validator("attested_by")
    @classmethod
    def _attested_by_named(cls, value: str) -> str:
        stripped = value.strip()
        # Reject empty-after-format/space (ZWSP, NBSP, etc.): strip() alone
        # keeps Cf characters, so also require a word character.
        if not stripped or not re.search(r"\w", stripped, flags=re.UNICODE):
            raise ValueError("attested_by is required (testimony needs a named attester)")
        return stripped

    @field_validator("attested_at")
    @classmethod
    def _attested_at_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("attested_at is required")
        return value


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttestationPass:
    """A complete, cap-passing attestation file joined to a draft manifest."""

    records: tuple[AttestationRecord, ...]
    by_media_id: dict[int, AttestationRecord]
    memory_keeps: int
    adjudicated: int


def _wrap_record_error(line_no: int, exc: Exception) -> RemediationError:
    return RemediationError(f"attestation jsonl line {line_no}: {exc}")


def load_attestation_jsonl(path: Path) -> list[AttestationRecord]:
    """Parse a jsonl file into typed records. Rejects unknown fields / schema."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RemediationError(f"attestation jsonl unreadable: {exc}") from exc

    records: list[AttestationRecord] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _wrap_record_error(line_no, exc) from exc
        if not isinstance(payload, dict):
            raise RemediationError(
                f"attestation jsonl line {line_no}: record must be a JSON object"
            )
        try:
            records.append(AttestationRecord.model_validate(payload))
        except ValidationError as exc:
            raise _wrap_record_error(line_no, exc) from exc
    if not records:
        raise RemediationError("attestation jsonl is empty")
    return records


def _memory_only_keep(record: AttestationRecord) -> bool:
    """True when the keep rests on memory alone (not a drop attestation)."""
    return (
        record.basis is AttestationBasis.MEMORY
        and record.attestation not in _DROP_ATTESTATIONS
    )


def validate_attestation_pass(
    records: list[AttestationRecord],
    manifest: GoldenManifest,
) -> AttestationPass:
    """Join records to the draft manifest. Fail-closed on every listed hole.

    Rejects: duplicate media_ids, media_ids absent from the manifest, sha256
    mismatch, incomplete coverage (not exactly one record per manifest entry).
    Fails closed when memory-only keeps exceed one-third of adjudicated
    entries (R4P-21).
    """
    by_id: dict[int, AttestationRecord] = {}
    duplicates: list[int] = []
    for record in records:
        if record.media_id in by_id:
            duplicates.append(record.media_id)
            continue
        by_id[record.media_id] = record
    if duplicates:
        raise RemediationError(
            f"duplicate attestation media_id(s): {sorted(set(duplicates))}"
        )

    manifest_by_id = {entry.media_id: entry for entry in manifest.entries}

    absent = sorted(media_id for media_id in by_id if media_id not in manifest_by_id)
    if absent:
        raise RemediationError(
            f"attestation media_id(s) absent from manifest: {absent}"
        )

    sha_mismatches: list[str] = []
    for media_id, record in by_id.items():
        entry = manifest_by_id[media_id]
        if record.sha256 != entry.sha256:
            sha_mismatches.append(
                f"media_id={media_id} record={record.sha256} manifest={entry.sha256}"
            )
    if sha_mismatches:
        raise RemediationError(
            "attestation sha256 does not match manifest entry: "
            + "; ".join(sha_mismatches)
        )

    missing = sorted(media_id for media_id in manifest_by_id if media_id not in by_id)
    if missing:
        raise RemediationError(
            f"incomplete attestation pass; missing record(s) for media_id(s): {missing}"
        )

    adjudicated = len(manifest.entries)
    memory_keeps = sum(1 for record in records if _memory_only_keep(record))
    # Strict exceed: memory_keeps > adjudicated/3  <=>  3*keeps > adjudicated.
    if memory_keeps * 3 > adjudicated:
        raise MemoryRateCapError(memory_keeps, adjudicated)

    return AttestationPass(
        records=tuple(records),
        by_media_id=by_id,
        memory_keeps=memory_keeps,
        adjudicated=adjudicated,
    )


def load_and_validate_attestation(
    jsonl_path: Path,
    manifest: GoldenManifest,
) -> AttestationPass:
    """Load a jsonl file and validate it as a complete attestation pass."""
    return validate_attestation_pass(load_attestation_jsonl(jsonl_path), manifest)


# ---------------------------------------------------------------------------
# Golden150 remediated-manifest emitter (scaffold; fixtures only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDrop:
    """One FR-gate drop. The image retains description-eval value."""

    media_id: int
    path: str
    rationale: str


@dataclass
class RemediationResult:
    """Emitter output: surviving GoldenManifest + FR-gate drop sidecar."""

    manifest: GoldenManifest
    dropped: list[GateDrop] = field(default_factory=list)

    def drop_sidecar(self) -> dict[str, Any]:
        """Sidecar section: dropped media_ids + rationale. Draft file untouched."""
        return {
            "scope": "fr_gate",
            "note": (
                "Drops are FR-gate-scoped, not global. Dropped entries keep "
                "description-eval value and were not deleted from the draft file."
            ),
            "dropped": [
                {
                    "media_id": drop.media_id,
                    "path": drop.path,
                    "rationale": drop.rationale,
                }
                for drop in self.dropped
            ],
        }


def _drop(entry: GoldenEntry, rationale: str) -> GateDrop:
    return GateDrop(media_id=entry.media_id, path=entry.path, rationale=rationale)


def _survivor_provenance(
    entry: GoldenEntry,
    record: AttestationRecord,
) -> Provenance:
    if entry.media_id in FIXED_RETAG_IDS:
        return Provenance(
            source=ProvenanceSource.OPERATOR,
            license=LicenseTag.MOCK_ENTITY,
            note=FIXED_RETAG_RATIONALE,
        )
    mapping = _SURVIVOR_PROVENANCE.get(record.attestation)
    if mapping is None:
        raise RemediationError(
            f"no survivor provenance mapping for attestation={record.attestation} "
            f"on media_id={entry.media_id}"
        )
    source, license_tag = mapping
    note = record.note or (
        f"attestation={record.attestation.value} basis={record.basis.value} "
        f"attested_by={record.attested_by}"
    )
    return Provenance(source=source, license=license_tag, note=note)


def emit_remediated_manifest(
    draft: GoldenManifest,
    attestation: AttestationPass | list[AttestationRecord] | Path,
    *,
    output_path: Path | None = None,
    drop_sidecar_path: Path | None = None,
) -> RemediationResult:
    """Build ``golden150-remediated-<YYYYMMDD>.json`` from draft + attestation.

    The draft file is never written. Dropped entries are recorded in the
    returned sidecar (and optionally ``drop_sidecar_path``), not deleted
    from the source. Output, if written, is a GoldenManifest that loads
    under the provenance-required loader.
    """
    if isinstance(attestation, Path):
        attested = load_and_validate_attestation(attestation, draft)
    elif isinstance(attestation, list):
        attested = validate_attestation_pass(attestation, draft)
    elif isinstance(attestation, AttestationPass):
        # Never trust a pre-built pass: re-bind against the supplied draft
        # (sha256 per media_id, completeness, memory cap).
        attested = validate_attestation_pass(list(attestation.records), draft)
    else:
        raise RemediationError(
            f"attestation must be a Path, record list, or AttestationPass; "
            f"got {type(attestation).__name__}"
        )

    survivors: list[GoldenEntry] = []
    dropped: list[GateDrop] = []
    for entry in draft.entries:
        record = attested.by_media_id[entry.media_id]
        if entry.media_id in FIXED_SCRAPE_DROP_IDS:
            dropped.append(_drop(entry, FIXED_SCRAPE_DROP_RATIONALE))
            continue
        if entry.media_id in FIXED_CELEB_DROP_IDS:
            dropped.append(_drop(entry, FIXED_CELEB_DROP_RATIONALE))
            continue
        # Attestation drop verdicts always win, including FIXED_RETAG_IDS.
        # The plan table only supplies survivor source/license after a keep.
        if record.attestation is AttestationKind.UNKNOWN:
            dropped.append(_drop(entry, ATTESTATION_UNKNOWN_RATIONALE))
            continue
        if record.attestation is AttestationKind.THIRD_PARTY:
            dropped.append(_drop(entry, ATTESTATION_THIRD_PARTY_RATIONALE))
            continue
        survivors.append(
            entry.model_copy(update={"provenance": _survivor_provenance(entry, record)})
        )

    if not survivors:
        raise RemediationError(
            "remediated manifest would have no entries; an empty corpus cannot be scored"
        )

    result = RemediationResult(
        manifest=GoldenManifest(
            manifest_version=draft.manifest_version,
            annotation_mode=draft.annotation_mode,
            roster=list(draft.roster),
            entries=survivors,
            roster_cohorts=dict(draft.roster_cohorts),
        ),
        dropped=dropped,
    )
    if output_path is not None:
        write_golden_manifest(result.manifest, output_path)
    if drop_sidecar_path is not None:
        drop_sidecar_path.write_text(
            json.dumps(result.drop_sidecar(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def write_golden_manifest(manifest: GoldenManifest, path: Path) -> None:
    """Deterministic GoldenManifest JSON (stable field order, trailing newline)."""
    payload = manifest.model_dump(mode="json", exclude_none=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# corpus-manifest-v3r emitter (fully executable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityClaimDrop:
    media_id: int
    path: str
    dropped_identities: tuple[str, ...]
    reason: str


@dataclass
class V3rEmitResult:
    output_path: Path
    sha256: str
    source_sha256: str
    drops: list[IdentityClaimDrop]
    identities_before: int
    identities_after: int
    unlabeled_before: int
    unlabeled_after: int


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def emit_corpus_v3r(
    source_path: Path,
    output_path: Path,
    *,
    expected_source_sha256: str | None = V3_SOURCE_SHA256,
    require_all_drop_ids: bool = True,
) -> V3rEmitResult:
    """Emit v3r = v3 with the 8 unsubstantiated identity claims removed.

    Image entries stay. Boxes (named and detected) are not touched. Identity
    catalog rows and the ``counts`` block are adjusted so the artifact stays
    internally consistent. The source file is never written.
    """
    source_bytes = source_path.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    if expected_source_sha256 and source_sha256 != expected_source_sha256:
        raise RemediationError(
            f"refusing to emit v3r: source sha256 {source_sha256} != "
            f"pinned measurement-source hash {expected_source_sha256}"
        )

    doc = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(doc, dict) or "entries" not in doc:
        raise RemediationError("corpus-manifest-v3 is not a JSON object with entries")

    identities_before = len(doc.get("identities") or [])
    unlabeled_before = int((doc.get("counts") or {}).get("unlabeled") or 0)

    drops: list[IdentityClaimDrop] = []
    for entry in doc["entries"]:
        if not isinstance(entry, dict):
            continue
        media_id = entry.get("media_id")
        if media_id not in V3_IDENTITY_CLAIM_DROP_IDS:
            continue
        path = str(entry.get("path") or "")
        named = tuple(entry.get("named_identities") or ())
        # Drop the identity claim only. Do not delete the image; do not touch boxes.
        entry["primary_identity"] = None
        entry["named_identities"] = []
        flags = [f for f in (entry.get("flags") or []) if f != "identity_from_filename_only"]
        entry["flags"] = flags
        drops.append(
            IdentityClaimDrop(
                media_id=int(media_id),
                path=path,
                dropped_identities=named,
                reason=V3_IDENTITY_CLAIM_DROP_RATIONALE,
            )
        )

    missing_ids = V3_IDENTITY_CLAIM_DROP_IDS - {d.media_id for d in drops}
    if require_all_drop_ids and missing_ids:
        raise RemediationError(
            f"v3r emit: expected identity-claim rows missing from source: "
            f"{sorted(missing_ids)}"
        )

    dropped_paths = {d.path for d in drops}
    remaining_identities: list[dict[str, Any]] = []
    for ident in doc.get("identities") or []:
        if not isinstance(ident, dict):
            continue
        primary_of = [p for p in (ident.get("primary_of") or []) if p not in dropped_paths]
        appears_in = [p for p in (ident.get("appears_in") or []) if p not in dropped_paths]
        ident["primary_of"] = primary_of
        ident["appears_in"] = appears_in
        ident["primary_count"] = len(primary_of)
        ident["appearance_count"] = len(appears_in)
        if ident["appearance_count"] > 0:
            remaining_identities.append(ident)
    doc["identities"] = remaining_identities

    counts = doc.setdefault("counts", {})
    flags = counts.setdefault("flags", {})
    counts["identities"] = len(remaining_identities)
    unlabeled_after = sum(
        1
        for entry in doc["entries"]
        if isinstance(entry, dict) and not entry.get("named_identities")
    )
    counts["unlabeled"] = unlabeled_after
    flags["identity_from_filename_only"] = sum(
        1
        for entry in doc["entries"]
        if isinstance(entry, dict)
        and "identity_from_filename_only" in (entry.get("flags") or [])
    )
    # secondary-only is identities that still appear but are never primary
    counts["identities_secondary_only"] = sum(
        1
        for ident in remaining_identities
        if ident.get("primary_count") == 0 and ident.get("appearance_count", 0) > 0
    )

    # Deterministic serialization: preserve key order (json.loads insertion
    # order), 1-space indent matching the v3 source, trailing newline (brief).
    rendered = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return V3rEmitResult(
        output_path=output_path,
        sha256=_sha256_bytes(rendered.encode("utf-8")),
        source_sha256=source_sha256,
        drops=drops,
        identities_before=identities_before,
        identities_after=len(remaining_identities),
        unlabeled_before=unlabeled_before,
        unlabeled_after=unlabeled_after,
    )


def default_v3r_output_name(day: date | None = None) -> str:
    stamp = (day or date.today()).strftime("%Y%m%d")
    return f"corpus-manifest-v3r-{stamp}.json"


def _repo_root_from_here() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "manifests" / "corpus-manifest-v3.json"
        if candidate.is_file():
            return parent
    raise RemediationError("cannot locate repo root (corpus-manifest-v3.json missing)")


def main(argv: list[str] | None = None) -> int:
    """Minimal CLI. Only ``emit-v3r`` is a real-data command.

    There is no ``emit-golden150`` real-data path — that would require a real
    attestation file this slice must not author.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="scripts.eval_harness.remediation")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v3r = sub.add_parser("emit-v3r", help="emit corpus-manifest-v3r-<YYYYMMDD>.json")
    v3r.add_argument(
        "--source",
        type=Path,
        default=None,
        help="path to corpus-manifest-v3.json (default: repo benchmarks copy)",
    )
    v3r.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output path (default: benchmarks/manifests/corpus-manifest-v3r-<today>.json)",
    )
    args = parser.parse_args(argv)

    if args.cmd == "emit-v3r":
        root = _repo_root_from_here()
        source = args.source or (root / "benchmarks" / "manifests" / "corpus-manifest-v3.json")
        output = args.output or (
            root / "benchmarks" / "manifests" / default_v3r_output_name()
        )
        result = emit_corpus_v3r(source, output)
        sys.stdout.write(
            f"emitted {result.output_path}\n"
            f"source_sha256 {result.source_sha256}\n"
            f"v3r_sha256 {result.sha256}\n"
            f"identity_claims_dropped {len(result.drops)}\n"
            f"identities {result.identities_before}->{result.identities_after}\n"
            f"unlabeled {result.unlabeled_before}->{result.unlabeled_after}\n"
        )
        for drop in result.drops:
            names = ",".join(drop.dropped_identities) or "(none)"
            sys.stdout.write(
                f"  drop media_id={drop.media_id} path={drop.path} "
                f"names={names} reason={drop.reason}\n"
            )
        return 0
    raise RemediationError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
