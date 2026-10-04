"""S1: persist public exports. S2 extends with GT mapping symbols."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from scripts.bench.score import (
    IOU_MATCH_THRESHOLD,
    box_area_xyxy,
    clamp01,
    gt_centre_to_tl,
    hungarian_iou_matches,
    pred_px_to_norm_tl,
)
from scripts.bench.stack_pair import BenchError
from scripts.bench.status import CLUSTER_SUCCESS_STATUSES, ItemOutcome, ItemPhase
from scripts.eval_harness.face_metrics import ImageDetection, ImageIdentities
from scripts.eval_harness.manifest import FaceBox, GoldenEntry, GoldenManifest

LEG_EXPORT_PAYLOAD_FILES = (
    "media_identities.json",
    "media_identity_results.json",
    "clusters.json",
    "cluster_members.json",
)
LEG_EXPORT_REQUIRED_FILES = (*LEG_EXPORT_PAYLOAD_FILES, "export_sha256.json")


@dataclass
class LegExport:
    stack_id: str
    media_identities: Any
    clusters: Any
    cluster_members: Any
    paths: dict[str, Path] = field(default_factory=dict)
    media_identity_results: Any = None


def require_cluster_success(run_dir: Path | str, stack_id: str) -> dict[str, Any]:
    path = Path(run_dir) / "legs" / stack_id / "cluster_job.json"
    if not path.is_file():
        raise BenchError("cluster_gate_refused", f"cluster_job.json missing for {stack_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = str(payload.get("status", "")).lower()
    if status not in CLUSTER_SUCCESS_STATUSES:
        raise BenchError("cluster_gate_refused", f"cluster job status {status!r} is not success")
    return payload


def export_leg(client: Any, run_dir: Path | str, stack_id: str) -> LegExport:
    require_cluster_success(run_dir, stack_id)
    media_ids = _roster_stack_media_ids(run_dir, stack_id)
    export_dir = Path(run_dir) / "legs" / stack_id / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "media_identities": export_dir / "media_identities.json",
        "media_identity_results": export_dir / "media_identity_results.json",
        "clusters": export_dir / "clusters.json",
        "cluster_members": export_dir / "cluster_members.json",
    }
    try:
        identities = client.media_identities(media_ids)
        identity_rows = _unwrap_rows(identities, what="media_identities")
    except Exception:
        # The upstream endpoint is one opaque batch request, so a failed batch
        # means every requested media id has an unknown/failed query result.
        _write_preserved(
            paths["media_identity_results"],
            [
                {"media_id": mid, "query_succeeded": False, "rows": []}
                for mid in media_ids
            ],
        )
        raise
    identity_results = [
        {
            "media_id": mid,
            "query_succeeded": True,
            "rows": [
                row
                for row in identity_rows
                if isinstance(row, dict) and row.get("media_id") == mid
            ],
        }
        for mid in media_ids
    ]
    _write_preserved(paths["media_identity_results"], identity_results)
    clusters = client.clusters()
    members: Any
    rows = _unwrap_rows(clusters, what="clusters")
    members = []
    for cluster in rows:
        cid = cluster.get("id") if cluster.get("id") is not None else cluster.get("cluster_id")
        if cid is None:
            continue
        members.append(client.cluster_members(str(cid)))

    _write_preserved(paths["media_identities"], identities)
    _write_preserved(paths["clusters"], clusters)
    _write_preserved(paths["cluster_members"], members)
    export_sha256 = _write_export_sha256(paths)
    paths["export_sha256"] = export_sha256
    return LegExport(
        stack_id=stack_id,
        media_identities=identities,
        clusters=clusters,
        cluster_members=members,
        paths=paths,
        media_identity_results=identity_results,
    )


def load_leg_exports(run_dir: Path | str, stack_id: str) -> LegExport:
    export_dir = Path(run_dir) / "legs" / stack_id / "exports"
    payloads = _read_verified_export_payloads(export_dir)
    identity_results_path = export_dir / "media_identity_results.json"
    identity_results = None
    if not identity_results_path.is_symlink() and identity_results_path.is_file():
        identity_results = json.loads(payloads["media_identity_results.json"])
    return LegExport(
        stack_id=stack_id,
        media_identities=json.loads(payloads["media_identities.json"]),
        clusters=json.loads(payloads["clusters.json"]),
        cluster_members=json.loads(payloads["cluster_members.json"]),
        media_identity_results=identity_results,
        paths={
            "media_identities": export_dir / "media_identities.json",
            "media_identity_results": identity_results_path,
            "clusters": export_dir / "clusters.json",
            "cluster_members": export_dir / "cluster_members.json",
            "export_sha256": export_dir / "export_sha256.json",
        },
    )


def _read_verified_export_payloads(export_dir: Path) -> dict[str, bytes]:
    digest_path = export_dir / "export_sha256.json"
    try:
        digests = json.loads(digest_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchError("export_digest_invalid", f"cannot read {digest_path.name}") from exc
    if not isinstance(digests, dict):
        raise BenchError("export_digest_invalid", f"{digest_path.name} must contain an object")

    payloads: dict[str, bytes] = {}
    for name in LEG_EXPORT_PAYLOAD_FILES:
        expected_digest = digests.get(name)
        if not isinstance(expected_digest, str) or not expected_digest:
            raise BenchError("export_digest_missing", f"missing digest for {name}")
        try:
            payload = (export_dir / name).read_bytes()
        except OSError as exc:
            raise BenchError("export_payload_missing", f"cannot read {name}") from exc
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            raise BenchError("export_digest_mismatch", f"sha256 mismatch for {name}")
        payloads[name] = payload
    return payloads


def _write_preserved(path: Path, payload: Any) -> None:
    # Persist the upstream payload as-is. Never invent envelope fields.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_export_sha256(paths: dict[str, Path]) -> Path:
    """Persist content hashes for the raw JSON exports used by scoring."""
    digests = {
        paths[name].name: hashlib.sha256(paths[name].read_bytes()).hexdigest()
        for name in ("media_identities", "media_identity_results", "clusters", "cluster_members")
    }
    dest = next(iter(paths.values())).parent / "export_sha256.json"
    dest.write_text(json.dumps(digests, indent=2, sort_keys=True), encoding="utf-8")
    return dest


def _roster_stack_media_ids(run_dir: Path | str, stack_id: str) -> list[int]:
    from scripts.bench.corpus import ItemOutcomeStore

    store = ItemOutcomeStore(Path(run_dir) / "legs" / stack_id / "items.jsonl")
    ids: list[int] = []
    seen: set[int] = set()
    for record in store.read_all():
        if record.get("phase") != ItemPhase.ANALYZE or record.get("outcome") != ItemOutcome.OK:
            continue
        mid = record.get("stack_media_id")
        if isinstance(mid, int) and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids


# ---------------------------------------------------------------------------
# S2: GT mapping + localization
# ---------------------------------------------------------------------------

_PRED_KEYS = frozenset({"x", "y", "width", "height"})
_WS = re.compile(r"\s+")


@dataclass
class DetectionMatchResult:
    matched_faces: int
    iou_values: list[float]
    degenerate_box_dropped: int
    pred_count: int
    gt_count: int
    matched_gt_indices: list[int] = field(default_factory=list)
    matched_pred_indices: list[int] = field(default_factory=list)


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
    gt_orig: list[int] = []
    dropped = 0
    for orig_i, box in enumerate(gt_boxes):
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
        gt_orig.append(orig_i)
    pred_tl: list[tuple[float, float, float, float]] = []
    pred_orig: list[int] = []
    for orig_i, pred in enumerate(predictions):
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
        pred_orig.append(orig_i)
    pairs, _pairwise = hungarian_iou_matches(gt_tl, pred_tl, threshold=IOU_MATCH_THRESHOLD)
    iou_values = [p[2] for p in pairs]
    return DetectionMatchResult(
        matched_faces=len(pairs),
        iou_values=iou_values,
        degenerate_box_dropped=dropped,
        pred_count=len(pred_tl),
        gt_count=len(gt_tl),
        matched_gt_indices=[gt_orig[p[1]] for p in pairs],
        matched_pred_indices=[pred_orig[p[0]] for p in pairs],
    )


def _unwrap_rows(raw: Any, *, what: str) -> list[dict[str, Any]]:
    # Live stack routes return a JSON array. Object envelopes are a second
    # shape and are rejected so a mid-series change cannot pass silently.
    if isinstance(raw, list):
        rows: list[dict[str, Any]] = []
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                raise BenchError(
                    "export_envelope_invalid",
                    f"{what}[{i}] must be a JSON object; got {type(row).__name__}",
                )
            rows.append(row)
        return rows
    raise BenchError(
        "export_envelope_invalid",
        f"{what} must be a JSON array (bare list); got {type(raw).__name__}",
    )


def _identities_list(export: Any) -> list[dict[str, Any]]:
    if not isinstance(export, dict):
        raise BenchError(
            "export_envelope_invalid",
            f"export must be a dict; got {type(export).__name__}",
        )
    if "media_identities" not in export:
        raise BenchError(
            "export_envelope_invalid",
            "dict export is missing required key media_identities",
        )
    return _unwrap_rows(export["media_identities"], what="media_identities")


def _clusters_list(export: Any) -> list[dict[str, Any]]:
    if not isinstance(export, dict):
        raise BenchError(
            "export_envelope_invalid",
            f"export must be a dict; got {type(export).__name__}",
        )
    if "clusters" not in export:
        raise BenchError(
            "export_envelope_invalid",
            "dict export is missing required key clusters",
        )
    return _unwrap_rows(export["clusters"], what="clusters")


def _primary_name_for_row(row: dict[str, Any], roster: Sequence[str]) -> str | None:
    canon = {normalize_label(n): n for n in roster}
    label = str(row.get("cluster_label") or "")
    auto = bool(row.get("is_auto_label"))
    if auto and _looks_auto_id(label):
        return None
    if not label:
        return None
    return canon.get(normalize_label(label))


def map_cluster_labels_primary(
    export: Any,
    roster: Sequence[str],
) -> dict[int, list[str]]:
    by_media: dict[int, list[str]] = {}
    for row in _identities_list(export):
        mid = row.get("media_id")
        if not isinstance(mid, int):
            continue
        mapped = _primary_name_for_row(row, roster)
        if mapped:
            by_media.setdefault(mid, [])
            if mapped not in by_media[mid]:
                by_media[mid].append(mapped)
    return by_media


def _centre_in_box(cx: float, cy: float, box_tl: tuple[float, float, float, float]) -> bool:
    x1, y1, w, h = box_tl
    return x1 <= cx <= x1 + w and y1 <= cy <= y1 + h


def _optimistic_names_by_pred_index(
    entry: GoldenEntry,
    rows: list[dict[str, Any]],
    width: int,
    height: int,
) -> dict[int, str]:
    """Hungarian + centre-in-box GT name per prediction index (optimistic only).

    One pred claims at most one GT (``assigned_pred``). Native consumption
    then applies labeled-wins: a pred with a primary name ignores this map.
    """
    gt_named = [(b, gt_centre_to_tl(b.x, b.y, b.w, b.h)) for b in entry.face_boxes if b.name]
    if not gt_named:
        return {}
    pred_tl: list[tuple[float, float, float, float]] = []
    pred_idx: list[int] = []
    for pi, row in enumerate(rows):
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
        pred_idx.append(pi)
    if not pred_tl:
        return {}
    gt_only = [tl for _, tl in gt_named]
    pairs, _ = hungarian_iou_matches(gt_only, pred_tl, threshold=IOU_MATCH_THRESHOLD)
    assigned_gt: set[int] = {p[1] for p in pairs}
    assigned_pred: set[int] = {p[0] for p in pairs}
    out: dict[int, str] = {}
    for pi, gi, _iou in pairs:
        name = gt_named[gi][0].name
        if name:
            out[pred_idx[pi]] = name
    for gi, (box, tl) in enumerate(gt_named):
        if gi in assigned_gt or not box.name:
            continue
        cx, cy = box.x, box.y
        for pi, ptl in enumerate(pred_tl):
            if pi in assigned_pred:
                continue
            if _centre_in_box(cx, cy, ptl) or _centre_in_box(ptl[0] + ptl[2] / 2, ptl[1] + ptl[3] / 2, tl):
                out[pred_idx[pi]] = box.name
                assigned_pred.add(pi)
                break
    return out


def map_cluster_labels_optimistic(
    export: Any,
    manifest: GoldenManifest,
    join: dict[int, dict[str, Any]],
) -> dict[int, list[str]]:
    """Hungarian + centre-in-box on unlabeled residuals only (labeled-wins).

    Already-labeled preds keep their primary names and are excluded from
    the assignment matrix so a geometric overlap cannot union a second GT
    name onto the media list. Names are appended once (deduped).
    """
    roster = list(manifest.roster) or [n for e in manifest.entries for n in e.present_identities]
    primary = map_cluster_labels_primary(export, roster)
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
            if _primary_name_for_row(row, roster) is not None:
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
    *,
    localization_counts: dict[str, int] | None = None,
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
        rows_sorted = sorted(rows, key=lambda r: str(r.get("identity_id", "")))
        pred_boxes = [r.get("bbox") or {} for r in rows_sorted]
        match = match_detection_boxes(
            list(entry.face_boxes),
            pred_boxes,
            image_width=width,
            image_height=height,
        )
        if localization_counts is not None:
            localization_counts["degenerate_box_dropped"] = (
                localization_counts.get("degenerate_box_dropped", 0) + match.degenerate_box_dropped
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
            # detection (IoU match). Predictions come only from matched faces.
            matched_idx = set(match.matched_gt_indices)
            labeled_native: list[str] = []
            for gi, box in enumerate(entry.face_boxes):
                if gi not in matched_idx:
                    continue
                name = box.name if isinstance(box, FaceBox) else box.get("name")
                if name and name not in labeled_native:
                    labeled_native.append(name)
            matched_pred = set(match.matched_pred_indices)
            predicted_native: list[str] = []
            roster_for_row = roster or [n for e in manifest.entries for n in e.present_identities]
            opt_by_pred: dict[int, str] = {}
            if "optimistic" in label_map:
                opt_by_pred = _optimistic_names_by_pred_index(entry, rows_sorted, width, height)
            for pi, row in enumerate(rows_sorted):
                if pi not in matched_pred:
                    continue
                name = _primary_name_for_row(row, roster_for_row)
                if name is None:
                    name = opt_by_pred.get(pi)
                if name and name not in predicted_native:
                    predicted_native.append(name)
            matched_boxes = [
                entry.face_boxes[i]
                for i in match.matched_gt_indices
                if 0 <= i < len(entry.face_boxes)
            ]
            stranger_native = (
                sum(1 for b in matched_boxes if (b.name if isinstance(b, FaceBox) else b.get("name")) is None)
                if entry.face_count == len(entry.face_boxes)
                else 0
            )
            id_rows.append(
                ImageIdentities(
                    image=entry.path,
                    predicted=predicted_native,
                    labeled=labeled_native,
                    recognition_enabled=entry.policy.recognition_enabled,
                    stranger_faces=stranger_native,
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
