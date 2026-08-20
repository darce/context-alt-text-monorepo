"""Compose gallery split, injected 1:N searches, and stratum join into one FIR run.

Does not run detect→embed→search. Callers inject ``SearchResult`` lists.

EVAL-18: per-stratum FNIR/FPI plus an overall IET point. An empty foil set is
unmeasured FPI (``fpi is None``), not a count of zero; a closed-set run must
set ``closed_set=True`` and cannot be reached by omitting foils.
EVAL-19: FPI stays an integer count when measured; enrolled-gallery
normalization is caller-supplied.
EVAL-16: undetected mated probes stay in the injected lists — this module does not
filter them out of the error budget.
MLDATA-09: unmeasured FNIR renders via ``BakeoffIETPoint.format_fnir``
("not measured"); declared-empty cells stay in the table.
MLDATA-07 / rg-015: ``manifest_images`` and unique-subject counts pass through
from ``join_by_stratum``; coverage gaps delegate to ``StratumReport``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
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
    "BakeoffIETPoint",
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
class BakeoffIETPoint:
    """IET point as published by a bakeoff run.

    ``measured`` is the FNIR half (n_mated > 0). FPI is ``None`` when the
    non-mated set was never declared — there is no FPI of zero over an
    undeclared foil list (EVAL-18). ``fpi=0`` is legal only for an explicit
    closed-set run or a declared foil list that produced no hits.
    """

    tau: float
    fnir: float | None
    fpi: int | None
    n_mated: int
    n_fnir_misses: int
    n_nonmated: int
    measured: bool
    n_enrolled_gallery_subjects: int | None = None

    def __post_init__(self) -> None:
        if self.measured:
            if self.fnir is None:
                raise ValueError("measured point requires fnir")
            if self.n_mated <= 0:
                raise ValueError("measured point requires n_mated > 0")
        else:
            if self.fnir is not None:
                raise ValueError("unmeasured FNIR must not carry a number")
            if self.n_mated != 0:
                raise ValueError("unmeasured FNIR requires n_mated == 0")
        if self.fpi is None:
            if self.n_nonmated != 0:
                raise ValueError("unmeasured FPI requires n_nonmated == 0")
        elif isinstance(self.fpi, bool) or not isinstance(self.fpi, int) or self.fpi < 0:
            raise ValueError(f"FPI must be a non-negative int or None, got {self.fpi!r}")

    @property
    def fpi_per_enrolled_subject(self) -> float | None:
        if self.fpi is None:
            return None
        n = self.n_enrolled_gallery_subjects
        if n is None or n <= 0:
            return None
        return self.fpi / n

    def format_fnir(self) -> str:
        if not self.measured or self.fnir is None:
            return "not measured"
        return f"{self.fnir:.3f}"


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

    @property
    def withheld_probe_templates(self) -> tuple[Template, ...]:
        """Leftover templates the split withheld from search (MLDATA-09)."""
        return self.split.withheld_probe_templates


@dataclass(frozen=True)
class RunReport:
    """Per-stratum IET points, overall point, and the joined coverage table."""

    points: Mapping[str, BakeoffIETPoint]
    overall: BakeoffIETPoint
    stratum_report: StratumReport
    tau: float
    seed: int
    withheld_probe_templates: tuple[Template, ...] = ()
    search_shortfalls: Mapping[str, int] = field(default_factory=dict)

    def coverage_gaps(self) -> list[dict[str, Any]]:
        return self.stratum_report.coverage_gaps()

    def to_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        n_withheld = len(self.withheld_probe_templates)
        for base in self.stratum_report.to_rows():
            shortfall = int(self.search_shortfalls.get(base["stratum"], 0))
            if base["stratum"] == GALLERY_STRATUM:
                rows.append(
                    {
                        "stratum": base["stratum"],
                        "n_images": base["n_images"],
                        "unique_subjects": base["unique_subjects"],
                        "fnir": "enrolled, not probed",
                        "fpi": None,
                        "n_mated": 0,
                        "n_nonmated": 0,
                        "declared_empty": base["declared_empty"],
                        "measured": False,
                        "incomplete": bool(base["incomplete"] or shortfall > 0),
                        "manifest_images": base["manifest_images"],
                        "tau": self.tau,
                        "fpi_per_enrolled_subject": None,
                        "n_enrolled_gallery_subjects": (
                            self.overall.n_enrolled_gallery_subjects
                        ),
                        "n_withheld_probe_templates": n_withheld,
                        "search_shortfall": shortfall,
                    }
                )
                continue
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
                    "incomplete": bool(base["incomplete"] or shortfall > 0),
                    "manifest_images": base["manifest_images"],
                    "tau": self.tau,
                    "fpi_per_enrolled_subject": point.fpi_per_enrolled_subject,
                    "n_enrolled_gallery_subjects": point.n_enrolled_gallery_subjects,
                    "n_withheld_probe_templates": n_withheld,
                    "search_shortfall": shortfall,
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
    n_enrolled_gallery_subjects: int | None = None,
    overall_nonmated: Sequence[SearchResult] | None = None,
    closed_set: bool = False,
) -> RunReport:
    """Score injected searches per stratum. Does not filter detection misses.

    Empty foil lists are unmeasured for FPI unless ``closed_set=True``.
    """
    if not math.isfinite(tau):
        raise FirBakeoffRunError(f"tau must be finite, got {tau!r}")

    expected_enrolled = len(plan.split.g1) + len(plan.split.g2)
    if n_enrolled_gallery_subjects is None:
        n_enrolled = expected_enrolled
    elif n_enrolled_gallery_subjects != expected_enrolled:
        raise FirBakeoffRunError(
            f"n_enrolled_gallery_subjects={n_enrolled_gallery_subjects} "
            f"does not match gallery size {expected_enrolled} (len(g1)+len(g2))"
        )
    else:
        n_enrolled = n_enrolled_gallery_subjects

    unknown = sorted(set(searches) - _known_strata(plan.index))
    if unknown:
        raise FirBakeoffRunError(f"searches contain undeclared strata: {unknown!r}")

    missing = _missing_required_probe_searches(plan, searches)
    if missing:
        raise FirBakeoffRunError(
            f"searches missing required probe strata {missing!r}: "
            "every populated probe stratum must have a searches key"
        )

    stratum_report = join_by_stratum(_join_records(plan), plan.index)
    points: dict[str, BakeoffIETPoint] = {}
    all_mated: list[SearchResult] = []
    strata_with_nonmated: list[str] = []
    search_shortfalls: dict[str, int] = {}
    for name in _row_names(stratum_report):
        if name == GALLERY_STRATUM:
            # Gallery join records are enrolled, not probed (MLDATA-09).
            continue
        mated, nonmated = _searches_for(searches, stratum=name)
        search_shortfalls[name] = _search_shortfall(
            plan, stratum=name, mated=mated
        )
        all_mated.extend(mated)
        if len(nonmated) > 0:
            strata_with_nonmated.append(name)
        points[name] = _publish_point(
            fnir_fpi_at_threshold(
                mated=mated,
                nonmated=nonmated,
                tau=tau,
                n_enrolled_gallery_subjects=n_enrolled,
            ),
            closed_set=closed_set,
        )
    if overall_nonmated is not None:
        overall_foils = overall_nonmated
    elif strata_with_nonmated:
        raise FirBakeoffRunError(
            "open-set workload must be declared once via overall_nonmated; "
            f"non-mated searches present on strata {strata_with_nonmated!r}"
        )
    else:
        overall_foils = ()
    if closed_set and (len(overall_foils) > 0 or strata_with_nonmated):
        raise FirBakeoffRunError(
            "closed_set=True cannot carry a non-mated (foil) workload (EVAL-18)"
        )
    overall = _publish_point(
        fnir_fpi_at_threshold(
            mated=all_mated,
            nonmated=overall_foils,
            tau=tau,
            n_enrolled_gallery_subjects=n_enrolled,
        ),
        closed_set=closed_set,
    )
    return RunReport(
        points=points,
        overall=overall,
        stratum_report=stratum_report,
        tau=float(tau),
        seed=plan.seed,
        withheld_probe_templates=plan.withheld_probe_templates,
        search_shortfalls=search_shortfalls,
    )


def _publish_point(point: IETPoint, *, closed_set: bool) -> BakeoffIETPoint:
    """Map an IET scorer point onto the bakeoff publication contract.

    IETPoint.fpi is always an int (unowned scorer). An empty foil list is
    unmeasured here unless the caller declared a closed-set run.
    """
    fpi: int | None
    if point.n_nonmated > 0 or closed_set:
        fpi = point.fpi
    else:
        fpi = None
    return BakeoffIETPoint(
        tau=point.tau,
        fnir=point.fnir,
        fpi=fpi,
        n_mated=point.n_mated,
        n_fnir_misses=point.n_fnir_misses,
        n_nonmated=point.n_nonmated,
        measured=point.measured,
        n_enrolled_gallery_subjects=point.n_enrolled_gallery_subjects,
    )


def _search_shortfall(
    plan: RunPlan,
    *,
    stratum: str,
    mated: Sequence[SearchResult],
) -> int:
    """How many plan probe entries are missing from the injected mated list.

    EVAL-16 / EVAL-19: dropping undetected mates or zero-face probes must not
    render as a complete unmeasured cell. Non-probe strata have no shortfall.
    """
    if stratum not in PROBE_STRATA:
        return 0
    expected = len(plan.probe_entries.get(stratum, ()))
    return max(0, expected - len(mated))


def _missing_required_probe_searches(
    plan: RunPlan,
    searches: Mapping[str, Mapping[str, Sequence[SearchResult]]],
) -> list[str]:
    empty = set(plan.index.declared_empty_cells)
    missing: list[str] = []
    for name in PROBE_STRATA:
        if name in empty:
            continue
        if plan.index.declared_images.get(name, 0) <= 0:
            continue
        if name not in searches:
            missing.append(name)
    return missing


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
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item)
    raise FirBakeoffRunError(
        f"present_identities must be a list of strings, got {type(value).__name__}"
    )


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
        media_ids = (int(entry["media_id"]),)
        for subject_id in identities:
            by_subject.setdefault(subject_id, []).append(
                Template(
                    template_id=f"{entry['media_id']}:{subject_id}",
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
