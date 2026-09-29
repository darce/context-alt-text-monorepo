"""Regression guard for GPUUX1-CD-02.

The scene startup tests used to pass only in the root worktree, which carries an
untracked `.env` supplying `PGPASSWORD`. In every linked lane worktree they
failed with `InsecureProductionConfigError`, so each offload lane inherited four
unconditional failures it could not distinguish from a real regression.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]

_STARTUP_TESTS = [
    "scene/tests/test_describe_route.py::test_create_app_registers_route_and_upload_cap",
    "scene/tests/test_describe_run_reclaim.py::test_startup_reclaim_failure_does_not_block_boot_and_is_wired",
    "scene/tests/test_describe_run_reclaim.py::test_startup_boot_order_reclaim_then_purge_then_snapshot",
    "scene/tests/test_describe_run_reclaim.py::test_startup_purge_or_snapshot_failure_does_not_block_boot",
]

_STARTUP_TEST_PLUGIN = """import pytest
import asyncio


# The startup tests exercise the lifespan; route mounting and refresh IO are separate work.
@pytest.fixture(autouse=True)
def skip_unrelated_router_registration(monkeypatch, request):
    if not (
        request.node.name.startswith("test_startup_")
        or request.node.name == "test_create_app_registers_route_and_upload_cap"
    ):
        return

    from fastapi import FastAPI

    include_router = FastAPI.include_router
    if request.node.name.startswith("test_startup_"):
        monkeypatch.setattr(FastAPI, "include_router", lambda self, router, *args, **kwargs: None)
    else:
        from scene.interface_adapters.http.router import router as scene_router

        def include_scene_router(self, router, *args, **kwargs):
            if router is scene_router:
                return include_router(self, router, *args, **kwargs)

        monkeypatch.setattr(FastAPI, "include_router", include_scene_router)

    import api.main as api_main

    async def idle_snapshot_refresher(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(api_main, "_supervise_load_snapshot_refresher", idle_snapshot_refresher)
"""


def test_startup_tests_pass_without_any_ambient_credentials(tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("RECOGNITION_", "PG", "ACX_"))}
    env["PATH"] = os.environ.get("PATH", "")
    env["ACX_GPU_SHELL_SUITE_SKIP"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), env.get("PYTHONPATH", "")))
    (tmp_path / "startup_test_plugin.py").write_text(_STARTUP_TEST_PLUGIN, encoding="utf-8")

    # The collection-scope receipt defaults to a fixed global path, so this
    # child would overwrite the outer run's receipt with its narrowed test scope
    # mid-run -- leaving any operator who reads it afterwards with a receipt
    # that understates what actually ran.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "startup_test_plugin",
            "-o",
            "timeout=60",
            "-o",
            "timeout_method=thread",
            f"--collection-scope-receipt={tmp_path / 'collection-scope.json'}",
            *_STARTUP_TESTS,
        ],
        cwd=SERVICE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )

    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
