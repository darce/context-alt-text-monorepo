"""Fail-closed DescriptionAdapter returned when the local VLM cannot be used.

Mirrors recognition's Unavailable* fallbacks: the worker/route degrades to a
clear error instead of crashing when torch/transformers or the model is absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind


class UnavailableDescriptionAdapter:
    kind = DescriptionAdapterKind.LOCAL_CPU
    model_id = "unavailable"
    model_version = "unavailable"
    prompt_or_task_version = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        raise RuntimeError(f"local VLM adapter unavailable: {self.reason}")
