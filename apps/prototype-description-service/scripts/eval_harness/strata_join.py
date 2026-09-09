"""Join run records to the frozen FIR-12 selection-manifest strata.

The selection manifest (schema ``bakeoff-selection/1``) is the authority for
stratum membership, ``strata_counts``, ``declared_empty_cells``, and identity
ground truth (``present_identities``). Run records supply coverage; this
module does not recompute those fields (rg-015).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SELECTION_SCHEMA = "bakeoff-selection/1"

_REQUIRED_TOP = ("schema", "entries", "strata_counts", "declared_empty_cells")
_REQUIRED_ENTRY = ("sha256", "media_id", "stratum")
_SUBJECT_LIST_FIELDS = ("subjects", "present_identities", "identities")
_SUBJECT_SCALAR_FIELDS = ("subject", "true_name")


class StratumJoinError(ValueError):
    """A selection-manifest load or record join failed."""


@dataclass(frozen=True)
class StratumIndex:
    """sha256 + media_id -> stratum, plus manifest metadata passed through."""

    by_sha256: Mapping[str, str]
    by_media_id: Mapping[int, str]
    subjects_by_sha256: Mapping[str, tuple[str, ...]]
    subjects_by_media_id: Mapping[int, tuple[str, ...]]
    strata_counts: Mapping[str, Any]
    declared_empty_cells: Sequence[str]
    declared_images: Mapping[str, int]
    sha256_by_media_id: Mapping[int, str]


@dataclass(frozen=True)
class StratumBucket:
    stratum: str
    n_images: int
    unique_subjects: int
    manifest_images: int


@dataclass(frozen=True)
class _ResolvedRecord:
    stratum: str
    image_key: str
    sha256: str
    media_id: int | None


@dataclass(frozen=True)
class StratumReport:
    """Per-stratum image and unique-subject counts for one joined record set."""

    buckets: Mapping[str, StratumBucket]
    declared_empty_cells: Sequence[str]
    strata_order: tuple[str, ...]

    def coverage_gaps(self) -> list[dict[str, Any]]:
        """Strata whose joined image count is short of the declared denominator."""
        gaps: list[dict[str, Any]] = []
        for name in self.strata_order:
            bucket = self.buckets[name]
            if bucket.n_images < bucket.manifest_images:
                gaps.append(
                    {
                        "stratum": name,
                        "joined_images": bucket.n_images,
                        "declared_images": bucket.manifest_images,
                    }
                )
        return gaps

    def to_rows(self) -> list[dict[str, Any]]:
        """One row per declared stratum, then one row per declared-empty cell.

        Empty cells stay in the table with ``declared_empty=True`` so an
        untested-looking omission cannot hide them (MLDATA-09). Rows short of
        the manifest denominator are marked ``incomplete`` (MLDATA-07).
        """
        rows: list[dict[str, Any]] = []
        for name in self.strata_order:
            bucket = self.buckets[name]
            rows.append(
                {
                    "stratum": name,
                    "n_images": bucket.n_images,
                    "manifest_images": bucket.manifest_images,
                    "unique_subjects": bucket.unique_subjects,
                    "declared_empty": False,
                    "incomplete": bucket.n_images < bucket.manifest_images,
                }
            )
        for cell in self.declared_empty_cells:
            rows.append(
                {
                    "stratum": cell,
                    "n_images": 0,
                    "manifest_images": 0,
                    "unique_subjects": 0,
                    "declared_empty": True,
                    "incomplete": False,
                }
            )
        return rows


def load_stratum_index(path: str | Path) -> StratumIndex:
    """Load the selection manifest and index every entry by sha256 and media_id."""
    payload = _read_selection_payload(path)
    declared_images = _declared_images_map(payload["strata_counts"])
    (
        by_sha256,
        by_media_id,
        sha256_by_media_id,
        subjects_by_sha256,
        subjects_by_media_id,
    ) = _index_entries(payload["entries"], declared_strata=declared_images)
    empty = payload["declared_empty_cells"]
    if not isinstance(empty, list) or not all(isinstance(cell, str) for cell in empty):
        raise StratumJoinError(
            "selection manifest 'declared_empty_cells' must be a list of strings"
        )
    return StratumIndex(
        by_sha256=by_sha256,
        by_media_id=by_media_id,
        subjects_by_sha256=subjects_by_sha256,
        subjects_by_media_id=subjects_by_media_id,
        strata_counts=payload["strata_counts"],
        declared_empty_cells=empty,
        declared_images=declared_images,
        sha256_by_media_id=sha256_by_media_id,
    )


def join_by_stratum(
    records: Iterable[object],
    index: StratumIndex,
) -> StratumReport:
    """Bucket records by selection-manifest stratum.

    Each bucket reports ``n_images`` (distinct canonical sha256 keys;
    media_id-only records are resolved through the manifest so a still
    keyed once by sha256 and once by media_id counts as one image) and
    ``unique_subjects`` (distinct subject names from the manifest, falling
    back to the record only when the entry has no ``present_identities``).
    A record whose sha256 or media_id is absent from the index raises —
    silent drops are forbidden.
    """
    images: dict[str, set[str]] = defaultdict(set)
    subjects: dict[str, set[str]] = defaultdict(set)
    for record in records:
        resolved = _resolve_record(record, index)
        images[resolved.stratum].add(resolved.image_key)
        subjects[resolved.stratum].update(_subjects_for(record, resolved, index))
    order = tuple(index.strata_counts)
    extra = sorted(set(images) - set(order))
    if extra:
        raise StratumJoinError(f"joined strata {extra} are not in strata_counts")
    buckets: dict[str, StratumBucket] = {}
    for name in order:
        buckets[name] = _bucket(name, images, subjects, index)
    return StratumReport(
        buckets=buckets,
        declared_empty_cells=index.declared_empty_cells,
        strata_order=order,
    )


def _bucket(
    name: str,
    images: Mapping[str, set[str]],
    subjects: Mapping[str, set[str]],
    index: StratumIndex,
) -> StratumBucket:
    return StratumBucket(
        stratum=name,
        n_images=len(images.get(name, ())),
        unique_subjects=len(subjects.get(name, ())),
        manifest_images=index.declared_images[name],
    )


def _read_selection_payload(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise StratumJoinError(f"selection manifest not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StratumJoinError(f"selection manifest is not valid JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise StratumJoinError(f"selection manifest must be a JSON object: {source}")
    missing = [key for key in _REQUIRED_TOP if key not in payload]
    if missing:
        raise StratumJoinError(
            f"selection manifest missing required keys {missing}: {source}"
        )
    schema = payload["schema"]
    if schema != SELECTION_SCHEMA:
        raise StratumJoinError(
            f"unsupported selection schema {schema!r}; expected {SELECTION_SCHEMA!r}"
        )
    return payload


def _index_entries(
    entries: object,
    *,
    declared_strata: Mapping[str, Any],
) -> tuple[
    dict[str, str],
    dict[int, str],
    dict[int, str],
    dict[str, tuple[str, ...]],
    dict[int, tuple[str, ...]],
]:
    if not isinstance(entries, list):
        raise StratumJoinError("selection manifest 'entries' must be a list")
    by_sha256: dict[str, str] = {}
    by_media_id: dict[int, str] = {}
    sha256_by_media_id: dict[int, str] = {}
    subjects_by_sha256: dict[str, tuple[str, ...]] = {}
    subjects_by_media_id: dict[int, tuple[str, ...]] = {}
    for i, entry in enumerate(entries):
        sha256, media_id, stratum, identities = _parse_entry(entry, i)
        if stratum not in declared_strata:
            raise StratumJoinError(
                f"entries[{i}].stratum {stratum!r} is not in strata_counts"
            )
        _reject_stratum_conflict(by_sha256, sha256, stratum, kind="sha256")
        _reject_stratum_conflict(by_media_id, media_id, stratum, kind="media_id")
        prior_sha = sha256_by_media_id.get(media_id)
        if prior_sha is not None and prior_sha != sha256:
            raise StratumJoinError(
                f"media_id {media_id!r} maps to both {prior_sha!r} and {sha256!r}"
            )
        by_sha256[sha256] = stratum
        by_media_id[media_id] = stratum
        sha256_by_media_id[media_id] = sha256
        if identities is not None:
            subjects_by_sha256[sha256] = identities
            subjects_by_media_id[media_id] = identities
    return by_sha256, by_media_id, sha256_by_media_id, subjects_by_sha256, subjects_by_media_id


def _parse_entry(
    entry: object, index: int
) -> tuple[str, int, str, tuple[str, ...] | None]:
    if not isinstance(entry, dict):
        raise StratumJoinError(f"entries[{index}] must be an object")
    absent = [key for key in _REQUIRED_ENTRY if key not in entry]
    if absent:
        raise StratumJoinError(f"entries[{index}] missing required keys {absent}")
    sha256 = entry["sha256"]
    if not isinstance(sha256, str) or not sha256:
        raise StratumJoinError(f"entries[{index}].sha256 must be a non-empty string")
    media_id = _as_media_id(entry["media_id"], where=f"entries[{index}].media_id")
    stratum = entry["stratum"]
    if not isinstance(stratum, str) or not stratum:
        raise StratumJoinError(f"entries[{index}].stratum must be a non-empty string")
    identities = _entry_identities(entry, where=f"entries[{index}]")
    return sha256, media_id, stratum, identities


def _entry_identities(entry: Mapping[str, Any], *, where: str) -> tuple[str, ...] | None:
    if "present_identities" not in entry:
        return None
    value = entry["present_identities"]
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(
            _normalise_identity_item(item, where=where) for item in value
        )
    raise StratumJoinError(
        f"{where}.present_identities must be a list of strings, got {type(value).__name__}"
    )


def _normalise_identity_item(value: object, *, where: str) -> str:
    """Ingest-time identity normalisation (BR-75).

    Same alphabet as ``fir_bakeoff_run._normalise_subject_id`` /
    ``gallery_split._normalise_subject_id``: strip and reject non-string or
    blank-after-strip items. Applied here, at manifest parse, so membership
    (roster lookup) and the census (unique-subject count) see the same
    canonical key instead of diverging on unstripped whitespace. A blank or
    malformed item is a manifest defect and must fail closed at the
    boundary (sr-006) rather than pass through and crash later at point of
    use, or silently vanish.
    """
    if not isinstance(value, str):
        raise StratumJoinError(
            f"{where}.present_identities item must be a non-empty string, "
            f"got {value!r}"
        )
    key = value.strip()
    if not key:
        raise StratumJoinError(
            f"{where}.present_identities item must be a non-empty string, "
            f"got {value!r}"
        )
    return key


def _reject_stratum_conflict(
    mapping: Mapping[Any, str], key: Any, stratum: str, *, kind: str
) -> None:
    prior = mapping.get(key)
    if prior is not None and prior != stratum:
        raise StratumJoinError(f"{kind} {key!r} maps to both {prior!r} and {stratum!r}")


def _declared_images_map(counts: object) -> dict[str, int]:
    if not isinstance(counts, dict):
        raise StratumJoinError("selection manifest 'strata_counts' must be an object")
    declared: dict[str, int] = {}
    for name, cell in counts.items():
        if not isinstance(name, str) or not name:
            raise StratumJoinError("strata_counts keys must be non-empty strings")
        declared[name] = _count_images(cell, name=name)
    return declared


def _count_images(cell: object, *, name: str) -> int:
    if not isinstance(cell, Mapping):
        raise StratumJoinError(
            f"strata_counts[{name!r}] must be an object with 'images', "
            f"got {type(cell).__name__}"
        )
    images = cell.get("images")
    if isinstance(images, bool) or not isinstance(images, int):
        raise StratumJoinError(
            f"strata_counts[{name!r}].images must be an int, got {images!r}"
        )
    if images < 0:
        raise StratumJoinError(f"strata_counts[{name!r}].images must be >= 0, got {images}")
    return images


def _resolve_record(record: object, index: StratumIndex) -> _ResolvedRecord:
    sha256 = _field(record, "sha256")
    raw_media_id = _field(record, "media_id")
    if sha256 is None and raw_media_id is None:
        raise StratumJoinError("record has no sha256 or media_id")
    if sha256 is not None and not isinstance(sha256, str):
        raise StratumJoinError(f"record sha256 must be a string, got {type(sha256).__name__}")
    media_id = (
        None
        if raw_media_id is None
        else _as_media_id(raw_media_id, where="record media_id")
    )
    found: list[tuple[str, str]] = []
    if sha256 is not None:
        stratum = index.by_sha256.get(sha256)
        if stratum is None:
            raise StratumJoinError(
                f"record key absent from selection manifest: sha256={sha256!r}"
            )
        found.append((stratum, sha256))
    if media_id is not None:
        stratum = index.by_media_id.get(media_id)
        if stratum is None:
            raise StratumJoinError(
                f"record key absent from selection manifest: media_id={media_id!r}"
            )
        found.append((stratum, index.sha256_by_media_id[media_id]))
    strata = {item[0] for item in found}
    if len(strata) != 1:
        raise StratumJoinError(
            f"record keys disagree on stratum: sha256={sha256!r} media_id={media_id!r}"
        )
    identities = {item[1] for item in found}
    if len(identities) != 1:
        raise StratumJoinError(
            f"record keys disagree on image: sha256={sha256!r} media_id={media_id!r}"
        )
    image_key = next(iter(identities))
    return _ResolvedRecord(
        stratum=found[0][0],
        image_key=image_key,
        sha256=image_key,
        media_id=media_id,
    )


def _subjects_for(
    record: object,
    resolved: _ResolvedRecord,
    index: StratumIndex,
) -> tuple[str, ...]:
    if resolved.sha256 is not None and resolved.sha256 in index.subjects_by_sha256:
        return index.subjects_by_sha256[resolved.sha256]
    if resolved.media_id is not None and resolved.media_id in index.subjects_by_media_id:
        return index.subjects_by_media_id[resolved.media_id]
    return _subjects_of(record)


def _subjects_of(record: object) -> tuple[str, ...]:
    for name in _SUBJECT_LIST_FIELDS:
        value = _field(record, name)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            return tuple(str(item) for item in value if item)
        raise StratumJoinError(
            f"record {name} must be a list of strings, got {type(value).__name__}"
        )
    for name in _SUBJECT_SCALAR_FIELDS:
        value = _field(record, name)
        if value:
            return (str(value),)
    return ()


def _field(record: object, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


def _as_media_id(value: object, *, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StratumJoinError(f"{where} must be an int, got {value!r}")
    return value


__all__ = [
    "SELECTION_SCHEMA",
    "StratumBucket",
    "StratumIndex",
    "StratumJoinError",
    "StratumReport",
    "join_by_stratum",
    "load_stratum_index",
]
