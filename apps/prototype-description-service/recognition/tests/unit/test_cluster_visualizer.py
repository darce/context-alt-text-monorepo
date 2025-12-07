"""Tests for ClusterVisualizer chart generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from recognition.observability.reports import BatchJobReport
from recognition.observability.visualization import ClusterVisualizer
from recognition.shared.ids import generate_id


def make_report() -> BatchJobReport:
    return BatchJobReport(
        job_id=str(generate_id()),
        algorithm="representative",
        started_at=datetime(2025, 1, 1, 0, 0, 0),
        completed_at=datetime(2025, 1, 1, 0, 0, 1),
        total_identities=10,
        accept_count=6,
        suggest_count=3,
        reject_count=1,
        clusters_created=2,
        avg_similarity=0.84,
    )


def test_generate_batch_report_chart(tmp_path: Path) -> None:
    visualizer = ClusterVisualizer(output_dir=tmp_path)
    report = make_report()

    chart_path = visualizer.generate_batch_report_chart(report, algorithm=report.algorithm, timestamp=report.started_at)

    assert chart_path.exists()
    assert chart_path.suffix == ".png"


def test_generate_similarity_heatmap(tmp_path: Path) -> None:
    visualizer = ClusterVisualizer(output_dir=tmp_path)
    similarities = list(np.linspace(0.1, 0.9, num=5))
    chart_path = visualizer.generate_similarity_histogram(
        cluster_id=str(generate_id()),
        similarities=similarities,
        algorithm="graph",
    )

    assert chart_path.exists()
    assert chart_path.suffix == ".png"
