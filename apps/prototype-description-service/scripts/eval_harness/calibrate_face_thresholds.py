#!/usr/bin/env python3
"""Calibrate face_pipeline thresholds from a pinned face_bakeoff report (FIR-6 S3a).

Pure artifact→artifact CLI: consumes a face_bakeoff schema-v1 report (FIR-5
serialization shape from report.py) plus a golden manifest (for per-media
stratum tags), applies the pair-level subject-disjoint K-fold protocol
([CAL-07]), and emits a deterministic calibration artifact (per-stratum
proposed thresholds + FNMR-tax table + protocol disclosure). Never writes
recognition settings.

FIR-5 decision contract notes:
- ``s_max`` is float|null; null encodes -inf / no gallery match.
- ``name_star`` is null iff ``s_max`` is null (no gallery match couples both).
- ``excluded_single_face_recall`` rows are excluded from FIR-5 recall and from
  calibration trials (EVAL-08 parity).
- Decision rows carry ``publishable`` (bool) from the FIR-5 serializer; the
  flag is required for schema parity and ignored for threshold math.

Usage (from apps/prototype-description-service)::

    uv run python -m scripts.eval_harness.calibrate_face_thresholds \\
        --report path/to/face_bakeoff_report.json \\
        --manifest path/to/golden.json \\
        --out path/to/calibration.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.eval_harness.accept_predicate import is_fnir_miss, is_fpi

# Pinned face_bakeoff report schema v1 (FIR-5 report.py serialization; LC-06/GR-08).
REPORT_KIND = "face_bakeoff"
REPORT_SCHEMA = "acx-eval/v1"
REPORT_DOC_KIND = "report"
REQUIRED_REPORT_KEYS = frozenset(
    {
        "schema",
        "kind",
        "report_kind",
        "provenance",
        "counts",
        "tau",
        "detection",
        "slices",
        "gate_proposal",
        "decisions",
        "failures",
    }
)
REQUIRED_TAU_KEYS = frozenset({"tau_k", "tau_op"})
REQUIRED_DECISION_KEYS = frozenset(
    {
        "media_id",
        "path",
        "box_index",
        "det_index",
        "true_name",
        "predicted_name",
        "decision",
        "s_max",
        "fold",
        "name_star",
        "enrolled",
        "tau_k",
        "excluded_single_face_recall",
        "publishable",
    }
)
# Pre-registered threshold-selection rule id (fit folds only; never re-tuned on read).
SELECTION_RULE_ID = "min_tau_at_fmr_le"
DEFAULT_FMR_TARGET = 0.01
GLOBAL_STRATUM = "_global"
ARTIFACT_KIND = "face_threshold_calibration"
ARTIFACT_SCHEMA_VERSION = 1
# No-match sentinel for s_max:null (FIR-5 serializes -inf as JSON null).
S_MAX_NO_MATCH = float("-inf")


class CalibrationError(Exception):
    """Fail-fast validation or protocol error (non-zero CLI exit)."""


@dataclass(frozen=True)
class Decision:
    media_id: int
    path: str
    box_index: int
    det_index: int
    true_name: str | None
    predicted_name: str | None
    decision: str
    s_max: float  # may be -inf when JSON null
    fold: int
    name_star: str | None
    enrolled: bool
    tau_k: float
    excluded_single_face_recall: bool
    publishable: bool


@dataclass(frozen=True)
class ScoreTrial:
    """One genuine or impostor trial used for threshold fit / OOF read."""

    score: float
    probe_identity: str | None  # None => anonymous stranger
    gallery_identity: str | None  # mate or name_star
    fold: int
    media_id: int
    strata: tuple[str, ...]
    is_genuine: bool


# ---------------------------------------------------------------------------
# Validation (fail-fast, missing keys ⇒ non-zero exit)
# ---------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_s_max(value: object) -> bool:
    """s_max is a finite number or null (-inf / no-match)."""
    if value is None:
        return True
    return _is_number(value)


def validate_face_bakeoff_report(doc: object) -> list[str]:
    """Return schema-violation messages; empty list means ok.

    Required keys match the FIR-5 face_bakeoff serialization in report.py
    (top-level envelope + decision row keys). Truncated / hand-invented shapes fail.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["report must be a JSON object"]

    missing = sorted(REQUIRED_REPORT_KEYS - doc.keys())
    if missing:
        errors.append(f"report missing required keys: {missing}")
        return errors

    if doc.get("schema") != REPORT_SCHEMA:
        errors.append(f"schema must be {REPORT_SCHEMA!r}, got {doc.get('schema')!r}")
    if doc.get("kind") != REPORT_DOC_KIND:
        errors.append(f"kind must be {REPORT_DOC_KIND!r}, got {doc.get('kind')!r}")
    if doc.get("report_kind") != REPORT_KIND:
        errors.append(f"report_kind must be {REPORT_KIND!r}, got {doc.get('report_kind')!r}")

    if not isinstance(doc.get("provenance"), dict):
        errors.append("provenance must be an object")
    if not isinstance(doc.get("detection"), dict):
        errors.append("detection must be an object")
    if not isinstance(doc.get("gate_proposal"), dict):
        errors.append("gate_proposal must be an object")
    if not isinstance(doc.get("failures"), list):
        errors.append("failures must be a list")

    tau = doc.get("tau")
    if not isinstance(tau, dict):
        errors.append("tau must be an object")
    else:
        missing_tau = sorted(REQUIRED_TAU_KEYS - tau.keys())
        if missing_tau:
            errors.append(f"tau missing required keys: {missing_tau}")
        else:
            tau_k = tau.get("tau_k")
            if not isinstance(tau_k, list) or not tau_k:
                errors.append("tau.tau_k must be a non-empty list of floats")
            elif not all(_is_number(x) for x in tau_k):
                errors.append("tau.tau_k entries must be finite numbers")
            if not _is_number(tau.get("tau_op")):
                errors.append("tau.tau_op must be a finite number")

    slices = doc.get("slices")
    if not isinstance(slices, dict):
        errors.append("slices must be an object mapping stratum -> metrics")
    else:
        for name, metrics in slices.items():
            if not isinstance(name, str) or not name:
                errors.append("slices keys must be non-empty strings")
            if not isinstance(metrics, dict):
                errors.append(f"slices[{name!r}] must be an object")

    decisions = doc.get("decisions")
    if not isinstance(decisions, list):
        errors.append("decisions must be a list")
    else:
        for i, row in enumerate(decisions):
            if not isinstance(row, dict):
                errors.append(f"decisions[{i}] must be an object")
                continue
            missing_d = sorted(REQUIRED_DECISION_KEYS - row.keys())
            if missing_d:
                errors.append(f"decisions[{i}] missing keys: {missing_d}")
                continue
            if not isinstance(row["media_id"], int) or isinstance(row["media_id"], bool):
                errors.append(f"decisions[{i}].media_id must be an int")
            if not isinstance(row["path"], str):
                errors.append(f"decisions[{i}].path must be a string")
            if not isinstance(row["box_index"], int) or isinstance(row["box_index"], bool):
                errors.append(f"decisions[{i}].box_index must be an int")
            if not isinstance(row["det_index"], int) or isinstance(row["det_index"], bool):
                errors.append(f"decisions[{i}].det_index must be an int")
            for name_key in ("true_name", "predicted_name", "name_star"):
                val = row[name_key]
                if val is not None and not isinstance(val, str):
                    errors.append(f"decisions[{i}].{name_key} must be str or null")
            if not isinstance(row["decision"], str):
                errors.append(f"decisions[{i}].decision must be a string")
            if not _is_s_max(row["s_max"]):
                errors.append(
                    f"decisions[{i}].s_max must be a finite number or null (-inf/no-match)"
                )
            if not isinstance(row["fold"], int) or isinstance(row["fold"], bool) or row["fold"] < 0:
                errors.append(f"decisions[{i}].fold must be a non-negative int")
            if not isinstance(row["enrolled"], bool):
                errors.append(f"decisions[{i}].enrolled must be a bool")
            if not isinstance(row["excluded_single_face_recall"], bool):
                errors.append(f"decisions[{i}].excluded_single_face_recall must be a bool")
            if not isinstance(row["publishable"], bool):
                errors.append(f"decisions[{i}].publishable must be a bool")
            if not _is_number(row["tau_k"]):
                errors.append(f"decisions[{i}].tau_k must be a finite number")
            # name_star/s_max coupling: null s_max ⇔ no gallery match ⇒ name_star null.
            name_star_val = row.get("name_star")
            name_star_present = isinstance(name_star_val, str) and name_star_val != ""
            if row["s_max"] is None and name_star_present:
                errors.append(
                    f"decisions[{i}]: s_max null (no match) requires name_star null "
                    "(and name_star set requires finite s_max)"
                )

    counts = doc.get("counts")
    if not isinstance(counts, dict):
        errors.append("counts must be an object")

    return errors


def validate_golden_manifest(doc: object) -> list[str]:
    """Schema-validate the golden manifest for stratum join (fail-fast)."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["manifest must be a JSON object"]
    if "entries" not in doc:
        return ["manifest missing required key: entries"]
    entries = doc["entries"]
    if not isinstance(entries, list) or not entries:
        return ["manifest.entries must be a non-empty list"]

    seen_ids: set[int] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{i}] must be an object")
            continue
        if "media_id" not in entry:
            errors.append(f"entries[{i}] missing media_id")
            continue
        mid = entry["media_id"]
        if not isinstance(mid, int) or isinstance(mid, bool) or mid < 1:
            errors.append(f"entries[{i}].media_id must be an int >= 1")
            continue
        if mid in seen_ids:
            errors.append(f"duplicate media_id {mid}")
        seen_ids.add(mid)
        # Stratum tags: domain (single) and/or tags (list). At least one surface
        # is required so the join is never silently empty (rg-008).
        domain = entry.get("domain")
        tags = entry.get("tags")
        has_domain = isinstance(domain, str) and bool(domain.strip())
        has_tags = isinstance(tags, list) and any(isinstance(t, str) and t.strip() for t in tags)
        if not has_domain and not has_tags:
            errors.append(
                f"entries[{i}] (media_id={mid}) needs domain and/or non-empty tags for stratum join"
            )
        if domain is not None and not isinstance(domain, str):
            errors.append(f"entries[{i}].domain must be a string when present")
        if tags is not None:
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                errors.append(f"entries[{i}].tags must be a list of strings when present")
    return errors


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CalibrationError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CalibrationError(f"invalid JSON in {path}: {exc}") from exc


def parse_decisions(doc: Mapping[str, Any]) -> list[Decision]:
    out: list[Decision] = []
    for row in doc["decisions"]:
        true_name = row["true_name"]
        if isinstance(true_name, str) and true_name == "":
            true_name = None
        predicted = row["predicted_name"]
        if isinstance(predicted, str) and predicted == "":
            predicted = None
        name_star = row["name_star"]
        if isinstance(name_star, str) and name_star == "":
            name_star = None
        raw_s_max = row["s_max"]
        s_max = S_MAX_NO_MATCH if raw_s_max is None else float(raw_s_max)
        out.append(
            Decision(
                media_id=int(row["media_id"]),
                path=str(row["path"]),
                box_index=int(row["box_index"]),
                det_index=int(row["det_index"]),
                true_name=true_name,
                predicted_name=predicted,
                decision=str(row["decision"]),
                s_max=s_max,
                fold=int(row["fold"]),
                name_star=name_star,
                enrolled=bool(row["enrolled"]),
                tau_k=float(row["tau_k"]),
                excluded_single_face_recall=bool(row["excluded_single_face_recall"]),
                publishable=bool(row["publishable"]),
            )
        )
    # Deterministic order independent of input file ordering.
    out.sort(
        key=lambda d: (
            d.media_id,
            d.box_index,
            d.det_index,
            d.fold,
            d.s_max if math.isfinite(d.s_max) else float("-1e300"),
            d.true_name or "",
        )
    )
    return out


def media_stratum_index(manifest: Mapping[str, Any]) -> dict[int, tuple[str, ...]]:
    """Join key: media_id → ordered unique stratum tags (domain + tags)."""
    index: dict[int, tuple[str, ...]] = {}
    for entry in manifest["entries"]:
        mid = int(entry["media_id"])
        names: list[str] = []
        domain = entry.get("domain")
        if isinstance(domain, str) and domain.strip():
            names.append(domain.strip())
        tags = entry.get("tags") or []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag.strip() and tag.strip() not in names:
                    names.append(tag.strip())
        index[mid] = tuple(names)
    return index


# ---------------------------------------------------------------------------
# Pair-level subject-disjoint K-fold protocol ([CAL-07])
# ---------------------------------------------------------------------------


def identity_fold_assignment(decisions: Sequence[Decision]) -> dict[str, int]:
    """Map roster identity → fold. Strangers (true_name=None) never appear.

    Each roster identity must occupy exactly one fold (subject-disjoint).
    Conflicting fold indices raise CalibrationError — they are not collapsed
    via min/max.
    """
    folds: dict[str, set[int]] = defaultdict(set)
    for d in decisions:
        if d.true_name is None:
            continue  # strangers never inform fold assignment / fitting
        if d.excluded_single_face_recall:
            continue
        folds[d.true_name].add(d.fold)
    assigned: dict[str, int] = {}
    for name in sorted(folds):
        vals = folds[name]
        if len(vals) != 1:
            raise CalibrationError(
                f"identity {name!r} spans multiple folds {sorted(vals)}; "
                "subject-disjoint K-fold requires one fold per roster identity"
            )
        assigned[name] = next(iter(vals))
    return assigned


def _trials_from_decision(
    d: Decision,
    strata_by_media: Mapping[int, tuple[str, ...]],
) -> list[ScoreTrial]:
    """Convert a decision row into zero or more score trials.

    - Rows with ``excluded_single_face_recall=True`` produce no trials (FIR-5
      excludes them from recall accounting; calibration mirrors that).
    - Anonymous strangers → one impostor trial (score may be -inf).
    - Enrolled named probes always emit a **genuine** trial so rank-1-miss /
      reject rows remain in the FNMR denominator:
        * mate at rank-1 (name_star == true_name) → score = s_max
        * otherwise → score = -inf (mate never accepted at any finite tau)
    - When name_star is a non-mate, also emit an impostor trial at s_max.
    - Non-enrolled named rows produce no trials.
    - Enrolled with null name_star and non-mate path uses genuine at -inf only.
    """
    if d.excluded_single_face_recall:
        return []

    strata = strata_by_media.get(d.media_id, ())
    score = float(d.s_max)

    if d.true_name is None:
        # Anonymous stranger: impostor probe only; never a genuine trial.
        return [
            ScoreTrial(
                score=score,
                probe_identity=None,
                gallery_identity=d.name_star,
                fold=d.fold,
                media_id=d.media_id,
                strata=strata,
                is_genuine=False,
            )
        ]

    if not d.enrolled:
        return []

    trials: list[ScoreTrial] = []
    mate_at_rank1 = d.name_star is not None and d.name_star == d.true_name
    genuine_score = score if mate_at_rank1 else S_MAX_NO_MATCH
    trials.append(
        ScoreTrial(
            score=genuine_score,
            probe_identity=d.true_name,
            gallery_identity=d.true_name,
            fold=d.fold,
            media_id=d.media_id,
            strata=strata,
            is_genuine=True,
        )
    )
    if d.name_star is not None and d.name_star != d.true_name:
        trials.append(
            ScoreTrial(
                score=score,
                probe_identity=d.true_name,
                gallery_identity=d.name_star,
                fold=d.fold,
                media_id=d.media_id,
                strata=strata,
                is_genuine=False,
            )
        )
    return trials


def build_trials(
    decisions: Sequence[Decision],
    strata_by_media: Mapping[int, tuple[str, ...]],
) -> list[ScoreTrial]:
    trials: list[ScoreTrial] = []
    for d in decisions:
        trials.extend(_trials_from_decision(d, strata_by_media))
    trials.sort(
        key=lambda t: (
            t.media_id,
            t.fold,
            t.score if math.isfinite(t.score) else float("-1e300"),
            t.probe_identity or "",
            t.gallery_identity or "",
            t.is_genuine,
        )
    )
    return trials


def fit_identities_for_held_fold(
    identity_folds: Mapping[str, int],
    held_fold: int,
) -> frozenset[str]:
    return frozenset(name for name, fold in identity_folds.items() if fold != held_fold)


def read_identities_for_held_fold(
    identity_folds: Mapping[str, int],
    held_fold: int,
) -> frozenset[str]:
    return frozenset(name for name, fold in identity_folds.items() if fold == held_fold)


def select_fit_trials(
    trials: Sequence[ScoreTrial],
    fit_identities: frozenset[str],
) -> list[ScoreTrial]:
    """Trials allowed to inform threshold fitting.

    Strangers never enter fit. Genuine trials require the probe identity in fit.
    Impostor trials require both probe and gallery identities in fit (pair-level);
    stranger impostors are excluded from fit by the stranger rule.
    """
    selected: list[ScoreTrial] = []
    for t in trials:
        if t.probe_identity is None:
            continue  # strangers never inform fitting
        if t.probe_identity not in fit_identities:
            continue
        if t.is_genuine:
            selected.append(t)
            continue
        # Impostor fit pair: both identities must be in the fit set.
        if t.gallery_identity is None or t.gallery_identity not in fit_identities:
            continue
        selected.append(t)
    return selected


def select_read_trials(
    trials: Sequence[ScoreTrial],
    read_identities: frozenset[str],
    fit_identities: frozenset[str],
    *,
    held_fold: int,
) -> list[ScoreTrial]:
    """Out-of-fold read trials under pair-level disjointness ([CAL-07]).

    - Genuine: probe identity in the held (read) fold.
    - Impostor with roster probe: both probe and gallery identities in the held
      fold; cross-fold impostors excluded.
    - Stranger probes: allowed as read-only rejection probes (never in fit).
      Counted **exactly once**:
        * named gallery (``name_star``): under the held fold of that gallery
          identity (not the row's fold) so fold-mismatched strangers are not
          dropped when FIR-5 leaves row fold uncoupled from gallery fold;
        * null gallery: under ``trial.fold == held_fold``.
      Gallery must never touch a fit-fold identity.
    - No read trial may reference a fit-fold identity as probe or gallery.
    """
    selected: list[ScoreTrial] = []
    for t in trials:
        if t.is_genuine:
            if t.probe_identity is None or t.probe_identity not in read_identities:
                continue
            if t.probe_identity in fit_identities:
                continue
            selected.append(t)
            continue

        # Impostor / stranger
        if t.probe_identity is None:
            if t.gallery_identity is not None and t.gallery_identity in fit_identities:
                continue
            if t.gallery_identity is not None and t.gallery_identity in read_identities:
                # Single-count under gallery fold (handles row/fold mismatch).
                selected.append(t)
                continue
            if t.gallery_identity is not None:
                # Named gallery not on the roster: fall back to row fold once.
                if t.fold != held_fold:
                    continue
                selected.append(t)
                continue
            # No gallery match: single-count by decision row fold.
            if t.fold != held_fold:
                continue
            selected.append(t)
            continue

        if t.probe_identity not in read_identities:
            continue
        if t.probe_identity in fit_identities:
            continue
        if t.gallery_identity is None:
            continue
        # Both identities of the impostor pair in the held fold.
        if t.gallery_identity not in read_identities:
            continue
        if t.gallery_identity in fit_identities:
            continue
        selected.append(t)
    return selected


def assert_pair_level_disjointness(
    read_trials: Sequence[ScoreTrial],
    fit_identities: frozenset[str],
) -> None:
    """Property: no read-pair touches a fit-fold identity; strangers not in fit."""
    if any(name is None for name in fit_identities):
        raise CalibrationError("strangers must never appear in the fit identity set")
    for t in read_trials:
        if t.probe_identity is not None and t.probe_identity in fit_identities:
            raise CalibrationError(
                f"read-pair probe {t.probe_identity!r} touches fit-fold identity set"
            )
        if t.gallery_identity is not None and t.gallery_identity in fit_identities:
            raise CalibrationError(
                f"read-pair gallery {t.gallery_identity!r} touches fit-fold identity set"
            )


def assert_fit_side_impostor_disjointness(
    fit_trials: Sequence[ScoreTrial],
    fit_identities: frozenset[str],
) -> None:
    """Property: fit trials never touch held-fold / stranger identities (FIR6RC-06).

    Genuine fit: probe in fit set. Impostor fit: both probe and gallery in fit.
    Strangers never inform fitting.
    """
    if any(name is None for name in fit_identities):
        raise CalibrationError("strangers must never appear in the fit identity set")
    for t in fit_trials:
        if t.probe_identity is None:
            raise CalibrationError("stranger probe must never appear in fit trials")
        if t.probe_identity not in fit_identities:
            raise CalibrationError(
                f"fit-pair probe {t.probe_identity!r} is outside the fit identity set"
            )
        if t.is_genuine:
            continue
        if t.gallery_identity is None:
            raise CalibrationError(
                f"fit impostor probe {t.probe_identity!r} missing gallery identity"
            )
        if t.gallery_identity not in fit_identities:
            raise CalibrationError(
                f"fit-pair gallery {t.gallery_identity!r} is outside the fit identity set"
            )


def fmr_at(scores: Sequence[float], tau: float) -> float | None:
    """Impostor acceptance rate at ``tau``.

    JANUS 2.3.4 FPI: a non-mated rank-1 is a false positive only when score
    is strictly greater than ``t``. Delegates to ``accept_predicate.is_fpi``
    so this stays in lockstep with ``open_set_identification._is_fpi`` — the
    FMR this module calibrates is the operating point the scorer publishes.
    """
    if not scores:
        return None
    accepted = sum(1 for s in scores if is_fpi(s, tau))
    return accepted / len(scores)


def fnmr_at(scores: Sequence[float], tau: float) -> float | None:
    """Genuine miss rate at ``tau``.

    JANUS 2.3.4 FNIR: a mated search misses when it does not return the mate
    at or above ``t`` (score < tau). A tie at tau is a hit, matching
    ``open_set_identification._is_fnir_miss``.
    """
    if not scores:
        return None
    missed = sum(1 for s in scores if is_fnir_miss(s, tau))
    return missed / len(scores)


def select_threshold(
    genuine_scores: Sequence[float],
    impostor_scores: Sequence[float],
    *,
    fmr_target: float,
) -> float | None:
    """Pre-registered rule: minimum tau with fit FMR ≤ target.

    FMR is JANUS 2.3.4 FPI (``fmr_at``: score > tau). Candidate thresholds are
    midpoints between consecutive unique finite observed scores (plus the 0.0
    and 1.0 bounds), so an interior candidate cannot tie an observed score.
    This makes the published FPI rule and operational apply rule agree on all
    observed scores, including the fixture's media_id=301 impostor at 0.58
    that was exactly the old proposed tau.

    Returns ``None`` (abstain) when there are zero fit impostors **or** every
    impostor score is non-finite (-inf / no-match only) — never fail-open to
    tau=0.0 / accept-everything ([CAL-01]). All--inf impostors yield
    ``fmr_at(..., 0.0) == 0`` which would otherwise accept candidate 0.0.
    When no candidate meets the target, fail-closed to max(1.0, peak observed
    finite score). Empty genuines are allowed (threshold from impostors only).

    Deterministic; no RNG.
    """
    if fmr_target < 0.0 or fmr_target > 1.0:
        raise CalibrationError(f"fmr_target must be in [0,1], got {fmr_target}")

    if not impostor_scores:
        # Cannot estimate FMR — abstain rather than propose accept-everything.
        return None

    # Finite impostor evidence required. All -inf (JSON null s_max) is not
    # usable FMR evidence at any finite tau (would fail-open to 0.0).
    if not any(math.isfinite(float(s)) for s in impostor_scores):
        return None

    finite = [
        float(s)
        for s in list(genuine_scores) + list(impostor_scores)
        if math.isfinite(float(s))
    ]
    observed = sorted(set(finite))
    midpoints = [
        (lower + upper) / 2.0 for lower, upper in zip(observed, observed[1:])
    ]
    candidates = sorted(set(midpoints) | {0.0, 1.0})
    # Prefer lower tau among those meeting FMR (higher acceptance). Walk ascending.
    for tau in candidates:
        fmr = fmr_at(impostor_scores, tau)
        # fmr is never None here (impostor_scores non-empty); require explicit pass.
        if fmr is not None and fmr <= fmr_target:
            return float(tau)

    # No tau meets target — fail closed to "accept nothing".
    peak = max(observed) if observed else 1.0
    return float(max(peak, 1.0))


def _filter_trials_for_stratum(
    trials: Sequence[ScoreTrial],
    stratum: str | None,
) -> list[ScoreTrial]:
    if stratum is None or stratum == GLOBAL_STRATUM:
        return list(trials)
    return [t for t in trials if stratum in t.strata]


def _oof_metrics_for_stratum(
    trials: Sequence[ScoreTrial],
    identity_folds: Mapping[str, int],
    k: int,
    *,
    stratum: str | None,
    fmr_target: float,
) -> dict[str, Any]:
    """Fit-on-complement / read-on-held metrics; per-fold OOF at each fit tau.

    OOF rates pool per-fold accept/miss counts evaluated at **that fold's**
    fit tau only (never at the median of taus that saw the read fold). Residual
    CAL-07 disclosure notes that the final proposed tau is still the median of
    fit taus and is not re-used to re-score every fold.
    """
    fit_taus: list[float] = []
    oof_genuine: list[float] = []
    oof_impostor: list[float] = []
    # Per-fold OOF outcome counts at that fold's tau.
    n_gen_oof = 0
    n_gen_miss = 0
    n_imp_oof = 0
    n_imp_accept = 0
    fold_rows: list[dict[str, Any]] = []
    n_abstained_folds = 0

    scoped = _filter_trials_for_stratum(trials, stratum)

    for held in range(k):
        fit_ids = fit_identities_for_held_fold(identity_folds, held)
        read_ids = read_identities_for_held_fold(identity_folds, held)
        fit_trials = select_fit_trials(scoped, fit_ids)
        read_trials = select_read_trials(scoped, read_ids, fit_ids, held_fold=held)
        assert_pair_level_disjointness(read_trials, fit_ids)
        assert_fit_side_impostor_disjointness(fit_trials, fit_ids)

        g_fit = [t.score for t in fit_trials if t.is_genuine]
        i_fit = [t.score for t in fit_trials if not t.is_genuine]
        tau = select_threshold(g_fit, i_fit, fmr_target=fmr_target)

        g_read = [t.score for t in read_trials if t.is_genuine]
        i_read = [t.score for t in read_trials if not t.is_genuine]

        fold_fmr: float | None = None
        fold_fnmr: float | None = None
        if tau is None:
            n_abstained_folds += 1
            # Do NOT pool abstained-fold read scores into tax denominators —
            # fnmr_oof/fmr_oof already exclude them ([CAL-05] consistency).
        else:
            fit_taus.append(tau)
            # Only non-abstained folds contribute to OOF pools / tax dens.
            oof_genuine.extend(g_read)
            oof_impostor.extend(i_read)
            fold_fmr = fmr_at(i_read, tau)
            fold_fnmr = fnmr_at(g_read, tau)
            for s in g_read:
                n_gen_oof += 1
                if is_fnir_miss(s, tau):
                    n_gen_miss += 1
            for s in i_read:
                n_imp_oof += 1
                if is_fpi(s, tau):  # JANUS 2.3.4 FPI; lockstep with fmr_at
                    n_imp_accept += 1

        fold_rows.append(
            {
                "held_fold": held,
                "tau_fit": tau,
                "abstained": tau is None,
                "insufficient_impostor_evidence": tau is None,
                "fnmr_oof_fold": fold_fnmr,
                "fmr_oof_fold": fold_fmr,
                "n_fit_genuine": len(g_fit),
                "n_fit_impostor": len(i_fit),
                "n_read_genuine": len(g_read),
                "n_read_impostor": len(i_read),
                "n_fit_identities": len(fit_ids),
                "n_read_identities": len(read_ids),
            }
        )

    # Final proposed tau: median of non-abstained fit taus (deterministic for
    # odd count; for even use lower middle after sort — no RNG). All-abstain → None.
    if fit_taus:
        ordered = sorted(fit_taus)
        mid = (len(ordered) - 1) // 2
        tau_proposed: float | None = ordered[mid]
    else:
        tau_proposed = None

    fnmr_oof = (n_gen_miss / n_gen_oof) if n_gen_oof else None
    fmr_oof = (n_imp_accept / n_imp_oof) if n_imp_oof else None

    return {
        "tau_proposed": tau_proposed,
        "fnmr_oof": fnmr_oof,
        "fmr_oof": fmr_oof,
        "n_genuine_oof": n_gen_oof,
        "n_impostor_oof": n_imp_oof,
        "n_abstained_folds": n_abstained_folds,
        "fold_rows": fold_rows,
        "fit_taus": fit_taus,
        # Retain OOF scores for tax recomputation at alternate fixed taus.
        "_oof_genuine": oof_genuine,
        "_oof_impostor": oof_impostor,
    }


def _public_stratum_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    tau_proposed = raw["tau_proposed"]
    insufficient = tau_proposed is None
    return {
        "tau_proposed": tau_proposed,
        "fnmr_oof": raw["fnmr_oof"],
        "fmr_oof": raw["fmr_oof"],
        "n_genuine_oof": raw["n_genuine_oof"],
        "n_impostor_oof": raw["n_impostor_oof"],
        "n_abstained_folds": raw["n_abstained_folds"],
        # Explicit flag so operators/CI can grep without inferring from null tau.
        "insufficient_impostor_evidence": insufficient,
        "fold_rows": raw["fold_rows"],
    }


def calibrate(
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    fmr_target: float = DEFAULT_FMR_TARGET,
    oact_coefficient: float = 0.0,
) -> dict[str, Any]:
    """Run pair-level K-fold calibration; return a JSON-serializable artifact."""
    report_errors = validate_face_bakeoff_report(report)
    if report_errors:
        raise CalibrationError("; ".join(report_errors))
    manifest_errors = validate_golden_manifest(manifest)
    if manifest_errors:
        raise CalibrationError("; ".join(manifest_errors))

    decisions = parse_decisions(report)
    if not decisions:
        raise CalibrationError("decisions list is empty")

    strata_by_media = media_stratum_index(manifest)
    missing_media = sorted({d.media_id for d in decisions if d.media_id not in strata_by_media})
    if missing_media:
        raise CalibrationError(
            f"decisions reference media_id(s) absent from manifest: {missing_media}"
        )

    identity_folds = identity_fold_assignment(decisions)
    tau_k = list(report["tau"]["tau_k"])
    k = len(tau_k)
    if k < 2:
        raise CalibrationError("tau.tau_k must have length K >= 2 for K-fold")
    max_fold = max(d.fold for d in decisions)
    if max_fold >= k:
        raise CalibrationError(f"decision fold {max_fold} out of range for K={k}")

    trials = build_trials(decisions, strata_by_media)

    # Strata present on any decision-joined media, sorted for determinism.
    stratum_names = sorted(
        {s for mid in {d.media_id for d in decisions} for s in strata_by_media.get(mid, ())}
    )

    global_raw = _oof_metrics_for_stratum(
        trials, identity_folds, k, stratum=None, fmr_target=fmr_target
    )
    per_stratum_raw: dict[str, dict[str, Any]] = {}
    for name in stratum_names:
        per_stratum_raw[name] = _oof_metrics_for_stratum(
            trials, identity_folds, k, stratum=name, fmr_target=fmr_target
        )

    global_tau = global_raw["tau_proposed"]
    # Named sampling frames for tax denominators (FIR6V11-02 AUDIT).
    # Both FNMR sides of the global-vs-stratum tax are evaluated on the
    # *stratum* OOF genuine pool from non-abstained folds — never on the
    # global genuine pool. Labels below make that explicit.
    stratum_oof_genuine_frame = "stratum_oof_genuine_non_abstained_folds"
    fnmr_tax_global_vs_stratum: dict[str, dict[str, Any]] = {}
    for name, raw in per_stratum_raw.items():
        g_scores: list[float] = list(raw["_oof_genuine"])
        stratum_tau = raw["tau_proposed"]
        stratum_fnmr = fnmr_at(g_scores, stratum_tau) if stratum_tau is not None else None
        # Honest label: FNMR of *stratum* genuines at the global tau — not the
        # global stratum's own FNMR (FIR6V11-02).
        stratum_fnmr_at_global_tau = (
            fnmr_at(g_scores, float(global_tau)) if global_tau is not None else None
        )
        tax = None
        if stratum_fnmr is not None and stratum_fnmr_at_global_tau is not None:
            tax = stratum_fnmr_at_global_tau - stratum_fnmr
        fnmr_tax_global_vs_stratum[name] = {
            "stratum_tau": stratum_tau,
            "global_tau": global_tau,
            "stratum_fnmr": stratum_fnmr,
            "stratum_fnmr_at_global_tau": stratum_fnmr_at_global_tau,
            # Deprecated alias kept for one cycle; same value as honest key.
            "global_fnmr": stratum_fnmr_at_global_tau,
            "tax": tax,
            "sampling_frame": {
                "genuine_scores": stratum_oof_genuine_frame,
                "denominator": "len(stratum_oof_genuine)",
                "n_genuine": len(g_scores),
                # FNMR denominators are genuine-only; impostor pool size is
                # reported for frame completeness (FIR6V11-02 / AUDIT-07).
                "n_impostor": int(raw["n_impostor_oof"]),
            },
        }

    # Global OACT coefficient tax ([CAL-05]/[ARCH-08]): a single coefficient is a
    # compromise vs per-stratum. With no per-decision occlusion severity on the
    # v1 report, tax is reported as the FNMR impact of elevating tau by
    # coefficient (uniform additive proxy). coefficient=0 ⇒ zero tax when base
    # tau is defined.
    oact_tax: dict[str, Any] = {
        "coefficient": float(oact_coefficient),
        "proxy": "uniform_additive_tau_elevation",
        "disclosure": (
            "OACT coefficient is a single global scalar (per-stratum coefficients "
            "deferred). Tax uses a uniform additive tau elevation of "
            "`coefficient` as a severity=1.0 proxy because face_bakeoff v1 "
            "decisions do not carry per-row occlusion_severity."
        ),
        "sampling_frame": {
            "genuine_scores": stratum_oof_genuine_frame,
            "denominator": "len(stratum_oof_genuine)",
        },
        "per_stratum_tax": {},
    }
    for name, raw in per_stratum_raw.items():
        g_scores = list(raw["_oof_genuine"])
        base_tau = raw["tau_proposed"]
        if base_tau is None:
            oact_tax["per_stratum_tax"][name] = {
                "base_tau": None,
                "elevated_tau": None,
                "base_fnmr": None,
                "elevated_fnmr": None,
                "tax": None,
                "sampling_frame": {
                    "genuine_scores": stratum_oof_genuine_frame,
                    "n_genuine": 0,
                    "n_impostor": int(raw["n_impostor_oof"]),
                },
            }
            continue
        elevated = float(base_tau) + float(oact_coefficient)
        base_fnmr = fnmr_at(g_scores, float(base_tau))
        elev_fnmr = fnmr_at(g_scores, elevated)
        tax = None
        if base_fnmr is not None and elev_fnmr is not None:
            tax = elev_fnmr - base_fnmr
        oact_tax["per_stratum_tax"][name] = {
            "base_tau": float(base_tau),
            "elevated_tau": elevated,
            "base_fnmr": base_fnmr,
            "elevated_fnmr": elev_fnmr,
            "tax": tax,
            "sampling_frame": {
                "genuine_scores": stratum_oof_genuine_frame,
                "n_genuine": len(g_scores),
                "n_impostor": int(raw["n_impostor_oof"]),
            },
        }

    n_stranger_decisions = sum(
        1
        for d in decisions
        if d.true_name is None and not d.excluded_single_face_recall
    )
    n_excluded = sum(1 for d in decisions if d.excluded_single_face_recall)
    # Silent drops: decision rows that emit zero trials (FIR6V11-02).
    n_non_enrolled_named = sum(
        1
        for d in decisions
        if d.true_name is not None
        and not d.enrolled
        and not d.excluded_single_face_recall
    )
    n_silent_drop_decisions = n_excluded + n_non_enrolled_named
    protocol = {
        "kind": "pair_level_subject_disjoint_kfold",
        "k": k,
        "selection_rule": SELECTION_RULE_ID,
        "fmr_target": fmr_target,
        "strangers_in_fit": False,
        "cross_fold_impostors_excluded": True,
        "fit_side_impostors_require_both_in_fit": True,
        "strangers_single_count_by_fold": True,
        "strangers_count_under_gallery_fold": True,
        "oof_read_per_fold_tau": True,
        "zero_fit_impostor_policy": "abstain",
        "all_nonfinite_impostor_policy": "abstain",
        "excluded_single_face_recall_skipped": True,
        "rank1_miss_genuine_at_neg_inf": True,
        "selection_rule_pre_registered": True,
        "deterministic": True,
        "n_roster_identities": len(identity_folds),
        "n_stranger_decisions": n_stranger_decisions,
        "n_excluded_single_face_recall": n_excluded,
        "n_non_enrolled_named_silent_drop": n_non_enrolled_named,
        "n_silent_drop_decisions": n_silent_drop_decisions,
        "sampling_frames": {
            "fit_genuine": "fit_fold_genuine_trials",
            "fit_impostor": "fit_fold_impostor_both_identities_in_fit",
            "oof_genuine": "held_fold_genuine_non_abstained",
            "oof_impostor": "held_fold_impostor_both_identities_in_held",
            "fnmr_tax_genuine": stratum_oof_genuine_frame,
            "oact_tax_genuine": stratum_oof_genuine_frame,
        },
        # AUDIT-07 (FIR6V11-02): every named frame defines target population,
        # sampling unit, and observation unit; undercoverage (units with
        # selection probability zero) is inventoried with counts adjacent to
        # the denominators they are dropped from.
        "sampling_frame_definitions": {
            "fit_fold_genuine_trials": {
                "target_population": (
                    "enrolled named probe faces in the Golden-150 bakeoff "
                    "report joined to the manifest"
                ),
                "sampling_unit": "identity (K-fold assignment is identity-level)",
                "observation_unit": "face-level genuine trial (probe s_max vs mate)",
                "undercoverage": {
                    "excluded_single_face_recall_rows": n_excluded,
                    "non_enrolled_named_rows": n_non_enrolled_named,
                },
            },
            "fit_fold_impostor_both_identities_in_fit": {
                "target_population": (
                    "probe/gallery non-mate pairs with both identities in the "
                    "fit set (strangers never inform fitting)"
                ),
                "sampling_unit": "identity pair (both fold-assigned identity-level)",
                "observation_unit": "face-level impostor trial (probe s_max vs non-mate)",
                "undercoverage": {
                    "cross_fold_pairs_excluded": True,
                    "excluded_single_face_recall_rows": n_excluded,
                    "non_enrolled_named_rows": n_non_enrolled_named,
                },
            },
            "held_fold_genuine_non_abstained": {
                "target_population": (
                    "enrolled named probe faces read out-of-fold on "
                    "non-abstained folds"
                ),
                "sampling_unit": "identity (held-fold membership is identity-level)",
                "observation_unit": "face-level genuine trial",
                "undercoverage": {
                    "abstained_fold_trials_dropped": True,
                    "excluded_single_face_recall_rows": n_excluded,
                    "non_enrolled_named_rows": n_non_enrolled_named,
                },
            },
            "held_fold_impostor_both_identities_in_held": {
                "target_population": (
                    "probe/gallery non-mate pairs (incl. strangers as read-only "
                    "probes) with both identities in the held fold"
                ),
                "sampling_unit": "identity pair (held-fold membership is identity-level)",
                "observation_unit": "face-level impostor trial",
                "undercoverage": {
                    "cross_fold_pairs_excluded": True,
                    "excluded_single_face_recall_rows": n_excluded,
                    "non_enrolled_named_rows": n_non_enrolled_named,
                },
            },
            stratum_oof_genuine_frame: {
                "target_population": (
                    "stratum-scoped OOF genuine pool from non-abstained folds "
                    "(NOT the global population; used by fnmr_tax and oact_tax)"
                ),
                "sampling_unit": "identity (fold clustering is identity-level)",
                "observation_unit": "face-level genuine trial",
                "undercoverage": {
                    "abstained_fold_trials_dropped": True,
                    "excluded_single_face_recall_rows": n_excluded,
                    "non_enrolled_named_rows": n_non_enrolled_named,
                },
            },
        },
        # AUDIT-11 (FIR6V11-02): trial denominators are face-level but folds
        # cluster at identity level, so trials within one identity are
        # correlated — raw n_* counts are not effective independent sample
        # sizes. No deff/ICC is estimated and no design-based intervals are
        # published in this artifact; any downstream CI must account for the
        # identity-level cluster design (deff ~= 1 + (M-1)*ICC, n_eff = n/deff).
        "trial_clustering_note": (
            "All n_genuine/n_impostor denominators count face-level trials, "
            "while K-fold assignment (the sampling design) clusters at the "
            "identity level. Trials sharing an identity are not independent; "
            "raw trial counts overstate effective sample size. This artifact "
            "publishes point rates only — no design-based confidence "
            "intervals. Downstream interval estimates must apply an "
            "identity-level cluster design effect (deff ≈ 1 + (M-1)·ICC; "
            "n_eff = n/deff) rather than treating trial counts as "
            "independent n (AUDIT-11)."
        ),
        "clustering_note": (
            "Calibration is pair-level over face_bakeoff decision scores "
            "(probe/gallery s_max trials). It does not re-run production "
            "clustering, joint assignment, or centroid refresh; production "
            "clustering behavior is out of scope for this artifact."
        ),
        "silent_drop_disclosure": (
            "Decision rows may emit zero calibration trials without failing "
            "the run: excluded_single_face_recall=true (FIR-5 recall parity) "
            f"n={n_excluded}; non-enrolled named probes n={n_non_enrolled_named}. "
            "These silent drops are counted above and never enter fit or OOF "
            "denominators."
        ),
        "disclosure": (
            "Thresholds are fit on the complement of each held fold; gate metrics "
            "are read on that held fold only, evaluated at that fold's fit tau "
            "(not at the median of taus that saw the read fold). Final "
            "tau_proposed is the median of non-abstained fit taus and is a "
            "proposal only — residual CAL-07 note: applying that single median "
            "back to every fold would re-introduce a weak train/test contact. "
            "Read-fold impostor pairs require both identities in the held fold "
            "(cross-fold pairs excluded). Fit-side impostor pairs require both "
            "probe and gallery identities in the fit set (FIR6RC-06). Anonymous "
            "strangers (true_name=null) are read-only probes, counted exactly "
            "once (named gallery under that gallery identity's fold; null "
            "gallery under decision.fold), and never inform fitting. Folds with "
            "zero fit impostors or only non-finite (-inf) impostor scores "
            "abstain (tau_fit=null / insufficient_impostor_evidence=true; never "
            "fail-open to 0.0). Enrolled rank-1-miss genuines remain in the FNMR "
            "denominator at score -inf (mate never accepted at any finite tau); "
            "a non-mate name_star also emits an impostor trial at s_max. Rows "
            "with excluded_single_face_recall=true are skipped (FIR-5 recall "
            "parity). Non-enrolled named probes are also silent-dropped (zero "
            "trials). "
            f"Selection rule {SELECTION_RULE_ID!r} is pre-registered on fit folds "
            "only before any held fold is read (FIR6RC-07). Candidate taus are "
            "midpoints between consecutive unique finite fit scores, plus 0.0 "
            "and 1.0 bounds, so interior candidates cannot tie observed scores "
            "and JANUS FPI and operational acceptance agree on fit observations. "
            "The calibration artifact is deterministic: bit-identical re-runs "
            "with the same report+manifest+fmr_target (no wall-clock or unpinned "
            "RNG; PYTHONHASHSEED-independent serialization). "
            "Decision rows carry publishable (bool) for FIR-5 schema parity; "
            "threshold math ignores it. FNMR-tax / OACT-tax denominators use "
            "only non-abstained fold stratum OOF genuine scores "
            f"({stratum_oof_genuine_frame}); "
            "stratum_fnmr_at_global_tau is the stratum genuine FNMR evaluated at "
            "global_tau (not the global pool's own FNMR). "
            "Calibration is pair-level over bakeoff scores, not a re-run of "
            "production clustering."
        ),
    }

    artifact = {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "protocol": protocol,
        "source": {
            "report_kind": report["report_kind"],
            "report_schema": report["schema"],
            "report_doc_kind": report["kind"],
            "report_tau_op": report["tau"]["tau_op"],
            "report_tau_k": list(report["tau"]["tau_k"]),
            "report_counts": report["counts"],
            "n_decisions": len(decisions),
            "n_excluded_single_face_recall": n_excluded,
            "strata": stratum_names,
        },
        "global": _public_stratum_row(global_raw),
        "per_stratum": {name: _public_stratum_row(raw) for name, raw in per_stratum_raw.items()},
        "fnmr_tax": {
            "global_vs_stratum": fnmr_tax_global_vs_stratum,
            "global_oact_coefficient": oact_tax,
        },
    }
    return artifact


def dumps_artifact(artifact: Mapping[str, Any]) -> str:
    """Canonical JSON: sorted keys, stable separators, trailing newline."""
    return json.dumps(artifact, sort_keys=True, indent=2, allow_nan=False) + "\n"


def run_calibration_paths(
    report_path: Path,
    manifest_path: Path,
    *,
    fmr_target: float = DEFAULT_FMR_TARGET,
    oact_coefficient: float = 0.0,
) -> dict[str, Any]:
    report = load_json(report_path)
    manifest = load_json(manifest_path)
    return calibrate(
        report,
        manifest,
        fmr_target=fmr_target,
        oact_coefficient=oact_coefficient,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calibrate_face_thresholds",
        description=(
            "Deterministic face threshold calibration from a face_bakeoff schema-v1 "
            "report + golden manifest (FIR-6 S3a). Writes no settings."
        ),
    )
    parser.add_argument("--report", type=Path, required=True, help="face_bakeoff report JSON")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="golden manifest JSON (domain/tags for stratum join)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write calibration artifact JSON (default: stdout)",
    )
    parser.add_argument(
        "--fmr-target",
        type=float,
        default=DEFAULT_FMR_TARGET,
        help=f"pre-registered fit FMR ceiling (default {DEFAULT_FMR_TARGET})",
    )
    parser.add_argument(
        "--oact-coefficient",
        type=float,
        default=0.0,
        help="global OACT coefficient for FNMR-tax proxy (default 0.0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if not (0.0 <= args.fmr_target <= 1.0):
            raise CalibrationError(f"--fmr-target must be in [0,1], got {args.fmr_target}")
        if not math.isfinite(args.oact_coefficient) or args.oact_coefficient < 0.0:
            raise CalibrationError(
                f"--oact-coefficient must be a finite number >= 0, got {args.oact_coefficient}"
            )
        artifact = run_calibration_paths(
            args.report,
            args.manifest,
            fmr_target=float(args.fmr_target),
            oact_coefficient=float(args.oact_coefficient),
        )
    except CalibrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = dumps_artifact(artifact)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
