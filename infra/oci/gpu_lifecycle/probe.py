"""Bounded warm/readiness wait for burst GPU instances (rg-007)."""

from __future__ import annotations

import ipaddress
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProbeStatus(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"
    ERROR = "error"


@dataclass(frozen=True)
class ProbeSample:
    instance_id: str
    status: ProbeStatus
    detail: str = ""


class InstanceReadinessProbe(Protocol):
    def probe(self, instance_id: str) -> ProbeSample: ...


@dataclass(frozen=True)
class ReadinessWaitResult:
    ready: tuple[str, ...]
    stalled: tuple[str, ...]
    timed_out: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def exit_code(self) -> int:
        return 1 if self.stalled or self.timed_out or self.errors else 0

    @property
    def failed(self) -> tuple[str, ...]:
        return self.stalled + self.timed_out


class WarmReadinessWait:
    """Poll each instance until ready, stalled, or the cycle budget expires.

    Per-instance no-progress cycles count probe ERROR / exception only.
    NOT_READY stays pending until max_cycles (normal boot is not a stall).
    One hung instance cannot halt the rest of the batch (rg-007).
    """

    def __init__(
        self,
        *,
        max_cycles: int,
        stall_cycles: int,
        sleep_seconds: float = 0.0,
    ) -> None:
        if max_cycles < 1:
            raise ValueError("max_cycles must be >= 1")
        if stall_cycles < 1:
            raise ValueError("stall_cycles must be >= 1")
        self.max_cycles = max_cycles
        self.stall_cycles = stall_cycles
        self.sleep_seconds = sleep_seconds

    def wait(self, instance_ids: list[str], probe: InstanceReadinessProbe) -> ReadinessWaitResult:
        pending = list(instance_ids)
        ready: list[str] = []
        stalled: list[str] = []
        errors: list[str] = []
        no_progress = dict.fromkeys(instance_ids, 0)

        for cycle in range(self.max_cycles):
            still_pending: list[str] = []
            for instance_id in pending:
                try:
                    sample = probe.probe(instance_id)
                except Exception as exc:  # noqa: BLE001 - isolate per instance
                    errors.append(f"{instance_id}: {type(exc).__name__}: {exc}")
                    no_progress[instance_id] += 1
                    if no_progress[instance_id] >= self.stall_cycles:
                        stalled.append(instance_id)
                        errors.append(f"{instance_id}: stalled after {no_progress[instance_id]} no-progress cycles")
                    else:
                        still_pending.append(instance_id)
                    continue
                if sample.status == ProbeStatus.READY:
                    ready.append(instance_id)
                    no_progress[instance_id] = 0
                    continue
                if sample.status == ProbeStatus.NOT_READY:
                    # Pending boot is progress toward READY; do not stall a
                    # normal A10 bring-up (W3-D-01). Timeout uses max_cycles.
                    no_progress[instance_id] = 0
                    still_pending.append(instance_id)
                    continue
                no_progress[instance_id] += 1
                if sample.detail:
                    errors.append(f"{instance_id}: {sample.detail}")
                if no_progress[instance_id] >= self.stall_cycles:
                    stalled.append(instance_id)
                    errors.append(f"{instance_id}: stalled after {no_progress[instance_id]} no-progress cycles")
                else:
                    still_pending.append(instance_id)
            pending = still_pending
            if not pending:
                break
            if cycle + 1 < self.max_cycles and self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)

        timed_out = list(pending)
        for instance_id in timed_out:
            errors.append(f"{instance_id}: readiness timeout after {self.max_cycles} cycles")
        return ReadinessWaitResult(
            ready=tuple(ready),
            stalled=tuple(stalled),
            timed_out=tuple(timed_out),
            errors=tuple(errors),
        )


def parse_candidate_endpoint(value: str) -> tuple[str, str]:
    """Parse ``INSTANCE_ID=BASE_URL`` into a normalised (id, base URL) pair.

    The base URL is the serving root (``http(s)://host:port``) shared by the
    readiness probe and the published routing target. IP literals must be
    private and routable (no loopback/unspecified/link-local), mirroring
    preflight-gpu-env.sh; hostnames stay subject to the API allowlist.
    """
    instance_id, sep, raw_url = value.partition("=")
    instance_id = instance_id.strip()
    raw_url = raw_url.strip()
    if not sep or not instance_id or not raw_url:
        raise ValueError("expected INSTANCE_ID=http(s)://host:port")
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("candidate endpoint must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("candidate endpoint must not carry userinfo")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("candidate endpoint must be a base URL without path, query or fragment")
    try:
        host = parsed.hostname
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as exc:
        raise ValueError(f"candidate endpoint has a malformed host or port: {exc}") from exc
    if not host:
        raise ValueError("candidate endpoint must name a host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        not address.is_private or address.is_loopback or address.is_unspecified or address.is_link_local
    ):
        raise ValueError("candidate endpoint IP must be private and non-loopback")
    return instance_id, raw_url.rstrip("/")


class HttpReadinessProbe:
    """GET a health URL; non-2xx / transport failure is NOT_READY, not a hang.

    ``url`` may include ``{instance_id}`` for per-instance endpoints. A URL
    without that placeholder is a single shared endpoint and must not be used
    for multi-id waits (caller refuses).
    """

    def __init__(self, *, url: str, timeout_seconds: float = 2.0) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds

    @property
    def is_per_instance(self) -> bool:
        return "{instance_id}" in self._url

    def _url_for(self, instance_id: str) -> str:
        return self._url.replace("{instance_id}", instance_id)

    def probe(self, instance_id: str) -> ProbeSample:
        url = self._url_for(instance_id)
        try:
            with urllib.request.urlopen(url, timeout=self._timeout_seconds) as resp:
                raw_status = getattr(resp, "status", None)
                if raw_status is None:
                    return ProbeSample(
                        instance_id=instance_id,
                        status=ProbeStatus.NOT_READY,
                        detail="missing http status",
                    )
                status = int(raw_status)
                if 200 <= status < 300:
                    return ProbeSample(instance_id=instance_id, status=ProbeStatus.READY)
                return ProbeSample(
                    instance_id=instance_id,
                    status=ProbeStatus.NOT_READY,
                    detail=f"http {status}",
                )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return ProbeSample(
                instance_id=instance_id,
                status=ProbeStatus.NOT_READY,
                detail=str(exc),
            )


class CandidateEndpointProbe:
    """Per-candidate readiness: probe each failover candidate's own endpoint.

    A candidate with no configured endpoint is an ERROR (counts toward stall),
    never a borrowed sibling's health (rg-007).
    """

    def __init__(self, endpoints: Mapping[str, str], *, timeout_seconds: float = 2.0) -> None:
        self._endpoints = dict(endpoints)
        self._timeout_seconds = timeout_seconds

    def probe(self, instance_id: str) -> ProbeSample:
        endpoint = self._endpoints.get(instance_id)
        if endpoint is None:
            return ProbeSample(
                instance_id=instance_id,
                status=ProbeStatus.ERROR,
                detail="no candidate endpoint configured",
            )
        return HttpReadinessProbe(url=f"{endpoint}/health", timeout_seconds=self._timeout_seconds).probe(instance_id)
