from __future__ import annotations

import json

import httpx

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter


def test_gpu_remote_adapter_posts_image_context_and_returns_adapter_result() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"path": request.url.path, "payload": json.loads(request.content)})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A detailed GPU caption."}}]},
        )

    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_GGUF",
        transport=httpx.MockTransport(handler),
    )

    assert isinstance(adapter, DescriptionAdapter)
    result = adapter.describe(image_bytes=b"\x89PNG\r\n\x1a\nfake", context={"caption": "Launch day"})

    assert isinstance(result, AdapterResult)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert result.alt_text_draft == "A detailed GPU caption."
    assert result.objects == ()
    assert result.context_sources == ("context.caption",)
    assert captured[0]["path"] == "/v1/chat/completions"
    assert captured[0]["payload"]["model"] == "Qwen3-VL-30B-A3B-Instruct"
    assert "Launch day" in json.dumps(captured[0]["payload"])
    assert "data:image/png;base64" in json.dumps(captured[0]["payload"])


def test_gpu_remote_adapter_rejects_empty_caption() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_GGUF",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        ),
    )

    try:
        adapter.describe(image_bytes=b"jpeg", context=None)
    except RuntimeError as exc:
        assert "empty caption" in str(exc)
    else:
        raise AssertionError("empty GPU caption should fail closed")
