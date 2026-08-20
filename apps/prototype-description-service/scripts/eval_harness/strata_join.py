"""Join run records to the frozen FIR-12 selection-manifest strata.

The selection manifest (schema ``bakeoff-selection/1``) is the authority for
stratum membership, ``strata_counts``, and ``declared_empty_cells``. This
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
    strata_counts: Mapping[str, Any]
    declared_empty_cells: Sequence[str]


@dataclass(frozen=True)
class StratumBucket:
    stratum: str
    n_images: int
    unique_subjects: int


@dataclass(frozen=True)
class StratumReport:
    """Per-stratum image and unique-subject counts for one joined record set."""

    buckets: Mapping[str, StratumBucket]
    declared_empty_cells: Sequence[str]
    strata_order: tuple[str, ...]

    def to_rows(self) -> list[dict[str, Any]]:
        """One row per declared stratum, then one row per declared-empty cell.

        Empty cells stay in the table with ``declared_empty=True`` so an
        untested-looking omission cannot hide them (MLDATA-09).
        """
        rows: list[dict[str, Any]] = []
        for name in self.strata_order:
            bucket = self.buckets[name]
            rows.append(
                {
                    "stratum": name,
                    "n_images": bucket.n_images,
                    "unique_subjects": bucket.unique_subjects,
                    "declared_empty": False,
                }
            )
        for cell in self.declared_empty_cells:
            rows.append(
                {
                    "stratum": cell,
                    "n_images": 0,
                    "unique_subjects": 0,
                    "declared_empty": True,
                }
            )
        return rows


def load_stratum_index(path: str | Path) -> StratumIndex:
    """Load the selection manifest and index every entry by sha256 and media_id."""
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
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise StratumJoinError("selection manifest 'entries' must be a list")
    by_sha256: dict[str, str] = {}
    by_media_id: dict[int, str] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StratumJoinError(f"entries[{i}] must be an object")
        absent = [key for key in _REQUIRED_ENTRY if key not in entry]
        if absent:
            raise StratumJoinError(f"entries[{i}] missing required keys {absent}")
        sha256 = entry["sha256"]
        if not isinstance(sha256, str) or not sha256:
            raise StratumJoinError(f"entries[{i}].sha256 must be a non-empty string")
        media_id = _as_media_id(entry["media_id"], where=f"entries[{i}].media_id")
        stratum = entry["stratum"]
        if not isinstance(stratum, str) or not stratum:
            raise StratumJoinError(f"entries[{i}].stratum must be a non-empty string")
        prior_sha = by_sha256.get(sha256)
        if prior_sha is not None and prior_sha != stratum:
            raise StratumJoinError(
                f"sha256 {sha256!r} maps to both {prior_sha!r} and {stratum!r}"
            )
        prior_mid = by_media_id.get(media_id)
        if prior_mid is not None and prior_mid != stratum:
            raise StratumJoinError(
                f"media_id {media_id} maps to both {prior_mid!r} and {stratum!r}"
            )
        by_sha256[sha256] = stratum
        by_media_id[media_id] = stratum
    counts = payload["strata_counts"]
    empty = payload["declared_empty_cells"]
    if not isinstance(counts, dict):
        raise StratumJoinError("selection manifest 'strata_counts' must be an object")
    if not isinstance(empty, list) or not all(isinstance(cell, str) for cell in empty):
        raise StratumJoinError(
            "selection manifest 'declared_empty_cells' must be a list of strings"
        )
    return StratumIndex(
        by_sha256=by_sha256,
        by_media_id=by_media_id,
        strata_counts=counts,
        declared_empty_cells=empty,
    )


def join_by_stratum(
    records: Iterable[object],
    index: StratumIndex,
) -> StratumReport:
    """Bucket records by selection-manifest stratum.

    Each bucket reports ``n_images`` (distinct image keys) and
    ``unique_subjects`` (distinct subject names). A record whose sha256 or
    media_id is absent from the index raises — silent drops are forbidden.
    """
    images: dict[str, set[str]] = defaultdict(set)
    subjects: dict[str, set[str]] = defaultdict(set)
    for record in records:
        stratum, image_key = _resolve_record(record, index)
        images[stratum].add(image_key)
        subjects[stratum].update(_subjects_of(record))
    order = tuple(index.strata_counts)
    buckets: dict[str, StratumBucket] = {}
    for name in order:
        buckets[name] = StratumBucket(
            stratum=name,
            n_images=len(images.get(name, ())),
            unique_subjects=len(subjects.get(name, ())),
        )
    extra = sorted(set(images) - set(order))
    for name in extra:
        buckets[name] = StratumBucket(
            stratum=name,
            n_images=len(images[name]),
            unique_subjects=len(subjects[name]),
        )
        order = order + (name,)
    return StratumReport(
        buckets=buckets,
        declared_empty_cells=index.declared_empty_cells,
        strata_order=order,
    )


def _resolve_record(record: object, index: StratumIndex) -> tuple[str, str]:
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
        found.append((stratum, str(media_id)))
    strata = {item[0] for item in found}
    if len(strata) != 1:
        raise StratumJoinError(
            f"record keys disagree on stratum: sha256={sha256!r} media_id={media_id!r}"
        )
    stratum = found[0][0]
    image_key = sha256 if sha256 is not None else str(media_id)
    return stratum, image_key


def _subjects_of(record: object) -> tuple[str, ...]:
    for name in _SUBJECT_LIST_FIELDS:
        value = _field(record, name)
        if value is None:
            continue
        if isinstance(value, str):
            return (value,) if value else ()
        return tuple(str(item) for item in value if item)
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
        if isinstance(value, str) and value.isdigit():
            return int(value)
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
