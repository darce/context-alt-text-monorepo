"""Compose gallery split, injected 1:N searches, and stratum join into one FIR run.

Does not run detect→embed→search. Callers inject ``SearchResult`` lists.

EVAL-18: per-stratum FNIR/FPI plus an overall IET point.
EVAL-19: FPI stays an integer count; enrolled-gallery normalization is caller-supplied.
EVAL-16: undetected mated probes stay in the injected lists — this module does not
filter them out of the error budget.
MLDATA-09: unmeasured FNIR renders via ``IETPoint.format_fnir`` ("not measured");
declared-empty cells stay in the table.
MLDATA-07 / rg-015: ``manifest_images`` and unique-subject counts pass through
from ``join_by_stratum``; coverage gaps delegate to ``StratumReport``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.eval_harness.gallery_split import (
    GalleryName,
    GallerySplit,
    Template,
    build_disjoint_galleries,
    probes_for,
)
from scripts.eval_harness.open_set_identification import (
    IETPoint,
    SearchResult,
    fnir_fpi_at_threshold,
)
from scripts.eval_harness.strata_join import (
    StratumIndex,
    StratumReport,
    join_by_stratum,
    load_stratum_index,
)

GALLERY_STRATUM = "E_clean"
PROBE_STRATA: tuple[str, ...] = (
    "A_true_occluder",
    "B_eyewear",
    "C_pose",
    "D_capture",
)

__all__ = [
    "GALLERY_STRATUM",
    "PROBE_STRATA",
    "FirBakeoffRunError",
    "ProbeEntry",
    "RunPlan",
    "RunReport",
    "build_run_plan",
    "score_run",
]


class FirBakeoffRunError(ValueError):
    """Run plan or score payload that would hide a measurement cell."""


@dataclass(frozen=True)
class ProbeEntry:
    """One selection-manifest image used as a probe (or gallery join record)."""

    media_id: int
    sha256: str
    stratum: str
    present_identities: tuple[str, ...]


@dataclass(frozen=True)
class RunPlan:
    """Reproducible gallery split plus probe entries keyed by stratum."""

    split: GallerySplit
    probe_entries: Mapping[str, tuple[ProbeEntry, ...]]
    seed: int
    index: StratumIndex
    gallery_entries: tuple[ProbeEntry, ...]


@dataclass(frozen=True)
class RunReport:
    """Per-stratum IET points, overall point, and the joined coverage table."""

    points: Mapping[str, IETPoint]
    overall: IETPoint
    stratum_report: StratumReport
    tau: float
    seed: int

    def coverage_gaps(self) -> list[dict[str, Any]]:
        return self.stratum_report.coverage_gaps()

    def to_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for base in self.stratum_report.to_rows():
            point = self.points[base["stratum"]]
            rows.append(
                {
                    "stratum": base["stratum"],
                    "n_images": base["n_images"],
                    "unique_subjects": base["unique_subjects"],
                    "fnir": point.format_fnir(),
                    "fpi": point.fpi,
                    "n_mated": point.n_mated,
                    "n_nonmated": point.n_nonmated,
                    "declared_empty": base["declared_empty"],
                    "measured": point.measured,
                    "incomplete": base["incomplete"],
                    "manifest_images": base["manifest_images"],
                }
            )
        return rows


def build_run_plan(*, selection_manifest_path: str | Path, seed: int) -> RunPlan:
    """Load the frozen frame, enroll E_clean, and record A/B/C/D probes."""
    path = Path(selection_manifest_path)
    index = load_stratum_index(path)
    entries = _read_entries(path)
    templates_by_subject = _templates_from_e_clean(entries)
    if not templates_by_subject:
        raise FirBakeoffRunError(
            "no E_clean identity templates: refusing an empty gallery (EVAL-18)"
        )
    split = build_disjoint_galleries(
        templates_by_subject=templates_by_subject,
        seed=seed,
    )
    # Fail fast if the split cannot produce an open-set (non-mated) search.
    probes_for(split, gallery=GalleryName.G1)
    probes_for(split, gallery=GalleryName.G2)
    return RunPlan(
        split=split,
        probe_entries=_probe_entries(entries),
        seed=seed,
        index=index,
        gallery_entries=_gallery_entries(entries),
    )


def score_run(
    *,
    plan: RunPlan,
    searches: Mapping[str, Mapping[str, Sequence[SearchResult]]],
    tau: float,
    n_enrolled_gallery_subjects: int,
) -> RunReport:
    """Score injected searches per stratum. Does not filter detection misses."""
    unknown = sorted(set(searches) - _known_strata(plan.index))
    if unknown:
        raise FirBakeoffRunError(f"searches contain undeclared strata: {unknown!r}")

    stratum_report = join_by_stratum(_join_records(plan), plan.index)
    points: dict[str, IETPoint] = {}
    all_mated: list[SearchResult] = []
    all_nonmated: list[SearchResult] = []
    for name in _row_names(stratum_report):
        mated, nonmated = _searches_for(searches, stratum=name)
        all_mated.extend(mated)
        all_nonmated.extend(nonmated)
        points[name] = fnir_fpi_at_threshold(
            mated=mated,
            nonmated=nonmated,
            tau=tau,
            n_enrolled_gallery_subjects=n_enrolled_gallery_subjects,
        )
    overall = fnir_fpi_at_threshold(
        mated=all_mated,
        nonmated=all_nonmated,
        tau=tau,
        n_enrolled_gallery_subjects=n_enrolled_gallery_subjects,
    )
    return RunReport(
        points=points,
        overall=overall,
        stratum_report=stratum_report,
        tau=float(tau),
        seed=plan.seed,
    )


def _known_strata(index: StratumIndex) -> set[str]:
    return set(index.strata_counts) | set(index.declared_empty_cells)


def _row_names(report: StratumReport) -> tuple[str, ...]:
    return tuple(row["stratum"] for row in report.to_rows())


def _searches_for(
    searches: Mapping[str, Mapping[str, Sequence[SearchResult]]],
    *,
    stratum: str,
) -> tuple[Sequence[SearchResult], Sequence[SearchResult]]:
    payload = searches.get(stratum)
    if payload is None:
        return (), ()
    if not isinstance(payload, Mapping):
        raise FirBakeoffRunError(
            f"searches[{stratum!r}] must be a mapping with 'mated' and 'nonmated'"
        )
    missing = [key for key in ("mated", "nonmated") if key not in payload]
    if missing:
        raise FirBakeoffRunError(
            f"searches[{stratum!r}] missing required keys {missing}"
        )
    return payload["mated"], payload["nonmated"]


def _join_records(plan: RunPlan) -> list[ProbeEntry]:
    records = list(plan.gallery_entries)
    for name in PROBE_STRATA:
        records.extend(plan.probe_entries.get(name, ()))
    return records


def _read_entries(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    if not isinstance(entries, list):
        raise FirBakeoffRunError("selection manifest 'entries' must be a list")
    return entries


def _identities(entry: Mapping[str, Any]) -> tuple[str, ...]:
    value = entry.get("present_identities")
    if not value:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value if item)


def _as_probe_entry(entry: Mapping[str, Any], *, stratum: str) -> ProbeEntry:
    sha256 = entry.get("sha256")
    if not isinstance(sha256, str) or not sha256:
        raise FirBakeoffRunError("entry sha256 must be a non-empty string")
    media_id = entry.get("media_id")
    if isinstance(media_id, bool) or not isinstance(media_id, int):
        raise FirBakeoffRunError(f"entry media_id must be an int, got {media_id!r}")
    return ProbeEntry(
        media_id=media_id,
        sha256=sha256,
        stratum=stratum,
        present_identities=_identities(entry),
    )


def _templates_from_e_clean(
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, list[Template]]:
    by_subject: dict[str, list[Template]] = {}
    for entry in entries:
        if entry.get("stratum") != GALLERY_STRATUM:
            continue
        identities = _identities(entry)
        if not identities:
            continue
        media_id = entry["media_id"]
        # Group photos share one media_id across subjects; gallery_split
        # forbids that id in two galleries or in gallery+reserved probes.
        media_ids = (int(media_id),) if len(identities) == 1 else ()
        for subject_id in identities:
            by_subject.setdefault(subject_id, []).append(
                Template(
                    template_id=f"{media_id}:{subject_id}",
                    subject_id=subject_id,
                    media_ids=media_ids,
                )
            )
    return by_subject


def _gallery_entries(entries: Sequence[Mapping[str, Any]]) -> tuple[ProbeEntry, ...]:
    out: list[ProbeEntry] = []
    for entry in entries:
        if entry.get("stratum") != GALLERY_STRATUM:
            continue
        if not _identities(entry):
            continue
        out.append(_as_probe_entry(entry, stratum=GALLERY_STRATUM))
    return tuple(out)


def _probe_entries(
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[ProbeEntry, ...]]:
    buckets: dict[str, list[ProbeEntry]] = {name: [] for name in PROBE_STRATA}
    for entry in entries:
        stratum = entry.get("stratum")
        if stratum not in buckets:
            continue
        buckets[stratum].append(_as_probe_entry(entry, stratum=stratum))
    return {name: tuple(items) for name, items in buckets.items()}
