from __future__ import annotations

import re
from pathlib import Path


_STATUS_VALUES = "pending|running|completed|failed"
_PHASE_VALUES = "queued|detecting|clustering|retrying|awaiting_projection|failed|complete"
_FORBIDDEN_PATTERNS = (
    re.compile(rf"(?:^|\W)(?:status|\.status)\s*(?:=|==|!=)\s*\"({_STATUS_VALUES})\""),
    re.compile(rf"(?:^|\W)(?:phase|\.phase)\s*(?:=|==|!=)\s*\"({_PHASE_VALUES})\""),
)
_TARGETS = (
    "recognition/application/orchestration/clustering/orchestrator.py",
    "recognition/application/scan/service.py",
    "recognition/interface_adapters/http/routers/clusters.py",
    "recognition/interface_adapters/http/routers/analyze.py",
    "recognition/interface_adapters/http/routers/analyze_multipart.py",
    "recognition/interface_adapters/http/deps/stores.py",
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