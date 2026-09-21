"""Tests for the collection-scope receipt's identity and path resolution."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[3]
RECEIPT_PATTERN = re.compile(r"receipt=(\S+)")


def _run_pytest_child(
    tmp_path: Path,
    *selection: str,
    ini_receipt: str | None = None,
    cli_receipt: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, dict[str, object]]:
    project = tmp_path / "project"
    tests = project / "tests"
    tests.mkdir(parents=True)
    (tests / "test_child.py").write_text(
        "def test_child() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    config = project / "pytest.ini"
    ini_lines = ["[pytest]", "testpaths = tests"]
    if ini_receipt is not None:
        ini_lines.append(f"collection_scope_receipt = {ini_receipt}")
    config.write_text("\n".join(ini_lines) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(SERVICE_ROOT), env.get("PYTHONPATH")) if part
    )
    args = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "conftest",
        "-c",
        str(config),
        *selection,
    ]
    if cli_receipt is not None:
        args.append(f"--collection-scope-receipt={cli_receipt}")
    args.extend(["-q", "-p", "no:cacheprovider"])
    result = subprocess.run(
        args,
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = result.stdout + result.stderr
    match = RECEIPT_PATTERN.search(output)
    assert match is not None, output
    receipt_path = Path(match.group(1))
    return result, receipt_path, json.loads(receipt_path.read_text(encoding="utf-8"))


def test_default_receipt_is_run_unique_and_self_identifying(tmp_path: Path) -> None:
    first, first_path, first_receipt = _run_pytest_child(tmp_path / "first")
    second, second_path, second_receipt = _run_pytest_child(tmp_path / "second")

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert first_path.is_absolute()
    assert second_path.is_absolute()
    assert first_path != second_path
    assert first_receipt["pid"] > 0
    assert str(first_receipt["pid"]) in first_path.name
    assert str(second_receipt["pid"]) in second_path.name
    assert first_receipt["rootdir"] == str((tmp_path / "first" / "project").resolve())
    assert first_receipt["declared_roots"] == ["tests"]
    assert first_receipt["collected_roots"] == ["tests"]
    assert first_receipt["collected_count"] == 1
    assert first_receipt["scope"] == "full"
    assert isinstance(first_receipt["started_at"], str)
    assert first_receipt["started_at"]
    assert str(first_path) in first.stdout


@pytest.mark.parametrize("override_kind", ["cli", "ini"])
def test_receipt_overrides_remain_supported(
    tmp_path: Path, override_kind: str
) -> None:
    expected = tmp_path / "custom" / f"{override_kind}.json"
    if override_kind == "cli":
        result, receipt_path, _ = _run_pytest_child(
            tmp_path / "cli", cli_receipt=expected
        )
    else:
        result, receipt_path, _ = _run_pytest_child(
            tmp_path / "ini",
            ini_receipt=str(expected),
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert receipt_path == expected.resolve()
    assert receipt_path.exists()
