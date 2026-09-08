"""Stratified probability-sample sizing and drawing for DESCQUAL-2 audits.

n is computed from a target margin of error plus the finite-population
correction (AUDIT-09), never as a percent of N. Independent image draws per
stratum carry inclusion probabilities (AUDIT-08 / AUDIT-10). Images cluster
within subject, so sizing inflates n0 by the Kish design effect *before* the
fpc (AUDIT-11) using the Kish effective cluster size a = Σ m_i² / Σ m_i, not
the mean. ``size_for_margin`` consumes an ICC; ``estimate_icc`` produces it
(one-way ANOVA + Fisher-Z CI) from a subject-stage draw (``draw_two_stage``).
FIR-12 ``strata_counts`` values are per-stratum objects; project image counts
before allocate() rather than passing the index through. Whole-frame Kish a
for planning n uses ``project_frame_psu_image_counts`` (a genuine PSU
partition of the 640-image frame), not the labeled-subject membership vector.
"""

from __future__ import annotations

import math
import random
from collections.abc import Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

# Conservative Bernoulli variance (AUDIT-09): p=0.5 maximises p(1-p).
_DEFAULT_P = 0.5
# Two-sided 95% normal quantile.
_DEFAULT_Z = 1.96


class AuditSamplingError(ValueError):
    """Invalid sizing, allocation, or draw inputs."""


class DeffOrder(StrEnum):
    """Order of Kish inflation vs finite-population correction (AUDIT-11)."""

    DEFF_THEN_FPC = "deff_then_fpc"
    FPC_ONLY = "fpc_only"


@dataclass(frozen=True)
class SampledUnit:
    unit_id: Hashable
    stratum: str
    inclusion_probability: float
    psu_id: Hashable | None = None


@dataclass(frozen=True)
class Sample:
    seed: int
    units: tuple[SampledUnit, ...]

    @property
    def unit_ids(self) -> tuple[Hashable, ...]:
        return tuple(unit.unit_id for unit in self.units)


@dataclass(frozen=True)
class IccEstimate:
    """One-way ANOVA ICC with Fisher-Z interval (AUDIT-11)."""

    icc: float
    lower: float
    upper: float
    n_psu: int
    n_within: float
    n_obs: int
    msb: float
    msw: float


@dataclass(frozen=True)
class SampleSize:
    """Reproducible sizing record: n0, deff inputs, ordering, and final n."""

    n: int
    n0: float
    n_deff: float
    deff: float
    population: int
    margin: float
    p: float
    z: float
    deff_order: DeffOrder
    cluster_size: float | None = None
    icc: float | None = None


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


@dataclass(frozen=True)
class ClusterSpec:
    """Per-stratum Kish effective cluster size a and ICC for Kish deff (AUDIT-11)."""

    # 1+(M−1)·ICC is the equal-size form, so an unequal-size frame must
    # supply a = Σ m_i² / Σ m_i, not the arithmetic mean.
    cluster_size: float
    icc: float

    def __post_init__(self) -> None:
        if not _finite_number(self.cluster_size) or self.cluster_size < 1:
            raise AuditSamplingError(
                f"cluster_size must be a finite number >= 1, got {self.cluster_size!r}"
            )
        if not _finite_number(self.icc) or not 0 <= self.icc <= 1:
            raise AuditSamplingError(
                f"icc must be a finite number in [0, 1], got {self.icc!r}"
            )


@dataclass(frozen=True)
class Allocation(Mapping[str, int]):
    """Per-stratum n_h; ``floors`` is the SampleSize that sized each precision floor."""

    counts: Mapping[str, int]
    floors: Mapping[str, SampleSize]

    def __post_init__(self) -> None:
        from types import MappingProxyType

        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))
        object.__setattr__(self, "floors", MappingProxyType(dict(self.floors)))

    def __hash__(self) -> int:
        return hash(
            (tuple(sorted(self.counts.items())), tuple(sorted(self.floors.items())))
        )

    def __getitem__(self, key: str) -> int:
        return self.counts[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.counts)

    def __len__(self) -> int:
        return len(self.counts)


def project_strata_image_counts(
    strata_counts: Mapping[str, object],
) -> dict[str, int]:
    """Project FIR-12 ``strata_counts[k]["images"]`` into allocate() sizes.

    The frozen frame stores per-stratum objects, not ints. allocate() takes
    image counts; this adapter is the only supported conversion (rg-015).
    """
    if not strata_counts:
        raise AuditSamplingError("strata_counts must be non-empty")
    sizes: dict[str, int] = {}
    for name, row in strata_counts.items():
        if not isinstance(row, Mapping):
            raise AuditSamplingError(
                f"strata_counts[{name!r}] must be an object with 'images', "
                f"got {type(row).__name__}"
            )
        if "images" not in row:
            raise AuditSamplingError(f"strata_counts[{name!r}] missing 'images'")
        images = row["images"]
        if isinstance(images, bool) or not isinstance(images, int) or images < 0:
            raise AuditSamplingError(
                f"strata_counts[{name!r}]['images'] must be a non-negative int, "
                f"got {images!r}"
            )
        sizes[name] = images
    return sizes


@dataclass(frozen=True)
class WholeFrameSubjectCounts:
    """Per-subject image counts with identities joined across strata (AUDIT-11).

    Concatenating per-stratum vectors from ``project_strata_subject_image_counts``
    splits a subject who appears in two strata into two clusters and understates
    Kish a. This object is the whole-frame join.
    """

    sizes: tuple[int, ...]
    n_entries: int
    n_unlabeled: int
    n_multi_identity_images: int
    extra_memberships: int


@dataclass(frozen=True)
class FramePsuPartition:
    """Image-level PSU partition of a selection frame (AUDIT-11).

    PSU = first-listed ``present_identities`` name, else an unlabeled
    singleton keyed by ``media_id``. ``sum(sizes) == n_entries`` is a
    partition invariant, not a test-only assertion.
    """

    sizes: tuple[int, ...]
    n_entries: int
    n_psus: int
    n_unlabeled_singletons: int
    never_first_identities: tuple[str, ...]

    def __post_init__(self) -> None:
        if sum(self.sizes) != self.n_entries:
            raise AuditSamplingError(
                "PSU sizes must partition the frame: "
                f"sum(sizes)={sum(self.sizes)} != n_entries={self.n_entries}"
            )
        if self.n_psus != len(self.sizes):
            raise AuditSamplingError(
                f"n_psus={self.n_psus} != len(sizes)={len(self.sizes)}"
            )


def _parse_media_id(entry: Mapping[object, object], index: int) -> Hashable:
    if "media_id" not in entry:
        raise AuditSamplingError(f"entries[{index}] missing 'media_id'")
    media_id = entry["media_id"]
    if isinstance(media_id, bool) or not isinstance(media_id, (int, str)):
        raise AuditSamplingError(
            f"entries[{index}]['media_id'] must be a non-bool int or str, "
            f"got {media_id!r}"
        )
    if isinstance(media_id, str) and not media_id:
        raise AuditSamplingError(
            f"entries[{index}]['media_id'] must be a non-empty str, "
            f"got {media_id!r}"
        )
    return media_id


def _parse_selection_entries(
    entries: Sequence[object],
) -> list[tuple[str, Hashable, tuple[str, ...]]]:
    """Return (stratum, media_id, unique identities) per entry; empty identities stay."""
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise AuditSamplingError(
            "entries must be a sequence of objects, "
            f"got {type(entries).__name__}"
        )
    if not entries:
        raise AuditSamplingError("entries must be non-empty")
    parsed: list[tuple[str, Hashable, tuple[str, ...]]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise AuditSamplingError(
                f"entries[{index}] must be an object with 'stratum', "
                f"'present_identities', and 'media_id', got {type(entry).__name__}"
            )
        if "stratum" not in entry:
            raise AuditSamplingError(f"entries[{index}] missing 'stratum'")
        stratum = entry["stratum"]
        if not isinstance(stratum, str) or not stratum:
            raise AuditSamplingError(
                f"entries[{index}]['stratum'] must be a non-empty str, "
                f"got {stratum!r}"
            )
        if "present_identities" not in entry:
            raise AuditSamplingError(f"entries[{index}] missing 'present_identities'")
        identities = entry["present_identities"]
        if isinstance(identities, (str, bytes)) or not isinstance(identities, Sequence):
            raise AuditSamplingError(
                f"entries[{index}]['present_identities'] must be a sequence of "
                f"names, got {type(identities).__name__}"
            )
        seen: set[str] = set()
        unique: list[str] = []
        for identity in identities:
            if not isinstance(identity, str) or not identity:
                raise AuditSamplingError(
                    f"entries[{index}]['present_identities'] items must be "
                    f"non-empty str, got {identity!r}"
                )
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(identity)
        parsed.append((stratum, _parse_media_id(entry, index), tuple(unique)))
    return parsed


def project_strata_subject_image_counts(
    entries: Sequence[object],
) -> dict[str, tuple[int, ...]]:
    """Project selection-manifest entries into per-stratum per-subject image counts.

    Each entry contributes one image to every named identity in its stratum.
    The resulting size vector is the Kish-a input for that cell (AUDIT-11).
    """
    counts: dict[str, dict[str, int]] = {}
    for stratum, _media_id, identities in _parse_selection_entries(entries):
        # Empty present_identities are not subject-clustered; they contribute
        # no cluster. Dropping them is the design, not a silent skip bug.
        for identity in identities:
            cell = counts.setdefault(stratum, {})
            cell[identity] = cell.get(identity, 0) + 1
    return {
        stratum: tuple(cell[name] for name in sorted(cell))
        for stratum, cell in counts.items()
    }


def project_whole_frame_subject_image_counts(
    entries: Sequence[object],
) -> WholeFrameSubjectCounts:
    """Join the same identity across strata into one cluster per subject.

    The whole-frame Kish a is Σ m_i² / Σ m_i over this joined size vector.
    """
    counts: dict[str, int] = {}
    n_unlabeled = 0
    n_multi = 0
    extra = 0
    parsed = _parse_selection_entries(entries)
    for _stratum, _media_id, identities in parsed:
        if not identities:
            n_unlabeled += 1
            continue
        if len(identities) > 1:
            n_multi += 1
            extra += len(identities) - 1
        for identity in identities:
            counts[identity] = counts.get(identity, 0) + 1
    return WholeFrameSubjectCounts(
        sizes=tuple(counts[name] for name in sorted(counts)),
        n_entries=len(parsed),
        n_unlabeled=n_unlabeled,
        n_multi_identity_images=n_multi,
        extra_memberships=extra,
    )


def project_frame_psu_image_counts(
    entries: Sequence[object],
) -> FramePsuPartition:
    """Assign each image to exactly one PSU of the frame being sized.

    Non-empty ``present_identities`` → PSU = the first-listed identity.
    Empty ``present_identities`` → singleton PSU ``unlabeled:{media_id}``.
    Extra memberships are not a second cluster. Unlabeled images stay in N.
    """
    parsed = _parse_selection_entries(entries)
    counts: dict[str, int] = {}
    all_identities: set[str] = set()
    first_listed: set[str] = set()
    n_unlabeled = 0
    for _stratum, media_id, identities in parsed:
        all_identities.update(identities)
        if not identities:
            n_unlabeled += 1
            key = f"unlabeled:{media_id}"
            counts[key] = counts.get(key, 0) + 1
            continue
        first = identities[0]
        first_listed.add(first)
        counts[first] = counts.get(first, 0) + 1
    sizes = tuple(counts[name] for name in sorted(counts))
    return FramePsuPartition(
        sizes=sizes,
        n_entries=len(parsed),
        n_psus=len(sizes),
        n_unlabeled_singletons=n_unlabeled,
        never_first_identities=tuple(sorted(all_identities - first_listed)),
    )


def kish_effective_cluster_size(sizes: Sequence[int | float]) -> float:
    """Kish effective cluster size a = Σ m_i² / Σ m_i from per-cluster sizes."""
    if not sizes:
        raise AuditSamplingError("cluster sizes must be non-empty")
    total = 0.0
    sum_sq = 0.0
    for index, raw in enumerate(sizes):
        if not _finite_number(raw) or raw <= 0:
            raise AuditSamplingError(
                f"cluster sizes[{index}] must be a finite number > 0, got {raw!r}"
            )
        m = float(raw)
        total += m
        sum_sq += m * m
    return sum_sq / total


def sample_size_for_margin(
    *,
    margin: float,
    population: int,
    p: float = _DEFAULT_P,
    z: float = _DEFAULT_Z,
) -> int:
    """SRS-of-proportion n from margin of error, with finite-population correction.

    n0 = z² p (1-p) / e², then n = n0 / (1 + (n0 - 1) / N), rounded up.
    """
    return size_for_margin(margin=margin, population=population, p=p, z=z).n


def size_for_margin(
    *,
    margin: float,
    population: int,
    p: float = _DEFAULT_P,
    z: float = _DEFAULT_Z,
    cluster_size: float | None = None,
    icc: float | None = None,
) -> SampleSize:
    """Size n from margin of error; apply Kish deff to n0 *before* the fpc."""
    if not 0 < margin:
        raise AuditSamplingError(f"margin must be > 0, got {margin!r}")
    if population < 1:
        raise AuditSamplingError(f"population must be >= 1, got {population!r}")
    if not 0 < p < 1:
        raise AuditSamplingError(f"p must be in (0, 1), got {p!r}")
    if z <= 0:
        raise AuditSamplingError(f"z must be > 0, got {z!r}")

    n0 = (z * z) * p * (1.0 - p) / (margin * margin)
    if cluster_size is None and icc is None:
        deff = 1.0
        n_deff = n0
        order = DeffOrder.FPC_ONLY
    elif cluster_size is not None and icc is not None:
        # Post-pilot the honest path is deff = V̂_cluster / V̂_SRS from the
        # draw, which already folds in unequal sizes, rather than any M.
        deff = design_effect(cluster_size=cluster_size, icc=icc)
        n_deff = n0 * deff
        order = DeffOrder.DEFF_THEN_FPC
    else:
        raise AuditSamplingError("cluster_size and icc must be provided together")
    n = n_deff / (1.0 + (n_deff - 1.0) / population)
    if not math.isfinite(n_deff) or not math.isfinite(n):
        raise AuditSamplingError(
            "computed sample size is non-finite; "
            f"n_deff={n_deff!r} n={n!r} cluster_size={cluster_size!r} icc={icc!r}"
        )
    return SampleSize(
        n=min(population, math.ceil(n)),
        n0=n0,
        n_deff=n_deff,
        deff=deff,
        population=population,
        margin=margin,
        p=p,
        z=z,
        deff_order=order,
        cluster_size=cluster_size,
        icc=icc,
    )


def design_effect(*, cluster_size: float, icc: float) -> float:
    """Kish design effect: 1 + (M − 1) × ICC (AUDIT-11)."""
    if not _finite_number(cluster_size) or cluster_size < 1:
        raise AuditSamplingError(
            f"cluster_size must be a finite number >= 1, got {cluster_size!r}"
        )
    if not _finite_number(icc) or not 0 <= icc <= 1:
        raise AuditSamplingError(f"icc must be a finite number in [0, 1], got {icc!r}")
    return 1.0 + (cluster_size - 1.0) * icc


def allocate(
    *,
    strata_sizes: Mapping[str, int],
    n: int,
    precision_floors: Mapping[str, float] | None = None,
    cluster_params: Mapping[str, ClusterSpec] | None = None,
) -> Allocation:
    """Allocate n across strata; proportional default, disproportional for floors.

    A precision floor is a per-stratum target margin: that stratum is sized from
    ``size_for_margin`` against its own N_h, and the remainder of n is allocated
    proportionally to the other strata (AUDIT-10). ``cluster_params`` is a
    per-stratum (a, ICC) map because Kish effective cluster size differs by
    cell; omitted keys keep the unclustered floor. Every ``cluster_params`` key
    must name a precision floor — a spec with no floor would silently no-op.
    ``cluster_params=None`` stays deff-blind (ICC is measured, not assumed).
    Each floor's SampleSize is on the returned Allocation so deff, n_eff =
    n/deff, and ordering can be read back (AUDIT-11).
    """
    if n < 0:
        raise AuditSamplingError(f"n must be >= 0, got {n!r}")
    if not strata_sizes:
        raise AuditSamplingError("strata_sizes must be non-empty")
    for name, size in strata_sizes.items():
        if isinstance(size, bool) or not isinstance(size, int):
            raise AuditSamplingError(
                f"stratum {name!r} size must be an int image count; "
                f"project strata_counts via project_strata_image_counts(), got {size!r}"
            )
        if size < 0:
            raise AuditSamplingError(f"stratum {name!r} size must be >= 0, got {size!r}")

    total_n = sum(strata_sizes.values())
    if total_n == 0:
        if n > 0:
            raise AuditSamplingError("cannot allocate n>0 across empty strata")
        return Allocation(counts={name: 0 for name in strata_sizes}, floors={})

    target = min(n, total_n)
    floors = dict(precision_floors or {})
    unknown = set(floors) - set(strata_sizes)
    if unknown:
        raise AuditSamplingError(f"precision_floors name unknown strata: {sorted(unknown)}")

    clusters = dict(cluster_params or {})
    unknown_clusters = set(clusters) - set(strata_sizes)
    if unknown_clusters:
        raise AuditSamplingError(
            f"cluster_params name unknown strata: {sorted(unknown_clusters)}"
        )
    for name, cluster in clusters.items():
        if not isinstance(cluster, ClusterSpec):
            raise AuditSamplingError(
                f"cluster_params[{name!r}] must be a ClusterSpec, got {type(cluster).__name__}"
            )
    unfloored_clusters = set(clusters) - set(floors)
    if unfloored_clusters:
        raise AuditSamplingError(
            "cluster_params name strata with no precision floor: "
            f"{sorted(unfloored_clusters)}"
        )

    assigned = {name: 0 for name in strata_sizes}
    floor_records: dict[str, SampleSize] = {}
    reserved = 0
    for name, margin in floors.items():
        floor_spec = clusters.get(name)
        if floor_spec is None:
            record = size_for_margin(margin=margin, population=strata_sizes[name])
        else:
            record = size_for_margin(
                margin=margin,
                population=strata_sizes[name],
                cluster_size=floor_spec.cluster_size,
                icc=floor_spec.icc,
            )
        n_h = min(record.n, strata_sizes[name])
        assigned[name] = n_h
        floor_records[name] = record
        reserved += n_h
    if reserved > target:
        raise AuditSamplingError(
            f"precision floors require n>={reserved}, got n={target}"
        )

    leftover = target - reserved
    remainder_keys = [name for name in strata_sizes if name not in floors]
    leftover = _pour(assigned, leftover, {k: strata_sizes[k] for k in remainder_keys})
    if leftover:
        capacity = {k: strata_sizes[k] - assigned[k] for k in strata_sizes}
        leftover = _pour(assigned, leftover, capacity)
    if leftover:
        raise AuditSamplingError(f"unable to place {leftover} leftover units")
    return Allocation(counts=assigned, floors=floor_records)


def _pour(assigned: dict[str, int], leftover: int, weights: Mapping[str, int]) -> int:
    """Place leftover units by largest-remainder; return any still unplaced."""
    if leftover <= 0 or not weights:
        return leftover
    extra = _largest_remainder(weights=weights, n=leftover)
    placed = 0
    for name, count in extra.items():
        assigned[name] = assigned.get(name, 0) + count
        placed += count
    return leftover - placed


def _largest_remainder(*, weights: Mapping[str, int], n: int) -> dict[str, int]:
    """Hamilton allocation of n, capped at each weight (stratum size / capacity)."""
    positive = {name: weight for name, weight in weights.items() if weight > 0}
    result = {name: 0 for name in weights}
    if not positive or n <= 0:
        return result
    cap = min(n, sum(positive.values()))
    total_w = sum(positive.values())
    quotas = {name: cap * weight / total_w for name, weight in positive.items()}
    for name, weight in positive.items():
        result[name] = min(weight, math.floor(quotas[name]))
    remaining = cap - sum(result[name] for name in positive)
    order = sorted(positive, key=lambda name: (-(quotas[name] - math.floor(quotas[name])), name))
    for name in order:
        if remaining <= 0:
            break
        if result[name] < positive[name]:
            result[name] += 1
            remaining -= 1
    return result


def draw(
    *,
    strata_members: Mapping[str, Sequence[Hashable]],
    allocation: Mapping[str, int],
    seed: int,
) -> Sample:
    """Independent SRS without replacement per stratum; each unit carries π_h = n_h / N_h.

    There is no convenience / first-n path: a design-based interval is only valid
    when inclusion probabilities are known before the draw (AUDIT-08).
    """
    members = {name: list(units) for name, units in strata_members.items()}
    _check_frame(members, allocation)

    rng = random.Random(seed)
    selected: list[SampledUnit] = []
    for stratum in sorted(members):
        n_h = allocation.get(stratum, 0)
        if n_h <= 0:
            continue
        frame = _ordered_unique(members[stratum])
        drawn = rng.sample(frame, n_h)
        pi_h = n_h / len(frame)
        selected.extend(
            SampledUnit(unit_id=unit_id, stratum=stratum, inclusion_probability=pi_h)
            for unit_id in drawn
        )
    return Sample(seed=seed, units=tuple(selected))


def draw_two_stage(
    *,
    clusters: Mapping[Hashable, Sequence[Hashable]],
    n_psu: int,
    n_within: int,
    seed: int,
) -> Sample:
    """SRS of subject PSUs, then SRS of n_within images inside each drawn PSU.

    Image-level ``draw`` cannot estimate a subject-clustered ICC: an n=30
    SRS is almost all singletons. n_within must be >= 2 so each drawn PSU
    carries replicates (AUDIT-11).
    """
    if not isinstance(clusters, Mapping) or isinstance(clusters, (str, bytes)):
        raise AuditSamplingError(
            f"clusters must be a mapping of PSU id -> units, got {type(clusters).__name__}"
        )
    if not clusters:
        raise AuditSamplingError("clusters must be non-empty")
    if isinstance(n_psu, bool) or not isinstance(n_psu, int) or n_psu < 1:
        raise AuditSamplingError(f"n_psu must be an int >= 1, got {n_psu!r}")
    if isinstance(n_within, bool) or not isinstance(n_within, int) or n_within < 2:
        raise AuditSamplingError(f"n_within must be >= 2, got {n_within!r}")

    frames: dict[Hashable, list[Hashable]] = {}
    for psu_id, units in clusters.items():
        if isinstance(units, (str, bytes)) or not isinstance(units, Sequence):
            raise AuditSamplingError(
                f"clusters[{psu_id!r}] must be a sequence of unit ids, "
                f"got {type(units).__name__}"
            )
        frame = _ordered_unique(units)
        if len(frame) != len(list(units)):
            raise AuditSamplingError(f"PSU {psu_id!r} has duplicate unit ids")
        if len(frame) < n_within:
            raise AuditSamplingError(
                f"PSU {psu_id!r} has m={len(frame)} < n_within={n_within}"
            )
        frames[psu_id] = frame

    psu_ids = _ordered_unique(list(frames))
    if n_psu > len(psu_ids):
        raise AuditSamplingError(
            f"n_psu={n_psu} exceeds number of clusters N={len(psu_ids)}"
        )

    rng = random.Random(seed)
    drawn_psus = rng.sample(psu_ids, n_psu)
    pi_psu = n_psu / len(psu_ids)
    selected: list[SampledUnit] = []
    for psu_id in drawn_psus:
        frame = frames[psu_id]
        drawn_units = rng.sample(frame, n_within)
        pi = pi_psu * (n_within / len(frame))
        selected.extend(
            SampledUnit(
                unit_id=unit_id,
                stratum="frame",
                inclusion_probability=pi,
                psu_id=psu_id,
            )
            for unit_id in drawn_units
        )
    return Sample(seed=seed, units=tuple(selected))


def estimate_icc(
    clusters: Sequence[Sequence[float]],
    *,
    z: float = _DEFAULT_Z,
) -> IccEstimate:
    """One-way random-effects ANOVA ICC with Fisher-Z 95% CI (AUDIT-11).

    Balanced k: ICC = (MSB − MSW) / (MSB + (k − 1) MSW). Unbalanced uses
    n0 in place of k. The interval is Fisher's ICC transform, not artanh(ρ).
    """
    if isinstance(clusters, (str, bytes)) or not isinstance(clusters, Sequence):
        raise AuditSamplingError(
            f"clusters must be a sequence of observation groups, "
            f"got {type(clusters).__name__}"
        )
    if not clusters:
        raise AuditSamplingError("clusters must be non-empty")
    groups: list[list[float]] = []
    for index, raw in enumerate(clusters):
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise AuditSamplingError(
                f"clusters[{index}] must be a sequence of numbers, "
                f"got {type(raw).__name__}"
            )
        if len(raw) < 2:
            raise AuditSamplingError(
                f"each cluster must have at least 2 observations, "
                f"clusters[{index}] has {len(raw)}"
            )
        group: list[float] = []
        for inner, value in enumerate(raw):
            if not _finite_number(value):
                raise AuditSamplingError(
                    f"clusters[{index}][{inner}] must be a finite number, "
                    f"got {value!r}"
                )
            group.append(float(value))
        groups.append(group)
    n_psu = len(groups)
    if n_psu <= 2:
        raise AuditSamplingError(f"Fisher-Z ICC CI requires n_psu > 2, got {n_psu}")
    if not _finite_number(z) or z <= 0:
        raise AuditSamplingError(f"z must be > 0, got {z!r}")

    n_i = [len(group) for group in groups]
    n_obs = sum(n_i)
    grand = sum(sum(group) for group in groups) / n_obs
    means = [sum(group) / len(group) for group in groups]
    ssb = sum(n * (mean - grand) ** 2 for n, mean in zip(n_i, means))
    ssw = sum(
        (value - mean) ** 2 for group, mean in zip(groups, means) for value in group
    )
    msb = ssb / (n_psu - 1)
    msw = ssw / (n_obs - n_psu)
    if all(n == n_i[0] for n in n_i):
        k = float(n_i[0])
    else:
        k = (n_obs - sum(n * n for n in n_i) / n_obs) / (n_psu - 1)
    denom = msb + (k - 1.0) * msw
    if denom == 0.0:
        raise AuditSamplingError("ICC is undefined when MSB and MSW are both 0")
    icc = (msb - msw) / denom
    if msw == 0.0 and msb > 0.0:
        lower, upper = 1.0, 1.0
        icc = 1.0
    else:
        lower, upper = _fisher_z_icc_interval(icc, n_psu=n_psu, k=k, z=z)
    return IccEstimate(
        icc=icc,
        lower=lower,
        upper=upper,
        n_psu=n_psu,
        n_within=k,
        n_obs=n_obs,
        msb=msb,
        msw=msw,
    )


def _fisher_z_icc_interval(
    icc: float, *, n_psu: int, k: float, z: float
) -> tuple[float, float]:
    """Invert Fisher's ICC z = (1/2) log((1+(k−1)ρ)/(1−ρ)); SE = √(k / (2(G−2)(k−1)))."""
    lo_bound = -1.0 / (k - 1.0)
    span = 1.0 - lo_bound
    eps = max(1e-12, span * 1e-12)
    rho = min(1.0 - eps, max(lo_bound + eps, icc))
    transformed = 0.5 * math.log((1.0 + (k - 1.0) * rho) / (1.0 - rho))
    se = math.sqrt(k / (2.0 * (n_psu - 2.0) * (k - 1.0)))

    def _invert(value: float) -> float:
        exponential = math.exp(2.0 * value)
        return (exponential - 1.0) / (exponential + k - 1.0)

    return _invert(transformed - z * se), _invert(transformed + z * se)


def _check_frame(
    members: Mapping[str, list[Hashable]],
    allocation: Mapping[str, int],
) -> None:
    unknown = set(allocation) - set(members)
    if unknown:
        raise AuditSamplingError(f"allocation names unknown strata: {sorted(unknown)}")
    seen: set[Hashable] = set()
    for stratum, units in members.items():
        n_h = allocation.get(stratum, 0)
        if n_h < 0:
            raise AuditSamplingError(f"allocation[{stratum!r}] must be >= 0, got {n_h!r}")
        unique = _ordered_unique(units)
        if len(unique) != len(units):
            raise AuditSamplingError(f"stratum {stratum!r} has duplicate unit ids")
        clash = seen.intersection(unique)
        if clash:
            raise AuditSamplingError(f"unit ids appear in multiple strata: {sorted(clash, key=repr)}")
        seen.update(unique)
        if n_h > len(unique):
            raise AuditSamplingError(
                f"allocation[{stratum!r}]={n_h} exceeds N_h={len(unique)}"
            )


def _ordered_unique(units: Sequence[Hashable]) -> list[Hashable]:
    """Stable unique list; sort when items are mutually comparable so frame order cannot bias the draw."""
    seen: set[Hashable] = set()
    unique: list[Hashable] = []
    for unit in units:
        if unit in seen:
            continue
        seen.add(unit)
        unique.append(unit)
    try:
        return sorted(unique)  # type: ignore[type-var]
    except TypeError:
        return unique
