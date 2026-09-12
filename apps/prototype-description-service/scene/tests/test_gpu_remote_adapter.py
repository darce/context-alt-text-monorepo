from __future__ import annotations

import base64
import json
import socket
import threading
from io import BytesIO

import httpx
import pytest
from PIL import Image

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm import gpu_remote_adapter
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
    assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")


def test_gpu_remote_adapter_rejects_webp_over_pixel_ceiling() -> None:
    source = BytesIO()
    Image.new("RGB", (4096, 4096), color=(24, 96, 180)).save(source, format="WEBP", lossless=True)

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        _adapter(lambda request: pytest.fail("oversized image reached the endpoint")).describe(
            image_bytes=source.getvalue(), context=None
        )

    message = str(exc_info.value)
    assert "4096x4096" in message
    assert str(gpu_remote_adapter._DEFAULT_MAX_IMAGE_PIXELS) in message


def test_gpu_remote_adapter_rejects_png_output_over_byte_ceiling(monkeypatch) -> None:
    source = BytesIO()
    Image.new("RGB", (17, 11), color=(24, 96, 180)).save(source, format="WEBP")
    monkeypatch.setattr(gpu_remote_adapter, "_DEFAULT_MAX_ENCODED_IMAGE_BYTES", 1)
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "unreachable"}}]})

    with pytest.raises(GpuRemoteAdapterError, match="PNG output"):
        _adapter(handler).describe(image_bytes=source.getvalue(), context=None)

    assert captured == []


def test_gpu_remote_adapter_serializes_webp_decode_with_gpu_semaphore(monkeypatch) -> None:
    source = BytesIO()
    Image.new("RGB", (17, 11), color=(24, 96, 180)).save(source, format="WEBP")
    image_bytes = source.getvalue()
    original_image_payload = gpu_remote_adapter._image_payload
    first_decode_started = threading.Event()
    second_decode_started = threading.Event()
    release_first_decode = threading.Event()
    second_worker_started = threading.Event()
    lock = threading.Lock()
    active_decodes = 0
    max_active_decodes = 0
    decode_calls = 0

    def tracked_image_payload(image: bytes) -> tuple[str, bytes]:
        nonlocal active_decodes, max_active_decodes, decode_calls
        with lock:
            decode_calls += 1
            call_number = decode_calls
            active_decodes += 1
            max_active_decodes = max(max_active_decodes, active_decodes)
        try:
            if call_number == 1:
                first_decode_started.set()
                if not release_first_decode.wait(timeout=5):
                    raise RuntimeError("test did not release the first decode")
            else:
                second_decode_started.set()
            return original_image_payload(image)
        finally:
            with lock:
                active_decodes -= 1

    monkeypatch.setattr(gpu_remote_adapter, "_image_payload", tracked_image_payload)

    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        max_concurrent_calls=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})
        ),
    )
    errors: list[BaseException] = []

    def run_describe(*, mark_worker_started: bool = False) -> None:
        try:
            if mark_worker_started:
                second_worker_started.set()
            adapter.describe(image_bytes=image_bytes, context=None)
        except BaseException as exc:  # noqa: BLE001 - surface thread failures below
            errors.append(exc)

    first = threading.Thread(target=run_describe)
    second = threading.Thread(target=lambda: run_describe(mark_worker_started=True))
    second_started = False
    try:
        first.start()
        assert first_decode_started.wait(timeout=2)
        second.start()
        second_started = True
        assert second_worker_started.wait(timeout=2)
        second_started_before_first_release = second_decode_started.wait(timeout=1)
    finally:
        release_first_decode.set()
        first.join(timeout=5)
        if second_started:
            second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert decode_calls == 2
    assert not second_started_before_first_release
    assert max_active_decodes == 1


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
