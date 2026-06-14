"""S9: local-CPU adapter protocol conformance + fail-closed (no model load).

These tests never load Florence-2 (torch/transformers are imported lazily inside
the adapter), so the suite stays fast and torch-free. The real model load +
inference is exercised by scripts/benchmark_local_vlm.py.
"""

import pytest

from scene.application.description_adapter import DescriptionAdapter
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.florence_local_adapter import LocalCpuDescriptionAdapter
from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter


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
    with pytest.raises(RuntimeError):
        unavailable.describe(image_bytes=b"x", context=None)


def test_get_description_adapter_defaults_to_seeded(monkeypatch):
    monkeypatch.delenv("ACX_DESCRIPTION_ADAPTER", raising=False)
    from scene.interface_adapters.http.deps import get_description_adapter

    assert get_description_adapter().kind is DescriptionAdapterKind.SEEDED


def test_get_description_adapter_selects_local_cpu(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "local_cpu")
    from scene.infrastructure.vlm import reset_shared_local_cpu_adapter_for_tests
    from scene.interface_adapters.http.deps import get_description_adapter

    reset_shared_local_cpu_adapter_for_tests()
    try:
        adapter = get_description_adapter()  # constructs the singleton; no model load
        assert adapter.kind is DescriptionAdapterKind.LOCAL_CPU
    finally:
        reset_shared_local_cpu_adapter_for_tests()


def test_get_description_adapter_degrades_to_unavailable(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "local_cpu")
    import scene.infrastructure.vlm as vlm_pkg
    from scene.interface_adapters.http.deps import get_description_adapter

    def _boom(**kwargs):
        raise RuntimeError("simulated missing [vlm]")

    monkeypatch.setattr(vlm_pkg, "get_shared_local_cpu_adapter", _boom)
    assert isinstance(get_description_adapter(), UnavailableDescriptionAdapter)
