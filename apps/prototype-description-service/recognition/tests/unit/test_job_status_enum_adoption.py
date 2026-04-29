from __future__ import annotations

import ast
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
    "recognition/domain/services/export_service.py",
    "recognition/infrastructure/repositories/scan_queue_repository.py",
    "recognition/observability/recognition_runs.py",
    "recognition/interface_adapters/http/routers/clusters.py",
    "recognition/interface_adapters/http/routers/analyze.py",
    "recognition/interface_adapters/http/routers/analyze_multipart.py",
    "recognition/interface_adapters/http/deps/stores.py",
    "recognition/worker/handlers/clustering.py",
    "recognition/worker/handlers/scan.py",
    "recognition/worker/scan_worker.py",
)

_ALLOWED_ADAPTER_REFERENCE_PATHS = {
    "recognition/application/embedding/detector.py",
    "recognition/application/embedding/generator.py",
    "recognition/application/tasks/scan.py",
}

_ALLOWED_REMOTE_CALL_SITES = {
    "recognition/application/embedding/detector.py": {"detect_faces"},
    "recognition/application/embedding/generator.py": {"analyze"},
}


def _iter_application_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "recognition" / "application").rglob("*.py"))


def _relative_path(repo_root: Path, path: Path) -> str:
    return str(path.relative_to(repo_root))


def _find_adapter_reference_paths(repo_root: Path) -> set[str]:
    return {
        _relative_path(repo_root, path)
        for path in _iter_application_files(repo_root)
        if "InsightFaceAdapter" in path.read_text()
    }


class _RemoteCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"analyze", "detect_faces"}:
            self.calls.add(func.attr)
        self.generic_visit(node)


def _find_remote_call_sites(repo_root: Path) -> dict[str, set[str]]:
    call_sites: dict[str, set[str]] = {}

    for path in _iter_application_files(repo_root):
        visitor = _RemoteCallVisitor()
        visitor.visit(ast.parse(path.read_text(), filename=str(path)))
        if visitor.calls:
            call_sites[_relative_path(repo_root, path)] = visitor.calls

    return call_sites


def test_clustering_and_scan_paths_use_job_enums() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for relative_path in _TARGETS:
        file_path = repo_root / relative_path
        for line_number, line in enumerate(file_path.read_text().splitlines(), start=1):
            if any(pattern.search(line) for pattern in _FORBIDDEN_PATTERNS):
                violations.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert not violations, "\n".join(violations)


def test_application_adapter_inventory_stays_bounded() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    assert _find_adapter_reference_paths(repo_root) == _ALLOWED_ADAPTER_REFERENCE_PATHS


def test_only_known_application_seams_make_remote_adapter_calls() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    assert _find_remote_call_sites(repo_root) == _ALLOWED_REMOTE_CALL_SITES