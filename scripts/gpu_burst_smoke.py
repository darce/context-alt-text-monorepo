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
``finally`` before it reports success or failure.  SIGTERM and SIGHUP are routed
into that same unwind so an orchestrator or CI timeout cannot leave the instance
RUNNING; SIGKILL is uncatchable and remains the host reaper's problem.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
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
_settings = import_module("scene.config.settings")
_describe_load = import_module("scene.application.describe_load")
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
MAX_LIVE_SECONDS = 1200
GPU_USD_PER_HOUR = 2.0
DEFAULT_STOP_PRINCIPAL = "gpu_lifecycle"
DRY_TENANT_ID = "dry-tenant"
EXPECTED_GPU_BURST_DISPLAY_NAME = "acx-gpu-burst"
EXPECTED_GPU_BURST_SHAPE = "VM.GPU.A10.1"
EXPECTED_GPU_BURST_TAGS = {
    "project": "acx",
    "env": "production",
    "role": "gpu-burst",
    "scale_to_zero": "true",
    "purpose": "gpu-spike-bench",
}
DEFAULT_EVIDENCE_DIR = ".workbay/tmp/gpu-burst-smoke"
WARM_START_BUDGET_SECONDS = float(_settings.DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS)
IDLE_REAPER_SECONDS = 300
REAPER_BUDGET_SECONDS = 120
NON_BILLING_TERMINAL_STATES = {"STOPPED", "TERMINATED"}
FENCE_BUDGET_SECONDS = 2
AUDIT_INDEX_TIMEOUT_SECONDS = 60.0
MIN_COMPOSED_BUDGET_SECONDS = (
    WARM_START_BUDGET_SECONDS
    + IDLE_REAPER_SECONDS
    + REAPER_BUDGET_SECONDS
    + FENCE_BUDGET_SECONDS
    + AUDIT_INDEX_TIMEOUT_SECONDS
)
POST_STOP_HEALTH_TIMEOUT_SECONDS = 20.0
LOAD_SNAPSHOT_SKEW_SECONDS = 2.0
# WBUX6-MRG-02 moved publication from one `/run/acx/describe-load.json` to a
# per-environment layout. Keep this in parity with the `--load-dir` flag the
# lifecycle units carry in scripts/deploy/gpu-lifecycle-install.sh, which is the
# same authority scripts/deploy/check-gpu-snapshots.sh resolves its load dir
# from.
DEFAULT_LOAD_DIR = "/run/acx-write"
LOAD_SNAPSHOT_FILENAME = "describe-load.json"
TERMINATION_SIGNAL_NAMES = ("SIGTERM", "SIGHUP")
LOAD_SNAPSHOT_OBSERVATION_SECONDS = float(_describe_load.DEFAULT_LOAD_REFRESH_SECONDS)


class SmokeFailure(RuntimeError):  # noqa: N818 - public smoke contract name
    """The smoke completed far enough to produce failing evidence."""


class PreflightRefusal(RuntimeError):  # noqa: N818 - public smoke contract name
    """The operator or environment did not satisfy the live safety gate."""


class SmokeTerminated(KeyboardInterrupt):
    """A termination signal, raised so the compensating STOP path unwinds.

    It subclasses ``KeyboardInterrupt`` so SIGTERM and SIGHUP take exactly the
    exit route SIGINT already takes: no ``except SmokeFailure`` swallows it, and
    the single ``finally`` STOP in :func:`run_smoke` stays the one writer of the
    stop action.

    WBUX6-W5-03, deliberate: this propagates past ``_write_evidence``, so a
    signal-terminated run emits NO evidence artifact. A partial run must not
    leave a file that reads as a verdict. The observable substitutes are the
    compensating STOP, the ``TERMINATED:`` stderr line, and the ``128+signum``
    exit status -- so the run is not silent either (OBS-08 silence is not
    success, ~/Development/heuristics-canon-research/lexicons/engineering.md:478).
    Guarded by ``test_sigterm_unwinds_into_the_compensating_stop``.
    """

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"terminated by signal {signal.Signals(signum).name}")


@contextlib.contextmanager
def terminating_signals_raise() -> Iterator[None]:
    """Route SIGTERM/SIGHUP into the compensating-STOP unwind, for one run only.

    A running A10 outlives this process, so its compensation has to fire on every
    exit route the process can actually take. With no handler a SIGTERM -- how an
    orchestrator, a CI timeout, or ``timeout(1)`` kills a hung run -- ends the
    interpreter without unwinding, and the instance keeps billing. Handlers are
    installed only for the duration of a CLI run and restored afterwards, so
    importing this module never changes a caller's disposition.

    SIGKILL cannot be caught, so ``kill -9`` still leaks the instance; the host
    idle reaper is the only backstop for that case.
    """

    installed: dict[int, Any] = {}

    def _raise(signum: int, _frame: Any) -> None:
        # Ignore repeats so a second signal cannot interrupt the STOP that is
        # already unwinding; SIGKILL stays the operator's escape hatch.
        for number in installed:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(number, signal.SIG_IGN)
        raise SmokeTerminated(signum)

    for name in TERMINATION_SIGNAL_NAMES:
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            installed[int(number)] = signal.signal(number, _raise)
        except (OSError, ValueError):
            # Not the main thread, or the platform has no such signal.
            continue
    try:
        yield
    finally:
        for number, previous in installed.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(number, previous)


@contextlib.contextmanager
def terminating_signals_deferred() -> Iterator[None]:
    """Make the compensating STOP uninterruptible by a catchable signal.

    :func:`terminating_signals_raise` routes a signal INTO the unwind. That is
    only half the guarantee: once the process is already unwinding for some
    other reason (a ``SmokeFailure``, a blown deadline, a refusal after start),
    the STOP loop in :func:`run_smoke`'s ``finally`` is ordinary Python, and a
    SIGTERM arriving mid-loop raises straight through it. The A10 is then left
    RUNNING and billing -- the exact outcome the ``finally`` exists to prevent,
    reachable by a signal that arrives two lines later than the one already
    covered.

    A compensating action must run to completion once started; the window in
    which it can be abandoned is the bulkhead's leak. The loop is bounded by
    ``EMERGENCY_STOP_TIMEOUT_SECONDS``, so masking cannot hang the process, and
    SIGKILL is still the operator's escape hatch (RES-16 a claimed
    fault-tolerance mechanism must be exercised before the claim ships,
    ~/Development/heuristics-canon-research/lexicons/engineering.md:127;
    RLSE-05 silent failure is the worst failure, engineering.md:696).
    """

    previous: dict[int, Any] = {}
    for name in (*TERMINATION_SIGNAL_NAMES, "SIGINT"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            previous[int(number)] = signal.signal(number, signal.SIG_IGN)
        except (OSError, ValueError):
            continue
    try:
        yield
    finally:
        for number, handler in previous.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(number, handler)


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


def _snapshot_written_at(snapshot: dict[str, Any]) -> float:
    value = snapshot.get("value")
    written_at = value.get("written_at") if isinstance(value, dict) else None
    if isinstance(written_at, (int, float)) and not isinstance(written_at, bool):
        return float(written_at)
    return float("-inf")


def _read_load_snapshot(source: str) -> dict[str, Any]:
    """Read describe-load evidence from a per-environment root or a single file.

    WBUX6-MRG-02 publishes to ``<load-dir>/<environment>/describe-load.json``, so
    a reader that names one fixed file observes nothing on the deployed host.
    Walk the environments that host actually published, take the freshest
    publication, and always report every candidate scanned: a snapshot that is
    missing must stay distinguishable from one reporting idleness (OBS-08,
    silence is not success).
    """

    directory = Path(source)
    if not directory.is_dir():
        return _load_optional_json(source)
    try:
        candidates = sorted(child / LOAD_SNAPSHOT_FILENAME for child in directory.iterdir() if child.is_dir())
    except OSError as exc:
        return {"availability": "unreadable", "path": source, "error": str(exc)}
    scanned = [str(candidate) for candidate in candidates]
    published = [
        snapshot
        for snapshot in (_load_optional_json(str(candidate)) for candidate in candidates)
        if snapshot.get("availability") == "available"
    ]
    if not published:
        return {"availability": "unavailable", "path": source, "scanned": scanned}
    # WBUX6-W5-04: freshness is not identity. The smoke triggers exactly ONE
    # service, so on a host publishing several environments the freshest
    # snapshot may belong to an environment this run never drove -- the sensor
    # would then be reading a stock the actuator does not control (OBS-12,
    # ~/Development/heuristics-canon-research/lexicons/engineering.md:482).
    # Report the ambiguity instead of resolving it silently; the caller pins the
    # environment with --load-environment.
    return {
        **max(published, key=_snapshot_written_at),
        "scanned": scanned,
        "published_paths": [str(snapshot["path"]) for snapshot in published],
        # A directory without a readable file is still a published environment
        # whose state is unknown.  Counting only readable snapshots would let a
        # fresh file from the wrong environment satisfy this run's load proof.
        "attribution": "environment-pinned" if len(candidates) == 1 else "freshest-of-many",
    }


def _load_source(args: argparse.Namespace) -> str:
    """Resolve where this run reads describe-load evidence from.

    ``--load-json`` names one file outright. ``--load-environment`` names the
    environment this run drove, which is the only identity-grounded reading of
    the per-environment layout. With neither, the reader walks ``--load-dir``
    and must declare its attribution (WBUX6-W5-04).
    """

    if args.load_json:
        return args.load_json
    if args.load_environment:
        return str(Path(args.load_dir) / args.load_environment / LOAD_SNAPSHOT_FILENAME)
    return args.load_dir


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

    def list_stop_events(
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
        # Keep the raw lifecycle snapshots so live evidence has the same
        # gpu_state timeline that FakeOci exposes during a dry run.
        self.observed_gpu_states: list[dict[str, Any]] = []

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
            output_details = ""
            if isinstance(exc, subprocess.CalledProcessError):
                stdout_tail = str(exc.stdout or exc.output or "")[-500:]
                stderr_tail = str(exc.stderr or "")[-500:]
                output_details = f"; stdout tail: {stdout_tail!r}; stderr tail: {stderr_tail!r}"
            raise SmokeFailure(f"OCI command failed: {exc}{output_details}") from exc

    def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, Any]:
        payload = self._run(
            ["compute", "instance", "get", "--instance-id", instance_id],
            timeout=timeout,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise SmokeFailure("OCI instance get returned no data object")
        self.observed_gpu_states.append(dict(data))
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

    def list_stop_events(
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
        return [event for event in data if _is_stop_event(event, instance_id)]


def _default_dry_gpu_states() -> list[dict[str, Any]]:
    """Return the dry snapshot sequence used by the shared transition path.

    The lifecycle file's public ``state`` vocabulary collapses OCI STOPPING to
    ``stopped``.  ``lifecycle_state`` is retained in this deterministic fixture
    so the smoke can exercise the same raw OCI transition sequence as live mode
    while still carrying a valid state-snapshot payload.
    """

    return [
        {
            "state": "stopped",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 0.0,
            "reason": None,
            "since": 0.0,
        },
        {
            "state": "starting",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 1.0,
            "reason": None,
            "since": 1.0,
        },
        {
            "state": "warming",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 2.0,
            "reason": None,
            "since": 2.0,
        },
        {
            "state": "warming",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 3.0,
            "reason": None,
            "since": 3.0,
        },
        {
            "state": "warming",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 4.0,
            "reason": None,
            "since": 4.0,
        },
        {
            "state": "stopped",
            "lifecycle_state": "STOPPING",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 5.0,
            "reason": None,
            "since": 5.0,
        },
        {
            "state": "stopped",
            "instance_id": "<burst-instance-ocid>",
            "written_at": 6.0,
            "reason": None,
            "since": 6.0,
        },
    ]


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
            None,
            None,
            "final_gpu",
        ]
    )
    result_generations: list[int] = field(default_factory=lambda: [0, 0, 0, 1])
    duplicate_enqueue_on_second_poll: bool = False
    gpu_states: list[dict[str, Any]] = field(default_factory=_default_dry_gpu_states)
    load_snapshot_after_trigger: dict[str, Any] | None = field(
        default_factory=lambda: {
            "queue_depth": 0,
            "in_flight": 0,
            "batch_in_progress": True,
        }
    )
    load_snapshot_written_offset_seconds: float = 0.0
    submitted_at: datetime | None = field(default=None, init=False)
    transport_counts: dict[str, int] = field(default_factory=dict, init=False)


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
    payload = DescribeRunItemResponse(**values).model_dump(mode="json")
    # The production response currently omits persistence metadata, but live
    # WordPress fixtures may expose it. Keep these stable fields in the dry
    # transport so the second-poll comparison can prove row identity.
    payload["id"] = f"dry-item-{media_id}"
    payload["created_at"] = _iso_utc(scenario.submitted_at or _utc_now())
    return payload


def make_mock_transport(
    scenario: DryScenario,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> httpx.MockTransport:
    """Return the canned WP/service transport used by the default dry run."""

    polls = 0
    item_polls = 0
    health_polls = 0
    terminal_observed = False
    counts = {
        "requests": 0,
        "health_gets": 0,
        "enqueue_posts": 0,
        "items_gets": 0,
        "run_gets": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal health_polls, item_polls, polls, terminal_observed
        counts["requests"] += 1
        path = request.url.path
        if request.method == "GET" and path == "/health/detailed":
            counts["health_gets"] += 1
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
            counts["enqueue_posts"] += 1
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Basic "):
                return httpx.Response(401, json={"code": "missing_auth"})
            if scenario.submitted_at is None:
                scenario.submitted_at = now()
            return httpx.Response(
                202,
                json={
                    "tenant_id": DRY_TENANT_ID,
                    "run_id": "11111111-1111-4111-8111-111111111111",
                },
            )
        if request.method == "GET" and path.endswith("/items"):
            counts["items_gets"] += 1
            status = scenario.item_statuses[min(item_polls, len(scenario.item_statuses) - 1)]
            tier = scenario.item_tiers[min(item_polls, len(scenario.item_tiers) - 1)]
            result_generation = scenario.result_generations[min(item_polls, len(scenario.result_generations) - 1)]
            item_polls += 1
            rows = [
                _dry_item_payload(
                    scenario,
                    media_id=media_id,
                    status=status,
                    tier=tier,
                    result_generation=result_generation,
                )
                for media_id in scenario.returned_media_ids
            ]
            if scenario.duplicate_enqueue_on_second_poll and terminal_observed and rows:
                duplicate = dict(rows[0])
                duplicate["id"] = f"{duplicate['id']}-duplicate"
                duplicate["created_at"] = _iso_utc(now() + timedelta(seconds=1))
                rows.append(duplicate)
            return httpx.Response(
                200,
                json={
                    "tenant_id": DRY_TENANT_ID,
                    "run_id": "11111111-1111-4111-8111-111111111111",
                    "items": rows,
                },
            )
        if request.method == "GET" and "/recognition/describe/runs/" in path:
            counts["run_gets"] += 1
            status = scenario.run_statuses[min(polls, len(scenario.run_statuses) - 1)]
            polls += 1
            terminal_observed = status in TERMINAL_RUN_STATUSES
            return httpx.Response(
                200,
                json={
                    "tenant_id": DRY_TENANT_ID,
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

    transport = httpx.MockTransport(handler)
    scenario.transport_counts = counts
    # Expose the same counters through the transport for callers that only
    # possess the httpx client (run_smoke's live/dry shared seam).
    transport.transport_counts = counts  # type: ignore[attr-defined]
    transport.counts = counts  # type: ignore[attr-defined]
    return transport


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
    stop_action_count: int = 1
    stop_principal: str | None = DEFAULT_STOP_PRINCIPAL
    stop_principal_id: str | None = "ocid1.dynamicgroup.oc1..gpu-lifecycle"
    stop_event_time: str | None = "2026-01-01T00:00:10Z"
    stop_events: list[dict[str, Any]] | None = None
    gpu_states: list[dict[str, Any]] | None = None
    observed_gpu_states: list[dict[str, Any]] = field(default_factory=list, init=False)
    gpu_states_enabled: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.gpu_states_enabled = self.gpu_states is not None
        if self.gpu_states is not None:
            self.gpu_states = list(self.gpu_states)

    def trigger(self) -> None:
        self.armed = True

    def begin_reaper(self) -> None:
        self.reaping = True

    def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, Any]:
        del timeout
        if self.gpu_states_enabled:
            if self.gpu_states:
                snapshot = self.gpu_states.pop(0)
                self.observed_gpu_states.append(snapshot)
                self.current_state = _gpu_snapshot_lifecycle_state(snapshot)
        else:
            states = self.stop_states if self.stopping else (self.reaper_states if self.reaping else self.startup_states)
            if self.stopping and states or self.armed and states:
                self.current_state = states.pop(0)
        return {
            "id": instance_id,
            "display-name": EXPECTED_GPU_BURST_DISPLAY_NAME,
            "shape": EXPECTED_GPU_BURST_SHAPE,
            "compartment-id": self.compartment_id,
            "lifecycle-state": self.current_state,
            "freeform-tags": dict(EXPECTED_GPU_BURST_TAGS),
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
            "display-name": EXPECTED_GPU_BURST_DISPLAY_NAME,
            "shape": EXPECTED_GPU_BURST_SHAPE,
            "lifecycle-state": self.current_state,
            "freeform-tags": dict(EXPECTED_GPU_BURST_TAGS),
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
                "eventId": f"dry-start-event-{index}",
                "data": {
                    "resourceId": instance_id,
                    "request": {
                        "id": f"dry-start-request-{index}",
                        "parameters": {"action": ["START"]},
                    },
                },
            }
            for index in range(self.start_action_count)
        ]

    def list_stop_events(
        self,
        compartment_id: str,
        instance_id: str,
        *,
        start_time: str,
        end_time: str,
        timeout: float,
    ) -> list[dict[str, Any]]:
        del compartment_id, end_time, start_time, timeout
        if self.stop_events is not None:
            return list(self.stop_events)
        if self.stop_action_count <= 0 or self.current_state != "STOPPED":
            return []
        return [
            {
                "eventType": "com.oraclecloud.computeapi.instanceaction.end",
                "eventId": f"dry-stop-event-{index}",
                "eventTime": self.stop_event_time,
                "data": {
                    "resourceId": instance_id,
                    "identity": {
                        "principalName": self.stop_principal,
                        "principalId": self.stop_principal_id,
                    },
                    "request": {
                        "id": f"dry-stop-request-{index}",
                        "parameters": {"action": ["StopInstance"]},
                    },
                },
            }
            for index in range(self.stop_action_count)
        ]


@dataclass
class SmokeResult:
    exit_code: int
    evidence: dict[str, Any]
    stop_principal: str | None = None
    stop_event_time: str | None = None


def _state(data: dict[str, Any]) -> str:
    return str(data.get("lifecycle-state") or data.get("lifecycle_state") or "UNKNOWN").upper()


def _compartment_id(data: dict[str, Any]) -> str:
    value = data.get("compartment-id") or data.get("compartment_id")
    if not isinstance(value, str) or not value:
        raise SmokeFailure("OCI instance has no compartment id")
    return value


def _gpu_burst_identity_mismatches(instance: Mapping[str, Any]) -> list[str]:
    name = instance.get("display-name") or instance.get("display_name")
    shape = instance.get("shape")
    freeform = instance.get("freeform-tags") or instance.get("freeform_tags")
    mismatches: list[str] = []
    if name != EXPECTED_GPU_BURST_DISPLAY_NAME:
        mismatches.append(f"display-name={name!r}")
    if shape != EXPECTED_GPU_BURST_SHAPE:
        mismatches.append(f"shape={shape!r}")
    if not isinstance(freeform, Mapping):
        return [*mismatches, "freeform-tags is not an object"]
    for key, expected in EXPECTED_GPU_BURST_TAGS.items():
        if freeform.get(key) != expected:
            mismatches.append(f"freeform-tags.{key}={freeform.get(key)!r}")
    return mismatches


def _is_gpu_burst(instance: dict[str, Any]) -> bool:
    """Require the complete Terraform-owned identity before any lifecycle action."""

    return not _gpu_burst_identity_mismatches(instance)


def _has_gpu_burst_ownership_tag(instance: Mapping[str, Any]) -> bool:
    """Scope orphan discovery by the stable ownership role, not mutable identity."""

    freeform = instance.get("freeform-tags") or instance.get("freeform_tags")
    return isinstance(freeform, Mapping) and freeform.get("role") == EXPECTED_GPU_BURST_TAGS["role"]


def _is_start_event(event: dict[str, Any], instance_id: str) -> bool:
    # OCI Audit emits begin/end records for one action.  Only the completed
    # record is authoritative, otherwise a single START is counted twice.
    if not str(event.get("eventType") or "").endswith(".end"):
        return False
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


def _audit_event_data(event: dict[str, Any]) -> dict[str, Any] | None:
    data = event.get("data")
    return data if isinstance(data, dict) else None


def _audit_resource_id(event: dict[str, Any]) -> str | None:
    data = _audit_event_data(event)
    if data is None:
        return None
    value = data.get("resourceId") or data.get("resource_id")
    return value if isinstance(value, str) else None


def _audit_action_values(event: dict[str, Any]) -> list[Any]:
    data = _audit_event_data(event) or {}
    request = data.get("request")
    request = request if isinstance(request, dict) else {}
    parameters = request.get("parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    values: list[Any] = []
    for candidate in (
        parameters.get("action"),
        request.get("action"),
        data.get("action"),
        event.get("action"),
        event.get("requestAction"),
    ):
        if isinstance(candidate, list):
            values.extend(candidate)
        elif candidate is not None:
            values.append(candidate)
    return values


def _normalized_audit_action(value: Any) -> str:
    return re.sub(r"[^A-Z]", "", str(value).upper())


def _is_stop_event(event: dict[str, Any], instance_id: str) -> bool:
    """Return whether an OCI Audit end record is a STOP for this instance."""

    if not str(event.get("eventType") or "").endswith(".end"):
        return False
    if _audit_resource_id(event) != instance_id:
        return False
    return any(
        _normalized_audit_action(value) in {"STOP", "STOPINSTANCE"}
        for value in _audit_action_values(event)
    )


def _stop_event_identity(event: dict[str, Any]) -> str:
    data = _audit_event_data(event) or {}
    request = data.get("request")
    request_id = request.get("id") if isinstance(request, dict) else None
    return str(request_id or event.get("eventId") or json.dumps(event, sort_keys=True))


def _unique_stop_events(events: Sequence[dict[str, Any]], instance_id: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for event in events:
        if _is_stop_event(event, instance_id):
            unique.setdefault(_stop_event_identity(event), event)
    return list(unique.values())


def _audit_identity(event: dict[str, Any]) -> dict[str, Any]:
    data = _audit_event_data(event) or {}
    for container in (data, event):
        identity = container.get("identity")
        if isinstance(identity, dict):
            return identity
    return {}


def _stop_event_principals(event: dict[str, Any]) -> list[str]:
    identity = _audit_identity(event)
    principals: list[str] = []
    for key in ("principalName", "principalId", "principal_name", "principal_id"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip() and value not in principals:
            principals.append(value)
    return principals


def _audit_event_time(event: dict[str, Any]) -> str | None:
    data = _audit_event_data(event) or {}
    for container in (event, data):
        for key in ("eventTime", "event_time", "timeCreated", "time_created"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _parse_audit_event_time(value: str) -> datetime | None:
    """Parse an OCI Audit timestamp, treating a timezone-less value as UTC."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _audit_time_sort_key(event: dict[str, Any]) -> tuple[int, float | str]:
    value = _audit_event_time(event)
    if value is None:
        return (1, "")
    parsed = _parse_audit_event_time(value)
    return (0, parsed.timestamp()) if parsed is not None else (1, value)


def _first_stop_event(events: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    return min(events, key=_audit_time_sort_key) if events else None


def _stop_events_in_window(
    events: Sequence[dict[str, Any]],
    instance_id: str,
    *,
    start_time: str,
    end_time: str,
) -> list[dict[str, Any]]:
    """Keep only timestamped STOP records for this instance in the query window.

    The OCI CLI applies the window server-side, but dry fakes and wrapped clients
    do not necessarily do so. Re-checking it locally keeps an old or malformed
    audit record from proving a STOP that happened outside this smoke run.
    """

    start = _parse_audit_event_time(start_time)
    end = _parse_audit_event_time(end_time)
    if start is None or end is None or end < start:
        return []
    in_window: list[dict[str, Any]] = []
    for event in events:
        if not _is_stop_event(event, instance_id):
            continue
        event_time = _audit_event_time(event)
        parsed_event_time = _parse_audit_event_time(event_time) if event_time is not None else None
        if parsed_event_time is not None and start <= parsed_event_time <= end:
            in_window.append(event)
    return in_window


def _gpu_snapshot_lifecycle_state(snapshot: Mapping[str, Any]) -> str:
    """Map a lifecycle snapshot (or an OCI state alias) to smoke states."""

    raw = next(
        (
            snapshot.get(key)
            for key in ("lifecycle-state", "lifecycle_state", "instance-state", "instance_state", "state")
            if snapshot.get(key) is not None
        ),
        "UNKNOWN",
    )
    state = str(raw).upper()
    if state in {"WARMING", "READY"}:
        return "RUNNING"
    if state in {"STOPPED", "STARTING", "RUNNING", "STOPPING"}:
        return state
    return "UNKNOWN"


def _start_event_identity(event: dict[str, Any]) -> str:
    data = event.get("data")
    request = data.get("request") if isinstance(data, dict) else None
    request_id = request.get("id") if isinstance(request, dict) else None
    return str(request_id or event.get("eventId") or json.dumps(event, sort_keys=True))


def _unique_start_events(events: Sequence[dict[str, Any]], instance_id: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for event in events:
        if _is_start_event(event, instance_id):
            unique.setdefault(_start_event_identity(event), event)
    return list(unique.values())


def _load_snapshot_has_fresh_work(
    snapshot: dict[str, Any],
    *,
    freshness_anchor: datetime,
) -> tuple[bool, str]:
    if snapshot.get("availability") != "available" or not isinstance(snapshot.get("value"), dict):
        return False, (
            f"snapshot {snapshot.get('availability', 'invalid')} after pre-submit "
            f"freshness_anchor={_iso_utc(freshness_anchor)}"
        )
    # WBUX6-W5-04: a snapshot picked by freshness out of several published
    # environments is not evidence that THIS run's trigger produced the load.
    # Refuse rather than attribute another environment's work to this run
    # (OBS-12 sensors must touch the controlled stock, engineering.md:482;
    # RLSE-05 silent failure is the worst failure, engineering.md:696).
    if snapshot.get("attribution") == "freshest-of-many":
        return False, (
            "load snapshot is ambiguous: "
            f"{len(snapshot.get('published_paths', []))} environments published under "
            f"{snapshot.get('path')!r}'s root and this run drove only one; "
            "re-run with --load-environment <env> so the reading is identity-grounded; "
            f"published={snapshot.get('published_paths')}"
        )
    value = snapshot["value"]
    written_at = value.get("written_at")
    fresh = isinstance(written_at, (int, float)) and not isinstance(written_at, bool)
    earliest_fresh_timestamp = freshness_anchor.timestamp() - LOAD_SNAPSHOT_SKEW_SECONDS
    fresh = fresh and float(written_at) >= earliest_fresh_timestamp
    counts = (value.get("queue_depth"), value.get("in_flight"))
    counts_valid = all(isinstance(count, int) and not isinstance(count, bool) and count >= 0 for count in counts)
    batch_value = value.get("batch_in_progress")
    batch_valid = isinstance(batch_value, bool)
    pending = sum(counts) + int(batch_value) if counts_valid and batch_valid else 0
    observed = bool(fresh and counts_valid and batch_valid and pending > 0)
    return observed, (
        f"fresh={fresh}; pending={pending}; batch_in_progress={batch_value!r}; written_at={written_at!r}; "
        f"freshness_anchor={_iso_utc(freshness_anchor)}; skew_seconds={LOAD_SNAPSHOT_SKEW_SECONDS}"
    )


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


def _run_envelope(body: Mapping[str, Any], *, endpoint: str) -> tuple[str, str]:
    """Read the tenant/run envelope returned by an untrusted HTTP boundary."""

    run_id = body.get("run_id")
    tenant_id = body.get("tenant_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise SmokeFailure(f"{endpoint} response has no non-empty run_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise SmokeFailure(f"{endpoint} response has no non-empty tenant_id")
    return run_id, tenant_id


def _validate_run_envelope(
    body: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_tenant_id: str,
    endpoint: str,
) -> None:
    """Bind a status/items response to the run and tenant established at submit."""

    run_id, tenant_id = _run_envelope(body, endpoint=endpoint)
    if run_id != expected_run_id:
        raise SmokeFailure(
            f"{endpoint} response run_id {run_id!r} does not match expected {expected_run_id!r}"
        )
    if tenant_id != expected_tenant_id:
        raise SmokeFailure(
            f"{endpoint} response tenant_id {tenant_id!r} does not match expected {expected_tenant_id!r}"
        )


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


def _queue_item_identity(item: Mapping[str, Any]) -> tuple[str, str]:
    """Choose a stable persisted-row identity for the second-poll proof."""

    for key in ("id", "item_id", "itemId"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return key, str(value)
    for key in ("created_at", "createdAt"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return key, str(value)
    # The current describe-items contract has no persistence id. A media id +
    # generation is the strongest stable fallback and still catches a second
    # row when its generation differs or the response contains duplicate rows.
    return (
        "media_id_generation",
        f"{item.get('media_id', 'unavailable')}:{item.get('result_generation', 'unavailable')}",
    )


def _new_queue_items(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before_counts = Counter(_queue_item_identity(item) for item in before)
    after_counts = Counter(_queue_item_identity(item) for item in after)
    new_items: list[dict[str, Any]] = []
    for identity, count in sorted(after_counts.items()):
        delta = count - before_counts.get(identity, 0)
        if delta > 0:
            new_items.append({"identity": list(identity), "count": delta})
    return new_items


def _client_transport_counts(client: httpx.Client) -> Mapping[str, int] | None:
    """Read optional counters exposed by the dry MockTransport."""

    transport = getattr(client, "_transport", None)
    for attribute in ("transport_counts", "counts"):
        counts = getattr(transport, attribute, None)
        if isinstance(counts, Mapping):
            return counts
    return None


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


@dataclass
class _SmokeExecution:
    args: argparse.Namespace
    client: httpx.Client
    oci: OciClient
    app_password: str
    service_api_key: str
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    now: Callable[[], datetime]
    load_snapshot_reader: Callable[[str], dict[str, Any]]
    deadline: Deadline = field(init=False)
    checks: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    item_timeline: list[dict[str, Any]] = field(default_factory=list)
    service_health_samples: list[dict[str, Any]] = field(default_factory=list)
    denylist_verdicts: list[dict[str, Any]] = field(default_factory=list)
    run_id: str = "unavailable"
    tenant_id: str = "unavailable"
    run_status: str = "unavailable"
    start_action_evidence: dict[str, Any] = field(
        default_factory=lambda: {"source": "oci_audit", "status": "unavailable", "count": 0}
    )
    stop_action_evidence: dict[str, Any] = field(
        default_factory=lambda: {"source": "oci_audit", "status": "unavailable", "count": 0}
    )
    second_burst_evidence: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "not_attempted",
            "new_items": [],
            "enqueue_posts_during_poll": None,
            "enqueue_posts_during_replay": None,
            "transport_telemetry_available": None,
            "idempotent_response": None,
        }
    )
    stop_principal: str | None = None
    stop_event_time: str | None = None
    preflight_refused: bool = False
    instance_validated: bool = False
    compartment_id: str = "unavailable"
    run_window_started_at: str = "unavailable"
    trigger_elapsed: float = 0.0
    reaper_stopped: bool = False
    gpu_snapshot: dict[str, Any] = field(init=False)
    load_source: str = field(init=False)
    load_snapshot_before_trigger: dict[str, Any] = field(init=False)
    load_snapshot_after_trigger: dict[str, Any] = field(init=False)
    phase_durations_seconds: dict[str, float] = field(default_factory=dict)
    auth: httpx.BasicAuth | None = None
    running_observed: bool = False
    terminal_before_running: set[int | str] = field(default_factory=set)
    degraded_items: set[int | str] = field(default_factory=set)
    generations_by_media_id: dict[int | str, list[tuple[str, int]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.deadline = Deadline(float(self.args.max_seconds), self.monotonic)
        self.gpu_snapshot = _load_optional_json(self.args.gpu_state_json)
        self.load_source = _load_source(self.args)
        self.load_snapshot_before_trigger = self.load_snapshot_reader(self.load_source)
        self.load_snapshot_after_trigger = {
            "availability": "unavailable",
            "path": self.load_source,
        }

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})


def _record_health(run: _SmokeExecution, phase: str, health: dict[str, Any]) -> bool:
    healthy = health.get("status") == "ok" and health.get("description_adapter") == "gpu_qwen30b"
    run.service_health_samples.append(
        {
            "elapsed_seconds": round(run.deadline.elapsed(), 3),
            "phase": phase,
            "status": str(health.get("status") or "unknown"),
            "description_adapter": str(health.get("description_adapter") or "unknown"),
            "healthy": healthy,
        }
    )
    return healthy


def _poll_health(run: _SmokeExecution, phase: str, *, request_deadline: Deadline | None = None) -> None:
    try:
        health = _request_json(
            run.client,
            "GET",
            f"{run.args.service_base_url.rstrip('/')}/health/detailed",
            deadline=request_deadline or run.deadline,
            headers={"Authorization": f"Bearer {run.service_api_key}"},
        )
    except SmokeFailure as exc:
        run.service_health_samples.append(
            {
                "elapsed_seconds": round(run.deadline.elapsed(), 3),
                "phase": phase,
                "status": "request_failed",
                "description_adapter": "unknown",
                "healthy": False,
                "detail": str(exc),
            }
        )
        raise
    if not _record_health(run, phase, health):
        raise SmokeFailure(
            f"description service unhealthy during {phase}: "
            f"status={health.get('status')}, adapter={health.get('description_adapter')}"
        )


def _poll_items(run: _SmokeExecution, *, record_timeline: bool = True) -> list[dict[str, Any]]:
    if run.auth is None:
        raise SmokeFailure("WordPress authentication was not initialized")
    item_body = _request_json(
        run.client,
        "GET",
        f"{run.args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs/{run.run_id}/items",
        deadline=run.deadline,
        auth=run.auth,
    )
    _validate_run_envelope(
        item_body,
        expected_run_id=run.run_id,
        expected_tenant_id=run.tenant_id,
        endpoint="items",
    )
    fetched_items = _validate_items_payload(item_body.get("items"))
    if not record_timeline:
        return fetched_items
    run.items = fetched_items
    elapsed = round(run.deadline.elapsed(), 3)
    for item in fetched_items:
        media_id = item.get("media_id", "unavailable")
        status = str(item.get("status") or "unknown")
        tier = item.get("tier")
        result_generation = int(item.get("result_generation", 0))
        run.item_timeline.append(
            {
                "elapsed_seconds": elapsed,
                "media_id": media_id,
                "status": status,
                "tier": tier,
                "result_generation": result_generation,
            }
        )
        if isinstance(tier, str):
            observations = run.generations_by_media_id.setdefault(media_id, [])
            observation = (tier, result_generation)
            if not observations or observations[-1] != observation:
                observations.append(observation)
        if not run.running_observed and status in TERMINAL_ITEM_STATUSES:
            run.terminal_before_running.add(media_id)
        if status == "completed" and tier == "provisional_cpu":
            run.degraded_items.add(media_id)
    return fetched_items


def _preflight(run: _SmokeExecution) -> None:
    try:
        try:
            health = _request_json(
                run.client,
                "GET",
                f"{run.args.service_base_url.rstrip('/')}/health/detailed",
                deadline=run.deadline,
                headers={"Authorization": f"Bearer {run.service_api_key}"},
            )
        except HttpStatusFailure as exc:
            if exc.status_code in {401, 403}:
                run.check("service_auth", False, f"HTTP {exc.status_code}")
                run.preflight_refused = True
                raise PreflightRefusal("description service rejected bearer authentication") from exc
            raise
        health_ok = _record_health(run, "preflight", health)
        run.check("service_auth", True, "bearer authentication accepted")
        adapter_ok = health.get("description_adapter") == "gpu_qwen30b"
        run.check("health_adapter_gpu_qwen30b", adapter_ok, str(health.get("description_adapter")))
        if not adapter_ok:
            run.preflight_refused = True
            raise PreflightRefusal("description service is not using gpu_qwen30b")
        run.check("service_health_preflight", health_ok, str(health.get("status")))
        if not health_ok:
            run.preflight_refused = True
            raise PreflightRefusal("description service is unhealthy at preflight")

        initial = run.oci.get_instance(
            run.args.instance_id,
            timeout=run.deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
        )
        run.compartment_id = _compartment_id(initial)
        identity_matches = str(initial.get("id")) == run.args.instance_id
        run.check(
            "instance_identity_matches",
            identity_matches,
            "requested instance identity verified"
            if identity_matches
            else "OCI response identity does not match the requested instance",
        )
        identity_mismatches = _gpu_burst_identity_mismatches(initial)
        dedicated_instance = not identity_mismatches
        run.check(
            "instance_dedicated_gpu_burst",
            dedicated_instance,
            "dedicated gpu-burst identity verified"
            if dedicated_instance
            else "instance metadata does not match the Terraform-owned A10 burst contract: "
            + ", ".join(identity_mismatches),
        )
        if not identity_matches or not dedicated_instance:
            run.preflight_refused = True
            raise PreflightRefusal("instance identity or dedicated gpu-burst ownership is invalid")
        initial_state = _state(initial)
        _record_transition(run.transitions, initial_state, elapsed=run.deadline.elapsed(), now=run.now)
        run.check("initial_instance_stopped", initial_state == "STOPPED", initial_state)
        if initial_state != "STOPPED":
            run.preflight_refused = True
            raise PreflightRefusal(f"burst instance must start STOPPED, got {initial_state}")
        run.instance_validated = True
    except SmokeFailure as exc:
        run.check("preflight", False, str(exc))
        run.preflight_refused = True
        raise PreflightRefusal(str(exc)) from exc


def _submit_and_observe_load(run: _SmokeExecution) -> None:
    run.auth = httpx.BasicAuth(run.args.wp_user, run.app_password)
    load_freshness_anchor = run.now()
    run.run_window_started_at = _iso_utc(load_freshness_anchor)
    load_ready, load_detail = _load_snapshot_has_fresh_work(
        run.load_snapshot_before_trigger,
        freshness_anchor=load_freshness_anchor,
    )
    run.check("load_snapshot_ready_before_trigger", load_ready, load_detail)
    if not load_ready:
        run.check("load_snapshot_observed_after_trigger", False, load_detail)
        raise SmokeFailure(f"load snapshot precondition failed before enqueue: {load_detail}")
    submitted = _request_json(
        run.client,
        "POST",
        f"{run.args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs",
        deadline=run.deadline,
        auth=run.auth,
        payload={"media_ids": run.args.media_ids},
    )
    candidate_run_id, candidate_tenant_id = _run_envelope(submitted, endpoint="submit")
    run.run_id = candidate_run_id
    run.tenant_id = candidate_tenant_id
    run.trigger_elapsed = run.deadline.elapsed()
    trigger = getattr(run.oci, "trigger", None)
    if callable(trigger):
        trigger()

    load_observation_deadline = Deadline(
        min(LOAD_SNAPSHOT_OBSERVATION_SECONDS, max(0.0, run.deadline.remaining())),
        run.monotonic,
    )
    while True:
        run.load_snapshot_after_trigger = run.load_snapshot_reader(run.load_source)
        load_observed, load_detail = _load_snapshot_has_fresh_work(
            run.load_snapshot_after_trigger,
            freshness_anchor=load_freshness_anchor,
        )
        if load_observed or load_observation_deadline.remaining() <= 0 or run.deadline.remaining() <= 0:
            break
        run.sleep(min(POLL_SECONDS, load_observation_deadline.remaining(), run.deadline.remaining()))
    run.check("load_snapshot_observed_after_trigger", load_observed, load_detail)
    if not load_observed:
        # Do not warm or process after the actuator/sensor link failed.  The
        # enqueue already happened, so finally-stop still owns cleanup, but
        # continuing here could turn an unproven load into GPU spend.
        raise SmokeFailure(f"load snapshot observation failed after enqueue: {load_detail}")


def _warm_and_process(run: _SmokeExecution) -> None:
    warm_started = False
    warm_start_started = run.deadline.elapsed()
    warm_start_budget_ok = True
    while not warm_started:
        warm_start_elapsed = run.deadline.elapsed() - warm_start_started
        if warm_start_elapsed >= WARM_START_BUDGET_SECONDS:
            warm_start_budget_ok = False
            run.check(
                "warm_start_budget",
                False,
                f"warm start exceeded {WARM_START_BUDGET_SECONDS:g}s budget at {warm_start_elapsed:.3f}s",
            )
            break
        try:
            run.deadline.check("waiting for GPU warm start")
        except SmokeFailure as exc:
            run.check("deadline", False, str(exc))
            break
        observed = run.oci.get_instance(
            run.args.instance_id,
            timeout=run.deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
        )
        observed_state = _state(observed)
        _record_transition(run.transitions, observed_state, elapsed=run.deadline.elapsed(), now=run.now)
        warm_started = observed_state == "RUNNING"
        run.running_observed = run.running_observed or warm_started
        _poll_items(run)
        _poll_health(run, "warm_up")
        if not warm_started:
            run.sleep(POLL_SECONDS)
    if warm_start_budget_ok:
        run.check(
            "warm_start_budget",
            warm_started or run.deadline.elapsed() - warm_start_started < WARM_START_BUDGET_SECONDS,
            (
                f"warm start completed in {run.deadline.elapsed() - warm_start_started:.3f}s"
                if warm_started
                else f"overall deadline ended before {WARM_START_BUDGET_SECONDS:g}s warm-start budget"
            ),
        )
    run.check(
        "warm_start_running",
        warm_started,
        "RUNNING" if warm_started else "deadline before RUNNING",
    )
    if warm_started:
        run.phase_durations_seconds["warm_start"] = round(
            run.deadline.elapsed() - run.trigger_elapsed,
            3,
        )
    processing_started = run.deadline.elapsed()

    while warm_started and run.run_status not in TERMINAL_RUN_STATUSES:
        try:
            run.deadline.check("polling WordPress run")
        except SmokeFailure as exc:
            run.check("deadline", False, str(exc))
            break
        observed = run.oci.get_instance(
            run.args.instance_id,
            timeout=run.deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
        )
        observed_state = _state(observed)
        _record_transition(run.transitions, observed_state, elapsed=run.deadline.elapsed(), now=run.now)
        run.running_observed = run.running_observed or observed_state == "RUNNING"
        _poll_items(run)
        _poll_health(run, "processing")
        if run.auth is None:
            raise SmokeFailure("WordPress authentication was not initialized")
        flow = _request_json(
            run.client,
            "GET",
            f"{run.args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs/{run.run_id}",
            deadline=run.deadline,
            auth=run.auth,
        )
        _validate_run_envelope(
            flow,
            expected_run_id=run.run_id,
            expected_tenant_id=run.tenant_id,
            endpoint="status",
        )
        run.run_status = str(flow.get("status") or "unknown")
        if run.run_status not in TERMINAL_RUN_STATUSES:
            run.sleep(POLL_SECONDS)

    run.check("run_terminal_success", run.run_status in SUCCESS_RUN_STATUSES, run.run_status)
    run.phase_durations_seconds["processing"] = round(
        run.deadline.elapsed() - processing_started,
        3,
    )


def _validate_completed_items(run: _SmokeExecution) -> None:
    run.check(
        "no_item_terminal_before_running",
        not run.terminal_before_running,
        f"offending media_ids: {sorted(run.terminal_before_running, key=str)}",
    )
    run.check(
        "no_degraded_items",
        not run.degraded_items,
        f"offending media_ids: {sorted(run.degraded_items, key=str)}",
    )

    returned_media_id_rows = [item.get("media_id") for item in run.items]
    duplicate_ids = {media_id for media_id in returned_media_id_rows if returned_media_id_rows.count(media_id) > 1}
    if duplicate_ids:
        raise SmokeFailure(f"duplicate media_id rows returned: {sorted(duplicate_ids, key=str)}")
    requested_ids = set(run.args.media_ids)
    returned_ids = set(returned_media_id_rows)
    run.check(
        "returned_media_ids_exact",
        returned_ids == requested_ids,
        f"expected {sorted(requested_ids)}; returned {sorted(returned_ids, key=str)}",
    )
    items_by_id = {item.get("media_id"): item for item in run.items}
    missing_ids = requested_ids - returned_ids
    incomplete_ids = {
        media_id
        for media_id in requested_ids
        if media_id in items_by_id and items_by_id[media_id].get("status") != "completed"
    }
    run.check(
        "all_items_completed",
        not missing_ids and not incomplete_ids,
        f"missing media_ids: {sorted(missing_ids)}; non-completed media_ids: {sorted(incomplete_ids)}",
    )

    requested_items = [items_by_id[media_id] for media_id in run.args.media_ids if media_id in items_by_id]
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
    run.check("tier_final_gpu", not wrong_tier_ids, f"offending media_ids: {sorted(wrong_tier_ids)}")

    denied_ids: set[int] = set(missing_ids)
    for item in requested_items:
        for field_name in ("caption", "alt_text_draft"):
            sample = item.get(field_name) or ""
            denied = not bool(str(sample).strip()) or fixture_sample_is_denied(str(sample))
            run.denylist_verdicts.append(
                {
                    "media_id": item.get("media_id", "unavailable"),
                    "field": field_name,
                    "denied": denied,
                    "sample": str(sample),
                }
            )
            if denied:
                denied_ids.add(item["media_id"])
    run.check("caption_not_fixture", not denied_ids, f"offending media_ids: {sorted(denied_ids)}")
    run.check(
        "model_id_qwen30b",
        not wrong_model_ids,
        f"offending media_ids: {sorted(wrong_model_ids)}; expected {EXPECTED_MODEL_ID}",
    )
    run.check(
        "model_revision_pinned",
        not wrong_revision_ids,
        f"offending media_ids: {sorted(wrong_revision_ids)}; expected {EXPECTED_REVISION}",
    )

    non_superseded_ids: set[int] = set(missing_ids)
    for media_id in requested_ids - missing_ids:
        observations = run.generations_by_media_id.get(media_id, [])
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
    run.check(
        "provisional_superseded_by_final",
        not non_superseded_ids,
        f"offending media_ids: {sorted(non_superseded_ids)}",
    )


def _wait_for_reaper(run: _SmokeExecution) -> None:
    begin_reaper = getattr(run.oci, "begin_reaper", None)
    if callable(begin_reaper):
        begin_reaper()
    reaper_started = run.deadline.elapsed()
    idle_reaper_budget_ok = True
    reaper_budget_ok = True
    reaper_stop_started: float | None = None
    while not run.reaper_stopped:
        reaper_elapsed = run.deadline.elapsed() - reaper_started
        if reaper_stop_started is None and reaper_elapsed >= IDLE_REAPER_SECONDS:
            idle_reaper_budget_ok = False
            run.check(
                "idle_reaper_budget",
                False,
                f"idle reaper exceeded {IDLE_REAPER_SECONDS:g}s budget at {reaper_elapsed:.3f}s",
            )
            break
        if reaper_stop_started is not None and run.deadline.elapsed() - reaper_stop_started >= REAPER_BUDGET_SECONDS:
            reaper_budget_ok = False
            run.check(
                "reaper_budget",
                False,
                f"reaper STOP convergence exceeded {REAPER_BUDGET_SECONDS:g}s budget",
            )
            break
        try:
            run.deadline.check("waiting for idle reaper STOPPED")
        except SmokeFailure as exc:
            if not any(existing["name"] == "deadline" for existing in run.checks):
                run.check("deadline", False, str(exc))
            break
        observed = run.oci.get_instance(
            run.args.instance_id,
            timeout=run.deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
        )
        observed_state = _state(observed)
        _record_transition(run.transitions, observed_state, elapsed=run.deadline.elapsed(), now=run.now)
        if observed_state == "STOPPING" and reaper_stop_started is None:
            reaper_stop_started = run.deadline.elapsed()
        run.reaper_stopped = observed_state == "STOPPED"
        _poll_health(run, "recovery" if run.reaper_stopped else "drain")
        if not run.reaper_stopped:
            run.sleep(POLL_SECONDS)
    if idle_reaper_budget_ok:
        run.check(
            "idle_reaper_budget",
            True,
            f"idle reaper completed within {IDLE_REAPER_SECONDS:g}s budget",
        )
    if reaper_budget_ok:
        run.check(
            "reaper_budget",
            True,
            (
                "STOP convergence was not needed"
                if reaper_stop_started is None
                else f"STOP convergence completed within {REAPER_BUDGET_SECONDS:g}s budget"
            ),
        )
    run.check(
        "instance_stopped_after_reaper",
        run.reaper_stopped,
        "STOPPED" if run.reaper_stopped else "deadline before STOPPED",
    )
    run.phase_durations_seconds["idle_reaper"] = round(
        run.deadline.elapsed() - reaper_started,
        3,
    )


def _audit_start_and_second_poll(run: _SmokeExecution) -> None:
    audit_started = run.deadline.elapsed()
    audit_deadline = Deadline(AUDIT_INDEX_TIMEOUT_SECONDS, run.monotonic)
    start_events: list[dict[str, Any]] = []
    audit_attempted = False
    while not start_events:
        try:
            if audit_attempted:
                audit_deadline.check("waiting for OCI Audit START event indexing")
                run.deadline.check("waiting for OCI Audit START event indexing")
            audit_timeout = min(
                audit_deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
                run.deadline.timeout(OCI_CALL_TIMEOUT_SECONDS),
            )
        except SmokeFailure:
            break
        audit_attempted = True
        raw_start_events = run.oci.list_start_events(
            run.compartment_id,
            run.args.instance_id,
            start_time=run.run_window_started_at,
            end_time=_iso_utc(run.now()),
            timeout=audit_timeout,
        )
        start_events = _unique_start_events(raw_start_events, run.args.instance_id)
        if start_events:
            break
        run.sleep(POLL_SECONDS)
    audit_lag_seconds = round(run.deadline.elapsed() - audit_started, 3)
    run.phase_durations_seconds["audit_index"] = audit_lag_seconds
    run.start_action_evidence = {
        "source": "oci_audit",
        "status": "observed" if start_events else "not_indexed",
        "count": len(start_events),
        "audit_lag_seconds": audit_lag_seconds,
        "window_start": run.run_window_started_at,
        "window_end": _iso_utc(run.now()),
    }
    run.check(
        "exactly_one_start_action",
        len(start_events) == 1,
        (
            f"observed {len(start_events)} authoritative START action(s)"
            if start_events
            else f"zero START events indexed after {audit_lag_seconds:.3f}s"
        ),
    )
    if run.reaper_stopped and run.items:
        before_second_poll = [dict(item) for item in run.items]
        counts_before_replay = _client_transport_counts(run.client)
        enqueue_before_replay = (
            counts_before_replay.get("enqueue_posts") if counts_before_replay is not None else None
        )
        try:
            if run.auth is None:
                raise SmokeFailure("WordPress authentication was not initialized")
            replay = _request_json(
                run.client,
                "POST",
                f"{run.args.wp_base_url.rstrip('/')}/wp-json/acx/v1/recognition/describe/runs",
                deadline=run.deadline,
                auth=run.auth,
                payload={"media_ids": run.args.media_ids},
            )
            replay_run_id, replay_tenant_id = _run_envelope(replay, endpoint="second enqueue")
            idempotent_response = replay_run_id == run.run_id and replay_tenant_id == run.tenant_id
            if not idempotent_response:
                raise SmokeFailure(
                    "second enqueue response is not idempotent: "
                    f"run_id={replay_run_id!r}, tenant_id={replay_tenant_id!r}"
                )
            counts_after_replay = _client_transport_counts(run.client)
            enqueue_after_replay = (
                counts_after_replay.get("enqueue_posts") if counts_after_replay is not None else None
            )
            enqueue_replay_delta = (
                int(enqueue_after_replay) - int(enqueue_before_replay)
                if enqueue_before_replay is not None and enqueue_after_replay is not None
                else None
            )
            after_second_poll = _poll_items(run, record_timeline=False)
            counts_after_poll = _client_transport_counts(run.client)
            enqueue_after_poll = counts_after_poll.get("enqueue_posts") if counts_after_poll is not None else None
            enqueue_poll_delta = (
                int(enqueue_after_poll) - int(enqueue_after_replay)
                if enqueue_after_poll is not None and enqueue_after_replay is not None
                else None
            )
            new_items = _new_queue_items(before_second_poll, after_second_poll)
            telemetry_available = (
                enqueue_before_replay is not None
                and enqueue_after_replay is not None
                and enqueue_after_poll is not None
            )
            no_new_items = not new_items
            # Live HTTPTransport does not expose the dry MockTransport's
            # request counters.  The replay response is the authoritative
            # idempotence proof there: a duplicate enqueue would return a new
            # run envelope, while the follow-up item comparison catches an
            # extra persisted row in a reused run.
            replay_post_observed = not telemetry_available or enqueue_replay_delta == 1
            no_duplicate_replay = idempotent_response and no_new_items and replay_post_observed
            no_enqueue_during_poll = not telemetry_available or enqueue_poll_delta == 0
            passed = no_duplicate_replay and no_enqueue_during_poll
            run.second_burst_evidence = {
                "status": "observed" if passed else "failed",
                "items_before": [list(_queue_item_identity(item)) for item in before_second_poll],
                "items_after": [list(_queue_item_identity(item)) for item in after_second_poll],
                "new_items": new_items,
                "enqueue_posts_before": enqueue_before_replay,
                "enqueue_posts_after_replay": enqueue_after_replay,
                "enqueue_posts_after": enqueue_after_poll,
                "enqueue_posts_during_replay": enqueue_replay_delta,
                "enqueue_posts_during_poll": enqueue_poll_delta,
                "transport_telemetry_available": telemetry_available,
                "idempotent_response": idempotent_response,
            }
            run.check(
                "second_burst_no_enqueue",
                passed,
                (
                    "idempotent replay created no new item and the follow-up poll issued zero enqueue POSTs"
                    if passed
                    else (
                        "idempotent replay or persisted-item comparison failed"
                        if not telemetry_available
                        else (
                            f"new_items={new_items}; enqueue_posts_during_replay={enqueue_replay_delta!r}; "
                            f"enqueue_posts_during_poll={enqueue_poll_delta!r}; "
                            f"idempotent_response={idempotent_response!r}"
                        )
                    )
                ),
            )
        except (SmokeFailure, OSError, ValueError) as exc:
            counts_after_failure = _client_transport_counts(run.client)
            enqueue_after_failure = (
                counts_after_failure.get("enqueue_posts") if counts_after_failure is not None else None
            )
            enqueue_replay_delta = (
                int(enqueue_after_failure) - int(enqueue_before_replay)
                if enqueue_before_replay is not None and enqueue_after_failure is not None
                else None
            )
            run.second_burst_evidence = {
                "status": "failed",
                "new_items": [],
                "enqueue_posts_during_poll": None,
                "enqueue_posts_during_replay": enqueue_replay_delta,
                "transport_telemetry_available": (
                    enqueue_before_replay is not None and enqueue_after_failure is not None
                ),
                "idempotent_response": False,
                "error": str(exc),
            }
            run.check("second_burst_no_enqueue", False, str(exc))
    else:
        run.second_burst_evidence = {
            "status": "not_attempted",
            "new_items": [],
            "enqueue_posts_during_poll": None,
            "enqueue_posts_during_replay": None,
            "transport_telemetry_available": None,
            "idempotent_response": None,
        }
        run.check(
            "second_burst_no_enqueue",
            False,
            "second poll requires a completed run with a STOPPED instance",
        )


def _cleanup_timeout(run: _SmokeExecution, ceiling: float = OCI_CALL_TIMEOUT_SECONDS) -> float:
    """Use the run deadline for cleanup calls, with a tiny STOP escape hatch."""

    remaining = run.deadline.remaining()
    return max(0.1, min(ceiling, remaining)) if remaining > 0 else 0.1


def _cleanup_sleep(run: _SmokeExecution) -> None:
    if run.deadline.remaining() > 0:
        run.sleep(min(POLL_SECONDS, run.deadline.remaining()))


def _issue_compensating_stop(run: _SmokeExecution) -> tuple[bool, str | None]:
    """Mask terminating signals only while the critical STOP mutation runs."""

    try:
        with terminating_signals_deferred():
            run.oci.stop_instance(
                run.args.instance_id,
                timeout=_cleanup_timeout(run, EMERGENCY_STOP_TIMEOUT_SECONDS),
            )
    except (SmokeFailure, OSError, ValueError) as exc:
        return False, str(exc)
    return True, None


def _compensate_instance_stop(run: _SmokeExecution) -> tuple[str, list[str], int]:
    """Interpret lifecycle state and issue STOP for every non-terminal state."""

    final_state = "UNKNOWN"
    stop_failures: list[str] = []
    successful_stop_calls = 0
    stop_requested = False
    post_deadline_polls = 0
    while final_state not in NON_BILLING_TERMINAL_STATES:
        state_error: str | None = None
        try:
            observed = run.oci.get_instance(
                run.args.instance_id,
                timeout=_cleanup_timeout(run),
            )
            final_state = _state(observed)
            _record_transition(run.transitions, final_state, elapsed=run.deadline.elapsed(), now=run.now)
        except (SmokeFailure, PreflightRefusal, OSError, ValueError) as exc:
            final_state = "UNKNOWN"
            state_error = str(exc)
            _record_transition(run.transitions, final_state, elapsed=run.deadline.elapsed(), now=run.now)
        if run.deadline.remaining() <= 0:
            post_deadline_polls += 1

        if final_state in NON_BILLING_TERMINAL_STATES:
            break
        if run.oci.stop_calls >= MAX_EMERGENCY_STOP_ATTEMPTS:
            stop_failures.append(
                state_error or f"bounded compensating STOP retries exhausted in state {final_state}"
            )
            break
        if final_state != "STOPPING" or not stop_requested:
            stopped, stop_error = _issue_compensating_stop(run)
            if stopped:
                successful_stop_calls += 1
                stop_requested = True
            else:
                stop_requested = False
                stop_failures.append(stop_error or "compensating STOP failed")
        if run.deadline.remaining() <= 0 and post_deadline_polls >= MAX_EMERGENCY_STOP_ATTEMPTS:
            stop_failures.append(f"overall deadline exhausted while waiting for {final_state}")
            break
        _cleanup_sleep(run)
    return final_state, stop_failures, successful_stop_calls


def _audit_stop_events(run: _SmokeExecution) -> tuple[list[dict[str, Any]], float, str | None]:
    """Poll STOP audit records only while the overall run deadline remains."""

    started = run.deadline.elapsed()
    audit_budget = min(AUDIT_INDEX_TIMEOUT_SECONDS, max(0.0, run.deadline.remaining()))
    stop_events: list[dict[str, Any]] = []
    error: str | None = None
    while run.deadline.elapsed() - started < audit_budget and not stop_events:
        try:
            window_end = _iso_utc(run.now())
            raw_events = run.oci.list_stop_events(
                run.compartment_id,
                run.args.instance_id,
                start_time=run.run_window_started_at,
                end_time=window_end,
                timeout=_cleanup_timeout(run),
            )
            stop_events = _stop_events_in_window(
                _unique_stop_events(raw_events, run.args.instance_id),
                run.args.instance_id,
                start_time=run.run_window_started_at,
                end_time=window_end,
            )
        except (SmokeFailure, OSError, ValueError) as exc:
            error = str(exc)
            break
        if not stop_events:
            _cleanup_sleep(run)
    return stop_events, round(run.deadline.elapsed() - started, 3), error


def _record_stop_attribution(
    run: _SmokeExecution,
    stop_events: Sequence[dict[str, Any]],
    lag: float,
    error: str | None = None,
) -> None:
    """Record the first in-window STOP principal and enforce its allow-list."""

    run.stop_action_evidence = {
        "source": "oci_audit",
        "status": "error" if error is not None else ("observed" if stop_events else "not_indexed"),
        "count": len(stop_events),
        "audit_lag_seconds": lag,
        "window_start": run.run_window_started_at,
        "window_end": _iso_utc(run.now()),
    }
    if error is not None:
        run.stop_action_evidence["error"] = error
    first_stop_event = _first_stop_event(stop_events)
    if first_stop_event is None:
        run.check("stop_event_observed", False, f"zero STOP events indexed after {lag:.3f}s")
        run.check("stop_principal_allowed", False, "no STOP event principal available")
        run.check("stop_attribution", False, "cannot prove who stopped the GPU without a STOP event")
        return

    principals = _stop_event_principals(first_stop_event)
    run.stop_principal = principals[0] if principals else None
    run.stop_event_time = _audit_event_time(first_stop_event)
    expected_principals = [
        str(principal)
        for principal in getattr(run.args, "expected_stop_principal", [DEFAULT_STOP_PRINCIPAL])
        if str(principal).strip()
    ]
    allowed = bool(principals) and any(principal in expected_principals for principal in principals)
    run.check("stop_event_observed", True, f"first STOP event at {run.stop_event_time!r}")
    run.check(
        "stop_principal_allowed",
        allowed,
        (
            f"principal={run.stop_principal!r}; expected one of {expected_principals!r}"
            if principals
            else "STOP event has no principalName or principalId"
        ),
    )
    run.check(
        "stop_attribution",
        allowed and run.stop_event_time is not None,
        (
            f"principal={run.stop_principal!r}; event_time={run.stop_event_time!r}"
            if allowed
            else "STOP principal is not an expected lifecycle reaper principal"
        ),
    )


def _discover_orphans(run: _SmokeExecution) -> None:
    """Find running instances by ownership tag, then report identity drift."""

    try:
        listed = run.oci.list_instances(run.compartment_id, timeout=_cleanup_timeout(run))
        owned = [
            instance
            for instance in listed
            if str(instance.get("id")) != run.args.instance_id and _has_gpu_burst_ownership_tag(instance)
        ]
        mismatches = {
            str(instance.get("id")): _gpu_burst_identity_mismatches(instance)
            for instance in owned
            if _gpu_burst_identity_mismatches(instance)
        }
        running = [instance for instance in owned if _state(instance) not in NON_BILLING_TERMINAL_STATES]
        run.check("orphan_identity_matches", not mismatches, str(mismatches) if mismatches else "all ownership-tagged identities match")
        run.check(
            "no_orphan_running",
            not running,
            f"{len(running)} orphan(s): {[str(instance.get('id')) for instance in running]}",
        )
    except (SmokeFailure, OSError, ValueError) as exc:
        run.check("orphan_identity_matches", False, str(exc))
        run.check("no_orphan_running", False, str(exc))


def _compensate_and_audit_stop(run: _SmokeExecution) -> None:
    if not run.instance_validated:
        run.check("finally_stop_skipped", True, "instance was not validated; STOP and OCI follow-up skipped")
        return

    final_state, stop_failures, successful_stop_calls = _compensate_instance_stop(run)
    stop_detail = "already terminal; no compensating STOP needed" if run.oci.stop_calls == 0 else (
        f"STOP issued ({run.oci.stop_calls} attempt(s))"
    )
    run.check(
        "finally_stop_issued",
        not stop_failures or successful_stop_calls > 0,
        stop_detail if not stop_failures else f"{stop_detail}; failures: {'; '.join(stop_failures)}",
    )
    stopped = final_state in NON_BILLING_TERMINAL_STATES
    run.check("instance_stopped_finally", stopped, final_state)
    if run.deadline.remaining() > 0:
        with contextlib.suppress(SmokeFailure, OSError, ValueError):
            _poll_health(run, "after_stop", request_deadline=run.deadline)
    else:
        run.service_health_samples.append(
            {
                "elapsed_seconds": round(run.deadline.elapsed(), 3),
                "phase": "after_stop",
                "status": "skipped_deadline",
                "description_adapter": "unknown",
                "healthy": True,
                "skipped": True,
            }
        )
    _discover_orphans(run)
    stop_events, lag, error = _audit_stop_events(run)
    _record_stop_attribution(run, stop_events, lag, error)




def _emit_smoke_result(run: _SmokeExecution) -> SmokeResult:
    unhealthy_samples = [sample for sample in run.service_health_samples if not sample["healthy"]]
    run.check(
        "service_health_throughout",
        not unhealthy_samples,
        f"{len(run.service_health_samples)} sample(s); {len(unhealthy_samples)} unhealthy",
    )

    evidence_elapsed_seconds = run.deadline.elapsed()
    running_seconds = _running_seconds(run.transitions, final_elapsed_seconds=evidence_elapsed_seconds)
    cost = round(running_seconds * GPU_USD_PER_HOUR / 3600.0, 6)
    stopped_finally = any(
        check["name"] == "instance_stopped_finally" and check["passed"] for check in run.checks
    )
    running_seconds_ongoing = run.instance_validated and not stopped_finally
    cost_estimate_ongoing = running_seconds_ongoing
    measurements = {
        "running_seconds": running_seconds,
        "running_seconds_ongoing": running_seconds_ongoing,
        "cost_estimate_usd": cost,
        "cost_estimate_ongoing": cost_estimate_ongoing,
    }
    assert_no_null_measurement_values(measurements)
    item_provenance = []
    for item in run.items:
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
        "mode": "live" if run.args.live else "dry-run",
        "generated_at": _iso_utc(run.now()),
        "head_sha": _head_sha(),
        "instance_id": run.args.instance_id,
        "tenant_id": run.tenant_id,
        "run_id": run.run_id,
        "run_status": run.run_status,
        "media_ids": run.args.media_ids,
        "transitions": run.transitions,
        "start_action_evidence": run.start_action_evidence,
        "stop_action_evidence": run.stop_action_evidence,
        "stop_principal": run.stop_principal,
        "stop_event_time": run.stop_event_time,
        "gpu_state_timeline": getattr(run.oci, "observed_gpu_states", []),
        "second_burst": run.second_burst_evidence,
        "item_timeline": run.item_timeline,
        "item_provenance": item_provenance,
        "service_health_samples": run.service_health_samples,
        "denylist_verdicts": run.denylist_verdicts,
        "gpu_state_json": run.gpu_snapshot,
        "load_json": {
            "source": run.load_source,
            "before_trigger": run.load_snapshot_before_trigger,
            "after_trigger": run.load_snapshot_after_trigger,
        },
        "phase_durations_seconds": run.phase_durations_seconds,
        "budget_seconds": {
            "warm_start": WARM_START_BUDGET_SECONDS,
            "idle_reaper": IDLE_REAPER_SECONDS,
            "reaper": REAPER_BUDGET_SECONDS,
            "fence": FENCE_BUDGET_SECONDS,
            "audit_index": AUDIT_INDEX_TIMEOUT_SECONDS,
            "max": run.args.max_seconds,
        },
        "measurements": measurements,
        "running_seconds_ongoing": running_seconds_ongoing,
        "cost_estimate_usd": cost,
        "cost_estimate_ongoing": cost_estimate_ongoing,
        "checks": run.checks,
        "errors": [str(check["detail"]) for check in run.checks if not check["passed"]],
    }
    _write_evidence(run.args.evidence_out, evidence, force=run.args.force)
    _print_assertion_table(run.checks)

    remaining_budget_seconds = run.args.max_seconds
    warm_start_budget_seconds = min(WARM_START_BUDGET_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= warm_start_budget_seconds
    idle_reaper_seconds = min(IDLE_REAPER_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= idle_reaper_seconds
    reaper_budget_seconds = min(REAPER_BUDGET_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= reaper_budget_seconds
    fence_budget_seconds = min(FENCE_BUDGET_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= fence_budget_seconds
    audit_budget_seconds = min(AUDIT_INDEX_TIMEOUT_SECONDS, remaining_budget_seconds)
    remaining_budget_seconds -= audit_budget_seconds
    inference_budget_seconds = remaining_budget_seconds
    budget_total = (
        warm_start_budget_seconds
        + inference_budget_seconds
        + idle_reaper_seconds
        + reaper_budget_seconds
        + fence_budget_seconds
        + audit_budget_seconds
    )
    print(
        f"\nBudget: {budget_total}s = warm-start {warm_start_budget_seconds}s + "
        f"inference {inference_budget_seconds}s + idle {idle_reaper_seconds}s + "
        f"reap {reaper_budget_seconds}s + fence {fence_budget_seconds}s + audit {audit_budget_seconds}s"
    )
    print(
        f"Estimated GPU cost: ${cost:.6f} ({running_seconds:.3f}s RUNNING at ${GPU_USD_PER_HOUR:.2f}/hour; "
        f"{'ongoing' if cost_estimate_ongoing else 'closed'})"
    )
    print(f"Evidence: {run.args.evidence_out}")
    exit_code = 2 if run.preflight_refused else (0 if all(check["passed"] for check in run.checks) else 1)
    return SmokeResult(
        exit_code=exit_code,
        evidence=evidence,
        stop_principal=run.stop_principal,
        stop_event_time=run.stop_event_time,
    )


def _run_smoke_flow(run: _SmokeExecution) -> None:
    _preflight(run)
    _submit_and_observe_load(run)
    _warm_and_process(run)
    _validate_completed_items(run)
    _wait_for_reaper(run)
    _audit_start_and_second_poll(run)


def _run_smoke_phase_machine(
    args: argparse.Namespace,
    *,
    client: httpx.Client,
    oci: OciClient,
    app_password: str,
    service_api_key: str,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _utc_now,
    load_snapshot_reader: Callable[[str], dict[str, Any]] = _read_load_snapshot,
) -> SmokeResult:
    """Coordinate the bounded phases; each phase owns its own lifecycle proof."""

    run = _SmokeExecution(
        args,
        client=client,
        oci=oci,
        app_password=app_password,
        service_api_key=service_api_key,
        monotonic=monotonic,
        sleep=sleep,
        now=now,
        load_snapshot_reader=load_snapshot_reader,
    )
    try:
        try:
            _run_smoke_flow(run)
        except PreflightRefusal:
            run.preflight_refused = True
        except (SmokeFailure, OSError, ValueError) as exc:
            run.check("flow_completed", False, str(exc))
    finally:
        _compensate_and_audit_stop(run)
    return _emit_smoke_result(run)




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
    load_snapshot_reader: Callable[[str], dict[str, Any]] = _read_load_snapshot,
) -> SmokeResult:
    """Run the smoke through its phase machine and return serialized evidence."""

    return _run_smoke_phase_machine(
        args,
        client=client,
        oci=oci,
        app_password=app_password,
        service_api_key=service_api_key,
        monotonic=monotonic,
        sleep=sleep,
        now=now,
        load_snapshot_reader=load_snapshot_reader,
    )


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


class _ExpectedStopPrincipalAction(argparse.Action):
    """Append an allow-list value while replacing the implicit default."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str,
        option_string: str | None = None,
    ) -> None:
        del parser, option_string
        current = getattr(namespace, self.dest, None)
        if current is None or current == [DEFAULT_STOP_PRINCIPAL]:
            current = []
        current.append(values)
        setattr(namespace, self.dest, current)


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
    parser.add_argument(
        "--expected-stop-principal",
        action=_ExpectedStopPrincipalAction,
        default=[DEFAULT_STOP_PRINCIPAL],
        metavar="PRINCIPAL",
        help=(
            "principal name or OCID allowed to stop the burst; repeat for aliases "
            f"(default: {DEFAULT_STOP_PRINCIPAL})"
        ),
    )
    parser.add_argument("--gpu-state-json", default="/run/acx/gpu-state.json")
    parser.add_argument(
        "--load-dir",
        default=DEFAULT_LOAD_DIR,
        help=(
            "per-environment describe-load root the API publishes into "
            f"(<load-dir>/<environment>/{LOAD_SNAPSHOT_FILENAME}); default {DEFAULT_LOAD_DIR}"
        ),
    )
    parser.add_argument(
        "--load-environment",
        default=None,
        metavar="ENV",
        help=(
            "environment this run drives; reads exactly "
            f"<load-dir>/<ENV>/{LOAD_SNAPSHOT_FILENAME}. Required on a host that "
            "publishes more than one environment, because freshness alone cannot "
            "attribute observed load to this run (WBUX6-W5-04)"
        ),
    )
    parser.add_argument(
        "--load-json",
        default=None,
        help="explicit single describe-load.json to read instead of walking --load-dir",
    )
    parser.add_argument("--max-seconds", type=int, default=MAX_LIVE_SECONDS)
    parser.add_argument(
        "--evidence-out",
        default=(f"{DEFAULT_EVIDENCE_DIR}/GPUSMOKE-1-evidence-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"),
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
    expected_stop_principals = getattr(args, "expected_stop_principal", [DEFAULT_STOP_PRINCIPAL])
    if not expected_stop_principals or any(
        not isinstance(principal, str) or not principal.strip()
        for principal in expected_stop_principals
    ):
        raise PreflightRefusal("--expected-stop-principal must name at least one non-empty principal")
    environment_options = (
        ("--wp-app-password-env", args.wp_app_password_env),
        ("--service-api-key-env", args.service_api_key_env),
    )
    for option, environment_name in environment_options:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", environment_name):
            raise PreflightRefusal(f"{option} must name a valid environment variable")
    if not args.live:
        evidence_target = _evidence_path(args.evidence_out)
        if evidence_target.exists() and not args.force:
            raise PreflightRefusal(f"evidence output already exists: {evidence_target}; pass --force to overwrite")
        return "dry-run-only", "dry-service-key"
    if os.environ.get("ACX_GPU_SMOKE_CONFIRM") != "RUN":
        raise PreflightRefusal("live mode requires ACX_GPU_SMOKE_CONFIRM=RUN")
    if args.max_seconds < MIN_COMPOSED_BUDGET_SECONDS:
        raise PreflightRefusal(
            f"--max-seconds must cover the {MIN_COMPOSED_BUDGET_SECONDS:g}s composed "
            "warm-start + idle + reap + fence contract"
        )
    for option, value, purpose in (
        ("--service-base-url", args.service_base_url, "description service"),
        ("--wp-base-url", args.wp_base_url, "WordPress service"),
    ):
        parsed_url = urlsplit(value)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.hostname.endswith(".invalid")
            or "<" in value
            or ">" in value
        ):
            raise PreflightRefusal(f"{option} must explicitly name the {purpose}")
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
    evidence_target = _evidence_path(args.evidence_out)
    if evidence_target.exists() and not args.force:
        raise PreflightRefusal(f"evidence output already exists: {evidence_target}; pass --force to overwrite")
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
        scenario = DryScenario()
        client = client_factory(transport=make_mock_transport(scenario, now=clock.now), follow_redirects=False)
        oci = FakeOci(gpu_states=scenario.gpu_states)

    try:
        kwargs: dict[str, Any] = {}
        if clock is not None:

            def dry_load_snapshot_reader(path: str) -> dict[str, Any]:
                written_at = scenario.submitted_at or clock.now()
                return {
                    "availability": "available",
                    "path": path,
                    "value": {
                        **(scenario.load_snapshot_after_trigger or {}),
                        "written_at": (written_at.timestamp() + scenario.load_snapshot_written_offset_seconds),
                    },
                }

            kwargs = {
                "monotonic": clock.monotonic,
                "sleep": clock.sleep,
                "now": clock.now,
                "load_snapshot_reader": dry_load_snapshot_reader,
            }
        # The handler lives here, not at import: a SIGTERM must unwind the one
        # compensating-STOP path in run_smoke, and only a CLI run owns the
        # process disposition.
        with terminating_signals_raise():
            result = run_smoke(
                args,
                client=client,
                oci=oci,
                app_password=app_password,
                service_api_key=service_api_key,
                **kwargs,
            )
    except SmokeTerminated as exc:
        print(
            f"TERMINATED: {exc}; the compensating STOP path ran before exit",
            file=sys.stderr,
        )
        return 128 + exc.signum
    finally:
        client.close()
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
