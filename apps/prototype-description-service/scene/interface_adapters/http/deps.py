"""DI providers for the scene describe route (E19-1 S5, profile switch S11)."""

from __future__ import annotations

import os
from ipaddress import ip_address
from urllib.parse import urlparse

from scene.application.description_adapter import DescriptionAdapter
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.config.profiles import DescriptionProfile, get_profile_spec
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter


def _is_private_gpu_endpoint(endpoint_url: str) -> bool:
    parsed = urlparse(endpoint_url)
    host = parsed.hostname
    if host is None:
        return False
    if host in {"localhost", "acx-gpu-burst"} or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        addr = ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def get_gpu_description_adapter() -> DescriptionAdapter:
    """Resolve the provisional Qwen GPU profile, independent of the default profile."""
    settings = DescriptionSettings()
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    if settings.gpu_endpoint_url and _is_private_gpu_endpoint(settings.gpu_endpoint_url):
        from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter

        return GpuRemoteDescriptionAdapter(
            endpoint_url=settings.gpu_endpoint_url,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
            prompt_or_task_version=settings.prompt_or_task_version,
            timeout_s=settings.generation_timeout_seconds,
        )
    return UnavailableDescriptionAdapter(
        "ACX_GPU_ENDPOINT_URL must be set to a private/loopback in-tenancy endpoint for the GPU profile",
        kind=DescriptionAdapterKind.GPU,
        model_id=spec.model_id or "unavailable",
        model_version=spec.model_version,
    )


def get_description_adapter() -> DescriptionAdapter:
    """Resolve the configured ``ACX_DESCRIPTION_ADAPTER`` profile to an adapter.

    - ``seeded`` (default): deterministic, instant, model-free.
    - ``florence_small``: Florence-2-base-ft local-CPU adapter (process-wide
      singleton, lazy model load). A missing ``[vlm]`` extra degrades to a
      fail-closed UnavailableDescriptionAdapter rather than a 500 at import.
    - ``florence_large`` / ``gpu_phi4``: deferred stubs — fail-closed adapters
      naming why and where the enablement notes live.

    NOTE: ``florence_small`` runs off the event loop (``asyncio.to_thread`` in
    VisualFactsService) but still inline within the request; the DB-backed async
    worker is deferred (see the profile registry impl-notes pointer).
    """
    settings = DescriptionSettings()
    spec = get_profile_spec(settings.profile)

    if spec.profile is DescriptionProfile.SEEDED:
        return SeededDescriptionAdapter(
            model_version=settings.model_version,
            prompt_or_task_version=settings.prompt_or_task_version,
        )

    if spec.adapter_kind is DescriptionAdapterKind.HOSTED_PROVIDER:
        # Registered available=False; usable only behind the explicit opt-in env
        # because image bytes leave the service boundary (E20-11).
        if os.environ.get("ACX_HOSTED_PROVIDER_OPTIN") == "1":
            from scene.infrastructure.provider.hosted_provider_adapter import (
                HostedProviderDescriptionAdapter,
            )

            return HostedProviderDescriptionAdapter(
                model_id=spec.model_id or "unavailable",
                model_version=spec.model_version,
            )
        return UnavailableDescriptionAdapter(
            spec.unavailable_reason or f"profile '{spec.profile.value}' is not available",
            kind=spec.adapter_kind,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
        )

    if spec.adapter_kind is DescriptionAdapterKind.GPU and spec.available:
        return get_gpu_description_adapter()

    if not spec.available:
        return UnavailableDescriptionAdapter(
            spec.unavailable_reason or f"profile '{spec.profile.value}' is not available",
            kind=spec.adapter_kind,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
        )

    # Available local-CPU Florence profile (florence_small).
    try:
        from scene.application.settings.vlm import VlmSettings
        from scene.infrastructure.vlm import get_shared_local_cpu_adapter

        vlm = VlmSettings()
        return get_shared_local_cpu_adapter(
            model_id=spec.model_id,
            model_revision=spec.model_revision,
            model_version=spec.model_version,
            max_image_edge_px=vlm.max_image_edge_px,
            num_beams=spec.num_beams or 3,
            max_new_tokens=spec.max_new_tokens or 512,
        )
    except Exception as exc:  # noqa: BLE001 - degrade uniformly on any import/setup failure
        return UnavailableDescriptionAdapter(
            str(exc),
            kind=spec.adapter_kind,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
        )
