"""Dual-frame scoring, accepted set, bootstrap precision gate, tier report."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.bench.corpus import ItemOutcomeStore, is_detection_exhaustive, load_bench_manifest
from scripts.bench.export_map import _unwrap_rows, load_leg_exports, require_cluster_success, to_face_metric_inputs
from scripts.bench.stack_pair import BenchError, StackPairConfig, load_stack_pair
from scripts.eval_harness.face_metrics import detection_pr, identification_pr
from scripts.eval_harness.manifest import (
    AnnotationMode,
    GoldenEntry,
    GoldenManifest,
    ScoreInvariant,
    SUPPORTED_MANIFEST_VERSION,
    refusal_explanation,
)

LICENSE_BANNER = (
    "INTERNAL BENCH ONLY — insightface/buffalo_l outputs must never be user-facing "
    "or used as training data."
)

BOOTSTRAP_RESAMPLES = 2000
CI_LEVEL = 0.95

SAMPLING_FRAME_CROSSBENCH_NATIVE = "frame_fir5_native"
SAMPLING_FRAME_E2E = "frame_e2e"
LABEL_MAP_PRIMARY = "label_map_primary"
LABEL_MAP_OPTIMISTIC = "label_map_optimistic"

HOLM_NOT_COMPUTED = "not_computed"

# Persist contract for legs/<stack_id>/preflight.json (PROV-01). Score refuses
# a file that is missing, unreadable (including non-UTF-8 bytes), not a JSON
# object, or lacks these keys. Validation is key-presence only: values are
# not re-checked at score time (null opencv_major or expected≠resolved still
# pass if every key is present). The honest writer cannot emit those
# artifacts; they are reachable only via a tampered or hand-written file.
PROV01_PREFLIGHT_KEYS = (
    "stack_id",
    "base_url",
    "expected_profile",
    "expected_pgvector_dim",
    "resolved_profile",
    "resolved_pgvector_dim",
    "opencv_major",
    "opencv_major_source",
    "checked_at",
    "ready_excerpt",
    "health_detailed_excerpt",
)


class CrossbenchTier(StrEnum):
    CONFIRMATORY = "CONFIRMATORY"
    DIRECTIONAL = "DIRECTIONAL"
    DIAGNOSTIC = "DIAGNOSTIC"


@dataclass(frozen=True)
class ImageCounts:
    tp: int
    fp: int
    fn: int


@dataclass
class BootstrapInterval:
    ci_lower: float | None
    ci_upper: float | None
    ci_half_width: float | None
    ci_level: float | None = CI_LEVEL
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES
    bootstrap_seed: int = 0
    resampling_unit: str = "image"
    partial_occasions: int = 0
    p_value: float | None = None
    n_used: int = 0
    bootstrap_status: str = "ok"
    bootstrap_error: str | None = None


@dataclass
class AcceptedSet:
    manifest_media_ids: list[int]
    paths: list[str]
    content_sha256s: list[str]
    accepted_set_size: int
    detection_scoring_set: list[int]
    detection_scoring_set_size: int
    manifest_entry_count: int
    floor_config: float | int
    resolved_floor_count: int
    resampling_unit: str = "image"
    zero_detection_media_count: int = 0
    ingest_asymmetric_media: int = 0
    attrition_ingest_analyze: int = 0
    attrition_join: int = 0
    baseline_superset_checked: bool = False
    computed_at: str = ""
    join_by_stack: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)


def resolve_floor_count(accepted_set_floor: float | int, n_entries: int) -> int:
    if isinstance(accepted_set_floor, int) and not isinstance(accepted_set_floor, bool):
        return int(accepted_set_floor)
    return max(2, math.ceil(float(accepted_set_floor) * n_entries))


def stranger_faces_for(entry: GoldenEntry) -> int:
    if entry.face_count != len(entry.face_boxes):
        return 0
    return sum(1 for box in entry.face_boxes if box.name is None)


def percentile_linear(values: list[float], q: float) -> float:
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        raise ValueError("empty sample")
    if n == 1:
        return xs[0]
    k = (n - 1) * (q / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def bootstrap_paired_delta(
    a: list[Any],
    b: list[Any],
    seed: int,
    *,
    metric: str = "mean",
    occasion_ids: list[str] | None = None,
    occasion_full_size: dict[str, int] | None = None,
    accepted_mask: list[bool] | None = None,
    B: int = BOOTSTRAP_RESAMPLES,
    cell: str | None = None,
) -> BootstrapInterval:
    if len(a) != len(b):
        raise BenchError("config_invalid", "paired series must be the same length")
    n = len(a)
    if n == 0:
        raise BenchError("bootstrap_empty_series", "paired series is empty")
    del cell  # call-site label so spies can bind (cell, length) pairs
    if accepted_mask is not None and len(accepted_mask) != n:
        raise BenchError("config_invalid", "accepted_mask must match series length")
    eligible = [i for i in range(n) if accepted_mask is None or accepted_mask[i]]
    if not eligible:
        raise BenchError("bootstrap_empty_series", "accepted_mask selected no units")
    units: list[list[int]]
    partial = 0
    resampling_unit = "image"
    if occasion_ids is None:
        units = [[i] for i in eligible]
    else:
        if len(occasion_ids) != n:
            raise BenchError("config_invalid", "occasion_ids must match series length")
        groups: dict[str, list[int]] = {}
        for i in eligible:
            groups.setdefault(occasion_ids[i], []).append(i)
        full: list[list[int]] = []
        split: list[int] = []
        for oid, idxs in groups.items():
            if occasion_full_size is None:
                required = len(idxs)
            elif oid not in occasion_full_size:
                partial += 1
                split.extend(idxs)
                continue
            else:
                required = occasion_full_size[oid]
            if len(idxs) == required:
                full.append(idxs)
            else:
                partial += 1
                split.extend(idxs)
        if full and partial == 0 and not split:
            units = full
            resampling_unit = "occasion"
        elif full and (partial or split):
            units = full + [[i] for i in split]
            resampling_unit = "occasion+image"
        else:
            units = [[i] for i in eligible]
            resampling_unit = "occasion+image" if partial else "image"

    rng = random.Random(seed)
    k = len(units)
    if k == 0:
        raise BenchError("bootstrap_empty_series", "no resampling units")
    defined: list[float] = []
    n_undefined = 0
    for _ in range(B):
        picks = [units[rng.randrange(k)] for _ in range(k)]
        idxs = [i for unit in picks for i in unit]
        delta = _resample_delta(a, b, idxs, metric)
        if delta is None:
            n_undefined += 1
        else:
            defined.append(delta)
    if not defined:
        raise BenchError("bootstrap_undefined", "every resample had an undefined ratio")
    # Sample space is all B draws. An undefined micro-ratio is treated as
    # delta=0 (no evidence of a signed difference) so p and the percentile CI
    # share that space. Zeros count in both tails (d<=0 and d>=0); a partial
    # bootstrap can therefore only inflate two-sided p, never deflate it.
    # n_used stays the defined-resample count; status "partial" when n_used<B
    # so assign_tier can refuse CONFIRMATORY on an incomplete bootstrap.
    deltas = defined + [0.0] * n_undefined
    lower = percentile_linear(deltas, 2.5)
    upper = percentile_linear(deltas, 97.5)
    n_used = len(defined)
    n_le = sum(1 for d in deltas if d <= 0.0)
    n_ge = sum(1 for d in deltas if d >= 0.0)
    p_raw = 2.0 * min(n_le / B, n_ge / B)
    p_val = min(1.0, max(p_raw, 1.0 / (B + 1)))
    return BootstrapInterval(
        ci_lower=lower,
        ci_upper=upper,
        ci_half_width=(upper - lower) / 2.0,
        bootstrap_resamples=B,
        bootstrap_seed=seed,
        resampling_unit=resampling_unit,
        partial_occasions=partial,
        p_value=p_val,
        n_used=n_used,
        bootstrap_status="ok" if n_used == B else "partial",
    )


def _resample_delta(a: list[Any], b: list[Any], idxs: list[int], metric: str) -> float | None:
    if metric == "mean":
        return (sum(a[i] for i in idxs) / len(idxs)) - (sum(b[i] for i in idxs) / len(idxs))
    if metric in {"micro_recall", "micro_precision"}:
        va = _micro_ratio([a[i] for i in idxs], metric)
        vb = _micro_ratio([b[i] for i in idxs], metric)
        if va is None or vb is None:
            return None
        return va - vb
    raise BenchError("config_invalid", f"unknown bootstrap metric {metric!r}")


def _micro_ratio(counts: list[ImageCounts], metric: str) -> float | None:
    tp = sum(c.tp for c in counts)
    fp = sum(c.fp for c in counts)
    fn = sum(c.fn for c in counts)
    denom = tp + fn if metric == "micro_recall" else tp + fp
    if denom == 0:
        return None
    return tp / denom


def holm_bonferroni(
    pairs: list[tuple[str, float]],
    alpha: float = 0.05,
    *,
    family_size: int | None = None,
) -> dict[str, dict[str, Any]]:
    m = len(pairs) if family_size is None else int(family_size)
    if m <= 0:
        return {}
    if family_size is not None and family_size < len(pairs):
        raise BenchError("config_invalid", "family_size must be >= number of Holm pairs")
    ordered = sorted(pairs, key=lambda t: t[1])
    out: dict[str, dict[str, Any]] = {}
    prefix_ok = True
    for rank, (name, p_value) in enumerate(ordered, start=1):
        threshold = alpha / (m - rank + 1)
        ok = prefix_ok and p_value <= threshold
        if p_value > threshold:
            prefix_ok = False
            ok = False
        out[name] = {
            "p_value": p_value,
            "holm_rank": rank,
            "holm_threshold": threshold,
            "holm_significant": ok,
        }
    return out


def assign_tier(cell: str, ctx: dict[str, Any]) -> tuple[CrossbenchTier, str | None]:
    if ctx.get("count_only"):
        return CrossbenchTier.DIAGNOSTIC, None
    if not ctx.get("named", False):
        return CrossbenchTier.DIAGNOSTIC, None
    if not ctx.get("exhaustiveness_ok", True):
        return CrossbenchTier.DIRECTIONAL, "detection_exhaustiveness_unasserted"
    if not ctx.get("floor_ok", True):
        return CrossbenchTier.DIRECTIONAL, "accepted_set_below_floor"
    delta = float(ctx.get("head_to_head_delta", 0.0))
    if float(ctx.get("ci_half_width", math.inf)) > delta / 2.0:
        return CrossbenchTier.DIRECTIONAL, "ci_half_width_above_precision_floor"
    if ctx.get("optimistic") or "label_map_optimistic" in str(cell):
        return CrossbenchTier.DIRECTIONAL, None
    if ctx.get("native_frame") or "frame_fir5_native" in str(cell):
        return CrossbenchTier.DIRECTIONAL, "frame_fir5_native"
    confirmatory_eligible = bool(ctx.get("primary") or ctx.get("holm_significant", False))
    if confirmatory_eligible:
        if "bootstrap_status" not in ctx:
            raise BenchError(
                "bootstrap_status_missing",
                "named confirmatory-eligible cell missing bootstrap_status",
            )
        if str(ctx["bootstrap_status"]) != "ok":
            return CrossbenchTier.DIRECTIONAL, "bootstrap_status"
        return CrossbenchTier.CONFIRMATORY, None
    # Named non-significant secondaries: a partial/errored bootstrap is the
    # more specific refusal. "holm" is only the reason when status is ok.
    if "bootstrap_status" in ctx and str(ctx["bootstrap_status"]) != "ok":
        return CrossbenchTier.DIRECTIONAL, "bootstrap_status"
    return CrossbenchTier.DIRECTIONAL, "holm"


def _latest_by_phase(records: list[dict[str, Any]], media_id: int, phase: str) -> dict[str, Any] | None:
    found = None
    for rec in records:
        if rec.get("manifest_media_id") == media_id and rec.get("phase") == phase:
            found = rec
    return found


def _terminal_ingest_ok(records: list[dict[str, Any]], media_id: int) -> bool:
    ingest = _latest_by_phase(records, media_id, "ingest")
    analyze = _latest_by_phase(records, media_id, "analyze")
    # Condition (i) is the explicit terminal ingest field. Prefer the ingest
    # row so an analyze-phase error cannot invert ingest provenance.
    rec = ingest or analyze
    if rec is None:
        return False
    if ingest is None and analyze is not None and analyze.get("outcome") != "ok":
        return False
    outcome = rec.get("terminal_ingest_outcome")
    if outcome is None:
        return False
    return outcome == "success"


def _ingest_roster(records: list[dict[str, Any]]) -> set[int]:
    return {
        int(r["manifest_media_id"])
        for r in records
        if r.get("phase") == "ingest" and "manifest_media_id" in r
    }


def _analyze_ok(records: list[dict[str, Any]], media_id: int) -> dict[str, Any] | None:
    rec = _latest_by_phase(records, media_id, "analyze")
    if rec is None or rec.get("outcome") != "ok":
        return None
    mid = rec.get("stack_media_id")
    if not isinstance(mid, int):
        return None
    return rec


def _baseline_superset_checked(root: Path, pair: StackPairConfig) -> bool:
    run_path = root / "run.json"
    if run_path.is_file():
        try:
            run_doc = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run_doc = {}
        if "baseline_superset_checked" in run_doc:
            return bool(run_doc["baseline_superset_checked"])
    return False


def _load_manifest_from_run(run_dir: Path) -> GoldenManifest:
    for candidate in (run_dir / "manifest.json",):
        if candidate.is_file():
            return load_bench_manifest(candidate, None)
    run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    path = run_doc.get("manifest_path")
    if not path:
        raise BenchError("config_invalid", "run-dir has no manifest.json or manifest_path")
    return load_bench_manifest(path, None)


def _load_pair(run_dir: Path) -> StackPairConfig:
    path = run_dir / "stack_pair.yaml"
    if path.is_file():
        return load_stack_pair(path)
    # Reconstruct a minimal pair from the redacted stack_pair.json
    raw = json.loads((run_dir / "stack_pair.json").read_text(encoding="utf-8"))
    # write a temp-compatible view: we only need fields already present
    return StackPairConfig(
        stacks=tuple(),  # unused by score path that reads legs by known ids
        head_to_head_delta=float(raw["head_to_head_delta"]),
        bootstrap_seed=int(raw["bootstrap_seed"]),
        primary_endpoint=raw["primary_endpoint"],
        secondary_endpoints=tuple(raw.get("secondary_endpoints") or []),
        accepted_set_floor=raw.get("accepted_set_floor", 0.90),
        max_differential_attrition=float(raw.get("max_differential_attrition", 0.05)),
        baseline_manifest_path=raw.get("baseline_manifest_path"),
    )


def compute_accepted_set(run_dir: Path | str) -> AcceptedSet:
    root = Path(run_dir)
    manifest = _load_manifest_from_run(root)
    pair = _load_pair(root)
    from scripts.bench.corpus import assert_floor_fits_corpus

    assert_floor_fits_corpus(pair.accepted_set_floor, len(manifest.entries))
    stacks = [p.name for p in (root / "legs").iterdir() if p.is_dir()]
    records_by: dict[str, list[dict[str, Any]]] = {}
    roster_by: dict[str, set[int]] = {}
    join_by: dict[str, dict[int, dict[str, Any]]] = {}
    for stack_id in stacks:
        store = ItemOutcomeStore(root / "legs" / stack_id / "items.jsonl")
        recs = store.read_all()
        records_by[stack_id] = recs
        roster_by[stack_id] = {
            int(r["manifest_media_id"])
            for r in recs
            if r.get("phase") == "ingest" and "manifest_media_id" in r
        }
        join: dict[int, dict[str, Any]] = {}
        for entry in manifest.entries:
            rec = _analyze_ok(recs, entry.media_id)
            if rec is None:
                continue
            join[entry.media_id] = {
                "stack_media_id": rec["stack_media_id"],
                "image_width": rec.get("image_width"),
                "image_height": rec.get("image_height"),
            }
        join_by[stack_id] = join

    accepted: list[GoldenEntry] = []
    attrition_ia = 0
    attrition_join = 0
    ingest_asym = 0
    for entry in manifest.entries:
        mid = entry.media_id
        ok_both = True
        ia_fail = False
        join_fail = False
        present = []
        for stack_id in stacks:
            recs = records_by[stack_id]
            in_roster = mid in roster_by[stack_id]
            present.append(in_roster)
            ingest_ok = _terminal_ingest_ok(recs, mid)
            analyze = _analyze_ok(recs, mid)
            if not ingest_ok or analyze is None:
                ia_fail = True
                ok_both = False
            if not in_roster:
                join_fail = True
                ok_both = False
        if present.count(True) == 1:
            ingest_asym += 1
        if ok_both:
            accepted.append(entry)
        else:
            if ia_fail:
                attrition_ia += 1
            elif join_fail:
                attrition_join += 1

    # Document-level mode wins (sr-007): entry-level box/count match is not
    # exhaustiveness when annotation_mode is roster_only. Route through the
    # same resolver score_head_to_head uses so the accepted-set artifact
    # agrees with refused detection cells (rg-015).
    candidate_entries = [e for e in accepted if is_detection_exhaustive(e)]
    detection_manifest = _subset_manifest(manifest, candidate_entries)
    if _detection_score_mode(detection_manifest, manifest) is not AnnotationMode.EXHAUSTIVE:
        detection_set: list[int] = []
    else:
        detection_set = [e.media_id for e in candidate_entries]
    zero_det = 0
    exports_by = {stack_id: load_leg_exports(root, stack_id) for stack_id in stacks}
    for entry in accepted:
        for stack_id in stacks:
            export = exports_by[stack_id]
            rows = _unwrap_rows(export.media_identities, what="media_identities")
            stack_mid = join_by[stack_id][entry.media_id]["stack_media_id"]
            if not any(isinstance(r, dict) and r.get("media_id") == stack_mid for r in rows):
                zero_det += 1
                break

    # export rows not in roster → fail closed (stack_media_id domain only)
    for stack_id in stacks:
        export = exports_by[stack_id]
        rows = _unwrap_rows(export.media_identities, what="media_identities")
        roster_stack_ids = {
            rec.get("stack_media_id")
            for rec in records_by[stack_id]
            if rec.get("phase") == "analyze" and rec.get("outcome") == "ok"
        }
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("media_id"), int):
                if row["media_id"] not in roster_stack_ids:
                    raise BenchError(
                        "export_media_not_in_roster",
                        f"{stack_id} export media_id {row['media_id']} not in roster",
                    )

    n = len(manifest.entries)
    return AcceptedSet(
        manifest_media_ids=[e.media_id for e in accepted],
        paths=[e.path for e in accepted],
        content_sha256s=[e.sha256 for e in accepted],
        accepted_set_size=len(accepted),
        detection_scoring_set=detection_set,
        detection_scoring_set_size=len(detection_set),
        manifest_entry_count=n,
        floor_config=pair.accepted_set_floor,
        resolved_floor_count=resolve_floor_count(pair.accepted_set_floor, n),
        zero_detection_media_count=zero_det,
        ingest_asymmetric_media=ingest_asym,
        attrition_ingest_analyze=attrition_ia,
        attrition_join=attrition_join,
        baseline_superset_checked=_baseline_superset_checked(root, pair),
        computed_at=datetime.now(timezone.utc).isoformat(),
        join_by_stack=join_by,
    )


def write_accepted_set(run_dir: Path, accepted: AcceptedSet) -> Path:
    dest = Path(run_dir) / "score" / "accepted_set.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_media_ids": accepted.manifest_media_ids,
        "paths": accepted.paths,
        "content_sha256s": accepted.content_sha256s,
        "accepted_set_size": accepted.accepted_set_size,
        "detection_scoring_set_size": accepted.detection_scoring_set_size,
        "manifest_entry_count": accepted.manifest_entry_count,
        "floor_config": accepted.floor_config,
        "resolved_floor_count": accepted.resolved_floor_count,
        "resampling_unit": accepted.resampling_unit,
        "computed_at": accepted.computed_at,
        "license_banner": LICENSE_BANNER,
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def write_attrition(run_dir: Path, accepted: AcceptedSet, manifest: GoldenManifest, records_by: dict[str, list]) -> Path:
    dest = Path(run_dir) / "score" / "attrition.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    missing = []
    accepted_ids = set(accepted.manifest_media_ids)
    stacks = list(records_by)
    for entry in manifest.entries:
        if entry.media_id in accepted_ids:
            continue
        phase = "analyze"
        for stack_id in stacks:
            recs = records_by[stack_id]
            if not _terminal_ingest_ok(recs, entry.media_id):
                phase = "ingest"
                break
            if _analyze_ok(recs, entry.media_id) is None:
                phase = "analyze"
                break
            ingest_roster = {
                int(r["manifest_media_id"])
                for r in recs
                if r.get("phase") == "ingest" and "manifest_media_id" in r
            }
            if entry.media_id not in ingest_roster:
                phase = "roster"
                break
        missing.append({"manifest_media_id": entry.media_id, "phase": phase})
    one_sided = {}
    for stack_id, recs in records_by.items():
        ids = []
        for entry in manifest.entries:
            if (
                _terminal_ingest_ok(recs, entry.media_id)
                and _analyze_ok(recs, entry.media_id) is not None
                and entry.media_id in _ingest_roster(recs)
                and entry.media_id not in accepted_ids
            ):
                ids.append(entry.media_id)
        one_sided[stack_id] = ids
    payload = {
        "missing": missing,
        "one_sided": one_sided,
        "attrition_ingest_analyze": accepted.attrition_ingest_analyze,
        "attrition_join": accepted.attrition_join,
        "ingest_asymmetric_media": accepted.ingest_asymmetric_media,
        "license_banner": LICENSE_BANNER,
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def build_dual_frames(
    export: Any,
    manifest: GoldenManifest,
    join: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    frames: dict[str, Any] = {}
    for frame in ("native", "e2e"):
        for label in ("primary", "optimistic"):
            det, ident = to_face_metric_inputs(export, manifest, join, label, frame=frame)  # type: ignore[arg-type]
            frames[f"{frame}/{label}"] = {"detection": det, "identification": ident}
    return frames


def _pr_payload(result: Any) -> dict[str, Any]:
    return {
        "precision": result.precision,
        "recall": result.recall,
        "true_positives": result.true_positives,
        "false_positives": result.false_positives,
        "false_negatives": result.false_negatives,
    }


def _subset_manifest(
    manifest: GoldenManifest, entries: list[GoldenEntry]
) -> GoldenManifest | None:
    """Rebuild a v3 document over a scored subset. Mode is the parent's.

    ADR-015: annotation_mode is document-level. A subset never widens
    roster_only to exhaustive.
    """
    if not entries:
        return None
    return GoldenManifest(
        manifest_version=SUPPORTED_MANIFEST_VERSION,
        annotation_mode=manifest.annotation_mode,
        roster=list(manifest.roster),
        entries=entries,
        roster_cohorts=dict(manifest.roster_cohorts),
    )


def _detection_score_mode(detection_manifest: GoldenManifest | None, parent: GoldenManifest) -> AnnotationMode:
    """Mode of the document whose entries are detection-scored (ADR-015)."""
    source = detection_manifest if detection_manifest is not None else parent
    return source.annotation_mode


def _detection_refusal_invariant(mode: AnnotationMode) -> ScoreInvariant:
    if mode is AnnotationMode.ROSTER_ONLY:
        return ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    return ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE


def _refused_detection_payload(invariant: ScoreInvariant) -> dict[str, Any]:
    return {
        "refused": True,
        "invariant": invariant.value,
        "reason": refusal_explanation(invariant),
        "value": None,
        "precision": None,
        "recall": None,
        "true_positives": None,
        "false_positives": None,
        "false_negatives": None,
    }


def _detection_counts(item: Any) -> ImageCounts:
    if item.matched_faces is None:
        tp = min(item.pred_faces, item.labeled_faces)
        return ImageCounts(tp, max(item.pred_faces - item.labeled_faces, 0), max(item.labeled_faces - item.pred_faces, 0))
    matched = item.matched_faces
    return ImageCounts(matched, max(item.pred_faces - matched, 0), max(item.labeled_faces - matched, 0))


def _ident_counts(item: Any) -> ImageCounts | None:
    if not item.recognition_enabled:
        return None
    predicted = set(item.predicted)
    labeled = set(item.labeled)
    return ImageCounts(len(predicted & labeled), len(predicted - labeled), len(labeled - predicted))


def _cell_id(metric: str, frame_key: str, label_key: str) -> str:
    frame = SAMPLING_FRAME_E2E if frame_key == "e2e" else SAMPLING_FRAME_CROSSBENCH_NATIVE
    label = LABEL_MAP_PRIMARY if label_key == "primary" else LABEL_MAP_OPTIMISTIC
    return f"{metric}@{frame}/{label}"


def _require_prov01_preflights(root: Path, stacks: list[str]) -> bool:
    missing = [
        stack_id for stack_id in stacks if not (root / "legs" / stack_id / "preflight.json").is_file()
    ]
    if missing:
        raise BenchError(
            "preflight_missing",
            "preflight.json missing for "
            + ", ".join(missing)
            + "; score refuses a run-dir without PROV-01",
        )
    for stack_id in stacks:
        path = root / "legs" / stack_id / "preflight.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BenchError(
                "preflight_invalid",
                f"{stack_id} preflight.json is not valid JSON",
            ) from exc
        if not isinstance(doc, dict):
            raise BenchError(
                "preflight_invalid",
                f"{stack_id} preflight.json must be a JSON object",
            )
        absent = [key for key in PROV01_PREFLIGHT_KEYS if key not in doc]
        if absent:
            raise BenchError(
                "preflight_invalid",
                f"{stack_id} preflight.json missing PROV-01 keys: " + ", ".join(absent),
            )
    return True


def score_head_to_head(run_dir: Path | str) -> Path:
    root = Path(run_dir)
    manifest = _load_manifest_from_run(root)
    pair = _load_pair(root)
    stacks = sorted(p.name for p in (root / "legs").iterdir() if p.is_dir())
    preflight_present = _require_prov01_preflights(root, stacks)
    for stack_id in stacks:
        require_cluster_success(root, stack_id)
    (root / "score").mkdir(parents=True, exist_ok=True)

    accepted = compute_accepted_set(root)
    write_accepted_set(root, accepted)
    records_by = {
        stack_id: ItemOutcomeStore(root / "legs" / stack_id / "items.jsonl").read_all() for stack_id in stacks
    }
    write_attrition(root, accepted, manifest, records_by)

    # Differential attrition: |one-sided-A − one-sided-B| / |manifest|
    one_sided_counts = []
    for stack_id in stacks:
        recs = records_by[stack_id]
        n_os = 0
        for entry in manifest.entries:
            ok = (
                _terminal_ingest_ok(recs, entry.media_id)
                and _analyze_ok(recs, entry.media_id) is not None
                and entry.media_id in _ingest_roster(recs)
                and entry.media_id not in accepted.manifest_media_ids
            )
            if ok:
                n_os += 1
        one_sided_counts.append(n_os)
    if len(one_sided_counts) == 2:
        skew = abs(one_sided_counts[0] - one_sided_counts[1]) / max(1, accepted.manifest_entry_count)
        if skew > pair.max_differential_attrition:
            header = {
                "error_code": "differential_attrition_exceeded",
                "license_banner": LICENSE_BANNER,
                "pr_cells_emitted": False,
                "cells": [],
            }
            (root / "score" / "frames.json").write_text(json.dumps(header, indent=2), encoding="utf-8")
            raise BenchError("differential_attrition_exceeded", "one-sided attrition exceeds max_differential_attrition")

    accepted_entries = [e for e in manifest.entries if e.media_id in set(accepted.manifest_media_ids)]
    detection_entries = [e for e in accepted_entries if e.media_id in set(accepted.detection_scoring_set)]
    detection_ids = set(accepted.detection_scoring_set)
    exhaustiveness_ok = len(detection_ids) == len(accepted_entries)
    floor_ok = accepted.accepted_set_size >= accepted.resolved_floor_count
    named = {pair.primary_endpoint, *pair.secondary_endpoints}

    path_to_mid: dict[str, int] = {}
    for entry in manifest.entries:
        if entry.path in path_to_mid and path_to_mid[entry.path] != entry.media_id:
            raise BenchError(
                "duplicate_manifest_path",
                f"manifest path {entry.path!r} maps to multiple media_ids",
            )
        path_to_mid[entry.path] = entry.media_id
    counts_by: dict[str, dict[str, list[ImageCounts]]] = {cell: {s: [] for s in stacks} for cell in named}
    cells: list[dict[str, Any]] = []

    for stack_id in stacks:
        export = load_leg_exports(root, stack_id)
        join = {
            mid: info
            for mid, info in accepted.join_by_stack.get(stack_id, {}).items()
            if mid in set(accepted.manifest_media_ids)
        }
        accepted_manifest = _subset_manifest(manifest, accepted_entries)
        detection_manifest = _subset_manifest(manifest, detection_entries)
        detection_mode = _detection_score_mode(detection_manifest, manifest)
        detection_refused = detection_mode is not AnnotationMode.EXHAUSTIVE
        export_payload = {
            "media_identities": export.media_identities,
            "clusters": export.clusters,
            "cluster_members": export.cluster_members,
        }
        for frame_key, frame_name in (("e2e", SAMPLING_FRAME_E2E), ("native", SAMPLING_FRAME_CROSSBENCH_NATIVE)):
            for label_key, label_name in (("primary", LABEL_MAP_PRIMARY), ("optimistic", LABEL_MAP_OPTIMISTIC)):
                ident: list[Any] = []
                if accepted_manifest is not None:
                    _, ident = to_face_metric_inputs(
                        export_payload,
                        accepted_manifest,
                        join,
                        label_key,
                        frame=frame_key,  # type: ignore[arg-type]
                    )
                det: list[Any] = []
                if detection_manifest is not None and not detection_refused:
                    det, _ = to_face_metric_inputs(
                        export_payload,
                        detection_manifest,
                        join,
                        label_key,
                        frame=frame_key,  # type: ignore[arg-type]
                    )
                if detection_refused:
                    det_matched = None
                    det_count = None
                else:
                    det_matched = detection_pr(det, annotation_mode=detection_mode)
                    det_count = detection_pr(
                        [
                            type(d)(image=d.image, pred_faces=d.pred_faces, labeled_faces=d.labeled_faces)
                            for d in det
                        ],
                        annotation_mode=detection_mode,
                    )
                ident_pr = identification_pr(ident)
                det_by_mid: dict[int, Any] = {}
                for det_row in det:
                    mid = path_to_mid.get(det_row.image)
                    if mid is None:
                        raise BenchError(
                            "join_row_missing",
                            f"detection row path {det_row.image!r} is not in the manifest",
                        )
                    det_by_mid[mid] = det_row
                ident_by_mid: dict[int, Any] = {}
                for ident_row in ident:
                    mid = path_to_mid.get(ident_row.image)
                    if mid is None:
                        raise BenchError(
                            "join_row_missing",
                            f"identification row path {ident_row.image!r} is not in the manifest",
                        )
                    ident_by_mid[mid] = ident_row
                for metric, result, population in (
                    ("detection_recall", det_matched, detection_entries),
                    ("detection_precision", det_matched, detection_entries),
                    ("identification_recall", ident_pr, accepted_entries),
                    ("identification_precision", ident_pr, accepted_entries),
                ):
                    cell = _cell_id(metric, frame_key, label_key)
                    if metric.startswith("detection") and detection_refused:
                        cells.append(
                            {
                                "cell": cell,
                                "stack_id": stack_id,
                                "frame": frame_name,
                                "label_map": label_name,
                                "metric": metric,
                                "tier": CrossbenchTier.DIAGNOSTIC.value,
                                **_refused_detection_payload(
                                    _detection_refusal_invariant(detection_mode)
                                ),
                                "_frame_key": frame_key,
                                "_label_key": label_key,
                                "_refused": True,
                            }
                        )
                        continue
                    if cell in counts_by:
                        series: list[ImageCounts] = []
                        for entry in population:
                            if metric.startswith("detection"):
                                row = det_by_mid.get(entry.media_id)
                                if row is None:
                                    raise BenchError(
                                        "join_row_missing",
                                        f"detection population media_id={entry.media_id} has no metric row",
                                    )
                                series.append(_detection_counts(row))
                            else:
                                row = ident_by_mid.get(entry.media_id)
                                if row is None:
                                    raise BenchError(
                                        "join_row_missing",
                                        f"identification population media_id={entry.media_id} has no metric row",
                                    )
                                counted = _ident_counts(row)
                                if counted is not None:
                                    series.append(counted)
                        counts_by[cell][stack_id] = series
                    cells.append(
                        {
                            "cell": cell,
                            "stack_id": stack_id,
                            "frame": frame_name,
                            "label_map": label_name,
                            "metric": metric,
                            "value": result.recall if metric.endswith("recall") else result.precision,
                            **_pr_payload(result),
                            "_frame_key": frame_key,
                            "_label_key": label_key,
                            "_is_detection": metric.startswith("detection_"),
                        }
                    )
                if detection_refused:
                    cells.append(
                        {
                            "cell": f"detection_count_only@{frame_name}/{label_name}",
                            "stack_id": stack_id,
                            "tier": CrossbenchTier.DIAGNOSTIC.value,
                            "count_only": True,
                            **_refused_detection_payload(
                                _detection_refusal_invariant(detection_mode)
                            ),
                        }
                    )
                else:
                    cells.append(
                        {
                            "cell": f"detection_count_only@{frame_name}/{label_name}",
                            "stack_id": stack_id,
                            "tier": CrossbenchTier.DIAGNOSTIC.value,
                            "count_only": True,
                            **_pr_payload(det_count),
                        }
                    )

    intervals: dict[str, BootstrapInterval] = {}
    bootstrap_errors: dict[str, BenchError] = {}
    if len(stacks) == 2:
        for cell_name, by_stack in counts_by.items():
            series_a = by_stack.get(stacks[0]) or []
            series_b = by_stack.get(stacks[1]) or []
            if not series_a or not series_b or len(series_a) != len(series_b):
                if cell_name in named:
                    bootstrap_errors[cell_name] = BenchError(
                        "bootstrap_series_mismatch",
                        f"{cell_name} series missing or length-mismatched",
                    )
                continue
            boot_metric = "micro_recall" if cell_name.startswith("identification_recall") or cell_name.startswith("detection_recall") else "micro_precision"
            try:
                intervals[cell_name] = bootstrap_paired_delta(
                    series_a,
                    series_b,
                    seed=pair.bootstrap_seed,
                    metric=boot_metric,
                    cell=cell_name,
                )
            except BenchError as exc:
                bootstrap_errors[cell_name] = exc

    holm: dict[str, dict[str, Any]] = {}
    declared_secondaries = list(pair.secondary_endpoints)
    holm_missing: set[str] = set()
    if declared_secondaries:
        padded: list[tuple[str, float]] = []
        for cell_name in declared_secondaries:
            interval = intervals.get(cell_name)
            if interval is None or interval.p_value is None:
                padded.append((cell_name, 1.0))
                holm_missing.add(cell_name)
            else:
                padded.append((cell_name, float(interval.p_value)))
        holm = holm_bonferroni(padded, family_size=len(declared_secondaries))

    for cell in cells:
        if cell.get("count_only") or cell.pop("_refused", False):
            cell.pop("_frame_key", None)
            cell.pop("_label_key", None)
            continue
        name = cell["cell"]
        interval = intervals.get(name)
        holm_info = holm.get(name)
        half_width: float | None = interval.ci_half_width if interval is not None else None
        if interval is not None:
            boot_status = interval.bootstrap_status
        elif name in bootstrap_errors:
            boot_status = bootstrap_errors[name].code
        elif name in named:
            boot_status = "not_computed"
        else:
            # Unnamed cells exit DIAGNOSTIC at assign_tier's named-check
            # before bootstrap_status is consulted; this stamp is inert.
            boot_status = "ok"
        ctx = {
            "named": name in named,
            "primary": name == pair.primary_endpoint,
            "optimistic": cell.pop("_label_key") == "optimistic",
            "native_frame": cell.pop("_frame_key") == "native",
            "floor_ok": floor_ok,
            "ci_half_width": half_width if half_width is not None else math.inf,
            "head_to_head_delta": pair.head_to_head_delta,
            "holm_significant": bool(holm_info["holm_significant"]) if holm_info and name not in holm_missing else False,
            "exhaustiveness_ok": exhaustiveness_ok,
            "count_only": False,
            "bootstrap_status": boot_status,
        }
        cell.pop("_is_detection", None)
        tier, reason = assign_tier(name, ctx)
        cell["tier"] = tier.value
        cell["reason"] = reason
        if interval is not None:
            cell["bootstrap_resamples"] = interval.bootstrap_resamples
            cell["bootstrap_seed"] = interval.bootstrap_seed
            cell["resampling_unit"] = interval.resampling_unit
            cell["p_value"] = interval.p_value
            cell["partial_occasions"] = interval.partial_occasions
            cell["bootstrap_status"] = interval.bootstrap_status
            cell["bootstrap_n_used"] = interval.n_used
            # Partial/errored bootstrap: do not publish a zero-imputed collapsed
            # interval as if it were a real CI. p still uses the padded space.
            if interval.bootstrap_status == "ok":
                cell["ci_level"] = interval.ci_level
                cell["ci_lower"] = interval.ci_lower
                cell["ci_upper"] = interval.ci_upper
                cell["ci_half_width"] = interval.ci_half_width
            else:
                # Partial/errored: no published interval. Floor/p used the
                # padded B-draw space via ctx; do not stamp a real ci_level
                # beside null CI bounds.
                cell["ci_level"] = None
                cell["ci_lower"] = None
                cell["ci_upper"] = None
                cell["ci_half_width"] = None
        else:
            cell["ci_level"] = None
            cell["ci_lower"] = None
            cell["ci_upper"] = None
            cell["ci_half_width"] = None
            cell["bootstrap_resamples"] = None
            cell["p_value"] = None
            err = bootstrap_errors.get(name)
            if err is not None:
                cell["bootstrap_status"] = err.code
                cell["bootstrap_error"] = str(err)
            elif name in named:
                cell["bootstrap_status"] = "not_computed"
        if holm_info is not None:
            cell["holm_p_value"] = holm_info["p_value"]
            if name not in holm_missing:
                cell.update({k: holm_info[k] for k in ("holm_rank", "holm_threshold", "holm_significant")})
            else:
                cell["holm_significant"] = False
                cell["holm_status"] = HOLM_NOT_COMPUTED
        # holm_bonferroni pads every declared secondary, so holm_info is
        # never None for one. No elif fallback.


    frames = {
        "license_banner": LICENSE_BANNER,
        "cells": cells,
        "accepted_set_size": accepted.accepted_set_size,
        "detection_scoring_set_size": accepted.detection_scoring_set_size,
        "resolved_floor_count": accepted.resolved_floor_count,
        "floor_config": accepted.floor_config,
        "manifest_entry_count": accepted.manifest_entry_count,
        "zero_detection_media_count": accepted.zero_detection_media_count,
        "ingest_asymmetric_media": accepted.ingest_asymmetric_media,
        "attrition_ingest_analyze": accepted.attrition_ingest_analyze,
        "attrition_join": accepted.attrition_join,
        "baseline_superset_checked": accepted.baseline_superset_checked,
        "bootstrap_seed": pair.bootstrap_seed,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "ci_level": CI_LEVEL,
        "resampling_unit": "image",
        "pr_cells_emitted": True,
        # present-and-structurally-valid (keys present). Not a mere existence
        # flag; _require_prov01_preflights only returns True or raises.
        "preflight_present": preflight_present,
    }
    frames_path = root / "score" / "frames.json"
    frames_path.write_text(json.dumps(frames, indent=2), encoding="utf-8")

    html = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>FIR-8 crossbench</title></head><body>",
        f"<h1>Cross-stack bench</h1><p>{LICENSE_BANNER}</p>",
        f"<p>accepted_set_size={accepted.accepted_set_size} resolved_floor_count={accepted.resolved_floor_count}</p>",
        "<table border='1'><tr><th>cell</th><th>stack</th><th>tier</th><th>value</th><th>reason</th></tr>",
    ]
    for cell in cells:
        html.append(
            "<tr>"
            f"<td>{cell.get('cell')}</td><td>{cell.get('stack_id')}</td>"
            f"<td>{cell.get('tier')}</td><td>{cell.get('value')}</td>"
            f"<td>{cell.get('reason')}</td></tr>"
        )
    html.append("</table></body></html>")
    report = root / "score" / "report.html"
    report.write_text("\n".join(html), encoding="utf-8")
    return report
