from __future__ import annotations

import re
from pathlib import Path

from recognition.domain.job import JobPhase, JobStatus, JobType
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse

_STATUS_VALUES = "pending|running|completed|failed"
_PHASE_VALUES = "queued|detecting|clustering|retrying|awaiting_projection|failed|complete"
_SCAN_ITEM_STATUS_VALUES = "pending|processing|completed|failed|cancelled|skipped"
_FORBIDDEN_PATTERNS = (
    re.compile(rf"(?:^|\W)(?:status|\.status)\s*(?:=|==|!=)\s*\"({_STATUS_VALUES})\""),
    re.compile(rf"(?:^|\W)(?:phase|\.phase)\s*(?:=|==|!=)\s*\"({_PHASE_VALUES})\""),
    re.compile(rf"(?:job_status|status)\s+in\s+\([^\)]*\"({_STATUS_VALUES})\""),
    re.compile(rf"(?:^|\W)(?:status|\.status)\s*(?:=|==|!=)\s*\"({_SCAN_ITEM_STATUS_VALUES})\""),
    re.compile(r"(?:^|\W)(?:type|\.type)\s*=\s*\"(analyze|clustering|curation|split)\""),
)
_TARGETS = (
    "recognition/application/orchestration/clustering/orchestrator.py",
    "recognition/application/scan/service.py",
    "recognition/application/services/export_service.py",
    "recognition/infrastructure/repositories/scan_queue_repository.py",
    "recognition/observability/recognition_runs.py",
    "recognition/interface_adapters/http/routers/clusters_admission.py",
    "recognition/interface_adapters/http/routers/clusters_snapshot.py",
    "recognition/interface_adapters/http/routers/clusters_topology.py",
    "recognition/interface_adapters/http/routers/clusters_maintenance.py",
    "recognition/interface_adapters/http/routers/analyze.py",
    "recognition/interface_adapters/http/routers/analyze_multipart.py",
    "recognition/interface_adapters/http/deps/stores.py",
    "recognition/worker/handlers/clustering.py",
    "recognition/worker/handlers/scan.py",
    "recognition/worker/scan_worker.py",
)


def test_clustering_and_scan_paths_use_job_enums() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for relative_path in _TARGETS:
        file_path = repo_root / relative_path
        for line_number, line in enumerate(file_path.read_text().splitlines(), start=1):
            if any(pattern.search(line) for pattern in _FORBIDDEN_PATTERNS):
                violations.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert not violations, "\n".join(violations)


def test_job_response_models_use_enum_types() -> None:
    assert JobStatusResponse.model_fields["type"].annotation is JobType
    assert JobStatusResponse.model_fields["status"].annotation is JobStatus
    assert JobProgressResponse.model_fields["phase"].annotation == JobPhase | None


def test_clustering_job_types_groups_clustering_curation_split() -> None:
    """CLUSTERING_JOB_TYPES centralizes the clustering-family types (persisted to IdentityClusteringJob)."""
    from recognition.domain.job import CLUSTERING_JOB_TYPES

    assert isinstance(CLUSTERING_JOB_TYPES, frozenset)
    assert frozenset({JobType.CLUSTERING, JobType.CURATION, JobType.SPLIT}) == CLUSTERING_JOB_TYPES
    # ANALYZE routes to the scan model, not the clustering-job table.
    assert JobType.ANALYZE not in CLUSTERING_JOB_TYPES


def test_job_repository_uses_centralized_clustering_job_types() -> None:
    """The clustering-family grouping must not be re-inlined as a literal tuple in the repository."""
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "recognition/infrastructure/repositories/job_repository.py").read_text()
    assert "CLUSTERING_JOB_TYPES" in src
    assert "(JobType.CLUSTERING, JobType.CURATION, JobType.SPLIT)" not in src


def test_scan_worker_uses_centralized_clustering_job_types() -> None:
    """The worker's claim/recover queries must not re-inline the clustering-family string list."""
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "recognition/worker/scan_worker.py").read_text()
    assert "CLUSTERING_JOB_TYPES" in src
    assert '["clustering", "curation", "split"]' not in src
