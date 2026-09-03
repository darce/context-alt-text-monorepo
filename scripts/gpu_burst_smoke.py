#!/usr/bin/env python3
"""Prove that a WordPress describe run bursts to GPU and is reaped safely.

The default is a completely offline dry run.  It uses ``httpx.MockTransport``
and an in-memory OCI state machine, but follows the same WordPress REST, polling,
assertion, evidence, and compensating-STOP path as live mode.  Its generated
evidence is written below the ignored ``.workbay/tmp`` tree by default::

    python3 scripts/gpu_burst_smoke.py

Live mode is deliberately awkward to invoke.  Run it only on ``acx-backend`` as
``ubuntu`` (the host with the OCI binary and vaulted key), set the application
password in the environment named by ``--wp-app-password-env``, and acknowledge
the spend guard.  The description-service bearer token is read from the
environment named by ``--service-api-key-env``::

    ACX_GPU_SMOKE_CONFIRM=RUN python3 scripts/gpu_burst_smoke.py --live \
      --wp-base-url https://wordpress.example --wp-user operator \
      --media-ids 101,102 --service-base-url http://<burst-private-ip>:8000 \
      --service-api-key-env ACX_DESCRIPTION_API_KEY \
      --instance-id <burst-instance-ocid> --max-seconds 900

No password is accepted on argv.  Every HTTP/OCI operation has a timeout, every
poll loop checks one overall deadline, and live execution always issues STOP in
``finally`` before it reports success or failure.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import import_module
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = REPO_ROOT / "apps" / "prototype-description-service"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Load the deployment profile after bootstrapping the repo-local service package.
_profiles = import_module("scene.config.profiles")
DescriptionProfile = _profiles.DescriptionProfile
get_profile_spec = _profiles.get_profile_spec
DescribeRunItemResponse = import_module("scene.interface_adapters.http.schemas.responses").DescribeRunItemResponse

EXPECTED_MODEL_ID = "Qwen3-VL-30B-A3B-Instruct"
EXPECTED_PROFILE = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
if EXPECTED_PROFILE.model_id != EXPECTED_MODEL_ID or not EXPECTED_PROFILE.model_revision:
    raise RuntimeError("gpu_qwen30b profile is missing its expected model identity pin")
EXPECTED_REVISION = EXPECTED_PROFILE.model_revision

TERMINAL_RUN_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled"}
SUCCESS_RUN_STATUSES = {"completed"}
TERMINAL_ITEM_STATUSES = {"completed", "failed", "skipped"}
FIXTURE_TOKEN_SETS = (
    "person standing outdoors greenery",
    "plate food wooden table",
    "scenic landscape mountains clear sky",
    "close up small object neutral background",
    "printed document several lines text",
    "two people seated indoors conversation",
    "building exterior seen street",
    "pet animal resting soft surface",
)
OCI_CALL_TIMEOUT_SECONDS = 30.0
HTTP_CALL_TIMEOUT_SECONDS = 15.0
POLL_SECONDS = 2.0
EMERGENCY_STOP_TIMEOUT_SECONDS = 120.0
MAX_EMERGENCY_STOP_ATTEMPTS = 4
MAX_LIVE_SECONDS = 900
GPU_USD_PER_HOUR = 2.0
DEFAULT_EVIDENCE_DIR = ".workbay/tmp/gpu-burst-smoke"
WARM_START_BUDGET_SECONDS = 101
IDLE_REAPER_SECONDS = 300
REAPER_BUDGET_SECONDS = 120
FENCE_BUDGET_SECONDS = 2


class SmokeFailure(RuntimeError):  # noqa: N818 - public smoke contract name
    """The smoke completed far enough to produce failing evidence."""


class PreflightRefusal(RuntimeError):  # noqa: N818 - public smoke contract name
    """The operator or environment did not satisfy the live safety gate."""


class HttpStatusFailure(SmokeFailure):
    """An HTTP call returned a non-success status code."""

    def __init__(self, method: str, url: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"{method} {url} failed with HTTP {status_code}")


def assert_no_null_measurement_values(value: Any, path: str = "measurements") -> None:
    """Reject null leaves in an evidence measurement tree."""

    if value is None:
        raise AssertionError(f"{path} must not be null")
    if isinstance(value, dict):
        for key, child in value.items():
            assert_no_null_measurement_values(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_no_null_measurement_values(child, f"{path}[{index}]")


def normalize_fixture_sample(sample: str) -> str:
    """Port the canonical shell normalizer using its ASCII token semantics."""

    lowered = sample.lower()
    return " ".join(re.sub(r"[^a-z0-9]", " ", lowered).split())


def fixture_sample_is_denied(sample: str) -> bool:
    """Return whether every content token of a seeded fixture is present."""

    tokens = set(normalize_fixture_sample(sample).split())
    return any(set(needles.split()).issubset(tokens) for needles in FIXTURE_TOKEN_SETS)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def _load_optional_json(path: str) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"availability": "unavailable", "path": path}
    except (OSError, json.JSONDecodeError) as exc:
        return {"availability": "unreadable", "path": path, "error": str(exc)}
    return {"availability": "available", "path": path, "value": payload}


@dataclass
class Deadline:
    max_seconds: float
    monotonic: Callable[[], float] = time.monotonic
    started: float = field(init=False)

    def __post_init__(self) -> None:
        self.started = self.monotonic()

    def elapsed(self) -> float:
        return max(0.0, self.monotonic() - self.started)

    def remaining(self) -> float:
        return self.max_seconds - self.elapsed()

    def check(self, stage: str) -> None:
        if self.remaining() <= 0:
            raise SmokeFailure(f"deadline exhausted while {stage}")

    def timeout(self, ceiling: float) -> float:
        self.check("starting an external call")
        return max(0.1, min(ceiling, self.remaining()))


class OciClient(Protocol):
    stop_calls: int

    def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, Any]: ...

    def stop_instance(self, instance_id: str, *, timeout: float) -> None: ...

    def list_instances(self, compartment_id: str, *, timeout: float) -> list[dict[str, Any]]: ...

    def list_start_events(
        self,
        compartment_id: str,
        instance_id: str,
        *,
        start_time: str,
        end_time: str,
        timeout: float,
    ) -> list[dict[str, Any]]: ...


class SubprocessOci:
    """Small timeout-bound facade over the OCI CLI JSON surface."""

    def __init__(self, oci_bin: str) -> None:
        self.oci_bin = oci_bin
        self.stop_calls = 0

    def _run(self, args: Sequence[str], *, timeout: float) -> Any:
        try:
            result = subprocess.run(
                [self.oci_bin, *args, "--output", "json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise SmokeFailure(f"OCI command failed: {exc}") from exc

    def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, Any]:
        payload = self._run(
            ["compute", "instance", "get", "--instance-id", instance_id],
            timeout=timeout,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise SmokeFailure("OCI instance get returned no data object")
        return data

    def stop_instance(self, instance_id: str, *, timeout: float) -> None:
        self.stop_calls += 1
        self._run(
            [
                "compute",
                "instance",
                "action",
                "--instance-id",
                instance_id,
                "--action",
                "STOP",
            ],
            timeout=timeout,
        )

    def list_instances(self, compartment_id: str, *, timeout: float) -> list[dict[str, Any]]:
        payload = self._run(
            [
                "compute",
                "instance",
                "list",
                "--compartment-id",
                compartment_id,
                "--all",
            ],
            timeout=timeout,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise SmokeFailure("OCI instance list returned no data array")
        return data

    def list_start_events(
        self,
        compartment_id: str,
        instance_id: str,
        *,
        start_time: str,
        end_time: str,
        timeout: float,
    ) -> list[dict[str, Any]]:
        payload = self._run(
            [
                "audit",
                "event",
                "list",
                "--compartment-id",
                compartment_id,
                "--start-time",
                start_time,
                "--end-time",
                end_time,
                "--all",
            ],
            timeout=timeout,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(event, dict) for event in data):
            raise SmokeFailure("OCI audit event list returned no data array")
        return [event for event in data if _is_start_event(event, instance_id)]


@dataclass
class DryScenario:
    health_adapter: str = "gpu_qwen30b"
    health_statuses: list[str] = field(default_factory=lambda: ["ok"])
    service_api_key: str = "dry-service-key"
    caption: str = "A red bicycle leans beside a brick library wall."
    alt_text_draft: str = "Red bicycle beside a brick library wall"
    model_id: str = EXPECTED_PROFILE.hub_repo
    revision: str = EXPECTED_REVISION
    run_statuses: list[str] = field(default_factory=lambda: ["running", "completed"])
    returned_media_ids: list[int] = field(default_factory=lambda: [101])
    item_statuses: list[str] = field(default_factory=lambda: ["queued", "running", "running", "completed"])
    item_tiers: list[str | None] = field(
        default_factory=lambda: [
            None,
            "provisional_cpu",
            "provisional_cpu",
            "final_gpu",
        ]
    )
    result_generations: list[int] = field(default_factory=lambda: [0, 1, 1, 2])


def _dry_item_payload(
    scenario: DryScenario,
    *,
    media_id: int,
    status: str,
    tier: str | None,
    result_generation: int,
) -> dict[str, Any]:
    """Build the canned item through the same schema as the service response."""

    values: dict[str, Any] = {
        "media_id": media_id,
        "status": status,
        "tier": tier,
        "result_generation": result_generation,
        "caption": scenario.caption if status == "completed" else None,
        "alt_text_draft": scenario.alt_text_draft if status == "completed" else None,
        "provenance": ({"model_id": f"{scenario.model_id}@{scenario.revision}"} if tier is not None else None),
    }
    return DescribeRunItemResponse(**values).model_dump(mode="json")


def make_mock_transport(scenario: DryScenario) -> httpx.MockTransport:
    """Return the canned WP/service transport used by the default dry run."""

    polls = 0
    item_polls = 0
    health_polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal health_polls, item_polls, polls
        path = request.url.path
        if request.method == "GET" and path == "/health/detailed":
            if request.headers.get("authorization") != f"Bearer {scenario.service_api_key}":
                return httpx.Response(401, json={"detail": "unauthorized"})
            health_status = scenario.health_statuses[min(health_polls, len(scenario.health_statuses) - 1)]
            health_polls += 1
            return httpx.Response(
                200,
                json={
                    "status": health_status,
                    "description_adapter": scenario.health_adapter,
                },
            )
        if request.method == "POST" and path == "/wp-json/acx/v1/recognition/describe/runs":
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Basic "):
                return httpx.Response(401, json={"code": "missing_auth"})
            return httpx.Response(202, json={"run_id": "11111111-1111-4111-8111-111111111111"})
        if request.method == "GET" and path.endswith("/items"):
            status = scenario.item_statuses[min(item_polls, len(scenario.item_statuses) - 1)]
            tier = scenario.item_tiers[min(item_polls, len(scenario.item_tiers) - 1)]
            result_generation = scenario.result_generations[min(item_polls, len(scenario.result_generations) - 1)]
            item_polls += 1
            return httpx.Response(
                200,
                json={
                    "tenant_id": "dry-tenant",
                    "run_id": "11111111-1111-4111-8111-111111111111",
                    "items": [
                        _dry_item_payload(
                            scenario,
                            media_id=media_id,
                            status=status,
                            tier=tier,
                            result_generation=result_generation,
                        )
                        for media_id in scenario.returned_media_ids
                    ],
                },
            )
        if request.method == "GET" and "/recognition/describe/runs/" in path:
            status = scenario.run_statuses[min(polls, len(scenario.run_statuses) - 1)]
            polls += 1
            return httpx.Response(
                200,
                json={
                    "tenant_id": "dry-tenant",
                    "run_id": "11111111-1111-4111-8111-111111111111",
                    "status": status,
                    "phase": "complete" if status in TERMINAL_RUN_STATUSES else "describing",
                    "completed": 1 if status in SUCCESS_RUN_STATUSES else 0,
                    "failed": 0,
                    "skipped": 0,
                    "total": 1,
                },
            )
        return httpx.Response(404, json={"error": f"uncanned {request.method} {path}"})

    return httpx.MockTransport(handler)


@dataclass
class FastClock:
    """A deterministic no-sleep clock for the offline orchestration path."""

    seconds: float = 0.0
    epoch: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    def monotonic(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.seconds += seconds

    def now(self) -> datetime:
        return self.epoch + timedelta(seconds=self.seconds)


@dataclass
class FakeOci:
    """Offline STOPPED→STARTING→RUNNING→STOPPING→STOPPED OCI machine."""

    startup_states: list[str] = field(default_factory=lambda: ["STARTING", "RUNNING"])
    reaper_states: list[str] = field(default_factory=lambda: ["RUNNING", "STOPPING", "STOPPED"])
    orphan_instances: list[dict[str, Any]] = field(default_factory=list)
    stop_effective: bool = True
    stop_states: list[str] = field(default_factory=lambda: ["STOPPING", "STOPPED"])
    compartment_id: str = "<compartment-ocid>"
    stop_calls: int = 0
    armed: bool = False
    reaping: bool = False
    stopping: bool = False
    current_state: str = "STOPPED"
    start_action_count: int = 1

    def trigger(self) -> None:
        self.armed = True

    def begin_reaper(self) -> None:
        self.reaping = True

    def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, Any]:
        del timeout
        states = self.stop_states if self.stopping else (self.reaper_states if self.reaping else self.startup_states)
        if self.stopping and states or self.armed and states:
            self.current_state = states.pop(0)
        return {
            "id": instance_id,
            "display-name": "acx-gpu-burst",
            "compartment-id": self.compartment_id,
            "lifecycle-state": self.current_state,
            "freeform-tags": {"role": "gpu-burst"},
        }

    def stop_instance(self, instance_id: str, *, timeout: float) -> None:
        del instance_id, timeout
        self.stop_calls += 1
        if self.stop_effective:
            self.current_state = "STOPPING"
            self.armed = False
            self.reaping = False
            self.stopping = True

    def list_instances(self, compartment_id: str, *, timeout: float) -> list[dict[str, Any]]:
        del compartment_id, timeout
        target = {
            "id": "<burst-instance-ocid>",
            "display-name": "acx-gpu-burst",
            "lifecycle-state": self.current_state,
            "freeform-tags": {"role": "gpu-burst"},
        }
        return [target, *self.orphan_instances]

    def list_start_events(
        self,
        compartment_id: str,
        instance_id: str,
        *,
        start_time: str,
        end_time: str,
        timeout: float,
    ) -> list[dict[str, Any]]:
        del compartment_id, end_time, start_time, timeout
        return [
            {
                "eventType": "com.oraclecloud.computeapi.instanceaction.end",
                "data": {
                    "resourceId": instance_id,
                    "request": {"parameters": {"action": ["START"]}},
                },
            }
            for _ in range(self.start_action_count)
        ]


@dataclass
class SmokeResult:
    exit_code: int
    evidence: dict[str, Any]


def _state(data: dict[str, Any]) -> str:
    return str(data.get("lifecycle-state") or data.get("lifecycle_state") or "UNKNOWN").upper()


def _compartment_id(data: dict[str, Any]) -> str:
    value = data.get("compartment-id") or data.get("compartment_id")
    if not isinstance(value, str) or not value:
        raise SmokeFailure("OCI instance has no compartment id")
    return value


def _is_gpu_burst(instance: dict[str, Any]) -> bool:
    name = str(instance.get("display-name") or instance.get("display_name") or "")
    freeform = instance.get("freeform-tags") or instance.get("freeform_tags") or {}
    role = freeform.get("role") if isinstance(freeform, dict) else None
    return name.startswith("acx-gpu-burst") or role == "gpu-burst"


def _is_start_event(event: dict[str, Any], instance_id: str) -> bool:
    data = event.get("data")
    if not isinstance(data, dict) or data.get("resourceId") != instance_id:
        return False
    request = data.get("request")
    if not isinstance(request, dict):
        return False
    parameters = request.get("parameters")
    if not isinstance(parameters, dict):
        return False
    action = parameters.get("action")
    actions = action if isinstance(action, list) else [action]
    return any(str(value).upper() == "START" for value in actions)


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    deadline: Deadline,
    auth: httpx.BasicAuth | None = None,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = client.request(
            method,
            url,
            auth=auth,
            headers=headers,
            json=payload,
            timeout=deadline.timeout(HTTP_CALL_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        raise HttpStatusFailure(method, url, exc.response.status_code) from exc
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise SmokeFailure(f"{method} {url} failed: {exc}") from exc
    if not isinstance(body, dict):
        raise SmokeFailure(f"{method} {url} returned a non-object JSON body")
    return body


def _validate_items_payload(raw_items: object) -> list[dict[str, Any]]:
    """Fail loudly when the WordPress items boundary violates its schema."""

    if not isinstance(raw_items, list):
        raise SmokeFailure(f"items must be a list, got {type(raw_items).__name__}")
    for index, item in enumerate(raw_items):
        path = f"items[{index}]"
        if not isinstance(item, dict):
            raise SmokeFailure(f"{path} must be an object, got {type(item).__name__}")

        media_id = item.get("media_id")
        if isinstance(media_id, bool) or not isinstance(media_id, int) or media_id <= 0:
            raise SmokeFailure(f"{path}.media_id must be a positive int, got {type(media_id).__name__}")
        status = item.get("status")
        if not isinstance(status, str):
            raise SmokeFailure(f"{path}.status must be a str, got {type(status).__name__}")

        if "tier" not in item:
            raise SmokeFailure(f"{path}: contract_tier_missing (expected top-level tier)")
        tier = item["tier"]
        if tier is not None and (not isinstance(tier, str) or not tier):
            raise SmokeFailure(f"{path}.tier must be a non-empty str or null, got {type(tier).__name__}")
        result_generation = item.get("result_generation")
        if isinstance(result_generation, bool) or not isinstance(result_generation, int) or result_generation < 0:
            raise SmokeFailure(
                f"{path}.result_generation must be a non-negative int, got {type(result_generation).__name__}"
            )

        provenance = item.get("provenance")
        if provenance is None:
            if status == "completed":
                raise SmokeFailure(f"{path}.provenance must be an object for a completed item, got NoneType")
            continue
        if not isinstance(provenance, dict):
            raise SmokeFailure(f"{path}.provenance must be an object or null, got {type(provenance).__name__}")
        model_identity = provenance.get("model_id")
        if not isinstance(model_identity, str) or not model_identity:
            raise SmokeFailure(
                f"{path}.provenance.model_id must be a non-empty str, got {type(model_identity).__name__}"
            )
        hub_repo, separator, revision = model_identity.rpartition("@")
        if not separator or not hub_repo or not revision:
            raise SmokeFailure(f"{path}.provenance.model_id must use <hub_repo>@<revision>")
    return raw_items


def _record_transition(
    transitions: list[dict[str, Any]],
    state: str,
    *,
    elapsed: float,
    now: Callable[[], datetime],
) -> None:
    if transitions and transitions[-1]["state"] == state:
        return
    transitions.append(
        {
            "state": state,
            "timestamp": _iso_utc(now()),
            "elapsed_seconds": round(elapsed, 3),
        }
    )


def _running_seconds(transitions: list[dict[str, Any]], *, final_elapsed_seconds: float) -> float:
    total = 0.0
    for current, following in pairwise(transitions):
        if current["state"] == "RUNNING":
            total += max(
                0.0,
                float(following["elapsed_seconds"]) - float(current["elapsed_seconds"]),
            )
    if transitions and transitions[-1]["state"] == "RUNNING":
        total += max(
            0.0,
            final_elapsed_seconds - float(transitions[-1]["elapsed_seconds"]),
        )
    return round(total, 3)


def _evidence_path(path: str) -> Path:
    return REPO_ROOT / path if not Path(path).is_absolute() else Path(path)


def _write_evidence(path: str, evidence: dict[str, Any], *, force: bool = False) -> None:
    target = _evidence_path(path)
    if target.exists() and not force:
        raise PreflightRefusal(f"evidence output already exists: {target}; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


def _print_assertion_table(checks: list[dict[str, Any]]) -> None:
    print("\nAssertion                         Result  Detail")
    print("-------------------------------- ------- ----------------------------------------")
    for check in checks:
        result = "PASS" if check["passed"] else "FAIL"
        print(f"{check['name']:<32} {result:<7} {check['detail']}")


def run_smoke(
    args: argparse.Namespace,
    *,
    client: httpx.Client,
    oci: OciClient,
    app_password: str,
    service_api_key: str,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _utc_now,
) -> SmokeResult:
    """Run the shared dry/live orchestration and always write evidence."""

    deadline = Deadline(float(args.max_seconds), monotonic)
    checks: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    item_timeline: list[dict[str, Any]] = []
    service_health_samples: list[dict[str, Any]] = []
    denylist_verdicts: list[dict[str, Any]] = []
    run_id = "unavailable"
    run_status = "unavailable"
    start_action_evidence: dict[str, Any] = {
        "source": "oci_audit",
        "status": "unavailable",
        "count": 0,
    }
    preflight_refused = False
    instance_validated = False
    compartment_id = "unavailable"
    gpu_snapshot = _load_optional_json(args.gpu_state_json)
    load_snapshot = _load_optional_json(args.load_json)

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def record_health(phase: str, health: dict[str, Any]) -> bool:
        healthy = health.get("status") == "ok" and health.get("description_adapter") == "gpu_qwen30b"
        service_health_samples.append(
            {
                "elapsed_seconds": round(deadline.elapsed(), 3),
                "phase": phase,
                "status": str(health.get("status") or "unknown"),
                "description_adapter": str(health.get("description_adapter") or "unknown"),
                "healthy": healthy,
            }
        )
        return healthy

    def poll_health(phase: str) -> None:
        try:
            health = _request_json(
                client,
                "GET",
                f"{args.service_base_url.rstrip('/')}/health/detailed",
                deadline=deadline,
                headers={"Authorization": f"Bearer {service_api_key}"},
            )
        except SmokeFailure as exc:
            service_health_samples.append(
                {
                    "elapsed_seconds": round(deadline.elapsed(), 3),
                    "phase": phase,
                    "status": "request_failed",
                    "description_adapter": "unknown",
                    "healthy": False,
                    "detail": str(exc),
                }
            )
            raise
        if not record_health(phase, health):
            raise SmokeFailure(
                f"description service unhealthy during {phase}: "
                f"status={health.get('status')}, "
                f"adapter={health.get('description_adapter')}"
            )

    try:
        try:
            try:
                health = _request_json(
                    client,
                    "GET",
                    f"{args.service_base_url.rstrip('/')}/health/detailed",
                    deadline=deadline,
                    headers={"Authorization": f"Bearer {service_api_key}"},
                )
            except HttpStatusFailure as exc:
                if exc.status_code in {401, 403}:
                    check("service_auth", False, f"HTTP {exc.status_code}")
                    preflight_refused = True
                    raise PreflightRefusal("description service rejected bearer authentication") from exc
                raise
            health_ok = record_health("preflight", health)
            check("service_auth", True, "bearer authentication accepted")
            adapter_ok = health.get("description_adapter") == "gpu_qwen30b"
            check(
                "health_adapter_gpu_qwen30b",
                adapter_ok,
                str(health.get("description_adapter")),
            )
            if not adapter_ok:
                preflight_refused = True
                raise PreflightRefusal("description service is not using gpu_qwen30b")
            check("service_health_preflight", health_ok, str(health.get("status")))
            if not health_ok:
                preflight_refused = True
                raise PreflightRefusal("description service is unhealthy at preflight")

            initial = oci.get_instance(
                args.instance_id,
                timeout=deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
            )
            compartment_id = _compartment_id(initial)
            identity_matches = str(initial.get("id")) == args.instance_id
            check(
                "instance_identity_matches",
                identity_matches,
                "requested instance identity verified"
                if identity_matches
                else "OCI response identity does not match the requested instance",
            )
            dedicated_instance = _is_gpu_burst(initial)
            check(
                "instance_dedicated_gpu_burst",
                dedicated_instance,
                "dedicated gpu-burst identity verified"
                if dedicated_instance
                else "instance name/tag does not identify a dedicated gpu-burst host",
            )
            if not identity_matches or not dedicated_instance:
                preflight_refused = True
                raise PreflightRefusal("instance identity or dedicated gpu-burst ownership is invalid")
            initial_state = _state(initial)
            _record_transition(transitions, initial_state, elapsed=deadline.elapsed(), now=now)
            check("initial_instance_stopped", initial_state == "STOPPED", initial_state)
            if initial_state != "STOPPED":
                preflight_refused = True
                raise PreflightRefusal(f"burst instance must start STOPPED, got {initial_state}")
            instance_validated = True
        except SmokeFailure as exc:
            check("preflight", False, str(exc))
            preflight_refused = True
            raise PreflightRefusal(str(exc)) from exc

        auth = httpx.BasicAuth(args.wp_user, app_password)
        run_window_started_at = _iso_utc(now())
        submitted = _request_json(
            client,
            "POST",
            f"{args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs",
            deadline=deadline,
            auth=auth,
            payload={"media_ids": args.media_ids},
        )
        candidate_run_id = submitted.get("run_id")
        if not isinstance(candidate_run_id, str) or not candidate_run_id:
            raise SmokeFailure("WordPress submit response has no run_id")
        run_id = candidate_run_id
        trigger = getattr(oci, "trigger", None)
        if callable(trigger):
            trigger()

        running_observed = False
        terminal_before_running: set[int | str] = set()
        degraded_items: set[int | str] = set()
        generations_by_media_id: dict[int | str, list[tuple[str, int]]] = {}

        def poll_items() -> None:
            nonlocal items
            item_body = _request_json(
                client,
                "GET",
                f"{args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs/{run_id}/items",
                deadline=deadline,
                auth=auth,
            )
            raw_items = item_body.get("items")
            items = _validate_items_payload(raw_items)
            elapsed = round(deadline.elapsed(), 3)
            for item in items:
                media_id = item.get("media_id", "unavailable")
                status = str(item.get("status") or "unknown")
                tier = item.get("tier")
                result_generation = int(item.get("result_generation", 0))
                item_timeline.append(
                    {
                        "elapsed_seconds": elapsed,
                        "media_id": media_id,
                        "status": status,
                        "tier": tier,
                        "result_generation": result_generation,
                    }
                )
                if isinstance(tier, str):
                    observations = generations_by_media_id.setdefault(media_id, [])
                    observation = (tier, result_generation)
                    if not observations or observations[-1] != observation:
                        observations.append(observation)
                if not running_observed and status in TERMINAL_ITEM_STATUSES:
                    terminal_before_running.add(media_id)
                if status == "completed" and tier == "provisional_cpu":
                    degraded_items.add(media_id)

        warm_started = False
        while not warm_started:
            try:
                deadline.check("waiting for GPU warm start")
            except SmokeFailure as exc:
                check("deadline", False, str(exc))
                break
            observed = oci.get_instance(
                args.instance_id,
                timeout=deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
            )
            observed_state = _state(observed)
            _record_transition(transitions, observed_state, elapsed=deadline.elapsed(), now=now)
            warm_started = observed_state == "RUNNING"
            running_observed = running_observed or warm_started
            poll_items()
            poll_health("warm_up")
            if not warm_started:
                sleep(POLL_SECONDS)
        check(
            "warm_start_running",
            warm_started,
            "RUNNING" if warm_started else "deadline before RUNNING",
        )

        while warm_started and run_status not in TERMINAL_RUN_STATUSES:
            try:
                deadline.check("polling WordPress run")
            except SmokeFailure as exc:
                check("deadline", False, str(exc))
                break
            observed = oci.get_instance(
                args.instance_id,
                timeout=deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
            )
            _record_transition(transitions, _state(observed), elapsed=deadline.elapsed(), now=now)
            running_observed = running_observed or _state(observed) == "RUNNING"
            poll_items()
            poll_health("processing")
            run = _request_json(
                client,
                "GET",
                f"{args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs/{run_id}",
                deadline=deadline,
                auth=auth,
            )
            run_status = str(run.get("status") or "unknown")
            if run_status not in TERMINAL_RUN_STATUSES:
                sleep(POLL_SECONDS)

        check("run_terminal_success", run_status in SUCCESS_RUN_STATUSES, run_status)
        check(
            "no_item_terminal_before_running",
            not terminal_before_running,
            f"offending media_ids: {sorted(terminal_before_running, key=str)}",
        )
        check(
            "no_degraded_items",
            not degraded_items,
            f"offending media_ids: {sorted(degraded_items, key=str)}",
        )

        returned_media_id_rows = [item.get("media_id") for item in items]
        duplicate_ids = {media_id for media_id in returned_media_id_rows if returned_media_id_rows.count(media_id) > 1}
        if duplicate_ids:
            raise SmokeFailure(f"duplicate media_id rows returned: {sorted(duplicate_ids, key=str)}")
        requested_ids = set(args.media_ids)
        returned_ids = set(returned_media_id_rows)
        check(
            "returned_media_ids_exact",
            returned_ids == requested_ids,
            f"expected {sorted(requested_ids)}; returned {sorted(returned_ids, key=str)}",
        )
        items_by_id = {item.get("media_id"): item for item in items}
        missing_ids = requested_ids - returned_ids
        incomplete_ids = {
            media_id
            for media_id in requested_ids
            if media_id in items_by_id and items_by_id[media_id].get("status") != "completed"
        }
        check(
            "all_items_completed",
            not missing_ids and not incomplete_ids,
            f"missing media_ids: {sorted(missing_ids)}; non-completed media_ids: {sorted(incomplete_ids)}",
        )

        requested_items = [items_by_id[media_id] for media_id in args.media_ids if media_id in items_by_id]
        wrong_tier_ids: set[int] = set(missing_ids)
        wrong_model_ids: set[int] = set(missing_ids)
        wrong_revision_ids: set[int] = set(missing_ids)
        for item in requested_items:
            media_id = item["media_id"]
            provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
            if item.get("tier") != "final_gpu":
                wrong_tier_ids.add(media_id)
            model_identity = str(provenance.get("model_id") or "")
            hub_repo, separator, revision = model_identity.rpartition("@")
            if not separator or hub_repo != EXPECTED_PROFILE.hub_repo:
                wrong_model_ids.add(media_id)
            if not separator or revision != EXPECTED_REVISION:
                wrong_revision_ids.add(media_id)
        check(
            "tier_final_gpu",
            not wrong_tier_ids,
            f"offending media_ids: {sorted(wrong_tier_ids)}",
        )

        denied_ids: set[int] = set(missing_ids)
        for item in requested_items:
            for field_name in ("caption", "alt_text_draft"):
                sample = item.get(field_name) or ""
                denied = not bool(str(sample).strip()) or fixture_sample_is_denied(str(sample))
                denylist_verdicts.append(
                    {
                        "media_id": item.get("media_id", "unavailable"),
                        "field": field_name,
                        "denied": denied,
                        "sample": str(sample),
                    }
                )
                if denied:
                    denied_ids.add(item["media_id"])
        check(
            "caption_not_fixture",
            not denied_ids,
            f"offending media_ids: {sorted(denied_ids)}",
        )

        check(
            "model_id_qwen30b",
            not wrong_model_ids,
            f"offending media_ids: {sorted(wrong_model_ids)}; expected {EXPECTED_MODEL_ID}",
        )
        check(
            "model_revision_pinned",
            not wrong_revision_ids,
            f"offending media_ids: {sorted(wrong_revision_ids)}; expected {EXPECTED_REVISION}",
        )

        non_superseded_ids: set[int] = set(missing_ids)
        for media_id in requested_ids - missing_ids:
            observations = generations_by_media_id.get(media_id, [])
            provisional_generations = [generation for tier, generation in observations if tier == "provisional_cpu"]
            final_generations = [generation for tier, generation in observations if tier == "final_gpu"]
            if not final_generations or (
                provisional_generations
                and not any(
                    final_generation > provisional_generation
                    for provisional_generation in provisional_generations
                    for final_generation in final_generations
                )
            ):
                non_superseded_ids.add(media_id)
        check(
            "provisional_superseded_by_final",
            not non_superseded_ids,
            f"offending media_ids: {sorted(non_superseded_ids)}",
        )

        begin_reaper = getattr(oci, "begin_reaper", None)
        if callable(begin_reaper):
            begin_reaper()
        reaper_stopped = False
        while not reaper_stopped:
            try:
                deadline.check("waiting for idle reaper STOPPED")
            except SmokeFailure as exc:
                if not any(existing["name"] == "deadline" for existing in checks):
                    check("deadline", False, str(exc))
                break
            observed = oci.get_instance(
                args.instance_id,
                timeout=deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
            )
            observed_state = _state(observed)
            _record_transition(transitions, observed_state, elapsed=deadline.elapsed(), now=now)
            reaper_stopped = observed_state == "STOPPED"
            poll_health("recovery" if reaper_stopped else "drain")
            if not reaper_stopped:
                sleep(POLL_SECONDS)
        check(
            "instance_stopped_after_reaper",
            reaper_stopped,
            "STOPPED" if reaper_stopped else "deadline before STOPPED",
        )
        start_events = oci.list_start_events(
            compartment_id,
            args.instance_id,
            start_time=run_window_started_at,
            end_time=_iso_utc(now()),
            timeout=deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
        )
        start_action_evidence = {
            "source": "oci_audit",
            "status": "observed",
            "count": len(start_events),
            "window_start": run_window_started_at,
            "window_end": _iso_utc(now()),
        }
        check(
            "exactly_one_start_action",
            len(start_events) == 1,
            f"observed {len(start_events)} authoritative START action(s)",
        )
    except PreflightRefusal:
        preflight_refused = True
    except (SmokeFailure, OSError, ValueError) as exc:
        check("flow_completed", False, str(exc))
    finally:
        if not instance_validated:
            check(
                "finally_stop_skipped",
                True,
                "instance was not validated; STOP and OCI follow-up skipped",
            )
        else:
            final_state = "UNKNOWN"
            stop_failures: list[str] = []
            successful_stop_calls = 0
            try:
                emergency_deadline = Deadline(EMERGENCY_STOP_TIMEOUT_SECONDS, monotonic)
                while final_state != "STOPPED":
                    emergency_deadline.check("waiting for compensating STOPPED")
                    try:
                        final_instance = oci.get_instance(
                            args.instance_id,
                            timeout=emergency_deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
                        )
                    except (SmokeFailure, PreflightRefusal, OSError, ValueError) as exc:
                        if oci.stop_calls >= MAX_EMERGENCY_STOP_ATTEMPTS:
                            raise SmokeFailure(
                                f"bounded compensating STOP retries exhausted after state read failure: {exc}"
                            ) from exc
                        try:
                            oci.stop_instance(
                                args.instance_id,
                                timeout=emergency_deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
                            )
                            successful_stop_calls += 1
                        except (SmokeFailure, OSError, ValueError) as stop_exc:
                            stop_failures.append(str(stop_exc))
                        sleep(POLL_SECONDS)
                        continue
                    final_state = _state(final_instance)
                    _record_transition(
                        transitions,
                        final_state,
                        elapsed=deadline.elapsed(),
                        now=now,
                    )
                    if final_state in {"STARTING", "RUNNING"}:
                        if oci.stop_calls >= MAX_EMERGENCY_STOP_ATTEMPTS:
                            raise SmokeFailure("bounded compensating STOP retries exhausted")
                        try:
                            oci.stop_instance(
                                args.instance_id,
                                timeout=emergency_deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
                            )
                            successful_stop_calls += 1
                        except (SmokeFailure, OSError, ValueError) as exc:
                            stop_failures.append(str(exc))
                    if final_state != "STOPPED":
                        sleep(POLL_SECONDS)
                stop_detail = (
                    "already STOPPED; no compensating STOP needed"
                    if oci.stop_calls == 0
                    else f"STOP issued ({oci.stop_calls} attempt(s))"
                )
                check(
                    "finally_stop_issued",
                    not stop_failures or successful_stop_calls > 0,
                    stop_detail if not stop_failures else f"{stop_detail}; failures: {'; '.join(stop_failures)}",
                )
                check("instance_stopped_finally", True, final_state)
            except (SmokeFailure, OSError, ValueError) as exc:
                check(
                    "finally_stop_issued",
                    False,
                    "; ".join(stop_failures) or str(exc),
                )
                check(
                    "instance_stopped_finally",
                    False,
                    f"{exc}; last state {final_state}",
                )

            with contextlib.suppress(SmokeFailure, OSError, ValueError):
                poll_health("after_stop")

            try:
                listed = oci.list_instances(compartment_id, timeout=OCI_CALL_TIMEOUT_SECONDS)
                orphans = [
                    instance
                    for instance in listed
                    if str(instance.get("id")) != args.instance_id
                    and _is_gpu_burst(instance)
                    and _state(instance) == "RUNNING"
                ]
                check("no_orphan_running", not orphans, f"{len(orphans)} orphan(s)")
            except (SmokeFailure, OSError, ValueError) as exc:
                check("no_orphan_running", False, str(exc))

    unhealthy_samples = [sample for sample in service_health_samples if not sample["healthy"]]
    check(
        "service_health_throughout",
        not unhealthy_samples,
        f"{len(service_health_samples)} sample(s); {len(unhealthy_samples)} unhealthy",
    )

    evidence_elapsed_seconds = deadline.elapsed()
    running_seconds = _running_seconds(transitions, final_elapsed_seconds=evidence_elapsed_seconds)
    cost = round(running_seconds * GPU_USD_PER_HOUR / 3600.0, 6)
    stopped_finally = any(check["name"] == "instance_stopped_finally" and check["passed"] for check in checks)
    running_seconds_ongoing = instance_validated and not stopped_finally
    cost_estimate_ongoing = running_seconds_ongoing
    measurements = {
        "running_seconds": running_seconds,
        "running_seconds_ongoing": running_seconds_ongoing,
        "cost_estimate_usd": cost,
        "cost_estimate_ongoing": cost_estimate_ongoing,
    }
    assert_no_null_measurement_values(measurements)
    item_provenance = []
    for item in items:
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        model_identity = str(provenance.get("model_id") or "")
        hub_repo, separator, revision = model_identity.rpartition("@")
        item_provenance.append(
            {
                "media_id": item.get("media_id", "unavailable"),
                "tier": item.get("tier", "unavailable"),
                "model_id": hub_repo if separator else "unavailable",
                "revision": revision if separator else "unavailable",
                "result_generation": item.get("result_generation", "unavailable"),
            }
        )
    evidence = {
        "schema_version": 1,
        "mode": "live" if args.live else "dry-run",
        "generated_at": _iso_utc(now()),
        "head_sha": _head_sha(),
        "run_id": run_id,
        "run_status": run_status,
        "media_ids": args.media_ids,
        "transitions": transitions,
        "start_action_evidence": start_action_evidence,
        "item_timeline": item_timeline,
        "item_provenance": item_provenance,
        "service_health_samples": service_health_samples,
        "denylist_verdicts": denylist_verdicts,
        "gpu_state_json": gpu_snapshot,
        "load_json": load_snapshot,
        "measurements": measurements,
        "running_seconds_ongoing": running_seconds_ongoing,
        "cost_estimate_usd": cost,
        "cost_estimate_ongoing": cost_estimate_ongoing,
        "checks": checks,
    }
    _write_evidence(args.evidence_out, evidence, force=args.force)
    _print_assertion_table(checks)
    remaining_budget_seconds = args.max_seconds
    warm_start_budget_seconds = min(WARM_START_BUDGET_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= warm_start_budget_seconds
    idle_reaper_seconds = min(IDLE_REAPER_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= idle_reaper_seconds
    reaper_budget_seconds = min(REAPER_BUDGET_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= reaper_budget_seconds
    fence_budget_seconds = min(FENCE_BUDGET_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= fence_budget_seconds
    inference_budget_seconds = remaining_budget_seconds
    budget_total = (
        warm_start_budget_seconds
        + inference_budget_seconds
        + idle_reaper_seconds
        + reaper_budget_seconds
        + fence_budget_seconds
    )
    print(
        f"\nBudget: {budget_total}s = warm-start {warm_start_budget_seconds}s + "
        f"inference {inference_budget_seconds}s + idle {idle_reaper_seconds}s + "
        f"reap {reaper_budget_seconds}s + fence {fence_budget_seconds}s"
    )
    print(
        f"Estimated GPU cost: ${cost:.6f} ({running_seconds:.3f}s RUNNING at ${GPU_USD_PER_HOUR:.2f}/hour; "
        f"{'ongoing' if cost_estimate_ongoing else 'closed'})"
    )
    print(f"Evidence: {args.evidence_out}")
    exit_code = 2 if preflight_refused else (0 if all(check["passed"] for check in checks) else 1)
    return SmokeResult(exit_code=exit_code, evidence=evidence)


def _media_ids(value: str) -> list[int]:
    try:
        parsed = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("media ids must be comma-separated integers") from exc
    if not parsed or any(media_id <= 0 for media_id in parsed):
        raise argparse.ArgumentTypeError("at least one positive media id is required")
    if len(set(parsed)) != len(parsed):
        raise argparse.ArgumentTypeError("media ids must be unique (idempotent trigger guard)")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wp-base-url", default="https://wordpress.invalid")
    parser.add_argument("--wp-user", default="gpu-smoke-operator")
    parser.add_argument("--wp-app-password-env", default="ACX_WP_APP_PASSWORD", metavar="NAME")
    parser.add_argument("--media-ids", type=_media_ids, default=_media_ids("101"))
    parser.add_argument("--service-base-url", default="https://description-service.invalid")
    parser.add_argument("--service-api-key-env", default="ACX_DESCRIPTION_API_KEY", metavar="NAME")
    parser.add_argument("--instance-id", default="<burst-instance-ocid>")
    parser.add_argument("--oci-bin", default="oci")
    parser.add_argument("--gpu-state-json", default="/run/acx/gpu-state.json")
    parser.add_argument("--load-json", default="/run/acx/describe-load.json")
    parser.add_argument("--max-seconds", type=int, default=MAX_LIVE_SECONDS)
    parser.add_argument(
        "--evidence-out",
        default=(f"{DEFAULT_EVIDENCE_DIR}/GPUSMOKE-1-evidence-{datetime.now(UTC).date().isoformat()}.json"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing evidence artifact",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="live",
        action="store_false",
        help="offline MockTransport run (default)",
    )
    mode.add_argument(
        "--live",
        dest="live",
        action="store_true",
        help="operator-gated live WP/OCI run",
    )
    parser.set_defaults(live=False)
    return parser


def _validate_args(args: argparse.Namespace) -> tuple[str, str]:
    if args.max_seconds <= 0 or args.max_seconds > MAX_LIVE_SECONDS:
        raise PreflightRefusal(f"--max-seconds must be between 1 and {MAX_LIVE_SECONDS}")
    environment_options = (
        ("--wp-app-password-env", args.wp_app_password_env),
        ("--service-api-key-env", args.service_api_key_env),
    )
    for option, environment_name in environment_options:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", environment_name):
            raise PreflightRefusal(f"{option} must name a valid environment variable")
    evidence_target = _evidence_path(args.evidence_out)
    if evidence_target.exists() and not args.force:
        raise PreflightRefusal(f"evidence output already exists: {evidence_target}; pass --force to overwrite")
    if not args.live:
        return "dry-run-only", "dry-service-key"
    if os.environ.get("ACX_GPU_SMOKE_CONFIRM") != "RUN":
        raise PreflightRefusal("live mode requires ACX_GPU_SMOKE_CONFIRM=RUN")
    service_url = urlsplit(args.service_base_url)
    if (
        service_url.scheme not in {"http", "https"}
        or not service_url.hostname
        or service_url.hostname.endswith(".invalid")
        or "<" in args.service_base_url
        or ">" in args.service_base_url
    ):
        raise PreflightRefusal("--service-base-url must explicitly name the description service")
    password = os.environ.get(args.wp_app_password_env)
    if not password:
        raise PreflightRefusal(f"live mode requires a password in {args.wp_app_password_env}")
    service_api_key = os.environ.get(args.service_api_key_env)
    if not service_api_key:
        raise PreflightRefusal(f"live mode requires a service API key in {args.service_api_key_env}")
    resolved = shutil.which(args.oci_bin)
    if resolved is None:
        raise PreflightRefusal(f"OCI binary does not resolve: {args.oci_bin}")
    args.oci_bin = resolved
    if args.instance_id == "<burst-instance-ocid>":
        raise PreflightRefusal("replace <burst-instance-ocid> before live mode")
    return password, service_api_key


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
    oci_factory: Callable[[str], OciClient] = SubprocessOci,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        app_password, service_api_key = _validate_args(args)
    except PreflightRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.live:
        client = client_factory(follow_redirects=False)
        oci = oci_factory(args.oci_bin)
        clock = None
    else:
        clock = FastClock()
        client = client_factory(transport=make_mock_transport(DryScenario()), follow_redirects=False)
        oci = FakeOci()

    try:
        kwargs: dict[str, Any] = {}
        if clock is not None:
            kwargs = {
                "monotonic": clock.monotonic,
                "sleep": clock.sleep,
                "now": clock.now,
            }
        result = run_smoke(
            args,
            client=client,
            oci=oci,
            app_password=app_password,
            service_api_key=service_api_key,
            **kwargs,
        )
    finally:
        client.close()
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
