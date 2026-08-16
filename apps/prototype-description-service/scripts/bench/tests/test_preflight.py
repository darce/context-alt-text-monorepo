"""Preflight fail-closed on real /ready + /health/detailed payload shapes."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import httpx
import pytest

from scripts.bench.preflight import (
    PreflightError,
    preflight_stack,
    write_preflight_json,
)
from scripts.bench.stack_pair import StackEndpoint, load_stack_pair
from scripts.bench.tests.conftest import FIR_STACK, INSIGHTFACE_STACK, write_pair


def _insightface_endpoint(**overrides: object) -> StackEndpoint:
    payload = {**INSIGHTFACE_STACK, **overrides}
    return StackEndpoint(
        stack_id=payload["stack_id"],
        role=payload["role"],
        base_url=payload["base_url"],
        expected_profile=payload["expected_profile"],
        expected_pgvector_dim=payload["expected_pgvector_dim"],
        opencv_major=payload.get("opencv_major"),
        api_key_env=payload["api_key_env"],
        tenant_id_env=payload["tenant_id_env"],
    )


def _ready(dim: int, *, status: str = "ok") -> dict:
    return {
        "status": "ok",
        "timestamp": "2026-07-29T00:00:00Z",
        "checks": [
            {
                "name": "database",
                "status": status,
                "detail": f"reachable; pgvector_dimension={dim}",
            }
        ],
    }


def _health(profile: str) -> dict:
    return {
        "status": "ok",
        "timestamp": "2026-07-29T00:00:00Z",
        "model_cache": {
            "model_name": "buffalo_l",
            "cache_dir": "/models",
            "bundle_files": 2,
            "status": "ok",
            "detail": "cached",
            "profile": profile,
        },
    }


def _transport(ready: dict | int, health: dict | int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ready":
            if isinstance(ready, int):
                return httpx.Response(ready, json={"detail": "missing"})
            return httpx.Response(200, json=ready)
        if request.url.path == "/health/detailed":
            if isinstance(health, int):
                return httpx.Response(health, json={"detail": "auth"})
            return httpx.Response(200, json=health)
        return httpx.Response(404, json={"detail": "no"})

    return httpx.MockTransport(handler)


def test_preflight_ok_real_shapes() -> None:
    result = preflight_stack(
        _insightface_endpoint(),
        transport=_transport(_ready(512), _health("insightface")),
        api_key="k",
    )
    assert result.resolved_profile == "insightface"
    assert result.resolved_pgvector_dim == 512
    assert result.opencv_major == 5
    assert result.opencv_major_source == "operator_attested"


def test_dim_drift_on_insightface_raises_profile_or_dim_drift() -> None:
    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=_transport(_ready(128), _health("insightface")),
            api_key="k",
        )
    assert exc.value.code == "profile_or_dim_drift"


def test_missing_pgvector_token_is_drift() -> None:
    ready = _ready(512)
    ready["checks"][0]["detail"] = "reachable; database ok"
    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=_transport(ready, _health("insightface")),
            api_key="k",
        )
    assert exc.value.code == "profile_or_dim_drift"


def test_missing_model_cache_profile_is_drift() -> None:
    health = _health("insightface")
    del health["model_cache"]["profile"]
    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=_transport(_ready(512), health),
            api_key="k",
        )
    assert exc.value.code == "profile_or_dim_drift"


def test_auth_401_is_preflight_auth_failed() -> None:
    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=_transport(_ready(512), 401),
            api_key="bad",
        )
    assert exc.value.code == "preflight_auth_failed"


def test_health_404_is_preflight_endpoint_missing() -> None:
    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=_transport(_ready(512), 404),
            api_key="k",
        )
    assert exc.value.code == "preflight_endpoint_missing"


def test_fir_leg_expects_128_face_pipeline() -> None:
    endpoint = StackEndpoint(
        stack_id=FIR_STACK["stack_id"],
        role=FIR_STACK["role"],
        base_url=FIR_STACK["base_url"],
        expected_profile="face_pipeline",
        expected_pgvector_dim=128,
        opencv_major=5,
        api_key_env=FIR_STACK["api_key_env"],
        tenant_id_env=FIR_STACK["tenant_id_env"],
    )
    result = preflight_stack(
        endpoint,
        transport=_transport(_ready(128), _health("face_pipeline")),
        api_key="k",
    )
    assert result.resolved_pgvector_dim == 128
    assert result.resolved_profile == "face_pipeline"


def test_write_preflight_json_round_trips_prov01_keys(tmp_path: Path) -> None:
    from dataclasses import fields

    from scripts.bench.preflight import PreflightResult
    from scripts.bench.score_report import PROV01_PREFLIGHT_KEYS, _require_prov01_preflights

    assert tuple(f.name for f in fields(PreflightResult)) == PROV01_PREFLIGHT_KEYS
    result = preflight_stack(
        _insightface_endpoint(),
        transport=_transport(_ready(512), _health("insightface")),
        api_key="k",
    )
    dest = tmp_path / "legs" / result.stack_id / "preflight.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_preflight_json(dest, result)
    assert _require_prov01_preflights(tmp_path, [result.stack_id]) is True


def test_missing_opencv_major_raises_and_writes_no_preflight_json(tmp_path: Path) -> None:
    dest = tmp_path / "preflight.json"
    endpoint = _insightface_endpoint()
    object.__setattr__(endpoint, "opencv_major", None)
    with pytest.raises(PreflightError) as exc:
        result = preflight_stack(
            endpoint,
            transport=_transport(_ready(512), _health("insightface")),
            api_key="k",
        )
        write_preflight_json(dest, result)
    assert exc.value.code == "opencv_major_unattested"
    assert not dest.exists()


def test_load_missing_opencv_major_is_unattested(tmp_path: Path) -> None:
    pair = {
        "head_to_head_delta": 0.10,
        "bootstrap_seed": 20260729,
        "primary_endpoint": "detection_recall@frame_e2e/label_map_primary",
        "secondary_endpoints": [],
        "stacks": [
            {k: v for k, v in INSIGHTFACE_STACK.items() if k != "opencv_major"},
            dict(FIR_STACK),
        ],
    }
    path = write_pair(tmp_path / "pair.yaml", pair)
    with pytest.raises(Exception) as exc:
        load_stack_pair(path)
    assert getattr(exc.value, "code", "") == "opencv_major_unattested"


def test_run_pair_defaults_to_fail_closed_preflight(tmp_path: Path) -> None:
    from scripts.bench.driver import run_pair
    from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    with pytest.raises(PreflightError) as exc:
        run_pair(
            pair,
            manifest_path=manifest,
            images_dir=images,
            out_dir=tmp_path / "out-default",
            clients={
                "acx-dev-insightface": FakeClient(),
                "acx-dev-fir": FakeClient(),
            },
            preflight_transports={
                "acx-dev-insightface": _transport(500, _health("insightface")),
                "acx-dev-fir": _transport(_ready(128), _health("face_pipeline")),
            },
        )
    assert exc.value.code == "preflight_endpoint_missing"
    assert not list((tmp_path / "out-default").rglob("items.jsonl"))


def test_cli_run_fail_closed_aborts_before_media_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.bench import cross_stack_bench
    from scripts.bench.tests.conftest import write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair_path = write_pair(tmp_path / "pair.yaml")
    out = tmp_path / "cli-out"

    def boom(*_a, **_k):
        raise PreflightError("preflight_endpoint_missing", "cli seam")

    monkeypatch.setattr("scripts.bench.preflight.preflight_pair", boom)
    rc = cross_stack_bench.main(
        ["run", "--config", str(pair_path), "--manifest", str(manifest), "--out", str(out)]
    )
    assert rc == 2
    assert not (out / "run.json").exists()
    assert not list(out.rglob("items.jsonl"))


def test_run_pair_persists_preflight_json(tmp_path: Path) -> None:
    from scripts.bench.driver import run_pair
    from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = tmp_path / "out-prov"
    run_pair(
        pair,
        manifest_path=manifest,
        images_dir=images,
        out_dir=out,
        clients={
            "acx-dev-insightface": FakeClient(),
            "acx-dev-fir": FakeClient(),
        },
        preflight_transports={
            "acx-dev-insightface": _transport(_ready(512), _health("insightface")),
            "acx-dev-fir": _transport(_ready(128), _health("face_pipeline")),
        },
    )
    for stack_id, dim, profile in (
        ("acx-dev-insightface", 512, "insightface"),
        ("acx-dev-fir", 128, "face_pipeline"),
    ):
        doc = json.loads((out / "legs" / stack_id / "preflight.json").read_text())
        assert doc["opencv_major"] == 5
        assert doc["opencv_major_source"] == "operator_attested"
        assert doc["resolved_pgvector_dim"] == dim
        assert doc["resolved_profile"] == profile


def test_run_pair_preflights_when_not_skipped(tmp_path: Path) -> None:
    from scripts.bench.driver import run_pair
    from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    with pytest.raises(PreflightError) as exc:
        run_pair(
            pair,
            manifest_path=manifest,
            images_dir=images,
            out_dir=tmp_path / "out",
            clients={
                "acx-dev-insightface": FakeClient(),
                "acx-dev-fir": FakeClient(),
            },
            skip_preflight=False,
            preflight_transports={
                "acx-dev-insightface": _transport(500, _health("insightface")),
                "acx-dev-fir": _transport(_ready(128), _health("face_pipeline")),
            },
        )
    assert exc.value.code == "preflight_endpoint_missing"
    assert not list((tmp_path / "out").rglob("items.jsonl"))


def test_preflight_out_does_not_stamp_config_as_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.bench import cross_stack_bench

    pair_path = write_pair(tmp_path / "pair.yaml")
    out = tmp_path / "preflight-out"
    monkeypatch.setattr(cross_stack_bench, "preflight_pair", lambda *a, **k: {})
    rc = cross_stack_bench.main(["preflight", "--config", str(pair_path), "--out", str(out)])
    assert rc == 0
    assert not (out / "manifest.json").exists()
    assert not (out / "manifest.sha").exists()


def test_preflight_http_500_is_endpoint_missing() -> None:
    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=_transport(500, _health("insightface")),
            api_key="k",
        )
    assert exc.value.code == "preflight_endpoint_missing"


def test_preflight_non_json_500_is_endpoint_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ready":
            return httpx.Response(500, content=b"<html>nope</html>")
        return httpx.Response(200, json=_health("insightface"))

    with pytest.raises(PreflightError) as exc:
        preflight_stack(
            _insightface_endpoint(),
            transport=httpx.MockTransport(handler),
            api_key="k",
        )
    assert exc.value.code == "preflight_endpoint_missing"


def test_bench_package_imports_no_cv2() -> None:
    bench_root = Path(__file__).resolve().parents[1]
    for py_path in bench_root.rglob("*.py"):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "cv2" and not alias.name.startswith("cv2."), py_path
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "cv2" and not node.module.startswith("cv2."), py_path
    imported_by_bench = [
        name
        for name, mod in sys.modules.items()
        if name == "cv2" or name.startswith("cv2.")
    ]
    for name in imported_by_bench:
        origin = getattr(sys.modules[name], "__file__", "") or ""
        assert "scripts/bench" not in origin.replace("\\", "/")
