"""GTMR G2 runtime receipts: offline causal REDs, healthy controls, and collector proposal.

Owner: lane G2 (proposed owner of scripts/collect_gpu_runtime_evidence.py).
Frozen protocol: FROZEN ADDITIVE STRICT GPU EVIDENCE CONTRACT v1. The contract is an
expected protocol, never an observation. This file authors tests only.

Source identity: tree 9e759b04784174a84d33f3fad91ec38457371023 is verified locally.
Commit a543ac2eab3ff1a8cc4cb17c74b2113f5ac2ae97 is not present in this history-stripped
sandbox, so commit ancestry is NOT proven by this file.

Three test classes are reported separately:

``test_control_*``   Healthy controls on UNCHANGED production. They must pass now and after
                     any fix.
``test_red_*``       CAUSAL REDs on UNCHANGED production. Each differs from a healthy control
                     by exactly one factor and is expected to FAIL now. A failure is a real
                     defect in existing behaviour; the docstring names the producer it reads.
``test_proposal_*``  FUTURE-INTERFACE PROPOSAL for scripts/collect_gpu_runtime_evidence.py.
                     Marked xfail(reason=PROPOSAL_PENDING) while that module is absent. Import
                     absence is not a behaviour defect and is never reported as one. Once the
                     module exists these run as ordinary assertions.
``test_freeze_*``    Fixture freeze: pinned digests of the frozen raw command outputs.

Offline only. A subprocess guard fails any live call. This file never runs nvidia-smi,
docker, oci, a live /proc read, a GPU, a database, or the network.

Real producers read before fixtures (NVIDIA/Docker/proc/llama.cpp):
  * nvidia-smi memory query and CSV parse: apps/prototype-description-service/scripts/eval_harness/bench_capture.py
    (_NVIDIA_SMI_QUERY, VramSampler._sample). Only memory.used/memory.total is in-repo.
  * llama-server argv and build preflight: apps/prototype-description-service/scripts/eval_harness/bakeoff_runner.py
    (serve argv, --version grep).
  * container launch argv, --gpus all, --name acx-gpu-vlm, model/mmproj names, bind mount:
    infra/oci/gpu-cloud-init.yaml (acx-gpu-vlm-start.sh).
  * docker inspect --format usage: scripts/deploy/recognition-service.sh.
  * /proc/<pid>/stat field 22 start-time parse: scripts/gate_ops.sh (starttime_of).
  * /proc/sys/kernel/random/boot_id reader: infra/oci/gpu_lifecycle/intent.py.
  * OCI instance get argv and data.lifecycle-state payload: infra/oci/gpu_lifecycle/reaper.py (fetch_instance_idle_seconds).
  * request payload mirror: apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py (_completion_payload, lines 267-298).
  * input hashes: apps/prototype-description-service/scene/application/hashing.py (used as the oracle).
NOT in-repo, therefore marked UNVERIFIED-NATIVE below: the nvidia-smi compute-apps query, the
docker logs --timestamps shape, llama.cpp startup offload/build/completion log text, and the
server-side request_id echo. Those are proposal shapes for native verification by the parent.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = REPO_ROOT / "scripts" / "gpu_burst_smoke.py"
SAMPLER_PATH = REPO_ROOT / "apps" / "prototype-description-service" / "scripts" / "eval_harness" / "bench_capture.py"
HASHING_PATH = REPO_ROOT / "apps" / "prototype-description-service" / "scene" / "application" / "hashing.py"
COLLECTOR_PATH = REPO_ROOT / "scripts" / "collect_gpu_runtime_evidence.py"

# ---------------------------------------------------------------------------
# Frozen fixture identities. All values are fixture-only. None is a live OCID,
# secret, address, or observation. Path and file names come from in-repo producers.
# ---------------------------------------------------------------------------

INSTANCE_ID = "ocid1.instance.oc1..gtmr-g2-fixture-gpu"
BOOT_ID = "3c1f0a2e-7d4b-4e8a-9b61-2f5d0c9e8a10"
BOOT_ID_PREVIOUS = "9a7e4d11-0b2c-4f6e-8d3a-5c1b7e2f4a90"
CONTAINER_NAME = "acx-gpu-vlm"  # infra/oci/gpu-cloud-init.yaml --name
IMAGE_REF = "ghcr.io/ggerganov/llama.cpp:server-cuda"  # infra/oci/gpu-cloud-init.yaml
CONTAINER_ID = "ab" * 32
CONTAINER_ID_RESTARTED = "cd" * 32
IMAGE_ID = "sha256:" + "1f" * 32
IMAGE_ID_OTHER = "sha256:" + "2e" * 32
CONTAINER_PID = 4242
CONTAINER_START_TICKS = 918273
CONTAINER_STARTED_AT = "2026-10-12T00:00:01.000000000Z"
GPU_UUID = "GPU-3f9c1d2e-8a7b-4c6d-9e0f-1a2b3c4d5e6f"
OTHER_GPU_PID = 7001
MODEL_FILE = "qwen3-vl-30b-a3b-instruct-q4.gguf"  # infra/oci/gpu-cloud-init.yaml
PROJECTOR_FILE = "qwen3-vl-30b-a3b-instruct-mmproj.gguf"  # infra/oci/gpu-cloud-init.yaml
OTHER_MODEL_FILE = "fixture-other-model-q4.gguf"
OTHER_PROJECTOR_FILE = "fixture-other-mmproj.gguf"
HOST_MODEL_DIR = "/opt/acx-gpu/models"  # bind source, infra/oci/gpu-cloud-init.yaml
CONTAINER_MODEL_DIR = "/models"  # bind destination
SECRET_KEY_PATH = "/run/acx-gpu-vlm/api-key"  # never read by any frozen argv
MODEL_HOST_PATH = f"{HOST_MODEL_DIR}/{MODEL_FILE}"
PROJECTOR_HOST_PATH = f"{HOST_MODEL_DIR}/{PROJECTOR_FILE}"
OTHER_MODEL_HOST_PATH = f"{HOST_MODEL_DIR}/{OTHER_MODEL_FILE}"
OTHER_PROJECTOR_HOST_PATH = f"{HOST_MODEL_DIR}/{OTHER_PROJECTOR_FILE}"
MODEL_INODE = 917001
PROJECTOR_INODE = 917002
MODEL_BYTES = b"fixture-model-weights\n"
PROJECTOR_BYTES = b"fixture-mmproj-weights\n"
MODEL_SHA256 = hashlib.sha256(MODEL_BYTES).hexdigest()
PROJECTOR_SHA256 = hashlib.sha256(PROJECTOR_BYTES).hexdigest()
MODEL_ID = "example-org/gtmr-g2-fixture-model"
REQUEST_ID = "gtmr-g2-req-0001"
OTHER_REQUEST_ID = "gtmr-g2-req-0000"
IMAGE_BYTES = b"fixture-image-bytes\n"
SYSTEM_PROMPT = "fixture system prompt"
USER_TEXT = "fixture user text"

# Timestamps for docker-logs-shaped lines (UNVERIFIED-NATIVE shape, RFC3339Nano prefix).
T_BUILD = "2026-10-12T00:00:02.100000000Z"
T_OFFLOAD = "2026-10-12T00:00:03.400000000Z"
T_COMPLETION = "2026-10-12T00:00:20.000000000Z"
T_STALE = "2026-10-11T23:59:00.000000000Z"  # before CONTAINER_STARTED_AT: a prior run

LOG_BUILD = f"{T_BUILD} build: 8123 (5e1f2ab) with cc for x86_64-linux-gnu"
LOG_BUILD_OLD = f"{T_BUILD} build: 7000 (0aa11bb) with cc for x86_64-linux-gnu"
LOG_OFFLOAD_GPU = f"{T_OFFLOAD} load_tensors: offloaded 49/49 layers to GPU"
LOG_OFFLOAD_CPU = f"{T_OFFLOAD} load_tensors: offloaded 0/49 layers to GPU"
LOG_OFFLOAD_STALE = f"{T_STALE} load_tensors: offloaded 49/49 layers to GPU"
LOG_COMPLETION = f"{T_COMPLETION} srv  log_server_r: request_id={REQUEST_ID} status=200 completion"
LOG_COMPLETION_OTHER = f"{T_COMPLETION} srv  log_server_r: request_id={OTHER_REQUEST_ID} status=200 completion"

MAX_CALLS = 32  # bound for every offline collector run; the healthy path uses fewer
MAX_STDOUT_BYTES = 1 << 20  # frozen cap; the truncation fixture exceeds it by 2x
ARTIFACT_KEYS = ("relative_path", "sha256", "command_argv", "exit_code", "capture_started_at", "capture_finished_at")

# Frozen v1 PROPOSAL vocabulary. Proposal only, never an observed fact. Each assertion helper
# refuses a code outside these sets, so a test cannot quietly invent a new reason.
STATUSES = frozenset({"complete", "incomplete", "contradicted"})
MISSING_CODES = frozenset(
    {
        "instance_not_running",
        "build_line_absent",
        "gpu_process_for_container_absent",
        "gpu_query_timeout",
        "command_failed",
        "maps_unreadable",
        "offload_line_absent",
        "startup_log_stale",
        "request_completion_absent",
        "output_truncated",
        "deadline_exhausted",
    }
)
CONTRADICTION_CODES = frozenset(
    {
        "instance_mismatch",
        "boot_changed",
        "container_changed",
        "pid_reused",
        "mapped_model_argv_mismatch",
        "mapped_projector_argv_mismatch",
        "mapped_file_replaced",
        "offload_cpu",
    }
)

# ---------------------------------------------------------------------------
# Frozen argv trace. Every argv is a list of str with no shell. The proposal argv
# is frozen here so the collector cannot drift silently.
# ---------------------------------------------------------------------------

ARGV_INSTANCE = ("oci", "compute", "instance", "get", "--instance-id", INSTANCE_ID, "--output", "json")
ARGV_BOOT = ("cat", "/proc/sys/kernel/random/boot_id")
ARGV_INSPECT = ("docker", "inspect", CONTAINER_NAME)
ARGV_GPU_APPS = (
    "nvidia-smi",
    "--query-compute-apps=pid,process_name,used_gpu_memory,gpu_uuid",
    "--format=csv,noheader,nounits",
)
ARGV_LOGS = ("docker", "logs", "--timestamps", CONTAINER_NAME)
ARGV_PROC_STAT = ("cat", f"/proc/{CONTAINER_PID}/stat")
ARGV_PROC_CMDLINE = ("cat", f"/proc/{CONTAINER_PID}/cmdline")
ARGV_PROC_MAPS = ("cat", f"/proc/{CONTAINER_PID}/maps")
ARGV_GPU_UTIL = ("nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits")
ARGV_V1_MODELS = ("curl", "-fsS", "http://127.0.0.1:8000/v1/models")
ARGV_CONFIG_PINS = ("cat", "/opt/acx-gpu/config.env")
ARGV_FILE_EXISTS = ("test", "-f", MODEL_HOST_PATH)


def _file_argvs(path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return ("stat", "-c", "%i", path), ("sha256sum", path)


class CollectorAbsentError(RuntimeError):
    """Raised when the G2 proposal module has not been implemented yet."""


class UnscriptedCommand(BaseException):
    """Raised for an argv the frozen trace does not contain. BaseException so it cannot be swallowed."""


class RunnerBoundExceeded(BaseException):
    """Raised when a collector exceeds the frozen call bound."""


# ---------------------------------------------------------------------------
# Loaders. Existing production files are loaded by path, never imported as packages.
# ---------------------------------------------------------------------------


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve the owning module by name
    spec.loader.exec_module(module)
    return module


@cache
def _smoke() -> ModuleType:
    return _load("gtmr_g2_gpu_burst_smoke", SMOKE_PATH)


@cache
def _sampler_module() -> ModuleType:
    return _load("gtmr_g2_bench_capture", SAMPLER_PATH)


@cache
def _hashing() -> ModuleType:
    return _load("gtmr_g2_hashing", HASHING_PATH)


def _collector() -> ModuleType:
    if not COLLECTOR_PATH.is_file():
        raise CollectorAbsentError(str(COLLECTOR_PATH))
    return _load("gtmr_g2_collect_gpu_runtime_evidence", COLLECTOR_PATH)


_COLLECTOR_PRESENT = COLLECTOR_PATH.is_file()
_PENDING = pytest.mark.xfail(
    not _COLLECTOR_PRESENT,
    raises=CollectorAbsentError,
    strict=False,
    reason=(
        "PROPOSAL_PENDING: scripts/collect_gpu_runtime_evidence.py not implemented. "
        "Future-interface coverage only; import absence is not a behaviour defect."
    ),
)


@pytest.fixture(autouse=True)
def _no_live_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("live subprocess is forbidden in offline GTMR G2 tests")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "check_output", _forbidden)
    monkeypatch.setattr(os, "system", _forbidden)


# ---------------------------------------------------------------------------
# Bounded fake runner and deadline. Protocol mirrors subprocess.run for bytes output,
# and gpu_burst_smoke.Deadline for remaining().
# ---------------------------------------------------------------------------


class FakeDeadline:
    def __init__(self, seconds: float) -> None:
        self._left = float(seconds)

    def remaining(self) -> float:
        return self._left

    def spend(self, seconds: float) -> None:
        self._left -= float(seconds)


class FrozenRunner:
    """Scripted stand-in for subprocess.run. Each argv maps to an ordered outcome queue.

    The last outcome repeats, so before/after reads can differ by listing two outcomes.
    Unscripted argv fails closed by raising UnscriptedCommand unless ``allow_unscripted``
    is set, in which case it returns rc=127. ``trace`` keeps every raw call and stdout.
    ``violations`` records timeout, shell, bound, and deadline breaches for assertion.
    """

    def __init__(
        self,
        script: Mapping[tuple[str, ...], list[Any]],
        *,
        deadline: FakeDeadline | None = None,
        costs: Mapping[tuple[str, ...], float] | None = None,
        allow_unscripted: bool = False,
        max_calls: int = MAX_CALLS,
    ) -> None:
        self._queues = {tuple(key): list(value) for key, value in script.items()}
        self._deadline = deadline
        self._costs = {tuple(key): float(value) for key, value in (costs or {}).items()}
        self._allow_unscripted = allow_unscripted
        self._max_calls = max_calls
        self.trace: list[dict[str, Any]] = []
        self.unexpected: list[tuple[str, ...]] = []
        self.violations: list[str] = []

    def __call__(
        self,
        argv: Iterable[str],
        *,
        timeout: float | None = None,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        shell: bool = False,
        **extra: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        key = tuple(argv)
        remaining = self._deadline.remaining() if self._deadline is not None else None
        self.trace.append(
            {
                "argv": list(key),
                "timeout": timeout,
                "capture_output": capture_output,
                "text": text,
                "check": check,
                "shell": shell,
                "extra_kwargs": sorted(extra),
                "remaining_at_call": remaining,
                "stdout": None,
            }
        )
        if len(self.trace) > self._max_calls:
            self.violations.append(f"call bound {self._max_calls} exceeded at {key!r}")
            raise RunnerBoundExceeded(key)
        if shell:
            self.violations.append(f"shell=True used for {key!r}")
        if timeout is None or not math.isfinite(timeout) or timeout <= 0:
            self.violations.append(f"non-finite or non-positive timeout {timeout!r} for {key!r}")
        if remaining is not None and remaining <= 0:
            self.violations.append(f"call after deadline exhausted: {key!r}")
        if remaining is not None and timeout is not None and timeout > remaining + 1e-9:
            self.violations.append(f"timeout {timeout} exceeds remaining {remaining} for {key!r}")
        if key in self._costs and self._deadline is not None:
            self._deadline.spend(self._costs[key])
        queue = self._queues.get(key)
        if not queue:
            self.unexpected.append(key)
            if self._allow_unscripted:
                return _done(key, b"", rc=127, stderr=b"unscripted")
            raise UnscriptedCommand(key)
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, BaseException):
            raise outcome
        self.trace[-1]["stdout"] = outcome.stdout
        return outcome


def _done(
    argv: Iterable[str], stdout: bytes, *, rc: int = 0, stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=list(argv), returncode=rc, stdout=stdout, stderr=stderr)


def _timeout(argv: Iterable[str], seconds: float = 5.0) -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(cmd=list(argv), timeout=seconds)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value: str) -> bytes:
    return (value + "\n").encode()


# ---------------------------------------------------------------------------
# Frozen raw outputs. Each builder reproduces the producer's stdout shape. The UNVERIFIED-NATIVE
# shapes are marked; parent native capture must confirm them before G2 acceptance.
# ---------------------------------------------------------------------------


def _instance_json(*, instance_id: str = INSTANCE_ID, state: str = "RUNNING") -> bytes:
    # Shape: reaper.py fetch_instance_idle_seconds reads payload["data"]["lifecycle-state"].
    doc = {"data": {"id": instance_id, "lifecycle-state": state, "display-name": "gtmr-g2-fixture"}}
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()


def _inspect_json(
    *,
    container_id: str = CONTAINER_ID,
    image_id: str = IMAGE_ID,
    pid: int = CONTAINER_PID,
    started_at: str = CONTAINER_STARTED_AT,
    device_requests: bool = True,
) -> bytes:
    # UNVERIFIED-NATIVE field set (Docker inspect JSON). Mounts mirror gpu-cloud-init.yaml -v flags.
    host_config: dict[str, Any] = {}
    if device_requests:
        host_config["DeviceRequests"] = [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}]
    doc = [
        {
            "Id": container_id,
            "Name": f"/{CONTAINER_NAME}",
            "Image": image_id,
            "Config": {"Image": IMAGE_REF},
            "State": {"Status": "running", "Running": True, "Pid": pid, "StartedAt": started_at},
            "HostConfig": host_config,
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": HOST_MODEL_DIR,
                    "Destination": CONTAINER_MODEL_DIR,
                    "Mode": "ro",
                    "RW": False,
                },
                {
                    "Type": "bind",
                    "Source": SECRET_KEY_PATH,
                    "Destination": "/run/secrets/acx-gpu-api-key",
                    "Mode": "ro",
                    "RW": False,
                },
            ],
        }
    ]
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()


def _gpu_apps_csv(rows: Iterable[tuple[int, str, int, str]] | None = None) -> bytes:
    # UNVERIFIED-NATIVE: --query-compute-apps. The CSV delimiter and noheader/nounits
    # convention match the in-repo --query-gpu producer in bench_capture.py.
    if rows is None:
        rows = [
            (CONTAINER_PID, "llama-server", 20480, GPU_UUID),
            (OTHER_GPU_PID, "python3", 512, GPU_UUID),
        ]
    return "".join(f"{pid}, {name}, {used}, {uuid}\n" for pid, name, used, uuid in rows).encode()


def _proc_stat(start_ticks: int, *, pid: int = CONTAINER_PID) -> bytes:
    # /proc/<pid>/stat: fields 3..22 follow "(comm) ". Field 22 is starttime, as in gate_ops.sh.
    rest = ["S"] + ["0"] * 18 + [str(start_ticks)]
    return f"{pid} (llama-server) {' '.join(rest)} 0 0 0 0 0 0 0 0 0 0 0\n".encode()


def _cmdline(model_path: str | None = None, projector_path: str | None = None) -> bytes:
    # Arguments mirror gpu-cloud-init.yaml acx-gpu-vlm-start.sh exactly. The key file path is an
    # argument value only; the key itself is never in any argv.
    model = model_path or f"{CONTAINER_MODEL_DIR}/{MODEL_FILE}"
    projector = projector_path or f"{CONTAINER_MODEL_DIR}/{PROJECTOR_FILE}"
    argv = [
        "llama-server",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--model",
        model,
        "--mmproj",
        projector,
        "--ctx-size",
        "8192",
        "--api-key-file",
        "/run/secrets/acx-gpu-api-key",
    ]
    return b"\x00".join(part.encode() for part in argv) + b"\x00"


def _maps(model_path: str = MODEL_HOST_PATH, projector_path: str = PROJECTOR_HOST_PATH) -> bytes:
    # Kernel /proc/<pid>/maps line shape: address perms offset dev inode pathname.
    # UNVERIFIED-NATIVE: whether the host-view pathname equals the bind-source path.
    lines = [
        f"7f0000000000-7f0000100000 r--p 00000000 08:01 {MODEL_INODE}  {model_path}",
        f"7f0000200000-7f0000210000 r--p 00000000 08:01 {PROJECTOR_INODE}  {projector_path}",
        "7f0000300000-7f0000301000 rw-p 00000000 00:00 0 ",
    ]
    return ("\n".join(lines) + "\n").encode()


def _logs(*lines: str) -> bytes:
    return "".join(f"{line}\n" for line in lines).encode()


def _request_body(image: bytes = IMAGE_BYTES, *, system: str = SYSTEM_PROMPT, user: str = USER_TEXT) -> bytes:
    # Mirrors gpu_remote_adapter._completion_payload (lines 267-298). Not imported: that module
    # pulls scene.* and PIL. The image-url data-URI shape is copied from the producer.
    url = "data:image/png;base64," + base64.b64encode(image).decode()
    payload = {
        "model": MODEL_ID,
        "temperature": 0,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "text", "text": user},
                ],
            },
        ],
    }
    return json.dumps(payload).encode()


def _file_script(path: str, inode: int, sha: str) -> dict[tuple[str, ...], list[Any]]:
    stat_argv, sha_argv = _file_argvs(path)
    return {
        stat_argv: [_done(stat_argv, _text(str(inode)))],
        sha_argv: [_done(sha_argv, f"{sha}  {path}\n".encode())],
    }


def _healthy_script(overrides: Mapping[tuple[str, ...], list[Any]] | None = None) -> dict[tuple[str, ...], list[Any]]:
    script: dict[tuple[str, ...], list[Any]] = {
        ARGV_INSTANCE: [_done(ARGV_INSTANCE, _instance_json())],
        ARGV_BOOT: [_done(ARGV_BOOT, _text(BOOT_ID))],
        ARGV_INSPECT: [_done(ARGV_INSPECT, _inspect_json())],
        ARGV_GPU_APPS: [_done(ARGV_GPU_APPS, _gpu_apps_csv())],
        ARGV_PROC_STAT: [_done(ARGV_PROC_STAT, _proc_stat(CONTAINER_START_TICKS))],
        ARGV_PROC_CMDLINE: [_done(ARGV_PROC_CMDLINE, _cmdline())],
        ARGV_PROC_MAPS: [_done(ARGV_PROC_MAPS, _maps())],
        ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD, LOG_OFFLOAD_GPU, LOG_COMPLETION))],
    }
    script.update(_file_script(MODEL_HOST_PATH, MODEL_INODE, MODEL_SHA256))
    script.update(_file_script(PROJECTOR_HOST_PATH, PROJECTOR_INODE, PROJECTOR_SHA256))
    script.update(dict(overrides or {}))
    return script


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instance_id": INSTANCE_ID,
        "container_name": CONTAINER_NAME,
        "request_id": REQUEST_ID,
        "request_body": _request_body(),
    }
    base.update(overrides)
    return base


def _collect(
    script: Mapping[tuple[str, ...], list[Any]],
    *,
    deadline: FakeDeadline | None = None,
    costs: Mapping[tuple[str, ...], float] | None = None,
    observation: Mapping[str, Any] | None = None,
    allow_unscripted: bool = False,
) -> tuple[Mapping[str, Any], FrozenRunner]:
    """Run the proposal collector against the frozen runner. Raises CollectorAbsentError while pending."""

    dl = deadline if deadline is not None else FakeDeadline(600.0)
    runner = FrozenRunner(script, deadline=dl, costs=costs, allow_unscripted=allow_unscripted)
    module = _collector()
    result = module.collect_runtime_evidence(
        runner=runner,
        observation=dict(observation) if observation is not None else _observation(),
        deadline=dl,
    )
    if not allow_unscripted:
        assert runner.unexpected == [], f"argv outside the frozen trace reached the runner: {runner.unexpected}"
    assert runner.violations == [], runner.violations
    assert {"section", "status", "observations", "missing_reasons", "contradictions", "artifacts"} <= set(result)
    assert result["status"] in STATUSES, result["status"]
    return result, runner


def _assert_missing(result: Mapping[str, Any], code: str) -> None:
    assert code in MISSING_CODES, f"{code!r} is outside the frozen v1 missing-reason vocabulary"
    assert result["status"] != "complete", result
    assert code in result["missing_reasons"], (code, result["missing_reasons"])


def _assert_contradiction(result: Mapping[str, Any], code: str) -> None:
    assert code in CONTRADICTION_CODES, f"{code!r} is outside the frozen v1 contradiction vocabulary"
    assert result["status"] != "complete", result
    assert code in result["contradictions"], (code, result["contradictions"])


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _walk_keys(item)


# ---------------------------------------------------------------------------
# FIXTURE FREEZE. Pinned digests of the frozen raw outputs. A failure means a fixture changed.
# ---------------------------------------------------------------------------

PINNED_RAW_DIGESTS = {
    "instance": "1e35ebb0b3b2deb5875fa7f89afabfc5487ec64817dfd5581f38e655f7b7ac94",
    "boot": "28a7afc26385f86a223141b3d3924fcd5e52c7ed1df57d4a455f66b9887e2ff8",
    "inspect": "81a878a9f7b8bfde6865ee94b66cc1eccfde8b2a2e729d04c2012435a6fef4fd",
    "gpu_apps": "543375c372fa54c898440eeb79f34c8f0fa25eb6235b5f301353f1b1ce563095",
    "proc_stat": "f53d9e050b9fb7582156313265acb99188f5c30ef2dbb2564532a0ea0697ba81",
    "cmdline": "3b65d7912761f050398a7893caded31a6093ab99f4fd4b34c7d9fef083d29308",
    "maps": "3107178a804e70fea37f235600a9309419fe254c22bbb0741d968a4e372533e0",
    "logs": "605ebe448fefd136175a1068924e7ae3785cb4b60bca770daa001c3857b308ed",
    "model_stat": "9438c330824438b74228a3a609980a664d2dc6593845dc2e6e43fbd5770e264c",
    "model_sha": "e57c125948d49b044f01db133b3dc16f1f75b8cc9799e075353c80cc5ed10954",
    "projector_stat": "b1ce6219486aede0452ed814078e4c42e6acc0cb613caf0b6e70eddd35c42dc8",
    "projector_sha": "a9a614f441da7a9766d07ce78a0f9ce7c60b1c63b7616529376212846c9ceff6",
    "request_body": "2bca7fbeb7d087b563a3a7accf8b1bb5be27cd3035d2979d5dc76cce9aac250f",
}


def test_freeze_frozen_raw_outputs_match_pinned_digests() -> None:
    script = _healthy_script()
    model_stat, model_sha = _file_argvs(MODEL_HOST_PATH)
    projector_stat, projector_sha = _file_argvs(PROJECTOR_HOST_PATH)
    observed = {
        "instance": _sha(script[ARGV_INSTANCE][0].stdout),
        "boot": _sha(script[ARGV_BOOT][0].stdout),
        "inspect": _sha(_inspect_json()),
        "gpu_apps": _sha(script[ARGV_GPU_APPS][0].stdout),
        "proc_stat": _sha(script[ARGV_PROC_STAT][0].stdout),
        "cmdline": _sha(script[ARGV_PROC_CMDLINE][0].stdout),
        "maps": _sha(script[ARGV_PROC_MAPS][0].stdout),
        "logs": _sha(script[ARGV_LOGS][0].stdout),
        "model_stat": _sha(script[model_stat][0].stdout),
        "model_sha": _sha(script[model_sha][0].stdout),
        "projector_stat": _sha(script[projector_stat][0].stdout),
        "projector_sha": _sha(script[projector_sha][0].stdout),
        "request_body": _sha(_observation()["request_body"]),
    }
    assert set(observed) == set(PINNED_RAW_DIGESTS), "frozen fixture set changed"
    drifted = {
        key: (PINNED_RAW_DIGESTS[key], observed[key]) for key in observed if observed[key] != PINNED_RAW_DIGESTS[key]
    }
    assert drifted == {}, f"frozen raw outputs drifted (pinned, observed): {drifted}"


# ---------------------------------------------------------------------------
# CONTROLS on unchanged production. Each differs from a RED by exactly one factor.
# ---------------------------------------------------------------------------

SMOKE_PIN_REPO = "example-org/gtmr-g2-fixture-model"
SMOKE_PIN_REVISION = "rev-pinned"


class _SmokeCheckSink:
    """Minimal stand-in for _SmokeExecution. _check_item_provenance reads only expected_profile and check()."""

    def __init__(self) -> None:
        spec = SimpleNamespace(hub_repo=SMOKE_PIN_REPO, model_id=None, model_revision=SMOKE_PIN_REVISION)
        self.expected_profile = SimpleNamespace(spec=spec)
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append((name, bool(passed), detail))


def _smoke_item(*, tier: str = "final_gpu", model: str | None = None, cached: bool = False) -> dict[str, Any]:
    identity = model if model is not None else f"{SMOKE_PIN_REPO}@{SMOKE_PIN_REVISION}"
    return {"media_id": 1, "tier": tier, "provenance": {"model_id": identity, "cached": cached}}


def _smoke_checks(item: Mapping[str, Any]) -> list[tuple[str, bool, str]]:
    sink = _SmokeCheckSink()
    _smoke()._check_item_provenance(sink, [dict(item)], set())
    return sink.checks


def test_control_smoke_uncached_final_gpu_pinned_item_passes_every_check() -> None:
    checks = _smoke_checks(_smoke_item(cached=False))
    assert [name for name, _, _ in checks] == ["tier_final_gpu", "model_id_expected_profile", "model_revision_pinned"]
    assert all(passed for _, passed, _ in checks), checks


def test_control_smoke_cpu_tier_item_is_rejected_by_existing_tier_check() -> None:
    checks = {name: passed for name, passed, _ in _smoke_checks(_smoke_item(tier="provisional_cpu"))}
    assert checks["tier_final_gpu"] is False


def test_control_smoke_wrong_model_identity_is_rejected_by_existing_model_check() -> None:
    checks = {name: passed for name, passed, _ in _smoke_checks(_smoke_item(model="example-org/other@rev-x"))}
    assert checks["model_id_expected_profile"] is False


def _sampler_record(stdout: str) -> dict[str, Any]:
    sampler_cls = _sampler_module().VramSampler

    def runner(argv: Iterable[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout=stdout, stderr="")

    sampler = sampler_cls(interval_s=0.0, runner=runner)
    sampler._sample()
    return sampler.stop()


def test_control_sampler_two_clean_newline_terminated_rows_are_measured() -> None:
    record = _sampler_record("1024, 24576\n2048, 24576\n")
    assert record["status"] == "measured"
    assert (record["gpu_count"], record["total_mb"], record["peak_used_mb"]) == (2, 49152, 3072)
    assert record["per_gpu_used_mb_at_peak"] == [1024, 2048]


def test_control_sampler_memory_only_record_carries_no_process_or_gpu_identity() -> None:
    # The in-repo NVIDIA producer is memory-only. This control proves it cannot establish
    # process/GPU identity alone, so G2 must not read a MEASURED record as loaded-model proof.
    record = _sampler_record("1024, 24576\n2048, 24576\n")
    assert {"pid", "process_name", "gpu_uuid"}.isdisjoint(record)


# ---------------------------------------------------------------------------
# CAUSAL REDs on unchanged production. Each must FAIL now. Failure = defect in existing behaviour.
# ---------------------------------------------------------------------------


def test_red_smoke_tier_predicate_accepts_cached_final_gpu_replay() -> None:
    # Producer: visual_facts_service._row_to_response sets tier=final_gpu for any GPU-adapter row,
    # including cache hits (cached=True). describe_run.py:370 carries provenance.cached through.
    # Predicate: gpu_burst_smoke._check_item_provenance checks tier, model, and revision but never
    # provenance.cached. Single differing factor from the control: cached=True.
    checks = _smoke_checks(_smoke_item(cached=True))
    assert not all(passed for _, passed, _ in checks), (
        "a cached final_gpu replay satisfied every final_gpu predicate; the predicate does not "
        f"establish uncached GPU execution: {checks}"
    )


def test_red_sampler_truncated_total_is_measured_as_fabricated_capacity() -> None:
    # Control: "1024, 24576\n2048, 24576\n". Single differing factor: the second row is truncated
    # mid-number ("2457" for "24576") with no terminating newline. The producer parses the
    # truncated total as real and reports MEASURED total_mb=27033 instead of refusing the sample.
    record = _sampler_record("1024, 24576\n2048, 2457")
    assert record["status"] != "measured", (
        f"truncated nvidia-smi output was reported as MEASURED total_mb={record.get('total_mb')} "
        f"gpu_count={record.get('gpu_count')}"
    )


def test_red_sampler_malformed_row_is_silently_dropped_while_measured() -> None:
    # Control: two clean rows. Single differing factor: the second row is unparseable
    # ("GPU lost"). The producer drops it, keeps the first row, and reports MEASURED gpu_count=1.
    record = _sampler_record("1024, 24576\nGPU lost, \n")
    assert record["status"] != "measured", (
        f"a dropped malformed row was reported as MEASURED with gpu_count={record.get('gpu_count')}"
    )


# ---------------------------------------------------------------------------
# G2 FUTURE-INTERFACE PROPOSAL. Proposed collector: collect_runtime_evidence(*, runner, observation, deadline).
# Result keys: section, status (complete|incomplete|contradicted), observations, missing_reasons,
# contradictions, artifacts. Artifact keys are ARTIFACT_KEYS. Deadline exposes remaining() seconds.
# Vocabulary frozen here for v1 (proposal, not a produced fact).
# ---------------------------------------------------------------------------


def _obs(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return result["observations"]


@_PENDING
def test_proposal_happy_path_joins_every_runtime_observation() -> None:
    result, _runner = _collect(_healthy_script())
    assert result["section"] == "runtime"
    assert result["status"] == "complete", (result["missing_reasons"], result["contradictions"])
    assert result["missing_reasons"] == []
    assert result["contradictions"] == []
    obs = _obs(result)
    assert obs["instance"]["lifecycle_state"] == "RUNNING"
    assert obs["container"]["container_id"] == CONTAINER_ID
    assert obs["container"]["image_id"] == IMAGE_ID
    assert obs["process"]["pid"] == CONTAINER_PID
    assert obs["process"]["start_ticks"] == CONTAINER_START_TICKS
    assert obs["gpu"]["gpu_uuid"] == GPU_UUID
    assert obs["gpu"]["pid"] == CONTAINER_PID
    assert obs["mapped"]["model"]["sha256"] == MODEL_SHA256
    assert obs["mapped"]["projector"]["sha256"] == PROJECTOR_SHA256
    assert obs["runtime"]["offload"]["gpu_layers"] == 49
    assert obs["runtime"]["offload"]["total_layers"] == 49
    assert obs["runtime"]["build"] == "b8123"
    assert obs["request"]["completion_request_id"] == REQUEST_ID
    assert obs["request"]["image_sha256"] == _hashing().compute_image_hash(IMAGE_BYTES)


@_PENDING
def test_proposal_artifacts_retain_exact_raw_bytes_and_argv() -> None:
    result, runner = _collect(_healthy_script())
    artifacts = result["artifacts"]
    assert artifacts, "no raw-artifact custody emitted"
    for artifact in artifacts:
        assert tuple(sorted(artifact)) == tuple(sorted(ARTIFACT_KEYS)), artifact
        raw = [call["stdout"] for call in runner.trace if call["argv"] == artifact["command_argv"]]
        assert artifact["sha256"] in {_sha(item) for item in raw}, artifact
        assert artifact["exit_code"] == 0
    boot = [a for a in artifacts if a["command_argv"] == list(ARGV_BOOT)]
    assert boot and boot[0]["sha256"] == _sha(_text(BOOT_ID)), "trailing newline must be part of the digested bytes"


@_PENDING
def test_proposal_boot_id_change_between_capture_ends_is_stale_boot() -> None:
    script = _healthy_script({ARGV_BOOT: [_done(ARGV_BOOT, _text(BOOT_ID)), _done(ARGV_BOOT, _text(BOOT_ID_PREVIOUS))]})
    result, _ = _collect(script)
    _assert_contradiction(result, "boot_changed")


@_PENDING
def test_proposal_container_id_change_between_capture_ends_is_contradiction() -> None:
    script = _healthy_script(
        {
            ARGV_INSPECT: [
                _done(ARGV_INSPECT, _inspect_json()),
                _done(ARGV_INSPECT, _inspect_json(container_id=CONTAINER_ID_RESTARTED)),
            ]
        }
    )
    result, _ = _collect(script)
    _assert_contradiction(result, "container_changed")


@_PENDING
def test_proposal_pid_start_change_is_pid_reuse_not_the_same_process() -> None:
    script = _healthy_script(
        {
            ARGV_PROC_STAT: [
                _done(ARGV_PROC_STAT, _proc_stat(CONTAINER_START_TICKS)),
                _done(ARGV_PROC_STAT, _proc_stat(CONTAINER_START_TICKS + 5000)),
            ]
        }
    )
    result, _ = _collect(script)
    _assert_contradiction(result, "pid_reused")


@_PENDING
def test_proposal_other_gpu_process_alone_is_never_attributed_to_the_container() -> None:
    script = _healthy_script(
        {ARGV_GPU_APPS: [_done(ARGV_GPU_APPS, _gpu_apps_csv([(OTHER_GPU_PID, "python3", 512, GPU_UUID)]))]}
    )
    result, _ = _collect(script)
    _assert_missing(result, "gpu_process_for_container_absent")
    assert _obs(result)["gpu"]["pid"] is None


@_PENDING
def test_proposal_mapped_model_disagreeing_with_server_argv_is_contradiction() -> None:
    # argv says /models/<MODEL_FILE> (container view) -> host /opt/acx-gpu/models/<MODEL_FILE>.
    # Maps show a different backing file. The collector must hash what is mapped and flag the mismatch.
    script = _healthy_script({ARGV_PROC_MAPS: [_done(ARGV_PROC_MAPS, _maps(model_path=OTHER_MODEL_HOST_PATH))]})
    script.update(_file_script(OTHER_MODEL_HOST_PATH, MODEL_INODE, _sha(b"other")))
    result, _ = _collect(script)
    _assert_contradiction(result, "mapped_model_argv_mismatch")
    assert _obs(result)["mapped"]["model"]["host_path"] == OTHER_MODEL_HOST_PATH


@_PENDING
def test_proposal_mapped_projector_disagreeing_with_server_argv_is_contradiction() -> None:
    script = _healthy_script({ARGV_PROC_MAPS: [_done(ARGV_PROC_MAPS, _maps(projector_path=OTHER_PROJECTOR_HOST_PATH))]})
    script.update(_file_script(OTHER_PROJECTOR_HOST_PATH, PROJECTOR_INODE, _sha(b"other-mmproj")))
    result, _ = _collect(script)
    _assert_contradiction(result, "mapped_projector_argv_mismatch")


@_PENDING
def test_proposal_model_file_replaced_after_mapping_is_contradiction() -> None:
    # Maps inode 917001 but the path now resolves to a different inode: the hashed bytes are not the mapped bytes.
    stat_argv, _sha_argv = _file_argvs(MODEL_HOST_PATH)
    script = _healthy_script({stat_argv: [_done(stat_argv, _text(str(MODEL_INODE + 1)))]})
    result, _ = _collect(script)
    _assert_contradiction(result, "mapped_file_replaced")


@_PENDING
def test_proposal_cpu_offload_zero_layers_is_contradiction() -> None:
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD, LOG_OFFLOAD_CPU, LOG_COMPLETION))]})
    result, _ = _collect(script)
    _assert_contradiction(result, "offload_cpu")
    assert _obs(result)["runtime"]["offload"]["gpu_layers"] == 0


@_PENDING
def test_proposal_absent_offload_line_is_missing_despite_gpus_all_and_gpu_process() -> None:
    # --gpus all (DeviceRequests) and GPU utilization are present, but no factual offload line exists.
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD, LOG_COMPLETION))]})
    result, _ = _collect(script)
    _assert_missing(result, "offload_line_absent")
    assert _obs(result)["runtime"]["offload"] is None


@_PENDING
def test_proposal_stale_startup_log_before_container_start_is_excluded() -> None:
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_OFFLOAD_STALE, LOG_BUILD, LOG_COMPLETION))]})
    result, _ = _collect(script)
    _assert_missing(result, "startup_log_stale")
    assert _obs(result)["runtime"]["offload"] is None


@_PENDING
def test_proposal_cached_request_without_server_completion_is_missing() -> None:
    # A cached replay produces no server completion for this request id. The collector must not
    # treat the adapter-side request record or an offload line as completion proof.
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD, LOG_OFFLOAD_GPU))]})
    result, _ = _collect(script)
    _assert_missing(result, "request_completion_absent")
    assert _obs(result)["request"]["completion_request_id"] is None


@_PENDING
def test_proposal_completion_for_another_request_is_not_attributed() -> None:
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD, LOG_OFFLOAD_GPU, LOG_COMPLETION_OTHER))]})
    result, _ = _collect(script)
    _assert_missing(result, "request_completion_absent")
    assert _obs(result)["request"]["completion_request_id"] is None


@_PENDING
def test_proposal_maps_permission_denied_is_missing_and_never_fabricated_from_argv() -> None:
    # The collector must not hash the argv-derived path when /proc/<pid>/maps is unreadable.
    # Those file reads are absent from the frozen script, so any attempt is an unscripted argv.
    denied = _done(ARGV_PROC_MAPS, b"", rc=1, stderr=b"cat: /proc/4242/maps: Permission denied\n")
    script = _healthy_script({ARGV_PROC_MAPS: [denied]})
    for argv in _file_argvs(MODEL_HOST_PATH) + _file_argvs(PROJECTOR_HOST_PATH):
        script.pop(argv, None)
    result, _ = _collect(script)
    _assert_missing(result, "maps_unreadable")
    assert _obs(result)["mapped"]["model"]["sha256"] is None
    assert _obs(result)["mapped"]["projector"]["sha256"] is None


@_PENDING
def test_proposal_wrong_instance_is_contradiction() -> None:
    script = _healthy_script(
        {ARGV_INSTANCE: [_done(ARGV_INSTANCE, _instance_json(instance_id="ocid1.instance.oc1..other"))]}
    )
    result, _ = _collect(script)
    _assert_contradiction(result, "instance_mismatch")


@_PENDING
def test_proposal_instance_not_running_is_missing() -> None:
    script = _healthy_script({ARGV_INSTANCE: [_done(ARGV_INSTANCE, _instance_json(state="STOPPED"))]})
    result, _ = _collect(script)
    _assert_missing(result, "instance_not_running")


@_PENDING
def test_proposal_gpu_query_timeout_is_missing_reason_not_a_crash() -> None:
    script = _healthy_script({ARGV_GPU_APPS: [_timeout(ARGV_GPU_APPS)]})
    result, runner = _collect(script)
    _assert_missing(result, "gpu_query_timeout")
    assert _obs(result)["gpu"]["pid"] is None
    assert any(call["argv"] == list(ARGV_GPU_APPS) and call["timeout"] for call in runner.trace)


@_PENDING
def test_proposal_nonzero_command_is_recorded_and_its_stdout_is_not_parsed() -> None:
    # rc=9 with a parseable-looking row. The row must not be attributed.
    failed = _done(ARGV_GPU_APPS, _gpu_apps_csv(), rc=9, stderr=b"Unable to determine the device handle\n")
    result, _ = _collect(_healthy_script({ARGV_GPU_APPS: [failed]}))
    _assert_missing(result, "command_failed")
    assert _obs(result)["gpu"]["pid"] is None
    recorded = [a for a in result["artifacts"] if a["command_argv"] == list(ARGV_GPU_APPS)]
    assert recorded and recorded[0]["exit_code"] == 9


@_PENDING
def test_proposal_truncated_log_output_is_refused_and_not_partially_parsed() -> None:
    # Offload line sits at the head, so a naive parser would find it. Output exceeds the frozen cap.
    oversized = _logs(LOG_BUILD, LOG_OFFLOAD_GPU, LOG_COMPLETION) + (b"x" * ((2 << 20) + 1))
    result, _ = _collect(_healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, oversized)]}))
    _assert_missing(result, "output_truncated")
    assert _obs(result)["runtime"]["offload"] is None
    assert _obs(result)["request"]["completion_request_id"] is None


@_PENDING
def test_proposal_deadline_exhaustion_stops_calls_and_reports_missing() -> None:
    deadline = FakeDeadline(10.0)
    costs = dict.fromkeys(_healthy_script(), 4.0)
    result, runner = _collect(_healthy_script(), deadline=deadline, costs=costs)
    assert len(runner.trace) <= 3, [call["argv"] for call in runner.trace]
    _assert_missing(result, "deadline_exhausted")


@_PENDING
def test_proposal_calls_are_bounded_shell_free_and_never_read_the_secret_key() -> None:
    result, runner = _collect(_healthy_script())
    assert len(runner.trace) <= MAX_CALLS
    for call in runner.trace:
        assert call["shell"] is False
        assert call["text"] is False
        assert call["capture_output"] is True
        assert all(isinstance(part, str) for part in call["argv"])
        assert SECRET_KEY_PATH not in call["argv"]
    assert result["status"] == "complete"


@_PENDING
def test_proposal_utilization_config_pins_v1models_gpus_all_and_file_exist_never_prove_load() -> None:
    script = {
        ARGV_INSTANCE: [_done(ARGV_INSTANCE, _instance_json())],
        ARGV_GPU_UTIL: [_done(ARGV_GPU_UTIL, b"98\n")],
        ARGV_CONFIG_PINS: [_done(ARGV_CONFIG_PINS, f"ACX_GPU_MODEL={MODEL_FILE}\n".encode())],
        ARGV_V1_MODELS: [_done(ARGV_V1_MODELS, json.dumps({"data": [{"id": MODEL_ID}]}).encode())],
        ARGV_FILE_EXISTS: [_done(ARGV_FILE_EXISTS, b"")],
        ARGV_INSPECT: [_done(ARGV_INSPECT, _inspect_json(device_requests=True))],
    }
    result, _ = _collect(script, allow_unscripted=True)
    assert result["status"] != "complete"
    obs = _obs(result)
    assert obs["gpu"]["pid"] is None
    assert obs["mapped"]["model"]["sha256"] is None
    assert obs["runtime"]["offload"] is None
    assert obs["request"]["completion_request_id"] is None
    assert "gpu_process_for_container_absent" in result["missing_reasons"]


@_PENDING
def test_proposal_observations_never_copy_expected_policy_or_secret_keys() -> None:
    result, _ = _collect(_healthy_script())
    forbidden = re.compile(r"expected|policy|pin|secret|token|password", re.IGNORECASE)
    assert not [key for key in _walk_keys(_obs(result)) if forbidden.search(key)]
    assert SECRET_KEY_PATH not in json.dumps(_obs(result))


@_PENDING
def test_proposal_build_identity_is_not_inferred_from_the_image_tag() -> None:
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_OFFLOAD_GPU, LOG_COMPLETION))]})
    result, _ = _collect(script)
    _assert_missing(result, "build_line_absent")
    assert _obs(result)["runtime"]["build"] is None


@_PENDING
def test_proposal_observed_build_is_recorded_verbatim_not_judged_against_policy() -> None:
    # The collector reports what it observed. Comparison to the pinned runtime build is G1's job.
    script = _healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD_OLD, LOG_OFFLOAD_GPU, LOG_COMPLETION))]})
    result, _ = _collect(script)
    assert _obs(result)["runtime"]["build"] == "b7000"
    assert result["contradictions"] == []


@_PENDING
def test_proposal_observed_image_id_is_recorded_verbatim_not_judged_against_policy() -> None:
    # A wrong runtime image is recorded as observed. Pin comparison belongs to G1, never to the collector.
    result, _ = _collect(_healthy_script({ARGV_INSPECT: [_done(ARGV_INSPECT, _inspect_json(image_id=IMAGE_ID_OTHER))]}))
    assert _obs(result)["container"]["image_id"] == IMAGE_ID_OTHER
    assert _obs(result)["container"]["image_ref"] == IMAGE_REF
    assert result["contradictions"] == []


@_PENDING
def test_proposal_applied_input_and_prompt_hashes_follow_retained_request_bytes() -> None:
    hashing = _hashing()
    first_result, _ = _collect(_healthy_script(), observation=_observation())
    changed = _observation(request_body=_request_body(image=b"changed-image-bytes\n"))
    second_result, _ = _collect(_healthy_script(), observation=changed)
    first = _obs(first_result)["request"]
    second = _obs(second_result)["request"]
    assert first["image_sha256"] == hashing.compute_image_hash(IMAGE_BYTES)
    assert second["image_sha256"] == hashing.compute_image_hash(b"changed-image-bytes\n")
    assert first["image_sha256"] != second["image_sha256"]
    assert first["system_prompt_sha256"] == _sha(SYSTEM_PROMPT.encode())
    assert first["user_text_sha256"] == _sha(USER_TEXT.encode())
    assert first["request_body_sha256"] == _sha(_observation()["request_body"])
