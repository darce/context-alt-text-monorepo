"""Local-CPU VLM (Florence-2) infrastructure for image description (E19-1 S9).

Imports here must stay light: torch/transformers live behind the ``[vlm]`` extra
and are imported lazily inside the adapter so the default recognition-only
runtime never pulls them.
"""

from __future__ import annotations

from scene.infrastructure.vlm.florence_local_adapter import (
    LocalCpuDescriptionAdapter,
    LocalVlmUnavailableError,
)
from scene.infrastructure.vlm.unavailable_adapter import (
    DescriptionAdapterUnavailableError,
    UnavailableDescriptionAdapter,
)

_SHARED: LocalCpuDescriptionAdapter | None = None


def get_shared_local_cpu_adapter(**kwargs) -> LocalCpuDescriptionAdapter:
    """Process-wide singleton so the heavy model loads at most once."""
    global _SHARED
    if _SHARED is None:
        _SHARED = LocalCpuDescriptionAdapter(**kwargs)
    return _SHARED


def reset_shared_local_cpu_adapter_for_tests() -> None:
    global _SHARED
    _SHARED = None


__all__ = [
    "DescriptionAdapterUnavailableError",
    "LocalCpuDescriptionAdapter",
    "LocalVlmUnavailableError",
    "UnavailableDescriptionAdapter",
    "get_shared_local_cpu_adapter",
    "reset_shared_local_cpu_adapter_for_tests",
]
