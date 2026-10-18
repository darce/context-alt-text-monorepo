"""Hosted-provider DescriptionAdapter (E20-11 Slice 1).

Image bytes leave the Alt Context service boundary when this adapter runs, so it
is opt-in only (``ACX_HOSTED_PROVIDER_OPTIN=1``) and fail-closed: any provider
error, timeout, or malformed response raises ``HostedProviderError`` — never a
partial result. The service maps ``DescriptionAdapterKind.HOSTED_PROVIDER`` to
``ProviderMode.HOSTED``, which drives the existing
``ProviderDisclosure.left_service_boundary`` wire field.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind
from shared.secrets import get_secret_provider

_DEFAULT_TIMEOUT_S = 30.0
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

InvokeFn = Callable[..., AdapterResult]


class HostedProviderError(RuntimeError):
    """The hosted provider call failed; the adapter fails closed (no partial result)."""


def _media_type(image_bytes: bytes) -> str:
    """Sniff the data-URL media type; the service accepts jpeg/png/webp."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def openai_chat_invoke(
    *, image_bytes: bytes, context: Mapping[str, Any] | None, timeout_s: float, model: str
) -> AdapterResult:
    """One image -> one OpenAI chat-completions vision call -> AdapterResult.

    Requires ``ACX_HOSTED_PROVIDER_API_KEY``. ``model`` is the adapter's
    ``model_id`` so wire/audit provenance can never diverge from the model
    actually invoked (rg-015).
    """
    api_key = get_secret_provider().get_secret_optional("ACX_HOSTED_PROVIDER_API_KEY", "") or ""
    if not api_key:
        raise HostedProviderError("ACX_HOSTED_PROVIDER_API_KEY is not set")
    prompt = "Describe this image in one concise, factual sentence suitable as alt text."
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{_media_type(image_bytes)};base64,{base64.b64encode(image_bytes).decode()}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 256,
    }
    response = httpx.post(
        _OPENAI_CHAT_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_s,
    )
    response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise HostedProviderError("provider returned an empty or non-text caption (null/filtered content)")
    caption = content.strip()
    return AdapterResult(
        caption=caption,
        objects=(),
        ocr_text=None,
        alt_text_draft=caption,
        context_sources=(),
        context_applied=False,
    )


class HostedProviderDescriptionAdapter:
    """DescriptionAdapter over a hosted provider call. Fail-closed on any error."""

    kind = DescriptionAdapterKind.HOSTED_PROVIDER

    def __init__(
        self,
        *,
        model_id: str,
        model_version: str,
        prompt_or_task_version: str = "1",
        invoke: InvokeFn = openai_chat_invoke,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.prompt_or_task_version = prompt_or_task_version
        self._invoke = invoke
        self._timeout_s = timeout_s

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        try:
            result = self._invoke(
                image_bytes=image_bytes, context=context, timeout_s=self._timeout_s, model=self.model_id
            )
        except HostedProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — fail closed on any provider fault, never a partial result
            raise HostedProviderError(f"hosted provider call failed: {type(exc).__name__}: {exc}") from exc
        if not isinstance(result, AdapterResult):
            raise HostedProviderError(f"provider invoke returned {type(result).__name__}, expected AdapterResult")
        return result


class FakeHostedProviderAdapter:
    """Deterministic, network-free hosted-adapter double for unit tests."""

    kind = DescriptionAdapterKind.HOSTED_PROVIDER
    model_id = "fake-hosted-model"
    model_version = "fake-1"
    prompt_or_task_version = "1"

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        return AdapterResult(
            caption="A canned hosted-provider caption.",
            objects=(),
            ocr_text=None,
            alt_text_draft="A canned hosted-provider caption.",
            context_sources=(),
            context_applied=False,
        )
