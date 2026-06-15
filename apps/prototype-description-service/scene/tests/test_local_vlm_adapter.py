"""S9: local-CPU adapter protocol conformance + fail-closed (no model load).

These tests never load Florence-2 (torch/transformers are imported lazily inside
the adapter), so the suite stays fast and torch-free. The real model load +
inference is exercised by scripts/benchmark_local_vlm.py. Profile-switch
resolution (which profile picks which adapter) lives in test_description_profiles.py.
"""

import pytest

from scene.application.description_adapter import DescriptionAdapter
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.florence_local_adapter import LocalCpuDescriptionAdapter
from scene.infrastructure.vlm.unavailable_adapter import (
    DescriptionAdapterUnavailableError,
    UnavailableDescriptionAdapter,
)


def test_local_cpu_adapter_conforms_to_protocol_without_loading():
    adapter = LocalCpuDescriptionAdapter()
    assert isinstance(adapter, DescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.LOCAL_CPU
    assert adapter.model_id and adapter.model_version and adapter.prompt_or_task_version


def test_prompt_version_encodes_tasks_and_beams():
    a = LocalCpuDescriptionAdapter(tasks=("<MORE_DETAILED_CAPTION>",), num_beams=1)
    b = LocalCpuDescriptionAdapter(tasks=("<MORE_DETAILED_CAPTION>", "<OD>"), num_beams=3)
    assert a.prompt_or_task_version != b.prompt_or_task_version


def test_unavailable_adapter_is_protocol_and_fails_closed():
    unavailable = UnavailableDescriptionAdapter("missing [vlm] extra")
    assert isinstance(unavailable, DescriptionAdapter)
    # DescriptionAdapterUnavailableError subclasses RuntimeError.
    with pytest.raises(DescriptionAdapterUnavailableError):
        unavailable.describe(image_bytes=b"x", context=None)


def test_unavailable_adapter_carries_provenance_for_stub_profiles():
    stub = UnavailableDescriptionAdapter(
        "deferred", kind=DescriptionAdapterKind.GPU, model_id="microsoft/Phi-4-multimodal-instruct"
    )
    assert stub.kind is DescriptionAdapterKind.GPU
    assert stub.model_id == "microsoft/Phi-4-multimodal-instruct"
