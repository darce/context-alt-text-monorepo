"""GTMR G2 runtime receipts: offline causal REDs, healthy controls, and collector proposal.

Owner: lane G2 (proposed owner of scripts/collect_gpu_runtime_evidence.py).
Frozen protocol: FROZEN ADDITIVE STRICT GPU EVIDENCE CONTRACT v1. The contract is an
expected protocol, never an observation. This file authors tests only.

Fixture origins predate the current collector; this file does not attest source ancestry.

Three test classes are reported separately:

``test_control_*``   Healthy controls on UNCHANGED production. They must pass now and after
                     any fix.
``test_red_*``       Regression assertions. The two sampler hypotheticals are strict xfails:
                     c67 supplied no native receipt proving truncation or successful malformed rows.
``test_proposal_*``  Legacy proposal oracles for scripts/collect_gpu_runtime_evidence.py. Marked
                     xfail(reason=PROPOSAL_PENDING) only while that module is absent; import absence is
                     not a behaviour defect. The module now exists, so these run as ordinary assertions
                     through ``_legacy_view`` (one-to-one ABI v1 -> legacy names, absent fields -> None).
                     The five c67 ABI corrections assert the frozen envelope directly: runtime kinds,
                     separate stream/receipt/capture custody, verbatim identities and canonical prompt.
``test_<ABI>``      ABI v1 selectors (receipts, identity, completion binding, custody, redaction,
                     readiness). Each asserts the frozen envelope directly through ``result["abi"]``.
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
import importlib
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

import httpx
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
LOG_COMPLETION_STALE = f"{T_STALE} srv  log_server_r: request_id={REQUEST_ID} status=200 completion"

# Adapter receipt fixtures (ABI v1 inference lineage). Client timings bracket the server completion.
FIXTURE_CAPTION = b"fixture caption"
RESPONSE_BODY = b'{"choices":[{"message":{"content":"fixture caption"}}]}\n'
RECEIPT_STARTED_AT = "2026-10-12T00:00:05.000000Z"
RECEIPT_FINISHED_AT = "2026-10-12T00:00:20.500000Z"

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
        # Vocabulary extension for the collector's documented codes (kept in sync by
        # test_vocabulary_matches_collector_declared_vocabulary).
        "boot_id_unparseable",
        "call_budget_exhausted",
        "caption_absent",
        "clock_relationship_undeclared",
        "cmdline_unparsed",
        "command_timeout",
        "dependency_absent",
        "digest_unparseable",
        "endpoint_unparseable",
        "file_stat_unparseable",
        "gpu_query_unparseable",
        "http_status_absent",
        "inspect_malformed",
        "instance_unparseable",
        "instruction_absent",
        "mapped_file_absent",
        "mount_absent",
        "receipt_over_budget",
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
        "build_ambiguous",
        "completion_ambiguous",
        "gpu_identity_changed",
        "gpu_process_ambiguous",
        "offload_ambiguous",
        "receipt_body_mismatch",
        "receipt_malformed",
        "request_id_collision",
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
    is set, in which case it returns rc=127. ``trace`` keeps both streams and all supplied keyword names.
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
        **extra: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        capture_output = extra.get("capture_output", False)
        text = extra.get("text", False)
        check = extra.get("check", False)
        shell = extra.get("shell", False)
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
                "stderr": None,
                "exit_code": None,
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
        self.trace[-1]["stderr"] = outcome.stderr
        self.trace[-1]["exit_code"] = outcome.returncode
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


def _body_image(body: bytes) -> bytes:
    url = json.loads(body)["messages"][1]["content"][0]["image_url"]["url"]
    return base64.b64decode(url.split(",", maxsplit=1)[1])


def _receipt_for(
    body: bytes,
    *,
    kind: str = "caption",
    correlation_id: str = REQUEST_ID,
    source: bytes | None = None,
    encoded: bytes | None = None,
    caption: bytes = FIXTURE_CAPTION,
) -> dict[str, Any]:
    """Adapter receipt shape (raw custody bytes only). Source defaults to the body image: no transcode."""
    decoded = _body_image(body)
    return {
        "request_kind": kind,
        "correlation_id": correlation_id,
        "media_type": "image/png",
        "request_body": body,
        "source_image": source if source is not None else decoded,
        "encoded_image": encoded if encoded is not None else decoded,
        "context_canonical": b"{}",
        "caption": caption,
        "response_body": RESPONSE_BODY,
        "status_code": 200,
        "started_at": RECEIPT_STARTED_AT,
        "finished_at": RECEIPT_FINISHED_AT,
    }


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instance_id": INSTANCE_ID,
        "container_name": CONTAINER_NAME,
        "request_id": REQUEST_ID,
        "request_body": _request_body(),
    }
    base.update(overrides)
    # Fixture correction: the adapter receipt is the lineage source. Derive a consistent one from the body
    # unless the caller supplies receipts explicitly. Assertions are unchanged.
    base.setdefault("adapter_receipts", [_receipt_for(base["request_body"])])
    return base


def _legacy_view(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One-to-one view of the frozen ABI v1 runtime section in the legacy proposal names.

    Absent ABI fields map to None. Legacy keys with no ABI counterpart (instance lifecycle, image_ref,
    total_layers, prompt-part hashes) stay None; corrected oracles assert the ABI directly.
    """
    section = raw["section"]
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for obs in section["observations"]:
        by_kind.setdefault(obs["kind"], []).append(obs["data"])
    identity = {data["phase"]: data for data in by_kind.get("runtime_identity", [])}
    before = identity.get("before", {})
    mapped = (by_kind.get("mapped_model") or [{}])[0]
    inference = (by_kind.get("inference") or [{}])[0]
    gpu_layers = mapped.get("offloaded_layers")
    observations = {
        "instance": {"lifecycle_state": None},
        "container": {
            "container_id": before.get("container_id"),
            "image_id": before.get("container_image_id"),
            "image_ref": None,
        },
        "process": {"pid": before.get("pid"), "start_ticks": before.get("start_ticks")},
        "gpu": {
            "gpu_uuid": before.get("gpu_uuid"),
            "pid": before.get("pid") if before.get("gpu_uuid") else None,
        },
        "mapped": {
            "model": {"host_path": mapped.get("model_path"), "sha256": mapped.get("model_sha256")},
            "projector": {"host_path": mapped.get("projector_path"), "sha256": mapped.get("projector_sha256")},
        },
        "runtime": {
            "offload": None if gpu_layers is None else {"gpu_layers": gpu_layers, "total_layers": None},
            "build": mapped.get("build_identity"),
        },
        "request": {
            "completion_request_id": inference.get("inference_request_id"),
            "image_sha256": inference.get("source_image_sha256"),
            "request_body_sha256": inference.get("request_body_sha256"),
            "system_prompt_sha256": None,
            "user_text_sha256": None,
        },
    }
    return {
        "section": "runtime",
        "status": section["status"],
        "observations": observations,
        "missing_reasons": [issue["code"] for issue in section["missing_reasons"]],
        "contradictions": [issue["code"] for issue in section["contradictions"]],
        "artifacts": raw["artifacts"],
        "abi": raw,
    }


def _collect(
    script: Mapping[tuple[str, ...], list[Any]],
    *,
    deadline: FakeDeadline | None = None,
    costs: Mapping[tuple[str, ...], float] | None = None,
    observation: Mapping[str, Any] | None = None,
    allow_unscripted: bool = False,
) -> tuple[Mapping[str, Any], FrozenRunner]:
    """Run the collector against the frozen runner. Raises CollectorAbsentError while pending.

    The collector returns the frozen ABI v1 envelope fragment {section, artifacts, raw_artifacts}. The
    returned view keeps the untouched ABI result under ``abi`` for ABI-shaped selectors.
    """

    dl = deadline if deadline is not None else FakeDeadline(600.0)
    runner = FrozenRunner(script, deadline=dl, costs=costs, allow_unscripted=allow_unscripted)
    module = _collector()
    raw = module.collect_runtime_evidence(
        runner=runner,
        observation=dict(observation) if observation is not None else _observation(),
        deadline=dl,
        # Declared synthetic fixture clock relationship; never observed clock evidence.
        clock_skew_bound_s=1.0,
    )
    if not allow_unscripted:
        assert runner.unexpected == [], f"argv outside the frozen trace reached the runner: {runner.unexpected}"
    assert runner.violations == [], runner.violations
    assert set(raw) == {"section", "artifacts", "raw_artifacts"}, sorted(raw)
    assert set(raw["section"]) == {"status", "observations", "missing_reasons", "contradictions"}
    assert raw["section"]["status"] in STATUSES, raw["section"]["status"]
    result = _legacy_view(raw)
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
# Regression assertions; the two unproven sampler hypotheticals are labelled separately.
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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="G2 sampler native receipt unproven (c67): numeric EOF does not prove truncation")
def test_red_sampler_truncated_total_is_measured_as_fabricated_capacity() -> None:
    # Hypothetical only: no native receipt or framing contract proves these numeric bytes were truncated.
    record = _sampler_record("1024, 24576\n2048, 2457")
    assert record["status"] != "measured", (
        f"truncated nvidia-smi output was reported as MEASURED total_mb={record.get('total_mb')} "
        f"gpu_count={record.get('gpu_count')}"
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="G2 sampler native receipt unproven (c67): successful malformed row lacks a producer receipt")
def test_red_sampler_malformed_row_is_silently_dropped_while_measured() -> None:
    # Hypothetical only: no native receipt attests this malformed row with a successful exit status.
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
    section = _abi(result)["section"]
    assert sorted(obs["kind"] for obs in section["observations"]) == [
        "inference", "mapped_model", "runtime_identity", "runtime_identity",
    ]
    identities = _kinds(section, "runtime_identity")
    assert [obs["data"] for obs in identities] == [
        {"instance_id": INSTANCE_ID, "boot_id": BOOT_ID, "container_id": CONTAINER_ID,
         "container_image_id": IMAGE_ID, "pid": CONTAINER_PID, "start_ticks": CONTAINER_START_TICKS,
         "gpu_uuid": GPU_UUID, "phase": phase}
        for phase in ("before", "after")
    ]
    assert _kinds(section, "mapped_model")[0]["data"] == {
        "instance_id": INSTANCE_ID, "boot_id": BOOT_ID, "container_id": CONTAINER_ID,
        "pid": CONTAINER_PID, "start_ticks": CONTAINER_START_TICKS,
        "model_path": MODEL_HOST_PATH, "model_sha256": MODEL_SHA256,
        "projector_path": PROJECTOR_HOST_PATH, "projector_sha256": PROJECTOR_SHA256,
        "build_identity": "8123 (5e1f2ab)", "offloaded_layers": 49, "gpu_execution": True,
    }
    inference = _kinds(section, "inference")[0]["data"]
    assert inference["inference_request_id"] == REQUEST_ID
    assert inference["source_image_sha256"] == _hashing().compute_image_hash(IMAGE_BYTES)
    for key in ("instance_id", "boot_id", "container_id", "pid", "start_ticks", "gpu_uuid"):
        assert inference[key] == identities[0]["data"][key], key


@_PENDING
def test_proposal_artifacts_retain_exact_raw_bytes_and_argv() -> None:
    observation = _observation()
    script = _healthy_script({ARGV_BOOT: [_done(ARGV_BOOT, _text(BOOT_ID), stderr=b"fixture diagnostic\n")]})
    result, runner = _collect(script, observation=observation)
    raw = _abi(result)
    artifacts = {artifact["relative_path"]: artifact for artifact in raw["artifacts"]}
    assert len(artifacts) == len(raw["artifacts"]), "duplicate artifact path"
    assert set(artifacts) == set(raw["raw_artifacts"])
    for path, artifact in artifacts.items():
        assert tuple(sorted(artifact)) == tuple(sorted(ARTIFACT_KEYS)), artifact
        assert artifact["sha256"] == _sha(raw["raw_artifacts"][path]), path
        assert not Path(path).is_absolute() and ".." not in Path(path).parts, path
    capture_paths = [path for path in artifacts if path.endswith("/capture.json")]
    assert len(capture_paths) == 1
    capture_path = capture_paths[0]
    capture = json.loads(raw["raw_artifacts"][capture_path])
    assert capture["schema_version"] == 1
    assert len(capture["calls"]) == len(runner.trace)
    covered = {capture_path}
    for call, traced in zip(capture["calls"], runner.trace):
        assert call["argv"] == traced["argv"]
        assert call["exit_code"] == traced["exit_code"] == 0
        assert call["timed_out"] is False and call["truncated"] is False
        for stream in ("stdout", "stderr"):
            ref = call[stream]
            path = ref["relative_path"]
            assert path not in covered
            covered.add(path)
            assert path.endswith("." + stream)
            assert raw["raw_artifacts"][path] == traced[stream], (path, stream)
            assert ref["bytes_received"] == ref["bytes_persisted"] == len(traced[stream])
            assert ref["sha256"] == artifacts[path]["sha256"]
            assert artifacts[path]["command_argv"] == traced["argv"]
            assert artifacts[path]["exit_code"] == traced["exit_code"]
            assert artifacts[path]["capture_started_at"] is None
            assert artifacts[path]["capture_finished_at"] is None
    receipt = observation["adapter_receipts"][0]
    parts = ("request_body", "source_image", "encoded_image", "context_canonical", "response_body", "caption")
    for part in parts:
        paths = [path for path in artifacts if path.endswith(f"-caption-{part}.bin")]
        assert len(paths) == 1, part
        path = paths[0]
        covered.add(path)
        assert raw["raw_artifacts"][path] == receipt[part], part
    meta_paths = [path for path in artifacts if path.endswith("-caption-meta.json")]
    assert len(meta_paths) == 1
    meta_path = meta_paths[0]
    covered.add(meta_path)
    assert json.loads(raw["raw_artifacts"][meta_path]) == {
        **{key: receipt[key] for key in ("request_kind", "correlation_id", "media_type", "status_code", "started_at", "finished_at")},
        "parts": {part: {"bytes": len(receipt[part]), "sha256": _sha(receipt[part])} for part in parts},
    }
    for path, artifact in artifacts.items():
        if path == capture_path or "/receipts/" in path:
            assert artifact["command_argv"] == [] and artifact["exit_code"] is None
            assert artifact["capture_started_at"] == (None if path == capture_path else receipt["started_at"])
            assert artifact["capture_finished_at"] == (None if path == capture_path else receipt["finished_at"])
    assert covered == set(artifacts), "unexpected or missing artifact source"


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


# Retired G2-R06 policy oracle: zero offload is covered as an observation by the G2 findings module.


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
        # The trace records every supplied keyword except timeout, including legacy subprocess flags.
        assert 0 < call["timeout"] <= 15
        assert call["extra_kwargs"] == ["max_bytes"]
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
        # Fixture correction: the compute-apps query ran successfully and listed no process for the
        # container (utilization 98% is not a process listing). An unscripted query is a failed
        # command, not absence, so this script states the observed empty listing explicitly.
        ARGV_GPU_APPS: [_done(ARGV_GPU_APPS, _gpu_apps_csv([]))],
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
    mapped = _kinds(_abi(result)["section"], "mapped_model")
    assert len(mapped) == 1
    assert mapped[0]["data"]["build_identity"] == "7000 (0aa11bb)"
    assert result["contradictions"] == []


@_PENDING
def test_proposal_observed_image_id_is_recorded_verbatim_not_judged_against_policy() -> None:
    # A wrong runtime image is recorded as observed. Pin comparison belongs to G1, never to the collector.
    result, _ = _collect(_healthy_script({ARGV_INSPECT: [_done(ARGV_INSPECT, _inspect_json(image_id=IMAGE_ID_OTHER))]}))
    identities = _kinds(_abi(result)["section"], "runtime_identity")
    assert [obs["data"]["phase"] for obs in identities] == ["before", "after"]
    assert all(obs["data"]["container_image_id"] == IMAGE_ID_OTHER for obs in identities)
    raw = _abi(result)["raw_artifacts"]
    inspect_bytes = [data for path, data in raw.items() if path.endswith("-inspect.stdout")]
    assert len(inspect_bytes) == 2
    assert all(json.loads(data)[0]["Config"]["Image"] == IMAGE_REF for data in inspect_bytes)
    assert result["contradictions"] == []


@_PENDING
def test_proposal_applied_input_and_prompt_hashes_follow_retained_request_bytes() -> None:
    hashing = _hashing()
    first_result, _ = _collect(_healthy_script(), observation=_observation())
    changed_system, changed_user = "Changed system prompt: café", "Changed user text: harbor"
    changed = _observation(request_body=_request_body(
        image=b"changed-image-bytes\n", system=changed_system, user=changed_user,
    ))
    second_result, _ = _collect(_healthy_script(), observation=changed)
    first = _kinds(_abi(first_result)["section"], "inference")[0]["data"]
    second = _kinds(_abi(second_result)["section"], "inference")[0]["data"]
    assert first["source_image_sha256"] == hashing.compute_image_hash(IMAGE_BYTES)
    assert second["source_image_sha256"] == hashing.compute_image_hash(b"changed-image-bytes\n")
    assert first["source_image_sha256"] != second["source_image_sha256"]
    for data, observation in ((first, _observation()), (second, changed)):
        request = observation["request_body"]
        messages = json.loads(request)["messages"]
        prompt = json.dumps(
            {"system_prompt": messages[0]["content"], "user_text": messages[1]["content"][1]["text"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        assert data["prompt_sha256"] == _sha(prompt)
        assert data["encoded_image_sha256"] == _sha(_body_image(request))
        assert data["request_body_sha256"] == _sha(request)
    assert first["prompt_sha256"] != second["prompt_sha256"]
    assert first["request_body_sha256"] != second["request_body_sha256"]


# ---------------------------------------------------------------------------
# G2 ABI v1 SELECTORS. Smoke and adapter selectors run against the unchanged module files and
# are NOT pending. Collector selectors use _PENDING until scripts/collect_gpu_runtime_evidence.py
# exists. Every selector asserts the frozen envelope; none is a skip or an xfail that hides a defect.
# ---------------------------------------------------------------------------

APP_ROOT = REPO_ROOT / "apps" / "prototype-description-service"


def _abi(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return result["abi"]


def _kinds(section: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    return [obs for obs in section["observations"] if obs["kind"] == kind]


def test_cached_final_gpu_is_not_new_execution() -> None:
    # Single differing factor from the uncached control: provenance.cached. The item stays final_gpu
    # with the pinned identity, so only the cache predicate can reject it. An absent cached flag is
    # refused too: an unobservable cache state cannot prove new GPU execution (fail closed).
    cached = {name: passed for name, passed, _ in _smoke_checks(_smoke_item(cached=True))}
    assert cached["tier_final_gpu"] is False, cached
    absent_item = _smoke_item(cached=False)
    del absent_item["provenance"]["cached"]
    absent = {name: passed for name, passed, _ in _smoke_checks(absent_item)}
    assert absent["tier_final_gpu"] is False, absent
    uncached = {name: passed for name, passed, _ in _smoke_checks(_smoke_item(cached=False))}
    assert all(uncached.values()), uncached


def _adapter_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(APP_ROOT))
    return importlib.import_module("scene.infrastructure.vlm.gpu_remote_adapter")


def _png(size: tuple[int, int] = (17, 11)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(24, 96, 180)).save(buffer, format="PNG")
    return buffer.getvalue()


def _chat(text: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": text}}]}


def test_control_adapter_without_receipt_sink_adds_no_correlation_header(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _adapter_module(monkeypatch)
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-request-id"))
        return httpx.Response(200, json=_chat("A caption."))

    adapter = mod.GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(handler),
        grounding_enabled=False,
    )
    assert adapter.describe(image_bytes=_png(), context=None).caption == "A caption."
    assert seen == [None], "the receipt hook must be inert unless a sink is installed"


def test_adapter_receipt_records_exact_wire_bytes_and_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    from PIL import Image

    mod = _adapter_module(monkeypatch)
    wire: list[tuple[str | None, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wire.append((request.headers.get("x-request-id"), request.content))
        return httpx.Response(200, json=_chat("A WebP caption."))

    source_buffer = io.BytesIO()
    Image.new("RGB", (17, 11), color=(24, 96, 180)).save(source_buffer, format="WEBP")
    source = source_buffer.getvalue()
    receipts: list[Mapping[str, Any]] = []
    adapter = mod.GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(handler),
        grounding_enabled=False,
        receipt_sink=receipts.append,
    )
    result = adapter.describe(image_bytes=source, context={"title": "Harbor"})

    assert result.caption == "A WebP caption."
    assert len(wire) == 1 and len(receipts) == 1
    correlation, body = wire[0]
    receipt = receipts[0]
    assert receipt["request_kind"] == "caption"
    assert receipt["request_body"] == body, "receipt must hold the exact bytes that crossed the wire"
    assert receipt["correlation_id"] == correlation and correlation
    assert receipt["source_image"] == source
    encoded = _body_image(body)
    assert receipt["encoded_image"] == encoded
    assert encoded != source and encoded.startswith(b"\x89PNG\r\n\x1a\n"), "WebP->PNG transcode must be visible"
    expected_context = json.dumps({"title": "Harbor"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert receipt["context_canonical"] == expected_context.encode("utf-8")
    assert receipt["caption"] == b"A WebP caption."
    assert json.loads(receipt["response_body"])["choices"][0]["message"]["content"] == "A WebP caption."
    assert receipt["status_code"] == 200
    assert receipt["started_at"].endswith("Z") and receipt["started_at"] <= receipt["finished_at"]


def test_adapter_receipts_keep_caption_and_grounding_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _adapter_module(monkeypatch)
    replies = [_chat("A man in a red hat."), _chat("[]")]
    wire: list[tuple[str | None, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        wire.append((request.headers.get("x-request-id"), request.content))
        return httpx.Response(200, json=replies[len(wire) - 1])

    receipts: list[Mapping[str, Any]] = []
    adapter = mod.GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(handler),
        grounding_enabled=True,
        receipt_sink=receipts.append,
    )
    adapter.describe(image_bytes=_png(), context=None)

    assert [receipt["request_kind"] for receipt in receipts] == ["caption", "grounding"]
    assert len(wire) == 2
    assert receipts[0]["request_body"] != receipts[1]["request_body"]
    assert receipts[0]["correlation_id"] != receipts[1]["correlation_id"]
    assert receipts[1]["request_body"] == wire[1][1]
    assert receipts[1]["caption"] == b"A man in a red hat."
    grounding_text = json.loads(wire[1][1])["messages"][1]["content"][1]["text"]
    assert "Caption:\nA man in a red hat." in grounding_text


def test_adapter_receipt_records_rejected_endpoint_without_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _adapter_module(monkeypatch)
    receipts: list[Mapping[str, Any]] = []
    adapter = mod.GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="busy")),
        grounding_enabled=False,
        receipt_sink=receipts.append,
    )
    with pytest.raises(mod.GpuRemoteAdapterError):
        adapter.describe(image_bytes=_png(), context=None)
    assert len(receipts) == 1
    assert receipts[0]["status_code"] == 503
    assert receipts[0]["caption"] is None, "a rejected call has no caption lineage to claim"
    assert receipts[0]["response_body"] == b"busy"


def test_adapter_receipt_sink_failure_does_not_change_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _adapter_module(monkeypatch)

    def broken(_receipt: Mapping[str, Any]) -> None:
        raise RuntimeError("sink down")

    adapter = mod.GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_chat("Still a caption."))),
        grounding_enabled=False,
        receipt_sink=broken,
    )
    assert adapter.describe(image_bytes=_png(), context=None).caption == "Still a caption."


@_PENDING
@pytest.mark.parametrize(
    ("override", "code"),
    [
        (
            {ARGV_BOOT: [_done(ARGV_BOOT, _text(BOOT_ID)), _done(ARGV_BOOT, _text(BOOT_ID_PREVIOUS))]},
            "boot_changed",
        ),
        (
            {
                ARGV_INSPECT: [
                    _done(ARGV_INSPECT, _inspect_json()),
                    _done(ARGV_INSPECT, _inspect_json(container_id=CONTAINER_ID_RESTARTED)),
                ]
            },
            "container_changed",
        ),
        (
            {
                ARGV_PROC_STAT: [
                    _done(ARGV_PROC_STAT, _proc_stat(CONTAINER_START_TICKS)),
                    _done(ARGV_PROC_STAT, _proc_stat(CONTAINER_START_TICKS + 5000)),
                ]
            },
            "pid_reused",
        ),
    ],
)
def test_runtime_receipt_rejects_identity_change(override: Mapping[Any, Any], code: str) -> None:
    result, _ = _collect(_healthy_script(override))
    section = _abi(result)["section"]
    assert section["status"] == "contradicted", section["status"]
    _assert_contradiction(result, code)
    phases = [obs["data"]["phase"] for obs in _kinds(section, "runtime_identity")]
    assert phases == ["before", "after"], phases
    assert _kinds(section, "inference") == [], "a receipt bound to a changed process must not be reported"


@_PENDING
@pytest.mark.parametrize(
    ("log_lines", "code"),
    [
        ((LOG_BUILD, LOG_OFFLOAD_GPU), "request_completion_absent"),
        ((LOG_BUILD, LOG_OFFLOAD_GPU, LOG_COMPLETION_OTHER), "request_completion_absent"),
        ((LOG_BUILD, LOG_OFFLOAD_GPU, LOG_COMPLETION_STALE), "startup_log_stale"),
    ],
)
def test_runtime_receipt_requires_verified_completion_binding(log_lines: tuple[str, ...], code: str) -> None:
    # Client correlation alone is insufficient: no server completion echo for this receipt id, so no
    # inference observation may be emitted for it.
    result, _ = _collect(_healthy_script({ARGV_LOGS: [_done(ARGV_LOGS, _logs(*log_lines))]}))
    section = _abi(result)["section"]
    assert section["status"] != "complete", section["status"]
    _assert_missing(result, code)
    assert _kinds(section, "inference") == [], "unbound receipt was reported as an inference observation"


@_PENDING
def test_runtime_receipt_binds_only_the_echoed_request_id() -> None:
    result, _ = _collect(_healthy_script())
    section = _abi(result)["section"]
    inference = _kinds(section, "inference")
    assert len(inference) == 1, inference
    data = inference[0]["data"]
    assert data["inference_request_id"] == REQUEST_ID
    assert data["request_kind"] == "caption"
    assert data["completion_started_at"] == RECEIPT_STARTED_AT
    assert data["completion_finished_at"] == T_COMPLETION
    assert data["request_body_sha256"] == _sha(_observation()["request_body"])
    assert data["source_image_sha256"] == _sha(IMAGE_BYTES)
    assert data["encoded_image_sha256"] == _sha(IMAGE_BYTES)
    assert data["caption_sha256"] == _sha(FIXTURE_CAPTION)
    assert data["context_hash"] == _sha(b"{}")
    prompt = json.dumps(
        {"system_prompt": SYSTEM_PROMPT, "user_text": USER_TEXT},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert data["prompt_sha256"] == _sha(prompt.encode("utf-8"))


@_PENDING
def test_runtime_receipt_custody_matches_persisted_bytes() -> None:
    result, _ = _collect(_healthy_script())
    raw = _abi(result)
    section = raw["section"]
    artifacts = {artifact["relative_path"]: artifact for artifact in raw["artifacts"]}
    assert len(artifacts) == len(raw["artifacts"]), "duplicate artifact path"
    assert set(raw["raw_artifacts"]) == set(artifacts), "every artifact must be persisted exactly once"
    for relative_path, data in raw["raw_artifacts"].items():
        assert artifacts[relative_path]["sha256"] == _sha(data), relative_path
        assert not relative_path.startswith("/") and ".." not in Path(relative_path).parts, relative_path
    ids = [obs["observation_id"] for obs in section["observations"]]
    assert len(ids) == len(set(ids)), "observation ids must be unique"
    for obs in section["observations"]:
        assert obs["artifact_relative_path"] in artifacts, obs["observation_id"]
        assert obs["artifact_sha256"] == artifacts[obs["artifact_relative_path"]]["sha256"]
        for ref in obs["source_artifacts"]:
            assert artifacts[ref["relative_path"]]["sha256"] == ref["sha256"], ref


@_PENDING
def test_runtime_receipt_unavailable_container_producer_is_incomplete_not_manufactured() -> None:
    # The inspect producer is unavailable (runner raises). No container identity may be manufactured
    # from the instruction, and no dependent probe may claim the missing identity.
    script = _healthy_script({ARGV_INSPECT: [FileNotFoundError("docker")]})
    result, _ = _collect(script)
    assert result["status"] != "complete", result["status"]
    _assert_missing(result, "command_failed")
    assert _obs(result)["container"]["container_id"] is None
    assert _obs(result)["process"]["pid"] is None
    assert _kinds(_abi(result)["section"], "runtime_identity") == []


GROUNDING_REQUEST_ID = "gtmr-g2-req-0002"
LOG_COMPLETION_GROUNDING = f"{T_COMPLETION} srv  log_server_r: request_id={GROUNDING_REQUEST_ID} status=200 completion"


@_PENDING
def test_runtime_receipt_never_persists_container_env_secrets() -> None:
    # docker inspect Config.Env can carry credentials. Persisted bytes and every serialized section
    # must omit the value, and the capture document records the redaction and the pre-redaction digest.
    inspect_doc = json.loads(_inspect_json())
    inspect_doc[0]["Config"] = {"Env": ["ACX_GPU_API_TOKEN=fixture-secret-value", "PATH=/usr/bin"]}
    raw_inspect = (json.dumps(inspect_doc, indent=2, sort_keys=True) + "\n").encode()
    result, _ = _collect(_healthy_script({ARGV_INSPECT: [_done(ARGV_INSPECT, raw_inspect)]}))
    raw = _abi(result)
    persisted = b"".join(raw["raw_artifacts"].values())
    assert b"fixture-secret-value" not in persisted
    assert b"fixture-secret-value" not in json.dumps(raw["section"]).encode()
    capture = json.loads(raw["raw_artifacts"]["raw/runtime/capture.json"])
    inspect_calls = [call for call in capture["calls"] if call["label"].endswith("inspect")]
    assert len(inspect_calls) == 2, [call["label"] for call in inspect_calls]
    for call in inspect_calls:
        assert call["redaction"]["fields"] == ["Config.Env"], call
        assert call["redaction"]["original_stdout_sha256"] == _sha(raw_inspect), call
    assert len(_kinds(_abi(result)["section"], "runtime_identity")) == 2, "redaction must not drop identity"


@_PENDING
def test_runtime_readiness_is_unauthenticated_and_http_status_is_not_invented() -> None:
    script = _healthy_script(
        {ARGV_V1_MODELS: [_done(ARGV_V1_MODELS, json.dumps({"data": [{"id": MODEL_ID}]}).encode())]}
    )
    result, _ = _collect(script, observation=_observation(readiness=True))
    readiness = _kinds(_abi(result)["section"], "readiness")
    assert len(readiness) == 1, readiness
    assert readiness[0]["data"] == {
        "instance_id": INSTANCE_ID,
        "authenticated": False,
        "http_status": None,
        "ready": True,
    }
    _assert_missing(result, "http_status_absent")


@_PENDING
def test_runtime_receipt_keeps_caption_and_grounding_requests_distinct() -> None:
    grounding_body = _request_body(system="fixture grounding system", user="fixture grounding user")
    receipts = [
        _receipt_for(_request_body(), kind="caption", correlation_id=REQUEST_ID),
        _receipt_for(grounding_body, kind="grounding", correlation_id=GROUNDING_REQUEST_ID),
    ]
    script = _healthy_script(
        {ARGV_LOGS: [_done(ARGV_LOGS, _logs(LOG_BUILD, LOG_OFFLOAD_GPU, LOG_COMPLETION, LOG_COMPLETION_GROUNDING))]}
    )
    result, _ = _collect(script, observation=_observation(adapter_receipts=receipts))
    inference = _kinds(_abi(result)["section"], "inference")
    assert [obs["data"]["request_kind"] for obs in inference] == ["caption", "grounding"], inference
    assert inference[0]["data"]["request_body_sha256"] != inference[1]["data"]["request_body_sha256"]
    assert inference[0]["data"]["inference_request_id"] != inference[1]["data"]["inference_request_id"]
    assert inference[1]["data"]["prompt_sha256"] != inference[0]["data"]["prompt_sha256"]
    assert result["status"] == "complete", (result["missing_reasons"], result["contradictions"])


@_PENDING
def test_runtime_receipt_encoded_bytes_must_match_the_request_body() -> None:
    # The adapter's encoded-image record must be the image the request body carried. A mismatch is
    # custody corruption: contradicted, and no inference observation is emitted for it.
    receipts = [_receipt_for(_request_body(), encoded=b"other-encoded-bytes")]
    result, _ = _collect(_healthy_script(), observation=_observation(adapter_receipts=receipts))
    _assert_contradiction(result, "receipt_body_mismatch")
    assert _kinds(_abi(result)["section"], "inference") == []


@_PENDING
def test_vocabulary_matches_collector_declared_vocabulary() -> None:
    # Guard against drift: the assertion helpers accept exactly the collector's declared reason codes.
    module = _collector()
    assert set(module.MISSING_CODES) == set(MISSING_CODES)
    assert set(module.CONTRADICTION_CODES) == set(CONTRADICTION_CODES)
