"""GTMR G2 runtime evidence collector: frozen ABI v1 ``runtime`` section.

Entry point::

    collect_runtime_evidence(*, runner, observation, deadline) -> {section, artifacts, raw_artifacts}

Runner protocol (the existing transport in scripts/tests/test_gtmr_gpu_runtime_receipts.py, FrozenRunner):

    runner(argv: list[str], *, timeout: float, max_bytes: int) -> Mapping | CompletedProcess[bytes]

    A Mapping with stdout/stderr bytes, exit_code, timed_out, truncated, capture_started_at and
    capture_finished_at is also accepted (the ABI proposal shape). A timeout may be raised as
    subprocess.TimeoutExpired and a launch failure as OSError. Any other exception propagates.

deadline: an object exposing ``remaining()`` seconds, or an absolute ``time.monotonic()`` float.
clock_skew_bound_s: optional declared shared-clock bound; never observed evidence.

observation: capture instructions, never evidence.
    instance_id: str                     OCI instance to read (a mismatch is a contradiction).
    container_name: str                  docker container name (default acx-gpu-vlm).
    adapter_receipts: list[Mapping]      raw receipts from GpuRemoteDescriptionAdapter(receipt_sink=...).
    readiness: bool                      probe /v1/models without a credential when True.

Evidence rules implemented here:
  * before/after identity captures must agree on boot, container, pid+start_ticks and GPU identity;
  * mapped model/projector custody is the maps-observed path, hashed as mapped; argv mismatch is a
    contradiction, never a substitution;
  * build and offload lines count only when written after the container's StartedAt;
  * an adapter receipt becomes an inference observation only with a server completion echo carrying
    its correlation id, fresh, with 2xx status. Client correlation alone is never sufficient;
  * raw bytes are persisted exactly, except Config.Env values, which are redacted before persistence
    and whose pre-redaction digest is recorded in the capture document.

Contradictions take precedence over missing reasons. A missing or unavailable producer is incomplete.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import json
import math
import re
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1
SECTION_NAME = "runtime"
RAW_DIR = "raw/runtime"
DEFAULT_CONTAINER = "acx-gpu-vlm"
MAX_STDOUT_BYTES = 1 << 20
MAX_STDERR_BYTES = 64 << 10
MAX_RECEIPT_BYTES = 32 << 20
MAX_RECEIPTS = 8
MAX_CALLS = 32
PER_CALL_TIMEOUT_S = 15.0
ENDPOINT_PROBE_ARGV = ("curl", "-fsS", "http://127.0.0.1:8000/v1/models")

MISSING_CODES = frozenset(
    {
        "instance_not_running",
        "instance_unparseable",
        "boot_id_unparseable",
        "inspect_malformed",
        "gpu_process_for_container_absent",
        "gpu_query_unparseable",
        "gpu_query_timeout",
        "command_failed",
        "command_timeout",
        "maps_unreadable",
        "cmdline_unparsed",
        "mapped_file_absent",
        "mount_absent",
        "file_stat_unparseable",
        "digest_unparseable",
        "build_line_absent",
        "offload_line_absent",
        "startup_log_stale",
        "request_completion_absent",
        "caption_absent",
        "http_status_absent",
        "endpoint_unparseable",
        "output_truncated",
        "deadline_exhausted",
        "call_budget_exhausted",
        "dependency_absent",
        "receipt_over_budget",
        "instruction_absent",
        "clock_relationship_undeclared",
    }
)
CONTRADICTION_CODES = frozenset(
    {
        "instance_mismatch",
        "boot_changed",
        "container_changed",
        "pid_reused",
        "gpu_identity_changed",
        "gpu_process_ambiguous",
        "mapped_model_argv_mismatch",
        "mapped_projector_argv_mismatch",
        "mapped_file_replaced",
        "offload_cpu",
        "offload_ambiguous",
        "build_ambiguous",
        "completion_ambiguous",
        "request_id_collision",
        "receipt_body_mismatch",
        "receipt_malformed",
    }
)

_RFC3339 = re.compile(r"\A(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_BOOT_ID = re.compile(r"\A[0-9A-Za-z-]{8,64}\Z")
_CORRELATION = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")
_LINE_BUILD = re.compile(r"build: (\d+) \(([0-9a-f]+)\)")
_LINE_OFFLOAD = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")
_LINE_COMPLETION = re.compile(r"request_id=(\S+) status=(\d+) completion")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes | bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    return b""


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_rfc3339_ns(text: str) -> int | None:
    """Epoch nanoseconds for an RFC3339 UTC 'Z' timestamp, or None when the text is not one."""
    match = _RFC3339.match(text)
    if match is None:
        return None
    try:
        moment = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    fraction = (match.group(2) or "").ljust(9, "0")
    return calendar.timegm(moment.utctimetuple()) * 1_000_000_000 + int(fraction)


def _time_or_none(value: Any) -> str | None:
    if isinstance(value, str) and _parse_rfc3339_ns(value) is not None:
        return value
    return None


def _remaining(deadline: Any) -> float:
    if hasattr(deadline, "remaining"):
        return float(deadline.remaining())
    return float(deadline) - time.monotonic()


def _pointer(*parts: Any) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _lines(data: bytes) -> Iterator[tuple[int, int, str]]:
    """Yield (start, end, text) per line; end is exclusive and includes the newline bytes."""
    offset = 0
    for raw in data.splitlines(keepends=True):
        end = offset + len(raw)
        yield offset, end, raw.rstrip(b"\r\n").decode("utf-8", "replace")
        offset = end


def _span(start: int, end: int) -> str:
    return f"bytes:{start}-{end}"


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-") or "call"


def _json_or_none(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _dumps(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Runner transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Outcome:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    timed_out: bool
    truncated: bool
    started_at: str | None
    finished_at: str | None


def _normalize(result: Any) -> _Outcome:
    if isinstance(result, Mapping):
        return _Outcome(
            stdout=_as_bytes(result.get("stdout")),
            stderr=_as_bytes(result.get("stderr")),
            exit_code=_int_or_none(result.get("exit_code")),
            timed_out=bool(result.get("timed_out")),
            truncated=bool(result.get("truncated")),
            started_at=_time_or_none(result.get("capture_started_at")),
            finished_at=_time_or_none(result.get("capture_finished_at")),
        )
    return _Outcome(
        stdout=_as_bytes(getattr(result, "stdout", None)),
        stderr=_as_bytes(getattr(result, "stderr", None)),
        exit_code=_int_or_none(getattr(result, "returncode", None)),
        timed_out=False,
        truncated=False,
        started_at=None,
        finished_at=None,
    )


@dataclass
class _Call:
    index: int
    label: str
    argv: tuple[str, ...]
    error: str | None
    exit_code: int | None
    timed_out: bool
    truncated: bool
    timeout_s: float
    max_bytes: int
    started_at: str | None
    finished_at: str | None
    stdout: bytes
    stderr: bytes
    stdout_path: str
    stderr_path: str
    redacted: list[str] = field(default_factory=list)
    original_stdout_sha256: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class _Issue:
    code: str
    field: str
    detail: str
    artifact_refs: list[dict[str, Any]]


@dataclass
class _Spec:
    relative_path: str
    command_argv: list[str]
    exit_code: int | None
    capture_started_at: str | None
    capture_finished_at: str | None


class _Run:
    """One collector run: bounded calls, persisted bytes, dedupe-keyed issues."""

    def __init__(self, runner: Any, deadline: Any, clock_skew_bound_s: float | None) -> None:
        self.runner = runner
        self.deadline = deadline
        self.clock_skew_bound_s = clock_skew_bound_s
        self.calls: list[_Call] = []
        self.files: dict[str, bytes] = {}
        self.specs: list[_Spec] = []
        self.missing: list[_Issue] = []
        self.contradictions: list[_Issue] = []
        self._keys: set[tuple[str, str, str]] = set()

    # -- issues -----------------------------------------------------------
    def _issue(
        self, bucket: list[_Issue], kind: str, code: str, field_name: str, detail: str, refs: Sequence[dict[str, Any]]
    ) -> None:
        key = (kind, code, field_name)
        if key in self._keys:
            return
        self._keys.add(key)
        bucket.append(_Issue(code=code, field=field_name, detail=detail, artifact_refs=list(refs)))

    def missing_reason(self, code: str, field_name: str, detail: str, refs: Sequence[dict[str, Any]] = ()) -> None:
        if code not in MISSING_CODES:
            raise ValueError(f"{code!r} is outside the v1 missing-reason vocabulary")
        self._issue(self.missing, "missing", code, field_name, detail, refs)

    def contradiction(self, code: str, field_name: str, detail: str, refs: Sequence[dict[str, Any]] = ()) -> None:
        if code not in CONTRADICTION_CODES:
            raise ValueError(f"{code!r} is outside the v1 contradiction vocabulary")
        self._issue(self.contradictions, "contradiction", code, field_name, detail, refs)

    # -- persistence ------------------------------------------------------
    def persist(
        self,
        relative_path: str,
        data: bytes,
        *,
        argv: Sequence[str] = (),
        exit_code: int | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        if relative_path.startswith("/") or ".." in relative_path.split("/") or "\x00" in relative_path:
            raise ValueError(f"unsafe artifact path {relative_path!r}")
        if relative_path in self.files:
            raise ValueError(f"duplicate artifact path {relative_path!r}")
        self.files[relative_path] = data
        self.specs.append(_Spec(relative_path, list(argv), exit_code, started_at, finished_at))

    def ref(self, relative_path: str, locator: str | None = None) -> dict[str, Any]:
        return {"relative_path": relative_path, "sha256": _sha(self.files[relative_path]), "locator": locator}

    def call_refs(self, call: _Call) -> list[dict[str, Any]]:
        return [self.ref(call.stdout_path), self.ref(call.stderr_path)]

    def redact_persisted(self, relative_path: str, data: bytes) -> None:
        self.files[relative_path] = data

    # -- calls ------------------------------------------------------------
    def call(self, label: str, argv: Sequence[str], *, max_bytes: int = MAX_STDOUT_BYTES) -> _Call | None:
        remaining = _remaining(self.deadline)
        if not math.isfinite(remaining) or remaining <= 0:
            self.missing_reason("deadline_exhausted", label, f"no time left before capture {label}")
            return None
        if len(self.calls) >= MAX_CALLS:
            self.missing_reason("call_budget_exhausted", label, f"collector call bound {MAX_CALLS} reached")
            return None
        timeout = min(PER_CALL_TIMEOUT_S, remaining)
        index = len(self.calls)
        argv_tuple = tuple(str(part) for part in argv)
        error: str | None = None
        outcome = _Outcome(b"", b"", None, False, False, None, None)
        try:
            result = self.runner(
                list(argv_tuple),
                timeout=timeout,
                max_bytes=max_bytes,
            )
        except subprocess.TimeoutExpired as exc:
            error = "timeout"
            outcome = _Outcome(_as_bytes(exc.stdout), _as_bytes(exc.stderr), None, True, False, None, None)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            error = "unavailable"
            outcome = _Outcome(
                b"", f"{type(exc).__name__}: {exc}".encode("utf-8", "replace"), None, False, False, None, None
            )
        else:
            outcome = _normalize(result)
        if error is None:
            if outcome.timed_out:
                error = "timeout"
            elif outcome.truncated or len(outcome.stdout) > max_bytes or len(outcome.stderr) > MAX_STDERR_BYTES:
                error = "truncated"
            elif outcome.exit_code != 0:
                error = "failed"
        base = f"{RAW_DIR}/calls/{index:02d}-{_slug(label)}"
        stdout_path, stderr_path = f"{base}.stdout", f"{base}.stderr"
        stdout_kept = outcome.stdout[:max_bytes]
        stderr_kept = outcome.stderr[:MAX_STDERR_BYTES]
        call = _Call(
            index=index,
            label=label,
            argv=argv_tuple,
            error=error,
            exit_code=outcome.exit_code,
            timed_out=outcome.timed_out,
            truncated=error == "truncated",
            timeout_s=timeout,
            max_bytes=max_bytes,
            started_at=outcome.started_at,
            finished_at=outcome.finished_at,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        self.calls.append(call)
        self.persist(
            stdout_path,
            stdout_kept,
            argv=argv_tuple,
            exit_code=outcome.exit_code,
            started_at=outcome.started_at,
            finished_at=outcome.finished_at,
        )
        self.persist(
            stderr_path,
            stderr_kept,
            argv=argv_tuple,
            exit_code=outcome.exit_code,
            started_at=outcome.started_at,
            finished_at=outcome.finished_at,
        )
        return call

    def call_issue(self, call: _Call, field_name: str, *, failed_code: str = "command_failed") -> None:
        if call.error == "timeout":
            code = "gpu_query_timeout" if field_name == "gpu_apps" else "command_timeout"
        elif call.error == "truncated":
            code = "output_truncated"
        else:
            code = failed_code
        detail = f"{call.label} error={call.error} exit_code={call.exit_code}"
        self.missing_reason(code, field_name, detail, self.call_refs(call))

    # -- finalize ---------------------------------------------------------
    def capture_document(self) -> bytes:
        calls = []
        for call in self.calls:
            calls.append(
                {
                    "index": call.index,
                    "label": call.label,
                    "argv": list(call.argv),
                    "error": call.error,
                    "exit_code": call.exit_code,
                    "timed_out": call.timed_out,
                    "truncated": call.truncated,
                    "timeout_s": call.timeout_s,
                    "max_bytes": call.max_bytes,
                    "redaction": {
                        "fields": list(call.redacted),
                        "original_stdout_sha256": call.original_stdout_sha256,
                    },
                    "capture_started_at": call.started_at,
                    "capture_finished_at": call.finished_at,
                    "stdout": {
                        "relative_path": call.stdout_path,
                        "bytes_received": len(call.stdout),
                        "bytes_persisted": len(self.files[call.stdout_path]),
                        "sha256": _sha(self.files[call.stdout_path]),
                    },
                    "stderr": {
                        "relative_path": call.stderr_path,
                        "bytes_received": len(call.stderr),
                        "bytes_persisted": len(self.files[call.stderr_path]),
                        "sha256": _sha(self.files[call.stderr_path]),
                    },
                }
            )
        doc = {"schema_version": SCHEMA_VERSION, "calls": calls,
               "clock_relationship": {"kind": "undeclared" if self.clock_skew_bound_s is None else "declared_shared_clock_bound",
                                      "bound_s": self.clock_skew_bound_s, "observed": False}}
        return _dumps(doc)


# ---------------------------------------------------------------------------
# Probe records
# ---------------------------------------------------------------------------


@dataclass
class _Identity:
    phase: str
    instance_id: str | None = None
    instance_ref: dict[str, Any] | None = None
    boot_id: str | None = None
    boot_ref: dict[str, Any] | None = None
    container_id: str | None = None
    container_image_id: str | None = None
    pid: int | None = None
    started_at: str | None = None
    mounts: list[Mapping[str, Any]] | None = None
    inspect_ref: dict[str, Any] | None = None
    start_ticks: int | None = None
    stat_ref: dict[str, Any] | None = None
    gpu_uuid: str | None = None
    gpu_ref: dict[str, Any] | None = None

    @property
    def observable(self) -> bool:
        return self.inspect_ref is not None

    @property
    def complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.instance_id,
                self.boot_id,
                self.container_id,
                self.container_image_id,
                self.pid,
                self.start_ticks,
                self.gpu_uuid,
            )
        )


@dataclass(frozen=True)
class _MapEntry:
    path: str
    inode: int
    span: tuple[int, int]


@dataclass
class _Custody:
    model: _MapEntry
    projector: _MapEntry
    model_sha: str | None
    projector_sha: str | None
    model_ref: dict[str, Any]
    projector_ref: dict[str, Any]
    maps_path: str
    cmdline_path: str


@dataclass(frozen=True)
class _Completion:
    request_id: str
    status: int
    timestamp: str
    timestamp_ns: int
    path: str
    span: tuple[int, int]


@dataclass
class _LogFacts:
    logs_path: str | None = None
    build: str | None = None
    build_ref: dict[str, Any] | None = None
    offload: tuple[int, int] | None = None
    offload_ref: dict[str, Any] | None = None
    completions: list[_Completion] = field(default_factory=list)
    ok: bool = False


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _capture_identity(run: _Run, phase: str, instance_id: str | None, container: str) -> _Identity:
    ident = _Identity(phase=phase)
    if instance_id is not None:
        inst = run.call(
            f"{phase}-instance", ("oci", "compute", "instance", "get", "--instance-id", instance_id, "--output", "json")
        )
        if inst is not None:
            if inst.ok:
                doc = _json_or_none(inst.stdout)
                data = doc.get("data") if isinstance(doc, dict) else None
                observed_id = data.get("id") if isinstance(data, dict) else None
                state = data.get("lifecycle-state") if isinstance(data, dict) else None
                if not isinstance(observed_id, str) or not isinstance(state, str):
                    run.missing_reason(
                        "instance_unparseable",
                        "instance",
                        f"{phase} instance payload lacks data.id/lifecycle-state",
                        run.call_refs(inst),
                    )
                else:
                    ident.instance_id = observed_id
                    ident.instance_ref = run.ref(inst.stdout_path, _pointer("data", "id"))
                    if observed_id != instance_id:
                        run.contradiction(
                            "instance_mismatch",
                            "instance_id",
                            f"{phase} observed {observed_id} for instruction {instance_id}",
                            run.call_refs(inst),
                        )
                    if state != "RUNNING":
                        run.missing_reason(
                            "instance_not_running", "lifecycle-state", f"{phase} state={state}", run.call_refs(inst)
                        )
            else:
                run.call_issue(inst, "instance")
    else:
        run.missing_reason("instruction_absent", "instance_id", "observation supplies no instance instruction")

    boot = run.call(f"{phase}-boot", ("cat", "/proc/sys/kernel/random/boot_id"))
    if boot is not None:
        if boot.ok:
            text = boot.stdout.decode("utf-8", "replace").strip()
            if _BOOT_ID.match(text):
                ident.boot_id = text
                ident.boot_ref = run.ref(boot.stdout_path, _span(0, len(boot.stdout)))
            else:
                run.missing_reason(
                    "boot_id_unparseable",
                    "boot_id",
                    f"{phase} boot_id payload is not an identifier",
                    run.call_refs(boot),
                )
        else:
            run.call_issue(boot, "boot_id")

    insp = run.call(f"{phase}-inspect", ("docker", "inspect", container))
    if insp is not None:
        _redact_inspect(run, insp)
        if insp.ok:
            entry = _inspect_entry(insp.stdout)
            if entry is None:
                run.missing_reason(
                    "inspect_malformed",
                    "inspect",
                    f"{phase} docker inspect lacks one container object",
                    run.call_refs(insp),
                )
            else:
                ident.container_id = _text_or_none(entry.get("Id"))
                ident.container_image_id = _text_or_none(entry.get("Image"))
                state = entry.get("State") if isinstance(entry.get("State"), dict) else {}
                pid = _int_or_none(state.get("Pid"))
                started = _time_or_none(state.get("StartedAt"))
                mounts = entry.get("Mounts") if isinstance(entry.get("Mounts"), list) else None
                if ident.container_id is None or pid is None or pid < 1 or started is None or mounts is None:
                    run.missing_reason(
                        "inspect_malformed",
                        "inspect",
                        f"{phase} inspect lacks Id/State.Pid/State.StartedAt/Mounts",
                        run.call_refs(insp),
                    )
                else:
                    ident.pid = pid
                    ident.started_at = started
                    ident.mounts = [m for m in mounts if isinstance(m, dict)]
                    ident.inspect_ref = run.ref(insp.stdout_path, _pointer(0, "Id"))
        else:
            run.call_issue(insp, "inspect")

    if ident.pid is not None:
        gpu = run.call(
            f"{phase}-gpu-apps",
            (
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory,gpu_uuid",
                "--format=csv,noheader,nounits",
            ),
        )
        if gpu is not None:
            if gpu.ok:
                _apply_gpu(run, ident, gpu)
            else:
                run.call_issue(gpu, "gpu_apps")
        stat = run.call(f"{phase}-proc-stat", ("cat", f"/proc/{ident.pid}/stat"))
        if stat is not None:
            if stat.ok:
                ticks = _start_ticks(stat.stdout, ident.pid)
                if ticks is None:
                    run.missing_reason(
                        "command_failed", "start_ticks", f"{phase} /proc stat unparseable", run.call_refs(stat)
                    )
                else:
                    ident.start_ticks = ticks
                    ident.stat_ref = run.ref(stat.stdout_path, _span(0, len(stat.stdout)))
            else:
                run.call_issue(stat, "start_ticks")
    else:
        run.missing_reason(
            "dependency_absent", f"{phase}.gpu_uuid", "no container pid; GPU and process probes not attempted"
        )
    return ident


def _inspect_entry(stdout: bytes) -> dict[str, Any] | None:
    doc = _json_or_none(stdout)
    if isinstance(doc, list) and len(doc) == 1 and isinstance(doc[0], dict):
        return doc[0]
    return None


def _redact_inspect(run: _Run, call: _Call) -> None:
    """Redact every inspect object, including failed or ambiguous captures."""
    doc = _json_or_none(call.stdout)
    fields = []
    if isinstance(doc, list):
        for entry in doc:
            for name in ("Config", "ContainerConfig"):
                config = entry.get(name) if isinstance(entry, dict) else None
                if isinstance(config, dict) and "Env" in config:
                    env = config["Env"]
                    config["Env"] = [
                        f"{item.split('=', 1)[0]}=<redacted>" if isinstance(item, str) and "=" in item else "<redacted>"
                        for item in env
                    ] if isinstance(env, list) else ["<redacted>"]
                    if f"{name}.Env" not in fields:
                        fields.append(f"{name}.Env")
        if not fields:
            return
        persisted = _dumps(doc)
        if len(persisted) > call.max_bytes:
            persisted = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                   allow_nan=False).encode("utf-8")
        call.redacted = fields
    else:
        persisted = b""
        call.redacted = ["malformed inspect withheld: Env may contain secrets"]
    if len(persisted) > call.max_bytes:
        persisted = b""
        call.truncated = True
        call.error = "truncated"
    call.original_stdout_sha256 = _sha(call.stdout[: call.max_bytes])
    run.redact_persisted(call.stdout_path, persisted)


def _apply_gpu(run: _Run, ident: _Identity, gpu: _Call) -> None:
    matches: list[tuple[str, tuple[int, int]]] = []
    malformed = 0
    for start, end, text in _lines(gpu.stdout):
        if not text.strip():
            continue
        parts = [part.strip() for part in text.split(",")]
        if len(parts) < 4 or not parts[0].isdigit():
            malformed += 1
            continue
        if int(parts[0]) == ident.pid:
            matches.append((parts[-1], (start, end)))
    if not matches:
        if malformed:
            run.missing_reason(
                "gpu_query_unparseable", "gpu_apps", f"{malformed} unparseable compute-app rows", run.call_refs(gpu)
            )
        else:
            run.missing_reason(
                "gpu_process_for_container_absent",
                "gpu_apps",
                f"no compute app with pid {ident.pid}",
                run.call_refs(gpu),
            )
        return
    uuids = {uuid for uuid, _ in matches}
    if len(uuids) > 1:
        run.contradiction(
            "gpu_process_ambiguous", "gpu_apps", f"pid {ident.pid} maps to {len(uuids)} GPU uuids", run.call_refs(gpu)
        )
        return
    ident.gpu_uuid = matches[0][0]
    ident.gpu_ref = run.ref(gpu.stdout_path, _span(*matches[0][1]))


def _start_ticks(stdout: bytes, pid: int) -> int | None:
    text = stdout.decode("utf-8", "replace")
    if text.split(" ", 1)[0] != str(pid):
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 2 :].split()
    if len(fields) < 20 or not fields[19].isdigit():
        return None
    return int(fields[19])


def _compare_identity(run: _Run, before: _Identity, after: _Identity) -> tuple[bool, bool]:
    """Return (contradicted, after_complete). Contradictions block dependent observations."""
    contradicted = False
    if before.boot_id and after.boot_id and before.boot_id != after.boot_id:
        run.contradiction(
            "boot_changed",
            "boot_id",
            f"{before.boot_id} -> {after.boot_id}",
            [r for r in (before.boot_ref, after.boot_ref) if r],
        )
        contradicted = True
    if before.container_id and after.container_id and before.container_id != after.container_id:
        run.contradiction(
            "container_changed",
            "container_id",
            "container id differs between captures",
            [r for r in (before.inspect_ref, after.inspect_ref) if r],
        )
        contradicted = True
    if (
        before.pid is not None
        and after.pid is not None
        and (before.pid, before.start_ticks) != (after.pid, after.start_ticks)
    ):
        run.contradiction(
            "pid_reused",
            "pid",
            f"pid/start_ticks {before.pid}/{before.start_ticks} -> {after.pid}/{after.start_ticks}",
            [r for r in (before.stat_ref, after.stat_ref) if r],
        )
        contradicted = True
    if before.gpu_uuid and after.gpu_uuid and before.gpu_uuid != after.gpu_uuid:
        run.contradiction(
            "gpu_identity_changed",
            "gpu_uuid",
            "GPU identity differs between captures",
            [r for r in (before.gpu_ref, after.gpu_ref) if r],
        )
        contradicted = True
    if before.instance_id and after.instance_id and before.instance_id != after.instance_id:
        run.contradiction(
            "instance_mismatch",
            "instance_id",
            "instance differs between captures",
            [r for r in (before.instance_ref, after.instance_ref) if r],
        )
        contradicted = True
    return contradicted, after.complete


def _host_path(container_path: str, mounts: Sequence[Mapping[str, Any]]) -> str | None:
    best: tuple[str, str] | None = None
    for mount in mounts:
        destination, source = mount.get("Destination"), mount.get("Source")
        if not isinstance(destination, str) or not isinstance(source, str):
            continue
        dest = destination.rstrip("/") or "/"
        covers = container_path == dest or container_path.startswith(dest.rstrip("/") + "/")
        if covers and (best is None or len(dest) > len(best[0])):
            best = (dest, source.rstrip("/"))
    if best is None:
        return None
    dest, source = best
    return source + container_path[len(dest.rstrip("/")) :]


def _cmdline_value(stdout: bytes, flag: str) -> str | None:
    parts = [part.decode("utf-8", "replace") for part in stdout.split(b"\x00") if part]
    if flag in parts:
        index = parts.index(flag)
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


def _maps_entries(call: _Call) -> list[_MapEntry]:
    entries: dict[str, _MapEntry] = {}
    for start, end, text in _lines(call.stdout):
        fields = text.split(maxsplit=5)
        if len(fields) != 6 or not fields[4].isdigit() or not fields[5].startswith("/"):
            continue
        path = fields[5].strip()
        entries.setdefault(path, _MapEntry(path=path, inode=int(fields[4]), span=(start, end)))
    return list(entries.values())


def _is_projector(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "mmproj" in name


def _capture_custody(run: _Run, before: _Identity) -> _Custody | None:
    if before.pid is None or before.mounts is None:
        run.missing_reason(
            "dependency_absent", "mapped_model", "container identity unavailable; mapped-file custody not attempted"
        )
        return None
    cmdline = run.call("cmdline", ("cat", f"/proc/{before.pid}/cmdline"))
    if cmdline is None:
        return None
    if not cmdline.ok:
        run.call_issue(cmdline, "cmdline")
        return None
    model_arg = _cmdline_value(cmdline.stdout, "--model")
    projector_arg = _cmdline_value(cmdline.stdout, "--mmproj")
    if model_arg is None or projector_arg is None:
        run.missing_reason(
            "cmdline_unparsed", "cmdline", "server argv lacks --model or --mmproj", run.call_refs(cmdline)
        )
        return None
    maps = run.call("maps", ("cat", f"/proc/{before.pid}/maps"))
    if maps is None:
        return None
    if not maps.ok:
        run.call_issue(maps, "maps", failed_code="maps_unreadable")
        return None
    entries = [entry for entry in _maps_entries(maps) if entry.path.endswith(".gguf")]
    model_entries = [entry for entry in entries if not _is_projector(entry.path)]
    projector_entries = [entry for entry in entries if _is_projector(entry.path)]
    if len(model_entries) != 1 or len(projector_entries) != 1:
        run.missing_reason(
            "mapped_file_absent",
            "maps",
            f"expected one mapped model and one mapped projector; found {len(model_entries)} and {len(projector_entries)}",
            run.call_refs(maps),
        )
        return None
    model_entry, projector_entry = model_entries[0], projector_entries[0]
    derived_model = _host_path(model_arg, before.mounts)
    derived_projector = _host_path(projector_arg, before.mounts)
    if derived_model is None or derived_projector is None:
        run.missing_reason(
            "mount_absent",
            "mounts",
            "no bind mount covers the server model or projector argv path",
            run.call_refs(maps),
        )
        return None
    if model_entry.path != derived_model:
        run.contradiction(
            "mapped_model_argv_mismatch",
            "model_path",
            f"mapped {model_entry.path} but argv implies {derived_model}",
            [run.ref(maps.stdout_path, _span(*model_entry.span))],
        )
    if projector_entry.path != derived_projector:
        run.contradiction(
            "mapped_projector_argv_mismatch",
            "projector_path",
            f"mapped {projector_entry.path} but argv implies {derived_projector}",
            [run.ref(maps.stdout_path, _span(*projector_entry.span))],
        )

    digests: dict[str, str | None] = {}
    refs: dict[str, dict[str, Any]] = {}
    for role, entry in (("model", model_entry), ("projector", projector_entry)):
        stat = run.call(f"{role}-stat", ("stat", "-c", "%i", entry.path))
        replaced = False
        if stat is not None:
            if stat.ok:
                token = stat.stdout.strip()
                inode = int(token) if token.isdigit() else None
                if inode is None:
                    run.missing_reason(
                        "file_stat_unparseable", f"{role}_stat", "stat output is not an inode", run.call_refs(stat)
                    )
                elif inode != entry.inode:
                    replaced = True
                    run.contradiction(
                        "mapped_file_replaced",
                        f"{role}_path",
                        f"mapped inode {entry.inode} but path now resolves to {inode}",
                        [run.ref(maps.stdout_path, _span(*entry.span)), run.ref(stat.stdout_path)],
                    )
            else:
                run.call_issue(stat, f"{role}_stat")
        digests[role] = None
        if replaced:
            continue
        sha_call = run.call(f"{role}-sha256", ("sha256sum", entry.path))
        if sha_call is None:
            continue
        if not sha_call.ok:
            run.call_issue(sha_call, f"{role}_sha256")
            continue
        token = sha_call.stdout.split()[0].decode("ascii", "replace") if sha_call.stdout.split() else ""
        if _HEX64.match(token):
            digests[role] = token
            refs[role] = run.ref(sha_call.stdout_path, _span(0, len(sha_call.stdout)))
        else:
            run.missing_reason(
                "digest_unparseable",
                f"{role}_sha256",
                "sha256sum output is not a 64-hex digest",
                run.call_refs(sha_call),
            )
    return _Custody(
        model=model_entry,
        projector=projector_entry,
        model_sha=digests.get("model"),
        projector_sha=digests.get("projector"),
        model_ref=refs.get("model", run.ref(maps.stdout_path, _span(*model_entry.span))),
        projector_ref=refs.get("projector", run.ref(maps.stdout_path, _span(*projector_entry.span))),
        maps_path=maps.stdout_path,
        cmdline_path=cmdline.stdout_path,
    )


def _capture_logs(run: _Run, container: str, started_at: str | None) -> _LogFacts | None:
    started_ns = _parse_rfc3339_ns(started_at) if started_at else None
    if started_ns is None:
        run.missing_reason(
            "dependency_absent", "logs", "container StartedAt unknown; log freshness cannot be established"
        )
        return None
    logs = run.call("logs", ("docker", "logs", "--timestamps", container))
    if logs is None:
        return None
    if not logs.ok:
        run.call_issue(logs, "logs")
        return None
    facts = _LogFacts(logs_path=logs.stdout_path, ok=True)
    builds: list[tuple[str, str, tuple[int, int], bool]] = []
    offloads: list[tuple[tuple[int, int], str, tuple[int, int], bool]] = []
    for path, data in ((logs.stdout_path, logs.stdout), (logs.stderr_path, logs.stderr)):
        for start, end, text in _lines(data):
            stamp, _, message = text.partition(" ")
            stamp_ns = _parse_rfc3339_ns(stamp)
            if stamp_ns is None:
                continue
            fresh = stamp_ns >= started_ns
            span = (start, end)
            build = _LINE_BUILD.search(message)
            if build:
                builds.append((f"{build.group(1)} ({build.group(2)})", path, span, fresh))
            offload = _LINE_OFFLOAD.search(message)
            if offload:
                offloads.append(((int(offload.group(1)), int(offload.group(2))), path, span, fresh))
            completion = _LINE_COMPLETION.search(message)
            if completion:
                facts.completions.append(
                    _Completion(completion.group(1), int(completion.group(2)), stamp, stamp_ns, path, span)
                )
    fresh_builds = [item for item in builds if item[3]]
    if not fresh_builds:
        if builds:
            run.missing_reason(
                "startup_log_stale", "build", "build line predates the container start", run.call_refs(logs)
            )
        else:
            run.missing_reason("build_line_absent", "build", "no build line in container logs", run.call_refs(logs))
    else:
        values = {value for value, _, _, _ in fresh_builds}
        if len(values) > 1:
            run.contradiction(
                "build_ambiguous", "build", f"{len(values)} distinct build identities after start", run.call_refs(logs)
            )
        else:
            value, path, span, _ = fresh_builds[-1]
            facts.build = value
            facts.build_ref = run.ref(path, _span(*span))
    fresh_offloads = [item for item in offloads if item[3]]
    if not fresh_offloads:
        if offloads:
            run.missing_reason(
                "startup_log_stale", "offload", "offload line predates the container start", run.call_refs(logs)
            )
        else:
            run.missing_reason(
                "offload_line_absent", "offload", "no layer offload line in container logs", run.call_refs(logs)
            )
    else:
        values = {value for value, _, _, _ in fresh_offloads}
        if len(values) > 1:
            run.contradiction(
                "offload_ambiguous",
                "offload",
                f"{len(values)} distinct offload results after start",
                run.call_refs(logs),
            )
        else:
            (layers, total), path, span, _ = fresh_offloads[-1]
            facts.offload = (layers, total)
            facts.offload_ref = run.ref(path, _span(*span))
    return facts


def _capture_readiness(run: _Run, instance_id: str | None) -> dict[str, Any] | None:
    probe = run.call("readiness", ENDPOINT_PROBE_ARGV)
    if probe is None:
        return None
    if not probe.ok:
        run.call_issue(probe, "readiness")
        return None
    doc = _json_or_none(probe.stdout)
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list):
        run.missing_reason(
            "endpoint_unparseable", "readiness", "/v1/models payload lacks a data list", run.call_refs(probe)
        )
        return None
    run.missing_reason(
        "http_status_absent",
        "http_status",
        "curl -fsS does not expose the HTTP status code",
        [run.ref(probe.stdout_path)],
    )
    return {
        "instance_id": instance_id,
        "authenticated": False,
        "http_status": None,
        "ready": len(data) > 0,
        "ref": run.ref(probe.stdout_path, _pointer("data")),
        "path": probe.stdout_path,
        "finished_at": probe.finished_at,
    }


# ---------------------------------------------------------------------------
# Adapter receipts (raw custody + lineage recomputed from bytes)
# ---------------------------------------------------------------------------


@dataclass
class _Receipt:
    index: int
    kind: str
    correlation_id: str
    status_code: int
    started_at: str
    finished_at: str
    request_body: bytes
    source_image: bytes
    encoded_image: bytes
    context_canonical: bytes
    caption: bytes | None
    response_body: bytes
    media_type: str
    model: str
    system_prompt: str
    user_text: str
    body_image: bytes


def _parse_request_body(body: bytes) -> tuple[str, str, str, bytes] | None:
    try:
        doc = json.loads(body)
        messages = doc["messages"]
        system = [m for m in messages if m.get("role") == "system"]
        user = [m for m in messages if m.get("role") == "user"]
        if len(system) != 1 or len(user) != 1:
            return None
        model, system_text, parts = doc["model"], system[0]["content"], user[0]["content"]
        if not isinstance(model, str) or not isinstance(system_text, str) or not isinstance(parts, list):
            return None
        urls = [part["image_url"]["url"] for part in parts if part.get("type") == "image_url"]
        texts = [part["text"] for part in parts if part.get("type") == "text"]
        if len(urls) != 1 or len(texts) != 1 or not isinstance(texts[0], str):
            return None
        header, separator, payload = urls[0].partition(",")
        if not separator or not header.startswith("data:") or not header.endswith(";base64"):
            return None
        return model, system_text, texts[0], base64.b64decode(payload, validate=True)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None


def _caption_from_response(response_body: bytes) -> bytes | None:
    """Pure duplicate of the adapter caption parser; grounding uses request input."""
    try:
        body = json.loads(response_body)
        message = body["choices"][0]["message"]
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    continue
                if not isinstance(part.get("text"), str):
                    return None
                parts.append(part["text"])
            text = " ".join(parts).strip()
        elif isinstance(content, str):
            text = content.strip()
        else:
            return None
        return text.encode("utf-8") if text else None
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError):
        return None


def _parse_receipt(run: _Run, index: int, raw: Any) -> _Receipt | None:
    site = f"adapter_receipts[{index}]"
    if not isinstance(raw, Mapping):
        run.contradiction("receipt_malformed", site, "receipt is not a mapping")
        return None
    byte_fields = ("request_body", "source_image", "encoded_image", "context_canonical", "response_body")
    if (
        raw.get("request_kind") not in ("caption", "grounding")
        or not isinstance(raw.get("correlation_id"), str)
        or not _CORRELATION.match(raw["correlation_id"])
    ):
        run.contradiction("receipt_malformed", site, "request_kind or correlation_id is malformed")
        return None
    if any(not isinstance(raw.get(name), bytes | bytearray) for name in byte_fields):
        run.contradiction("receipt_malformed", site, "a raw byte field is not bytes")
        return None
    caption = raw.get("caption")
    if caption is not None and not isinstance(caption, bytes | bytearray):
        run.contradiction("receipt_malformed", site, "caption is neither bytes nor null")
        return None
    status = _int_or_none(raw.get("status_code"))
    started, finished = _time_or_none(raw.get("started_at")), _time_or_none(raw.get("finished_at"))
    if status is None or started is None or finished is None:
        run.contradiction("receipt_malformed", site, "status_code or RFC3339 Z timings are missing")
        return None
    if _parse_rfc3339_ns(started) > _parse_rfc3339_ns(finished):
        run.contradiction("receipt_malformed", site, "receipt started_at exceeds finished_at")
        return None
    if any(len(raw[name]) > MAX_RECEIPT_BYTES for name in byte_fields):
        run.missing_reason("receipt_over_budget", site, "a receipt byte field exceeds the per-artifact budget")
        return None
    parsed = _parse_request_body(bytes(raw["request_body"]))
    if parsed is None:
        run.contradiction(
            "receipt_malformed",
            site,
            "request body is not a single system/user chat payload with one image and one text part",
        )
        return None
    model, system_text, user_text, body_image = parsed
    return _Receipt(
        index=index,
        kind=raw["request_kind"],
        correlation_id=raw["correlation_id"],
        status_code=status,
        started_at=started,
        finished_at=finished,
        request_body=bytes(raw["request_body"]),
        source_image=bytes(raw["source_image"]),
        encoded_image=bytes(raw["encoded_image"]),
        context_canonical=bytes(raw["context_canonical"]),
        caption=None if caption is None else bytes(caption),
        response_body=bytes(raw["response_body"]),
        media_type=str(raw.get("media_type", "")),
        model=model,
        system_prompt=system_text,
        user_text=user_text,
        body_image=body_image,
    )


def _persist_receipt(run: _Run, receipt: _Receipt) -> dict[str, dict[str, Any]]:
    base = f"{RAW_DIR}/receipts/{receipt.index:02d}-{receipt.kind}"
    parts = {
        "request_body": receipt.request_body,
        "source_image": receipt.source_image,
        "encoded_image": receipt.encoded_image,
        "context_canonical": receipt.context_canonical,
        "response_body": receipt.response_body,
    }
    if receipt.caption is not None:
        parts["caption"] = receipt.caption
    refs: dict[str, dict[str, Any]] = {}
    meta_parts: dict[str, Any] = {}
    for name, data in parts.items():
        relative = f"{base}-{name}.bin"
        run.persist(relative, data, started_at=receipt.started_at, finished_at=receipt.finished_at)
        refs[name] = run.ref(relative)
        meta_parts[name] = {"bytes": len(data), "sha256": _sha(data)}
    meta = {
        "request_kind": receipt.kind,
        "correlation_id": receipt.correlation_id,
        "media_type": receipt.media_type,
        "status_code": receipt.status_code,
        "started_at": receipt.started_at,
        "finished_at": receipt.finished_at,
        "parts": meta_parts,
    }
    meta_path = f"{base}-meta.json"
    run.persist(meta_path, _dumps(meta), started_at=receipt.started_at, finished_at=receipt.finished_at)
    refs["meta"] = run.ref(meta_path)
    return refs


# ---------------------------------------------------------------------------
# Observation builders
# ---------------------------------------------------------------------------


def _identity_observation(run: _Run, ident: _Identity) -> dict[str, Any]:
    primary = ident.inspect_ref or {}
    source_refs = [ref for ref in (ident.instance_ref, ident.boot_ref, ident.gpu_ref, ident.stat_ref) if ref]
    return {
        "observation_id": f"runtime.identity.{ident.phase}",
        "kind": "runtime_identity",
        "observed_at": _finished_time(run, primary.get("relative_path")),
        "artifact_relative_path": primary["relative_path"],
        "artifact_sha256": primary["sha256"],
        "source_artifacts": source_refs,
        "data": {
            "instance_id": ident.instance_id,
            "boot_id": ident.boot_id,
            "container_id": ident.container_id,
            "container_image_id": ident.container_image_id,
            "pid": ident.pid,
            "start_ticks": ident.start_ticks,
            "gpu_uuid": ident.gpu_uuid,
            "phase": ident.phase,
        },
    }


def _finished_time(run: _Run, relative_path: str | None) -> str | None:
    for spec in run.specs:
        if spec.relative_path == relative_path:
            return spec.capture_finished_at
    return None


def _mapped_observation(run: _Run, before: _Identity, custody: _Custody, logs: _LogFacts | None) -> dict[str, Any]:
    maps_ref = run.ref(custody.maps_path, _span(*custody.model.span))
    layers = logs.offload[0] if logs and logs.offload else None
    source_refs = [
        custody.model_ref,
        custody.projector_ref,
        run.ref(custody.cmdline_path, _span(0, len(run.files[custody.cmdline_path]))),
    ]
    if before.inspect_ref:
        source_refs.append(before.inspect_ref)
    if logs and logs.build_ref:
        source_refs.append(logs.build_ref)
    if logs and logs.offload_ref:
        source_refs.append(logs.offload_ref)
    return {
        "observation_id": "runtime.mapped_model",
        "kind": "mapped_model",
        "observed_at": _finished_time(run, custody.maps_path),
        "artifact_relative_path": maps_ref["relative_path"],
        "artifact_sha256": maps_ref["sha256"],
        "source_artifacts": source_refs,
        "data": {
            "instance_id": before.instance_id,
            "boot_id": before.boot_id,
            "container_id": before.container_id,
            "pid": before.pid,
            "start_ticks": before.start_ticks,
            "model_path": custody.model.path,
            "model_sha256": custody.model_sha,
            "projector_path": custody.projector.path,
            "projector_sha256": custody.projector_sha,
            "build_identity": logs.build if logs else None,
            "offloaded_layers": layers,
            "gpu_execution": None if layers is None else layers > 0,
        },
    }


def _inference_observation(
    run: _Run,
    receipt: _Receipt,
    completion: _Completion,
    before: _Identity,
    refs: dict[str, dict[str, Any]],
    logs: _LogFacts,
) -> dict[str, Any]:
    prompt = json.dumps(
        {"system_prompt": receipt.system_prompt, "user_text": receipt.user_text},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    primary = run.ref(completion.path, _span(*completion.span))
    source_refs = [
        refs[name]
        for name in (
            "request_body",
            "source_image",
            "encoded_image",
            "context_canonical",
            "caption",
            "response_body",
            "meta",
        )
        if name in refs
    ]
    for ref in (before.instance_ref, before.boot_ref, before.gpu_ref, before.stat_ref, before.inspect_ref):
        if ref:
            source_refs.append(ref)
    return {
        "observation_id": f"runtime.inference.{receipt.index:02d}",
        "kind": "inference",
        "observed_at": _finished_time(run, completion.path),
        "artifact_relative_path": primary["relative_path"],
        "artifact_sha256": primary["sha256"],
        "source_artifacts": source_refs,
        "data": {
            "inference_request_id": receipt.correlation_id,
            "request_kind": receipt.kind,
            "request_body_sha256": _sha(receipt.request_body),
            "source_image_sha256": _sha(receipt.source_image),
            "encoded_image_sha256": _sha(receipt.encoded_image),
            "context_hash": _sha(receipt.context_canonical),
            "prompt_sha256": _sha(prompt),
            "requested_model": receipt.model,
            "caption_sha256": _sha(receipt.caption) if receipt.caption is not None else None,
            "instance_id": before.instance_id,
            "boot_id": before.boot_id,
            "container_id": before.container_id,
            "pid": before.pid,
            "start_ticks": before.start_ticks,
            "gpu_uuid": before.gpu_uuid,
            "completion_started_at": receipt.started_at,
            "completion_finished_at": completion.timestamp,
        },
    }


def _bind_receipts(
    run: _Run,
    raw_receipts: Sequence[Any],
    before: _Identity,
    logs: _LogFacts | None,
    inference_allowed: bool,
) -> list[dict[str, Any]]:
    if not raw_receipts:
        run.missing_reason(
            "request_completion_absent",
            "adapter_receipts",
            "no adapter receipts supplied; no request lineage can be bound",
        )
        return []
    if len(raw_receipts) > MAX_RECEIPTS:
        run.missing_reason(
            "receipt_over_budget", "adapter_receipts", f"{len(raw_receipts)} receipts exceed the bound {MAX_RECEIPTS}"
        )
        raw_receipts = raw_receipts[:MAX_RECEIPTS]
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = 0
    for index, raw in enumerate(raw_receipts):
        receipt = _parse_receipt(run, index, raw)
        if receipt is None:
            continue
        if receipt.correlation_id in seen:
            run.contradiction(
                "request_id_collision", f"adapter_receipts[{index}]", "two receipts share a correlation id"
            )
            continue
        seen.add(receipt.correlation_id)
        refs = _persist_receipt(run, receipt)
        if not 200 <= receipt.status_code < 300:
            continue
        candidates += 1
        site = f"adapter_receipts[{index}]"
        if receipt.body_image != receipt.encoded_image:
            run.contradiction(
                "receipt_body_mismatch",
                site,
                "encoded image bytes differ from the image carried by the request body",
                [refs["request_body"], refs["encoded_image"]],
            )
            continue
        if receipt.caption is None:
            run.missing_reason(
                "caption_absent", site, "successful receipt carries no caption bytes", [refs["response_body"]]
            )
            continue
        if receipt.kind == "caption":
            derived = _caption_from_response(receipt.response_body)
            if derived is None or derived != receipt.caption:
                run.contradiction(
                    "receipt_malformed" if derived is None else "receipt_body_mismatch",
                    site, "caption does not derive from retained response bytes",
                    [refs["response_body"], refs["caption"]],
                )
                continue
        if logs is None or not logs.ok:
            run.missing_reason(
                "request_completion_absent", site, "container logs unavailable; completion echo not observable"
            )
            continue
        started_ns = _parse_rfc3339_ns(before.started_at) if before.started_at else None
        matches = [c for c in logs.completions if c.request_id == receipt.correlation_id]
        fresh = [c for c in matches if started_ns is not None and c.timestamp_ns >= started_ns]
        if len(fresh) > 1:
            run.contradiction("completion_ambiguous", site, f"{len(fresh)} completion lines echo one correlation id")
            continue
        if not fresh:
            if matches:
                run.missing_reason(
                    "startup_log_stale",
                    site,
                    "only pre-start completion lines echo this correlation id",
                    [refs["meta"]],
                )
            else:
                run.missing_reason(
                    "request_completion_absent",
                    site,
                    "no server completion line echoes this correlation id",
                    [refs["meta"]],
                )
            continue
        completion = fresh[0]
        start_ns = _parse_rfc3339_ns(receipt.started_at)
        finish_ns = _parse_rfc3339_ns(receipt.finished_at)
        if run.clock_skew_bound_s is None:
            run.missing_reason("clock_relationship_undeclared", site,
                               "completion cannot be bound without a declared clock relationship", [refs["meta"]])
            continue
        else:
            numerator, denominator = run.clock_skew_bound_s.as_integer_ratio()
            bound_ns = numerator * 1_000_000_000 // denominator
            if not start_ns - bound_ns <= completion.timestamp_ns <= finish_ns + bound_ns:
                run.contradiction("completion_ambiguous", site,
                                  "completion outside declared request clock bound", [refs["meta"]])
                continue
        if not 200 <= completion.status < 300:
            run.missing_reason(
                "request_completion_absent", site, f"server completion status {completion.status}", [refs["meta"]]
            )
            continue
        if not inference_allowed:
            continue
        observations.append(_inference_observation(run, receipt, completion, before, refs, logs))
    if candidates == 0:
        run.missing_reason(
            "request_completion_absent", "adapter_receipts", "no receipt carries a successful request to bind"
        )
    return observations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _final_artifacts(run: _Run) -> list[dict[str, Any]]:
    artifacts = []
    for spec in run.specs:
        artifacts.append(
            {
                "relative_path": spec.relative_path,
                "sha256": _sha(run.files[spec.relative_path]),
                "command_argv": spec.command_argv,
                "exit_code": spec.exit_code,
                "capture_started_at": spec.capture_started_at,
                "capture_finished_at": spec.capture_finished_at,
            }
        )
    return artifacts


def _issue_dict(issue: _Issue) -> dict[str, Any]:
    return {"code": issue.code, "field": issue.field, "detail": issue.detail, "artifact_refs": issue.artifact_refs}


class ClockSkewBoundError(ValueError):
    code = "clock_skew_bound_invalid"


def collect_runtime_evidence(
    *, runner: Any, observation: Mapping[str, Any], deadline: Any,
    clock_skew_bound_s: float | None = None,
) -> dict[str, Any]:
    """Collect the frozen ABI v1 runtime section. Returns {section, artifacts, raw_artifacts}."""
    if not isinstance(observation, Mapping):
        raise TypeError("observation must be a mapping of capture instructions")
    if clock_skew_bound_s is not None:
        if isinstance(clock_skew_bound_s, bool) or not isinstance(clock_skew_bound_s, (int, float)):
            raise ClockSkewBoundError("clock_skew_bound_s must be finite and nonnegative")
        try:
            clock_skew_bound_s = float(clock_skew_bound_s)
        except OverflowError:
            raise ClockSkewBoundError("clock_skew_bound_s must be finite and nonnegative") from None
        if not math.isfinite(clock_skew_bound_s) or clock_skew_bound_s < 0:
            raise ClockSkewBoundError("clock_skew_bound_s must be finite and nonnegative")
    run = _Run(runner, deadline, clock_skew_bound_s)
    instance_id = _text_or_none(observation.get("instance_id"))
    container = _text_or_none(observation.get("container_name")) or DEFAULT_CONTAINER

    before = _capture_identity(run, "before", instance_id, container)
    custody = _capture_custody(run, before)
    logs = _capture_logs(run, container, before.started_at)
    after = _capture_identity(run, "after", instance_id, container)
    contradicted, after_complete = _compare_identity(run, before, after)
    readiness = _capture_readiness(run, before.instance_id) if observation.get("readiness") else None

    inference_allowed = not contradicted and after_complete and before.complete
    observations: list[dict[str, Any]] = []
    if before.observable:
        observations.append(_identity_observation(run, before))
    if after.observable:
        observations.append(_identity_observation(run, after))
    if custody is not None and not contradicted:
        observations.append(_mapped_observation(run, before, custody, logs))
    raw_receipts = observation.get("adapter_receipts") or []
    if not isinstance(raw_receipts, Sequence) or isinstance(raw_receipts, str | bytes):
        run.contradiction("receipt_malformed", "adapter_receipts", "adapter_receipts is not a list")
        raw_receipts = []
    observations.extend(_bind_receipts(run, list(raw_receipts), before, logs, inference_allowed))
    if readiness is not None:
        observations.append(
            {
                "observation_id": "runtime.readiness",
                "kind": "readiness",
                "observed_at": readiness["finished_at"],
                "artifact_relative_path": readiness["path"],
                "artifact_sha256": readiness["ref"]["sha256"],
                "source_artifacts": [],
                "data": {
                    "instance_id": readiness["instance_id"],
                    "authenticated": readiness["authenticated"],
                    "http_status": readiness["http_status"],
                    "ready": readiness["ready"],
                },
            }
        )

    capture_path = f"{RAW_DIR}/capture.json"
    run.persist(capture_path, run.capture_document())
    if run.contradictions:
        status = "contradicted"
    elif run.missing:
        status = "incomplete"
    else:
        status = "complete"
    section = {
        "status": status,
        "observations": observations,
        "missing_reasons": [_issue_dict(issue) for issue in run.missing],
        "contradictions": [_issue_dict(issue) for issue in run.contradictions],
    }
    return {
        "section": section,
        "artifacts": _final_artifacts(run),
        "raw_artifacts": dict(run.files),
    }
