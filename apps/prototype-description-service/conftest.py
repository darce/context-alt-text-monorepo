"""Pytest collection-scope receipt and optional full-scope enforcement."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns

import pytest

_RECEIPT_DIRECTORY = Path("/tmp")
_RECEIPT_PREFIX = "prototype-description-service-pytest-collection-scope"
_LEGACY_RECEIPT_PATH = _RECEIPT_DIRECTORY / (
    "prototype-description-service-pytest-collection-scope.json"
)
_SERVICE_PYPROJECT = Path(__file__).with_name("pyproject.toml").resolve()


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
        default="",
    )


def _session_receipt_identity() -> tuple[str, Path]:
    """Return the session timestamp and a path partitioned by this process."""
    started_at = datetime.now(UTC).isoformat()
    return started_at, _RECEIPT_DIRECTORY / (
        f"{_RECEIPT_PREFIX}-{os.getpid()}-{time_ns()}.json"
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    started_at, default_path = _session_receipt_identity()
    config = session.config
    config._collection_scope_receipt_started_at = started_at  # type: ignore[attr-defined]
    config._collection_scope_receipt_default_path = default_path  # type: ignore[attr-defined]


def _receipt_path(config: pytest.Config, root: Path) -> Path:
    configured = config.getoption("--collection-scope-receipt")
    if not configured:
        ini_value = config.getini("collection_scope_receipt")
        ini_path = Path(ini_value) if ini_value else None
        project_default = getattr(config, "inifile", None)
        ini_config = getattr(config, "_inicfg", {}).get("collection_scope_receipt")
        ini_is_cli_override = getattr(ini_config, "origin", None) == "override"
        # The checked-in pyproject carries the pre-fix fixed path. Treat only
        # that value as the old default; other ini values remain overrides.
        is_legacy_project_default = (
            ini_path is not None
            and ini_path.resolve() == _LEGACY_RECEIPT_PATH.resolve()
            and project_default is not None
            and Path(project_default).resolve() == _SERVICE_PYPROJECT
            and not ini_is_cli_override
        )
        if not is_legacy_project_default:
            configured = ini_value
    if configured:
        receipt_path = Path(configured)
    else:
        receipt_path = getattr(config, "_collection_scope_receipt_default_path", None)
        if receipt_path is None:
            _, receipt_path = _session_receipt_identity()
    if not receipt_path.is_absolute():
        receipt_path = root / receipt_path
    return receipt_path.resolve()


def _refresh_canonical_receipt(payload: str) -> None:
    """Point the runbook's documented receipt path at this run.

    Without this the documented `cat` returns whichever run last wrote the old
    fixed path, so an operator reads a stale scope as if it were current.
    Replaced atomically so a concurrent xdist worker never observes a partial
    file; a read-only /tmp is non-fatal because the per-process receipt stays
    authoritative.
    """
    try:
        tmp = _LEGACY_RECEIPT_PATH.with_name(
            f"{_LEGACY_RECEIPT_PATH.name}.{os.getpid()}.{time_ns()}.tmp"
        )
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, _LEGACY_RECEIPT_PATH)
    except OSError:
        pass


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
        "pid": os.getpid(),
        "rootdir": str(root),
        "started_at": getattr(
            config,
            "_collection_scope_receipt_started_at",
            datetime.now(UTC).isoformat(),
        ),
        "declared_roots": declared,
        "collected_roots": sorted(collected),
        "collected_count": len(session.items),
        "scope": scope,
    }
    receipt_path = _receipt_path(config, root)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt, indent=2) + "\n"
    receipt_path.write_text(payload, encoding="utf-8")
    _refresh_canonical_receipt(payload)

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
        # Under xdist collection runs in the workers, so the controller holds
        # no receipt and would otherwise print nothing at all.
        terminalreporter.write_sep(
            "=",
            "collection scope: recorded per worker; "
            f"latest={_LEGACY_RECEIPT_PATH}; "
            f"all={_RECEIPT_DIRECTORY / (_RECEIPT_PREFIX + '-*.json')}",
        )
        return
    path = config._collection_scope_receipt_path  # type: ignore[attr-defined]
    terminalreporter.write_sep(
        "=",
        "collection scope: "
        f"{receipt['scope']}; declared={receipt['declared_roots']}; "
        f"collected={receipt['collected_roots']}; count={receipt['collected_count']}; "
        f"receipt={path}",
    )
