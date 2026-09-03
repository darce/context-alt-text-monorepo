#!/usr/bin/env python3
"""GPU spike bench for VLM-3B Slice 7a — cold boot, warm-start, throughput.

Captures E19-1 ``acx-gpu-spike/v1`` measurement fields for an explicitly
identified model and hardware configuration. Live OCI/GPU runs are operator-
gated; unit tests inject fake actuator/clock/http seams and never touch the
network [TEST-01].

Heuristics applied:
- [PERF-01] report p50/p95 percentiles for warm-start and s/img (not means alone)
- [RES-07] always STOP + wait STOPPED on exit so the instance is never left RUNNING
- [RLSE-05] phase failures exit non-zero and name the failed phase
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

DEFAULT_WARM_START_RUNS = 5
WARM_START_P95_TARGET_SECONDS = 90.0
LIVE_MEASUREMENT_SOURCE = "live_oci_gpu_spike_bench"
ARTIFACT_STATUS_MEASURED = "live_oci_measurement_complete"
ARTIFACT_STATUS_PENDING = "local_infra_scaffold_pending_live_oci_measurement"
SCHEMA = "acx-gpu-spike/v1"
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_LIFECYCLE_TIMEOUT_S = 900.0
DEFAULT_ENDPOINT_READY_TIMEOUT_S = 900.0
DEFAULT_OCI_TIMEOUT_SECONDS = 660
LIVE_CONFIRMATION_ENV = "ACX_GPU_BENCH_LIVE"
LIVE_CONFIRMATION_TOKEN = "I-UNDERSTAND-THIS-COSTS-MONEY"
SYSTEM_PROMPT = (
    "You write alt text for images. Describe only what is visible, in 1-2 "
    "plain sentences."
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BenchError(Exception):
    """Base bench failure."""


class PhaseError(BenchError):
    """Named phase failure — exit non-zero and name the phase [RLSE-05]."""

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(f"phase {phase} failed: {message}")


# ---------------------------------------------------------------------------
# Injectable seams
# ---------------------------------------------------------------------------


class InstanceActuator(Protocol):
    def verify_bench_dedicated(self, instance_id: str, expected_tag: str) -> None: ...

    def start(self, instance_id: str) -> None: ...

    def stop(self, instance_id: str) -> None: ...

    def get_lifecycle_state(self, instance_id: str) -> str: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.body.decode() if self.body else "null")


class HttpClient(Protocol):
    def get(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> HttpResponse: ...

    def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class UrlLibHttpClient:
    """Minimal stdlib HTTP client (no live use in unit tests)."""

    def __init__(self, *, timeout_seconds: float = 180.0) -> None:
        self._timeout = timeout_seconds

    def get(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> HttpResponse:
        req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        return self._open(req)

    def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        data = json.dumps(json_body).encode()
        hdrs = {"Content-Type": "application/json", **dict(headers or {})}
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        return self._open(req)

    def _open(self, req: urllib.request.Request) -> HttpResponse:
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return HttpResponse(
                    status_code=getattr(resp, "status", 200),
                    body=resp.read(),
                    headers=dict(resp.headers.items()) if resp.headers else {},
                )
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            return HttpResponse(status_code=exc.code, body=body)
        except urllib.error.URLError as exc:
            raise BenchError(f"HTTP request failed: {exc}") from exc
        except OSError as exc:
            # ConnectionResetError/ConnectionRefused (errno 54/61) — the endpoint is
            # down (booting, or mid STOP->START warm-start), or a tunnel reset the
            # socket. Treat as a transport failure so endpoint_ready() retries instead
            # of crashing the phase. [RES-06]
            raise BenchError(f"HTTP transport error: {exc}") from exc


class OciCliInstanceActuator:
    """START/STOP/get-lifecycle-state via OCI CLI (mirrors OciCliStopActuator)."""

    def __init__(
        self,
        *,
        oci_bin: str | None = None,
        auth: str | None = None,
        timeout_seconds: int = DEFAULT_OCI_TIMEOUT_SECONDS,
        wait_for_state: bool = False,
    ) -> None:
        self._oci_bin = oci_bin or shutil.which("oci") or "oci"
        self._auth = auth
        self._timeout_seconds = timeout_seconds
        # Bench polls lifecycle itself so default is fire-and-return without CLI wait.
        self._wait_for_state = wait_for_state

    def start(self, instance_id: str) -> None:
        self._action(instance_id, "START", wait_state="RUNNING")

    def stop(self, instance_id: str) -> None:
        self._action(instance_id, "STOP", wait_state="STOPPED")

    def get_lifecycle_state(self, instance_id: str) -> str:
        data = self._get_instance_data(instance_id)
        state = data.get("lifecycle-state") or data.get("lifecycle_state") or "UNKNOWN"
        return str(state).upper()

    def verify_bench_dedicated(self, instance_id: str, expected_tag: str) -> None:
        key, separator, expected_value = expected_tag.partition("=")
        if not separator or not key or not expected_value:
            raise BenchError("bench-dedicated tag must have the form KEY=VALUE")
        data = self._get_instance_data(instance_id)
        tags = data.get("freeform-tags") or data.get("freeform_tags")
        actual_value = tags.get(key) if isinstance(tags, dict) else None
        if actual_value != expected_value:
            raise BenchError(
                f"instance {instance_id} is not bench-dedicated: expected freeform tag "
                f"{key}={expected_value}"
            )

    def _get_instance_data(self, instance_id: str) -> dict[str, Any]:
        cmd = [
            self._oci_bin,
            "compute",
            "instance",
            "get",
            "--instance-id",
            instance_id,
            "--output",
            "json",
        ]
        if self._auth:
            cmd.extend(["--auth", self._auth])
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        payload = json.loads(proc.stdout)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise BenchError(
                f"oci instance get returned unexpected payload for {instance_id}"
            )
        return data

    def _action(self, instance_id: str, action: str, *, wait_state: str) -> None:
        cmd = [
            self._oci_bin,
            "compute",
            "instance",
            "action",
            "--instance-id",
            instance_id,
            "--action",
            action,
        ]
        if self._wait_for_state:
            cmd.extend(["--wait-for-state", wait_state, "--max-wait-seconds", "600"])
        if self._auth:
            cmd.extend(["--auth", self._auth])
        subprocess.run(cmd, check=True, timeout=self._timeout_seconds)


# ---------------------------------------------------------------------------
# Stats [PERF-01]
# ---------------------------------------------------------------------------


def percentile(samples: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile; ``p`` in [0, 100]."""
    if not samples:
        raise ValueError("percentile requires at least one sample")
    if p < 0 or p > 100:
        raise ValueError(f"percentile p must be in [0, 100], got {p}")
    ordered = sorted(float(s) for s in samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def mean(samples: Sequence[float]) -> float:
    if not samples:
        raise ValueError("mean requires at least one sample")
    return sum(float(s) for s in samples) / len(samples)


# ---------------------------------------------------------------------------
# Endpoint helpers (OpenAI-compatible contract, mirrors gpu_remote_adapter)
# ---------------------------------------------------------------------------


def _media_type(path: Path, raw: bytes) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "application/octet-stream"


def build_chat_completions_payload(
    *,
    model_id: str,
    image_bytes: bytes,
    media_type: str,
    user_text: str = "Describe this image for alt text.",
) -> dict[str, Any]:
    data_uri = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"
    return {
        "model": model_id,
        "temperature": 0,
        "max_tokens": 128,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
    }


def endpoint_ready(
    http: HttpClient,
    endpoint_url: str,
    *,
    model_id: str,
    api_key: str | None = None,
) -> bool:
    """True only when the endpoint identifies the requested model."""
    base = endpoint_url.rstrip("/")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        models = http.get(f"{base}/v1/models", headers=headers or None)
        if 200 <= models.status_code < 300:
            payload = models.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                return False
            return any(
                isinstance(item, dict) and item.get("id") == model_id for item in data
            )
    except BenchError:
        pass
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    # Minimal text-only completion as fallback readiness probe.
    payload = {
        "model": model_id,
        "temperature": 0,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "ping"}],
    }
    try:
        resp = http.post(
            f"{base}/v1/chat/completions", json_body=payload, headers=headers or None
        )
        if not (200 <= resp.status_code < 300):
            return False
        completion = resp.json()
        return isinstance(completion, dict) and completion.get("model") == model_id
    except BenchError:
        return False
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


# ---------------------------------------------------------------------------
# Lifecycle polling
# ---------------------------------------------------------------------------


def wait_for_lifecycle(
    actuator: InstanceActuator,
    instance_id: str,
    desired: str,
    *,
    clock: Clock,
    timeout_seconds: float = DEFAULT_LIFECYCLE_TIMEOUT_S,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_S,
) -> float:
    """Poll until lifecycle state matches ``desired``. Returns elapsed seconds."""
    desired_u = desired.upper()
    t0 = clock.monotonic()
    while True:
        state = actuator.get_lifecycle_state(instance_id).upper()
        if state == desired_u:
            return clock.monotonic() - t0
        if clock.monotonic() - t0 >= timeout_seconds:
            raise PhaseError(
                "lifecycle_poll",
                f"timeout waiting for {desired_u} (last state={state}, "
                f"timeout={timeout_seconds}s)",
            )
        clock.sleep(poll_interval_seconds)


def wait_for_endpoint_ready(
    http: HttpClient,
    endpoint_url: str,
    *,
    model_id: str,
    clock: Clock,
    api_key: str | None = None,
    timeout_seconds: float = DEFAULT_ENDPOINT_READY_TIMEOUT_S,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_S,
) -> float:
    t0 = clock.monotonic()
    while True:
        if endpoint_ready(http, endpoint_url, model_id=model_id, api_key=api_key):
            return clock.monotonic() - t0
        if clock.monotonic() - t0 >= timeout_seconds:
            raise PhaseError(
                "endpoint_ready",
                f"timeout waiting for endpoint readiness at {endpoint_url} "
                f"(timeout={timeout_seconds}s)",
            )
        clock.sleep(poll_interval_seconds)


def ensure_stopped(
    actuator: InstanceActuator,
    instance_id: str,
    *,
    clock: Clock,
    timeout_seconds: float = DEFAULT_LIFECYCLE_TIMEOUT_S,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """STOP and wait STOPPED — billing safety [RES-07]."""
    try:
        state = actuator.get_lifecycle_state(instance_id).upper()
    except Exception:  # noqa: BLE001 - best-effort stop path
        state = "UNKNOWN"
    stop_error: Exception | None = None
    if state != "STOPPED":
        try:
            actuator.stop(instance_id)
        except Exception as exc:  # noqa: BLE001
            # Still attempt to poll in case stop partially applied.
            stop_error = exc
            sys.stderr.write(f"ensure_stopped: stop() raised: {exc}\n")
    try:
        wait_for_lifecycle(
            actuator,
            instance_id,
            "STOPPED",
            clock=clock,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as poll_error:
        if stop_error is not None:
            raise BenchError(
                f"STOP request failed ({stop_error}); STOPPED verification also failed "
                f"({poll_error})"
            ) from poll_error
        raise
    if stop_error is not None:
        raise BenchError(
            f"STOP request failed before STOPPED verification: {stop_error}"
        )


# ---------------------------------------------------------------------------
# Bench phases
# ---------------------------------------------------------------------------


@dataclass
class ColdBootResult:
    cold_boot_seconds: float
    model_load_seconds: float
    instance_running_seconds: float
    endpoint_ready_seconds: float


@dataclass
class WarmStartResult:
    samples: list[float]
    shutdown_samples: list[float]
    p50: float
    p95: float
    meets_target: bool
    target_seconds: float = WARM_START_P95_TARGET_SECONDS


@dataclass
class ThroughputResult:
    samples: list[float]
    p50: float
    p95: float
    mean: float


@dataclass
class BenchResult:
    cold_boot: ColdBootResult
    warm_start: WarmStartResult
    throughput: ThroughputResult
    model_id: str
    instance_ocid: str
    endpoint_url: str
    warm_start_meets_target: bool


def run_cold_boot(
    *,
    actuator: InstanceActuator,
    http: HttpClient,
    clock: Clock,
    instance_id: str,
    endpoint_url: str,
    model_id: str,
    api_key: str | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_S,
    lifecycle_timeout_seconds: float = DEFAULT_LIFECYCLE_TIMEOUT_S,
    endpoint_timeout_seconds: float = DEFAULT_ENDPOINT_READY_TIMEOUT_S,
) -> ColdBootResult:
    """START from STOPPED → RUNNING → endpoint ready [cold_boot + model_load]."""
    try:
        state = actuator.get_lifecycle_state(instance_id).upper()
        if state != "STOPPED":
            ensure_stopped(
                actuator,
                instance_id,
                clock=clock,
                timeout_seconds=lifecycle_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        t0 = clock.monotonic()
        actuator.start(instance_id)
        wait_for_lifecycle(
            actuator,
            instance_id,
            "RUNNING",
            clock=clock,
            timeout_seconds=lifecycle_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        t_running = clock.monotonic()
        wait_for_endpoint_ready(
            http,
            endpoint_url,
            model_id=model_id,
            clock=clock,
            api_key=api_key,
            timeout_seconds=endpoint_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        t_ready = clock.monotonic()
        return ColdBootResult(
            cold_boot_seconds=t_ready - t0,
            model_load_seconds=t_ready - t_running,
            instance_running_seconds=t_running - t0,
            endpoint_ready_seconds=t_ready - t_running,
        )
    except PhaseError:
        raise
    except Exception as exc:
        raise PhaseError("cold_boot", str(exc)) from exc


def run_warm_start_loop(
    *,
    actuator: InstanceActuator,
    http: HttpClient,
    clock: Clock,
    instance_id: str,
    endpoint_url: str,
    model_id: str,
    runs: int,
    api_key: str | None = None,
    target_seconds: float = WARM_START_P95_TARGET_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_S,
    lifecycle_timeout_seconds: float = DEFAULT_LIFECYCLE_TIMEOUT_S,
    endpoint_timeout_seconds: float = DEFAULT_ENDPOINT_READY_TIMEOUT_S,
) -> WarmStartResult:
    """STOP→STOPPED→START→endpoint-ready, repeated; report p50/p95 [PERF-01]."""
    if runs < 1:
        raise PhaseError("warm_start", f"warm-start-runs must be >= 1, got {runs}")
    samples: list[float] = []
    shutdown_samples: list[float] = []
    try:
        for i in range(runs):
            shutdown_started = clock.monotonic()
            actuator.stop(instance_id)
            wait_for_lifecycle(
                actuator,
                instance_id,
                "STOPPED",
                clock=clock,
                timeout_seconds=lifecycle_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            shutdown_samples.append(clock.monotonic() - shutdown_started)
            t0 = clock.monotonic()
            actuator.start(instance_id)
            wait_for_lifecycle(
                actuator,
                instance_id,
                "RUNNING",
                clock=clock,
                timeout_seconds=lifecycle_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            wait_for_endpoint_ready(
                http,
                endpoint_url,
                model_id=model_id,
                clock=clock,
                api_key=api_key,
                timeout_seconds=endpoint_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            samples.append(clock.monotonic() - t0)
            print(
                f"warm-start run {i + 1}/{runs}: {samples[-1]:.3f}s "
                f"(shutdown={shutdown_samples[-1]:.3f}s)",
                flush=True,
            )
        p50 = percentile(samples, 50)
        p95 = percentile(samples, 95)
        meets = p95 <= target_seconds
        return WarmStartResult(
            samples=samples,
            shutdown_samples=shutdown_samples,
            p50=p50,
            p95=p95,
            meets_target=meets,
            target_seconds=target_seconds,
        )
    except PhaseError:
        raise
    except Exception as exc:
        raise PhaseError("warm_start", str(exc)) from exc


def run_throughput(
    *,
    http: HttpClient,
    clock: Clock,
    endpoint_url: str,
    model_id: str,
    image_paths: Sequence[Path],
    api_key: str | None = None,
) -> ThroughputResult:
    """POST each image through /v1/chat/completions; s/img p50/p95/mean [PERF-01]."""
    if not image_paths:
        raise PhaseError(
            "throughput", "at least one --image is required for throughput phase"
        )
    base = endpoint_url.rstrip("/")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    samples: list[float] = []
    try:
        for path in image_paths:
            raw = path.read_bytes()
            media = _media_type(path, raw)
            payload = build_chat_completions_payload(
                model_id=model_id,
                image_bytes=raw,
                media_type=media,
            )
            t0 = clock.monotonic()
            resp = http.post(
                f"{base}/v1/chat/completions",
                json_body=payload,
                headers=headers or None,
            )
            elapsed = clock.monotonic() - t0
            if not (200 <= resp.status_code < 300):
                raise PhaseError(
                    "throughput",
                    f"chat/completions HTTP {resp.status_code} for {path}",
                )
            try:
                completion = resp.json()
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PhaseError(
                    "throughput", f"invalid completion JSON for {path}: {exc}"
                ) from exc
            if not isinstance(completion, dict):
                raise PhaseError(
                    "throughput", f"invalid completion envelope for {path}"
                )
            response_model = completion.get("model")
            if response_model is not None and response_model != model_id:
                raise PhaseError(
                    "throughput",
                    f"completion model mismatch for {path}: expected {model_id}",
                )
            choices = completion.get("choices")
            first_choice = choices[0] if isinstance(choices, list) and choices else None
            message = (
                first_choice.get("message") if isinstance(first_choice, dict) else None
            )
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise PhaseError(
                    "throughput", f"completion content is empty or missing for {path}"
                )
            samples.append(elapsed)
            print(f"throughput {path.name}: {elapsed:.3f}s", flush=True)
        return ThroughputResult(
            samples=samples,
            p50=percentile(samples, 50),
            p95=percentile(samples, 95),
            mean=mean(samples),
        )
    except PhaseError:
        raise
    except Exception as exc:
        raise PhaseError("throughput", str(exc)) from exc


# ---------------------------------------------------------------------------
# Artifact emission
# ---------------------------------------------------------------------------


def default_artifact_path(*, today: date | None = None) -> Path:
    d = today or datetime.now(UTC).date()
    return Path("docs/tasks/vlm") / f"VLM-3-gpu-spike-{d.isoformat()}.json"


def build_spike_artifact(
    *,
    cold_boot: ColdBootResult,
    warm_start: WarmStartResult,
    throughput: ThroughputResult,
    model_id: str,
    shape: str,
    quantization: str,
    model_path: str,
    boot_volume_gb: int,
    vpus_per_gb: int,
    a10_quota_confirmed: bool = False,
    a100_or_l40s_headroom_confirmed: bool = False,
    serverless_gpu_available: bool = False,
    recorded_at: str | None = None,
    task_ref: str = "VLM-3",
) -> dict[str, Any]:
    """Fill acx-gpu-spike/v1 with zero null measurement values; flip status."""
    stamp = recorded_at or datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    return {
        "schema": SCHEMA,
        "task_ref": task_ref,
        "recorded_at": stamp,
        "status": ARTIFACT_STATUS_MEASURED,
        "shape": shape,
        "boot_volume_size_in_gbs": boot_volume_gb,
        "boot_volume_vpus_per_gb": vpus_per_gb,
        "measurement_candidate": {
            "model_id": model_id,
            "quantization": quantization,
            "model_path": model_path,
        },
        "measurements": {
            "cold_boot_seconds": {
                "value": cold_boot.cold_boot_seconds,
                "source": LIVE_MEASUREMENT_SOURCE,
            },
            "stopped_to_warm_start_seconds": {
                "value": warm_start.p50,
                "p50": warm_start.p50,
                "p95": warm_start.p95,
                "samples": list(warm_start.samples),
                "source": LIVE_MEASUREMENT_SOURCE,
            },
            "warm_start_p95_seconds": {
                "value": warm_start.p95,
                "target_seconds": warm_start.target_seconds,
                "meets_target": warm_start.meets_target,
                "samples": list(warm_start.samples),
                "source": LIVE_MEASUREMENT_SOURCE,
            },
            "shutdown_seconds": {
                "value": percentile(warm_start.shutdown_samples, 50),
                "p50": percentile(warm_start.shutdown_samples, 50),
                "p95": percentile(warm_start.shutdown_samples, 95),
                "samples": list(warm_start.shutdown_samples),
                "source": LIVE_MEASUREMENT_SOURCE,
            },
            "model_load_seconds": {
                "value": cold_boot.model_load_seconds,
                "source": LIVE_MEASUREMENT_SOURCE,
            },
            "seconds_per_image": {
                "value": throughput.p50,
                "p50": throughput.p50,
                "p95": throughput.p95,
                "mean": throughput.mean,
                "samples": list(throughput.samples),
                "sample_size_note": (
                    "n=1 image"
                    if len(throughput.samples) == 1
                    else f"n={len(throughput.samples)} images"
                ),
                "source": LIVE_MEASUREMENT_SOURCE,
            },
        },
        "oci_capacity": {
            "a10_quota_confirmed": a10_quota_confirmed,
            "a100_or_l40s_headroom_confirmed": a100_or_l40s_headroom_confirmed,
            "serverless_gpu_available": serverless_gpu_available,
            "source": (
                "operator_cli_flag"
                if any(
                    (
                        a10_quota_confirmed,
                        a100_or_l40s_headroom_confirmed,
                        serverless_gpu_available,
                    )
                )
                else "pending_operator_oci_console_or_cli_check"
            ),
        },
        "terraform": {
            "gpu_resource": "oci_core_instance.acx_gpu_burst",
            "gpu_shape_variable": "gpu_shape",
            "validate_command": "cd infra/oci && terraform validate",
        },
        "notes": [
            "Artifact produced by scripts/gpu_spike_bench.py (VLM-3B Slice 7a).",
            "Warm-start reports p50/p95 percentiles, not means [PERF-01].",
            "Shutdown time is recorded separately and excluded from warm-start samples.",
            (
                f"Warm-start p95 target {warm_start.target_seconds}s: "
                f"{'PASS' if warm_start.meets_target else 'FAIL'} "
                f"(p95={warm_start.p95:.3f}s)."
            ),
        ],
    }


def write_artifact(path: Path, artifact: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")


def assert_no_null_measurement_values(artifact: Mapping[str, Any]) -> None:
    measurements = artifact.get("measurements")
    if not isinstance(measurements, dict):
        raise BenchError("artifact missing measurements object")
    for key, body in measurements.items():
        if not isinstance(body, dict):
            raise BenchError(f"measurement {key} is not an object")
        if body.get("value") is None:
            raise BenchError(f"measurement {key}.value is null")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_bench(
    *,
    instance_ocid: str,
    endpoint_url: str,
    model_id: str,
    image_paths: Sequence[Path],
    warm_start_runs: int,
    actuator: InstanceActuator,
    http: HttpClient,
    clock: Clock,
    artifact_out: Path,
    boot_volume_gb: int,
    vpus_per_gb: int,
    shape: str,
    quantization: str,
    model_path: str,
    bench_dedicated_tag: str,
    a10_quota_confirmed: bool = False,
    a100_or_l40s_headroom_confirmed: bool = False,
    serverless_gpu_available: bool = False,
    api_key: str | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_S,
    lifecycle_timeout_seconds: float = DEFAULT_LIFECYCLE_TIMEOUT_S,
    endpoint_timeout_seconds: float = DEFAULT_ENDPOINT_READY_TIMEOUT_S,
    on_phase: Callable[[str], None] | None = None,
) -> BenchResult:
    """Run all phases; always STOP in ``finally`` after the dedicated-host gate."""
    cold: ColdBootResult | None = None
    warm: WarmStartResult | None = None
    thruput: ThroughputResult | None = None
    prepared_artifact: dict[str, Any] | None = None
    active_phase = "setup"

    def _mark(phase: str) -> None:
        nonlocal active_phase
        active_phase = phase
        if on_phase is not None:
            on_phase(phase)

    _mark("dedicated_instance_check")
    try:
        actuator.verify_bench_dedicated(instance_ocid, bench_dedicated_tag)
    except Exception as exc:
        raise PhaseError("dedicated_instance_check", str(exc)) from exc

    try:
        _mark("cold_boot")
        cold = run_cold_boot(
            actuator=actuator,
            http=http,
            clock=clock,
            instance_id=instance_ocid,
            endpoint_url=endpoint_url,
            model_id=model_id,
            api_key=api_key,
            poll_interval_seconds=poll_interval_seconds,
            lifecycle_timeout_seconds=lifecycle_timeout_seconds,
            endpoint_timeout_seconds=endpoint_timeout_seconds,
        )
        print(
            f"cold_boot: {cold.cold_boot_seconds:.3f}s "
            f"(model_load={cold.model_load_seconds:.3f}s)",
            flush=True,
        )

        _mark("warm_start")
        warm = run_warm_start_loop(
            actuator=actuator,
            http=http,
            clock=clock,
            instance_id=instance_ocid,
            endpoint_url=endpoint_url,
            model_id=model_id,
            runs=warm_start_runs,
            api_key=api_key,
            poll_interval_seconds=poll_interval_seconds,
            lifecycle_timeout_seconds=lifecycle_timeout_seconds,
            endpoint_timeout_seconds=endpoint_timeout_seconds,
        )
        verdict = "PASS" if warm.meets_target else "FAIL"
        print(
            f"warm_start: p50={warm.p50:.3f}s p95={warm.p95:.3f}s "
            f"target={warm.target_seconds}s → {verdict}",
            flush=True,
        )

        _mark("throughput")
        thruput = run_throughput(
            http=http,
            clock=clock,
            endpoint_url=endpoint_url,
            model_id=model_id,
            image_paths=image_paths,
            api_key=api_key,
        )
        print(
            f"throughput: p50={thruput.p50:.3f}s p95={thruput.p95:.3f}s "
            f"mean={thruput.mean:.3f}s (n={len(thruput.samples)})",
            flush=True,
        )

        _mark("artifact_prepare")
        artifact = build_spike_artifact(
            cold_boot=cold,
            warm_start=warm,
            throughput=thruput,
            model_id=model_id,
            shape=shape,
            quantization=quantization,
            model_path=model_path,
            boot_volume_gb=boot_volume_gb,
            vpus_per_gb=vpus_per_gb,
            a10_quota_confirmed=a10_quota_confirmed,
            a100_or_l40s_headroom_confirmed=a100_or_l40s_headroom_confirmed,
            serverless_gpu_available=serverless_gpu_available,
        )
        assert_no_null_measurement_values(artifact)
        prepared_artifact = artifact

        return BenchResult(
            cold_boot=cold,
            warm_start=warm,
            throughput=thruput,
            model_id=model_id,
            instance_ocid=instance_ocid,
            endpoint_url=endpoint_url,
            warm_start_meets_target=warm.meets_target,
        )
    except PhaseError:
        raise
    except Exception as exc:
        raise PhaseError(active_phase, str(exc)) from exc
    finally:
        # Billing safety: never leave the instance RUNNING [RES-07].
        try:
            ensure_stopped(
                actuator,
                instance_ocid,
                clock=clock,
                timeout_seconds=lifecycle_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            print("finally: instance STOPPED", flush=True)
        except Exception as stop_exc:
            sys.stderr.write(f"finally STOP failed: {stop_exc}\n")
            raise PhaseError("cleanup", str(stop_exc)) from stop_exc

        # A measured artifact is complete only after billing-safe STOPPED is proven.
        if prepared_artifact is not None:
            try:
                _mark("artifact_write")
                write_artifact(artifact_out, prepared_artifact)
                print(f"artifact written: {artifact_out}", flush=True)
            except PhaseError:
                raise
            except Exception as artifact_exc:
                raise PhaseError("artifact_write", str(artifact_exc)) from artifact_exc


def dry_run_plan(
    *,
    instance_ocid: str,
    endpoint_url: str,
    model_id: str | None,
    image_paths: Sequence[Path],
    warm_start_runs: int,
    artifact_out: Path,
    a10_quota_confirmed: bool,
    a100_or_l40s_headroom_confirmed: bool,
    serverless_gpu_available: bool,
    boot_volume_gb: int | None,
    vpus_per_gb: int | None,
    shape: str | None,
    quantization: str | None,
    model_path: str | None,
    bench_dedicated_tag: str | None,
) -> dict[str, Any]:
    plan = {
        "mode": "dry-run",
        "instance_ocid": instance_ocid,
        "endpoint_url": endpoint_url,
        "model_id": model_id,
        "warm_start_runs": warm_start_runs,
        "images": [str(p) for p in image_paths],
        "artifact_out": str(artifact_out),
        "boot_volume_gb": boot_volume_gb,
        "vpus_per_gb": vpus_per_gb,
        "shape": shape,
        "quantization": quantization,
        "model_path": model_path,
        "bench_dedicated_tag": bench_dedicated_tag,
        "phases": [
            "cold_boot: START from STOPPED → poll RUNNING → poll endpoint ready",
            (
                "warm_start: STOP→STOPPED (shutdown separate), then START→ready × "
                f"{warm_start_runs} (p50/p95 vs {WARM_START_P95_TARGET_SECONDS}s)"
            ),
            "throughput: POST /v1/chat/completions per --image",
            "artifact_write: fill acx-gpu-spike/v1 measurements, flip status",
            "finally: STOP + wait STOPPED [RES-07]",
        ],
        "oci_capacity_flags": {
            "a10_quota_confirmed": a10_quota_confirmed,
            "a100_or_l40s_headroom_confirmed": a100_or_l40s_headroom_confirmed,
            "serverless_gpu_available": serverless_gpu_available,
        },
        "touches_oci": False,
        "touches_endpoint": False,
    }
    print(json.dumps(plan, indent=2))
    return plan


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpu_spike_bench",
        description=(
            "VLM-3B GPU spike bench: cold boot, warm-start p50/p95, model load, "
            "seconds/image. Emits acx-gpu-spike/v1 JSON. Dry-run is the default; "
            "live operation requires --live plus an environment confirmation."
        ),
    )
    parser.add_argument(
        "--instance-ocid",
        required=True,
        help="OCI instance OCID for acx_gpu_burst",
    )
    parser.add_argument(
        "--endpoint-url",
        required=True,
        help="GPU VLM base URL (e.g. http://10.0.x.x:8000)",
    )
    parser.add_argument(
        "--artifact-out",
        type=Path,
        default=None,
        help=(
            "Output path for spike artifact JSON "
            "(default: docs/tasks/vlm/VLM-3-gpu-spike-<YYYY-MM-DD>.json)"
        ),
    )
    parser.add_argument(
        "--warm-start-runs",
        type=int,
        default=DEFAULT_WARM_START_RUNS,
        help=f"Number of STOP→START warm-start samples (default {DEFAULT_WARM_START_RUNS})",
    )
    parser.add_argument(
        "--boot-volume-gb",
        type=int,
        default=None,
        help="Live-run boot-volume size in GB (required unless --dry-run)",
    )
    parser.add_argument(
        "--vpus-per-gb",
        type=int,
        default=None,
        help="Live-run boot-volume performance in VPU/GB (required unless --dry-run)",
    )
    parser.add_argument(
        "--shape",
        default=None,
        help="Live-run OCI shape recorded in the artifact (required with --live)",
    )
    parser.add_argument(
        "--quantization",
        default=None,
        help="Live-run model quantization recorded in the artifact (required with --live)",
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help="Live-run served model path recorded in the artifact (required with --live)",
    )
    parser.add_argument(
        "--bench-dedicated-tag",
        default=None,
        metavar="KEY=VALUE",
        help=(
            "Expected OCI freeform tag proving the instance is bench-dedicated "
            "(required with --live)"
        ),
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="images",
        help="Image path for throughput phase (repeatable)",
    )
    parser.add_argument(
        "--model-id",
        default=None,
        help="Model id sent to the endpoint and recorded in the artifact (required with --live)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional Bearer token for the GPU endpoint",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the execution plan without OCI/endpoint calls (default)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help=(
            "Permit live OCI/endpoint operations when the environment confirmation "
            "is also set"
        ),
    )
    parser.add_argument(
        "--a10-quota-confirmed",
        action="store_true",
        help="Set oci_capacity.a10_quota_confirmed=true in the artifact",
    )
    parser.add_argument(
        "--a100-or-l40s-headroom-confirmed",
        action="store_true",
        help="Set oci_capacity.a100_or_l40s_headroom_confirmed=true",
    )
    parser.add_argument(
        "--serverless-gpu-available",
        action="store_true",
        help="Set oci_capacity.serverless_gpu_available=true",
    )
    parser.add_argument(
        "--oci-auth",
        default=None,
        help="Optional OCI CLI --auth value (e.g. instance_principal)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_S,
        help=f"Lifecycle/endpoint poll interval seconds (default {DEFAULT_POLL_INTERVAL_S})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    artifact_out = args.artifact_out or default_artifact_path()
    image_paths = [Path(p) for p in args.images]

    if not args.live:
        dry_run_plan(
            instance_ocid=args.instance_ocid,
            endpoint_url=args.endpoint_url,
            model_id=args.model_id,
            image_paths=image_paths,
            warm_start_runs=args.warm_start_runs,
            artifact_out=artifact_out,
            a10_quota_confirmed=args.a10_quota_confirmed,
            a100_or_l40s_headroom_confirmed=args.a100_or_l40s_headroom_confirmed,
            serverless_gpu_available=args.serverless_gpu_available,
            boot_volume_gb=args.boot_volume_gb,
            vpus_per_gb=args.vpus_per_gb,
            shape=args.shape,
            quantization=args.quantization,
            model_path=args.model_path,
            bench_dedicated_tag=args.bench_dedicated_tag,
        )
        return 0

    if os.environ.get(LIVE_CONFIRMATION_ENV) != LIVE_CONFIRMATION_TOKEN:
        parser.error(
            f"--live requires {LIVE_CONFIRMATION_ENV}={LIVE_CONFIRMATION_TOKEN}"
        )
    required_live_inputs = {
        "--model-id": args.model_id,
        "--boot-volume-gb": args.boot_volume_gb,
        "--vpus-per-gb": args.vpus_per_gb,
        "--shape": args.shape,
        "--quantization": args.quantization,
        "--model-path": args.model_path,
        "--bench-dedicated-tag": args.bench_dedicated_tag,
    }
    missing = [flag for flag, value in required_live_inputs.items() if value is None]
    if missing:
        parser.error(f"required for live runs: {', '.join(missing)}")
    assert args.boot_volume_gb is not None
    assert args.vpus_per_gb is not None
    assert args.model_id is not None
    assert args.shape is not None
    assert args.quantization is not None
    assert args.model_path is not None
    assert args.bench_dedicated_tag is not None
    if args.boot_volume_gb <= 0 or args.vpus_per_gb <= 0:
        parser.error("--boot-volume-gb and --vpus-per-gb must be positive")
    if (
        not args.shape.strip()
        or not args.quantization.strip()
        or not args.model_path.strip()
    ):
        parser.error("--shape, --quantization, and --model-path must be non-empty")
    tag_key, separator, tag_value = args.bench_dedicated_tag.partition("=")
    if not separator or not tag_key or not tag_value:
        parser.error("--bench-dedicated-tag must have the form KEY=VALUE")
    if not image_paths:
        parser.error("at least one --image is required (unless --dry-run)")

    actuator = OciCliInstanceActuator(auth=args.oci_auth)
    http = UrlLibHttpClient()
    clock = SystemClock()

    try:
        result = run_bench(
            instance_ocid=args.instance_ocid,
            endpoint_url=args.endpoint_url,
            model_id=args.model_id,
            image_paths=image_paths,
            warm_start_runs=args.warm_start_runs,
            actuator=actuator,
            http=http,
            clock=clock,
            artifact_out=artifact_out,
            boot_volume_gb=args.boot_volume_gb,
            vpus_per_gb=args.vpus_per_gb,
            shape=args.shape,
            quantization=args.quantization,
            model_path=args.model_path,
            bench_dedicated_tag=args.bench_dedicated_tag,
            a10_quota_confirmed=args.a10_quota_confirmed,
            a100_or_l40s_headroom_confirmed=args.a100_or_l40s_headroom_confirmed,
            serverless_gpu_available=args.serverless_gpu_available,
            api_key=args.api_key,
            poll_interval_seconds=args.poll_interval,
        )
    except PhaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except BenchError as exc:
        print(f"bench failed: {exc}", file=sys.stderr)
        return 1

    # Non-zero when warm-start p95 misses the 90s target so CI/ops see FAIL [RLSE-05].
    if not result.warm_start_meets_target:
        print(
            f"warm-start p95 target missed: p95={result.warm_start.p95:.3f}s "
            f"> {WARM_START_P95_TARGET_SECONDS}s",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
