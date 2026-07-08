"""Endpoint-backed GPU DescriptionAdapter for the bursty VLM tier."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import httpx

from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind

_DEFAULT_TIMEOUT_S = 180.0


def _media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class GpuRemoteAdapterError(RuntimeError):
    """The GPU endpoint failed or returned an invalid adapter payload."""


class GpuRemoteDescriptionAdapter:
    """DescriptionAdapter over an in-tenancy GPU endpoint."""

    kind = DescriptionAdapterKind.GPU

    def __init__(
        self,
        *,
        endpoint_url: str,
        model_id: str,
        model_version: str,
        prompt_or_task_version: str = "1",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.model_id = model_id
        self.model_version = model_version
        self.prompt_or_task_version = prompt_or_task_version
        self._timeout_s = timeout_s
        self._transport = transport

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        prompt = "Describe this image in 2-4 plain sentences suitable as alt text."
        if context:
            prompt = f"{prompt}\nContext: {dict(context)}"
        payload = {
            "model": self.model_id,
            "temperature": 0,
            "max_tokens": 512,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{_media_type(image_bytes)};base64,{base64.b64encode(image_bytes).decode()}"
                                )
                            },
                        },
                    ],
                }
            ],
        }
        try:
            with httpx.Client(timeout=self._timeout_s, transport=self._transport) as client:
                response = client.post(f"{self.endpoint_url}/v1/chat/completions", json=payload)
                response.raise_for_status()
                body = response.json()
        except GpuRemoteAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed on endpoint faults
            raise GpuRemoteAdapterError(f"GPU endpoint call failed: {type(exc).__name__}: {exc}") from exc

        caption = _extract_caption(body)
        alt_text_draft = caption
        if not isinstance(caption, str) or not caption.strip():
            raise GpuRemoteAdapterError("GPU endpoint returned an empty caption")

        return AdapterResult(
            caption=caption.strip(),
            objects=(),
            ocr_text=None,
            alt_text_draft=alt_text_draft.strip(),
            context_sources=tuple(f"context.{key}" for key in (context or {})),
            context_applied=bool(context),
        )


def _extract_caption(body: dict[str, Any]) -> str:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GpuRemoteAdapterError(f"GPU endpoint response missing choices[0].message: {body!r}") from exc
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    if not isinstance(content, str) or not content.strip():
        raise GpuRemoteAdapterError("GPU endpoint returned an empty caption")
    return content.strip()
