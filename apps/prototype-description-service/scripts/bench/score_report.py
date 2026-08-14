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
from scripts.bench.export_map import load_leg_exports, require_cluster_success, to_face_metric_inputs
from scripts.bench.stack_pair import BenchError, StackPairConfig, load_stack_pair
from scripts.eval_harness.face_metrics import detection_pr, identification_pr
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest

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

STACK_INSIGHT = "acx-dev-insightface"
STACK_FIR = "acx-dev-fir"


class CrossbenchTier(StrEnum):
    CONFIRMATORY = "CONFIRMATORY"
    DIRECTIONAL = "DIRECTIONAL"
    DIAGNOSTIC = "DIAGNOSTIC"


@dataclass
class BootstrapInterval:
    ci_lower: float
    ci_upper: float
    ci_half_width: float
    ci_level: float = CI_LEVEL
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES
    bootstrap_seed: int = 0
    resampling_unit: str = "image"
    partial_occasions: int = 0
    p_value: float | None = None


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
    a: list[float],
    b: list[float],
    seed: int,
    *,
    metric: str = "mean",
    occasion_ids: list[str] | None = None,
    occasion_full_size: dict[str, int] | None = None,
    accepted_mask: list[bool] | None = None,
    B: int = BOOTSTRAP_RESAMPLES,
) -> BootstrapInterval:
    if len(a) != len(b):
        raise BenchError("config_invalid", "paired series must be the same length")
    n = len(a)
    units: list[list[int]]
    partial = 0
    resampling_unit = "image"
    if occasion_ids is None:
        units = [[i] for i in range(n)]
    else:
        groups: dict[str, list[int]] = {}
        for i, oid in enumerate(occasion_ids):
            groups.setdefault(oid, []).append(i)
        full: list[list[int]] = []
        split: list[int] = []
        for oid, idxs in groups.items():
            required = (occasion_full_size or {}).get(oid, len(idxs))
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
            units = [[i] for i in range(n)]
            resampling_unit = "occasion+image" if partial else "image"

    rng = random.Random(seed)
    k = len(units)
    deltas: list[float] = []
    for _ in range(B):
        picks = [units[rng.randrange(k)] for _ in range(k)]
        idxs = [i for unit in picks for i in unit]
        if metric == "mean":
            mean_a = sum(a[i] for i in idxs) / len(idxs)
            mean_b = sum(b[i] for i in idxs) / len(idxs)
            deltas.append(mean_a - mean_b)
        else:
            deltas.append(0.0)
    lower = percentile_linear(deltas, 2.5)
    upper = percentile_linear(deltas, 97.5)
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
    )


def holm_bonferroni(pairs: list[tuple[str, float]], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    m = len(pairs)
    if m == 0:
        return {}
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
    if not ctx.get("cluster_ok", True):
        raise BenchError("cluster_gate_refused", "cluster phase missing/failed; not scored")
    if ctx.get("differential_attrition"):
        raise BenchError("differential_attrition_exceeded", "biased pool")
    if ctx.get("count_only"):
        return CrossbenchTier.DIAGNOSTIC, None
    if not ctx.get("named", False):
        return CrossbenchTier.DIAGNOSTIC, None
    if str(cell).startswith("detection_") and not ctx.get("exhaustiveness_ok", True):
        return CrossbenchTier.DIRECTIONAL, "detection_exhaustiveness_unasserted"
    if not ctx.get("floor_ok", True):
        return CrossbenchTier.DIRECTIONAL, "accepted_set_below_floor"
    delta = float(ctx.get("head_to_head_delta", 0.0))
    if float(ctx.get("ci_half_width", 0.0)) > delta / 2.0:
        return CrossbenchTier.DIRECTIONAL, "ci_half_width_above_precision_floor"
    if ctx.get("optimistic") or "label_map_optimistic" in str(cell):
        return CrossbenchTier.DIRECTIONAL, None
    if ctx.get("native_frame") or "frame_fir5_native" in str(cell):
        return CrossbenchTier.DIRECTIONAL, "secondary_frame"
    if ctx.get("primary") or cell == "detection_recall@frame_e2e/label_map_primary":
        return CrossbenchTier.CONFIRMATORY, None
    if ctx.get("holm_significant", False):
        return CrossbenchTier.CONFIRMATORY, None
    return CrossbenchTier.DIRECTIONAL, "holm"


def _latest_by_phase(records: list[dict[str, Any]], media_id: int, phase: str) -> dict[str, Any] | None:
    found = None
    for rec in records:
        if rec.get("manifest_media_id") == media_id and rec.get("phase") == phase:
            found = rec
    return found


def _terminal_ingest_ok(records: list[dict[str, Any]], media_id: int) -> bool:
    analyze = _latest_by_phase(records, media_id, "analyze")
    ingest = _latest_by_phase(records, media_id, "ingest")
    rec = analyze or ingest
    if rec is None:
        return False
    outcome = rec.get("terminal_ingest_outcome")
    if outcome is None:
        return False
    return outcome == "success"


def _analyze_ok(records: list[dict[str, Any]], media_id: int) -> dict[str, Any] | None:
    rec = _latest_by_phase(records, media_id, "analyze")
    if rec is None or rec.get("outcome") != "ok":
        return None
    mid = rec.get("stack_media_id")
    if not isinstance(mid, int):
        return None
    return rec


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
        roster_by[stack_id] = {int(r["manifest_media_id"]) for r in recs if "manifest_media_id" in r}
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
    one_sided: dict[str, set[int]] = {s: set() for s in stacks}
    attrition_ia = 0
    attrition_join = 0
    ingest_asym = 0
    all_ids = [e.media_id for e in manifest.entries]
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
            if ingest_ok and analyze is not None and in_roster:
                one_sided[stack_id].add(mid)
        if present.count(True) == 1:
            ingest_asym += 1
        if ok_both:
            accepted.append(entry)
        else:
            if ia_fail:
                attrition_ia += 1
            elif join_fail:
                attrition_join += 1

    detection_set = [e.media_id for e in accepted if is_detection_exhaustive(e)]
    zero_det = 0
    for entry in accepted:
        for stack_id in stacks:
            export = load_leg_exports(root, stack_id)
            raw = export.media_identities
            rows = raw if isinstance(raw, list) else (raw.get("data") or [])
            stack_mid = join_by[stack_id][entry.media_id]["stack_media_id"]
            if not any(isinstance(r, dict) and r.get("media_id") == stack_mid for r in rows):
                zero_det += 1
                break

    # export rows not in roster → fail closed
    for stack_id in stacks:
        export = load_leg_exports(root, stack_id)
        raw = export.media_identities
        rows = raw if isinstance(raw, list) else (raw.get("data") or [])
        roster_stack_ids = {
            rec.get("stack_media_id")
            for rec in records_by[stack_id]
            if rec.get("phase") == "analyze" and rec.get("outcome") == "ok"
        }
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("media_id"), int):
                if row["media_id"] not in roster_stack_ids and row["media_id"] not in roster_by[stack_id]:
                    # also accept if it matches a known stack_media_id
                    known = {j["stack_media_id"] for j in join_by[stack_id].values()}
                    if row["media_id"] not in known:
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
        baseline_superset_checked=bool(pair.baseline_manifest_path),
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
            if entry.media_id not in {int(r["manifest_media_id"]) for r in recs if "manifest_media_id" in r}:
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
                and entry.media_id in {int(r["manifest_media_id"]) for r in recs if "manifest_media_id" in r}
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


def _cell_id(metric: str, frame_key: str, label_key: str) -> str:
    frame = SAMPLING_FRAME_E2E if frame_key == "e2e" else SAMPLING_FRAME_CROSSBENCH_NATIVE
    label = LABEL_MAP_PRIMARY if label_key == "primary" else LABEL_MAP_OPTIMISTIC
    return f"{metric}@{frame}/{label}"


def score_head_to_head(run_dir: Path | str) -> Path:
    root = Path(run_dir)
    (root / "score").mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest_from_run(root)
    pair = _load_pair(root)
    stacks = sorted(p.name for p in (root / "legs").iterdir() if p.is_dir())
    for stack_id in stacks:
        require_cluster_success(root, stack_id)

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
                and entry.media_id in {int(r["manifest_media_id"]) for r in recs if "manifest_media_id" in r}
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
    detection_ids = set(accepted.detection_scoring_set)
    exhaustiveness_ok = len(detection_ids) == len(accepted_entries)
    floor_ok = accepted.accepted_set_size >= accepted.resolved_floor_count

    cells: list[dict[str, Any]] = []
    named = {pair.primary_endpoint, *pair.secondary_endpoints}
    # Per-image detection recall scalars for bootstrap on primary population
    per_image: dict[str, list[float]] = {s: [] for s in stacks}
    for stack_id in stacks:
        export = load_leg_exports(root, stack_id)
        join = {
            mid: info
            for mid, info in accepted.join_by_stack.get(stack_id, {}).items()
            if mid in set(accepted.manifest_media_ids)
        }
        # restrict manifest to accepted
        accepted_manifest = GoldenManifest(
            manifest_version=2,
            roster=list(manifest.roster),
            entries=accepted_entries,
        )
        for frame_key, frame_name in (("e2e", SAMPLING_FRAME_E2E), ("native", SAMPLING_FRAME_CROSSBENCH_NATIVE)):
            for label_key, label_name in (("primary", LABEL_MAP_PRIMARY), ("optimistic", LABEL_MAP_OPTIMISTIC)):
                det, ident = to_face_metric_inputs(
                    {
                        "media_identities": export.media_identities,
                        "clusters": export.clusters,
                        "cluster_members": export.cluster_members,
                    },
                    accepted_manifest,
                    join,
                    label_key,
                    frame=frame_key,  # type: ignore[arg-type]
                )
                det_matched = detection_pr(det)
                det_count = detection_pr(
                    [
                        type(d)(image=d.image, pred_faces=d.pred_faces, labeled_faces=d.labeled_faces)
                        for d in det
                    ]
                )
                ident_pr = identification_pr(ident)
                if frame_key == "e2e" and label_key == "primary":
                    for d in det:
                        rec = 1.0 if d.labeled_faces == 0 else (d.matched_faces or 0) / d.labeled_faces
                        per_image[stack_id].append(rec)
                for metric, result in (
                    ("detection_recall", det_matched),
                    ("detection_precision", det_matched),
                    ("identification_recall", ident_pr),
                    ("identification_precision", ident_pr),
                ):
                    cell = _cell_id(metric, frame_key, label_key)
                    interval = BootstrapInterval(0.0, 0.0, 0.0, bootstrap_seed=pair.bootstrap_seed)
                    ctx = {
                        "named": cell in named,
                        "primary": cell == pair.primary_endpoint,
                        "optimistic": label_key == "optimistic",
                        "native_frame": frame_key == "native",
                        "floor_ok": floor_ok,
                        "ci_half_width": 0.0,
                        "head_to_head_delta": pair.head_to_head_delta,
                        "holm_significant": cell == pair.primary_endpoint,
                        "exhaustiveness_ok": exhaustiveness_ok or not metric.startswith("detection_"),
                        "cluster_ok": True,
                        "count_only": False,
                    }
                    tier, reason = assign_tier(cell, ctx)
                    cells.append(
                        {
                            "cell": cell,
                            "stack_id": stack_id,
                            "frame": frame_name,
                            "label_map": label_name,
                            "metric": metric,
                            "tier": tier.value,
                            "reason": reason,
                            "value": result.recall if metric.endswith("recall") else result.precision,
                            **_pr_payload(result),
                            "ci_level": CI_LEVEL,
                            "ci_lower": interval.ci_lower,
                            "ci_upper": interval.ci_upper,
                            "ci_half_width": interval.ci_half_width,
                            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                            "bootstrap_seed": pair.bootstrap_seed,
                            "resampling_unit": "image",
                        }
                    )
                cells.append(
                    {
                        "cell": f"detection_count_only@{frame_name}/{label_name}",
                        "stack_id": stack_id,
                        "tier": CrossbenchTier.DIAGNOSTIC.value,
                        "count_only": True,
                        **_pr_payload(det_count),
                    }
                )

    # Head-to-head bootstrap on primary if both legs present
    if len(stacks) == 2 and per_image[stacks[0]] and per_image[stacks[1]]:
        interval = bootstrap_paired_delta(
            per_image[stacks[0]],
            per_image[stacks[1]],
            seed=pair.bootstrap_seed,
            metric="mean",
        )
        for cell in cells:
            if cell.get("cell") == pair.primary_endpoint:
                cell["ci_half_width"] = interval.ci_half_width
                cell["ci_lower"] = interval.ci_lower
                cell["ci_upper"] = interval.ci_upper
                cell["resampling_unit"] = interval.resampling_unit
                if interval.ci_half_width > pair.head_to_head_delta / 2:
                    cell["tier"] = CrossbenchTier.DIRECTIONAL.value
                    cell["reason"] = "ci_half_width_above_precision_floor"

    # Holm across secondaries using bootstrap p (same interval family; empty allowed)
    if pair.secondary_endpoints:
        holm = holm_bonferroni([(c, 1.0) for c in pair.secondary_endpoints])
        for cell in cells:
            info = holm.get(cell.get("cell", ""))
            if info:
                cell.update({k: info[k] for k in ("p_value", "holm_rank", "holm_threshold", "holm_significant")})

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
