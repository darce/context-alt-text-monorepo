from __future__ import annotations

import pytest

from scripts.eval_harness.face_metrics import latency_summary, nearest_rank_percentile


def test_latency_summary_uses_nearest_rank_for_integer_boundary():
    summary = latency_summary(list(range(20)))

    assert summary is not None
    assert summary["p95"] == 18.0


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        ([7.0], 0.95, 7.0),
        ([3.0, 1.0, 2.0], 0.0, 1.0),
        ([3.0, 1.0, 2.0], 1.0, 3.0),
    ],
)
def test_nearest_rank_percentile_boundary_cases(values, q, expected):
    assert nearest_rank_percentile(values, q) == expected
