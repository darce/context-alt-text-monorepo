from __future__ import annotations

import fcntl
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

service_conftest_spec = importlib.util.spec_from_file_location(
    "acx_service_root_conftest", Path(__file__).resolve().parents[3] / "conftest.py"
)
if service_conftest_spec is None or service_conftest_spec.loader is None:
    raise ImportError("Could not load the service-root conftest")
service_conftest = importlib.util.module_from_spec(service_conftest_spec)
service_conftest_spec.loader.exec_module(service_conftest)


def test_nested_collection_timeout_reports_paths_and_partial_output(
    tmp_path: Path, monkeypatch
) -> None:
    def timeout_run(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            kwargs.get("timeout", 240),
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(service_conftest.subprocess, "run", timeout_run)

    with pytest.raises(RuntimeError) as error:
        service_conftest._run_nested_collection(
            tmp_path, tmp_path / "receipt.json", "tests/test_blocked_import.py"
        )

    message = str(error.value)
    assert "240" in message
    assert "tests/test_blocked_import.py" in message
    assert "partial stdout" in message
    assert "partial stderr" in message


def test_nested_collection_subprocess_receives_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    received: dict[str, object] = {}

    def successful_run(command, **kwargs):
        received.update(kwargs)
        return subprocess.CompletedProcess(
            command, 0, stdout="tests/test_example.py::test_example\n", stderr=""
        )

    monkeypatch.setattr(
        service_conftest,
        "_NESTED_COLLECTION_TIMEOUT_SECONDS",
        37,
        raising=False,
    )
    monkeypatch.setattr(service_conftest.subprocess, "run", successful_run)

    service_conftest._run_nested_collection(
        tmp_path, tmp_path / "receipt.json", "tests/test_example.py"
    )

    assert received.get("timeout") == getattr(
        service_conftest, "_NESTED_COLLECTION_TIMEOUT_SECONDS", 240
    )


def test_xdist_timeout_is_cached_as_failure_and_released_lock(
    tmp_path: Path, monkeypatch
) -> None:
    class TempPathFactoryShim:
        def getbasetemp(self) -> Path:
            return base_temp

    base_temp = tmp_path / "base"
    base_temp.mkdir()
    tmp_path_factory = TempPathFactoryShim()
    test_run_uid = "nested-collection-timeout-test-run"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("PYTEST_XDIST_TESTRUNUID", test_run_uid)
    calls = 0

    def timeout_run(command, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(
            command,
            kwargs.get("timeout", 240),
            output=b"blocked collection",
        )

    monkeypatch.setattr(service_conftest.subprocess, "run", timeout_run)
    cache_path = tmp_path / f"nested-{test_run_uid}-blocked-collection.json"
    failure_path = cache_path.with_name(f"{cache_path.name}.failed")
    lock_path = cache_path.with_suffix(".lock")

    with pytest.raises(RuntimeError) as first_error:
        service_conftest._cached_nested_collection(
            tmp_path_factory, "blocked", "tests/test_blocked_import.py"
        )

    assert not cache_path.exists()
    assert failure_path.exists()
    failure_payload = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure_payload == {"error": str(first_error.value)}

    with pytest.raises(RuntimeError) as second_error:
        service_conftest._cached_nested_collection(
            tmp_path_factory, "blocked", "tests/test_blocked_import.py"
        )

    assert str(second_error.value) == str(first_error.value)
    assert calls == 1
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
