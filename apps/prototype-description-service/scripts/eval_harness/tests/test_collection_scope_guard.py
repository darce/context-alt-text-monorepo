"""Executable coverage for the pytest collection-scope guard."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys


SERVICE_ROOT = Path(__file__).resolve().parents[3]


def _write_project(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "tests_a").mkdir()
    (tmp_path / "tests_b").mkdir()
    (tmp_path / "tests_a" / "test_a.py").write_text("def test_a(): assert True\n")
    (tmp_path / "tests_b" / "test_b.py").write_text("def test_b(): assert True\n")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests_a", "tests_b"]\n'
    )
    return config, tmp_path / "receipt.json"


def _run(
    tmp_path: Path, *selection: str, require_full: bool = True, strict_env: bool = False
) -> tuple[subprocess.CompletedProcess[str], dict]:
    config, receipt = _write_project(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVICE_ROOT)
    # strict_env alone decides the child's gate state. Without the pop, an
    # ambient ACX_STRICT_GATE=1 -- which the remote-gate runbook tells
    # operators to set -- reaches the child and fails every case here that
    # expects narrowing to be allowed.
    env.pop("ACX_STRICT_GATE", None)
    if strict_env:
        env["ACX_STRICT_GATE"] = "1"
    args = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "conftest",
        "-c",
        str(config),
        f"--collection-scope-receipt={receipt}",
        *selection,
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    if require_full:
        args.insert(7, "--require-full-collection")
    result = subprocess.run(
        args,
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(receipt.read_text())


def test_narrowed_collection_without_flag_is_allowed_and_receipted(
    tmp_path: Path,
) -> None:
    result, receipt = _run(tmp_path, "tests_a", require_full=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert receipt["scope"] == "narrowed"
    assert receipt["collected_roots"] == ["tests_a"]


def test_narrowed_collection_is_rejected_and_receipted(tmp_path: Path) -> None:
    result, receipt = _run(tmp_path, "tests_a")

    assert result.returncode != 0
    assert "full collection required; collection was narrowed" in result.stderr
    assert set(receipt) == {
        "pid",
        "rootdir",
        "started_at",
        "declared_roots",
        "collected_roots",
        "collected_count",
        "scope",
    }
    assert receipt["declared_roots"] == ["tests_a", "tests_b"]
    assert receipt["collected_roots"] == ["tests_a"]
    assert receipt["collected_count"] == 1
    assert receipt["scope"] == "narrowed"
    assert isinstance(receipt["pid"], int)
    assert receipt["pid"] > 0
    assert receipt["rootdir"] == str(tmp_path.resolve())
    assert isinstance(receipt["started_at"], str)
    started_at = datetime.fromisoformat(receipt["started_at"])
    assert started_at.tzinfo is not None
    assert started_at.utcoffset() is not None


def test_full_collection_is_accepted_and_receipted(tmp_path: Path) -> None:
    result, receipt = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert set(receipt) == {
        "pid",
        "rootdir",
        "started_at",
        "declared_roots",
        "collected_roots",
        "collected_count",
        "scope",
    }
    assert receipt["declared_roots"] == ["tests_a", "tests_b"]
    assert receipt["collected_roots"] == ["tests_a", "tests_b"]
    assert receipt["collected_count"] == 2
    assert receipt["scope"] == "full"
    assert isinstance(receipt["pid"], int)
    assert receipt["pid"] > 0
    assert receipt["rootdir"] == str(tmp_path.resolve())
    assert isinstance(receipt["started_at"], str)
    started_at = datetime.fromisoformat(receipt["started_at"])
    assert started_at.tzinfo is not None
    assert started_at.utcoffset() is not None


def test_strict_gate_rejects_narrowed_collection_without_cli_flag(tmp_path: Path) -> None:
    """FIR-12-BR-80: the environment gate must make narrowing fail closed."""
    result, receipt = _run(tmp_path, "tests_a", require_full=False, strict_env=True)

    assert result.returncode != 0
    assert "full collection required; collection was narrowed" in result.stderr
    assert receipt["scope"] == "narrowed"
