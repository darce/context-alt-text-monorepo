"""GPUFAIL-1: every GPU invocation follows the fresh READY failover winner.

The lifecycle snapshot names the winner as ``instance_id`` + ``endpoint_url``.
A snapshot that advertises a winner endpoint switches routing to it; a snapshot
without one keeps the static ``ACX_GPU_ENDPOINT_URL`` (AD-2) path. A stale or
unknown winner never falls back to AD-2, which may be STOPPED.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

import httpx
import pytest

import scene.application.describe_run_worker as wmod
from scene.application.gpu_state import (
    GPU_ROUTING_MODE_ENV,
    GPU_STATE_PATH_ENV,
    GpuRouteSource,
    GpuState,
    resolve_gpu_route,
)
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm import gpu_remote_adapter
from scene.infrastructure.vlm.gpu_remote_adapter import (
    GpuRemoteAdapterError,
    GpuRemoteAdapterErrorReason,
    GpuRemoteDescriptionAdapter,
)

AD2_URL = "http://10.0.1.9:8000"
AD1_URL = "http://10.0.0.7:8000"
AD2_ID = "ocid1.instance.oc1.phx.ad2"
AD1_ID = "ocid1.instance.oc1.phx.ad1"
NOW = 1_800_000_000.0


@pytest.fixture
def snapshot_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "gpu-state.json"
    monkeypatch.setenv(GPU_STATE_PATH_ENV, str(path))
    monkeypatch.delenv(GPU_ROUTING_MODE_ENV, raising=False)
    return path


def _publish(path: Path, *, state: str = "ready", written_at: float | None = None, **fields: object) -> None:
    payload: dict[str, object] = {
        "state": state,
        "instance_id": None,
        "written_at": time.time() if written_at is None else written_at,
        "reason": None,
    }
    payload.update(fields)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _winner(path: Path, *, instance_id: str = AD1_ID, endpoint_url: str = AD1_URL, **fields: object) -> None:
    _publish(path, instance_id=instance_id, endpoint_url=endpoint_url, **fields)


def _route(**kwargs: object):
    kwargs.setdefault("static_endpoint_url", AD2_URL)
    kwargs.setdefault("allowlist", ())
    return resolve_gpu_route(**kwargs)  # type: ignore[arg-type]


# --- resolver policy -------------------------------------------------------


def test_missing_snapshot_keeps_static_ad2_path(snapshot_path: Path) -> None:
    route = _route()
    assert (route.endpoint_url, route.source) == (AD2_URL, GpuRouteSource.STATIC)


def test_single_candidate_snapshot_without_endpoint_keeps_static_ad2(snapshot_path: Path) -> None:
    _publish(snapshot_path, state="stopped", instance_id=AD2_ID)
    route = _route()
    assert (route.endpoint_url, route.source) == (AD2_URL, GpuRouteSource.STATIC)


def test_fresh_ready_winner_routes_to_its_endpoint(snapshot_path: Path) -> None:
    _winner(snapshot_path)
    route = _route()
    assert (route.endpoint_url, route.source, route.instance_id) == (AD1_URL, GpuRouteSource.WINNER, AD1_ID)
    assert route.state is GpuState.READY


@pytest.mark.parametrize("state", ["starting", "warming", "stopped", "degraded"])
def test_winner_that_is_not_ready_fails_closed_for_invocation(snapshot_path: Path, state: str) -> None:
    reason = "readiness_failure" if state == "degraded" else None
    _winner(snapshot_path, state=state, reason=reason)
    route = _route()
    assert route.endpoint_url is None
    assert route.source is GpuRouteSource.WINNER
    assert route.reason


def test_booting_winner_is_the_warmup_target_without_requiring_ready(snapshot_path: Path) -> None:
    _winner(snapshot_path, state="starting")
    assert _route(require_ready=False).endpoint_url == AD1_URL


def test_stale_ad1_winner_never_falls_back_to_static_ad2(snapshot_path: Path) -> None:
    _winner(snapshot_path, written_at=NOW - 3600)
    route = _route(now=NOW)
    assert route.endpoint_url is None
    assert route.source is GpuRouteSource.WINNER
    assert route.state is GpuState.UNKNOWN


@pytest.mark.parametrize(
    "fields",
    [
        {"instance_id": None, "endpoint_url": AD1_URL},
        {"instance_id": AD1_ID, "endpoint_url": None},
        {"instance_id": AD1_ID, "endpoint_url": ""},
        {"instance_id": AD1_ID, "endpoint_url": 7},
        {"instance_id": AD1_ID, "endpoint_url": "http://8.8.8.8:8000"},
        {"instance_id": AD1_ID, "endpoint_url": "http://u:p@10.0.0.7:8000"},
        {"instance_id": AD1_ID, "endpoint_url": "http://10.0.0.7:8000/v1"},
        {"instance_id": AD1_ID, "endpoint_url": "http://10.0.0.7:8000?x=1"},
        {"instance_id": AD1_ID, "endpoint_url": "http://10.0.0.7:99999"},
        {"instance_id": AD1_ID, "endpoint_url": "ftp://10.0.0.7:8000"},
        {"instance_id": AD1_ID, "endpoint_url": "http://evil.example.com:8000"},
    ],
)
def test_malformed_or_unsafe_winner_endpoint_fails_closed(snapshot_path: Path, fields: dict[str, object]) -> None:
    _publish(snapshot_path, **fields)
    route = _route()
    assert route.endpoint_url is None
    assert route.source is GpuRouteSource.WINNER


def test_allowlisted_private_hostname_winner_is_routable(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 0))]
    )
    _winner(snapshot_path, endpoint_url="http://gpu-ad1.sub.vcn.oraclevcn.com:8000")
    assert _route().endpoint_url == "http://gpu-ad1.sub.vcn.oraclevcn.com:8000"


@pytest.mark.parametrize("payload", [None, "{not json", json.dumps({"state": "ready", "written_at": 1})])
def test_winner_mode_fails_closed_without_a_fresh_winner(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str | None
) -> None:
    monkeypatch.setenv(GPU_ROUTING_MODE_ENV, "winner")
    if payload is not None:
        snapshot_path.write_text(payload, encoding="utf-8")
    route = _route()
    assert route.endpoint_url is None
    assert route.source is GpuRouteSource.WINNER


def test_winner_mode_fails_closed_on_ready_snapshot_without_endpoint(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GPU_ROUTING_MODE_ENV, "winner")
    _publish(snapshot_path, instance_id=AD2_ID)
    assert _route().endpoint_url is None


def test_unrecognised_routing_mode_fails_closed_as_winner(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GPU_ROUTING_MODE_ENV, "winer")
    assert _route().endpoint_url is None


# --- adapter: resolve per invocation --------------------------------------


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _recording_transport(urls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "A caption."}}]})

    return httpx.MockTransport(handler)


def _routed_adapter(urls: list[str], **kwargs: object) -> GpuRemoteDescriptionAdapter:
    return GpuRemoteDescriptionAdapter(
        endpoint_url=AD2_URL,
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=_recording_transport(urls),
        endpoint_resolver=lambda: _route(),
        **kwargs,  # type: ignore[arg-type]
    )


def test_adapter_follows_winner_changes_between_invocations(snapshot_path: Path) -> None:
    urls: list[str] = []
    adapter = _routed_adapter(urls, grounding_enabled=True, grounding_timeout_s=5.0)

    _winner(snapshot_path, instance_id=AD2_ID, endpoint_url=AD2_URL)
    adapter.describe(image_bytes=_png(), context=None)
    _winner(snapshot_path, instance_id=AD1_ID, endpoint_url=AD1_URL)
    adapter.describe(image_bytes=_png(), context=None)

    # Caption and grounding of one invocation share that invocation's winner.
    assert urls == [
        f"{AD2_URL}/v1/chat/completions",
        f"{AD2_URL}/v1/chat/completions",
        f"{AD1_URL}/v1/chat/completions",
        f"{AD1_URL}/v1/chat/completions",
    ]


def test_adapter_refuses_to_call_any_endpoint_without_a_ready_winner(snapshot_path: Path) -> None:
    urls: list[str] = []
    adapter = _routed_adapter(urls, grounding_enabled=False)
    _winner(snapshot_path, written_at=time.time() - 3600)

    with pytest.raises(GpuRemoteAdapterError) as excinfo:
        adapter.describe(image_bytes=_png(), context=None)

    assert excinfo.value.reason is GpuRemoteAdapterErrorReason.ENDPOINT_UNREACHABLE
    assert urls == []


def test_static_adapter_without_resolver_is_unchanged(snapshot_path: Path) -> None:
    urls: list[str] = []
    _winner(snapshot_path)
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url=AD2_URL,
        model_id="m",
        model_version="v",
        transport=_recording_transport(urls),
        grounding_enabled=False,
    )
    adapter.describe(image_bytes=_png(), context=None)
    assert urls == [f"{AD2_URL}/v1/chat/completions"]


def test_deps_gpu_adapter_routes_every_call_to_the_current_winner(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scene.interface_adapters.http import deps

    urls: list[str] = []
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", AD2_URL)
    monkeypatch.setenv("ACX_GPU_GROUNDING_ENABLED", "0")
    shared = httpx.Client(transport=_recording_transport(urls))
    monkeypatch.setattr(gpu_remote_adapter, "_get_shared_client", lambda timeout: shared)
    adapter = deps.get_gpu_description_adapter()

    _publish(snapshot_path, state="stopped", instance_id=AD2_ID)
    adapter.describe(image_bytes=_png(), context=None)  # single-candidate: static AD-2
    _winner(snapshot_path)
    adapter.describe(image_bytes=_png(), context=None)  # failover winner AD-1

    assert urls == [f"{AD2_URL}/v1/chat/completions", f"{AD1_URL}/v1/chat/completions"]


# --- worker warmup follows the same winner ---------------------------------


def test_worker_warmup_waits_for_ready_winner_and_probes_only_its_health(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", AD2_URL)
    monkeypatch.setattr(wmod, "_GPU_HEALTH_POLL_INTERVAL_SECONDS", 0)
    policy = wmod.gpu_run_policy(adapter_kind=DescriptionAdapterKind.GPU, settings=DescriptionSettings())
    assert policy is not None
    probed: list[str] = []
    _winner(snapshot_path, state="starting")

    def handler(request: httpx.Request) -> httpx.Response:
        probed.append(str(request.url))
        # The lifecycle promotes the winner once its own endpoint answers.
        _winner(snapshot_path, state="ready")
        return httpx.Response(200)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        wmod.httpx,
        "AsyncClient",
        lambda *, timeout: real_async_client(transport=httpx.MockTransport(handler), timeout=timeout),
    )

    immediately_ready = asyncio.run(
        wmod._wait_for_gpu_ready(
            endpoint_url=policy.endpoint_url,
            api_key=None,
            timeout_seconds=5,
            resolve_route=policy.route,
        )
    )

    assert set(probed) == {f"{AD1_URL}/health"}
    assert immediately_ready is False


def test_worker_warmup_times_out_rather_than_probing_ad2_for_a_stale_winner(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", AD2_URL)
    monkeypatch.setattr(wmod, "_GPU_HEALTH_POLL_INTERVAL_SECONDS", 0.01)
    policy = wmod.gpu_run_policy(adapter_kind=DescriptionAdapterKind.GPU, settings=DescriptionSettings())
    assert policy is not None
    probed: list[str] = []
    _winner(snapshot_path, written_at=time.time() - 3600)

    def handler(request: httpx.Request) -> httpx.Response:
        probed.append(str(request.url))
        return httpx.Response(200)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        wmod.httpx,
        "AsyncClient",
        lambda *, timeout: real_async_client(transport=httpx.MockTransport(handler), timeout=timeout),
    )

    with pytest.raises(TimeoutError, match="no READY GPU winner"):
        asyncio.run(
            wmod._wait_for_gpu_ready(
                endpoint_url=policy.endpoint_url,
                api_key=None,
                timeout_seconds=0.1,
                resolve_route=policy.route,
            )
        )
    assert probed == []


def test_run_describe_job_warmup_uses_policy_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", AD2_URL)
    policy = wmod.gpu_run_policy(adapter_kind=DescriptionAdapterKind.GPU, settings=DescriptionSettings())
    assert policy is not None
    import inspect

    source = inspect.getsource(wmod.run_describe_job)
    assert "resolve_route=gpu_policy.route" in source


# --- health follows the same winner ----------------------------------------


def test_health_detail_evaluates_the_winner_endpoint(
    snapshot_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.main as main_module
    from scene.config.profiles import DescriptionProfile

    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", AD2_URL)
    _winner(snapshot_path, endpoint_url="http://evil.example.com:8000")
    readiness = asyncio.run(main_module._description_adapter_readiness(DescriptionProfile.GPU_QWEN30B))
    assert readiness["usable"] is False
    assert readiness["reason"] == "endpoint_not_allowlisted"
