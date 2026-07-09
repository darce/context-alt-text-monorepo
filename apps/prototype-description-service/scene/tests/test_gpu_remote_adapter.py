from __future__ import annotations

import json
import socket

import httpx
import pytest

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.gpu_remote_adapter import (
    GpuRemoteAdapterError,
    GpuRemoteDescriptionAdapter,
    reset_gpu_remote_adapter_state_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_gpu_adapter_state():
    reset_gpu_remote_adapter_state_for_tests()
    yield
    reset_gpu_remote_adapter_state_for_tests()


def test_gpu_remote_adapter_posts_bakeoff_aligned_prompt_and_returns_adapter_result() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "headers": dict(request.headers),
                "payload": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A detailed GPU caption."}}]},
        )

    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        prompt_or_task_version="2",
        api_key="gpu-secret",
        transport=httpx.MockTransport(handler),
    )

    assert isinstance(adapter, DescriptionAdapter)
    result = adapter.describe(image_bytes=b"\x89PNG\r\n\x1a\nfake", context={"caption": "Launch day"})

    assert isinstance(result, AdapterResult)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.prompt_or_task_version == "2"
    assert result.alt_text_draft == "A detailed GPU caption."
    assert result.caption == "A detailed GPU caption."
    assert result.objects == ()
    assert result.context_sources == ("context.caption",)
    assert result.context_applied is True
    assert captured[0]["path"] == "/v1/chat/completions"
    assert captured[0]["headers"]["authorization"] == "Bearer gpu-secret"
    payload = captured[0]["payload"]
    assert payload["model"] == "Qwen3-VL-30B-A3B-Instruct"
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert "Never name or guess" in messages[0]["content"]
    user_content = messages[1]["content"]
    user_text = next(part["text"] for part in user_content if part["type"] == "text")
    assert "Context block:" in user_text
    assert "```" in user_text
    assert "- caption: Launch day" in user_text
    assert "/no_think" in user_text
    assert "data:image/png;base64" in json.dumps(user_content)


def test_gpu_remote_adapter_omits_context_sources_when_context_empty() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})
        ),
    )

    result = adapter.describe(image_bytes=b"jpeg", context={"caption": "", "title": None})

    assert result.context_sources == ()
    assert result.context_applied is False


def test_gpu_remote_adapter_rejects_empty_caption() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        ),
    )

    with pytest.raises(GpuRemoteAdapterError, match="empty caption"):
        adapter.describe(image_bytes=b"jpeg", context=None)


def test_gpu_remote_adapter_rejects_http_5xx() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "busy"})),
    )

    with pytest.raises(GpuRemoteAdapterError, match="GPU endpoint call failed"):
        adapter.describe(image_bytes=b"jpeg", context=None)


def test_gpu_remote_adapter_rejects_non_json_body() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")),
    )

    with pytest.raises(GpuRemoteAdapterError, match="GPU endpoint call failed"):
        adapter.describe(image_bytes=b"jpeg", context=None)


def test_gpu_remote_adapter_rejects_missing_choices_shape() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []})),
    )

    with pytest.raises(GpuRemoteAdapterError, match="missing choices"):
        adapter.describe(image_bytes=b"jpeg", context=None)


def test_gpu_remote_adapter_joins_list_content_parts() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "First"},
                                    {"type": "text", "text": "second"},
                                ]
                            }
                        }
                    ]
                },
            )
        ),
    )

    result = adapter.describe(image_bytes=b"jpeg", context=None)
    assert result.caption == "First second"


def test_gpu_remote_adapter_surfaces_reasoning_only_response() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning_content": "thinking only",
                            }
                        }
                    ]
                },
            )
        ),
    )

    with pytest.raises(GpuRemoteAdapterError, match="reasoning_content"):
        adapter.describe(image_bytes=b"jpeg", context=None)


def test_gpu_remote_adapter_applies_connect_and_read_timeouts(monkeypatch) -> None:
    captured: list[httpx.Timeout] = []
    original_client = httpx.Client

    class _CapturingClient(httpx.Client):
        def __init__(self, *, timeout, transport):
            captured.append(timeout)
            super().__init__(timeout=timeout, transport=transport)

    def _client_factory(*args, **kwargs):
        if kwargs.get("transport") is not None:
            return _CapturingClient(**kwargs)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _client_factory)
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        connect_timeout_s=3.0,
        read_timeout_s=120.0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})
        ),
    )
    adapter.describe(image_bytes=b"jpeg", context=None)

    assert captured
    assert captured[0].connect == 3.0
    assert captured[0].read == 120.0
