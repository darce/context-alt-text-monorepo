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
        payload = {
            "model": self.model_id,
            "image": {
                "media_type": _media_type(image_bytes),
                "base64": base64.b64encode(image_bytes).decode(),
            },
            "context": dict(context or {}),
        }
        try:
            with httpx.Client(timeout=self._timeout_s, transport=self._transport) as client:
                response = client.post(f"{self.endpoint_url}/describe", json=payload)
                response.raise_for_status()
                body = response.json()
        except GpuRemoteAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed on endpoint faults
            raise GpuRemoteAdapterError(f"GPU endpoint call failed: {type(exc).__name__}: {exc}") from exc

        caption = body.get("caption")
        alt_text_draft = body.get("alt_text_draft", caption)
        if not isinstance(caption, str) or not caption.strip():
            raise GpuRemoteAdapterError("GPU endpoint returned an empty caption")
        if not isinstance(alt_text_draft, str) or not alt_text_draft.strip():
            raise GpuRemoteAdapterError("GPU endpoint returned an empty alt_text_draft")

        return AdapterResult(
            caption=caption.strip(),
            objects=tuple(str(item) for item in body.get("objects", ())),
            ocr_text=body.get("ocr_text") if isinstance(body.get("ocr_text"), str) else None,
            alt_text_draft=alt_text_draft.strip(),
            context_sources=tuple(str(item) for item in body.get("context_sources", ())),
            context_applied=bool(body.get("context_applied", False)),
        )
