"""Fail-closed DescriptionAdapter returned when an adapter cannot be used.

Mirrors recognition's Unavailable* fallbacks: the route degrades to a clear,
typed error instead of crashing when torch/transformers or the model is absent
(missing ``[vlm]`` extra) or when a profile is intentionally deferred
(``florence_large`` pending the async worker, ``gpu_phi4`` pending a GPU host).
The describe route maps ``DescriptionAdapterUnavailableError`` to a 503 so the
WordPress UI gets an actionable status rather than an opaque 500.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scene.domain.description import DescriptionAdapterKind


class DescriptionAdapterUnavailableError(RuntimeError):
    """The selected description adapter/profile is not usable in this deployment."""


class UnavailableDescriptionAdapter:
    prompt_or_task_version = "unavailable"

    def __init__(
        self,
        reason: str,
        *,
        kind: DescriptionAdapterKind = DescriptionAdapterKind.LOCAL_CPU,
        model_id: str = "unavailable",
        model_version: str = "unavailable",
    ) -> None:
        self.reason = reason
        self.kind = kind
        self.model_id = model_id
        self.model_version = model_version

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> Any:
        raise DescriptionAdapterUnavailableError(f"description adapter unavailable: {self.reason}")
