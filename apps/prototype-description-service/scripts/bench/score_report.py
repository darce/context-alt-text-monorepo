"""Dual-frame scoring, accepted set, bootstrap precision gate, tier report."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from scripts.bench.corpus import ItemOutcomeStore, is_detection_exhaustive, load_bench_manifest
from scripts.bench.export_map import _unwrap_rows, load_leg_exports, require_cluster_success, to_face_metric_inputs
from scripts.bench.score import IOU_MATCH_THRESHOLD
from scripts.bench.stack_pair import (
    BenchError,
    HOLM_FAMILY_ENDPOINTS,
    ROOT_KEYS,
    StackPairConfig,
    _parse_stack,
    load_stack_pair,
    validate_stack_pair_config,
)
from scripts.eval_harness.face_metrics import detection_pr, detection_pr_strict, identification_pr
from scripts.eval_harness.manifest import (
    AnnotationMode,
    GoldenEntry,
    GoldenManifest,
    LEGACY_IMPORT_CAPTURE_SESSION_ID,
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
_MANIFEST_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# Approved frozen corpus bytes; the run-local manifest.sha is verified against
# manifest.json before score_head_to_head reaches corpus classification.
GOLDEN150_MANIFEST_SHA256 = (
    "0dc89a1d0378630522a16080a176c1533357419fcfbe704a7c2bfc487580ac54"
)

# Persist contract for legs/<stack_id>/preflight.json (PROV-01). Score refuses
# a file that is missing, unreadable (including non-UTF-8 bytes), not a JSON
# object, or lacks these keys. Required provenance values and runtime versions
# are also rechecked at score time so hand-written or tampered files fail closed.
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

_RUNTIME_FINGERPRINT_TOKEN = re.compile(r"(?:^|;\s*)numeric_runtime_fingerprint=(\{.*\})$")
_RUNTIME_FINGERPRINT_FIELDS = (
    "opencv_version",
    "opencv_major",
    "onnxruntime_version",
    "numpy_version",
    "scipy_version",
    "pillow_version",
    "hdbscan_version",
    "pgvector_version",
    "comparison_token",
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
    attrition_failures_by_media: dict[int, dict[str, list[str]]] = field(default_factory=dict)


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
            has_image_units = any(occasion_ids[idxs[0]].startswith("image:") for idxs in full)
            has_occasion_units = any(not occasion_ids[idxs[0]].startswith("image:") for idxs in full)
            if has_image_units and has_occasion_units:
                resampling_unit = "occasion+image"
            elif has_image_units:
                resampling_unit = "image"
            else:
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


def _primary_claim_type(ci_lower: float, ci_upper: float, equivalence_margin: float) -> str | None:
    """Classify a primary interval as superiority, equivalence, or unsupported."""
    if ci_lower > 0.0 or ci_upper < 0.0:
        return "superiority"
    if ci_lower >= -equivalence_margin and ci_upper <= equivalence_margin:
        return "equivalence"
    return None


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
    if ctx.get("golden150_provenance"):
        return CrossbenchTier.DIRECTIONAL, "golden150_bias_bound_pending"
    if ctx.get("primary"):
        if "bootstrap_status" not in ctx:
            raise BenchError(
                "bootstrap_status_missing",
                "named confirmatory-eligible cell missing bootstrap_status",
            )
        if str(ctx["bootstrap_status"]) != "ok":
            return CrossbenchTier.DIRECTIONAL, "bootstrap_status"
        if ctx.get("primary_claim_type") not in {"superiority", "equivalence"}:
            return CrossbenchTier.DIRECTIONAL, "primary_claim_unsupported"
        return CrossbenchTier.CONFIRMATORY, None
    if ctx.get("holm_significant", False):
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


def _record_matches_manifest_entry(record: dict[str, Any], entry: GoldenEntry) -> bool:
    # DATA-13: carry both the manifest path and its content pin through every
    # phase; a media id alone is not end-to-end provenance.
    return (
        isinstance(record.get("manifest_path"), str)
        and record.get("manifest_path") == entry.path
        and isinstance(record.get("content_sha256"), str)
        and record.get("content_sha256") == entry.sha256
    )


def _terminal_ingest_ok(
    records: list[dict[str, Any]], media_id: int, *, entry: GoldenEntry | None = None
) -> bool:
    ingest = _latest_by_phase(records, media_id, "ingest")
    # Ingest provenance must come from the durable ingest phase. Analyze rows
    # describe a later operation and cannot substitute for missing ingest
    # evidence, even when older writers copied the terminal outcome there.
    if ingest is None:
        return False
    if entry is not None and not _record_matches_manifest_entry(ingest, entry):
        return False
    outcome = ingest.get("terminal_ingest_outcome")
    if outcome is None:
        return False
    return outcome == "success"


def _ingest_roster(
    records: list[dict[str, Any]], manifest: GoldenManifest | None = None
) -> set[int]:
    if manifest is None:
        return {
            int(r["manifest_media_id"])
            for r in records
            if r.get("phase") == "ingest" and "manifest_media_id" in r
        }
    return {
        entry.media_id
        for entry in manifest.entries
        if any(
            r.get("phase") == "ingest"
            and r.get("manifest_media_id") == entry.media_id
            and _record_matches_manifest_entry(r, entry)
            for r in records
        )
    }


def _analyze_ok(
    records: list[dict[str, Any]], media_id: int, *, entry: GoldenEntry | None = None
) -> dict[str, Any] | None:
    rec = _latest_by_phase(records, media_id, "analyze")
    if rec is None or rec.get("outcome") != "ok":
        return None
    mid = rec.get("stack_media_id")
    if not isinstance(mid, int):
        return None
    if entry is not None and not _record_matches_manifest_entry(rec, entry):
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
    # Metadata-only reader: report scoring never opens image bytes, only reads
    # manifest fields (media_id/path/labels) already pinned by the run. Naming
    # the skip explicitly (VLM6-MERGE-01 / rg-015 / OBS-04) keeps every other
    # load_bench_manifest caller on default hash verification.
    # DATA-13/API-02: the run-local snapshot is the single pinned source;
    # scoring must not retry through a mutable external manifest path.
    # RES-02/RES-03: malformed or missing integrity evidence fails fast.
    pin_path = run_dir / "manifest.sha"
    if pin_path.is_symlink() or not pin_path.is_file():
        raise BenchError("manifest_sha_missing", "run-dir has no manifest.sha pin")
    try:
        pin = pin_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise BenchError("manifest_sha_invalid", "run-dir manifest.sha is unreadable") from exc
    if not _MANIFEST_SHA_RE.fullmatch(pin):
        raise BenchError("manifest_sha_invalid", "run-dir manifest.sha is not a sha256 digest")

    candidate = run_dir / "manifest.json"
    if candidate.is_symlink() or not candidate.is_file():
        raise BenchError(
            "manifest_missing",
            "run-dir has no regular manifest.json snapshot; refusing manifest_path fallback",
        )
    try:
        manifest_bytes = candidate.read_bytes()
    except OSError as exc:
        raise BenchError("manifest_missing", f"pinned manifest is unreadable: {candidate}") from exc
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    if digest != pin:
        raise BenchError(
            "manifest_sha_mismatch",
            f"manifest bytes do not match run-dir manifest.sha pin ({candidate})",
        )
    return load_bench_manifest(
        str(candidate),
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="metadata-only scoring path; image bytes never opened",
    )


def _load_pair(run_dir: Path) -> StackPairConfig:
    path = run_dir / "stack_pair.yaml"
    if path.is_symlink():
        raise BenchError("pair_snapshot_invalid", "run-dir stack_pair.yaml must not be a symlink")
    if path.is_file():
        return validate_stack_pair_config(load_stack_pair(path))
    # Reconstruct the pair from the redacted snapshot written by init_run_dir.
    # The endpoint declarations are retained in that snapshot specifically so
    # a later score cannot silently select arbitrary legs from the filesystem.
    snapshot = run_dir / "stack_pair.json"
    if snapshot.is_symlink():
        raise BenchError("pair_snapshot_invalid", "run-dir stack_pair.json must not be a symlink")
    try:
        raw = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchError("pair_snapshot_invalid", "run-dir stack_pair.json is unreadable") from exc
    if not isinstance(raw, dict):
        raise BenchError("pair_snapshot_invalid", "run-dir stack_pair.json must be a JSON object")
    unknown = set(raw) - ROOT_KEYS
    if unknown:
        raise BenchError("pair_snapshot_invalid", f"run-dir stack_pair.json has unknown keys: {sorted(unknown)}")
    raw_stacks = raw.get("stacks")
    if not isinstance(raw_stacks, list) or len(raw_stacks) != 2:
        raise BenchError("pair_snapshot_invalid", "run-dir stack_pair.json must declare exactly two stacks")
    try:
        stacks = tuple(_parse_stack(entry) for entry in raw_stacks)
        pair = StackPairConfig(
            stacks=stacks,
            head_to_head_delta=raw.get("head_to_head_delta"),
            bootstrap_seed=raw.get("bootstrap_seed"),
            primary_endpoint=raw.get("primary_endpoint"),
            secondary_endpoints=tuple(raw.get("secondary_endpoints") or []),
            accepted_set_floor=raw.get("accepted_set_floor", 0.90),
            max_differential_attrition=raw.get("max_differential_attrition", 0.05),
            baseline_manifest_path=raw.get("baseline_manifest_path"),
        )
        return validate_stack_pair_config(pair)
    except BenchError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise BenchError("pair_snapshot_invalid", "run-dir stack_pair.json has invalid configuration values") from exc


def _declared_stack_ids(root: Path, pair: StackPairConfig) -> list[str]:
    validate_stack_pair_config(pair)
    declared = [stack.stack_id for stack in pair.stacks]
    legs_root = root / "legs"
    if legs_root.is_symlink() or not legs_root.is_dir():
        raise BenchError("stack_pair_mismatch", "run-dir has no legs directory")
    try:
        children = list(legs_root.iterdir())
    except OSError as exc:
        raise BenchError("stack_pair_mismatch", "run-dir legs directory is unreadable") from exc
    if any(path.is_symlink() or not path.is_dir() for path in children):
        raise BenchError(
            "stack_pair_mismatch",
            "run-dir legs must contain only regular directories for the declared pair",
        )
    actual = sorted(path.name for path in children)
    expected = sorted(declared)
    if actual != expected:
        raise BenchError(
            "stack_pair_mismatch",
            f"run legs {actual} do not match declared pair {expected}",
        )
    return expected


def compute_accepted_set(run_dir: Path | str) -> AcceptedSet:
    root = Path(run_dir)
    manifest = _load_manifest_from_run(root)
    pair = _load_pair(root)
    from scripts.bench.corpus import assert_floor_fits_corpus

    assert_floor_fits_corpus(pair.accepted_set_floor, len(manifest.entries))
    stacks = _declared_stack_ids(root, pair)
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
            rec = _analyze_ok(recs, entry.media_id, entry=entry)
            if rec is None:
                continue
            join[entry.media_id] = {
                "stack_media_id": rec["stack_media_id"],
                "image_width": rec.get("image_width"),
                "image_height": rec.get("image_height"),
            }
        join_by[stack_id] = join

    exports_by = {stack_id: load_leg_exports(root, stack_id) for stack_id in stacks}
    identity_results_by_stack = {
        stack_id: _media_identity_results_by_id(export.media_identity_results)
        for stack_id, export in exports_by.items()
    }

    accepted: list[GoldenEntry] = []
    attrition_ia = 0
    attrition_join = 0
    ingest_asym = 0
    attrition_failures_by_media: dict[int, dict[str, list[str]]] = {}
    for entry in manifest.entries:
        mid = entry.media_id
        ok_both = True
        failed_by_stack: dict[str, list[str]] = {}
        present = []
        for stack_id in stacks:
            recs = records_by[stack_id]
            in_roster = mid in roster_by[stack_id]
            present.append(in_roster)
            ingest_ok = _terminal_ingest_ok(recs, mid, entry=entry)
            analyze = _analyze_ok(recs, mid, entry=entry)
            failures: list[str] = []
            if not ingest_ok or analyze is None:
                if not ingest_ok:
                    failures.append("ingest")
                if analyze is None:
                    failures.append("analyze")
                ok_both = False
            if not in_roster:
                failures.append("roster")
                ok_both = False
            elif analyze is not None and not _media_identity_query_succeeded(
                identity_results_by_stack[stack_id], analyze.get("stack_media_id")
            ):
                failures.append("identity_query")
                ok_both = False
            failed_by_stack[stack_id] = failures
        if present.count(True) == 1:
            ingest_asym += 1
        if ok_both:
            accepted.append(entry)
        else:
            attrition_failures_by_media[mid] = failed_by_stack
            all_failures = {failure for failures in failed_by_stack.values() for failure in failures}
            if all_failures & {"ingest", "analyze"}:
                attrition_ia += 1
            elif all_failures & {"roster", "identity_query"}:
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
    for entry in accepted:
        for stack_id in stacks:
            stack_mid = join_by[stack_id][entry.media_id]["stack_media_id"]
            query_result = identity_results_by_stack[stack_id].get(stack_mid)
            if query_result is not None and not query_result["rows"]:
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
        attrition_failures_by_media=attrition_failures_by_media,
    )


def _media_identity_results_by_id(payload: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(payload, list):
        return {}
    results: dict[int, dict[str, Any]] = {}
    invalid: set[int] = set()
    for result in payload:
        if not isinstance(result, dict):
            continue
        media_id = result.get("media_id")
        if not isinstance(media_id, int) or isinstance(media_id, bool):
            continue
        if (
            not isinstance(result.get("query_succeeded"), bool)
            or not isinstance(result.get("rows"), list)
            or media_id in results
            or media_id in invalid
        ):
            results.pop(media_id, None)
            invalid.add(media_id)
            continue
        results[media_id] = result
    return results


def _media_identity_query_succeeded(
    results_by_id: dict[int, dict[str, Any]], media_id: Any
) -> bool:
    if not isinstance(media_id, int) or isinstance(media_id, bool):
        return False
    result = results_by_id.get(media_id)
    return result is not None and result.get("query_succeeded") is True


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
    root = Path(run_dir)
    pair = _load_pair(root)
    declared_stacks = _declared_stack_ids(root, pair)
    if set(records_by) != set(declared_stacks):
        raise BenchError(
            "stack_pair_mismatch",
            f"attrition records {sorted(records_by)} do not match declared pair {declared_stacks}",
        )
    dest = root / "score" / "attrition.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    missing = []
    accepted_ids = set(accepted.manifest_media_ids)
    stacks = declared_stacks
    for entry in manifest.entries:
        if entry.media_id in accepted_ids:
            continue
        failed_by_stack = accepted.attrition_failures_by_media.get(entry.media_id)
        if not failed_by_stack:
            raise BenchError(
                "attrition_reason_missing",
                f"missing accepted-set failure details for manifest_media_id={entry.media_id}",
            )
        all_failures = {failure for failures in failed_by_stack.values() for failure in failures}
        # Keep the single phase field for older readers, with a declared
        # precedence; failed_conditions_by_stack carries every failed check.
        phase = next(
            (
                candidate
                for candidate in ("ingest", "analyze", "roster", "identity_query")
                if candidate in all_failures
            ),
            None,
        )
        if phase is None:
            raise BenchError(
                "attrition_reason_missing",
                f"empty accepted-set failure details for manifest_media_id={entry.media_id}",
            )
        missing.append(
            {
                "manifest_media_id": entry.media_id,
                "phase": "join" if phase == "identity_query" else phase,
                "failed_conditions_by_stack": failed_by_stack,
            }
        )
    one_sided = {}
    for stack_id, recs in records_by.items():
        ids = []
        for entry in manifest.entries:
            if (
                _terminal_ingest_ok(recs, entry.media_id, entry=entry)
                and _analyze_ok(recs, entry.media_id, entry=entry) is not None
                and entry.media_id in _ingest_roster(recs, manifest)
                and entry.media_id not in accepted_ids
            ):
                ids.append(entry.media_id)
        one_sided[stack_id] = ids
    detection_ids = set(accepted.detection_scoring_set)
    post_accept_exclusions = [
        {
            "manifest_media_id": entry.media_id,
            "reason": (
                "entry_not_detection_exhaustive"
                if not is_detection_exhaustive(entry)
                else "detection_scoring_refused"
            ),
        }
        for entry in manifest.entries
        if entry.media_id in accepted_ids and entry.media_id not in detection_ids
    ]
    payload = {
        "missing": missing,
        "post_accept_exclusions": post_accept_exclusions,
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


def _strict_detection_counts(
    item: Any,
    *,
    annotation_mode: AnnotationMode,
    run_manifest: dict[str, float],
) -> ImageCounts:
    result = detection_pr_strict(
        [item],
        annotation_mode=annotation_mode,
        run_manifest=run_manifest,
    )
    return ImageCounts(result.true_positives, result.false_positives, result.false_negatives)


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


def _occasion_resampling_info(manifest: GoldenManifest) -> tuple[dict[int, str], dict[str, int]]:
    """Map media to known capture sessions and retain each session's manifest size."""
    occasion_by_media: dict[int, str] = {}
    full_size: dict[str, int] = {}
    for entry in manifest.entries:
        sessions: set[str] = set()
        session_unknown = not entry.face_boxes
        for box in entry.face_boxes:
            lineage = box.lineage
            session = None if lineage is None else lineage.capture_session_id
            if not session or session == LEGACY_IMPORT_CAPTURE_SESSION_ID:
                session_unknown = True
            else:
                sessions.add(session)
        if not session_unknown and len(sessions) == 1:
            occasion_id = f"occasion:{next(iter(sessions))}"
        else:
            # A manifest entry without one unambiguous occasion remains an
            # independent media unit; never merge unrelated unknown occasions.
            occasion_id = f"image:{entry.media_id}"
        occasion_by_media[entry.media_id] = occasion_id
        full_size[occasion_id] = full_size.get(occasion_id, 0) + 1
    return occasion_by_media, full_size


def _is_golden150_corpus(run_dir: Path) -> bool:
    """Recognize the approved frozen corpus by its verified manifest content pin."""
    pin_path = run_dir / "manifest.sha"
    if pin_path.is_symlink() or not pin_path.is_file():
        raise BenchError("manifest_sha_missing", "run-dir has no manifest.sha pin")
    try:
        pin = pin_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise BenchError("manifest_sha_invalid", "run-dir manifest.sha is unreadable") from exc
    if not _MANIFEST_SHA_RE.fullmatch(pin):
        raise BenchError("manifest_sha_invalid", "run-dir manifest.sha is not a sha256 digest")
    # compute_accepted_set verified that this pin matches the run-local
    # manifest.json bytes before score_head_to_head classifies the corpus.
    return pin == GOLDEN150_MANIFEST_SHA256


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
    runtime_fingerprints: list[dict[str, Any]] = []
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
        _validate_preflight_provenance(doc, stack_id)
        runtime_fingerprints.append(_preflight_runtime_fingerprint(doc, stack_id))
    if runtime_fingerprints:
        reference = runtime_fingerprints[0]
        for candidate in runtime_fingerprints[1:]:
            differing = _first_runtime_fingerprint_difference(
                reference,
                candidate,
            )
            if differing is not None:
                raise BenchError(
                    "preflight_invalid",
                    f"runtime fingerprint field {differing} differs between benchmark legs",
                )
    return True


def _first_runtime_fingerprint_difference(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    fields: tuple[str, ...] = _RUNTIME_FINGERPRINT_FIELDS,
) -> str | None:
    """Return the first persisted runtime field that differs between legs."""
    return next((field for field in fields if left[field] != right[field]), None)


def _validate_preflight_provenance(doc: dict[str, Any], stack_id: str) -> None:
    """Recheck provenance values before scoring; key presence alone is unsafe."""
    if doc.get("stack_id") != stack_id:
        raise BenchError("preflight_invalid", f"{stack_id} preflight.json stack_id does not match its leg")
    if not isinstance(doc.get("expected_profile"), str) or not doc["expected_profile"]:
        raise BenchError("preflight_invalid", f"{stack_id} preflight.json expected_profile is invalid")
    if doc.get("resolved_profile") != doc["expected_profile"]:
        raise BenchError("preflight_invalid", f"{stack_id} preflight profile differs from expectation")
    expected_dim = doc.get("expected_pgvector_dim")
    resolved_dim = doc.get("resolved_pgvector_dim")
    if (
        type(expected_dim) is not int
        or expected_dim <= 0
        or type(resolved_dim) is not int
        or resolved_dim != expected_dim
    ):
        raise BenchError("preflight_invalid", f"{stack_id} preflight pgvector dimension differs from expectation")
    if type(doc.get("opencv_major")) is not int or doc["opencv_major"] != 5:
        raise BenchError("preflight_invalid", f"{stack_id} preflight must report OpenCV major 5")
    if doc.get("opencv_major_source") != "service_reported":
        raise BenchError("preflight_invalid", f"{stack_id} preflight OpenCV major is not service-reported")
    health = doc.get("health_detailed_excerpt")
    cache = health.get("model_cache") if isinstance(health, dict) else None
    if not isinstance(cache, dict) or cache.get("profile") != doc["resolved_profile"]:
        raise BenchError("preflight_invalid", f"{stack_id} detailed health profile differs from preflight")


def _preflight_runtime_fingerprint(doc: dict[str, Any], stack_id: str) -> dict[str, Any]:
    health = doc.get("health_detailed_excerpt")
    cache = health.get("model_cache") if isinstance(health, dict) else None
    detail = cache.get("detail") if isinstance(cache, dict) else None
    if not isinstance(detail, str):
        raise BenchError("preflight_invalid", f"{stack_id} preflight lacks detailed health model_cache.detail")
    match = _RUNTIME_FINGERPRINT_TOKEN.search(detail)
    if match is None:
        raise BenchError("preflight_invalid", f"{stack_id} preflight lacks a service runtime fingerprint")
    try:
        fingerprint = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint is invalid JSON") from exc
    if not isinstance(fingerprint, dict):
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint must be an object")
    required = _RUNTIME_FINGERPRINT_FIELDS
    if any(key not in fingerprint for key in required):
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint is incomplete")
    version_fields = tuple(key for key in required if key not in {"opencv_major", "comparison_token"})
    if any(not isinstance(fingerprint[key], str) or not fingerprint[key] for key in version_fields):
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint has an invalid version")
    token = fingerprint["comparison_token"]
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{64}", token) is None:
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint has an invalid comparison token")
    major = fingerprint["opencv_major"]
    if type(major) is not int or major != doc["opencv_major"]:
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint OpenCV major is inconsistent")
    version = fingerprint["opencv_version"]
    major_token = version.split(".", 1)[0]
    if not major_token.isdecimal() or int(major_token) != major:
        raise BenchError("preflight_invalid", f"{stack_id} runtime fingerprint OpenCV version is inconsistent")
    return {key: fingerprint[key] for key in required}


def _preflight_opencv_version(doc: dict[str, Any], stack_id: str) -> str:
    """Compatibility accessor for the OpenCV component of the runtime pin."""
    return str(_preflight_runtime_fingerprint(doc, stack_id)["opencv_version"])


def _strict_detection_inputs(
    detections: list[Any],
    manifest: GoldenManifest,
    export_payload: dict[str, Any],
    join: dict[int, dict[str, Any]],
) -> list[Any]:
    """Restore the geometry required by strict scoring from public exports."""
    rows_by_stack_mid: dict[int, list[dict[str, Any]]] = {}
    for row in _unwrap_rows(export_payload["media_identities"], what="media_identities"):
        mid = row.get("media_id")
        if isinstance(mid, int):
            rows_by_stack_mid.setdefault(mid, []).append(row)
    entry_by_path = {entry.path: entry for entry in manifest.entries}
    strict_inputs: list[Any] = []
    for detection in detections:
        entry = entry_by_path.get(detection.image)
        if entry is None:
            raise BenchError(
                "manifest_entry_missing",
                f"strict detection path {detection.image!r} has no manifest entry",
            )
        info = join.get(entry.media_id)
        if info is None:
            raise BenchError(
                "join_row_missing",
                f"strict detection path {detection.image!r} media_id={entry.media_id} has no join row",
            )
        stack_mid = info.get("stack_media_id")
        if not isinstance(stack_mid, int):
            raise BenchError(
                "join_row_missing",
                f"strict detection path {detection.image!r} media_id={entry.media_id} join row has no stack_media_id",
            )
        image_size = (info["image_width"], info["image_height"])
        export_rows = sorted(
            rows_by_stack_mid.get(stack_mid, []),
            key=lambda row: str(row.get("identity_id", "")),
        )
        boxes = tuple(
            (
                float(row["bbox"]["x"]),
                float(row["bbox"]["y"]),
                float(row["bbox"]["width"]),
                float(row["bbox"]["height"]),
            )
            for row in export_rows
        )
        strict_inputs.append(
            type(detection)(
                image=detection.image,
                pred_faces=detection.pred_faces,
                labeled_faces=detection.labeled_faces,
                detections_bbox_px=boxes,
                gt_boxes=tuple(entry.face_boxes),
                image_size=image_size,
                detection_frame_size=image_size,
            )
        )
    return strict_inputs


def score_head_to_head(run_dir: Path | str) -> Path:
    root = Path(run_dir)
    manifest = _load_manifest_from_run(root)
    pair = _load_pair(root)
    stacks = _declared_stack_ids(root, pair)
    (root / "score").mkdir(parents=True, exist_ok=True)

    accepted = compute_accepted_set(root)
    write_accepted_set(root, accepted)
    records_by = {
        stack_id: ItemOutcomeStore(root / "legs" / stack_id / "items.jsonl").read_all() for stack_id in stacks
    }
    write_attrition(root, accepted, manifest, records_by)

    # Preserve accepted-set diagnostics even when a later scoring precondition
    # refuses the run.
    for stack_id in stacks:
        require_cluster_success(root, stack_id)
    preflight_present = _require_prov01_preflights(root, stacks)

    # Differential attrition: |one-sided-A − one-sided-B| / |manifest|
    one_sided_counts = []
    for stack_id in stacks:
        recs = records_by[stack_id]
        n_os = 0
        for entry in manifest.entries:
            ok = (
                _terminal_ingest_ok(recs, entry.media_id, entry=entry)
                and _analyze_ok(recs, entry.media_id, entry=entry) is not None
                and entry.media_id in _ingest_roster(recs, manifest)
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
    occasion_by_media, occasion_full_size = _occasion_resampling_info(manifest)
    golden150_provenance = _is_golden150_corpus(root)
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
    counts_media_ids_by_cell: dict[str, list[int]] = {}
    cells: list[dict[str, Any]] = []
    localization_dropped_by_stack = {stack_id: 0 for stack_id in stacks}

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
                    localization_counts = (
                        {"degenerate_box_dropped": 0}
                        if frame_key == "e2e" and label_key == "primary"
                        else None
                    )
                    _, ident = to_face_metric_inputs(
                        export_payload,
                        accepted_manifest,
                        join,
                        label_key,
                        frame=frame_key,  # type: ignore[arg-type]
                        localization_counts=localization_counts,
                    )
                    if localization_counts is not None:
                        localization_dropped_by_stack[stack_id] = localization_counts["degenerate_box_dropped"]
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
                    strict_detection_counts_by_path: dict[str, ImageCounts] = {}
                else:
                    strict_detection_inputs = _strict_detection_inputs(
                        det, detection_manifest, export_payload, join
                    )
                    detection_run_manifest = {
                        "iou_threshold": (
                            manifest.iou_threshold
                            if manifest.iou_threshold is not None
                            else IOU_MATCH_THRESHOLD
                        )
                    }
                    det_matched = detection_pr_strict(
                        strict_detection_inputs,
                        annotation_mode=detection_mode,
                        run_manifest=detection_run_manifest,
                    )
                    strict_detection_counts_by_path = {
                        row.image: _strict_detection_counts(
                            row,
                            annotation_mode=detection_mode,
                            run_manifest=detection_run_manifest,
                        )
                        for row in strict_detection_inputs
                    }
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
                        series_media_ids: list[int] = []
                        for entry in population:
                            if metric.startswith("detection"):
                                row = det_by_mid.get(entry.media_id)
                                if row is None:
                                    raise BenchError(
                                        "join_row_missing",
                                        f"detection population media_id={entry.media_id} has no metric row",
                                    )
                                strict_counts = strict_detection_counts_by_path.get(row.image)
                                if strict_counts is None:
                                    raise BenchError(
                                        "join_row_missing",
                                        f"detection path {row.image!r} has no strict metric row",
                                    )
                                series.append(strict_counts)
                                series_media_ids.append(entry.media_id)
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
                                    series_media_ids.append(entry.media_id)
                        counts_by[cell][stack_id] = series
                        counts_media_ids_by_cell[cell] = series_media_ids
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
                    occasion_ids=[
                        occasion_by_media[media_id]
                        for media_id in counts_media_ids_by_cell[cell_name]
                    ],
                    occasion_full_size=occasion_full_size,
                    cell=cell_name,
                )
            except BenchError as exc:
                bootstrap_errors[cell_name] = exc

    holm: dict[str, dict[str, Any]] = {}
    declared_secondaries = list(pair.secondary_endpoints)
    holm_family = [cell_name for cell_name in declared_secondaries if cell_name in HOLM_FAMILY_ENDPOINTS]
    holm_missing: set[str] = set()
    if holm_family:
        padded: list[tuple[str, float]] = []
        for cell_name in holm_family:
            interval = intervals.get(cell_name)
            if interval is None or interval.p_value is None:
                padded.append((cell_name, 1.0))
                holm_missing.add(cell_name)
            else:
                padded.append((cell_name, float(interval.p_value)))
        holm = holm_bonferroni(padded, family_size=len(holm_family))

    primary_interval = intervals.get(pair.primary_endpoint)
    primary_claim_type: str | None = None
    primary_claim_direction: str | None = None
    primary_ci_lower: float | None = None
    primary_ci_upper: float | None = None
    if (
        primary_interval is not None
        and primary_interval.bootstrap_status == "ok"
        and primary_interval.ci_lower is not None
        and primary_interval.ci_upper is not None
    ):
        primary_ci_lower = primary_interval.ci_lower
        primary_ci_upper = primary_interval.ci_upper
        primary_claim_type = _primary_claim_type(
            primary_interval.ci_lower,
            primary_interval.ci_upper,
            pair.head_to_head_delta,
        )
        if primary_claim_type == "superiority":
            primary_claim_direction = stacks[0] if primary_interval.ci_lower > 0.0 else stacks[1]

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
            "golden150_provenance": golden150_provenance,
            "primary_claim_type": primary_claim_type if name == pair.primary_endpoint else None,
        }
        cell.pop("_is_detection", None)
        tier, reason = assign_tier(name, ctx)
        cell["tier"] = tier.value
        cell["reason"] = reason
        if name == pair.primary_endpoint:
            cell["primary_claim_type"] = primary_claim_type or "unsupported"
            cell["primary_claim_direction"] = primary_claim_direction
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
        "primary_claim": {
            "endpoint": pair.primary_endpoint,
            "claim_type": primary_claim_type or "unsupported",
            "direction": primary_claim_direction,
            "equivalence_margin": pair.head_to_head_delta,
            "ci_lower": primary_ci_lower,
            "ci_upper": primary_ci_upper,
        },
        "holm_family": holm_family,
        "holm_family_size": len(holm_family),
        "degenerate_box_dropped": localization_dropped_by_stack,
        "degenerate_box_dropped_scope": "accepted manifest; frame_e2e/label_map_primary localization pass, once per stack",
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
        "<p>Detection precision/recall measures end-to-end embeddable-face yield among public exports. "
        "Faces without embeddings are omitted from public export rows, so these values are not detector-only recall.</p>",
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
