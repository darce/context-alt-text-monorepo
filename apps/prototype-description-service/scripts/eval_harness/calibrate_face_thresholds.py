#!/usr/bin/env python3
"""Calibrate face_pipeline thresholds from a pinned face_bakeoff report (FIR-6 S3a).

Pure artifact→artifact CLI: consumes a face_bakeoff schema-v1 report plus a
golden manifest (for per-media stratum tags), applies the pair-level
subject-disjoint K-fold protocol ([CAL-07]), and emits a deterministic
calibration artifact (per-stratum proposed thresholds + FNMR-tax table +
protocol disclosure). Never writes recognition settings.

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

# Pinned face_bakeoff report schema v1 (FIR-5 serialization contract; LC-06/GR-08).
REPORT_KIND = "face_bakeoff"
REQUIRED_REPORT_KEYS = frozenset({"report_kind", "tau", "slices", "decisions", "counts"})
REQUIRED_TAU_KEYS = frozenset({"tau_k", "tau_op"})
REQUIRED_DECISION_KEYS = frozenset(
    {
        "media_id",
        "box_index",
        "true_name",
        "predicted_name",
        "decision",
        "s_max",
        "fold",
        "name_star",
        "enrolled",
        "tau_k",
    }
)
# Pre-registered threshold-selection rule id (fit folds only; never re-tuned on read).
SELECTION_RULE_ID = "min_tau_at_fmr_le"
DEFAULT_FMR_TARGET = 0.01
GLOBAL_STRATUM = "_global"
ARTIFACT_KIND = "face_threshold_calibration"
ARTIFACT_SCHEMA_VERSION = 1


class CalibrationError(Exception):
    """Fail-fast validation or protocol error (non-zero CLI exit)."""


@dataclass(frozen=True)
class Decision:
    media_id: int
    box_index: int
    true_name: str | None
    predicted_name: str | None
    decision: str
    s_max: float
    fold: int
    name_star: str | None
    enrolled: bool
    tau_k: float


@dataclass(frozen=True)
class ScoreTrial:
    """One genuine or impostor trial used for threshold fit / OOF read."""

    score: float
    probe_identity: str | None  # None => anonymous stranger
    gallery_identity: str | None  # name_star
    fold: int
    media_id: int
    strata: tuple[str, ...]
    is_genuine: bool


# ---------------------------------------------------------------------------
# Validation (fail-fast, missing keys ⇒ non-zero exit)
# ---------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_face_bakeoff_report(doc: object) -> list[str]:
    """Return schema-violation messages; empty list means ok."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["report must be a JSON object"]

    missing = sorted(REQUIRED_REPORT_KEYS - doc.keys())
    if missing:
        errors.append(f"report missing required keys: {missing}")
        return errors

    if doc.get("report_kind") != REPORT_KIND:
        errors.append(f"report_kind must be {REPORT_KIND!r}, got {doc.get('report_kind')!r}")

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
            if not isinstance(row["box_index"], int) or isinstance(row["box_index"], bool):
                errors.append(f"decisions[{i}].box_index must be an int")
            for name_key in ("true_name", "predicted_name", "name_star"):
                val = row[name_key]
                if val is not None and not isinstance(val, str):
                    errors.append(f"decisions[{i}].{name_key} must be str or null")
            if not isinstance(row["decision"], str):
                errors.append(f"decisions[{i}].decision must be a string")
            if not _is_number(row["s_max"]):
                errors.append(f"decisions[{i}].s_max must be a finite number")
            if not isinstance(row["fold"], int) or isinstance(row["fold"], bool) or row["fold"] < 0:
                errors.append(f"decisions[{i}].fold must be a non-negative int")
            if not isinstance(row["enrolled"], bool):
                errors.append(f"decisions[{i}].enrolled must be a bool")
            if not _is_number(row["tau_k"]):
                errors.append(f"decisions[{i}].tau_k must be a finite number")

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
        out.append(
            Decision(
                media_id=int(row["media_id"]),
                box_index=int(row["box_index"]),
                true_name=true_name,
                predicted_name=predicted,
                decision=str(row["decision"]),
                s_max=float(row["s_max"]),
                fold=int(row["fold"]),
                name_star=name_star,
                enrolled=bool(row["enrolled"]),
                tau_k=float(row["tau_k"]),
            )
        )
    # Deterministic order independent of input file ordering.
    out.sort(key=lambda d: (d.media_id, d.box_index, d.fold, d.s_max, d.true_name or ""))
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

    Fold is the minimum fold index observed for that identity (deterministic
    under multi-fold noise); conflicting folds raise.
    """
    folds: dict[str, set[int]] = defaultdict(set)
    for d in decisions:
        if d.true_name is None:
            continue  # strangers never inform fold assignment / fitting
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


def _trial_from_decision(
    d: Decision,
    strata_by_media: Mapping[int, tuple[str, ...]],
) -> ScoreTrial | None:
    """Convert a decision row into a genuine or impostor score trial.

    Genuine: enrolled roster face whose best match is itself (s_max is mate sim).
    Impostor: stranger probe, or enrolled face whose name_star ≠ true_name.
    Rows that cannot form a trial (e.g. enrolled genuine with null name_star and
    zero score ambiguity) are skipped.
    """
    strata = strata_by_media.get(d.media_id, ())
    if d.true_name is None:
        # Anonymous stranger: impostor probe only; never a genuine trial.
        return ScoreTrial(
            score=float(d.s_max),
            probe_identity=None,
            gallery_identity=d.name_star,
            fold=d.fold,
            media_id=d.media_id,
            strata=strata,
            is_genuine=False,
        )
    if not d.enrolled:
        return None
    if d.name_star is not None and d.name_star == d.true_name:
        return ScoreTrial(
            score=float(d.s_max),
            probe_identity=d.true_name,
            gallery_identity=d.name_star,
            fold=d.fold,
            media_id=d.media_id,
            strata=strata,
            is_genuine=True,
        )
    # Non-mate best match → impostor-style score at s_max against name_star.
    return ScoreTrial(
        score=float(d.s_max),
        probe_identity=d.true_name,
        gallery_identity=d.name_star,
        fold=d.fold,
        media_id=d.media_id,
        strata=strata,
        is_genuine=False,
    )


def build_trials(
    decisions: Sequence[Decision],
    strata_by_media: Mapping[int, tuple[str, ...]],
) -> list[ScoreTrial]:
    trials: list[ScoreTrial] = []
    for d in decisions:
        trial = _trial_from_decision(d, strata_by_media)
        if trial is not None:
            trials.append(trial)
    trials.sort(
        key=lambda t: (
            t.media_id,
            t.fold,
            t.score,
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
) -> list[ScoreTrial]:
    """Out-of-fold read trials under pair-level disjointness ([CAL-07]).

    - Genuine: probe identity in the held (read) fold.
    - Impostor with roster probe: both probe and gallery identities in the held
      fold; cross-fold impostors excluded.
    - Stranger probes: allowed as read-only rejection probes (never in fit);
      they must not touch a fit-fold gallery identity when counting pair FMR —
      gallery identity must be in the read fold (or null → always rejected).
    - No read trial may reference a fit-fold identity as probe or gallery.
    """
    selected: list[ScoreTrial] = []
    for t in trials:
        if t.is_genuine:
            if t.probe_identity is None or t.probe_identity not in read_identities:
                continue
            # Gallery is the mate (same identity) — already in read set.
            if t.probe_identity in fit_identities:
                continue
            selected.append(t)
            continue

        # Impostor / stranger
        if t.probe_identity is None:
            # Stranger: read-only; gallery (if any) must be in read fold so the
            # pair does not touch a fit-fold identity.
            if t.gallery_identity is not None and t.gallery_identity not in read_identities:
                continue
            if t.gallery_identity is not None and t.gallery_identity in fit_identities:
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


def fmr_at(scores: Sequence[float], tau: float) -> float | None:
    if not scores:
        return None
    accepted = sum(1 for s in scores if s >= tau)
    return accepted / len(scores)


def fnmr_at(scores: Sequence[float], tau: float) -> float | None:
    if not scores:
        return None
    missed = sum(1 for s in scores if s < tau)
    return missed / len(scores)


def select_threshold(
    genuine_scores: Sequence[float],
    impostor_scores: Sequence[float],
    *,
    fmr_target: float,
) -> float:
    """Pre-registered rule: minimum tau with fit FMR ≤ target (else max score).

    Candidate thresholds are the sorted unique scores from fit trials (plus 0.0
    and 1.0 bounds). Deterministic; no RNG.
    """
    if fmr_target < 0.0 or fmr_target > 1.0:
        raise CalibrationError(f"fmr_target must be in [0,1], got {fmr_target}")

    candidates = sorted({float(s) for s in list(genuine_scores) + list(impostor_scores)} | {0.0, 1.0})
    # Prefer lower tau among those meeting FMR (higher acceptance). Walk ascending.
    chosen: float | None = None
    for tau in candidates:
        fmr = fmr_at(impostor_scores, tau)
        if fmr is None or fmr <= fmr_target:
            chosen = tau
            break
    if chosen is None:
        # No tau meets target — fail closed to "accept nothing" at max observed + 0
        # or 1.0, whichever is higher.
        peak = max(candidates) if candidates else 1.0
        chosen = max(peak, 1.0)
    return float(chosen)


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
    """Fit-on-complement / read-on-held metrics; returns proposed tau + OOF rates."""
    fit_taus: list[float] = []
    oof_genuine: list[float] = []
    oof_impostor: list[float] = []
    fold_rows: list[dict[str, Any]] = []

    scoped = _filter_trials_for_stratum(trials, stratum)

    for held in range(k):
        fit_ids = fit_identities_for_held_fold(identity_folds, held)
        read_ids = read_identities_for_held_fold(identity_folds, held)
        fit_trials = select_fit_trials(scoped, fit_ids)
        read_trials = select_read_trials(scoped, read_ids, fit_ids)
        assert_pair_level_disjointness(read_trials, fit_ids)

        g_fit = [t.score for t in fit_trials if t.is_genuine]
        i_fit = [t.score for t in fit_trials if not t.is_genuine]
        tau = select_threshold(g_fit, i_fit, fmr_target=fmr_target)
        fit_taus.append(tau)

        g_read = [t.score for t in read_trials if t.is_genuine]
        i_read = [t.score for t in read_trials if not t.is_genuine]
        oof_genuine.extend(g_read)
        oof_impostor.extend(i_read)
        fold_rows.append(
            {
                "held_fold": held,
                "tau_fit": tau,
                "n_fit_genuine": len(g_fit),
                "n_fit_impostor": len(i_fit),
                "n_read_genuine": len(g_read),
                "n_read_impostor": len(i_read),
                "n_fit_identities": len(fit_ids),
                "n_read_identities": len(read_ids),
            }
        )

    # Final proposed tau: median of per-held fit taus (deterministic for odd K;
    # for even K use lower middle after sort — no RNG).
    if fit_taus:
        ordered = sorted(fit_taus)
        mid = (len(ordered) - 1) // 2
        tau_proposed = ordered[mid]
    else:
        tau_proposed = 1.0

    return {
        "tau_proposed": tau_proposed,
        "fnmr_oof": fnmr_at(oof_genuine, tau_proposed),
        "fmr_oof": fmr_at(oof_impostor, tau_proposed),
        "n_genuine_oof": len(oof_genuine),
        "n_impostor_oof": len(oof_impostor),
        "fold_rows": fold_rows,
        "fit_taus": fit_taus,
        # Retain OOF scores for tax recomputation at alternate taus.
        "_oof_genuine": oof_genuine,
        "_oof_impostor": oof_impostor,
    }


def _public_stratum_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tau_proposed": raw["tau_proposed"],
        "fnmr_oof": raw["fnmr_oof"],
        "fmr_oof": raw["fmr_oof"],
        "n_genuine_oof": raw["n_genuine_oof"],
        "n_impostor_oof": raw["n_impostor_oof"],
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

    global_tau = float(global_raw["tau_proposed"])
    fnmr_tax_global_vs_stratum: dict[str, dict[str, Any]] = {}
    for name, raw in per_stratum_raw.items():
        g_scores: list[float] = list(raw["_oof_genuine"])
        stratum_tau = float(raw["tau_proposed"])
        stratum_fnmr = fnmr_at(g_scores, stratum_tau)
        global_fnmr = fnmr_at(g_scores, global_tau)
        tax = None
        if stratum_fnmr is not None and global_fnmr is not None:
            tax = global_fnmr - stratum_fnmr
        fnmr_tax_global_vs_stratum[name] = {
            "stratum_tau": stratum_tau,
            "global_tau": global_tau,
            "stratum_fnmr": stratum_fnmr,
            "global_fnmr": global_fnmr,
            "tax": tax,
        }

    # Global OACT coefficient tax ([CAL-05]/[ARCH-08]): a single coefficient is a
    # compromise vs per-stratum. With no per-decision occlusion severity on the
    # v1 report, tax is reported as the FNMR impact of elevating tau by
    # coefficient (uniform additive proxy). coefficient=0 ⇒ zero tax.
    oact_tax: dict[str, Any] = {
        "coefficient": float(oact_coefficient),
        "proxy": "uniform_additive_tau_elevation",
        "disclosure": (
            "OACT coefficient is a single global scalar (per-stratum coefficients "
            "deferred). Tax uses a uniform additive tau elevation of "
            "`coefficient` as a severity=1.0 proxy because face_bakeoff v1 "
            "decisions do not carry per-row occlusion_severity."
        ),
        "per_stratum_tax": {},
    }
    for name, raw in per_stratum_raw.items():
        g_scores = list(raw["_oof_genuine"])
        base_tau = float(raw["tau_proposed"])
        elevated = base_tau + float(oact_coefficient)
        base_fnmr = fnmr_at(g_scores, base_tau)
        elev_fnmr = fnmr_at(g_scores, elevated)
        tax = None
        if base_fnmr is not None and elev_fnmr is not None:
            tax = elev_fnmr - base_fnmr
        oact_tax["per_stratum_tax"][name] = {
            "base_tau": base_tau,
            "elevated_tau": elevated,
            "base_fnmr": base_fnmr,
            "elevated_fnmr": elev_fnmr,
            "tax": tax,
        }

    n_stranger_decisions = sum(1 for d in decisions if d.true_name is None)
    protocol = {
        "kind": "pair_level_subject_disjoint_kfold",
        "k": k,
        "selection_rule": SELECTION_RULE_ID,
        "fmr_target": fmr_target,
        "strangers_in_fit": False,
        "cross_fold_impostors_excluded": True,
        "n_roster_identities": len(identity_folds),
        "n_stranger_decisions": n_stranger_decisions,
        "disclosure": (
            "Thresholds are fit and gate metrics are read out-of-fold only under "
            "subject-disjoint K-fold over roster identities. Read-fold impostor "
            "pairs require both identities in the held fold (cross-fold pairs "
            "excluded). Anonymous strangers (true_name=null) are read-only probes "
            "and never inform fitting. Selection rule "
            f"{SELECTION_RULE_ID!r} is pre-registered on fit folds only."
        ),
    }

    artifact = {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "protocol": protocol,
        "source": {
            "report_kind": report["report_kind"],
            "report_tau_op": report["tau"]["tau_op"],
            "report_tau_k": list(report["tau"]["tau_k"]),
            "report_counts": report["counts"],
            "n_decisions": len(decisions),
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
