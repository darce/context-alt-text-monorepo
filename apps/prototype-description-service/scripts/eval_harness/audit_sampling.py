"""Stratified probability-sample sizing and drawing for DESCQUAL-2 audits.

n is computed from a target margin of error plus the finite-population
correction (AUDIT-09), never as a percent of N. Independent draws per stratum
carry inclusion probabilities (AUDIT-08 / AUDIT-10). Images cluster within
subject, so sizing inflates n0 by the Kish design effect *before* the fpc
(AUDIT-11). FIR-12 ``strata_counts`` values are per-stratum objects; project
image counts before allocate() rather than passing the index through.
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


@dataclass(frozen=True)
class Sample:
    seed: int
    units: tuple[SampledUnit, ...]

    @property
    def unit_ids(self) -> tuple[Hashable, ...]:
        return tuple(unit.unit_id for unit in self.units)


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


@dataclass(frozen=True)
class ClusterSpec:
    """Per-stratum mean cluster size M and ICC for Kish deff (AUDIT-11)."""

    cluster_size: float
    icc: float


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
    if (cluster_size is None) != (icc is None):
        raise AuditSamplingError("cluster_size and icc must be provided together")

    n0 = (z * z) * p * (1.0 - p) / (margin * margin)
    if cluster_size is None:
        deff = 1.0
        n_deff = n0
        order = DeffOrder.FPC_ONLY
    else:
        deff = design_effect(cluster_size=cluster_size, icc=icc)
        n_deff = n0 * deff
        order = DeffOrder.DEFF_THEN_FPC
    n = n_deff / (1.0 + (n_deff - 1.0) / population)
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
    if cluster_size < 1:
        raise AuditSamplingError(f"cluster_size must be >= 1, got {cluster_size!r}")
    if not 0 <= icc <= 1:
        raise AuditSamplingError(f"icc must be in [0, 1], got {icc!r}")
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
    per-stratum (M, ICC) map because mean cluster size differs by cell; omitted
    entries keep today's unclustered floor. Each floor's SampleSize is on the
    returned Allocation so deff, n_eff = n/deff, and ordering can be read back
    (AUDIT-11).
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
    for name, spec in clusters.items():
        if not isinstance(spec, ClusterSpec):
            raise AuditSamplingError(
                f"cluster_params[{name!r}] must be a ClusterSpec, got {type(spec).__name__}"
            )

    assigned = {name: 0 for name in strata_sizes}
    floor_records: dict[str, SampleSize] = {}
    reserved = 0
    for name, margin in floors.items():
        spec = clusters.get(name)
        if spec is None:
            record = size_for_margin(margin=margin, population=strata_sizes[name])
        else:
            record = size_for_margin(
                margin=margin,
                population=strata_sizes[name],
                cluster_size=spec.cluster_size,
                icc=spec.icc,
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
