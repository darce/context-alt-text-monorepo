"""Observability module for recognition service clustering.

This module provides centralized logging, visualization, and reporting for
cluster assignment decisions. It extracts scattered logging calls from the
main application logic into a dedicated, structured interface.

Components:
- ClusteringLogger: Structured decision logging with algorithm context
- ClusterVisualizer: Chart generation after batch jobs
- BatchJobReport: Statistics collection for logging and visualization
- DecisionLog: Individual decision record dataclass

Usage:
    from recognition.observability import ClusteringLogger, ClusterVisualizer

    logger = ClusteringLogger(algorithm="HDBSCAN", job_id=job.id)
    logger.log_batch_start(identity_count=150, algorithm="HDBSCAN")

    # ... during processing ...
    logger.log_decision(identity_id, cluster_id, DecisionType.ACCEPT, 0.87)

    # ... after batch completes ...
    visualizer = ClusterVisualizer()
    chart_path = visualizer.generate_batch_report_chart(report, "HDBSCAN")
"""

from recognition.observability.decisions import DecisionLog, DecisionType
from recognition.observability.logging import ClusteringLogger
from recognition.observability.reports import BatchJobReport
from recognition.observability.visualization import ClusterVisualizer

__all__ = [
    "ClusteringLogger",
    "ClusterVisualizer",
    "BatchJobReport",
    "DecisionLog",
    "DecisionType",
]
