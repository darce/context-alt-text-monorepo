"""DI providers for the scene describe route (E19-1 S5, profile switch S11)."""

from __future__ import annotations

import os
import socket
from fnmatch import fnmatch
from ipaddress import ip_address
from urllib.parse import urlparse

from scene.application.description_adapter import DescriptionAdapter
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.config.profiles import DescriptionProfile, get_profile_spec
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter

_DEFAULT_GPU_ENDPOINT_ALLOWLIST = (
    "localhost",
    "acx-gpu-burst",
    "*.oraclevcn.com",
)


def _hostname_matches_allowlist(host: str, allowlist: tuple[str, ...]) -> bool:
    host_lower = host.lower()
    for entry in allowlist:
        pattern = entry.lower()
        if pattern.startswith("*.") and host_lower.endswith(pattern[1:]):
            return True
        if fnmatch(host_lower, pattern):
            return True
        if host_lower == pattern:
            return True
    return False


def _resolved_addresses_are_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            return False
        try:
            addr = ip_address(sockaddr[0])
        except ValueError:
            return False
        if not (addr.is_private or addr.is_loopback):
            return False
    return True


def _is_private_gpu_endpoint(endpoint_url: str, *, allowlist: tuple[str, ...]) -> bool:
    """Accept only private/loopback GPU endpoints under an authoritative allowlist.

    VLMFIX-S1-02: non-allowlisted hostnames are rejected with no DNS fallback
    (a private A record for evil-c2.example.com must not pass). Literal IPs
    still require is_private/is_loopback. Allowlisted hostnames still require
    every resolved address to be private/loopback.
    """
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if host is None:
        return False

    effective_allowlist = allowlist or _DEFAULT_GPU_ENDPOINT_ALLOWLIST
    try:
        addr = ip_address(host)
    except ValueError:
        # Hostname path: allowlist is authoritative — no DNS for non-matches.
        if not _hostname_matches_allowlist(host, effective_allowlist):
            return False
        return _resolved_addresses_are_private(host)
    return addr.is_private or addr.is_loopback


def get_gpu_description_adapter() -> DescriptionAdapter:
    """Resolve the provisional Qwen GPU profile, independent of the default profile."""
    settings = DescriptionSettings()
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    if settings.gpu_endpoint_url and _is_private_gpu_endpoint(
        settings.gpu_endpoint_url,
        allowlist=settings.gpu_endpoint_allowlist,
    ):
        from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter

        return GpuRemoteDescriptionAdapter(
            endpoint_url=settings.gpu_endpoint_url,
            model_id=spec.model_id or "unavailable",
            model_revision=spec.model_revision,
            model_version=spec.model_version,
            prompt_or_task_version=settings.gpu_prompt_or_task_version,
            connect_timeout_s=settings.gpu_connect_timeout_seconds,
            read_timeout_s=settings.gpu_read_timeout_seconds,
            api_key=settings.gpu_endpoint_api_key,
            max_concurrent_calls=settings.gpu_max_concurrent_calls,
        )
    return UnavailableDescriptionAdapter(
        "ACX_GPU_ENDPOINT_URL must be set to a private/loopback in-tenancy endpoint for the GPU profile",
        kind=DescriptionAdapterKind.GPU,
        model_id=spec.model_id or "unavailable",
        model_version=spec.model_version,
    )


def _build_florence_small_adapter(settings: DescriptionSettings) -> DescriptionAdapter:
    from scene.application.settings.vlm import VlmSettings
    from scene.infrastructure.vlm import get_shared_local_cpu_adapter

    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    vlm = VlmSettings()
    return get_shared_local_cpu_adapter(
        model_id=spec.model_id,
        model_revision=spec.model_revision,
        model_version=spec.model_version,
        max_image_edge_px=vlm.max_image_edge_px,
        num_beams=spec.num_beams or 3,
        max_new_tokens=spec.max_new_tokens or 512,
    )


def get_cpu_description_adapter() -> DescriptionAdapter:
    """Resolve a LOCAL CPU-tier adapter for explicit tier=cpu routing.

    VLMFIX-S1-07: never silently return a hosted adapter. When the default
    profile is local CPU (seeded / florence_*), reuse it; otherwise attempt
    Florence local CPU and fail closed if no local adapter can be resolved.
    """
    settings = DescriptionSettings()
    spec = get_profile_spec(settings.profile)
    if spec.adapter_kind is DescriptionAdapterKind.LOCAL_CPU:
        return get_description_adapter()
    florence_spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    try:
        return _build_florence_small_adapter(settings)
    except Exception as exc:  # noqa: BLE001 - degrade uniformly on import/setup failure
        return UnavailableDescriptionAdapter(
            (
                f"explicit tier=cpu requires a local CPU adapter; default profile "
                f"'{spec.profile.value}' is {spec.adapter_kind.value} and Florence "
                f"fallback failed: {exc}"
            ),
            kind=DescriptionAdapterKind.LOCAL_CPU,
            model_id=florence_spec.model_id or "unavailable",
            model_version=florence_spec.model_version,
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
        # The sync inline route always gets the RAW GPU adapter: the N-pass
        # ensemble multiplies latency N-fold and belongs only on the
        # minutes-tolerant async GPU-final tier — see
        # get_async_gpu_description_adapter (VLM4-RA-BR-02) [RES-02].
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
        return _build_florence_small_adapter(settings)
    except Exception as exc:  # noqa: BLE001 - degrade uniformly on any import/setup failure
        return UnavailableDescriptionAdapter(
            str(exc),
            kind=spec.adapter_kind,
            model_id=spec.model_id or "unavailable",
            model_version=spec.model_version,
        )


def get_async_gpu_description_adapter() -> DescriptionAdapter:
    """GPU adapter for the ASYNC final phase; ensemble-wrapped when opted in.

    The N-view ensemble runs N sequential GPU passes, so it is affordable only
    here — the minutes-tolerant async GPU-final tier — never the inline sync
    route or the CPU-provisional phase (VLM4-RA-BR-02) [RES-02]. One named
    profile opts in [sr-007]; an unavailable GPU stub is returned unwrapped so
    the fail-closed error surfaces once, not once per view.
    """
    gpu_adapter = get_gpu_description_adapter()
    settings = DescriptionSettings()
    spec = get_profile_spec(settings.profile)
    if spec.profile is DescriptionProfile.GPU_QWEN30B_ENSEMBLE and not isinstance(
        gpu_adapter, UnavailableDescriptionAdapter
    ):
        from scene.infrastructure.vlm.ensemble_decode import EnsembleDescriptionAdapter

        return EnsembleDescriptionAdapter(wrapped=gpu_adapter)
    return gpu_adapter
