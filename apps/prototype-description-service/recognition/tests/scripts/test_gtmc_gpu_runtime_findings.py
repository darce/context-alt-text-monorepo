"""Offline G2 source regressions; synthetic captures never certify GPU readiness.

Existing fixture builders are reused read-only;
assertions target the observations-list ABI, never the legacy oracle view.
Serving log/mapping shapes remain UNVERIFIED-NATIVE. No live I/O is permitted.
Canon v0.25.6 stable IDs: TEST-15, PROV-01, GRPH-32, WEB-16.
Each RED changes one input of a healthy pair, without mutating production.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


REPO = Path(__file__).resolve().parents[5]
CLOCK_SKEW_BOUND_S = 1.0


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def captures():
    return _load("c77_g2_readonly_captures", REPO / "scripts/tests/test_gtmr_gpu_runtime_receipts.py")


@pytest.fixture(autouse=True)
def forbid_live_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live I/O is forbidden in this offline module")

    for name in ("run", "Popen", "check_output", "call", "check_call"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def producer_receipt(captures, monkeypatch):
    """Actual adapter receipt with a declared synthetic shared UTC clock.

    MockTransport supplies response bytes; the adapter supplies wire request,
    parsed caption, encoded/source image, context and correlation ID. No fixture
    reconstructs these bytes from policy pins. Shared-clock tests characterize
    the collector; they do not attest a live server/client clock relationship.
    """
    f = captures
    adapter_module = f._adapter_module(monkeypatch)
    clock = iter((f.RECEIPT_STARTED_AT, f.RECEIPT_FINISHED_AT))
    monkeypatch.setattr(adapter_module, "_rfc3339_now", lambda: next(clock))
    receipts = []
    response_bytes = b'{"choices":[{"message":{"content":"Actual adapter caption."}}]}'
    wire = []

    def respond(request):
        wire.append(request.content)
        return httpx.Response(200, content=response_bytes)

    adapter = adapter_module.GpuRemoteDescriptionAdapter(
        endpoint_url="http://gpu.test:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_version="Q4_K_M",
        transport=httpx.MockTransport(respond),
        grounding_enabled=False,
        receipt_sink=receipts.append,
    )
    result = adapter.describe(image_bytes=f._png(), context={"title": "Harbor"})
    assert len(receipts) == len(wire) == 1
    receipt = dict(receipts[0])
    assert receipt["request_body"] == wire[0]
    assert receipt["response_body"] == response_bytes
    assert receipt["caption"] == result.caption.encode("utf-8")
    return receipt


class MappingRunner:
    """Bounded Mapping-return fake; legacy kwargs have compatibility defaults.

    No catch-all kwargs: accidental additions fail. FrozenRunner's older
    subprocess defaults and legacy assertion adapter are deliberately unused.
    """

    def __init__(self, script):
        self.script = {tuple(argv): list(outcomes) for argv, outcomes in script.items()}
        self.calls = 0

    def take(self, argv, *, timeout, max_bytes):
        self.calls += 1
        assert self.calls <= 32
        assert isinstance(argv, list) and all(isinstance(part, str) for part in argv)
        assert math.isfinite(timeout) and 0 < timeout <= 15
        assert type(max_bytes) is int and 0 < max_bytes <= 1 << 20
        key = tuple(argv)
        assert key in self.script, "unexpected command in offline fake"
        queue = self.script[key]
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        return {
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "exit_code": outcome.returncode,
            "timed_out": False,
            "truncated": False,
            "capture_started_at": "2026-10-12T00:00:21.000000Z",
            "capture_finished_at": "2026-10-12T00:00:21.100000Z",
        }

    def __call__(self, argv, *, timeout, max_bytes, capture_output=True, text=False, check=False, shell=False):
        assert capture_output is True and text is False and check is False and shell is False
        return self.take(argv, timeout=timeout, max_bytes=max_bytes)


class FrozenAbiRunner(MappingRunner):
    """Contract runner(argv, *, timeout, max_bytes), with no extra kwargs."""

    def __call__(self, argv, *, timeout, max_bytes):
        return self.take(argv, timeout=timeout, max_bytes=max_bytes)


def collect(f, receipt, *, overrides=None, completion=None, offload=None, runner_type=MappingRunner,
            clock_skew_bound_s=CLOCK_SKEW_BOUND_S):
    # Log echo is explicitly UNVERIFIED-NATIVE, derived from the actual receipt
    # ID rather than an invented audit ID. It tests parsing/binding only.
    timestamp = completion if completion is not None else f.T_COMPLETION
    echo = f"{timestamp} srv  log_server_r: request_id={receipt['correlation_id']} status=200 completion"
    logs = f._logs(f.LOG_BUILD, offload if offload is not None else f.LOG_OFFLOAD_GPU, echo)
    script_overrides = {f.ARGV_LOGS: [f._done(f.ARGV_LOGS, logs)]}
    script_overrides.update(overrides or {})
    runner = runner_type(f._healthy_script(script_overrides))
    raw = f._collector().collect_runtime_evidence(
        runner=runner,
        observation={
            "instance_id": f.INSTANCE_ID,
            "container_name": f.CONTAINER_NAME,
            "adapter_receipts": [receipt],
        },
        deadline=time.monotonic() + 30,
        **({} if clock_skew_bound_s is None else {"clock_skew_bound_s": clock_skew_bound_s}),
    )
    assert 0 < runner.calls <= 32
    assert set(raw) == {"section", "artifacts", "raw_artifacts"}
    section = raw["section"]
    assert set(section) == {"status", "observations", "missing_reasons", "contradictions"}
    assert isinstance(section["observations"], list)
    artifacts = {entry["relative_path"]: entry for entry in raw["artifacts"]}
    assert len(artifacts) == len(raw["artifacts"])
    assert set(artifacts) == set(raw["raw_artifacts"])
    for path, data in raw["raw_artifacts"].items():
        assert artifacts[path]["sha256"] == sha(data)
        assert not Path(path).is_absolute() and ".." not in Path(path).parts
    for observation in section["observations"]:
        assert observation["artifact_sha256"] == artifacts[observation["artifact_relative_path"]]["sha256"]
        for ref in observation["source_artifacts"]:
            assert ref["sha256"] == artifacts[ref["relative_path"]]["sha256"]
    capture = next(json.loads(data) for path, data in raw["raw_artifacts"].items() if path.endswith("/capture.json"))
    assert capture["schema_version"] == 1
    assert capture["clock_relationship"] == {
        "kind": "undeclared" if clock_skew_bound_s is None else "declared_shared_clock_bound",
        "bound_s": clock_skew_bound_s, "observed": False,
    }
    return raw


def sha(data):
    return hashlib.sha256(data).hexdigest()


def observations(raw, kind):
    return [entry["data"] for entry in raw["section"]["observations"] if entry["kind"] == kind]


def assert_healthy(raw):
    # Scoped fixture capture completeness is never task/E2E/quality readiness.
    assert raw["section"]["status"] == "complete"
    assert raw["section"]["contradictions"] == []
    assert raw["section"]["missing_reasons"] == []
    assert len(observations(raw, "inference")) == 1


def test_control_r01_caption_is_bound_to_retained_actual_response(captures, producer_receipt):
    raw = collect(captures, producer_receipt)
    assert_healthy(raw)
    caption = json.loads(producer_receipt["response_body"])["choices"][0]["message"]["content"].encode()
    assert observations(raw, "inference")[0]["caption_sha256"] == sha(caption)
    assert producer_receipt["response_body"] in raw["raw_artifacts"].values()


@pytest.mark.parametrize("mutation", ["caption", "malformed_response"])
def test_red_r01_caption_must_derive_from_retained_actual_response(captures, producer_receipt, mutation):
    """Malformed retained response contradicts supplied caption custody (R01 pin)."""
    changed = dict(producer_receipt)
    if mutation == "caption":
        changed["caption"] = b"Unrelated output."
    else:
        changed["response_body"] = b"not-json"
    raw = collect(captures, changed)
    assert raw["section"]["status"] == "contradicted", "G2-R01: unbound caption accepted"
    assert observations(raw, "inference") == []


def test_control_r02_completion_is_inside_declared_request_interval(captures, producer_receipt):
    """Completion start remains the client start; clock bound is declared, not observed."""
    raw = collect(captures, producer_receipt)
    assert_healthy(raw)
    data = observations(raw, "inference")[0]
    assert data["completion_started_at"] == producer_receipt["started_at"]
    assert data["completion_finished_at"] == captures.T_COMPLETION


def shifted_timestamp(f, timestamp, offset_s):
    ns = f._collector()._parse_rfc3339_ns(timestamp) + int(offset_s * 1_000_000_000)
    seconds, fraction = divmod(ns, 1_000_000_000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{fraction:09d}Z"


@pytest.mark.parametrize("bound_s", [0.0, 0.25, 2.0])
@pytest.mark.parametrize("mutation", ["reversed_client", "before_request", "after_response"])
def test_red_r02_impossible_timestamps_are_contradictions(captures, producer_receipt, mutation, bound_s):
    changed = dict(producer_receipt)
    completion = None
    if mutation == "reversed_client":
        changed["started_at"] = "2026-10-12T00:00:25.000000Z"
    elif mutation == "before_request":
        completion = shifted_timestamp(captures, changed["started_at"], -bound_s - 0.5)
    else:
        completion = shifted_timestamp(captures, changed["finished_at"], bound_s + 0.5)
    raw = collect(captures, changed, completion=completion, clock_skew_bound_s=bound_s)
    assert raw["section"]["status"] == "contradicted", "G2-R02: impossible shared-clock interval accepted"
    assert observations(raw, "inference") == []


@pytest.mark.parametrize("bound_s", [CLOCK_SKEW_BOUND_S, None], ids=["declared", "undeclared"])
def test_red_r02_reversed_within_bound_is_malformed(captures, producer_receipt, bound_s):
    changed = dict(producer_receipt)
    changed["started_at"] = shifted_timestamp(captures, captures.T_COMPLETION, 0.25)
    changed["finished_at"] = shifted_timestamp(captures, captures.T_COMPLETION, -0.25)
    raw = collect(captures, changed, clock_skew_bound_s=bound_s)
    assert raw["section"]["status"] == "contradicted", "G2-R02: reversed single-clock interval accepted"
    assert "receipt_malformed" in {issue["code"] for issue in raw["section"]["contradictions"]}
    assert observations(raw, "inference") == []


@pytest.mark.parametrize("bound_s", [0.0, 0.25, 2.0])
@pytest.mark.parametrize("edge", ["started_at", "finished_at"])
def test_control_r02_completion_at_declared_bound_is_retained(captures, producer_receipt, bound_s, edge):
    offset = -bound_s if edge == "started_at" else bound_s
    completion = shifted_timestamp(captures, producer_receipt[edge], offset)
    assert_healthy(collect(captures, producer_receipt, completion=completion, clock_skew_bound_s=bound_s))


@pytest.mark.parametrize("edge", ["started_at", "finished_at"])
def test_control_r02_absent_clock_bound_is_incomplete(captures, producer_receipt, edge):
    offset = -CLOCK_SKEW_BOUND_S - 0.5 if edge == "started_at" else CLOCK_SKEW_BOUND_S + 0.5
    completion = shifted_timestamp(captures, producer_receipt[edge], offset)
    raw = collect(captures, producer_receipt, completion=completion, clock_skew_bound_s=None)
    assert raw["section"]["status"] == "incomplete"
    assert raw["section"]["contradictions"] == []
    assert "clock_relationship_undeclared" in {issue["code"] for issue in raw["section"]["missing_reasons"]}
    assert observations(raw, "inference") == []


@pytest.mark.parametrize("bound_s", [-1, float("nan"), float("inf"), True, "1", {}, 10 ** 400],
                         ids=["negative", "nan", "inf", "bool", "string", "mapping", "overflow"])
def test_red_r02_invalid_clock_bound_is_refused_before_capture(captures, bound_s):
    runner = MappingRunner({})
    with pytest.raises(ValueError) as error:
        captures._collector().collect_runtime_evidence(
            runner=runner, observation={}, deadline=time.monotonic() + 30, clock_skew_bound_s=bound_s,
        )
    assert getattr(error.value, "code", None) == "clock_skew_bound_invalid"
    assert runner.calls == 0


def inspect_with_canary(f):
    # Artificial canary, never a credential; keep assertion diagnostics boolean.
    canary = "offline-" + "redaction-canary"
    doc = json.loads(f._inspect_json())
    doc[0]["Config"]["Env"] = ["FIXTURE_TOKEN=" + canary, "PATH=/usr/bin"]
    return doc, canary.encode()


def assert_canary_excluded(raw, canary):
    assert all(canary not in data for data in raw["raw_artifacts"].values()), "G2-R03: unsafe inspect bytes persisted"
    assert canary not in json.dumps(raw["section"]).encode()


def test_control_r03_successful_inspect_excludes_env_canary(captures, producer_receipt):
    doc, canary = inspect_with_canary(captures)
    payload = json.dumps(doc).encode()
    raw = collect(captures, producer_receipt, overrides={captures.ARGV_INSPECT: [captures._done(captures.ARGV_INSPECT, payload)]})
    assert_healthy(raw)
    assert_canary_excluded(raw, canary)


@pytest.mark.parametrize("mutation", ["nonzero_exit", "ambiguous_objects", "unparseable_inspect"])
def test_red_r03_failed_or_malformed_inspect_excludes_env_canary(captures, producer_receipt, mutation):
    f = captures
    doc, canary = inspect_with_canary(f)
    rc = 9 if mutation == "nonzero_exit" else 0
    if mutation == "ambiguous_objects":
        doc.append(dict(doc[0]))
    payload = json.dumps(doc).encode()
    if mutation == "unparseable_inspect":
        payload = payload[:-1]
    raw = collect(f, producer_receipt, overrides={f.ARGV_INSPECT: [f._done(f.ARGV_INSPECT, payload, rc=rc)]})
    assert raw["section"]["status"] == "incomplete"
    assert_canary_excluded(raw, canary)
    if mutation == "unparseable_inspect":
        assert all(raw["raw_artifacts"][call["stdout"]["relative_path"]] == b"" for call in inspect_calls(raw))


@pytest.mark.parametrize("config_name", ["Config", "ContainerConfig"])
def test_red_r03_env_names_survive_value_redaction(captures, producer_receipt, config_name):
    doc, canary = inspect_with_canary(captures)
    if config_name == "ContainerConfig":
        doc[0][config_name] = {"Env": doc[0]["Config"].pop("Env")}
    payload = json.dumps(doc).encode()
    raw = collect(captures, producer_receipt,
                  overrides={captures.ARGV_INSPECT: [captures._done(captures.ARGV_INSPECT, payload)]})
    assert_canary_excluded(raw, canary)
    assert_healthy(raw)
    for call in inspect_calls(raw):
        persisted = json.loads(raw["raw_artifacts"][call["stdout"]["relative_path"]])
        assert persisted[0][config_name]["Env"] == ["FIXTURE_TOKEN=<redacted>", "PATH=<redacted>"]
        assert config_name + ".Env" in call["redaction"]["fields"]


@pytest.mark.parametrize("config_name", ["Config", "ContainerConfig"])
@pytest.mark.parametrize("shape", ["non_list", "non_string"])
def test_red_r03_malformed_env_values_are_withheld(captures, producer_receipt, config_name, shape):
    doc, canary = inspect_with_canary(captures)
    doc[0]["Config"].pop("Env")
    env = canary.decode() if shape == "non_list" else [{"value": canary.decode()}]
    doc[0].setdefault(config_name, {})["Env"] = env
    payload = json.dumps(doc).encode()
    raw = collect(captures, producer_receipt,
                  overrides={captures.ARGV_INSPECT: [captures._done(captures.ARGV_INSPECT, payload)]})
    assert_canary_excluded(raw, canary)
    assert_healthy(raw)
    for call in inspect_calls(raw):
        persisted = json.loads(raw["raw_artifacts"][call["stdout"]["relative_path"]])
        assert persisted[0][config_name]["Env"] == ["<redacted>"]


def test_red_r03_redacted_inspect_overflow_obeys_byte_budget(captures, producer_receipt):
    doc, canary = inspect_with_canary(captures)
    doc[0]["ContainerConfig"] = {"Env": list(doc[0]["Config"]["Env"])}
    doc[0]["Padding"] = "x" * ((1 << 20) + 1)
    payload = json.dumps(doc).encode()
    raw = collect(captures, producer_receipt,
                  overrides={captures.ARGV_INSPECT: [captures._done(captures.ARGV_INSPECT, payload)]})
    assert_canary_excluded(raw, canary)
    assert raw["section"]["status"] == "incomplete"
    assert "output_truncated" in {issue["code"] for issue in raw["section"]["missing_reasons"]}
    for call in inspect_calls(raw):
        persisted = raw["raw_artifacts"][call["stdout"]["relative_path"]]
        assert call["truncated"] is True
        assert call["stdout"]["bytes_received"] == len(payload) > call["max_bytes"]
        assert len(persisted) == call["stdout"]["bytes_persisted"] <= call["max_bytes"]


def inspect_stderr(f, size):
    return {f.ARGV_INSPECT: [f._done(f.ARGV_INSPECT, f._inspect_json(), stderr=b"x" * size)]}


def inspect_calls(raw):
    capture = next(json.loads(data) for path, data in raw["raw_artifacts"].items() if path.endswith("/capture.json"))
    return [call for call in capture["calls"] if call["argv"][:2] == ["docker", "inspect"]]


def test_control_r04_stderr_at_cap_is_retained_without_truncation(captures, producer_receipt):
    raw = collect(captures, producer_receipt, overrides=inspect_stderr(captures, 65536))
    assert_healthy(raw)
    calls = inspect_calls(raw)
    assert len(calls) == 2
    assert all(call["stderr"]["bytes_received"] == call["stderr"]["bytes_persisted"] == 65536 for call in calls)
    assert all(call["truncated"] is False for call in calls)


def test_red_r04_clipped_stderr_marks_truncated_and_incomplete(captures, producer_receipt):
    """Retain the first 65536 stderr bytes and report the proven loss (R04 pin)."""
    raw = collect(captures, producer_receipt, overrides=inspect_stderr(captures, 65537))
    calls = inspect_calls(raw)
    assert len(calls) == 2
    assert all(call["stderr"]["bytes_received"] == 65537 and call["stderr"]["bytes_persisted"] == 65536 for call in calls)
    assert all(call["truncated"] is True for call in calls), "G2-R04: proven stderr byte loss not flagged"
    assert raw["section"]["status"] == "incomplete"
    assert "output_truncated" in {issue["code"] for issue in raw["section"]["missing_reasons"]}


def test_control_r05_mapping_result_is_consumed(captures, producer_receipt):
    assert_healthy(collect(captures, producer_receipt, runner_type=MappingRunner))


def test_red_r05_frozen_mapping_runner_needs_only_timeout_and_max_bytes(captures, producer_receipt):
    try:
        raw = collect(captures, producer_receipt, runner_type=FrozenAbiRunner)
    except TypeError as exc:
        if "unexpected keyword argument 'capture_output'" not in str(exc):
            raise
        pytest.fail("G2-R05: collector passes kwargs outside frozen runner ABI", pytrace=False)
    assert_healthy(raw)


def test_control_r06_positive_offload_is_an_observed_value(captures, producer_receipt):
    raw = collect(captures, producer_receipt)
    assert_healthy(raw)
    model = observations(raw, "mapped_model")[0]
    assert model["offloaded_layers"] == 49 and model["gpu_execution"] is True


def test_red_r06_zero_offload_is_observation_without_policy_judgment(captures, producer_receipt):
    raw = collect(captures, producer_receipt, offload=captures.LOG_OFFLOAD_CPU)
    model = observations(raw, "mapped_model")[0]
    assert model["offloaded_layers"] == 0 and model["gpu_execution"] is False
    assert raw["section"]["contradictions"] == [], "G2-R06: observed zero assigned policy contradiction"
    # G1 may refuse GPU policy; coherent scoped capture still records zero.
    assert_healthy(raw)
