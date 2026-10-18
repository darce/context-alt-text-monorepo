"""Characterization: scene + eval secret-key env resolution (SECRETS-P2 Slice 4).

Pins pre-migration observables for ACX_GPU_ENDPOINT_API_KEY (incl. ``or None``),
ACX_HOSTED_PROVIDER_API_KEY, and ACX_EVAL_API_KEY so the SecretProvider swap is
proven inert (TEST-03 / REF-05).
"""

from __future__ import annotations

import pytest

from scene.config.settings import DescriptionSettings
from scene.infrastructure.provider.hosted_provider_adapter import (
    HostedProviderError,
    openai_chat_invoke,
)
from scripts.eval_harness.cli import _require_live_env

# --- ACX_GPU_ENDPOINT_API_KEY (DescriptionSettings.gpu_endpoint_api_key) ---


def test_gpu_endpoint_api_key_resolves_from_env_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set → value."""
    monkeypatch.setenv("ACX_GPU_ENDPOINT_API_KEY", "gpu-secret-key")

    settings = DescriptionSettings()

    assert settings.gpu_endpoint_api_key == "gpu-secret-key"


def test_gpu_endpoint_api_key_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: unset → None (``get(...) or None``)."""
    monkeypatch.delenv("ACX_GPU_ENDPOINT_API_KEY", raising=False)

    settings = DescriptionSettings()

    assert settings.gpu_endpoint_api_key is None


def test_gpu_endpoint_api_key_empty_string_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set-but-empty → None via ``or None`` (not empty string)."""
    monkeypatch.setenv("ACX_GPU_ENDPOINT_API_KEY", "")

    settings = DescriptionSettings()

    assert settings.gpu_endpoint_api_key is None


# --- ACX_HOSTED_PROVIDER_API_KEY (openai_chat_invoke) ---


def test_hosted_provider_api_key_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: unset → \"\" → HostedProviderError (fail-closed)."""
    monkeypatch.delenv("ACX_HOSTED_PROVIDER_API_KEY", raising=False)

    with pytest.raises(HostedProviderError, match="ACX_HOSTED_PROVIDER_API_KEY is not set"):
        openai_chat_invoke(image_bytes=b"\xff\xd8jpeg", context=None, timeout_s=1.0, model="m")


def test_hosted_provider_api_key_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set-empty → \"\" → HostedProviderError."""
    monkeypatch.setenv("ACX_HOSTED_PROVIDER_API_KEY", "")

    with pytest.raises(HostedProviderError, match="ACX_HOSTED_PROVIDER_API_KEY is not set"):
        openai_chat_invoke(image_bytes=b"\xff\xd8jpeg", context=None, timeout_s=1.0, model="m")


def test_hosted_provider_api_key_set_used_in_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set → Bearer header carries that exact key."""
    from scene.infrastructure.provider import hosted_provider_adapter as mod

    captured: dict[str, object] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    def _post(url, *, json, headers, timeout):  # noqa: ANN001
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(mod.httpx, "post", _post)
    monkeypatch.setenv("ACX_HOSTED_PROVIDER_API_KEY", "hosted-char-key")

    openai_chat_invoke(image_bytes=b"\xff\xd8jpeg", context=None, timeout_s=1.0, model="m")

    assert captured["headers"] == {"Authorization": "Bearer hosted-char-key"}


# --- ACX_EVAL_API_KEY (_require_live_env) ---


def test_eval_api_key_resolves_from_env_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set → returned as second tuple element."""
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://eval.example")
    monkeypatch.setenv("ACX_EVAL_API_KEY", "eval-char-key")
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "tenant-1")

    _base, api_key, _tenant = _require_live_env()

    assert api_key == "eval-char-key"


def test_eval_api_key_unset_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: unset → \"\" → sys.exit for missing required env."""
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://eval.example")
    monkeypatch.delenv("ACX_EVAL_API_KEY", raising=False)
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "tenant-1")

    with pytest.raises(SystemExit, match="ACX_EVAL_API_KEY"):
        _require_live_env()


def test_eval_api_key_empty_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization: set-empty → \"\" → treated as missing."""
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://eval.example")
    monkeypatch.setenv("ACX_EVAL_API_KEY", "")
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "tenant-1")

    with pytest.raises(SystemExit, match="ACX_EVAL_API_KEY"):
        _require_live_env()
