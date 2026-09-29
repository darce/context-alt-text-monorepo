"""Regression coverage for lane maintenance and route-manifest freshness."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_FIXTURE_PATH = _REPOSITORY_ROOT / "apps/prototype-wp-alt-context/tests/fixtures/api-route-manifest.json"
_REAPER_PATH = _REPOSITORY_ROOT / "scripts/worktree_reap.py"


def _load_reaper() -> Any:
    spec = importlib.util.spec_from_file_location("dw2_worktree_reap", _REAPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reaper_accepts_the_pinned_registry_list_lanes_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reaper = _load_reaper()
    worktree = tmp_path / "active-worktree"
    seen_limits: list[int] = []

    class RuntimeConfig:
        @classmethod
        def for_repo(cls, repo: Path) -> Path:
            return repo

    def list_lanes(*, limit: int) -> dict[str, object]:
        seen_limits.append(limit)
        return {
            "ok": True,
            "data": {
                "lanes": [
                    {"lane_id": "active", "status": "blocked", "worktree_path": str(worktree)}
                ],
                "has_more": False,
            },
        }

    backend = types.ModuleType("workbay_handoff_mcp")
    backend.RuntimeConfig = RuntimeConfig  # type: ignore[attr-defined]
    backend.configure_runtime = lambda _config: None  # type: ignore[attr-defined]
    recording = types.ModuleType("workbay_handoff_mcp.lanes_recording")
    recording.list_lanes = list_lanes  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "workbay_handoff_mcp", backend)
    monkeypatch.setitem(sys.modules, "workbay_handoff_mcp.lanes_recording", recording)

    assert reaper.active_lane_paths(tmp_path) == {worktree.resolve(): "active"}
    assert seen_limits == [reaper._LANE_PAGE_LIMIT]


def test_reaper_python_defaults_to_the_repository_virtualenv() -> None:
    makefile = (_REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "PYTHON ?= $(ORCHESTRATOR_ROOT)/.venv/bin/python" in makefile


def test_route_manifest_check_rejects_a_stale_copy_without_mutating_it(tmp_path: Path) -> None:
    stale_fixture = tmp_path / "api-route-manifest.json"
    stale_contents = _FIXTURE_PATH.read_bytes() + b"\n"
    stale_fixture.write_bytes(stale_contents)

    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "check-route-manifest",
            f"ROUTE_MANIFEST_FIXTURE={stale_fixture}",
        ],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "route manifest is stale" in result.stderr
    assert stale_fixture.read_bytes() == stale_contents
