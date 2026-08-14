"""IoU / assignment helpers. Threshold is IOU_MATCH_THRESHOLD from face_assignment."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from scripts.eval_harness.face_assignment import IOU_MATCH_THRESHOLD

__all__ = [
    "IOU_MATCH_THRESHOLD",
    "clamp01",
    "gt_centre_to_tl",
    "iou_tl",
    "pred_px_to_norm_tl",
]


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else float(value)


def gt_centre_to_tl(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    return (x - w / 2.0, y - h / 2.0, w, h)


def pred_px_to_norm_tl(
    x: float, y: float, width: float, height: float, image_width: int, image_height: int
) -> tuple[float, float, float, float]:
    return (x / image_width, y / image_height, width / image_width, height / image_height)


def _xyxy(x1: float, y1: float, w: float, h: float) -> tuple[float, float, float, float]:
    return (clamp01(x1), clamp01(y1), clamp01(x1 + w), clamp01(y1 + h))


def box_area_xyxy(box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def iou_tl(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = _xyxy(a[0], a[1], a[2], a[3])
    bx1, by1, bx2, by2 = _xyxy(b[0], b[1], b[2], b[3])
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    if aa <= 0.0 or ba <= 0.0:
        return 0.0
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = aa + ba - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


def hungarian_iou_matches(
    gt_tl: Sequence[Sequence[float]],
    pred_tl: Sequence[Sequence[float]],
    *,
    threshold: float = IOU_MATCH_THRESHOLD,
) -> tuple[list[tuple[int, int, float]], list[float]]:
    n_gt = len(gt_tl)
    n_pred = len(pred_tl)
    pairwise: list[float] = []
    if n_gt == 0 or n_pred == 0:
        return [], pairwise
    matrix = np.zeros((n_pred, n_gt), dtype=np.float64)
    for i, pred in enumerate(pred_tl):
        for j, gt in enumerate(gt_tl):
            val = iou_tl(pred, gt)
            matrix[i, j] = val
            pairwise.append(val)
    row_ind, col_ind = linear_sum_assignment(-matrix)
    pairs: list[tuple[int, int, float]] = []
    for r, c in zip(row_ind, col_ind, strict=True):
        iou_val = float(matrix[r, c])
        if iou_val >= threshold:
            pairs.append((int(r), int(c), iou_val))
    return pairs, pairwise
