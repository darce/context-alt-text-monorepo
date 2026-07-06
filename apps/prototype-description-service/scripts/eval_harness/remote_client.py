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

from recognition.domain.job import JobStatus

_DEFAULT_TIMEOUT_S = 60.0
_BREAKER_THRESHOLD = 3
_DEFAULT_MAX_POLL_ATTEMPTS = 60
_CLUSTERS_PAGE_SIZE = 200
_MAX_CLUSTER_PAGES = 100  # rg-007 stall bound: refuse to page forever if the route ignores offset
# Mirror the live JobStatus contract (recognition/domain/job.py) exactly — no
# invented statuses (rg-005/rg-015). completed_with_errors is a terminal partial
# success (return the payload; per-item failures are isolated downstream);
# rejected/failed are terminal failures.
_TERMINAL_SUCCESS_STATUSES = frozenset({JobStatus.COMPLETED.value, JobStatus.COMPLETED_WITH_ERRORS.value})
_TERMINAL_FAILURE_STATUSES = frozenset({JobStatus.REJECTED.value, JobStatus.FAILED.value})


class RemoteClientError(Exception):
    """Request-level failure (HTTP error status, transport error, bad payload).

    ``status_code`` carries the HTTP status when the failure was an error
    response so callers can distinguish a genuine 409 label conflict from a
    systemic outage without string-matching the message (S2-04).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
                    # back off and retry. Individual 429s do not charge the
                    # breaker, but terminal exhaustion is a request-level failure
                    # like any other and must strike it (S2-02) so a persistently
                    # rate-limited key can open the circuit instead of hammering
                    # the live box for ~50 min.
                    rate_limit_retries += 1
                    if rate_limit_retries > self._max_rate_limit_retries:
                        self._consecutive_failures += 1
                        raise RemoteClientError(
                            f"{method} {url} failed: 429 rate limit persisted after "
                            f"{self._max_rate_limit_retries} backoff retries"
                        )
                    time.sleep(self._retry_after_seconds(response.headers.get("Retry-After")))
                    continue
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                self._consecutive_failures += 1
                status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                raise RemoteClientError(f"{method} {url} failed: {exc}", status_code=status_code) from exc
            self._consecutive_failures = 0
            return payload

    def _request_dict(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        payload = self._request(method, url, **kwargs)
        if not isinstance(payload, dict):
            raise RemoteClientError(f"{method} {url}: expected JSON object, got {type(payload).__name__}")
        return payload

    def _retry_after_seconds(self, header_value: str | None) -> float:
        """Seconds to sleep before a 429 retry, floored at ``rate_limit_wait``.

        Retry-After may be a delay in seconds or an HTTP-date (RFC 9110, plausible
        from a CDN/nginx fronting the box); a date or any malformed value must not
        escape as an uncaught ValueError outside the typed-error contract (S2-03) —
        fall back to the configured floor instead.
        """
        floor = self._rate_limit_wait
        if header_value is None:
            return floor
        try:
            seconds = float(header_value)
        except ValueError:
            return floor
        return max(seconds, floor)

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
        """POST /recognition/analyze/multipart (one image_<media_id> part each) -> job_id.

        The route envelope requires only ``tenant_id``; media ids are derived
        server-side from the ``image_<media_id>`` part names, so the client must
        not invent a ``media_ids`` envelope field the route ignores (rg-015).
        """
        files = [(f"image_{media_id}", (filename, image_bytes)) for media_id, filename, image_bytes in images]
        payload = self._request(
            "POST",
            "/recognition/analyze/multipart",
            files=files,
            data={"request": json.dumps({"tenant_id": self.tenant_id})},
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

    def clusters(self, labeled_only: bool = False) -> list[dict[str, Any]]:
        """GET /recognition/clusters (tenant from API key), fully paginated.

        The route returns a bare ``list[ClusterResponse]`` capped by the server's
        ``max_page_size``; walk offsets until a short page so clusters beyond the
        first page are never silently invisible (S2-08) — the seed's idempotency
        early-return and coverage re-check both depend on seeing every cluster.
        """
        all_clusters: list[dict[str, Any]] = []
        for _page in range(_MAX_CLUSTER_PAGES):
            page = self._request(
                "GET",
                "/recognition/clusters",
                params={
                    "labeled_only": labeled_only,
                    "limit": _CLUSTERS_PAGE_SIZE,
                    "offset": len(all_clusters),
                },
            )
            if not isinstance(page, list):
                raise RemoteClientError(f"GET /recognition/clusters: expected JSON array, got {type(page).__name__}")
            all_clusters.extend(page)
            if len(page) < _CLUSTERS_PAGE_SIZE:
                return all_clusters
        # Bounded loop (rg-007): a route that ignored offset and always returned a
        # full page would otherwise spin forever against the live box.
        raise RemoteClientError(
            f"GET /recognition/clusters: pagination exceeded {_MAX_CLUSTER_PAGES} pages "
            f"({_MAX_CLUSTER_PAGES * _CLUSTERS_PAGE_SIZE} clusters); refusing to loop unboundedly"
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
