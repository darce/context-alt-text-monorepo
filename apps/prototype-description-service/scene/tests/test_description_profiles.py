"""S11: the 4-option description profile switch (seeded / florence_small /
florence_large / gpu_phi4) and its resolution to a DescriptionAdapter.

No model is loaded here — adapter construction is lazy (torch/transformers import
only on ``ensure_loaded``), so the suite stays fast and torch-free. The two
stub profiles (florence_large, gpu_phi4) are fail-closed: selecting them yields
an UnavailableDescriptionAdapter whose ``describe`` raises a clear error.
"""

import pytest

from scene.application.description_adapter import DescriptionAdapter
from scene.config.profiles import (
    PROFILE_SPECS,
    DescriptionProfile,
    get_profile_spec,
)
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.unavailable_adapter import (
    DescriptionAdapterUnavailableError,
    UnavailableDescriptionAdapter,
)


def _reset_singleton():
    from scene.infrastructure.vlm import reset_shared_local_cpu_adapter_for_tests

    reset_shared_local_cpu_adapter_for_tests()


# ----------------------------------------------------------------- the switch


def test_profile_enum_has_exactly_the_four_operator_options():
    assert [p.value for p in DescriptionProfile] == [
        "seeded",
        "florence_small",
        "florence_large",
        "gpu_phi4",
    ]


def test_every_profile_has_a_registry_spec():
    assert set(PROFILE_SPECS) == set(DescriptionProfile)


def test_seeded_profile_is_available_and_model_free():
    spec = get_profile_spec(DescriptionProfile.SEEDED)
    assert spec.available is True
    assert spec.adapter_kind is DescriptionAdapterKind.SEEDED
    assert spec.model_id is None


def test_florence_small_spec_is_the_benchmarked_winner():
    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    assert spec.available is True
    assert spec.adapter_kind is DescriptionAdapterKind.LOCAL_CPU
    assert spec.model_id == "microsoft/Florence-2-base-ft"
    assert spec.model_revision == "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e"
    assert spec.model_version == "florence-2-base-ft"


def test_florence_large_is_a_deferred_stub_pointing_at_the_async_worker():
    spec = get_profile_spec(DescriptionProfile.FLORENCE_LARGE)
    assert spec.available is False
    assert spec.adapter_kind is DescriptionAdapterKind.LOCAL_CPU
    assert spec.model_id == "microsoft/Florence-2-large-ft"
    assert spec.unavailable_reason and "async" in spec.unavailable_reason.lower()


def test_gpu_phi4_is_a_gpu_stub():
    spec = get_profile_spec(DescriptionProfile.GPU_PHI4)
    assert spec.available is False
    assert spec.adapter_kind is DescriptionAdapterKind.GPU
    assert spec.model_id == "microsoft/Phi-4-multimodal-instruct"
    assert spec.unavailable_reason and "gpu" in spec.unavailable_reason.lower()


# ------------------------------------------------------------- settings wiring


def test_settings_default_profile_is_seeded(monkeypatch):
    monkeypatch.delenv("ACX_DESCRIPTION_ADAPTER", raising=False)
    assert DescriptionSettings().profile is DescriptionProfile.SEEDED


def test_settings_reads_profile_from_env(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    assert DescriptionSettings().profile is DescriptionProfile.FLORENCE_SMALL


# ------------------------------------------------------- adapter resolution


def test_resolve_defaults_to_seeded(monkeypatch):
    monkeypatch.delenv("ACX_DESCRIPTION_ADAPTER", raising=False)
    from scene.interface_adapters.http.deps import get_description_adapter

    assert get_description_adapter().kind is DescriptionAdapterKind.SEEDED


def test_resolve_florence_small_builds_local_cpu_without_loading(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    from scene.interface_adapters.http.deps import get_description_adapter

    _reset_singleton()
    try:
        adapter = get_description_adapter()
        assert isinstance(adapter, DescriptionAdapter)
        assert adapter.kind is DescriptionAdapterKind.LOCAL_CPU
        assert adapter.model_id == "microsoft/Florence-2-base-ft"
        assert adapter.model_version == "florence-2-base-ft"
    finally:
        _reset_singleton()


@pytest.mark.parametrize(
    ("profile", "kind"),
    [
        ("florence_large", DescriptionAdapterKind.LOCAL_CPU),
        ("gpu_phi4", DescriptionAdapterKind.GPU),
    ],
)
def test_resolve_stub_profiles_are_fail_closed(monkeypatch, profile, kind):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", profile)
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)
    assert adapter.kind is kind
    with pytest.raises(DescriptionAdapterUnavailableError):
        adapter.describe(image_bytes=b"x", context=None)


def test_florence_small_degrades_to_unavailable_when_vlm_missing(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    import scene.infrastructure.vlm as vlm_pkg
    from scene.interface_adapters.http.deps import get_description_adapter

    def _boom(**kwargs):
        raise RuntimeError("simulated missing [vlm]")

    monkeypatch.setattr(vlm_pkg, "get_shared_local_cpu_adapter", _boom)
    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)
    with pytest.raises(DescriptionAdapterUnavailableError):
        adapter.describe(image_bytes=b"x", context=None)
