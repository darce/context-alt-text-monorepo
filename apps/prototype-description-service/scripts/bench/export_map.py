"""S1: persist public exports. S2 extends with GT mapping symbols."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.bench.stack_pair import BenchError

_CLUSTER_SUCCESS = frozenset({"success", "completed", "ok", "completed_with_errors"})


@dataclass
class LegExport:
    stack_id: str
    media_identities: Any
    clusters: Any
    cluster_members: Any
    paths: dict[str, Path] = field(default_factory=dict)


def require_cluster_success(run_dir: Path | str, stack_id: str) -> dict[str, Any]:
    path = Path(run_dir) / "legs" / stack_id / "cluster_job.json"
    if not path.is_file():
        raise BenchError("cluster_gate_refused", f"cluster_job.json missing for {stack_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = str(payload.get("status", "")).lower()
    if status not in _CLUSTER_SUCCESS:
        raise BenchError("cluster_gate_refused", f"cluster job status {status!r} is not success")
    return payload


def export_leg(client: Any, run_dir: Path | str, stack_id: str) -> LegExport:
    require_cluster_success(run_dir, stack_id)
    media_ids = _roster_stack_media_ids(run_dir, stack_id)
    identities = client.media_identities(media_ids)
    clusters = client.clusters()
    members: Any
    if isinstance(clusters, list):
        collected: list[Any] = []
        for cluster in clusters:
            cid = cluster.get("id") or cluster.get("cluster_id") if isinstance(cluster, dict) else None
            if cid is None:
                continue
            collected.append(client.cluster_members(str(cid)))
        members = collected
    elif isinstance(clusters, dict):
        rows = clusters.get("data") or clusters.get("clusters") or []
        members = [client.cluster_members(str(c.get("id") or c.get("cluster_id"))) for c in rows if isinstance(c, dict)]
    else:
        members = []

    export_dir = Path(run_dir) / "legs" / stack_id / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "media_identities": export_dir / "media_identities.json",
        "clusters": export_dir / "clusters.json",
        "cluster_members": export_dir / "cluster_members.json",
    }
    _write_preserved(paths["media_identities"], identities)
    _write_preserved(paths["clusters"], clusters)
    _write_preserved(paths["cluster_members"], members)
    return LegExport(
        stack_id=stack_id,
        media_identities=identities,
        clusters=clusters,
        cluster_members=members,
        paths=paths,
    )


def load_leg_exports(run_dir: Path | str, stack_id: str) -> LegExport:
    export_dir = Path(run_dir) / "legs" / stack_id / "exports"
    return LegExport(
        stack_id=stack_id,
        media_identities=json.loads((export_dir / "media_identities.json").read_text(encoding="utf-8")),
        clusters=json.loads((export_dir / "clusters.json").read_text(encoding="utf-8")),
        cluster_members=json.loads((export_dir / "cluster_members.json").read_text(encoding="utf-8")),
        paths={
            "media_identities": export_dir / "media_identities.json",
            "clusters": export_dir / "clusters.json",
            "cluster_members": export_dir / "cluster_members.json",
        },
    )


def _write_preserved(path: Path, payload: Any) -> None:
    # Persist the upstream payload as-is. Never invent envelope fields.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _roster_stack_media_ids(run_dir: Path | str, stack_id: str) -> list[int]:
    from scripts.bench.corpus import ItemOutcomeStore

    store = ItemOutcomeStore(Path(run_dir) / "legs" / stack_id / "items.jsonl")
    ids: list[int] = []
    seen: set[int] = set()
    for record in store.read_all():
        if record.get("phase") != "analyze" or record.get("outcome") != "ok":
            continue
        mid = record.get("stack_media_id")
        if isinstance(mid, int) and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids


# ---------------------------------------------------------------------------
# S2: GT mapping + localization
# ---------------------------------------------------------------------------

from collections.abc import Sequence
from dataclasses import dataclass as _dataclass
from typing import Literal
import unicodedata
import re

from scripts.bench.score import (
    IOU_MATCH_THRESHOLD,
    box_area_xyxy,
    clamp01,
    gt_centre_to_tl,
    hungarian_iou_matches,
    pred_px_to_norm_tl,
)
from scripts.eval_harness.face_metrics import ImageDetection, ImageIdentities
from scripts.eval_harness.manifest import FaceBox, GoldenEntry, GoldenManifest

_PRED_KEYS = frozenset({"x", "y", "width", "height"})
_WS = re.compile(r"\s+")


@_dataclass
class DetectionMatchResult:
    matched_faces: int
    iou_values: list[float]
    degenerate_box_dropped: int
    pred_count: int
    gt_count: int
    matched_gt_indices: list[int] = field(default_factory=list)


def normalize_label(value: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", value).strip()).casefold()


def _looks_auto_id(label: str) -> bool:
    if not label or not label.strip():
        return True
    compact = label.replace("-", "")
    return compact.isalnum() and any(ch.isdigit() for ch in compact) and " " not in label.strip()


def match_detection_boxes(
    gt_boxes: list[Any],
    predictions: list[dict[str, Any]],
    *,
    image_width: int,
    image_height: int,
) -> DetectionMatchResult:
    if not isinstance(image_width, int) or not isinstance(image_height, int) or image_width <= 0 or image_height <= 0:
        raise BenchError("image_dimensions_missing", "image_width/image_height missing or non-positive")
    gt_tl: list[tuple[float, float, float, float]] = []
    dropped = 0
    for box in gt_boxes:
        if isinstance(box, FaceBox):
            x, y, w, h = box.x, box.y, box.w, box.h
        else:
            x, y, w, h = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
        tl = gt_centre_to_tl(float(x), float(y), float(w), float(h))
        xyxy = (clamp01(tl[0]), clamp01(tl[1]), clamp01(tl[0] + tl[2]), clamp01(tl[1] + tl[3]))
        if box_area_xyxy(xyxy) <= 0:
            dropped += 1
            continue
        gt_tl.append(tl)
    pred_tl: list[tuple[float, float, float, float]] = []
    for pred in predictions:
        keys = set(pred)
        if keys != _PRED_KEYS:
            raise BenchError("box_convention_unknown", f"prediction bbox keys {sorted(keys)} != {{x,y,width,height}}")
        tl = pred_px_to_norm_tl(
            float(pred["x"]),
            float(pred["y"]),
            float(pred["width"]),
            float(pred["height"]),
            image_width,
            image_height,
        )
        xyxy = (clamp01(tl[0]), clamp01(tl[1]), clamp01(tl[0] + tl[2]), clamp01(tl[1] + tl[3]))
        if box_area_xyxy(xyxy) <= 0:
            dropped += 1
            continue
        pred_tl.append(tl)
    pairs, pairwise = hungarian_iou_matches(gt_tl, pred_tl, threshold=IOU_MATCH_THRESHOLD)
    iou_values = [p[2] for p in pairs] if pairs else pairwise
    return DetectionMatchResult(
        matched_faces=len(pairs),
        iou_values=iou_values,
        degenerate_box_dropped=dropped,
        pred_count=len(pred_tl),
        gt_count=len(gt_tl),
        matched_gt_indices=[p[1] for p in pairs],
    )


def _identities_list(export: Any) -> list[dict[str, Any]]:
    if isinstance(export, dict):
        raw = export.get("media_identities", [])
    else:
        raw = getattr(export, "media_identities", [])
    if isinstance(raw, dict):
        raw = raw.get("data") or raw.get("items") or []
    return [row for row in raw if isinstance(row, dict)]


def _clusters_list(export: Any) -> list[dict[str, Any]]:
    if isinstance(export, dict):
        raw = export.get("clusters", [])
    else:
        raw = getattr(export, "clusters", [])
    if isinstance(raw, dict):
        raw = raw.get("data") or raw.get("clusters") or []
    return [row for row in raw if isinstance(row, dict)]


def map_cluster_labels_primary(
    export: Any,
    roster: Sequence[str],
) -> dict[int, list[str]]:
    canon = {normalize_label(n): n for n in roster}
    by_media: dict[int, list[str]] = {}
    for row in _identities_list(export):
        mid = row.get("media_id")
        if not isinstance(mid, int):
            continue
        label = str(row.get("cluster_label") or "")
        auto = bool(row.get("is_auto_label"))
        if auto and _looks_auto_id(label):
            continue
        if not label:
            continue
        mapped = canon.get(normalize_label(label))
        if mapped:
            by_media.setdefault(mid, [])
            if mapped not in by_media[mid]:
                by_media[mid].append(mapped)
    return by_media


def _centre_in_box(cx: float, cy: float, box_tl: tuple[float, float, float, float]) -> bool:
    x1, y1, w, h = box_tl
    return x1 <= cx <= x1 + w and y1 <= cy <= y1 + h


def map_cluster_labels_optimistic(
    export: Any,
    manifest: GoldenManifest,
    join: dict[int, dict[str, Any]],
) -> dict[int, list[str]]:
    """Hungarian overlap assignment; centre-in-box fallback allowed here only."""
    primary = map_cluster_labels_primary(
        export, manifest.roster or [n for e in manifest.entries for n in e.present_identities]
    )
    # Residual: for media with boxes, assign unlabeled clusters by overlap.
    identities = _identities_list(export)
    by_stack: dict[int, list[dict[str, Any]]] = {}
    for row in identities:
        mid = row.get("media_id")
        if isinstance(mid, int):
            by_stack.setdefault(mid, []).append(row)
    out: dict[int, list[str]] = {k: list(v) for k, v in primary.items()}
    stack_to_entry = {
        int(info["stack_media_id"]): mid
        for mid, info in join.items()
        if isinstance(info.get("stack_media_id"), int)
    }
    entries = {e.media_id: e for e in manifest.entries}
    for stack_mid, rows in by_stack.items():
        manifest_id = stack_to_entry.get(stack_mid)
        if manifest_id is None:
            continue
        entry = entries.get(manifest_id)
        if entry is None or not entry.face_boxes:
            continue
        info = join[manifest_id]
        width, height = int(info["image_width"]), int(info["image_height"])
        gt_named = [(b, gt_centre_to_tl(b.x, b.y, b.w, b.h)) for b in entry.face_boxes if b.name]
        if not gt_named:
            continue
        pred_tl = []
        for row in rows:
            bbox = row.get("bbox") or {}
            if set(bbox) != _PRED_KEYS:
                continue
            pred_tl.append(
                pred_px_to_norm_tl(
                    float(bbox["x"]),
                    float(bbox["y"]),
                    float(bbox["width"]),
                    float(bbox["height"]),
                    width,
                    height,
                )
            )
        if not pred_tl:
            continue
        gt_only = [tl for _, tl in gt_named]
        pairs, _ = hungarian_iou_matches(gt_only, pred_tl, threshold=IOU_MATCH_THRESHOLD)
        assigned_gt: set[int] = {p[1] for p in pairs}
        assigned_pred: set[int] = {p[0] for p in pairs}
        names = list(out.get(stack_mid, []))
        for _pi, gi, _iou in pairs:
            name = gt_named[gi][0].name
            if name and name not in names:
                names.append(name)
        # centre-in-box fallback for residuals
        for gi, (box, tl) in enumerate(gt_named):
            if gi in assigned_gt:
                continue
            cx, cy = box.x, box.y
            for pi, ptl in enumerate(pred_tl):
                if pi in assigned_pred:
                    continue
                if _centre_in_box(cx, cy, ptl) or _centre_in_box(ptl[0] + ptl[2] / 2, ptl[1] + ptl[3] / 2, tl):
                    if box.name and box.name not in names:
                        names.append(box.name)
                    assigned_pred.add(pi)
                    break
        if names:
            out[stack_mid] = names
    return out


def to_face_metric_inputs(
    export: Any,
    manifest: GoldenManifest,
    join: dict[int, dict[str, Any]],
    label_map: str,
    frame: Literal["native", "e2e"],
) -> tuple[list[ImageDetection], list[ImageIdentities]]:
    roster = list(manifest.roster)
    if "optimistic" in label_map:
        mapped = map_cluster_labels_optimistic(export, manifest, join)
    else:
        mapped = map_cluster_labels_primary(export, roster or [n for e in manifest.entries for n in e.present_identities])
    identities = _identities_list(export)
    by_stack: dict[int, list[dict[str, Any]]] = {}
    for row in identities:
        mid = row.get("media_id")
        if isinstance(mid, int):
            by_stack.setdefault(mid, []).append(row)

    detections: list[ImageDetection] = []
    id_rows: list[ImageIdentities] = []
    for entry in manifest.entries:
        info = join.get(entry.media_id)
        if info is None:
            continue
        stack_mid = info.get("stack_media_id")
        if not isinstance(stack_mid, int):
            continue
        width = info.get("image_width")
        height = info.get("image_height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise BenchError("image_dimensions_missing", f"bad dims for media {entry.media_id}")
        rows = by_stack.get(stack_mid, [])
        pred_boxes = [r.get("bbox") or {} for r in rows]
        # sort predictions by identity_id for reproducibility
        rows_sorted = sorted(rows, key=lambda r: str(r.get("identity_id", "")))
        pred_boxes = [r.get("bbox") or {} for r in rows_sorted]
        match = match_detection_boxes(
            list(entry.face_boxes),
            pred_boxes,
            image_width=width,
            image_height=height,
        )
        detections.append(
            ImageDetection(
                image=entry.path,
                pred_faces=len(rows),
                labeled_faces=len(entry.face_boxes),
                matched_faces=match.matched_faces,
            )
        )
        predicted = list(mapped.get(stack_mid, []))
        labeled_full = list(entry.present_identities)
        if frame == "native":
            # Per-face native rule: drop GT names whose *box* got no proposed
            # detection (IoU match). Mapper-hit is not a detection proposal.
            matched_idx = set(match.matched_gt_indices)
            labeled_native: list[str] = []
            for gi, box in enumerate(entry.face_boxes):
                if gi not in matched_idx:
                    continue
                name = box.name if isinstance(box, FaceBox) else box.get("name")
                if name and name not in labeled_native:
                    labeled_native.append(name)
            predicted_native = list(predicted) if rows else []
            id_rows.append(
                ImageIdentities(
                    image=entry.path,
                    predicted=predicted_native,
                    labeled=labeled_native,
                    recognition_enabled=entry.policy.recognition_enabled,
                    stranger_faces=sum(1 for b in entry.face_boxes if b.name is None)
                    if entry.face_count == len(entry.face_boxes)
                    else 0,
                )
            )
        else:
            id_rows.append(
                ImageIdentities(
                    image=entry.path,
                    predicted=predicted,
                    labeled=labeled_full,
                    recognition_enabled=entry.policy.recognition_enabled,
                    stranger_faces=sum(1 for b in entry.face_boxes if b.name is None)
                    if entry.face_count == len(entry.face_boxes)
                    else 0,
                )
            )
    return detections, id_rows
