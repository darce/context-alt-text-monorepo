"""The benchmark scorer delegates IoU and assignment to face_assignment."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.bench import score
from scripts.eval_harness.face_assignment import associate_detections, hungarian_iou_pairs


def test_hungarian_iou_matches_delegates_matrix_and_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[list[list[float]], float]] = []

    def recording_matcher(iou_matrix, *, threshold):
        seen.append((iou_matrix.tolist(), threshold))
        return []

    monkeypatch.setattr(score, "hungarian_iou_pairs", recording_matcher)

    pairs, pairwise = score.hungarian_iou_matches(
        [(0.2, 0.2, 0.2, 0.2)], [(0.2, 0.2, 0.2, 0.2)], threshold=0.37
    )

    assert seen == [([[1.0]], 0.37)]
    assert pairs == []
    assert pairwise == [1.0]


@pytest.mark.parametrize("shape", [(0, 2), (2, 0)])
def test_hungarian_iou_pairs_returns_empty_for_empty_matrix(shape: tuple[int, int]) -> None:
    assert hungarian_iou_pairs(np.empty(shape)) == []


@pytest.mark.parametrize(
    ("gt_tl", "pred_tl", "threshold", "expected_pairs", "expected_pairwise"),
    [
        (
            [(0.0, 0.0, 0.4, 0.4), (0.4, 0.0, 0.4, 0.4)],
            [(0.35, 0.0, 0.4, 0.4), (0.05, 0.0, 0.4, 0.4)],
            0.5,
            [(0, 1, 0.7777777777777773), (1, 0, 0.7777777777777777)],
            [0.06666666666666672, 0.7777777777777773, 0.7777777777777777, 0.06666666666666665],
        ),
        (
            [(0.4, 0.4, 0.2, 0.2)],
            [(0.45, 0.4, 0.2, 0.2), (0.4, 0.4, 0.2, 0.2)],
            0.5,
            [(1, 0, 1.0)],
            [0.6000000000000003, 1.0],
        ),
        (
            [(0.4, 0.4, 0.0, 0.2)],
            [(0.4, 0.4, 0.2, 0.2)],
            0.5,
            [],
            [0.0],
        ),
        (
            [(0.9, 0.2, 0.3, 0.5)],
            [(0.9, 0.2, 0.2, 0.5)],
            0.8,
            [(0, 0, 1.0)],
            [1.0],
        ),
    ],
)
def test_hungarian_iou_matches_preserves_current_box_results(
    gt_tl, pred_tl, threshold, expected_pairs, expected_pairwise
) -> None:
    pairs, pairwise = score.hungarian_iou_matches(gt_tl, pred_tl, threshold=threshold)

    assert [(row, col) for row, col, _ in pairs] == [
        (row, col) for row, col, _ in expected_pairs
    ]
    assert [iou for _, _, iou in pairs] == pytest.approx(
        [iou for _, _, iou in expected_pairs]
    )
    assert pairwise == pytest.approx(expected_pairwise)


def test_associate_detections_preserves_two_gt_crossing_pairs() -> None:
    result = associate_detections(
        [[35.0, 0.0, 40.0, 40.0], [5.0, 0.0, 40.0, 40.0]],
        [
            {"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4, "name": "A"},
            {"x": 0.6, "y": 0.2, "w": 0.4, "h": 0.4, "name": "B"},
        ],
        [100, 100],
    )

    assert [(pair.det_index, pair.gt_index, pair.name) for pair in result.pairs] == [
        (0, 1, "B"),
        (1, 0, "A"),
    ]
    assert [pair.iou for pair in result.pairs] == pytest.approx(
        [0.7777777777777778, 0.7777777777777778]
    )
