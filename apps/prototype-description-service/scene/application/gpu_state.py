"""Fail-closed reader for the GPU lifecycle snapshot (GPUUX-1).

The lifecycle controller is the single writer of ``/run/acx/gpu-state.json``
(DATA-14). This module only reads it. Missing, unreadable, corrupt, unknown
enum, or stale snapshots become ``GpuState.UNKNOWN`` — never fabricated
``ready`` (RES-03).

It also resolves where a GPU invocation goes (GPUFAIL-1): a snapshot that
publishes the failover winner's ``endpoint_url`` routes every call to that
winner while it is fresh and READY, and fails closed otherwise. A snapshot
without ``endpoint_url`` keeps the static ``ACX_GPU_ENDPOINT_URL`` (AD-2) path.
"""

from __future__ import annotations

import json
import logging
import math
import os
import socket
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_logger = logging.getLogger(__name__)

GPU_STATE_PATH_ENV = "ACX_GPU_STATE_PATH"
DEFAULT_GPU_STATE_PATH = "/run/acx/gpu-state.json"
GPU_STATE_STALE_SECONDS_ENV = "ACX_GPU_STATE_STALE_SECONDS"
DEFAULT_GPU_STATE_STALE_SECONDS = 180.0
GPU_STATE_FUTURE_SKEW_SECONDS = 5.0
GPU_ROUTING_MODE_ENV = "ACX_GPU_ROUTING_MODE"
DEFAULT_GPU_ENDPOINT_ALLOWLIST = (
    "localhost",
    "acx-gpu-burst",
    "*.oraclevcn.com",
)


class GpuState(StrEnum):
    """Burst-GPU execution state on DescribeRunResponse (sr-007)."""

    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    WARMING = "warming"
    READY = "ready"
    DEGRADED = "degraded"


class GpuRoutingMode(StrEnum):
    """How the API picks the GPU endpoint for an invocation (GPUFAIL-1).

    ``static`` (default) keeps ``ACX_GPU_ENDPOINT_URL`` unless the snapshot
    publishes a winner ``endpoint_url``; once it does, the winner rules apply.
    ``winner`` requires a fresh READY winner endpoint for every call, so an
    unreadable snapshot can never silently route to the static endpoint.
    """

    STATIC = "static"
    WINNER = "winner"


class GpuRouteSource(StrEnum):
    STATIC = "static"
    WINNER = "winner"


@dataclass(frozen=True)
class GpuRoute:
    """Endpoint for one GPU invocation; ``endpoint_url`` None means fail closed."""

    endpoint_url: str | None
    source: GpuRouteSource
    state: GpuState
    instance_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class GpuSnapshot:
    """Validated lifecycle snapshot; ``state`` is UNKNOWN when unusable."""

    state: GpuState
    instance_id: str | None = None
    endpoint_url: object = None
    advertises_endpoint: bool = False


_OBSERVED_LOCK = threading.Lock()
_last_observed: GpuState | None = None


@dataclass(frozen=True)
class GpuStateSettings:
    """Immutable GPU snapshot policy loaded once when the service starts.

    An unset stale-seconds variable intentionally uses the documented 180s
    default. An explicitly configured value must be a finite positive number;
    malformed configuration fails startup instead of silently changing policy.
    """

    stale_seconds: float

    @classmethod
    def from_environment(cls) -> GpuStateSettings:
        raw = os.environ.get(GPU_STATE_STALE_SECONDS_ENV)
        if raw is None:
            return cls(stale_seconds=DEFAULT_GPU_STATE_STALE_SECONDS)
        try:
            seconds = float(raw)
        except ValueError:
            seconds = math.nan
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(
                f"{GPU_STATE_STALE_SECONDS_ENV} must be a finite number in the "
                f"range 0 < seconds < infinity; got {raw!r}"
            )
        return cls(stale_seconds=seconds)


_GPU_STATE_SETTINGS = GpuStateSettings.from_environment()


def resolve_gpu_state_path() -> str:
    """Single source of truth for the lifecycle snapshot path (rg-008)."""
    configured_path = os.environ.get(GPU_STATE_PATH_ENV)
    if configured_path is None or not configured_path.strip():
        return DEFAULT_GPU_STATE_PATH
    return configured_path


def resolve_gpu_state_stale_seconds() -> float:
    """Return the immutable snapshot freshness window loaded at startup."""
    return _GPU_STATE_SETTINGS.stale_seconds


def reset_gpu_state_observation_for_tests() -> None:
    """Clear the last-logged state so tests can assert transition logging."""
    global _last_observed
    with _OBSERVED_LOCK:
        _last_observed = None


def read_gpu_state(*, now: float | None = None) -> GpuState:
    """Read the lifecycle snapshot, fail-closed to ``unknown``."""
    state = _read_snapshot(now=time.time() if now is None else now)
    _log_transition(state)
    return state


def _read_snapshot(*, now: float) -> GpuState:
    return read_gpu_snapshot(now=now).state


def read_gpu_snapshot(*, now: float | None = None) -> GpuSnapshot:
    """Read state plus the published winner identity and endpoint."""
    path = Path(resolve_gpu_state_path())
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return GpuSnapshot(state=GpuState.UNKNOWN)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return GpuSnapshot(state=GpuState.UNKNOWN)
    if not isinstance(payload, dict):
        return GpuSnapshot(state=GpuState.UNKNOWN)
    state = _state_from_payload(payload, now=time.time() if now is None else now)
    instance_id = payload.get("instance_id")
    return GpuSnapshot(
        state=state,
        instance_id=instance_id if state is not GpuState.UNKNOWN else None,
        endpoint_url=payload.get("endpoint_url"),
        advertises_endpoint="endpoint_url" in payload,
    )


def resolve_gpu_routing_mode() -> GpuRoutingMode:
    """Unset means static; an unrecognised value fails closed to winner."""
    raw = os.environ.get(GPU_ROUTING_MODE_ENV)
    if raw is None or not raw.strip():
        return GpuRoutingMode.STATIC
    try:
        return GpuRoutingMode(raw.strip().lower())
    except ValueError:
        _logger.warning("%s=%r is not static|winner; failing closed to winner routing", GPU_ROUTING_MODE_ENV, raw)
        return GpuRoutingMode.WINNER


def hostname_matches_allowlist(host: str, allowlist: tuple[str, ...]) -> bool:
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


def resolved_addresses_are_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        try:
            addr = ip_address(sockaddr[0])
        except ValueError:
            return False
        if not (addr.is_private or addr.is_loopback):
            return False
    return True


def is_private_gpu_endpoint(endpoint_url: str, *, allowlist: tuple[str, ...]) -> bool:
    """Accept only private/loopback GPU endpoints under an authoritative allowlist.

    VLMFIX-S1-02: non-allowlisted hostnames are rejected with no DNS fallback
    (a private A record for evil-c2.example.com must not pass). Literal IPs
    still require is_private/is_loopback. Allowlisted hostnames still require
    every resolved address to be private/loopback.
    """
    try:
        parsed = urlsplit(endpoint_url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if host is None:
        return False

    effective_allowlist = allowlist or DEFAULT_GPU_ENDPOINT_ALLOWLIST
    try:
        addr = ip_address(host)
    except ValueError:
        # Hostname path: allowlist is authoritative — no DNS for non-matches.
        if not hostname_matches_allowlist(host, effective_allowlist):
            return False
        return resolved_addresses_are_private(host)
    return addr.is_private or addr.is_loopback


def _winner_base_url(endpoint_url: object) -> str | None:
    """A routable winner endpoint is a bare http(s)://host[:port] base URL."""
    if not isinstance(endpoint_url, str) or not endpoint_url.strip():
        return None
    try:
        parsed = urlsplit(endpoint_url.strip())
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return endpoint_url.strip().rstrip("/")


def resolve_gpu_route(
    *,
    static_endpoint_url: str | None,
    allowlist: tuple[str, ...],
    require_ready: bool = True,
    now: float | None = None,
    mode: GpuRoutingMode | None = None,
) -> GpuRoute:
    """Resolve the endpoint for one GPU call; never a stale or unready winner.

    Winner rules apply when the routing mode is ``winner`` or the snapshot
    publishes ``endpoint_url``: the snapshot must be fresh and valid, name the
    winner ``instance_id``, carry a private allowlisted base URL, and (for an
    invocation) be READY. Anything else fails closed. In particular a known
    AD-1 winner that goes stale is never replaced by the static AD-2 endpoint,
    which the lifecycle may have left STOPPED. Hostname checks resolve DNS, so
    async callers must run this off the event loop.
    """
    snapshot = read_gpu_snapshot(now=now)
    effective_mode = resolve_gpu_routing_mode() if mode is None else mode
    if effective_mode is GpuRoutingMode.STATIC and not snapshot.advertises_endpoint:
        return GpuRoute(
            endpoint_url=static_endpoint_url.rstrip("/") if static_endpoint_url else None,
            source=GpuRouteSource.STATIC,
            state=snapshot.state,
            instance_id=snapshot.instance_id,
            reason=None if static_endpoint_url else "static_endpoint_unconfigured",
        )

    def closed(reason: str) -> GpuRoute:
        return GpuRoute(
            endpoint_url=None,
            source=GpuRouteSource.WINNER,
            state=snapshot.state,
            instance_id=snapshot.instance_id,
            reason=reason,
        )

    if snapshot.state is GpuState.UNKNOWN:
        return closed("gpu_state_unknown")
    if snapshot.instance_id is None:
        return closed("no_failover_winner")
    endpoint_url = _winner_base_url(snapshot.endpoint_url)
    if endpoint_url is None:
        return closed("winner_endpoint_invalid")
    if require_ready and snapshot.state is not GpuState.READY:
        return closed(f"winner_{snapshot.state.value}")
    if not is_private_gpu_endpoint(endpoint_url, allowlist=allowlist):
        return closed("winner_endpoint_not_private")
    return GpuRoute(
        endpoint_url=endpoint_url,
        source=GpuRouteSource.WINNER,
        state=snapshot.state,
        instance_id=snapshot.instance_id,
    )


def _state_from_payload(payload: dict[str, Any], *, now: float) -> GpuState:
    # Standalone mirror of docs/workbay/contracts/gpu-lifecycle.md. The API and
    # lifecycle controller are separate deployables, so do not couple them with
    # a cross-boundary validation import.
    state_raw = payload.get("state")
    if not isinstance(state_raw, str):
        return GpuState.UNKNOWN
    try:
        state = GpuState(state_raw)
    except ValueError:
        return GpuState.UNKNOWN
    if state is GpuState.UNKNOWN:
        return GpuState.UNKNOWN
    written_at = payload.get("written_at")
    if isinstance(written_at, bool) or not isinstance(written_at, (int, float)):
        return GpuState.UNKNOWN
    if not math.isfinite(written_at):
        return GpuState.UNKNOWN

    instance_id = payload.get("instance_id")
    if instance_id is not None and (
        not isinstance(instance_id, str) or not instance_id.strip()
    ):
        return GpuState.UNKNOWN

    # Mirrors the writer's _validate_snapshot_reason: starting may name why it is still starting
    # (readiness_wait_timeout), so a slow boot stays visible instead of reading as UNKNOWN.
    reason = payload.get("reason")
    if state is GpuState.DEGRADED:
        if not isinstance(reason, str) or not reason.strip():
            return GpuState.UNKNOWN
    elif state is GpuState.STARTING:
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            return GpuState.UNKNOWN
    elif reason is not None:
        return GpuState.UNKNOWN

    if "since" in payload:
        since = payload["since"]
        if (
            isinstance(since, bool)
            or not isinstance(since, (int, float))
            or not math.isfinite(since)
            or since > written_at
        ):
            return GpuState.UNKNOWN

    if written_at - now > GPU_STATE_FUTURE_SKEW_SECONDS:
        return GpuState.UNKNOWN
    if now - written_at > resolve_gpu_state_stale_seconds():
        return GpuState.UNKNOWN
    return state


def _log_transition(state: GpuState) -> None:
    global _last_observed
    with _OBSERVED_LOCK:
        previous = _last_observed
        if previous is state:
            return
        _logger.info("gpu_state transition %s -> %s", previous, state)
        _last_observed = state
