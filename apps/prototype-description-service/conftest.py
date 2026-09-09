"""Pytest collection-scope receipt and optional full-scope enforcement."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("collection scope")
    group.addoption(
        "--require-full-collection",
        action="store_true",
        help="fail unless every existing testpaths root contributes tests",
    )
    group.addoption(
        "--collection-scope-receipt",
        metavar="PATH",
        help="override the collection-scope receipt path",
    )
    parser.addini(
        "collection_scope_receipt",
        "path for the machine-readable collection-scope receipt",
        default="/tmp/prototype-description-service-pytest-collection-scope.json",
    )


def _relative_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return path.as_posix()


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    root = config.rootpath.resolve()
    declared = list(config.getini("testpaths"))
    declared_paths = [(label, (root / label).resolve()) for label in declared]
    existing = [(label, path) for label, path in declared_paths if path.exists()]

    collected: set[str] = set()
    for item in session.items:
        item_path = Path(str(item.path)).resolve()
        for label, declared_path in existing:
            if item_path.is_relative_to(declared_path):
                collected.add(label)

    expected = {label for label, _ in existing}
    scope = "full" if expected and collected == expected else "narrowed"
    receipt = {
        "declared_roots": declared,
        "collected_roots": sorted(collected),
        "collected_count": len(session.items),
        "scope": scope,
    }
    receipt_path = Path(
        config.getoption("--collection-scope-receipt")
        or config.getini("collection_scope_receipt")
    )
    if not receipt_path.is_absolute():
        receipt_path = root / receipt_path
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    config._collection_scope_receipt = receipt  # type: ignore[attr-defined]
    config._collection_scope_receipt_path = receipt_path  # type: ignore[attr-defined]
    strict_gate = os.environ.get("ACX_STRICT_GATE", "").strip() == "1"
    require_full = config.getoption("--require-full-collection")
    if (require_full or strict_gate) and scope != "full":
        source = "--require-full-collection" if require_full else "ACX_STRICT_GATE=1"
        missing = sorted(expected - collected)
        raise pytest.UsageError(
            "full collection required; collection was narrowed; "
            f"missing roots: {', '.join(missing) or '(none declared/existing)'}; "
            f"enforced by {source}"
        )


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    config = terminalreporter.config
    receipt = getattr(config, "_collection_scope_receipt", None)
    if receipt is None:
        return
    path = getattr(config, "_collection_scope_receipt_path")
    terminalreporter.write_sep(
        "=",
        "collection scope: "
        f"{receipt['scope']}; declared={receipt['declared_roots']}; "
        f"collected={receipt['collected_roots']}; count={receipt['collected_count']}; "
        f"receipt={_relative_label(path, config.rootpath.resolve())}",
    )
