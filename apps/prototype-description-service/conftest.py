"""Pytest collection-scope receipt and optional full-scope enforcement."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from time import time_ns

import pytest

_RECEIPT_DIRECTORY = Path("/tmp")
_RECEIPT_PREFIX = "prototype-description-service-pytest-collection-scope"
_LEGACY_RECEIPT_PATH = _RECEIPT_DIRECTORY / ("prototype-description-service-pytest-collection-scope.json")
_SERVICE_PYPROJECT = Path(__file__).with_name("pyproject.toml").resolve()
_EVAL_HARNESS_TEST_DIRECTORY = Path(__file__).parent / "scene" / "tests"
_NESTED_COLLECTION_TIMEOUT_SECONDS = 240


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
    return started_at, _RECEIPT_DIRECTORY / (f"{_RECEIPT_PREFIX}-{os.getpid()}-{time_ns()}.json")


def pytest_sessionstart(session: pytest.Session) -> None:
    started_at, default_path = _session_receipt_identity()
    config = session.config
    config._collection_scope_receipt_started_at = started_at  # type: ignore[attr-defined]
    config._collection_scope_receipt_default_path = default_path  # type: ignore[attr-defined]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "eval_harness: tests for the offline evaluation harness"
    )


def _explicitly_selected_eval_harness_paths(
    config: pytest.Config, eval_items: list[pytest.Item]
) -> set[Path]:
    item_paths = {Path(str(item.path)).resolve() for item in eval_items}
    invocation = config.invocation_params
    roots = {Path(invocation.dir).resolve(), config.rootpath.resolve()}
    selected_paths: set[Path] = set()
    args = (*config.args, *invocation.args)
    for arg in args:
        path_arg = str(arg).partition("::")[0]
        if not path_arg or path_arg.startswith("-"):
            continue
        path = Path(path_arg)
        candidates = (path,) if path.is_absolute() else (root / path for root in roots)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in item_paths:
                selected_paths.add(resolved)
    return selected_paths


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> Generator[None, None, None]:
    mark_expression = config.option.markexpr or ""
    explicitly_selected = re.search(
        r"(?:^|[^A-Za-z0-9_])eval_harness(?:$|[^A-Za-z0-9_])", mark_expression
    ) is not None
    eval_directory = _EVAL_HARNESS_TEST_DIRECTORY.resolve()
    eval_items: list[pytest.Item] = []
    for item in items:
        item_path = Path(str(item.path)).resolve()
        if (
            item_path.name.startswith("test_eval_harness")
            and item_path.is_relative_to(eval_directory)
        ):
            item.add_marker(pytest.mark.eval_harness)
            eval_items.append(item)

    explicitly_selected_paths = _explicitly_selected_eval_harness_paths(
        config, eval_items
    )
    deselected_items = [
        item
        for item in eval_items
        if not explicitly_selected
        and Path(str(item.path)).resolve() not in explicitly_selected_paths
    ]
    if deselected_items:
        deselected_ids = {id(item) for item in deselected_items}
        items[:] = [item for item in items if id(item) not in deselected_ids]
        config._eval_harness_deselected_paths = tuple(  # type: ignore[attr-defined]
            Path(str(item.path)).resolve() for item in deselected_items
        )
        config._eval_harness_deselected_count = len(deselected_items)  # type: ignore[attr-defined]
        config.hook.pytest_deselected(items=deselected_items)

    yield


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
        tmp = _LEGACY_RECEIPT_PATH.with_name(f"{_LEGACY_RECEIPT_PATH.name}.{os.getpid()}.{time_ns()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, _LEGACY_RECEIPT_PATH)
    except OSError:
        pass


def _run_nested_collection(
    project_root: Path, receipt_path: Path, *paths: str
) -> tuple[tuple[str, ...], str]:
    env = os.environ.copy()
    env.pop("ACX_STRICT_GATE", None)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
        "--collection-scope-receipt",
        str(receipt_path),
        *paths,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=_NESTED_COLLECTION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:

        def output_tail(value: str | bytes | None) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                value = value.decode(errors="replace")
            return value[-2000:]

        message = (
            "Nested pytest collection timed out after "
            f"{_NESTED_COLLECTION_TIMEOUT_SECONDS} seconds for paths: "
            f"{', '.join(paths) if paths else '<default collection>'}"
        )
        stdout_tail = output_tail(exc.stdout)
        stderr_tail = output_tail(exc.stderr)
        if stdout_tail:
            message += f"; partial stdout tail: {stdout_tail}"
        if stderr_tail:
            message += f"; partial stderr tail: {stderr_tail}"
        raise RuntimeError(message) from exc
    output = result.stdout + result.stderr
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return tuple(line.strip() for line in result.stdout.splitlines() if "::" in line), output


def _cached_nested_collection(
    tmp_path_factory: pytest.TempPathFactory, name: str, *paths: str
) -> tuple[tuple[str, ...], str]:
    project_root = Path(__file__).resolve().parent
    shared_directory = tmp_path_factory.getbasetemp().parent
    if os.environ.get("PYTEST_XDIST_WORKER") is None:
        receipt_path = shared_directory / f"nested-{name}-receipt.json"
        return _run_nested_collection(project_root, receipt_path, *paths)

    test_run_uid = os.environ["PYTEST_XDIST_TESTRUNUID"]
    cache_path = shared_directory / f"nested-{test_run_uid}-{name}-collection.json"
    failure_marker_path = cache_path.with_name(f"{cache_path.name}.failed")
    lock_path = cache_path.with_suffix(".lock")
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            elif failure_marker_path.exists():
                failure_payload = json.loads(
                    failure_marker_path.read_text(encoding="utf-8")
                )
                raise RuntimeError(failure_payload["error"])
            else:
                receipt_path = shared_directory / (
                    f"nested-{test_run_uid}-{name}-receipt.json"
                )
                try:
                    items, output = _run_nested_collection(
                        project_root, receipt_path, *paths
                    )
                except RuntimeError as exc:
                    failure_payload = {"error": str(exc)}
                    temporary_path = failure_marker_path.with_name(
                        f"{failure_marker_path.name}.{os.getpid()}.tmp"
                    )
                    temporary_path.write_text(
                        json.dumps(failure_payload), encoding="utf-8"
                    )
                    os.replace(temporary_path, failure_marker_path)
                    raise
                payload = {"items": items, "output": output}
                temporary_path = cache_path.with_name(
                    f"{cache_path.name}.{os.getpid()}.tmp"
                )
                temporary_path.write_text(json.dumps(payload), encoding="utf-8")
                os.replace(temporary_path, cache_path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return tuple(payload["items"]), payload["output"]


@pytest.fixture(scope="session")
def nested_collection_runner():
    return _run_nested_collection


@pytest.fixture(scope="session")
def nested_default_collection(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tuple[str, ...], str]:
    return _cached_nested_collection(tmp_path_factory, "default")


@pytest.fixture(scope="session")
def nested_broad_collection(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[tuple[str, ...], str]:
    return _cached_nested_collection(tmp_path_factory, "broad", ".")


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    root = config.rootpath.resolve()
    declared = list(config.getini("testpaths"))
    declared_paths = [(label, (root / label).resolve()) for label in declared]
    existing = [(label, path) for label, path in declared_paths if path.exists()]

    collected: set[str] = set()
    item_paths = [Path(str(item.path)).resolve() for item in session.items]
    item_paths.extend(getattr(config, "_eval_harness_deselected_paths", ()))
    for item_path in item_paths:
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
    if not config.getoption("--collection-scope-receipt"):
        _refresh_canonical_receipt(payload)

    config._collection_scope_receipt = receipt  # type: ignore[attr-defined]
    config._collection_scope_receipt_path = receipt_path  # type: ignore[attr-defined]
    config._collection_scope_receipt_deselected_count = getattr(
        config, "_eval_harness_deselected_count", 0
    )  # type: ignore[attr-defined]
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
    deselected_count = config._collection_scope_receipt_deselected_count  # type: ignore[attr-defined]
    terminalreporter.write_sep(
        "=",
        "collection scope: "
        f"{receipt['scope']}; declared={receipt['declared_roots']}; "
        f"collected={receipt['collected_roots']}; selected={receipt['collected_count']}; "
        f"eval_harness_deselected={deselected_count}; "
        f"receipt={path}",
    )
