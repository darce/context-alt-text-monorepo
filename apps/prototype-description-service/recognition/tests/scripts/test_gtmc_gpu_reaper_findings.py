"""Offline native receipt regressions; no OCI process is launched.

Only the subprocess side effect and host boot identity are replaced. Native
publication reads, locks, generation comparison, actuation and journal remain
in use. Reader callbacks are explicit test-only hooks, never OCI header proof.
PROV-01 / GRPH-32: each receipt is joined to named consumed raw publications.
TEST-15: the two unmarked RED cases exercise existing causal source defects.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from infra.oci.gpu_lifecycle import reaper
from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.intent import DecisionLogStore, IntentAuthorityStore
from infra.oci.gpu_lifecycle.load_source import AggregateJobLoadSource


BIN = "/nonexistent/c77-offline-oci"
INSTANCE = "offline-c77-instance"
REVISIONS = {"dev": 9101, "prod": 9102}
GENERATION_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
IDENTIFIERS = (
    "caller_request_id", "oci_response_request_id", "audit_request_id",
    "audit_event_id", "audit_principal_id",
)


def _publish(root: Path, environment: str, revision: int) -> Path:
    path = root / environment / "describe-load.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "queue_depth": 0, "in_flight": 0, "lease_demand": 0,
        "batch_in_progress": False, "revision": revision,
        "written_at": time.time(),
    }, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)
    return path


class SideEffects:
    """Record native argv; CompletedProcess is the subprocess API return shape."""

    def __init__(self, state="RUNNING", failure=None):
        self.state = state
        self.failure = failure
        self.actions = []
        self.gets = []
        self.started = []

    def run(self, cmd, **kwargs):
        argv = list(cmd)
        assert argv[0] == BIN, "offline guard: unexpected process"
        assert 0 < kwargs["timeout"] <= 5, "RES-02: bounded process"
        if argv[1:4] == ["compute", "instance", "get"]:
            self.gets.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
                "data": {"id": INSTANCE, "lifecycle-state": self.state},
            }), stderr="")
        assert argv[1:4] == ["compute", "instance", "action"]
        assert argv[argv.index("--instance-id") + 1] == INSTANCE
        assert argv[argv.index("--action") + 1] == "STOP"
        assert kwargs["check"] is True and kwargs["capture_output"] is True
        self.actions.append(argv)
        if self.failure == "launch":
            raise OSError("offline process launch refused")
        self.started.append(argv)
        if self.failure == "exit":
            raise subprocess.CalledProcessError(1, argv, output="", stderr="offline failure")
        self.state = "STOPPED"
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
            "data": {"id": INSTANCE, "lifecycle-state": "STOPPING"},
        }), stderr="")


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(IntentAuthorityStore, "_read_boot_id", staticmethod(lambda: "offline-c77-boot"))
    root = tmp_path / "load"
    paths = {env: _publish(root, env, revision) for env, revision in REVISIONS.items()}
    raw = {env: path.read_bytes() for env, path in paths.items()}
    generations = {
        env: dict(zip(GENERATION_FIELDS, (
            path.stat().st_dev, path.stat().st_ino,
            path.stat().st_size, path.stat().st_mtime_ns,
        ), strict=True)) for env, path in paths.items()
    }
    source = AggregateJobLoadSource(directory=root, stale_seconds=120, expected_environments=tuple(REVISIONS))
    real_read = AggregateJobLoadSource._read_consumed_publications
    read_entries = []

    def observed_read(self, expected):
        # Verify BOTH locks at raw-read entry, not merely during the later action.
        for env in REVISIONS:
            fd = os.open(root / env / "describe-load.json.lock", os.O_RDONLY)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
        read_entries.append(expected)
        return real_read(self, expected)

    monkeypatch.setattr(AggregateJobLoadSource, "_read_consumed_publications", observed_read)

    def run(*, state="RUNNING", failure=None, reader=None, legacy=False, opaque_failure=None):
        effects = SideEffects(state, failure)
        monkeypatch.setattr(reaper.subprocess, "run", effects.run)
        actuator = reaper.OciCliStopActuator(oci_bin=BIN, timeout_seconds=5, response_request_id_reader=reader)
        legacy_calls = []
        if legacy:
            class LegacyNoOp:
                def stop_instance(self, instance_id):
                    legacy_calls.append(instance_id)
                    return None  # Native supported legacy protocol shape, zero actions.
            actuator = LegacyNoOp()
        if opaque_failure is not None:
            native = actuator

            class OpaqueFailure:
                def stop_instance(self, instance_id):
                    if opaque_failure == "after_action":
                        native.stop_instance(instance_id)
                        raise OSError("offline opaque failure after action")
                    raise RuntimeError("offline opaque failure before action")

            actuator = OpaqueFailure()
        log = tmp_path / "decisions.jsonl"
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        result = reaper.run_reap_cycle(
            controller=GpuLifecycleController(idle_seconds=60),
            instances=[GpuInstance(instance_id=INSTANCE, state="RUNNING", idle_for_seconds=90)],
            load_source=source, actuator=actuator, fence_delay_seconds=0,
            max_lease_seconds=0, intent_dir=runtime,
            durable_state_dir=tmp_path / "durable", gpu_state_path=tmp_path / "gpu-state.json",
            decision_log_store=DecisionLogStore(log), now=datetime.now(UTC),
        )
        records = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(records) == 1 and len(read_entries) == 1
        record = records[0]
        receipts = record["lifecycle_receipts"]
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt["decision_id"] == record["decision_id"]
        assert receipt["action"] == "STOP" and receipt["instance_id"] == INSTANCE
        # Replace the live publications AFTER consumption. Custody must still name
        # the original distinct revisions and exact bytes, including error paths.
        for env in REVISIONS:
            _publish(root, env, 9200)
        consumed = receipt["consumed_load"]
        assert len(consumed) == len(REVISIONS)
        assert {item["environment"] for item in consumed} == set(REVISIONS)
        for item in consumed:
            env = item["environment"]
            assert item["revision"] == REVISIONS[env]
            assert item["generation"] == generations[env]
            assert item["publication_artifact_sha256"] == hashlib.sha256(raw[env]).hexdigest()
            relative = Path(item["publication_artifact_path"])
            assert not relative.is_absolute() and ".." not in relative.parts
            retained = (tmp_path / relative).read_bytes()
            assert retained == raw[env]
            assert json.loads(retained)["revision"] == REVISIONS[env]
        assert all(receipt[field] is None for field in IDENTIFIERS)
        return receipt, effects, legacy_calls, result, record

    return run


def test_red_legacy_none_without_actions_cannot_claim_command_invoked(cycle):
    receipt, effects, calls, result, record = cycle(legacy=True)
    assert calls == [INSTANCE] and effects.actions == [] and effects.started == []
    assert receipt["command_invoked"] is None
    assert receipt["outcome"] == "unknown"
    for field in ("actuation_receipt", "command_invoked"):
        assert {"field": field, "code": "actuator_returned_no_receipt"} in receipt["missing_reasons"]
    assert result.actuated == [("STOP", INSTANCE)]
    assert record["actuation_outcome"] == "honoured"


@pytest.mark.parametrize("reader_error", [OSError, ValueError])
def test_red_reader_oserror_after_action_cannot_reset_process_started(cycle, reader_error):
    reader_inputs = []

    def reader(stdout, stderr):
        reader_inputs.append((stdout, stderr))
        raise reader_error("offline receipt reader unavailable after action")

    receipt, effects, _, result, _ = cycle(reader=reader)
    assert len(effects.actions) == len(effects.started) == len(reader_inputs) == 1
    assert effects.state == "STOPPED" and json.loads(reader_inputs[0][0])["data"]["lifecycle-state"] == "STOPPING"
    assert receipt["command_invoked"] is True, "post-action reader failure cannot erase the observed process start"
    assert receipt["outcome"] == "issued"
    assert receipt["final_state"] == "STOPPING"
    assert receipt["oci_response_request_id"] is None
    assert {"field": "oci_response_request_id", "code": "action_response_reader_failed"} in receipt["missing_reasons"]
    assert not any(item["code"] == "process_not_started" for item in receipt["missing_reasons"])
    assert result.actuated == [("STOP", INSTANCE)]


@pytest.mark.parametrize("reader", [None, lambda stdout, stderr: None], ids=["default", "test-only-no-identifier"])
def test_control_successful_action_keeps_named_raw_custody(cycle, reader):
    receipt, effects, _, _, _ = cycle(reader=reader)
    assert len(effects.actions) == len(effects.started) == 1
    assert receipt["command_invoked"] is True and receipt["outcome"] == "issued"
    assert receipt["final_state"] == "STOPPING"
    assert any(item["field"] == "oci_response_request_id" for item in receipt["missing_reasons"])


def test_control_converged_stop_keeps_custody_without_action_rpc(cycle):
    def forbidden_reader(stdout, stderr):
        pytest.fail("converged GET must never enter action response reader")

    receipt, effects, _, _, _ = cycle(state="STOPPED", reader=forbidden_reader)
    assert len(effects.gets) == 1 and effects.actions == effects.started == []
    assert receipt["command_invoked"] is False and receipt["outcome"] == "already_converged"
    assert receipt["final_state"] == "STOPPED"


@pytest.mark.parametrize("failure,invoked", [("launch", False), ("exit", True)])
def test_control_launch_failure_and_started_failure_are_distinct(cycle, failure, invoked):
    receipt, effects, _, _, _ = cycle(failure=failure)
    assert len(effects.actions) == 1 and len(effects.started) == int(invoked)
    assert receipt["command_invoked"] is invoked and receipt["outcome"] == "failed"


@pytest.mark.parametrize("stage,actions", [("before_action", 0), ("after_action", 1)])
def test_opaque_failure_preserves_unknown_invocation_in_real_cycle(cycle, stage, actions):
    receipt, effects, _, result, record = cycle(opaque_failure=stage)
    assert len(effects.actions) == len(effects.started) == actions
    assert receipt["command_invoked"] is None
    assert receipt["outcome"] == "unknown"
    assert {"field": "command_invoked", "code": "invocation_unattributed"} in receipt["missing_reasons"]
    assert not any(item["code"] == "process_not_started" for item in receipt["missing_reasons"])
    assert result.errors and record["actuation_outcome"] == "failed"
