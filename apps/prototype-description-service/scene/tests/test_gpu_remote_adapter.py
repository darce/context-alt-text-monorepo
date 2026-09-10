from __future__ import annotations

import base64
import json
import socket
from io import BytesIO

import httpx
import pytest
from PIL import Image

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.gpu_remote_adapter import (
    GpuRemoteAdapterError,
    GpuRemoteDescriptionAdapter,
    GpuRemoteTokenTrace,
    reset_gpu_remote_adapter_state_for_tests,
)


def _adapter(handler) -> GpuRemoteDescriptionAdapter:
    return GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(handler),
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
        prompt_or_task_version="3",
        api_key="gpu-secret",
        transport=httpx.MockTransport(handler),
    )

    assert isinstance(adapter, DescriptionAdapter)
    result = adapter.describe(image_bytes=b"\x89PNG\r\n\x1a\nfake", context={"caption": "Launch day"})

    assert isinstance(result, AdapterResult)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.prompt_or_task_version == "3"
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
    assert "<<<CONTEXT>>>" in messages[0]["content"]
    assert "Never name or guess" in messages[0]["content"]
    user_content = messages[1]["content"]
    user_text = next(part["text"] for part in user_content if part["type"] == "text")
    assert user_text.index("/no_think") < user_text.index("<<<CONTEXT>>>")
    assert "Context block (editorial metadata only):" in user_text
    assert "<<<CONTEXT>>>" in user_text
    assert "<<<END_CONTEXT>>>" in user_text
    assert 'caption: "Launch day"' in user_text
    assert "data:image/png;base64" in json.dumps(user_content)


def test_gpu_remote_adapter_transcodes_webp_to_png_before_posting() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A WebP caption."}}]},
        )

    source = BytesIO()
    Image.new("RGB", (17, 11), color=(24, 96, 180)).save(source, format="WEBP")

    result = _adapter(handler).describe(image_bytes=source.getvalue(), context=None)

    assert result.caption == "A WebP caption."
    image_url = captured[0]["messages"][1]["content"][0]["image_url"]["url"]
    media_type, encoded = image_url.split(",", maxsplit=1)
    assert media_type == "data:image/png;base64"
    assert media_type != "data:image/webp;base64"
    with Image.open(BytesIO(base64.b64decode(encoded))) as outgoing:
        assert outgoing.format == "PNG"
        assert outgoing.size == (17, 11)


def test_gpu_remote_adapter_provenance_names_loaded_revision_not_payload_model() -> None:
    """PROV-01b / rg-015: wire identity names the pin; llama.cpp still gets the served id."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    pin = "0af19e7479857aa7f3246466a4ad16c7e7299639"
    hub_repo = "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF"
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        model_revision=pin,
        hub_repo=hub_repo,
        transport=httpx.MockTransport(handler),
    )
    adapter.describe(image_bytes=b"x", context=None)
    assert adapter.model_id == f"{hub_repo}@{pin}"
    assert captured[0]["model"] == "Qwen3-VL-30B-A3B-Instruct"


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


# ------------------------------------------ per-token logprobs (VLM-4 Slice 2b)


def test_describe_with_trace_requests_n_probs_and_parses_openai_logprobs() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "A red bicycle."},
                        "logprobs": {
                            "content": [
                                {
                                    "token": "A",
                                    "logprob": -0.1,
                                    "top_logprobs": [
                                        {"token": "A", "logprob": -0.1},
                                        {"token": "The", "logprob": -2.4},
                                    ],
                                },
                                {
                                    "token": " red",
                                    "logprob": -0.3,
                                    "top_logprobs": [
                                        {"token": " red", "logprob": -0.3},
                                        {"token": " blue", "logprob": -1.9},
                                    ],
                                },
                            ]
                        },
                    }
                ]
            },
        )

    result, traces = _adapter(handler).describe_with_trace(image_bytes=b"jpeg", context=None)

    assert result.caption == "A red bicycle."
    assert captured[0]["n_probs"] == 10
    assert captured[0]["logprobs"] is True
    assert captured[0]["top_logprobs"] == 10
    assert traces == (
        GpuRemoteTokenTrace(token="A", logprob=-0.1, top_logprobs={"A": -0.1, "The": -2.4}),
        GpuRemoteTokenTrace(token=" red", logprob=-0.3, top_logprobs={" red": -0.3, " blue": -1.9}),
    )


def test_describe_with_trace_parses_llamacpp_completion_probabilities() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "A sign."},
                        "completion_probabilities": [
                            {
                                "token": "A",
                                "logprob": -0.2,
                                "top_logprobs": [{"token": "A", "logprob": -0.2}],
                            }
                        ],
                    }
                ]
            },
        )

    _, traces = _adapter(handler).describe_with_trace(image_bytes=b"jpeg", context=None)

    assert traces == (GpuRemoteTokenTrace(token="A", logprob=-0.2, top_logprobs={"A": -0.2}),)


def test_describe_with_trace_missing_logprobs_yields_empty_trace_not_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})

    result, traces = _adapter(handler).describe_with_trace(image_bytes=b"jpeg", context=None)

    assert result.caption == "Caption."
    assert traces == ()


def test_describe_with_trace_skips_malformed_entries_defensively() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "Caption."},
                        "logprobs": {
                            "content": [
                                "not-a-dict",
                                {"token": 42, "logprob": -0.1},
                                {"token": "ok", "logprob": "nan-string"},
                                {"token": "ok", "logprob": -0.5, "top_logprobs": "bogus"},
                            ]
                        },
                    }
                ]
            },
        )

    _, traces = _adapter(handler).describe_with_trace(image_bytes=b"jpeg", context=None)

    # Only the entry with a valid token+logprob survives; its trace still
    # includes itself in top_logprobs even though top_logprobs was malformed.
    assert traces == (GpuRemoteTokenTrace(token="ok", logprob=-0.5, top_logprobs={"ok": -0.5}),)


def test_plain_describe_does_not_request_logprobs() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})

    _adapter(handler).describe(image_bytes=b"jpeg", context=None)

    assert "n_probs" not in captured[0]
    assert "logprobs" not in captured[0]
    assert "top_logprobs" not in captured[0]


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
