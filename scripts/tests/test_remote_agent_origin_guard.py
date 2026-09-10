from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/remote_agent.sh"
PACKAGE_NAME = "workbay_demo"


def _origin_guard_block() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start_marker = "_ORIGIN_GUARD_STATUS=''\n"
    end_marker = "if ! _assert_lane_venv_origin; then"
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end].replace("\\$", "$")


def _phase_attestation_block() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start_marker = 'case "\\$_ORIGIN_GUARD_STATUS" in\n'
    end_marker = "# agent_launch opens at end of last pre-agent phase that ran"
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end].replace("\\$", "$")


@pytest.fixture()
def lane_venv(tmp_path: Path) -> Path:
    venv = tmp_path / "lane-venv"
    completed = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return venv


def _site_packages(venv: Path) -> Path:
    site_dirs = sorted((venv / "lib").glob("python*/site-packages"))
    assert len(site_dirs) == 1
    return site_dirs[0]


def _run_probe(venv: Path, packages: Path) -> subprocess.CompletedProcess[str]:
    command = (
        "set -euo pipefail\n"
        f"{_origin_guard_block()}\n"
        "_assert_lane_venv_origin\n"
        "printf '%s\\n' \"$_ORIGIN_GUARD_STATUS\"\n"
    )
    return subprocess.run(
        ["bash", "-c", command],
        env={**os.environ, "LANE_VENV": str(venv), "SBX": str(packages.parent)},
        capture_output=True,
        text=True,
        check=False,
    )


def _source_package(packages: Path, *, body: str = "") -> Path:
    package = packages / "workbay-system" / "src" / PACKAGE_NAME
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(body, encoding="utf-8")
    return package


def _redirect_package(venv: Path, package: Path) -> None:
    (_site_packages(venv) / PACKAGE_NAME).symlink_to(package, target_is_directory=True)


def test_empty_consumer_skips_origin_guard(lane_venv: Path, tmp_path: Path) -> None:
    completed = _run_probe(lane_venv, tmp_path / "packages")

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "skipped_no_guarded_roots"
    assert "venv_origin_guard skipped" in completed.stderr
    assert "venv_origin_shadow no guarded packages discovered" not in completed.stderr


def test_guarded_package_from_lane_root_is_verified(lane_venv: Path, tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    package = _source_package(packages)
    _redirect_package(lane_venv, package)

    completed = _run_probe(lane_venv, packages)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "verified_roots"


def test_guarded_package_shadow_fails_closed(lane_venv: Path, tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    _source_package(packages)
    shadow = _site_packages(lane_venv) / PACKAGE_NAME
    shadow.mkdir()
    (shadow / "__init__.py").write_text("# stale copy\n", encoding="utf-8")

    completed = _run_probe(lane_venv, packages)

    assert completed.returncode == 1
    assert f"venv_origin_shadow {PACKAGE_NAME}" in completed.stderr
    assert str((shadow / "__init__.py").resolve()) in completed.stderr


def test_guarded_package_import_failure_fails_closed(lane_venv: Path, tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    package = _source_package(packages, body="raise RuntimeError('broken package')\n")
    _redirect_package(lane_venv, package)

    completed = _run_probe(lane_venv, packages)

    assert completed.returncode == 1
    assert f"venv_origin_shadow {PACKAGE_NAME} import_error:RuntimeError" in completed.stderr


def test_pytest_path_guard_violation_fails_closed(lane_venv: Path, tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    package = _source_package(packages)
    _redirect_package(lane_venv, package)
    guard = packages / "workbay-system" / "scripts" / "pytest_path_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text(
        "def collect_violations(expected):\n    return [('path_guard_violation', expected / 'outside.py', expected)]\n",
        encoding="utf-8",
    )

    completed = _run_probe(lane_venv, packages)

    assert completed.returncode == 1
    assert "venv_origin_shadow path_guard_violation" in completed.stderr


def test_empty_consumer_still_fails_on_path_guard_violation(lane_venv: Path, tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    guard = packages / "workbay-system" / "scripts" / "pytest_path_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text(
        "def collect_violations(expected):\n    return [('path_guard_violation', expected / 'outside.py', expected)]\n",
        encoding="utf-8",
    )

    completed = _run_probe(lane_venv, packages)

    assert completed.returncode == 1
    assert "venv_origin_shadow path_guard_violation" in completed.stderr


@pytest.mark.parametrize(
    ("status", "origin_ok", "origin_guard"),
    [
        ("verified_roots", 1, "verified_roots"),
        ("skipped_no_guarded_roots", None, "skipped_no_guarded_roots"),
    ],
)
def test_phase_attestation_distinguishes_skipped_origin_guard(
    status: str, origin_ok: int | None, origin_guard: str
) -> None:
    command = (
        "set -euo pipefail\n"
        f'_ORIGIN_GUARD_STATUS="{status}"\n'
        '_PHASES_JSON_PARTS=\'"sync":{"start_ts":1}\'\n'
        f"{_phase_attestation_block()}\n"
        "printf '{%s}\\n' \"$_PHASES_JSON_PARTS\"\n"
    )
    completed = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    sync = json.loads(completed.stdout)["sync"]
    assert sync["origin_ok"] == origin_ok
    assert sync["origin_guard"] == origin_guard


