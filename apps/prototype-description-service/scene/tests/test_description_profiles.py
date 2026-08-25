"""S11: the 4-option description profile switch (seeded / florence_small /
florence_large / gpu_phi4) and its resolution to a DescriptionAdapter.

No model is loaded here — adapter construction is lazy (torch/transformers import
only on ``ensure_loaded``), so the suite stays fast and torch-free. The two
stub profiles (florence_large, gpu_phi4) are fail-closed: selecting them yields
an UnavailableDescriptionAdapter whose ``describe`` raises a clear error.
"""

import socket

import pytest

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.config.profiles import (
    PROFILE_SPECS,
    DescriptionProfile,
    get_profile_spec,
)
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.provider.hosted_provider_adapter import (
    FakeHostedProviderAdapter,
    HostedProviderDescriptionAdapter,
    HostedProviderError,
)
from scene.infrastructure.vlm.unavailable_adapter import (
    DescriptionAdapterUnavailableError,
    UnavailableDescriptionAdapter,
)


def _reset_singleton():
    from scene.infrastructure.vlm import reset_shared_local_cpu_adapter_for_tests

    reset_shared_local_cpu_adapter_for_tests()


# ----------------------------------------------------------------- the switch


def test_profile_enum_has_exactly_the_operator_options():
    assert [p.value for p in DescriptionProfile] == [
        "seeded",
        "florence_small",
        "florence_large",
        "gpu_phi4",
        "gpu_qwen30b",
        "gpu_qwen30b_ensemble",
        "hosted_gpt4o",
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


def test_gpu_qwen30b_profile_is_available_endpoint_profile():
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    assert spec.available is True
    assert spec.adapter_kind is DescriptionAdapterKind.GPU
    assert spec.model_id == "Qwen3-VL-30B-A3B-Instruct"
    assert spec.model_version == "Q4_K_M"
    assert spec.model_revision == "0af19e7479857aa7f3246466a4ad16c7e7299639"


def test_gpu_qwen30b_ensemble_spec_mirrors_gpu_qwen30b():
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B_ENSEMBLE)
    base = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    assert spec.available is True
    assert spec.adapter_kind is DescriptionAdapterKind.GPU
    assert spec.model_id == base.model_id
    assert spec.model_version == base.model_version
    assert spec.model_revision == base.model_revision


def test_available_gpu_profiles_pin_a_non_none_hub_revision():
    """PROV-01a / SEC-10: an available GPU profile without a 40-char hub pin is unauditable."""
    gpu_available = [
        spec
        for spec in PROFILE_SPECS.values()
        if spec.available and spec.adapter_kind is DescriptionAdapterKind.GPU
    ]
    assert gpu_available, "expected at least one available GPU profile"
    for spec in gpu_available:
        revision = spec.model_revision
        assert revision is not None, (
            f"{spec.profile.value} is available=True GPU but model_revision is None "
            "(unpinned hub pull; SEC-10)"
        )
        assert len(revision) == 40, (
            f"{spec.profile.value} model_revision must be a 40-char hub SHA, got {revision!r}"
        )
        assert all(ch in "0123456789abcdef" for ch in revision), (
            f"{spec.profile.value} model_revision is not lowercase hex: {revision!r}"
        )


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


def test_resolve_gpu_qwen30b_requires_endpoint_optin(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.GPU


def test_resolve_gpu_qwen30b_yields_gpu_adapter(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, GpuRemoteDescriptionAdapter)
    assert isinstance(adapter, DescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.model_id == "Qwen3-VL-30B-A3B-Instruct"


def test_resolve_gpu_qwen30b_ensemble_sync_route_gets_raw_gpu_adapter(monkeypatch):
    """VLM4-RA-BR-02 [RES-02]: the sync inline route must NEVER see the N-pass wrapper."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b_ensemble")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, GpuRemoteDescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.model_id == "Qwen3-VL-30B-A3B-Instruct"


def test_resolve_gpu_qwen30b_ensemble_async_final_gets_wrapped_adapter(monkeypatch):
    """VLM4-RA-BR-02: the async GPU-final tier is the ONLY place the ensemble runs."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b_ensemble")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")
    from scene.infrastructure.vlm.ensemble_decode import EnsembleDescriptionAdapter
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter
    from scene.interface_adapters.http.deps import get_async_gpu_description_adapter

    adapter = get_async_gpu_description_adapter()
    assert isinstance(adapter, EnsembleDescriptionAdapter)
    assert isinstance(adapter, DescriptionAdapter)
    assert isinstance(adapter._wrapped, GpuRemoteDescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.model_id == "Qwen3-VL-30B-A3B-Instruct"
    assert adapter.model_version == "Q4_K_M"
    assert adapter.prompt_or_task_version == "3"


def test_resolve_async_gpu_adapter_without_ensemble_profile_is_raw(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter
    from scene.interface_adapters.http.deps import get_async_gpu_description_adapter

    assert isinstance(get_async_gpu_description_adapter(), GpuRemoteDescriptionAdapter)


def test_resolve_gpu_qwen30b_ensemble_without_endpoint_is_fail_closed_unwrapped(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b_ensemble")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    from scene.interface_adapters.http.deps import (
        get_async_gpu_description_adapter,
        get_description_adapter,
    )

    for resolver in (get_description_adapter, get_async_gpu_description_adapter):
        adapter = resolver()
        assert isinstance(adapter, UnavailableDescriptionAdapter)
        assert adapter.kind is DescriptionAdapterKind.GPU


def test_resolve_gpu_qwen30b_rejects_public_endpoint(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "https://example.com")
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)


def test_resolve_gpu_qwen30b_accepts_oraclevcn_host_when_dns_is_private(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://acx-gpu-burst.compute.oraclevcn.com:8000")

    def _private_dns(host, port, family=0, type=0, proto=0, flags=0):
        assert host == "acx-gpu-burst.compute.oraclevcn.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.42", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, GpuRemoteDescriptionAdapter)
    assert adapter.prompt_or_task_version == "3"


def test_resolve_gpu_qwen30b_rejects_allowlisted_host_resolving_public_ip(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://acx-gpu-burst:8000")

    def _public_dns(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)


def test_resolve_gpu_qwen30b_passes_api_key_to_adapter(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://10.0.1.42:8000")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_API_KEY", "secret-key")
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, GpuRemoteDescriptionAdapter)
    assert adapter._api_key == "secret-key"


# --------------------------------------------------- hosted provider (E20-11)


def test_hosted_profile_is_registered_fail_closed():
    spec = get_profile_spec(DescriptionProfile.HOSTED_GPT4O)
    assert spec.available is False
    assert spec.adapter_kind is DescriptionAdapterKind.HOSTED_PROVIDER
    assert spec.model_id == "gpt-4o-mini"
    assert spec.unavailable_reason and "ACX_HOSTED_PROVIDER_OPTIN" in spec.unavailable_reason


def test_resolve_hosted_is_fail_closed_without_optin(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "hosted_gpt4o")
    monkeypatch.delenv("ACX_HOSTED_PROVIDER_OPTIN", raising=False)
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.HOSTED_PROVIDER
    with pytest.raises(DescriptionAdapterUnavailableError):
        adapter.describe(image_bytes=b"x", context=None)


def test_resolve_hosted_optin_yields_hosted_adapter(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "hosted_gpt4o")
    monkeypatch.setenv("ACX_HOSTED_PROVIDER_OPTIN", "1")
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, HostedProviderDescriptionAdapter)
    assert isinstance(adapter, DescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.HOSTED_PROVIDER
    assert adapter.model_id == "gpt-4o-mini"


def test_default_profile_unaffected_by_hosted_optin(monkeypatch):
    monkeypatch.delenv("ACX_DESCRIPTION_ADAPTER", raising=False)
    monkeypatch.setenv("ACX_HOSTED_PROVIDER_OPTIN", "1")
    from scene.interface_adapters.http.deps import get_description_adapter

    assert get_description_adapter().kind is DescriptionAdapterKind.SEEDED


def test_fake_hosted_adapter_satisfies_protocol_with_canned_result():
    fake = FakeHostedProviderAdapter()
    assert isinstance(fake, DescriptionAdapter)
    assert fake.kind is DescriptionAdapterKind.HOSTED_PROVIDER
    result = fake.describe(image_bytes=b"x", context=None)
    assert isinstance(result, AdapterResult)
    assert result.caption


def test_hosted_adapter_fails_closed_on_provider_error():
    def _boom(*, image_bytes, context, timeout_s, model):
        raise RuntimeError("provider 500")

    adapter = HostedProviderDescriptionAdapter(
        model_id="gpt-4o-mini",
        model_version="gpt-4o-mini",
        prompt_or_task_version="1",
        invoke=_boom,
    )
    with pytest.raises(HostedProviderError):
        adapter.describe(image_bytes=b"x", context=None)


class _FakeHttpxResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _capture_httpx_post(monkeypatch, body):
    from scene.infrastructure.provider import hosted_provider_adapter as mod

    calls = {}

    def _post(url, *, json, headers, timeout):
        calls["payload"] = json
        return _FakeHttpxResponse(body)

    monkeypatch.setattr(mod.httpx, "post", _post)
    monkeypatch.setenv("ACX_HOSTED_PROVIDER_API_KEY", "test-key")
    return calls


def test_openai_invoke_uses_adapter_model_and_sniffed_mime(monkeypatch):
    from scene.infrastructure.provider.hosted_provider_adapter import openai_chat_invoke

    calls = _capture_httpx_post(monkeypatch, {"choices": [{"message": {"content": "A caption."}}]})
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    result = openai_chat_invoke(image_bytes=png, context=None, timeout_s=5.0, model="gpt-4o-mini")
    assert result.caption == "A caption."
    assert calls["payload"]["model"] == "gpt-4o-mini"  # rg-015: provenance model == invoked model
    image_url = calls["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


def test_openai_invoke_fails_closed_on_null_content(monkeypatch):
    from scene.infrastructure.provider.hosted_provider_adapter import openai_chat_invoke

    _capture_httpx_post(monkeypatch, {"choices": [{"message": {"content": None}}]})
    with pytest.raises(HostedProviderError):
        openai_chat_invoke(image_bytes=b"\xff\xd8jpeg", context=None, timeout_s=5.0, model="gpt-4o-mini")


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


def test_resolve_gpu_qwen30b_rejects_non_allowlisted_hostname_even_if_dns_private(monkeypatch):
    """VLMFIX-S1-02: allowlist is authoritative — private DNS alone is not enough."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://evil-c2.example.com:8000")

    def _private_dns(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.99", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter
    from scene.interface_adapters.http.deps import get_description_adapter

    adapter = get_description_adapter()
    assert isinstance(adapter, UnavailableDescriptionAdapter)


def test_tier_cpu_never_returns_hosted_adapter(monkeypatch):
    """VLMFIX-S1-07: explicit tier=cpu must not resolve to hosted."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "hosted_gpt4o")
    monkeypatch.setenv("ACX_HOSTED_PROVIDER_OPTIN", "1")
    from scene.domain.description import DescriptionAdapterKind
    from scene.interface_adapters.http.deps import get_cpu_description_adapter

    adapter = get_cpu_description_adapter()
    assert adapter.kind is not DescriptionAdapterKind.HOSTED_PROVIDER
