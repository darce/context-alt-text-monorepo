"""Compose gallery split, injected 1:N searches, and stratum join into one FIR run.

Does not run detect→embed→search. Callers inject ``SearchResult`` lists.

EVAL-18: per-stratum FNIR/FPI plus an overall IET point. An empty foil set is
unmeasured FPI (``fpi is None``), not a count of zero; a closed-set run must
set ``closed_set=True`` and cannot be reached by omitting foils.
EVAL-19: FPI stays an integer count when measured; enrolled-gallery
normalization follows the declared search gallery, never ``len(g1)+len(g2)``.
EVAL-16: undetected mated probes stay in the injected lists — this module does not
filter them out of the error budget. Completeness counts distinct
``MatedSearchUnit`` keys, never ``len(mated)``; a duplicate submission is a
caller error, not extra coverage of a dropped mate.
EVAL-18: foil (still, gallery) units are the FPI exposure. A truncated or
duplicated foil set cannot render as a complete FPI cell.
MLDATA-09: unmeasured FNIR renders via ``BakeoffIETPoint.format_fnir``
("not measured"); declared-empty cells stay in the table.
MLDATA-07 / rg-015: ``manifest_images`` and unique-subject counts pass through
from ``join_by_stratum``; coverage gaps delegate to ``StratumReport``.
An overall FNIR built over an incomplete probe stratum prints ``incomplete``,
never a bare number.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.eval_harness import gate_contract
from scripts.eval_harness.gallery_split import (
    GalleryName,
    GallerySplit,
    ProbeSet,
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
    "MatedSearchUnit",
    "ProbeEntry",
    "RunPlan",
    "RunReport",
    "both_gallery_probe_entries",
    "both_gallery_search_count",
    "build_run_plan",
    "expected_mated_search_count",
    "expected_nonmated_search_count",
    "mated_galleries_for",
    "mated_identities_for",
    "occluded_probes_for",
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
    galleries: tuple[GalleryName, ...] = ()
    incomplete: bool = False

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
        if self.incomplete:
            return "incomplete"
        return f"{self.fnir:.3f}"


@dataclass(frozen=True)
class ProbeEntry:
    """One selection-manifest image used as a probe (or gallery join record)."""

    media_id: int
    sha256: str
    stratum: str
    present_identities: tuple[str, ...]


@dataclass(frozen=True)
class MatedSearchUnit:
    """One FNIR unit: (still, gallery, enrolled subject).

    JANUS 2.2 is one template per subject. A still with three enrolled
    subjects is three mated searches, never one. EVAL-16 keeps a dropped
    co-subject in the error budget; EVAL-18 requires this unit to be
    declared rather than inferred from still count.
    """

    entry: ProbeEntry
    gallery: GalleryName
    subject_id: str


@dataclass(frozen=True)
class RunPlan:
    """Reproducible gallery split plus probe entries keyed by stratum."""

    split: GallerySplit
    probe_entries: Mapping[str, tuple[ProbeEntry, ...]]
    seed: int
    index: StratumIndex
    gallery_entries: tuple[ProbeEntry, ...]
    probe_sets: Mapping[GalleryName, ProbeSet]

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
    nonmated_shortfalls: Mapping[str, int] = field(default_factory=dict)
    never_measured_probe_strata: tuple[str, ...] = ()
    """Declared PROBE_STRATA absent from ``points`` (BR-68): never measured,
    as distinct from measured-and-short (``points[name].incomplete``)."""

    def coverage_gaps(self) -> list[dict[str, Any]]:
        return self.stratum_report.coverage_gaps()

    def to_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        n_withheld = len(self.withheld_probe_templates)
        for base in self.stratum_report.to_rows():
            shortfall = int(self.search_shortfalls.get(base["stratum"], 0))
            foil_shortfall = int(self.nonmated_shortfalls.get(base["stratum"], 0))
            cell_incomplete = bool(
                base["incomplete"] or shortfall > 0 or foil_shortfall > 0
            )
            if base["stratum"] == GALLERY_STRATUM:
                rows.append(
                    {
                        "stratum": base["stratum"],
                        "rubric_version": gate_contract.RUBRIC_VERSION,
                        "n_images": base["n_images"],
                        "unique_subjects": base["unique_subjects"],
                        "fnir": "enrolled, not probed",
                        "fpi": None,
                        "n_mated": 0,
                        "n_nonmated": 0,
                        "declared_empty": base["declared_empty"],
                        "measured": False,
                        "incomplete": cell_incomplete,
                        "manifest_images": base["manifest_images"],
                        "tau": self.tau,
                        "fpi_per_enrolled_subject": None,
                        "n_enrolled_gallery_subjects": (
                            self.overall.n_enrolled_gallery_subjects
                        ),
                        "gallery": (),
                        "n_withheld_probe_templates": n_withheld,
                        "search_shortfall": shortfall,
                        "nonmated_shortfall": foil_shortfall,
                    }
                )
                continue
            point = self.points[base["stratum"]]
            rows.append(
                {
                    "stratum": base["stratum"],
                    "rubric_version": gate_contract.RUBRIC_VERSION,
                    "n_images": base["n_images"],
                    "unique_subjects": base["unique_subjects"],
                    "fnir": point.format_fnir(),
                    "fpi": point.fpi,
                    "n_mated": point.n_mated,
                    "n_nonmated": point.n_nonmated,
                    "declared_empty": base["declared_empty"],
                    "measured": point.measured,
                    "incomplete": cell_incomplete,
                    "manifest_images": base["manifest_images"],
                    "tau": self.tau,
                    "fpi_per_enrolled_subject": point.fpi_per_enrolled_subject,
                    "n_enrolled_gallery_subjects": point.n_enrolled_gallery_subjects,
                    "gallery": tuple(g.value for g in point.galleries),
                    "n_withheld_probe_templates": n_withheld,
                    "search_shortfall": shortfall,
                    "nonmated_shortfall": foil_shortfall,
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
    probe_sets = {
        GalleryName.G1: probes_for(split, gallery=GalleryName.G1),
        GalleryName.G2: probes_for(split, gallery=GalleryName.G2),
    }
    return RunPlan(
        split=split,
        probe_entries=_probe_entries(entries),
        seed=seed,
        index=index,
        gallery_entries=_gallery_entries(entries),
        probe_sets=probe_sets,
    )


def _normalise_subject_id(value: object, *, gallery: str) -> str:
    """Same alphabet as gallery_split._normalise_subject_id (BR-64 / EVAL-18)."""
    if not isinstance(value, str):
        raise FirBakeoffRunError(
            f"{gallery} subject_id must be a non-empty string, got {value!r}"
        )
    key = value.strip()
    if not key:
        raise FirBakeoffRunError(
            f"{gallery} subject_id must be a non-empty string, got {value!r}"
        )
    return key


def mated_identities_for(
    entry: ProbeEntry, *, split: GallerySplit, gallery: GalleryName | str
) -> tuple[str, ...]:
    """Identities on ``entry`` enrolled in ``gallery`` (empty → foil for it).

    Deduplicated by normalised key (BR-73): the MatedSearchUnit contract is
    one enrolled subject, one mated search, never one per mention. Without
    this guard two spellings of the same subject on one still (e.g. 'Bob'
    and 'Bob ', which now normalise to the same roster key at ingest —
    BR-75) would each append, doubling that subject's search and biasing
    FNIR's denominator downward. A duplicate mention is treated as the same
    search unit rather than a manifest error: by the time it reaches here
    the identity has already passed ingest validation (BR-75), so a repeat
    reads as "this subject is present" stated twice, not as corrupt data.
    """
    try:
        name = GalleryName(gallery)
    except ValueError as exc:
        raise FirBakeoffRunError(
            f"gallery {gallery!r} is not a declared gallery of the split"
        ) from exc
    roster = split.g1 if name is GalleryName.G1 else split.g2
    matched: list[str] = []
    seen: set[str] = set()
    for subject_id in entry.present_identities:
        key = _normalise_subject_id(subject_id, gallery=name.value)
        if key in roster and key not in seen:
            matched.append(key)
            seen.add(key)
    return tuple(matched)


def mated_galleries_for(entry: ProbeEntry, *, plan: RunPlan) -> tuple[GalleryName, ...]:
    """Declared galleries this still is mated against (one or both)."""
    return tuple(
        gallery
        for gallery in _declared_galleries(plan)
        if mated_identities_for(entry, split=plan.split, gallery=gallery)
    )


def both_gallery_probe_entries(plan: RunPlan) -> tuple[ProbeEntry, ...]:
    """Occluded stills with identities enrolled in both G1 and G2."""
    return tuple(
        entry
        for stratum in PROBE_STRATA
        for entry in plan.probe_entries.get(stratum, ())
        if len(mated_galleries_for(entry, plan=plan)) == 2
    )


def both_gallery_search_count(plan: RunPlan) -> int:
    """Mated (still, gallery, enrolled subject) units from co-present stills."""
    return sum(
        len(mated_identities_for(entry, split=plan.split, gallery=gallery))
        for entry in both_gallery_probe_entries(plan)
        for gallery in mated_galleries_for(entry, plan=plan)
    )


def occluded_probes_for(
    plan: RunPlan, *, gallery: GalleryName | str
) -> tuple[tuple[MatedSearchUnit, ...], tuple[ProbeEntry, ...]]:
    """Mated subject-units / foil stills for a 1:N search against ``gallery``.

    Consumes ``plan.probe_sets`` as the declared-gallery set. The mated
    unit is one enrolled subject on one still against this gallery
    (JANUS 2.2 / EVAL-16 / EVAL-18). A still co-present in both galleries
    yields one unit per enrolled subject per gallery, never one unit for
    the still.
    """
    name = _as_declared_gallery(gallery, declared=plan.probe_sets)
    mated: list[MatedSearchUnit] = []
    foils: list[ProbeEntry] = []
    for stratum in PROBE_STRATA:
        for entry in plan.probe_entries.get(stratum, ()):
            identities = mated_identities_for(entry, split=plan.split, gallery=name)
            if identities:
                for subject_id in identities:
                    mated.append(
                        MatedSearchUnit(
                            entry=entry, gallery=name, subject_id=subject_id
                        )
                    )
            else:
                foils.append(entry)
    return tuple(mated), tuple(foils)


def expected_mated_search_count(plan: RunPlan, *, stratum: str) -> int:
    """Mated (still, gallery, enrolled subject) units the stratum must cover.

    Derived from ``occluded_probes_for``; never counted independently.
    """
    return len(_mated_search_units(plan, stratum=stratum))


def expected_nonmated_search_count(plan: RunPlan, *, stratum: str) -> int:
    """Foil (still, gallery) units the stratum must cover.

    Foils stay still-level (BR-29). Derived from ``occluded_probes_for``[1].
    """
    return len(_foil_search_units(plan, stratum=stratum))


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
    Classifies each ``ProbeEntry`` against ``plan.split`` / ``plan.probe_sets``:
    a search is mated iff the probe carries an identity enrolled in its
    declared gallery (EVAL-18 / JANUS 2.2).
    FPI per enrolled subject uses the unique declared gallery of the
    searches that compose the point (EVAL-19 / JANUS 2.3.4). A pooled
    point that spans both galleries has no honest denominator.
    """
    if not math.isfinite(tau):
        raise FirBakeoffRunError(f"tau must be finite, got {tau!r}")

    _reject_union_enrolled_count(plan, n_enrolled_gallery_subjects)

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
    coverage_incomplete = {
        row["stratum"]: bool(row["incomplete"]) for row in stratum_report.to_rows()
    }
    points: dict[str, BakeoffIETPoint] = {}
    all_mated: list[SearchResult] = []
    strata_with_nonmated: list[str] = []
    search_shortfalls: dict[str, int] = {}
    nonmated_shortfalls: dict[str, int] = {}
    for name in _row_names(stratum_report):
        if name == GALLERY_STRATUM:
            # Gallery join records are enrolled, not probed (MLDATA-09).
            continue
        mated, nonmated = _searches_for(searches, stratum=name)
        _validate_stratum_searches(
            plan, stratum=name, mated=mated, nonmated=nonmated
        )
        mated_shortfall = _search_shortfall(plan, stratum=name, mated=mated)
        foil_shortfall = _nonmated_search_shortfall(
            plan, stratum=name, nonmated=nonmated, closed_set=closed_set
        )
        search_shortfalls[name] = mated_shortfall
        nonmated_shortfalls[name] = foil_shortfall
        all_mated.extend(mated)
        if len(nonmated) > 0:
            strata_with_nonmated.append(name)
        galleries = _galleries_of(plan, (*mated, *nonmated))
        cell_incomplete = bool(
            coverage_incomplete.get(name, False)
            or mated_shortfall > 0
            or foil_shortfall > 0
        )
        points[name] = _publish_point(
            fnir_fpi_at_threshold(
                mated=mated,
                nonmated=nonmated,
                tau=tau,
                n_enrolled_gallery_subjects=_enrolled_for(
                    plan,
                    galleries,
                    supplied=n_enrolled_gallery_subjects,
                ),
            ),
            closed_set=closed_set,
            galleries=galleries,
            incomplete=cell_incomplete,
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
    _validate_overall_nonmated(plan, overall_foils)
    overall_galleries = _galleries_of(plan, (*all_mated, *overall_foils))
    never_measured = _never_measured_probe_strata(plan, points)
    overall_incomplete = bool(never_measured) or any(
        points[name].incomplete for name in PROBE_STRATA if name in points
    )
    overall = _publish_point(
        fnir_fpi_at_threshold(
            mated=all_mated,
            nonmated=overall_foils,
            tau=tau,
            n_enrolled_gallery_subjects=_enrolled_for(
                plan,
                overall_galleries,
                supplied=n_enrolled_gallery_subjects,
            ),
        ),
        closed_set=closed_set,
        galleries=overall_galleries,
        incomplete=overall_incomplete,
    )
    return RunReport(
        points=points,
        overall=overall,
        stratum_report=stratum_report,
        tau=float(tau),
        seed=plan.seed,
        withheld_probe_templates=plan.withheld_probe_templates,
        search_shortfalls=search_shortfalls,
        nonmated_shortfalls=nonmated_shortfalls,
        never_measured_probe_strata=never_measured,
    )


def _never_measured_probe_strata(
    plan: RunPlan, points: Mapping[str, BakeoffIETPoint]
) -> tuple[str, ...]:
    """Declared probe strata that never produced a measured/short point (BR-68).

    Rolls up over the DECLARED ``PROBE_STRATA`` set, not the observed
    ``points`` keys: a stratum absent from ``points`` because it produced
    zero join rows (never appeared in ``stratum_report``) must count as
    incomplete for a different reason than "measured and short"
    (``points[name].incomplete``) — it was never measured at all. The only
    explicit, documented exemption is a stratum the manifest itself
    declares empty (``declared_empty_cells``); that is a legitimate
    zero-workload cell, not an accidental gap.
    """
    return tuple(
        name
        for name in PROBE_STRATA
        if name not in points and not _is_exempt_probe_stratum(plan, name)
    )


def _is_exempt_probe_stratum(plan: RunPlan, name: str) -> bool:
    """Whether a declared probe stratum legitimately requires no measurement.

    Only an explicit manifest ``declared_empty_cells`` entry is evidence of
    exemption. In particular, a missing ``D_capture`` count is not empty: BR-68
    showed that treating its implicit zero as exempt lets that unmeasured cell
    bypass the required-search guard and reach publication as complete.
    """
    return name in plan.index.declared_empty_cells


def _publish_point(
    point: IETPoint,
    *,
    closed_set: bool,
    galleries: tuple[GalleryName, ...] = (),
    incomplete: bool = False,
) -> BakeoffIETPoint:
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
        galleries=galleries,
        incomplete=incomplete,
    )


def _roster_size(plan: RunPlan, gallery: GalleryName) -> int:
    if gallery is GalleryName.G1:
        return len(plan.split.g1)
    return len(plan.split.g2)


def _reject_union_enrolled_count(
    plan: RunPlan, supplied: int | None
) -> None:
    if supplied is None:
        return
    legal = {_roster_size(plan, GalleryName.G1), _roster_size(plan, GalleryName.G2)}
    if supplied not in legal:
        raise FirBakeoffRunError(
            f"n_enrolled_gallery_subjects={supplied} does not match a declared "
            f"gallery size (g1={_roster_size(plan, GalleryName.G1)}, "
            f"g2={_roster_size(plan, GalleryName.G2)})"
        )


def _galleries_of(
    plan: RunPlan, searches: Sequence[SearchResult]
) -> tuple[GalleryName, ...]:
    names = {
        _as_declared_gallery(search.gallery, declared=plan.probe_sets)
        for search in searches
    }
    return tuple(sorted(names, key=lambda gallery: gallery.value))


def _enrolled_for(
    plan: RunPlan,
    galleries: tuple[GalleryName, ...],
    *,
    supplied: int | None,
) -> int | None:
    if len(galleries) != 1:
        if supplied is not None and len(galleries) > 1:
            raise FirBakeoffRunError(
                f"n_enrolled_gallery_subjects={supplied} cannot normalize FPI "
                f"across galleries {[g.value for g in galleries]!r}"
            )
        return None
    n = _roster_size(plan, galleries[0])
    if supplied is not None and supplied != n:
        raise FirBakeoffRunError(
            f"n_enrolled_gallery_subjects={supplied} does not match gallery "
            f"{galleries[0].value} size {n}"
        )
    return n


def _declared_galleries(plan: RunPlan) -> tuple[GalleryName, ...]:
    return tuple(sorted(plan.probe_sets, key=lambda gallery: gallery.value))


def _mated_search_units(
    plan: RunPlan, *, stratum: str | None = None
) -> tuple[MatedSearchUnit, ...]:
    return tuple(
        unit
        for gallery in _declared_galleries(plan)
        for unit in occluded_probes_for(plan, gallery=gallery)[0]
        if stratum is None or unit.entry.stratum == stratum
    )


def _foil_search_units(
    plan: RunPlan, *, stratum: str | None = None
) -> tuple[tuple[ProbeEntry, GalleryName], ...]:
    return tuple(
        (entry, gallery)
        for gallery in _declared_galleries(plan)
        for entry in occluded_probes_for(plan, gallery=gallery)[1]
        if stratum is None or entry.stratum == stratum
    )


def _mated_unit_key(
    search: SearchResult, *, plan: RunPlan
) -> tuple[int, GalleryName, str]:
    gallery = _as_declared_gallery(search.gallery, declared=plan.probe_sets)
    if search.true_name is None:
        raise FirBakeoffRunError(
            f"mated search media_id={search.media_id} gallery={gallery.value} "
            "is missing true_name"
        )
    return (search.media_id, gallery, search.true_name)


def _foil_unit_key(
    search: SearchResult, *, plan: RunPlan
) -> tuple[int, GalleryName]:
    gallery = _as_declared_gallery(search.gallery, declared=plan.probe_sets)
    return (search.media_id, gallery)


def _as_declared_gallery(
    value: GalleryName | str, *, declared: Mapping[GalleryName, ProbeSet]
) -> GalleryName:
    try:
        name = GalleryName(value)
    except ValueError as exc:
        raise FirBakeoffRunError(
            f"search gallery {value!r} is not a declared gallery of the split"
        ) from exc
    if name not in declared:
        raise FirBakeoffRunError(
            f"search gallery {name.value!r} is not a declared gallery of the split"
        )
    return name


def _validate_search_against_entry(
    search: SearchResult,
    *,
    entry: ProbeEntry,
    plan: RunPlan,
    filed_as_mated: bool,
) -> GalleryName:
    gallery = _as_declared_gallery(search.gallery, declared=plan.probe_sets)
    identities = mated_identities_for(entry, split=plan.split, gallery=gallery)
    if filed_as_mated:
        if not identities:
            raise FirBakeoffRunError(
                f"search media_id={search.media_id} gallery={gallery.value} "
                "has no identity enrolled in that gallery but was filed as mated"
            )
        if search.true_name not in identities:
            raise FirBakeoffRunError(
                f"mated search true_name={search.true_name!r} is not enrolled in "
                f"gallery {gallery.value} on media_id={search.media_id}"
            )
    elif identities:
        raise FirBakeoffRunError(
            f"search media_id={search.media_id} gallery={gallery.value} "
            "carries an identity enrolled in that gallery but was filed as non-mated"
        )
    return gallery


def _validate_stratum_searches(
    plan: RunPlan,
    *,
    stratum: str,
    mated: Sequence[SearchResult],
    nonmated: Sequence[SearchResult],
) -> None:
    by_media = {entry.media_id: entry for entry in plan.probe_entries.get(stratum, ())}
    appeared: dict[int, set[GalleryName]] = {}
    seen_mated: set[tuple[int, GalleryName, str]] = set()
    seen_foils: set[tuple[int, GalleryName]] = set()
    for filed_as_mated, group in ((True, mated), (False, nonmated)):
        for search in group:
            entry = by_media.get(search.media_id)
            if entry is None:
                raise FirBakeoffRunError(
                    f"search media_id={search.media_id} is not a probe in stratum {stratum!r}"
                )
            gallery = _validate_search_against_entry(
                search, entry=entry, plan=plan, filed_as_mated=filed_as_mated
            )
            appeared.setdefault(search.media_id, set()).add(gallery)
            if filed_as_mated:
                key = _mated_unit_key(search, plan=plan)
                if key in seen_mated:
                    raise FirBakeoffRunError(
                        f"duplicate mated search media_id={search.media_id} "
                        f"gallery={gallery.value} true_name={search.true_name!r}"
                    )
                seen_mated.add(key)
            else:
                foil_key = _foil_unit_key(search, plan=plan)
                if foil_key in seen_foils:
                    raise FirBakeoffRunError(
                        f"duplicate non-mated search media_id={search.media_id} "
                        f"gallery={gallery.value}"
                    )
                seen_foils.add(foil_key)
    needed_by_media: dict[int, set[GalleryName]] = {}
    for unit in _mated_search_units(plan, stratum=stratum):
        needed_by_media.setdefault(unit.entry.media_id, set()).add(unit.gallery)
    for media_id, needed in needed_by_media.items():
        if len(needed) < 2:
            continue
        seen = appeared.get(media_id, set())
        if seen and seen != needed:
            raise FirBakeoffRunError(
                f"probe media_id={media_id} is enrolled in both galleries "
                f"but appears with "
                f"{[g.value for g in sorted(seen, key=lambda g: g.value)]!r} "
                "in searches"
            )


def _validate_overall_nonmated(
    plan: RunPlan, foils: Sequence[SearchResult]
) -> None:
    by_media = {
        entry.media_id: entry
        for stratum in PROBE_STRATA
        for entry in plan.probe_entries.get(stratum, ())
    }
    seen_foils: set[tuple[int, GalleryName]] = set()
    for search in foils:
        entry = by_media.get(search.media_id)
        if entry is None:
            raise FirBakeoffRunError(
                f"overall_nonmated media_id={search.media_id} is not a probe entry"
            )
        gallery = _validate_search_against_entry(
            search, entry=entry, plan=plan, filed_as_mated=False
        )
        foil_key = (search.media_id, gallery)
        if foil_key in seen_foils:
            raise FirBakeoffRunError(
                f"duplicate overall_nonmated media_id={search.media_id} "
                f"gallery={gallery.value}"
            )
        seen_foils.add(foil_key)


def _search_shortfall(
    plan: RunPlan,
    *,
    stratum: str,
    mated: Sequence[SearchResult],
) -> int:
    """How many mated (still, gallery, enrolled subject) units are missing.

    EVAL-16 / EVAL-19: dropping undetected mates or co-subjects must not
    render as a complete unmeasured cell. Non-probe strata have no shortfall.
    Count is distinct ``MatedSearchUnit`` keys against
    ``expected_mated_search_count``, never ``len(mated)``.
    """
    if stratum not in PROBE_STRATA:
        return 0
    expected = {
        (unit.entry.media_id, unit.gallery, unit.subject_id)
        for unit in _mated_search_units(plan, stratum=stratum)
    }
    submitted = {_mated_unit_key(search, plan=plan) for search in mated}
    return max(0, len(expected) - len(submitted & expected))


def _nonmated_search_shortfall(
    plan: RunPlan,
    *,
    stratum: str,
    nonmated: Sequence[SearchResult],
    closed_set: bool,
) -> int:
    """How many foil (still, gallery) units are missing from the injected list.

    Closed-set runs declare no foil workload. Open-set FPI is a count against
    the declared gallery (JANUS 2.3.4); a truncated foil set understates it.
    """
    if closed_set or stratum not in PROBE_STRATA:
        return 0
    expected = {
        (entry.media_id, gallery)
        for entry, gallery in _foil_search_units(plan, stratum=stratum)
    }
    submitted = {_foil_unit_key(search, plan=plan) for search in nonmated}
    return max(0, len(expected) - len(submitted & expected))


def _missing_required_probe_searches(
    plan: RunPlan,
    searches: Mapping[str, Mapping[str, Sequence[SearchResult]]],
) -> list[str]:
    missing: list[str] = []
    for name in PROBE_STRATA:
        if _is_exempt_probe_stratum(plan, name):
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
    """Ingest-time identity normalisation (BR-75).

    Applies the same alphabet as ``_normalise_subject_id`` (strip, reject
    non-string / blank-after-strip) at manifest parse, so membership
    (``mated_identities_for``) and the published unique-subject census
    (``strata_join``) see one canonical key per subject instead of
    diverging on unstripped whitespace or a silent ``str()`` coercion. A
    blank or malformed item is rejected here — fail closed at the boundary
    (sr-006) — rather than reaching ``mated_identities_for`` and crashing
    at point of use, or silently dropping a genuine mate.
    """
    value = entry.get("present_identities")
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(
            _normalise_subject_id(item, gallery="present_identities")
            for item in value
        )
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
