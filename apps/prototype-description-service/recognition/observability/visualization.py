"""
Visualization helpers for clustering reports and similarity analysis.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from recognition.observability.reports import BatchJobReport


class ClusterVisualizer:
    """Generate visual artifacts for clustering observability."""

    def __init__(self, output_dir: Path) -> None:
        """Initialize the visualizer.

        Args:
            output_dir: Directory where charts should be written.
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _init_matplotlib() -> None:
        """Lazy init for matplotlib with Agg backend."""
        import matplotlib

        matplotlib.use("Agg")

    def generate_batch_report_chart(
        self,
        report: BatchJobReport,
        algorithm: str,
        timestamp: datetime | None = None,
    ) -> Path:
        """Produce a stacked bar chart summarizing a clustering batch.

        Args:
            report: Batch job report containing summary metrics.
            algorithm: Algorithm name to annotate the chart.
            timestamp: Optional timestamp to include in the visualization.

        Returns:
            Path: Location of the generated chart image.
        """
        ts = timestamp or datetime.now()
        fname = f"batch_{report.job_id}_{ts.strftime('%Y%m%d%H%M%S')}.png"
        path = self.output_dir / fname

        # Lazy import to avoid hard dependency when not used
        self._init_matplotlib()
        import matplotlib.pyplot as plt

        labels = ["accepted", "suggested", "rejected"]
        counts = [report.accept_count, report.suggest_count, report.reject_count]

        fig, ax = plt.subplots()
        ax.barh(["results"], [sum(counts)], color="#e0e0e0", label="total")
        left = 0
        colors = ["#4caf50", "#ffc107", "#f44336"]
        for idx, count in enumerate(counts):
            ax.barh(["results"], [count], left=left, color=colors[idx], label=labels[idx])
            left += count

        ax.set_title(f"Clustering Batch ({algorithm})")
        ax.set_xlabel("count")
        ax.legend()
        ax.grid(axis="x", linestyle="--", alpha=0.5)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path

    def generate_similarity_histogram(
        self,
        cluster_id: UUID,
        similarities: list[float],
        algorithm: str | None = None,
    ) -> Path:
        """Generate a similarity histogram for a cluster."""
        fname = f"cluster_{cluster_id}_similarities.png"
        path = self.output_dir / fname

        self._init_matplotlib()
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.hist(similarities, bins=10, range=(0.0, 1.0), color="#2196f3", alpha=0.8)
        ax.set_xlim(0, 1)
        ax.set_xlabel("similarity")
        ax.set_ylabel("count")
        ax.set_title(f"Similarity Histogram ({algorithm or 'unknown'})")
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path
