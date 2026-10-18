"""Open-set 1:N identification: FNIR vs FPI at a fixed score threshold (IET).

Bake-off gate metric, alongside ``face_assignment.open_set_counts_at_tau``.
That scorer optimizes open-set F1 whose precision divides FP by (TP+FP) — a
denominator the system under test produces. This module does not replace it.

EVAL-18: paired FNIR and integer FPI at threshold ``tau``, with an explicit
non-mated search stratum (not CMC / rank-only).
EVAL-19: FPI is a count. Never FPI / n_nonmated. The only optional normalized
false-positive figure is ``IETPoint.fpi_per_enrolled_subject``, whose
denominator is ``n_enrolled_gallery_subjects`` supplied by the caller — fixed
outside the system (enrolled gallery size), not a volume the detector mints.
EVAL-16: a mated probe with ``detected=False`` is an FNIR miss; detection sits
inside the identification error budget.
MLDATA-09: empty mated is an unmeasured cell (``measured=False``, ``fnir=None``),
never FNIR 0.0. FPI stays an integer count and is still reported.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scripts.eval_harness.accept_predicate import is_fnir_miss, is_fpi
from scripts.eval_harness.gallery_split import GalleryName


def _require_finite(value: float, *, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


@dataclass(frozen=True)
class SearchResult:
    """One 1:N search: a (probe image, gallery) pair.

    ``true_name is None`` means the probe is non-mated against ``gallery``.
    Mated-ness is per gallery, not per still — a still enrolled in both
    galleries is two searches (JANUS 2.2 / EVAL-18).
    """

    detected: bool
    top1_score: float | None
    top1_name: str | None
    true_name: str | None
    gallery: GalleryName | str
    media_id: int

    def __post_init__(self) -> None:
        if isinstance(self.media_id, bool) or not isinstance(self.media_id, int):
            raise ValueError(f"media_id must be an int, got {self.media_id!r}")


@dataclass(frozen=True)
class IETPoint:
    """FNIR vs FPI at one score threshold (Identification Error Tradeoff)."""

    tau: float
    fnir: float | None
    fpi: int
    n_mated: int
    n_fnir_misses: int
    n_nonmated: int
    measured: bool
    n_enrolled_gallery_subjects: int | None = None

    def __post_init__(self) -> None:
        if self.measured:
            if self.fnir is None:
                raise ValueError("measured IETPoint requires fnir")
            if self.n_mated <= 0:
                raise ValueError("measured IETPoint requires n_mated > 0")
        else:
            if self.fnir is not None:
                # Unmeasured FNIR must not look like a perfect 0.0 (MLDATA-09).
                raise ValueError("unmeasured IETPoint must not carry an FNIR number")
            if self.n_mated != 0:
                raise ValueError("unmeasured IETPoint requires n_mated == 0")

    @property
    def fpi_per_enrolled_subject(self) -> float | None:
        """FPI divided by enrolled gallery subject count (EVAL-19).

        Denominator is caller-supplied gallery size, not the number of
        non-mated searches the detector emitted. ``None`` when the caller
        omitted ``n_enrolled_gallery_subjects`` or passed a non-positive
        count (empty gallery — no external exposure to normalize against).
        """
        n = self.n_enrolled_gallery_subjects
        if n is None or n <= 0:
            return None
        return self.fpi / n

    def format_fnir(self) -> str:
        """Render FNIR; unmeasured cells are never a number (MLDATA-09)."""
        if not self.measured or self.fnir is None:
            return "not measured"
        return f"{self.fnir:.3f}"


def _is_fnir_miss(search: SearchResult, *, tau: float) -> bool:
    """True when a mated search does not return its mate at or above ``tau``."""
    if search.true_name is None:
        raise ValueError("mated SearchResult requires true_name")
    if not search.detected:
        return True
    if search.top1_score is not None:
        _require_finite(search.top1_score, name="top1_score")
    if search.top1_name is None or search.top1_score is None:
        return True
    return search.top1_name != search.true_name or is_fnir_miss(search.top1_score, tau)


def _is_fpi(search: SearchResult, *, tau: float) -> bool:
    """True when a non-mated search returns rank-1 with score strictly > ``tau``."""
    if search.true_name is not None:
        raise ValueError("nonmated SearchResult requires true_name is None")
    if not search.detected:
        return False
    if search.top1_score is not None:
        _require_finite(search.top1_score, name="top1_score")
    if search.top1_name is None or search.top1_score is None:
        return False
    return is_fpi(search.top1_score, tau)


def fnir_fpi_at_threshold(
    *,
    mated: Sequence[SearchResult],
    nonmated: Sequence[SearchResult],
    tau: float,
    n_enrolled_gallery_subjects: int | None = None,
) -> IETPoint:
    """Paired FNIR and FPI at score threshold ``tau``.

    FNIR: proportion of ``mated`` searches that do not return the mated gallery
    template at or above ``tau``. Undetected mated probes are misses (EVAL-16).
    Empty ``mated`` → ``measured=False``, ``fnir=None`` (MLDATA-09: unmeasured
    is not a perfect score). FPI is still counted.

    FPI: integer count of ``nonmated`` searches returning a rank-1 candidate
    with score > ``tau``. Not a rate over ``len(nonmated)`` (EVAL-19).

    Non-finite ``tau`` or a non-finite ``top1_score`` on a detected search
    raises ``ValueError``: IEEE NaN comparisons are all false, so they would
    otherwise report as a clean measurement (EVAL-18).
    """
    if n_enrolled_gallery_subjects is not None and n_enrolled_gallery_subjects < 0:
        raise ValueError("n_enrolled_gallery_subjects must be >= 0 when provided")
    _require_finite(tau, name="tau")

    n_mated = len(mated)
    n_misses = sum(1 for search in mated if _is_fnir_miss(search, tau=tau))
    measured = n_mated > 0
    fnir: float | None = None if not measured else n_misses / n_mated
    fpi = sum(1 for search in nonmated if _is_fpi(search, tau=tau))
    return IETPoint(
        tau=float(tau),
        fnir=fnir,
        fpi=int(fpi),
        n_mated=n_mated,
        n_fnir_misses=n_misses,
        n_nonmated=len(nonmated),
        measured=measured,
        n_enrolled_gallery_subjects=n_enrolled_gallery_subjects,
    )


def iet_curve(
    *,
    mated: Sequence[SearchResult],
    nonmated: Sequence[SearchResult],
    thresholds: Sequence[float],
    n_enrolled_gallery_subjects: int | None = None,
) -> list[IETPoint]:
    """IET points at each ``thresholds`` value, in the given order."""
    return [
        fnir_fpi_at_threshold(
            mated=mated,
            nonmated=nonmated,
            tau=float(tau),
            n_enrolled_gallery_subjects=n_enrolled_gallery_subjects,
        )
        for tau in thresholds
    ]


__all__ = [
    "SearchResult",
    "IETPoint",
    "fnir_fpi_at_threshold",
    "iet_curve",
]
