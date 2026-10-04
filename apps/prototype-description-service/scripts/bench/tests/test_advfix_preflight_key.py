"""Regression tests for configured API-key enforcement during preflight."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.bench.preflight import PreflightError, preflight_pair
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import write_pair


def test_preflight_missing_api_key_fails_before_health_and_writes_no_evidence(
    tmp_path: Path,
) -> None:
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        expected_dim, expected_profile = (
            (512, "insightface")
            if request.url.host == "dev.api.altcontext.com"
            else (128, "face_pipeline")
        )
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "checks": [
                        {
                            "name": "database",
                            "status": "ok",
                            "detail": f"reachable; pgvector_dimension={expected_dim}",
                        }
                    ],
                },
            )

        fingerprint = {
            "opencv_version": "5.0.0.93",
            "opencv_major": 5,
            "onnxruntime_version": "1.28.0",
            "numpy_version": "2.5.1",
            "scipy_version": "1.18.0",
            "pillow_version": "12.3.0",
            "hdbscan_version": "0.8.44",
            "pgvector_version": "0.5.0",
            "comparison_token": "0" * 64,
        }
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "model_cache": {
                    "model_name": "buffalo_l",
                    "bundle_files": 2,
                    "bundle_sha256": "a" * 64,
                    "profile": expected_profile,
                    "detail": "cached; numeric_runtime_fingerprint="
                    + json.dumps(fingerprint, sort_keys=True, separators=(",", ":")),
                },
            },
        )

    transports = {
        endpoint.stack_id: httpx.MockTransport(handler)
        for endpoint in pair.stacks
    }
    out_dir = tmp_path / "preflight-out"

    with pytest.raises(PreflightError) as exc:
        preflight_pair(pair, out_dir=out_dir, transports=transports, api_keys={})

    assert exc.value.code == "preflight_auth_failed"
    assert "/health/detailed" not in requested_paths
    assert not list(out_dir.rglob("preflight.json"))
