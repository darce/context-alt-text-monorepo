"""HTTP client for the remote OCI service — Nygard discipline (assessment §7).

Explicit per-request timeout, 3-strike circuit breaker (shared across calls,
reset on success), bounded job polling. Concurrency 1 by construction: one
synchronous client, one request in flight (the live demo box must not degrade).
Per-item failure isolation and bounded-stall exit (rg-007) live in the CLI
fetch loop; this client only raises typed errors.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

_DEFAULT_TIMEOUT_S = 60.0
_BREAKER_THRESHOLD = 3
_DEFAULT_MAX_POLL_ATTEMPTS = 60
_TERMINAL_FAILURE_STATUSES = {"failed", "error", "cancelled"}
_TERMINAL_SUCCESS_STATUSES = {"completed", "done", "succeeded"}


class RemoteClientError(Exception):
    """Request-level failure (HTTP error status, transport error, bad payload)."""


class CircuitOpenError(RemoteClientError):
    """Raised without touching the network after 3 consecutive failures."""


class JobPollTimeoutError(RemoteClientError):
    """Job did not reach a terminal status within the bounded poll budget."""


class RemoteSceneClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        tenant_id: str = "",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_poll_attempts: int = _DEFAULT_MAX_POLL_ATTEMPTS,
        poll_interval: float = 2.0,
        rate_limit_wait: float = 20.0,
        max_rate_limit_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.tenant_id = tenant_id
        headers = {"X-API-Key": api_key}
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id  # required by get_tenant_id deps (media routes)
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
        )
        self._max_poll_attempts = max_poll_attempts
        self._poll_interval = poll_interval
        self._rate_limit_wait = rate_limit_wait
        self._max_rate_limit_retries = max_rate_limit_retries
        self._consecutive_failures = 0

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        if self._consecutive_failures >= _BREAKER_THRESHOLD:
            raise CircuitOpenError(
                f"circuit open after {self._consecutive_failures} consecutive failures; "
                "aborting before further remote calls"
            )
        rate_limit_retries = 0
        while True:
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code == 429:
                    # Expected under the per-key RPM budget (STANDARD = 60 rpm);
                    # back off and retry without charging the breaker.
                    rate_limit_retries += 1
                    if rate_limit_retries > self._max_rate_limit_retries:
                        raise RemoteClientError(
                            f"{method} {url} failed: 429 rate limit persisted after "
                            f"{self._max_rate_limit_retries} backoff retries"
                        )
                    retry_after = float(response.headers.get("Retry-After", self._rate_limit_wait))
                    time.sleep(max(retry_after, self._rate_limit_wait) if retry_after else self._rate_limit_wait)
                    continue
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                self._consecutive_failures += 1
                raise RemoteClientError(f"{method} {url} failed: {exc}") from exc
            self._consecutive_failures = 0
            return payload

    def _request_dict(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        payload = self._request(method, url, **kwargs)
        if not isinstance(payload, dict):
            raise RemoteClientError(f"{method} {url}: expected JSON object, got {type(payload).__name__}")
        return payload

    def describe(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        media_id: int,
        context_pack: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /scene/describe/multipart -> visual facts + alt-text draft.

        Contract (describe.py): single part named ``image_<media_id>``; envelope
        requires ``tenant_id`` + ``media_id``; legacy ``context`` dict carries the
        WP title/caption fields used by the golden manifest's context packs.
        """
        return self._request_dict(
            "POST",
            "/scene/describe/multipart",
            files={f"image_{media_id}": (filename, image_bytes)},
            data={
                "request": json.dumps(
                    {
                        "tenant_id": self.tenant_id,
                        "media_id": media_id,
                        "context": context_pack or None,
                    }
                )
            },
        )

    def analyze(self, images: list[tuple[int, str, bytes]]) -> str:
        """POST /recognition/analyze/multipart (one image_<media_id> part each) -> job_id."""
        files = [(f"image_{media_id}", (filename, image_bytes)) for media_id, filename, image_bytes in images]
        payload = self._request(
            "POST",
            "/recognition/analyze/multipart",
            files=files,
            data={"request": json.dumps({"tenant_id": self.tenant_id, "media_ids": [str(m) for m, _, _ in images]})},
        )
        job_id = payload.get("id") or payload.get("job_id")  # JobStatusResponse uses `id`
        if not isinstance(job_id, str) or not job_id:
            raise RemoteClientError(f"analyze response missing job id: {payload!r}")
        return job_id

    def wait_job(self, job_id: str) -> dict[str, Any]:
        """Poll GET /recognition/jobs/{job_id} until terminal; bounded attempts."""
        for attempt in range(1, self._max_poll_attempts + 1):
            payload = self._request_dict("GET", f"/recognition/jobs/{job_id}")
            status = str(payload.get("status", "")).lower()
            if status in _TERMINAL_SUCCESS_STATUSES:
                return payload
            if status in _TERMINAL_FAILURE_STATUSES:
                raise RemoteClientError(f"job {job_id} reached terminal status {status!r}")
            if attempt < self._max_poll_attempts and self._poll_interval > 0:
                time.sleep(self._poll_interval)
        raise JobPollTimeoutError(f"job {job_id} not terminal after {self._max_poll_attempts} polls")

    def media_identities(self, media_ids: list[int]) -> Any:
        """GET /recognition/media/identities?media_ids=... (repeated params)."""
        return self._request(
            "GET",
            "/recognition/media/identities",
            params=[("media_ids", str(m)) for m in media_ids],
        )

    def clustering_job(self, tenant_id: str, mode: str = "sync") -> dict[str, Any]:
        """POST /recognition/clustering/jobs (sync mode completes inline)."""
        return self._request_dict(
            "POST",
            "/recognition/clustering/jobs",
            json={"tenant_id": tenant_id, "mode": mode},
        )

    def clusters(self, labeled_only: bool = False) -> Any:
        """GET /recognition/clusters (tenant from API key)."""
        return self._request(
            "GET",
            "/recognition/clusters",
            params={"labeled_only": labeled_only, "limit": 200},
        )

    def cluster_members(self, cluster_id: str) -> dict[str, Any]:
        """GET /recognition/clusters/{id}/members (members carry media_id)."""
        return self._request_dict("GET", f"/recognition/clusters/{cluster_id}/members")

    def patch_cluster(self, cluster_id: str, tenant_id: str, label: str) -> dict[str, Any]:
        """PATCH /recognition/clusters/{id} — labeling sets user_confirmed server-side."""
        return self._request_dict(
            "PATCH",
            f"/recognition/clusters/{cluster_id}",
            json={"tenant_id": tenant_id, "label": label},
        )
