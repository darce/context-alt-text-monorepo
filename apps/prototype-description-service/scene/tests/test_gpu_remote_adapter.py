from __future__ import annotations

import base64
import importlib
import json
import logging
import socket
import threading
from types import SimpleNamespace
from io import BytesIO

import httpx
import pytest
from PIL import Image

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.application.identity_merge.merge import NormalizedBox, span_replaceable
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm import gpu_remote_adapter
from scene.infrastructure.vlm.gpu_remote_adapter import (
    GpuRemoteAdapterError,
    GpuRemoteAdapterErrorReason,
    GpuRemoteDescriptionAdapter,
    GpuRemoteTokenTrace,
    reset_gpu_remote_adapter_state_for_tests,
)


def _adapter(handler, **kwargs) -> GpuRemoteDescriptionAdapter:
    return GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _png_bytes(*, width: int = 100, height: int = 100) -> bytes:
    source = BytesIO()
    Image.new("RGB", (width, height), color=(24, 96, 180)).save(source, format="PNG")
    return source.getvalue()


def _jpeg_bytes(*, width: int = 100, height: int = 100) -> bytes:
    source = BytesIO()
    Image.new("RGB", (width, height), color=(24, 96, 180)).save(source, format="JPEG")
    return source.getvalue()


def _user_text_from_payload(payload: dict) -> str:
    content = payload["messages"][1]["content"]
    return next(part["text"] for part in content if part["type"] == "text")


def _caption_then_grounding_handler(
    *,
    caption: str,
    grounding_content: str,
    captured: list[dict],
):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        if "Locate each person mentioned in the caption" in _user_text_from_payload(payload):
            return httpx.Response(200, json={"choices": [{"message": {"content": grounding_content}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": caption}}]})

    return handler


def test_gpu_remote_adapter_stores_quantization_and_defaults_to_none() -> None:
    default_adapter = _adapter(lambda request: httpx.Response(200, json={}))
    assert default_adapter.quantization is None

    explicit_adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="1",
        quantization="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    assert explicit_adapter.quantization == "Q4_K_M"


@pytest.fixture(autouse=True)
def _reset_gpu_adapter_state(monkeypatch):
    monkeypatch.delenv("ACX_GPU_GROUNDING_ENABLED", raising=False)
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
    result = adapter.describe(image_bytes=_png_bytes(), context={"caption": "Launch day"})

    assert isinstance(result, AdapterResult)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.prompt_or_task_version == "3"
    assert result.alt_text_draft == "A detailed GPU caption."
    assert result.caption == "A detailed GPU caption."
    assert result.objects == ()
    assert result.phrase_boxes == ()
    assert result.context_sources == ("context.caption",)
    assert result.context_applied is True
    assert len(captured) == 1
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

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "4096x4096" in exc_info.value.raw_diagnostic
    assert str(gpu_remote_adapter._DEFAULT_MAX_IMAGE_PIXELS) in exc_info.value.raw_diagnostic
    assert "4096x4096" not in str(exc_info.value)


def test_gpu_remote_adapter_rejects_oversized_webp_before_decoder_construction(monkeypatch) -> None:
    image_bytes = bytearray(25)
    image_bytes[0:4] = b"RIFF"
    image_bytes[8:12] = b"WEBP"
    image_bytes[12:16] = b"VP8L"
    image_bytes[20] = 0x2F
    image_bytes[21:25] = ((4096 - 1) | ((4096 - 1) << 14)).to_bytes(4, "little")

    def fail_open(*args, **kwargs):
        raise AssertionError("Image.open must not be reached")

    monkeypatch.setattr(gpu_remote_adapter.Image, "open", fail_open)

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        gpu_remote_adapter._image_payload(bytes(image_bytes))

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "4096x4096" in exc_info.value.raw_diagnostic
    assert str(gpu_remote_adapter._DEFAULT_MAX_IMAGE_PIXELS) in exc_info.value.raw_diagnostic


def test_gpu_remote_adapter_rejects_png_over_pixel_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(gpu_remote_adapter, "_DEFAULT_MAX_IMAGE_PIXELS", 50)
    image_bytes = _png_bytes(width=10, height=10)

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        gpu_remote_adapter._image_payload(image_bytes)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "image/png" in exc_info.value.raw_diagnostic
    assert "10x10" in exc_info.value.raw_diagnostic
    assert "50" in exc_info.value.raw_diagnostic
    assert "10x10" not in str(exc_info.value)


def test_gpu_remote_adapter_rejects_jpeg_over_pixel_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(gpu_remote_adapter, "_DEFAULT_MAX_IMAGE_PIXELS", 50)
    image_bytes = _jpeg_bytes(width=10, height=10)

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        gpu_remote_adapter._image_payload(image_bytes)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "image/jpeg" in exc_info.value.raw_diagnostic
    assert "10x10" in exc_info.value.raw_diagnostic
    assert "50" in exc_info.value.raw_diagnostic
    assert "10x10" not in str(exc_info.value)


def test_gpu_remote_adapter_png_under_pixel_ceiling_is_byte_identical(monkeypatch) -> None:
    monkeypatch.setattr(gpu_remote_adapter, "_DEFAULT_MAX_IMAGE_PIXELS", 10_000)
    image_bytes = _png_bytes(width=32, height=24)

    media_type, outgoing = gpu_remote_adapter._image_payload(image_bytes)

    assert media_type == "image/png"
    assert outgoing == image_bytes


def test_gpu_remote_adapter_jpeg_under_pixel_ceiling_is_byte_identical(monkeypatch) -> None:
    monkeypatch.setattr(gpu_remote_adapter, "_DEFAULT_MAX_IMAGE_PIXELS", 10_000)
    image_bytes = _jpeg_bytes(width=32, height=24)

    media_type, outgoing = gpu_remote_adapter._image_payload(image_bytes)

    assert media_type == "image/jpeg"
    assert outgoing == image_bytes


def test_gpu_remote_adapter_unreadable_png_header_fails_closed() -> None:
    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        gpu_remote_adapter._image_payload(b"\x89PNG\r\n\x1a\nfake")

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "image/png" in exc_info.value.raw_diagnostic


def test_gpu_remote_adapter_unreadable_jpeg_header_fails_closed() -> None:
    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        gpu_remote_adapter._image_payload(b"jpeg")

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "image/jpeg" in exc_info.value.raw_diagnostic


def test_webp_canvas_size_matches_pillow_for_real_webp() -> None:
    source = BytesIO()
    Image.new("RGB", (17, 11), color=(24, 96, 180)).save(source, format="WEBP", lossless=True)
    image_bytes = source.getvalue()

    with Image.open(BytesIO(image_bytes)) as image:
        expected_size = image.size

    assert gpu_remote_adapter._webp_canvas_size(image_bytes) == expected_size


def test_webp_canvas_size_matches_pillow_for_lossy_vp8_webp() -> None:
    source = BytesIO()
    Image.new("RGB", (19, 13), color=(24, 96, 180)).save(source, format="WEBP", lossless=False)
    image_bytes = source.getvalue()

    assert image_bytes[12:16] == b"VP8 "
    with Image.open(BytesIO(image_bytes)) as image:
        expected_size = image.size

    assert gpu_remote_adapter._webp_canvas_size(image_bytes) == expected_size


def test_webp_canvas_size_matches_pillow_for_vp8x_webp() -> None:
    source = BytesIO()
    Image.new("RGBA", (19, 13), color=(24, 96, 180, 127)).save(source, format="WEBP")
    image_bytes = source.getvalue()

    assert image_bytes[12:16] == b"VP8X"
    with Image.open(BytesIO(image_bytes)) as image:
        expected_size = image.size

    assert gpu_remote_adapter._webp_canvas_size(image_bytes) == expected_size


def test_gpu_remote_adapter_rejects_png_output_over_byte_ceiling(monkeypatch) -> None:
    source = BytesIO()
    Image.new("RGB", (17, 11), color=(24, 96, 180)).save(source, format="WEBP")
    monkeypatch.setattr(gpu_remote_adapter, "_DEFAULT_MAX_ENCODED_IMAGE_BYTES", 1)
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "unreachable"}}]})

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        _adapter(handler).describe(image_bytes=source.getvalue(), context=None)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.IMAGE_UNSUPPORTED
    assert "PNG output" in exc_info.value.raw_diagnostic
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
    adapter.describe(image_bytes=_png_bytes(), context=None)
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

    result = adapter.describe(image_bytes=_jpeg_bytes(), context={"caption": "", "title": None})

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

    with pytest.raises(GpuRemoteAdapterError, match="empty caption") as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.EMPTY_CAPTION


def test_gpu_remote_adapter_rejects_http_5xx() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "busy"})),
    )

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.ENDPOINT_REJECTED
    assert exc_info.value.status_code == 503


def test_gpu_remote_adapter_rejects_auth_body_without_leaking_upstream_details() -> None:
    endpoint_url = "http://gpu.test:8000"
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url=endpoint_url,
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": {"message": "invalid api key"}})
        ),
    )

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    error = exc_info.value
    assert error.reason == "endpoint_rejected"
    assert error.status_code == 401
    assert error.upstream_status == 401
    assert "invalid api key" not in str(error)
    assert "invalid api key" not in error.message
    assert endpoint_url not in str(error)
    assert endpoint_url not in error.message
    assert "invalid api key" in error.raw_diagnostic


@pytest.mark.parametrize(
    ("error_type", "detail"),
    [
        (httpx.ConnectError, "connect failed for gpu.test:8000"),
        (httpx.ReadTimeout, "read timed out for gpu.test:8000"),
    ],
)
def test_gpu_remote_adapter_classifies_transport_failures_without_leaking_details(error_type, detail) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(detail, request=request)

    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    error = exc_info.value
    assert error.reason == "endpoint_unreachable"
    assert "ConnectError" not in error.message
    assert "ReadTimeout" not in error.message
    assert "gpu.test:8000" not in error.message
    assert detail in error.raw_diagnostic


def test_gpu_remote_adapter_rejects_non_json_body() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json")),
    )

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.RESPONSE_MALFORMED
    assert "not-json" in exc_info.value.raw_diagnostic


def test_gpu_remote_adapter_rejects_missing_choices_shape() -> None:
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [], "body": "secret-body"})),
    )

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.RESPONSE_MALFORMED
    assert "missing choices" in exc_info.value.raw_diagnostic
    assert "secret-body" not in exc_info.value.message


def test_gpu_remote_adapter_rejects_response_without_text_parts_without_leaking_body() -> None:
    response_body = {
        "choices": [
            {
                "message": {
                    "content": [{"type": "image_url", "image_url": {"url": "secret-body"}}],
                }
            }
        ]
    }
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_body)),
    )

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    error = exc_info.value
    assert error.reason == "response_malformed"
    assert "secret-body" not in error.message
    assert "secret-body" in error.raw_diagnostic


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

    result = adapter.describe(image_bytes=_jpeg_bytes(), context=None)
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

    with pytest.raises(GpuRemoteAdapterError) as exc_info:
        adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    assert exc_info.value.reason == GpuRemoteAdapterErrorReason.RESPONSE_MALFORMED
    assert "reasoning_content" in exc_info.value.raw_diagnostic


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

    result, traces = _adapter(handler).describe_with_trace(image_bytes=_jpeg_bytes(), context=None)

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

    _, traces = _adapter(handler).describe_with_trace(image_bytes=_jpeg_bytes(), context=None)

    assert traces == (GpuRemoteTokenTrace(token="A", logprob=-0.2, top_logprobs={"A": -0.2}),)


def test_describe_with_trace_missing_logprobs_yields_empty_trace_not_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})

    result, traces = _adapter(handler).describe_with_trace(image_bytes=_jpeg_bytes(), context=None)

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

    _, traces = _adapter(handler).describe_with_trace(image_bytes=_jpeg_bytes(), context=None)

    # Only the entry with a valid token+logprob survives; its trace still
    # includes itself in top_logprobs even though top_logprobs was malformed.
    assert traces == (GpuRemoteTokenTrace(token="ok", logprob=-0.5, top_logprobs={"ok": -0.5}),)


def test_plain_describe_does_not_request_logprobs() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})

    _adapter(handler).describe(image_bytes=_jpeg_bytes(), context=None)

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
    adapter.describe(image_bytes=_jpeg_bytes(), context=None)

    assert captured
    assert captured[0].connect == 3.0
    assert captured[0].read == 120.0


def test_reloading_gpu_remote_adapter_does_not_change_pillow_pixel_policy(monkeypatch) -> None:
    sentinel = 123456789
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", sentinel)

    # Reload rebinds every class in the module namespace; callers that imported
    # GpuRemoteAdapterError by value (the describe router) would stop matching it.
    snapshot = dict(vars(gpu_remote_adapter))
    try:
        importlib.reload(gpu_remote_adapter)

        assert sentinel == Image.MAX_IMAGE_PIXELS
    finally:
        vars(gpu_remote_adapter).clear()
        vars(gpu_remote_adapter).update(snapshot)


# ------------------------------------------ Qwen person-span grounding (GPUFLOW-3 N3)


def test_gpu_remote_adapter_grounding_flag_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("ACX_GPU_GROUNDING_ENABLED", raising=False)
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "A man stands."}}]})

    result = _adapter(handler).describe(image_bytes=_png_bytes(), context=None)

    assert result.phrase_boxes == ()
    assert len(captured) == 1
    assert "Locate each person mentioned in the caption" not in _user_text_from_payload(captured[0])


def test_gpu_remote_adapter_grounding_env_flag_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("ACX_GPU_GROUNDING_ENABLED", raising=False)
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "Caption."}}]})
        ),
    )
    assert adapter.grounding_enabled is False


def test_gpu_remote_adapter_grounding_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("ACX_GPU_GROUNDING_ENABLED", "true")
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands by a window.",
        grounding_content=json.dumps({"bboxes": [[100.0, 100.0, 600.0, 900.0]], "labels": ["A man"]}),
        captured=captured,
    )

    result = _adapter(handler).describe(image_bytes=_png_bytes(), context=None)

    assert len(captured) == 2
    assert len(result.phrase_boxes) == 1
    assert result.phrase_boxes[0].phrase == "A man"


def test_gpu_remote_adapter_explicit_off_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv("ACX_GPU_GROUNDING_ENABLED", "true")
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "A man stands."}}]})

    result = _adapter(handler, grounding_enabled=False).describe(image_bytes=_png_bytes(), context=None)

    assert result.phrase_boxes == ()
    assert len(captured) == 1


def test_gpu_remote_adapter_grounding_maps_florence_shape_phrase_boxes() -> None:
    captured: list[dict] = []
    caption = "A man stands by a window."
    handler = _caption_then_grounding_handler(
        caption=caption,
        grounding_content=json.dumps({"bboxes": [[100.0, 100.0, 600.0, 900.0]], "labels": ["A man"]}),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert result.caption == caption
    assert len(captured) == 2
    assert captured[1]["max_tokens"] == 512
    assert "n_probs" not in captured[1]
    grounding_text = _user_text_from_payload(captured[1])
    assert "Locate each person mentioned in the caption" in grounding_text
    assert "bbox_2d" in grounding_text
    assert "0-1000" in grounding_text
    assert caption in grounding_text
    assert "/no_think" in grounding_text
    assert len(result.phrase_boxes) == 1
    box = result.phrase_boxes[0]
    assert box.phrase == "A man"
    assert (box.span_start, box.span_end) == (0, 5)
    assert box.box == NormalizedBox(x=0.1, y=0.1, width=0.5, height=0.8)


def test_gpu_remote_adapter_grounding_accepts_qwen_bbox_2d_list() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content=json.dumps([{"bbox_2d": [250.0, 100.0, 750.0, 900.0], "label": "A woman"}]),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert len(result.phrase_boxes) == 1
    assert result.phrase_boxes[0].phrase == "A woman"
    assert result.phrase_boxes[0].box == NormalizedBox(x=0.25, y=0.10, width=0.50, height=0.80)


def test_gpu_remote_adapter_grounding_accepts_unit_frame_boxes() -> None:
    # N-B-14: unit-frame only for non-bbox_2d quads with a fractional coordinate.
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A person sits.",
        grounding_content=json.dumps({"bboxes": [[0.1, 0.2, 0.6, 0.9]], "labels": ["A person"]}),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert result.phrase_boxes[0].box == NormalizedBox(x=0.1, y=0.2, width=0.5, height=0.7)


def test_gpu_remote_adapter_grounding_bbox_2d_zero_one_stays_in_qwen_frame() -> None:
    # N-B-14: Qwen bbox_2d [0,0,1,1] is 0.1% of the 0-1000 frame, not a full-image box.
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content=json.dumps([{"bbox_2d": [0, 0, 1, 1], "label": "A woman"}]),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert len(result.phrase_boxes) == 1
    assert result.phrase_boxes[0].phrase == "A woman"
    assert result.phrase_boxes[0].box == NormalizedBox(x=0.0, y=0.0, width=0.001, height=0.001)
    assert result.phrase_boxes[0].box.width != 1.0
    assert result.phrase_boxes[0].box.height != 1.0


def test_gpu_remote_adapter_grounding_malformed_boxes_fail_closed() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands.",
        grounding_content=json.dumps({"bboxes": ["not-a-quad"], "labels": ["A man"]}),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert result.caption == "A man stands."
    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_out_of_image_boxes_fail_closed() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands.",
        grounding_content=json.dumps({"bboxes": [[0.0, 0.0, 2000.0, 50.0]], "labels": ["A man"]}),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=100, height=100), context=None
    )

    assert result.caption == "A man stands."
    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_coord_above_1000_outside_image_fails_closed() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content=json.dumps([{"bbox_2d": [0.0, 0.0, 1001.0, 800.0], "label": "A woman"}]),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_coord_in_open_1000_to_image_width_fails_closed() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content=json.dumps([{"bbox_2d": [0.0, 0.0, 1500.0, 800.0], "label": "A woman"}]),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_negative_coord_fails_closed() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content=json.dumps([{"bbox_2d": [-50.0, 0.0, 500.0, 500.0], "label": "A woman"}]),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_missing_boxes_fail_closed() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands.",
        grounding_content="I cannot locate anyone.",
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert result.caption == "A man stands."
    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_follow_up_failure_keeps_caption() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        if "Locate each person mentioned in the caption" in _user_text_from_payload(payload):
            return httpx.Response(500, text="upstream grounding fault")
        return httpx.Response(200, json={"choices": [{"message": {"content": "A man stands."}}]})

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert result.caption == "A man stands."
    assert result.phrase_boxes == ()
    assert len(captured) == 2


def test_gpu_remote_adapter_grounding_follow_up_uses_own_timeout(monkeypatch) -> None:
    captured_timeouts: list[httpx.Timeout] = []
    original_client = httpx.Client

    class _CapturingClient(httpx.Client):
        def __init__(self, *, timeout, transport):
            captured_timeouts.append(timeout)
            super().__init__(timeout=timeout, transport=transport)

    def _client_factory(*args, **kwargs):
        if kwargs.get("transport") is not None:
            return _CapturingClient(**kwargs)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _client_factory)
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands.",
        grounding_content=json.dumps({"bboxes": [], "labels": []}),
        captured=captured,
    )
    adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        connect_timeout_s=3.0,
        read_timeout_s=120.0,
        grounding_enabled=True,
        grounding_timeout_s=12.0,
        transport=httpx.MockTransport(handler),
    )
    adapter.describe(image_bytes=_png_bytes(), context=None)

    assert len(captured_timeouts) == 2
    assert captured_timeouts[0].read == 120.0
    assert captured_timeouts[1].read == 12.0
    assert captured_timeouts[1].connect == 3.0


def _budget_adapter(handler, *, read_timeout_s: float) -> GpuRemoteDescriptionAdapter:
    return GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        connect_timeout_s=3.0,
        read_timeout_s=read_timeout_s,
        grounding_enabled=True,
        grounding_timeout_s=30.0,
        transport=httpx.MockTransport(handler),
    )


def _fake_monotonic(monkeypatch, readings: list[float]) -> None:
    import scene.infrastructure.vlm.gpu_remote_adapter as adapter_module

    values = iter(readings)
    monkeypatch.setattr(adapter_module, "time", SimpleNamespace(monotonic=lambda: next(values)))


def test_gpu_remote_adapter_grounding_is_capped_by_remaining_caption_budget(monkeypatch) -> None:
    captured_timeouts: list[httpx.Timeout] = []
    original_client = httpx.Client

    def _client_factory(*args, **kwargs):
        if kwargs.get("transport") is not None:
            captured_timeouts.append(kwargs["timeout"])
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _client_factory)
    # Caption took 165s of a 175s budget: grounding may use only the 10s left, not its 30s default.
    _fake_monotonic(monkeypatch, [0.0, 165.0])
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands.",
        grounding_content=json.dumps({"bboxes": [], "labels": []}),
        captured=captured,
    )
    _budget_adapter(handler, read_timeout_s=175.0).describe(image_bytes=_png_bytes(), context=None)

    assert len(captured) == 2
    assert captured_timeouts[1].read == 10.0
    assert captured_timeouts[1].connect == 3.0


def test_gpu_remote_adapter_skips_grounding_when_caption_budget_is_spent(monkeypatch, caplog) -> None:
    _fake_monotonic(monkeypatch, [0.0, 174.5])
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A man stands.",
        grounding_content=json.dumps({"bboxes": [], "labels": []}),
        captured=captured,
    )
    with caplog.at_level(logging.INFO):
        result = _budget_adapter(handler, read_timeout_s=175.0).describe(image_bytes=_png_bytes(), context=None)

    assert result.caption == "A man stands."
    assert result.phrase_boxes == ()
    assert len(captured) == 1
    assert "budget_exhausted" in caplog.text


def test_gpu_remote_adapter_grounding_labels_bind_on_word_boundaries() -> None:
    captured: list[dict] = []
    caption = "A woman and a man stand."
    handler = _caption_then_grounding_handler(
        caption=caption,
        grounding_content=json.dumps(
            [
                {"bbox_2d": [50.0, 100.0, 400.0, 900.0], "label": "woman"},
                {"bbox_2d": [500.0, 100.0, 900.0, 900.0], "label": "man"},
            ]
        ),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert len(result.phrase_boxes) == 2
    woman, man = result.phrase_boxes
    assert woman.phrase == "woman"
    assert (woman.span_start, woman.span_end) == (2, 7)
    assert caption[woman.span_start : woman.span_end] == "woman"
    assert man.phrase == "man"
    assert (man.span_start, man.span_end) == (14, 17)
    assert caption[man.span_start : man.span_end] == "man"
    assert (man.span_start, man.span_end) != (4, 7)


def test_gpu_remote_adapter_grounding_accepts_markdown_fenced_json() -> None:
    captured: list[dict] = []
    rows = [{"bbox_2d": [250.0, 100.0, 750.0, 900.0], "label": "A woman"}]
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content="```json\n" + json.dumps(rows) + "\n```",
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert len(result.phrase_boxes) == 1
    assert result.phrase_boxes[0].phrase == "A woman"
    assert (result.phrase_boxes[0].span_start, result.phrase_boxes[0].span_end) == (0, 7)
    assert result.phrase_boxes[0].box == NormalizedBox(x=0.25, y=0.10, width=0.50, height=0.80)


def test_gpu_remote_adapter_grounding_single_object_payload_yields_no_boxes() -> None:
    captured: list[dict] = []
    handler = _caption_then_grounding_handler(
        caption="A woman waves.",
        grounding_content=json.dumps({"bbox_2d": [250.0, 100.0, 750.0, 900.0], "label": "A woman"}),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert result.caption == "A woman waves."
    assert result.phrase_boxes == ()


def test_gpu_remote_adapter_grounding_unmatched_label_is_not_replaceable() -> None:
    captured: list[dict] = []
    caption = "A woman waves."
    handler = _caption_then_grounding_handler(
        caption=caption,
        grounding_content=json.dumps([{"bbox_2d": [250.0, 100.0, 750.0, 900.0], "label": "a man"}]),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(
        image_bytes=_png_bytes(width=2000, height=1500), context=None
    )

    assert len(result.phrase_boxes) == 1
    box = result.phrase_boxes[0]
    assert box.phrase == "a man"
    assert (box.span_start, box.span_end) == (-1, -1)
    assert span_replaceable(caption, box) is False


def test_gpu_remote_adapter_grounding_repeated_label_advances_cursor() -> None:
    captured: list[dict] = []
    caption = "A man and a man"
    handler = _caption_then_grounding_handler(
        caption=caption,
        grounding_content=json.dumps(
            [
                {"bbox_2d": [50.0, 100.0, 400.0, 900.0], "label": "man"},
                {"bbox_2d": [500.0, 100.0, 900.0, 900.0], "label": "man"},
            ]
        ),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert len(result.phrase_boxes) == 2
    first, second = result.phrase_boxes
    assert first.phrase == "man"
    assert (first.span_start, first.span_end) == (2, 5)
    assert caption[first.span_start : first.span_end] == "man"
    assert second.phrase == "man"
    assert (second.span_start, second.span_end) == (12, 15)
    assert caption[second.span_start : second.span_end] == "man"
    assert second.span_start > first.span_end


def test_gpu_remote_adapter_grounding_keeps_valid_rows_from_mixed_payload() -> None:
    captured: list[dict] = []
    caption = "A woman and a man stand."
    handler = _caption_then_grounding_handler(
        caption=caption,
        grounding_content=json.dumps(
            [
                {"bbox_2d": [50.0, 100.0, 400.0, 900.0], "label": "woman"},
                "not-an-object",
                {"bbox_2d": "bad-quad", "label": "person"},
                {"label": "missing-box"},
                {"bbox_2d": [500.0, 100.0, 900.0, 900.0], "label": "man"},
            ]
        ),
        captured=captured,
    )

    result = _adapter(handler, grounding_enabled=True).describe(image_bytes=_png_bytes(), context=None)

    assert len(result.phrase_boxes) == 2
    woman, man = result.phrase_boxes
    assert woman.phrase == "woman"
    assert (woman.span_start, woman.span_end) == (2, 7)
    assert man.phrase == "man"
    assert (man.span_start, man.span_end) == (14, 17)
