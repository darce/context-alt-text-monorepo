"""RED CLI contract tests for the lane manifest rules checker."""

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/check_lane_manifest_rules.py"


def _run(*args, cwd):
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )


def _clean_lane():
    return {
        "owned_paths": ["scripts/a.py"],
        "test_commands": ["python -m pytest scripts/test_a.py -q"],
        "preferred_backend": "codex-remote",
        "preferred_model": "gpt-6.1-sol",
        "preferred_reasoning_effort": "high",
        "preferred_speed": "fast",
        "objective": "Add a.",
    }


def _write(directory, name, lanes):
    path = directory / f"{name}.json"
    path.write_text(json.dumps({"task_ref": name, "lanes": lanes}), encoding="utf-8")
    return path


@pytest.fixture
def manifest_dir(tmp_path):
    directory = tmp_path / "manifests"
    directory.mkdir()
    return directory


def test_manifest_malformed(manifest_dir, tmp_path):
    (manifest_dir / "BAD.json").write_text("{not json", encoding="utf-8")

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR BAD.json -: manifest-malformed:" in result.stdout


def test_test_commands_empty(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["test_commands"] = []
    _write(manifest_dir, "EMPTY", {"worker": lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR EMPTY.json worker: test-commands-empty:" in result.stdout


def test_description_service_env(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["owned_paths"] = ["apps/prototype-description-service/scene/a.py"]
    _write(manifest_dir, "ENV", {"worker": lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR ENV.json worker: description-service-env:" in result.stdout


def test_route_pin_null(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["preferred_model"] = None
    _write(manifest_dir, "PIN", {"worker": lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR PIN.json worker: route-pin-null:" in result.stdout


def test_brief_forbids_commit(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["objective"] = "Add a. Do not commit the result."
    _write(manifest_dir, "BRIEF", {"worker": lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR BRIEF.json worker: brief-forbids-commit:" in result.stdout


def test_route_pin_null_speed_only(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["preferred_speed"] = None
    _write(manifest_dir, "SPEED", {"worker": lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "ERROR SPEED.json worker: route-pin-null:" in result.stdout


def test_owned_paths_wide_warning(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["owned_paths"] = ["scripts/a.py", "scripts/b.py", "scripts/c.py", "scripts/d.py"]
    _write(manifest_dir, "WIDE", {"worker": lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARNING WIDE.json worker: owned-paths-wide:" in result.stdout
    assert result.stdout.splitlines()[-1] == "lane manifest rules: 0 error(s), 1 warning(s) in 1 manifest(s)"


def test_clean_manifest(manifest_dir, tmp_path):
    _write(manifest_dir, "CLEAN", {"worker": _clean_lane()})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "lane manifest rules: 0 error(s), 0 warning(s) in 1 manifest(s)\n"


def test_golden_manifest_skipped(manifest_dir, tmp_path):
    lane = _clean_lane()
    lane["test_commands"] = []
    _write(manifest_dir, "X.golden", {"worker": lane})
    _write(manifest_dir, "CLEAN", {"worker": _clean_lane()})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "lane manifest rules: 0 error(s), 0 warning(s) in 1 manifest(s)\n"


def test_terminal_lanes_skipped(manifest_dir, tmp_path):
    terminal_lane = _clean_lane()
    terminal_lane["test_commands"] = []
    terminal_lane["terminal"] = {"status": "merged", "at": "2026-10-29T00:00:00Z"}
    closed_lane = _clean_lane()
    closed_lane["test_commands"] = []
    closed_lane["status"] = "closed"
    _write(manifest_dir, "TERMINAL", {"terminal": terminal_lane, "closed": closed_lane})

    result = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "lane manifest rules: 0 error(s), 0 warning(s) in 1 manifest(s)\n"


def test_task_ref_scoping(manifest_dir, tmp_path):
    _write(manifest_dir, "A", {"worker": _clean_lane()})
    lane = _clean_lane()
    lane["test_commands"] = []
    _write(manifest_dir, "B", {"worker": lane})

    scoped = _run("--manifest-dir", str(manifest_dir), "--task-ref", "A", cwd=tmp_path)

    assert scoped.returncode == 0, scoped.stdout + scoped.stderr
    assert scoped.stdout == "lane manifest rules: 0 error(s), 0 warning(s) in 1 manifest(s)\n"

    unscoped = _run("--manifest-dir", str(manifest_dir), cwd=tmp_path)

    assert unscoped.returncode == 1, unscoped.stdout + unscoped.stderr
    assert "ERROR B.json worker: test-commands-empty:" in unscoped.stdout
    assert unscoped.stdout.splitlines()[-1] == "lane manifest rules: 1 error(s), 0 warning(s) in 2 manifest(s)"

    missing = _run("--manifest-dir", str(manifest_dir), "--task-ref", "MISSING", cwd=tmp_path)

    assert missing.returncode == 2, missing.stdout + missing.stderr
