from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

# These are the only application-layer files that should mention InsightFaceAdapter.
# tasks/scan.py belongs here because it wires adapter providers, even though it
# must not invoke the remote adapter surface directly.
_ALLOWED_ADAPTER_REFERENCE_PATHS = {
    "recognition/application/embedding/detector.py",
    "recognition/application/embedding/generator.py",
    "recognition/application/tasks/scan.py",
}

# Only concrete remote awaits belong here. Keep this allowlist in sync with the
# InsightFaceAdapter public remote-call surface when that adapter grows.
_ALLOWED_REMOTE_CALL_SITES = {
    "recognition/application/embedding/detector.py": {"detect_faces"},
    "recognition/application/embedding/generator.py": {"analyze"},
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _iter_application_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "recognition" / "application").rglob("*.py"))


def _relative_path(repo_root: Path, path: Path) -> str:
    return str(path.relative_to(repo_root))


def _expression_path(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expression_path(node.value)
        if parent is None:
            return None
        return f"{parent}.{node.attr}"
    return None


def _annotation_mentions_insightface_adapter(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id == "InsightFaceAdapter"
    if isinstance(node, ast.Attribute):
        return node.attr == "InsightFaceAdapter"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "InsightFaceAdapter" in node.value
    return any(_annotation_mentions_insightface_adapter(child) for child in ast.iter_child_nodes(node))


def _iter_function_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[ast.arg]:
    yield from node.args.posonlyargs
    yield from node.args.args
    yield from node.args.kwonlyargs
    if node.args.vararg is not None:
        yield node.args.vararg
    if node.args.kwarg is not None:
        yield node.args.kwarg


class _InsightFaceRemoteCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: set[str] = set()
        self._function_receivers: list[set[str]] = []
        self._class_receivers: list[set[str]] = []

    def _known_receivers(self) -> set[str]:
        receivers: set[str] = set()
        for scope in self._class_receivers:
            receivers.update(scope)
        for scope in self._function_receivers:
            receivers.update(scope)
        return receivers

    def _record_receiver(self, receiver: str) -> None:
        if self._function_receivers:
            self._function_receivers[-1].add(receiver)
        if receiver.startswith("self.") and self._class_receivers:
            self._class_receivers[-1].add(receiver)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_receivers.append(set())
        self.generic_visit(node)
        self._class_receivers.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        initial_receivers = {
            parameter.arg
            for parameter in _iter_function_parameters(node)
            if _annotation_mentions_insightface_adapter(parameter.annotation)
        }
        self._function_receivers.append(initial_receivers)
        self.generic_visit(node)
        self._function_receivers.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if _annotation_mentions_insightface_adapter(node.annotation):
            target = _expression_path(node.target)
            if target is not None:
                self._record_receiver(target)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value_path = _expression_path(node.value)
        if value_path in self._known_receivers():
            for target in node.targets:
                target_path = _expression_path(target)
                if target_path is not None:
                    self._record_receiver(target_path)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            receiver_path = _expression_path(func.value)
            if receiver_path in self._known_receivers() and func.attr in {"analyze", "detect_faces"}:
                self.calls.add(func.attr)
        self.generic_visit(node)


def _find_adapter_reference_paths(repo_root: Path) -> set[str]:
    return {
        _relative_path(repo_root, path)
        for path in _iter_application_files(repo_root)
        if "InsightFaceAdapter" in path.read_text()
    }


def _find_remote_call_sites(repo_root: Path) -> dict[str, set[str]]:
    call_sites: dict[str, set[str]] = {}

    for path in _iter_application_files(repo_root):
        visitor = _InsightFaceRemoteCallVisitor()
        visitor.visit(ast.parse(path.read_text(), filename=str(path)))
        if visitor.calls:
            call_sites[_relative_path(repo_root, path)] = visitor.calls

    return call_sites


def test_application_adapter_inventory_stays_bounded() -> None:
    repo_root = _repo_root()

    assert _find_adapter_reference_paths(repo_root) == _ALLOWED_ADAPTER_REFERENCE_PATHS


def test_only_known_application_seams_make_remote_adapter_calls() -> None:
    repo_root = _repo_root()

    assert _find_remote_call_sites(repo_root) == _ALLOWED_REMOTE_CALL_SITES
