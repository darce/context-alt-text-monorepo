"""Tests for the lane manifest owned-path overlap checker."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_lane_manifest_overlaps.py"


def _write_manifest(
    manifest_dir: Path,
    task_ref: str,
    lanes: list[dict],
    *,
    filename: str | None = None,
) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / (filename or f"{task_ref}.json")
    # The generator emits a dictionary keyed by lane id, not a list of rows.
    lane_map = {
        str(lane["lane_id"]): {
            key: value for key, value in lane.items() if key != "lane_id"
        }
        for lane in lanes
    }
    path.write_text(json.dumps({"task_ref": task_ref, "lanes": lane_map}))
    return path


def _lane(lane_id: str, owned_paths: list[str], **extra: object) -> dict:
    lane = {"lane_id": lane_id, "owned_paths": owned_paths, "status": "active"}
    lane.update(extra)
    if lane.get("status") is None:
        lane.pop("status")
    return lane


def _run(manifest_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest-dir", str(manifest_dir), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_exact_owned_path_match_is_reported(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["scripts/check.py"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["scripts/check.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 1
    assert "task-a/lane-a" in result.stdout
    assert "task-b/lane-b" in result.stdout
    assert "scripts/check.py" in result.stdout


def test_directory_prefix_and_glob_suffix_are_overlaps(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/"])])
    _write_manifest(
        manifest_dir,
        "task-b",
        [_lane("lane-b", ["src/feature.py"]), _lane("lane-c", ["scripts/**"])],
    )
    _write_manifest(manifest_dir, "task-c", [_lane("lane-d", ["scripts/check.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 1
    assert "task-a/lane-a" in result.stdout
    assert "task-b/lane-b" in result.stdout
    assert "task-b/lane-c" in result.stdout
    assert "task-c/lane-d" in result.stdout


def test_single_star_glob_is_a_directory_prefix(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/*"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/foo.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 1
    assert "src <-> src/foo.py" in result.stdout


def test_single_star_glob_does_not_escape_its_directory(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/a/*"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/b.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 0
    assert "No owned-path overlaps" in result.stdout


def test_aliased_paths_are_canonicalized_before_prefix_comparison(
    tmp_path: Path,
) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        "task-a",
        [_lane("lane-a", ["src/../scripts/**"])],
    )
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["scripts/check.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 1
    assert "scripts <-> scripts/check.py" in result.stdout


@pytest.mark.parametrize(
    ("owned_path", "error_fragment"),
    [
        ("/scripts/**", "absolute"),
        ("../scripts/**", "escapes"),
        ("foo/../C:/bar", "absolute"),
    ],
)
def test_absolute_and_escaping_paths_are_rejected(
    tmp_path: Path, owned_path: str, error_fragment: str
) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", [owned_path])])

    result = _run(manifest_dir)

    assert result.returncode == 2
    assert error_fragment in result.stderr.lower()


def test_sibling_files_do_not_overlap(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/a.py"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/b.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 0
    assert "No owned-path overlaps" in result.stdout


def test_closed_and_merged_lanes_are_excluded_by_default(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        "task-a",
        [_lane("lane-a", ["src/shared.py"], status="closed")],
    )
    _write_manifest(
        manifest_dir,
        "task-b",
        [_lane("lane-b", ["src/shared.py"], status="merged")],
    )
    _write_manifest(
        manifest_dir,
        "task-c",
        [_lane("lane-c", ["src/shared.py"], status="open")],
    )

    result = _run(manifest_dir)

    assert result.returncode == 0
    assert "task-a/lane-a" not in result.stdout
    assert "task-b/lane-b" not in result.stdout


def test_include_status_can_reenable_terminal_lanes(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        "task-a",
        [_lane("lane-a", ["src/shared.py"], status="closed")],
    )
    _write_manifest(
        manifest_dir,
        "task-b",
        [_lane("lane-b", ["src/shared.py"], status="closed")],
    )

    result = _run(manifest_dir, "--include-status", "closed")

    assert result.returncode == 1
    assert "task-a/lane-a" in result.stdout
    assert "task-b/lane-b" in result.stdout


def test_lane_status_json_overrides_manifest_status(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        "task-a",
        [_lane("lane-a", ["src/shared.py"], status="open")],
    )
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/shared.py"])])
    status_path = tmp_path / "lane-status.json"
    status_path.write_text(json.dumps({"task-a/lane-a": "closed"}))

    result = _run(manifest_dir, "--lane-status-json", str(status_path))

    assert result.returncode == 0
    assert "task-a/lane-a" not in result.stdout


def test_unstatused_stale_lanes_are_excluded_by_default(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        "task-active",
        [_lane("lane-a", ["src/shared.py"])],
    )
    _write_manifest(
        manifest_dir,
        "task-stale",
        [_lane("lane-stale", ["src/shared.py"], status=None)],
    )

    result = _run(manifest_dir)

    assert result.returncode == 0
    assert "1 live lanes" in result.stdout
    assert "task-stale/lane-stale" not in result.stdout


def test_status_json_excludes_manifest_lanes_missing_from_live_export(
    tmp_path: Path,
) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(
        manifest_dir,
        "task-active",
        [_lane("lane-a", ["src/shared.py"], status=None)],
    )
    _write_manifest(
        manifest_dir,
        "task-stale",
        [_lane("lane-stale", ["src/shared.py"], status=None)],
    )
    status_path = tmp_path / "lane-status.json"
    status_path.write_text(json.dumps({"task-active/lane-a": "active"}))

    result = _run(manifest_dir, "--lane-status-json", str(status_path))

    assert result.returncode == 0
    assert "1 live lanes" in result.stdout


@pytest.mark.parametrize(
    "payload",
    [{"unexpected": []}, {"data": {"unexpected": []}}],
)
def test_unrecognized_nonempty_status_json_is_rejected(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/shared.py"])])
    status_path = tmp_path / "lane-status.json"
    status_path.write_text(json.dumps(payload))

    result = _run(manifest_dir, "--lane-status-json", str(status_path))

    assert result.returncode == 2
    assert "recognized" in result.stderr.lower()


def test_allow_list_records_reason_and_clears_failure(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/shared.py"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/shared.py"])])

    result = _run(
        manifest_dir,
        "--allow",
        "task-a/lane-a:task-b/lane-b=shared contract",
    )

    assert result.returncode == 0
    assert "ALLOW" in result.stdout
    assert "shared contract" in result.stdout


def test_empty_manifest_directory_is_a_successful_notice(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "empty"

    result = _run(manifest_dir)

    assert result.returncode == 0
    assert "No lane manifests found" in result.stdout


def test_existing_non_directory_manifest_path_is_rejected(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")

    result = _run(manifest_path)

    assert result.returncode == 2
    assert "directory" in result.stderr.lower()


def test_json_output_has_machine_readable_overlap_shape(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/b.py"])])

    result = _run(manifest_dir, "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["overlap_count"] == 1
    overlap = payload["overlaps"][0]
    assert overlap["lanes"] == ["task-a/lane-a", "task-b/lane-b"]
    assert overlap["allowed"] is False
    assert overlap["paths"] == [{"left": "src", "right": "src/b.py"}]


def test_review_lanes_with_no_owned_paths_never_overlap(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("review", [])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/review.py"])])

    result = _run(manifest_dir)

    assert result.returncode == 0


def test_make_include_declares_target_and_check_all_dependency() -> None:
    makefile = (REPO_ROOT / "mk" / "lane-overlaps.mk").read_text()

    assert "lane-overlaps-check:" in makefile
    assert "check-all: lane-overlaps-check" in makefile
    assert "lane-overlaps-tests:" in makefile
    assert "test-scripts: lane-overlaps-tests" in makefile
    assert "scripts/test_check_lane_manifest_overlaps.py" in makefile


def test_make_manifest_probe_is_portable() -> None:
    makefile = (REPO_ROOT / "mk" / "lane-overlaps.mk").read_text()

    assert "find " not in makefile
    assert "-maxdepth" not in makefile


def test_make_status_export_fetches_all_pages(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    _write_manifest(manifest_dir, "task-a", [_lane("lane-a", ["src/shared.py"])])
    _write_manifest(manifest_dir, "task-b", [_lane("lane-b", ["src/shared.py"])])

    fake_mcp = tmp_path / "fake-mcp"
    fake_mcp.write_text(
        "#!/bin/sh\n"
        "offset=0\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    --offset) offset=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "if [ \"$offset\" -eq 0 ]; then\n"
        "  printf '%s\\n' '{\"ok\":true,\"total_matching\":2,\"returned\":1,\"has_more\":true,\"lanes\":[{\"task_ref\":\"task-a\",\"lane_id\":\"lane-a\",\"status\":\"active\"}]}'\n"
        "else\n"
        "  printf '%s\\n' '{\"ok\":true,\"total_matching\":2,\"returned\":1,\"has_more\":false,\"lanes\":[{\"task_ref\":\"task-b\",\"lane_id\":\"lane-b\",\"status\":\"active\"}]}'\n"
        "fi\n"
    )
    fake_mcp.chmod(0o755)

    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-f",
            str(REPO_ROOT / "mk" / "lane-overlaps.mk"),
            "lane-overlaps-check",
            f"LANE_OVERLAPS_MANIFEST_DIR={manifest_dir}",
            f"MCP_CMD={fake_mcp}",
            "MCP_STATE_ARGS=",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    # GNU Make maps a failing recipe's status to its conventional exit 2.
    assert result.returncode == 2
    assert "task-a/lane-a" in result.stdout
    assert "task-b/lane-b" in result.stdout
