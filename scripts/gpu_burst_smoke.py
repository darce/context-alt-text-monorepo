#!/usr/bin/env python3
"""Prove that a WordPress describe run bursts to GPU and is reaped safely.

The default is a completely offline dry run.  It uses ``httpx.MockTransport``
and an in-memory OCI state machine, but follows the same WordPress REST, polling,
assertion, evidence, and compensating-STOP path as live mode::

    python3 scripts/gpu_burst_smoke.py

Live mode is deliberately awkward to invoke.  Run it only on ``acx-backend`` as
``ubuntu`` (the host with the OCI binary and vaulted key), set the application
password in the environment named by ``--wp-app-password-env``, and acknowledge
the spend guard::

    ACX_GPU_SMOKE_CONFIRM=RUN python3 scripts/gpu_burst_smoke.py --live \
      --wp-base-url https://wordpress.example --wp-user operator \
      --media-ids 101,102 --service-base-url http://<burst-private-ip>:8000 \
      --instance-id <burst-instance-ocid> --max-seconds 900

No password is accepted on argv.  Every HTTP/OCI operation has a timeout, every
poll loop checks one overall deadline, and live execution always issues STOP in
``finally`` before it reports success or failure.
"""

from __future__ import annotations

import argparse
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
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = REPO_ROOT / "apps" / "prototype-description-service"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# The deployment profile is the single source of truth for this mutable pin.
from scene.config.profiles import DescriptionProfile, get_profile_spec

EXPECTED_MODEL_ID = "Qwen3-VL-30B-A3B-Instruct"
EXPECTED_PROFILE = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
if (
    EXPECTED_PROFILE.model_id != EXPECTED_MODEL_ID
    or not EXPECTED_PROFILE.model_revision
):
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
MAX_LIVE_SECONDS = 900
GPU_USD_PER_HOUR = 2.0


class SmokeFailure(RuntimeError):
    """The smoke completed far enough to produce failing evidence."""


class PreflightRefusal(RuntimeError):
    """The operator or environment did not satisfy the live safety gate."""


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

    def list_instances(
        self, compartment_id: str, *, timeout: float
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
                "--force",
            ],
            timeout=timeout,
        )

    def list_instances(
        self, compartment_id: str, *, timeout: float
    ) -> list[dict[str, Any]]:
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
        if not isinstance(data, list) or not all(
            isinstance(item, dict) for item in data
        ):
            raise SmokeFailure("OCI instance list returned no data array")
        return data


@dataclass
class DryScenario:
    health_adapter: str = "gpu_qwen30b"
    tier: str = "final_gpu"
    caption: str = "A red bicycle leans beside a brick library wall."
    alt_text_draft: str = "Red bicycle beside a brick library wall"
    model_id: str = EXPECTED_MODEL_ID
    revision: str = EXPECTED_REVISION
    run_statuses: list[str] = field(default_factory=lambda: ["running", "completed"])
    returned_media_ids: list[int] = field(default_factory=lambda: [101])
    item_statuses: list[str] = field(
        default_factory=lambda: ["queued", "queued", "running", "completed"]
    )
    item_tiers: list[str | None] = field(
        default_factory=lambda: [None, None, None, "final_gpu"]
    )


def make_mock_transport(scenario: DryScenario) -> httpx.MockTransport:
    """Return the canned WP/service transport used by the default dry run."""

    polls = 0
    item_polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal item_polls, polls
        path = request.url.path
        if request.method == "GET" and path == "/health/detailed":
            return httpx.Response(
                200,
                json={"status": "ok", "description_adapter": scenario.health_adapter},
            )
        if (
            request.method == "POST"
            and path == "/wp-json/acx/v1/recognition/describe/runs"
        ):
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Basic "):
                return httpx.Response(401, json={"code": "missing_auth"})
            return httpx.Response(
                202, json={"run_id": "11111111-1111-4111-8111-111111111111"}
            )
        if request.method == "GET" and path.endswith("/items"):
            status = scenario.item_statuses[
                min(item_polls, len(scenario.item_statuses) - 1)
            ]
            tier = scenario.item_tiers[min(item_polls, len(scenario.item_tiers) - 1)]
            item_polls += 1
            return httpx.Response(
                200,
                json={
                    "tenant_id": "dry-tenant",
                    "run_id": "11111111-1111-4111-8111-111111111111",
                    "items": [
                        {
                            "media_id": media_id,
                            "status": status,
                            "caption": scenario.caption
                            if status == "completed"
                            else None,
                            "alt_text_draft": scenario.alt_text_draft
                            if status == "completed"
                            else None,
                            "provenance": (
                                {
                                    "tier": scenario.tier
                                    if tier == "final_gpu"
                                    else tier,
                                    "model_id": scenario.model_id,
                                    "revision": scenario.revision,
                                }
                                if tier is not None
                                else None
                            ),
                        }
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
                    "phase": "complete"
                    if status in TERMINAL_RUN_STATUSES
                    else "describing",
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
    reaper_states: list[str] = field(
        default_factory=lambda: ["RUNNING", "STOPPING", "STOPPED"]
    )
    orphan_instances: list[dict[str, Any]] = field(default_factory=list)
    stop_effective: bool = True
    stop_states: list[str] = field(default_factory=lambda: ["STOPPING", "STOPPED"])
    compartment_id: str = "<compartment-ocid>"
    stop_calls: int = 0
    armed: bool = False
    reaping: bool = False
    stopping: bool = False
    current_state: str = "STOPPED"

    def trigger(self) -> None:
        self.armed = True

    def begin_reaper(self) -> None:
        self.reaping = True

    def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, Any]:
        del timeout
        states = (
            self.stop_states
            if self.stopping
            else (self.reaper_states if self.reaping else self.startup_states)
        )
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

    def list_instances(
        self, compartment_id: str, *, timeout: float
    ) -> list[dict[str, Any]]:
        del compartment_id, timeout
        target = {
            "id": "<burst-instance-ocid>",
            "display-name": "acx-gpu-burst",
            "lifecycle-state": self.current_state,
            "freeform-tags": {"role": "gpu-burst"},
        }
        return [target, *self.orphan_instances]


@dataclass
class SmokeResult:
    exit_code: int
    evidence: dict[str, Any]


def _state(data: dict[str, Any]) -> str:
    return str(
        data.get("lifecycle-state") or data.get("lifecycle_state") or "UNKNOWN"
    ).upper()


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


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    deadline: Deadline,
    auth: httpx.BasicAuth | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = client.request(
            method,
            url,
            auth=auth,
            json=payload,
            timeout=deadline.timeout(HTTP_CALL_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise SmokeFailure(f"{method} {url} failed: {exc}") from exc
    if not isinstance(body, dict):
        raise SmokeFailure(f"{method} {url} returned a non-object JSON body")
    return body


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


def _running_seconds(
    transitions: list[dict[str, Any]], *, final_elapsed_seconds: float
) -> float:
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


def _write_evidence(path: str, evidence: dict[str, Any]) -> None:
    target = REPO_ROOT / path if not Path(path).is_absolute() else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(target)


def _print_assertion_table(checks: list[dict[str, Any]]) -> None:
    print("\nAssertion                         Result  Detail")
    print(
        "-------------------------------- ------- ----------------------------------------"
    )
    for check in checks:
        result = "PASS" if check["passed"] else "FAIL"
        print(f"{check['name']:<32} {result:<7} {check['detail']}")


def run_smoke(
    args: argparse.Namespace,
    *,
    client: httpx.Client,
    oci: OciClient,
    app_password: str,
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
    denylist_verdicts: list[dict[str, Any]] = []
    run_id = "unavailable"
    run_status = "unavailable"
    preflight_refused = False
    compartment_id = "unavailable"
    gpu_snapshot = _load_optional_json(args.gpu_state_json)
    load_snapshot = _load_optional_json(args.load_json)

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        try:
            health = _request_json(
                client,
                "GET",
                f"{args.service_base_url.rstrip('/')}/health/detailed",
                deadline=deadline,
            )
            adapter_ok = health.get("description_adapter") == "gpu_qwen30b"
            check(
                "health_adapter_gpu_qwen30b",
                adapter_ok,
                str(health.get("description_adapter")),
            )
            if not adapter_ok:
                preflight_refused = True
                raise PreflightRefusal("description service is not using gpu_qwen30b")

            initial = oci.get_instance(
                args.instance_id,
                timeout=deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
            )
            compartment_id = _compartment_id(initial)
            initial_state = _state(initial)
            _record_transition(
                transitions, initial_state, elapsed=deadline.elapsed(), now=now
            )
            check("initial_instance_stopped", initial_state == "STOPPED", initial_state)
            if initial_state != "STOPPED":
                preflight_refused = True
                raise PreflightRefusal(
                    f"burst instance must start STOPPED, got {initial_state}"
                )
        except SmokeFailure as exc:
            check("preflight", False, str(exc))
            preflight_refused = True
            raise PreflightRefusal(str(exc)) from exc

        auth = httpx.BasicAuth(args.wp_user, app_password)
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
        provisional_or_degraded: set[int | str] = set()

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
            items = (
                [item for item in raw_items if isinstance(item, dict)]
                if isinstance(raw_items, list)
                else []
            )
            elapsed = round(deadline.elapsed(), 3)
            for item in items:
                media_id = item.get("media_id", "unavailable")
                status = str(item.get("status") or "unknown")
                provenance = item.get("provenance")
                tier = provenance.get("tier") if isinstance(provenance, dict) else None
                item_timeline.append(
                    {
                        "elapsed_seconds": elapsed,
                        "media_id": media_id,
                        "status": status,
                        "tier": tier,
                    }
                )
                if not running_observed and status in TERMINAL_ITEM_STATUSES:
                    terminal_before_running.add(media_id)
                if status == "degraded" or tier == "provisional_cpu":
                    provisional_or_degraded.add(media_id)

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
            _record_transition(
                transitions, observed_state, elapsed=deadline.elapsed(), now=now
            )
            warm_started = observed_state == "RUNNING"
            running_observed = running_observed or warm_started
            poll_items()
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
            _record_transition(
                transitions, _state(observed), elapsed=deadline.elapsed(), now=now
            )
            running_observed = running_observed or _state(observed) == "RUNNING"
            poll_items()
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
            "no_provisional_or_degraded_items",
            not provisional_or_degraded,
            f"offending media_ids: {sorted(provisional_or_degraded, key=str)}",
        )

        requested_ids = set(args.media_ids)
        returned_ids = {item.get("media_id") for item in items}
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
            if media_id in items_by_id
            and items_by_id[media_id].get("status") != "completed"
        }
        check(
            "all_items_completed",
            not missing_ids and not incomplete_ids,
            f"missing media_ids: {sorted(missing_ids)}; non-completed media_ids: {sorted(incomplete_ids)}",
        )

        requested_items = [
            items_by_id[media_id]
            for media_id in args.media_ids
            if media_id in items_by_id
        ]
        wrong_tier_ids: set[int] = set(missing_ids)
        wrong_model_ids: set[int] = set(missing_ids)
        wrong_revision_ids: set[int] = set(missing_ids)
        for item in requested_items:
            media_id = item["media_id"]
            provenance = (
                item.get("provenance")
                if isinstance(item.get("provenance"), dict)
                else {}
            )
            if provenance.get("tier") != "final_gpu":
                wrong_tier_ids.add(media_id)
            if provenance.get("model_id") != EXPECTED_MODEL_ID:
                wrong_model_ids.add(media_id)
            if (
                provenance.get("revision") or provenance.get("model_revision")
            ) != EXPECTED_REVISION:
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
                denied = not bool(str(sample).strip()) or fixture_sample_is_denied(
                    str(sample)
                )
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
            _record_transition(
                transitions, observed_state, elapsed=deadline.elapsed(), now=now
            )
            reaper_stopped = observed_state == "STOPPED"
            if not reaper_stopped:
                sleep(POLL_SECONDS)
        check(
            "instance_stopped_after_reaper",
            reaper_stopped,
            "STOPPED" if reaper_stopped else "deadline before STOPPED",
        )
        start_count = sum(
            transition["state"] == "STARTING" for transition in transitions
        )
        check(
            "exactly_one_start_transition", start_count == 1, f"observed {start_count}"
        )
    except PreflightRefusal:
        pass
    except (SmokeFailure, OSError, ValueError) as exc:
        check("flow_completed", False, str(exc))
    finally:
        try:
            oci.stop_instance(args.instance_id, timeout=OCI_CALL_TIMEOUT_SECONDS)
            check(
                "finally_stop_issued", True, f"STOP issued ({oci.stop_calls} call(s))"
            )
        except (SmokeFailure, OSError, ValueError) as exc:
            check("finally_stop_issued", False, str(exc))

        final_state = "UNKNOWN"
        try:
            emergency_deadline = Deadline(EMERGENCY_STOP_TIMEOUT_SECONDS, monotonic)
            while final_state != "STOPPED":
                emergency_deadline.check("waiting for compensating STOPPED")
                final_instance = oci.get_instance(
                    args.instance_id,
                    timeout=emergency_deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
                )
                final_state = _state(final_instance)
                _record_transition(
                    transitions, final_state, elapsed=deadline.elapsed(), now=now
                )
                if compartment_id == "unavailable":
                    compartment_id = _compartment_id(final_instance)
                if final_state != "STOPPED":
                    sleep(POLL_SECONDS)
            check("instance_stopped_finally", True, final_state)
        except (SmokeFailure, OSError, ValueError) as exc:
            check("instance_stopped_finally", False, f"{exc}; last state {final_state}")

        try:
            listed = oci.list_instances(
                compartment_id, timeout=OCI_CALL_TIMEOUT_SECONDS
            )
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

    evidence_elapsed_seconds = deadline.elapsed()
    running_seconds = _running_seconds(
        transitions, final_elapsed_seconds=evidence_elapsed_seconds
    )
    cost = round(running_seconds * GPU_USD_PER_HOUR / 3600.0, 6)
    stopped_finally = any(
        check["name"] == "instance_stopped_finally" and check["passed"]
        for check in checks
    )
    running_seconds_ongoing = not stopped_finally
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
        provenance = (
            item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        )
        item_provenance.append(
            {
                "media_id": item.get("media_id", "unavailable"),
                "tier": provenance.get("tier", "unavailable"),
                "model_id": provenance.get("model_id", "unavailable"),
                "revision": provenance.get("revision")
                or provenance.get("model_revision")
                or "unavailable",
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
        "item_timeline": item_timeline,
        "item_provenance": item_provenance,
        "denylist_verdicts": denylist_verdicts,
        "gpu_state_json": gpu_snapshot,
        "load_json": load_snapshot,
        "measurements": measurements,
        "running_seconds_ongoing": running_seconds_ongoing,
        "cost_estimate_usd": cost,
        "cost_estimate_ongoing": cost_estimate_ongoing,
        "checks": checks,
    }
    _write_evidence(args.evidence_out, evidence)
    _print_assertion_table(checks)
    print(
        f"\nBudget: {args.max_seconds}s = idle 300s + reap 120s + fence 2s + slack {max(0, args.max_seconds - 422)}s"
    )
    print(
        f"Estimated GPU cost: ${cost:.6f} ({running_seconds:.3f}s RUNNING at ${GPU_USD_PER_HOUR:.2f}/hour; "
        f"{'ongoing' if cost_estimate_ongoing else 'closed'})"
    )
    print(f"Evidence: {args.evidence_out}")
    exit_code = (
        2
        if preflight_refused
        else (0 if all(check["passed"] for check in checks) else 1)
    )
    return SmokeResult(exit_code=exit_code, evidence=evidence)


def _media_ids(value: str) -> list[int]:
    try:
        parsed = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "media ids must be comma-separated integers"
        ) from exc
    if not parsed or any(media_id <= 0 for media_id in parsed):
        raise argparse.ArgumentTypeError("at least one positive media id is required")
    if len(set(parsed)) != len(parsed):
        raise argparse.ArgumentTypeError(
            "media ids must be unique (idempotent trigger guard)"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wp-base-url", default="https://wordpress.invalid")
    parser.add_argument("--wp-user", default="gpu-smoke-operator")
    parser.add_argument(
        "--wp-app-password-env", default="ACX_WP_APP_PASSWORD", metavar="NAME"
    )
    parser.add_argument("--media-ids", type=_media_ids, default=_media_ids("101"))
    parser.add_argument(
        "--service-base-url", default="https://description-service.invalid"
    )
    parser.add_argument("--instance-id", default="<burst-instance-ocid>")
    parser.add_argument("--oci-bin", default="oci")
    parser.add_argument("--gpu-state-json", default="/run/acx/gpu-state.json")
    parser.add_argument("--load-json", default="/run/acx/describe-load.json")
    parser.add_argument("--max-seconds", type=int, default=MAX_LIVE_SECONDS)
    parser.add_argument(
        "--evidence-out",
        default=f"docs/tasks/vlm/GPUSMOKE-1-evidence-{datetime.now(UTC).date().isoformat()}.json",
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


def _validate_args(args: argparse.Namespace) -> str:
    if args.max_seconds <= 0 or args.max_seconds > MAX_LIVE_SECONDS:
        raise PreflightRefusal(
            f"--max-seconds must be between 1 and {MAX_LIVE_SECONDS}"
        )
    if not args.live:
        return "dry-run-only"
    if os.environ.get("ACX_GPU_SMOKE_CONFIRM") != "RUN":
        raise PreflightRefusal("live mode requires ACX_GPU_SMOKE_CONFIRM=RUN")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.wp_app_password_env):
        raise PreflightRefusal(
            "--wp-app-password-env must name a valid environment variable"
        )
    password = os.environ.get(args.wp_app_password_env)
    if not password:
        raise PreflightRefusal(
            f"live mode requires a password in {args.wp_app_password_env}"
        )
    resolved = shutil.which(args.oci_bin)
    if resolved is None:
        raise PreflightRefusal(f"OCI binary does not resolve: {args.oci_bin}")
    args.oci_bin = resolved
    if args.instance_id == "<burst-instance-ocid>":
        raise PreflightRefusal("replace <burst-instance-ocid> before live mode")
    return password


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
    oci_factory: Callable[[str], OciClient] = SubprocessOci,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        app_password = _validate_args(args)
    except PreflightRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.live:
        client = client_factory(follow_redirects=False)
        oci = oci_factory(args.oci_bin)
        clock = None
    else:
        clock = FastClock()
        client = client_factory(
            transport=make_mock_transport(DryScenario()), follow_redirects=False
        )
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
            args, client=client, oci=oci, app_password=app_password, **kwargs
        )
    finally:
        client.close()
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
