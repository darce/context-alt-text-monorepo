"""Own authenticated GETs against /ready and /health/detailed."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from scripts.bench.stack_pair import BenchError, StackEndpoint, StackPairConfig

_DIM_TOKEN = re.compile(r"pgvector_dimension=(\d+)")
_RUNTIME_FINGERPRINT_TOKEN = re.compile(r"(?:^|;\s*)numeric_runtime_fingerprint=(\{.*\})$")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PreflightError(BenchError):
    """Stable-code preflight failure. Never writes a partial preflight.json."""


@dataclass(frozen=True)
class PreflightResult:
    stack_id: str
    base_url: str
    expected_profile: str
    expected_pgvector_dim: int
    resolved_profile: str
    resolved_pgvector_dim: int
    opencv_major: int
    opencv_major_source: str
    checked_at: str
    ready_excerpt: dict[str, Any]
    health_detailed_excerpt: dict[str, Any]


def preflight_stack(
    endpoint: StackEndpoint,
    *,
    transport: httpx.BaseTransport | None = None,
    api_key: str | None = None,
) -> PreflightResult:
    if getattr(endpoint, "opencv_major", None) in (None, ""):
        raise PreflightError("opencv_major_unattested", "opencv_major is required")
    try:
        expected_opencv_major = int(endpoint.opencv_major)
    except (TypeError, ValueError) as exc:
        raise PreflightError("opencv_major_unattested", "opencv_major is not parseable") from exc

    headers: dict[str, str] = {}
    key = api_key
    if key:
        headers["X-API-Key"] = key
    client = httpx.Client(
        base_url=endpoint.base_url,
        headers=headers,
        timeout=httpx.Timeout(30.0),
        transport=transport,
    )
    try:
        ready_body = _get_json(client, "/ready", auth=False)
        health_body = _get_json(client, "/health/detailed", auth=True)
    finally:
        client.close()

    dim = _parse_ready_dim(ready_body, endpoint.expected_pgvector_dim)
    profile = _parse_health_profile(health_body, endpoint.expected_profile)
    _parse_model_bundle_provenance(health_body)
    runtime_fingerprint = _parse_numeric_runtime_fingerprint(health_body)
    opencv_major = runtime_fingerprint["opencv_major"]
    if opencv_major != expected_opencv_major:
        raise PreflightError(
            "opencv_major_drift",
            f"service OpenCV major {opencv_major} != configured {expected_opencv_major}",
        )
    if opencv_major != 5:
        raise PreflightError("opencv_major_unsupported", f"service OpenCV major {opencv_major} is not 5")
    return PreflightResult(
        stack_id=endpoint.stack_id,
        base_url=endpoint.base_url,
        expected_profile=endpoint.expected_profile,
        expected_pgvector_dim=endpoint.expected_pgvector_dim,
        resolved_profile=profile,
        resolved_pgvector_dim=dim,
        opencv_major=opencv_major,
        opencv_major_source="service_reported",
        checked_at=datetime.now(UTC).isoformat(),
        ready_excerpt=_excerpt(ready_body),
        health_detailed_excerpt=_excerpt(health_body),
    )


def preflight_pair(
    pair: StackPairConfig,
    *,
    out_dir: Path | None = None,
    transports: dict[str, httpx.BaseTransport] | None = None,
    api_keys: dict[str, str] | None = None,
) -> dict[str, PreflightResult]:
    results: dict[str, PreflightResult] = {}
    for endpoint in pair.stacks:
        transport = (transports or {}).get(endpoint.stack_id)
        key = (api_keys or {}).get(endpoint.stack_id)
        results[endpoint.stack_id] = preflight_stack(endpoint, transport=transport, api_key=key)
    if out_dir is not None:
        for stack_id, result in results.items():
            dest = Path(out_dir) / stack_id / "preflight.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_preflight_json(dest, result)
    return results


def write_preflight_json(path: Path | str, result: PreflightResult) -> None:
    Path(path).write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")


def _get_json(client: httpx.Client, url: str, *, auth: bool) -> dict[str, Any]:
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise PreflightError("preflight_endpoint_missing", f"{url} unreachable: {exc}") from exc
    if response.status_code in {401, 403}:
        raise PreflightError("preflight_auth_failed", f"{url} returned {response.status_code}")
    if response.status_code == 404 or response.status_code >= 500:
        raise PreflightError("preflight_endpoint_missing", f"{url} returned {response.status_code}")
    if response.status_code >= 400:
        raise PreflightError("preflight_endpoint_missing", f"{url} returned {response.status_code}")
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise PreflightError("profile_or_dim_drift", f"{url} returned non-JSON") from exc
    if not isinstance(body, dict):
        raise PreflightError("profile_or_dim_drift", f"{url} expected object")
    return body


def _parse_ready_dim(body: dict[str, Any], expected: int) -> int:
    checks = body.get("checks")
    if not isinstance(checks, list):
        raise PreflightError("profile_or_dim_drift", "/ready missing checks")
    database = next((c for c in checks if isinstance(c, dict) and c.get("name") == "database"), None)
    if database is None:
        raise PreflightError("profile_or_dim_drift", "/ready missing database check")
    status = str(database.get("status", "")).lower()
    if status != "ok":
        raise PreflightError("profile_or_dim_drift", f"database check status {status!r} is not ok")
    detail = str(database.get("detail", ""))
    match = _DIM_TOKEN.search(detail)
    if not match:
        raise PreflightError("profile_or_dim_drift", "pgvector_dimension token absent from database detail")
    dim = int(match.group(1))
    if dim != expected:
        raise PreflightError("profile_or_dim_drift", f"pgvector dim {dim} != expected {expected}")
    return dim


def _parse_health_profile(body: dict[str, Any], expected: str) -> str:
    cache = body.get("model_cache")
    if not isinstance(cache, dict):
        raise PreflightError("profile_or_dim_drift", "model_cache missing")
    profile = cache.get("profile")
    if not isinstance(profile, str) or not profile:
        raise PreflightError("profile_or_dim_drift", "model_cache.profile missing")
    if profile != expected:
        raise PreflightError("profile_or_dim_drift", f"profile {profile!r} != expected {expected!r}")
    return profile


def _parse_model_bundle_provenance(body: dict[str, Any]) -> None:
    """Require the service to attest which model bundle is active and hash it."""
    cache = body.get("model_cache")
    if not isinstance(cache, dict):
        raise PreflightError("model_bundle_unreported", "model_cache missing from detailed health")
    model_name = cache.get("model_name")
    bundle_files = cache.get("bundle_files")
    bundle_sha256 = cache.get("bundle_sha256")
    if not isinstance(model_name, str) or not model_name.strip():
        raise PreflightError("model_bundle_unreported", "model_cache.model_name missing from detailed health")
    if type(bundle_files) is not int or bundle_files <= 0:
        raise PreflightError("model_bundle_unreported", "model_cache.bundle_files is missing or empty")
    if not isinstance(bundle_sha256, str) or _SHA256.fullmatch(bundle_sha256) is None:
        raise PreflightError("model_bundle_unreported", "model_cache.bundle_sha256 is missing or invalid")


def _parse_numeric_runtime_fingerprint(body: dict[str, Any]) -> dict[str, Any]:
    """Read the service-reported canonical runtime fingerprint from health."""
    cache = body.get("model_cache")
    if not isinstance(cache, dict):
        raise PreflightError("opencv_runtime_unreported", "model_cache missing from detailed health")
    detail = cache.get("detail")
    if not isinstance(detail, str):
        raise PreflightError("opencv_runtime_unreported", "model_cache.detail missing from detailed health")
    match = _RUNTIME_FINGERPRINT_TOKEN.search(detail)
    if match is None:
        raise PreflightError("opencv_runtime_unreported", "numeric runtime fingerprint missing from detailed health")
    try:
        fingerprint = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PreflightError("opencv_runtime_unreported", "numeric runtime fingerprint is invalid JSON") from exc
    if not isinstance(fingerprint, dict):
        raise PreflightError("opencv_runtime_unreported", "numeric runtime fingerprint must be an object")
    required = ("opencv_version", "opencv_major", "onnxruntime_version", "numpy_version")
    if any(key not in fingerprint for key in required):
        raise PreflightError("opencv_runtime_unreported", "numeric runtime fingerprint is incomplete")
    if any(not isinstance(fingerprint[key], str) or not fingerprint[key] for key in required if key != "opencv_major"):
        raise PreflightError("opencv_runtime_unreported", "numeric runtime fingerprint has an invalid version")
    major = fingerprint["opencv_major"]
    if type(major) is not int or major <= 0:
        raise PreflightError("opencv_runtime_unreported", "numeric runtime fingerprint has an invalid OpenCV major")
    version_major = fingerprint["opencv_version"].split(".", 1)[0]
    if not version_major.isdecimal() or int(version_major) != major:
        raise PreflightError("opencv_runtime_unreported", "OpenCV version and major do not match")
    return fingerprint


def _excerpt(body: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(body))
    for secret_key in ("api_key", "authorization", "token", "secret"):
        if secret_key in redacted:
            redacted[secret_key] = "[redacted]"
    return redacted
