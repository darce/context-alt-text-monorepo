"""G3 causal joins for the idle reaper: publication revision, consumed generation, decision, OCI response.

Authoring rules for this file:

* Producers are real. ``AggregateJobLoadSource`` reads native ``describe-load.json`` bytes,
  ``run_reap_cycle`` decides and fences, ``OciCliStopActuator`` builds the argv, and
  ``DecisionLogStore`` appends the JSONL decision record.
* The OCI CLI is replaced only at the ``subprocess.run`` boundary by ``FakeOciCli``. Every
  process invocation must use the sentinel binary; anything else fails the test. No OCI
  request, network call, or host path under /opt, /run, or /var is touched.
* RED tests name a join the current producer does not export. They do not depend on a field
  name: each asserts that the decision record carries the observed value in any recoverable
  form, so an implementation that exports the join passes without matching this file's wording.
* CONTROL tests pin behavior that exists today (counts, fence, STOP, idempotency, fail-closed
  load) and must survive the producer change unchanged.

Typed missing-interface proposal (not imported here, so its absence is not a behavior defect):

* the decision record carries, for each declared environment, the fence generation consumed by
  ``actuate_if_generation`` and the publication revision the same cycle read. The RED asserts the raw
  components so an independent reader can check them without the producer's encoding; a digest-only
  encoding would need its canonical form specified separately;
* each STOP receipt carries the OCI request identifier from the actuation response, or an explicit
  missing marker when the CLI exposes none (never a fabricated value);
* a decision that claims an actuation distinguishes "OCI request issued" from "already converged on
  a convergence poll".

The fake's request-identifier line is a fake native shape. Whether the real OCI CLI exposes an
``opc-request-id`` on stdout or stderr is unverified in this lane and must be probed natively by
the parent before any implementation relies on it.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import infra.oci.gpu_lifecycle.reaper as reaper_mod
import pytest
from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.intent import DecisionLogStore, IntentAuthorityStore
from infra.oci.gpu_lifecycle.load_source import AggregateJobLoadSource
from infra.oci.gpu_lifecycle.reaper import OciCliStopActuator, ReapCycleResult, run_reap_cycle

FAKE_OCI_BIN = "/nonexistent/gtmr-fake-oci-cli"
ENV = "dev"
OTHER_ENV = "prod"
INSTANCE_ID = "ocid1.instance.oc1..gtmrjoins"
IDLE_SECONDS = 60
REVISION = 9001
REQUEST_ID_PREFIX = "opc-req-"


@pytest.fixture(autouse=True)
def _known_host_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    # The intent authority store reads the host boot id; pin it so these tests run anywhere.
    monkeypatch.setattr(IntentAuthorityStore, "_read_boot_id", staticmethod(lambda: "gtmr-joins-boot"))


@dataclass
class FakeOciCli:
    """Subprocess-boundary fake for the OCI CLI. It never reaches OCI.

    Output follows real ``subprocess.run`` semantics: stdout or stderr is returned only when the
    caller captured it. A STOP action moves the fake instance to STOPPED. ``action_fails`` makes the
    action exit non-zero (``check=True`` raises) and leaves the instance state unchanged.
    ``get_request_id`` prints an identifier on the convergence GET's stderr, which is not an action.
    """

    state: str = "RUNNING"
    request_id: str | None = None
    get_request_id: str | None = None
    action_fails: bool = False
    get_argv: list[list[str]] = field(default_factory=list)
    action_argv: list[list[str]] = field(default_factory=list)
    action_output_captured: list[bool] = field(default_factory=list)

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        argv = [str(part) for part in cmd]
        if not argv or argv[0] != FAKE_OCI_BIN:
            raise AssertionError(f"non-fake process invoked from the lifecycle test: {argv[:1]}")
        captured_out = kwargs.get("capture_output") is True or kwargs.get("stdout") == subprocess.PIPE
        captured_err = kwargs.get("capture_output") is True or kwargs.get("stderr") == subprocess.PIPE
        if argv[1:4] == ["compute", "instance", "get"]:
            self.get_argv.append(argv)
            body = json.dumps({"data": {"id": INSTANCE_ID, "lifecycle-state": self.state}})
            get_err = f"{REQUEST_ID_PREFIX}{self.get_request_id}\n" if self.get_request_id else ""
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=body if captured_out else None,
                stderr=get_err if captured_err else None,
            )
        if argv[1:4] == ["compute", "instance", "action"]:
            self.action_argv.append(argv)
            self.action_output_captured.append(captured_out or captured_err)
            if self.action_fails:
                if kwargs.get("check") is True:
                    raise subprocess.CalledProcessError(1, argv, output="", stderr="fake action failure")
                return subprocess.CompletedProcess(argv, 1, stdout=None, stderr=None)
            self.state = "STOPPED"
            body = json.dumps({"data": {"id": INSTANCE_ID, "lifecycle-state": "STOPPING"}})
            err = f"{REQUEST_ID_PREFIX}{self.request_id}\n" if self.request_id else ""
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=body if captured_out else None,
                stderr=err if captured_err else None,
            )
        raise AssertionError(f"unexpected OCI CLI subcommand in the fake: {argv[1:4]}")


@pytest.fixture
def fake_oci(monkeypatch: pytest.MonkeyPatch) -> FakeOciCli:
    fake = FakeOciCli()
    monkeypatch.setattr(reaper_mod.subprocess, "run", fake.run)
    return fake


@dataclass(frozen=True)
class ReapRun:
    result: ReapCycleResult
    records: list[dict[str, Any]]
    raw_records: list[str]
    consumed: list[Any]


def _publish(
    load_dir: Path,
    environment: str,
    *,
    revision: int,
    queue_depth: int = 0,
    in_flight: int = 0,
    lease_demand: int = 0,
    batch_in_progress: bool = False,
    written_at: float | None = None,
) -> Path:
    """Replace one environment's describe-load.json the way the publisher does: write temp, rename."""
    target = load_dir / environment / "describe-load.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "queue_depth": queue_depth,
        "in_flight": in_flight,
        "batch_in_progress": batch_in_progress,
        "lease_demand": lease_demand,
        "revision": revision,
        "written_at": time.time() if written_at is None else written_at,
    }
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, target)
    return target


def _running(idle_seconds: int = 90) -> GpuInstance:
    return GpuInstance(instance_id=INSTANCE_ID, state="RUNNING", idle_for_seconds=idle_seconds)


def _stopped() -> GpuInstance:
    return GpuInstance(instance_id=INSTANCE_ID, state="STOPPED", idle_for_seconds=0)


def _reap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    load_dir: Path,
    fake: FakeOciCli,
    environments: tuple[str, ...] = (ENV,),
    instances: list[GpuInstance] | None = None,
    log_path: Path | None = None,
    before_fence_sample: Callable[[], None] | None = None,
    actuator: OciCliStopActuator | None = None,
    max_lease_seconds: int = 0,
) -> ReapRun:
    """Run one real reap cycle; spy on the real fence call and the real snapshot without replacing them."""
    consumed: list[Any] = []
    real_actuate = AggregateJobLoadSource.actuate_if_generation

    def record_consumed(self: AggregateJobLoadSource, expected_generation: object, action: Callable[[], None]) -> bool:
        consumed.append(expected_generation)
        return real_actuate(self, expected_generation, action)

    monkeypatch.setattr(AggregateJobLoadSource, "actuate_if_generation", record_consumed)
    if before_fence_sample is not None:
        real_snapshot = AggregateJobLoadSource.snapshot
        samples = 0

        def snapshot_with_fence_hook(self: AggregateJobLoadSource) -> Any:
            nonlocal samples
            samples += 1
            if samples == 2:  # 1 = initial decision sample, 2 = fence resample inside the cycle
                before_fence_sample()
            return real_snapshot(self)

        monkeypatch.setattr(AggregateJobLoadSource, "snapshot", snapshot_with_fence_hook)

    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    log = tmp_path / "decision-log.jsonl" if log_path is None else log_path
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=IDLE_SECONDS),
        instances=[_running()] if instances is None else instances,
        load_source=AggregateJobLoadSource(
            directory=load_dir,
            stale_seconds=120.0,
            expected_environments=environments,
        ),
        actuator=OciCliStopActuator(oci_bin=FAKE_OCI_BIN, timeout_seconds=5) if actuator is None else actuator,
        fence_delay_seconds=0,
        max_lease_seconds=max_lease_seconds,
        intent_dir=runtime,
        durable_state_dir=tmp_path / "durable",
        gpu_state_path=tmp_path / "gpu-state.json",
        decision_log_store=DecisionLogStore(log),
        now=datetime.now(UTC),
    )
    raw = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return ReapRun(
        result=result,
        records=[json.loads(line) for line in raw],
        raw_records=raw,
        consumed=consumed,
    )


def _int_values(value: Any) -> set[int]:
    """Every integer a record carries, including decimal strings, so encoding choices do not matter."""
    found: set[int] = set()
    if isinstance(value, dict):
        for item in value.values():
            found |= _int_values(item)
    elif isinstance(value, list | tuple):
        for item in value:
            found |= _int_values(item)
    elif isinstance(value, bool):
        return found
    elif isinstance(value, int):
        found.add(value)
    elif isinstance(value, str) and value.isdigit():
        found.add(int(value))
    return found


def _unbound_fence_components(record: dict[str, Any], generation: Any) -> list[int]:
    """Stat components of the consumed fence generation that the decision record does not carry."""
    recorded = _int_values(record)
    return sorted(
        component for _, stat in generation if stat is not None for component in stat if component not in recorded
    )


def _revision_is_bound(record: dict[str, Any], revision: int) -> bool:
    return revision in _int_values(record)


def _request_id_is_bound(raw_record: str, request_id: str) -> bool:
    return request_id in raw_record


def _claimed_stops(records: list[dict[str, Any]]) -> int:
    """STOPs the decision log says were honoured. Each one should correspond to one issued OCI request."""
    return sum(len(record["actuated"]) for record in records)


# --------------------------------------------------------------------------------------------
# CONTROL: behavior that exists today and must survive the join change.
# --------------------------------------------------------------------------------------------


def test_control_idle_stop_issues_one_oci_action_and_one_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert run.result.fenced_off is False
    assert run.result.actuated == [("STOP", INSTANCE_ID)]
    assert [argv[1:4] for argv in fake_oci.action_argv] == [["compute", "instance", "action"]]
    assert len(run.consumed) == 1, "the real fence must consume exactly one generation before STOP"
    assert len(run.records) == 1
    record = run.records[0]
    assert record["mode"] == "reap"
    assert record["actuation_outcome"] == "honoured"
    assert record["actuated"] == [{"action": "STOP", "instance_id": INSTANCE_ID}]


def test_control_generation_change_during_fence_cancels_stop_and_is_recorded_as_fenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)

    def publisher_replaces_snapshot() -> None:
        _publish(load_dir, ENV, revision=REVISION + 1)

    run = _reap(
        tmp_path,
        monkeypatch,
        load_dir=load_dir,
        fake=fake_oci,
        before_fence_sample=publisher_replaces_snapshot,
    )

    assert run.result.fenced_off is True
    assert run.result.actuated == []
    assert fake_oci.action_argv == [], "a generation change during the fence must issue no OCI action"
    assert len(run.records) == 1
    assert run.records[0]["actuation_outcome"] == "fenced_off"
    assert run.records[0]["actuated"] == []
    assert run.records[0]["decided"] == [{"action": "STOP", "instance_id": INSTANCE_ID}]


def test_control_pending_work_in_another_environment_blocks_stop_without_a_spend_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    _publish(load_dir, OTHER_ENV, revision=REVISION, queue_depth=1, lease_demand=1, in_flight=1)

    run = _reap(
        tmp_path,
        monkeypatch,
        load_dir=load_dir,
        fake=fake_oci,
        environments=(ENV, OTHER_ENV),
    )

    assert run.result.actuated == []
    assert fake_oci.action_argv == []
    assert run.records == [], "unexplained pending work must not write a STOP decision"


def test_control_untrustworthy_publication_fails_closed_without_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION, written_at=time.time() - 10_000)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert run.result.actuated == []
    assert fake_oci.action_argv == []
    assert not any(record["actuated"] for record in run.records)


def test_control_repeat_cycle_after_stop_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    first = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)
    assert first.result.actuated == [("STOP", INSTANCE_ID)]

    second = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci, instances=[_stopped()])

    assert second.result.actuated == []
    assert len(fake_oci.action_argv) == 1, "an already-stopped instance must not receive a second OCI action"
    assert len(second.records) == 1, "a no-op cycle must not append a decision record"


def test_control_converged_stop_issues_no_oci_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.state = "STOPPED"  # OCI converged before this cycle's STOP reaches the actuator

    _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv == [], "the convergence check must not issue a STOP request"
    assert [argv[1:4] for argv in fake_oci.get_argv] == [["compute", "instance", "get"]] * len(fake_oci.get_argv)


def test_control_absent_request_identifier_is_not_fabricated_or_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.request_id = "CTRL-REQ-7731"
    with_id = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)
    assert with_id.records

    fake_oci.state = "RUNNING"
    fake_oci.request_id = None
    without_id = _reap(
        tmp_path,
        monkeypatch,
        load_dir=load_dir,
        fake=fake_oci,
        log_path=tmp_path / "second-decision-log.jsonl",
    )

    assert len(fake_oci.action_argv) == 2
    assert without_id.records, "the STOP is still recorded when the CLI exposes no request identifier"
    assert REQUEST_ID_PREFIX not in without_id.raw_records[0]
    assert "CTRL-REQ-7731" not in without_id.raw_records[0], "an earlier response identifier must not leak"


def test_control_join_checks_accept_a_record_that_carries_the_joins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """Oracle sanity: each RED check must go green when the join is present, so the RED is not vacuous.

    The mutation is test-only and in memory: it adds the three joins to a real decision record the way a
    producer might, then runs the same check helpers the RED tests use.
    """
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.request_id = "STOP-7731"
    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)
    assert len(run.consumed) == 1 and len(run.records) == 1

    generation = run.consumed[0]
    carried = {
        **run.records[0],
        "consumed_generation": {env: list(stat) for env, stat in generation if stat is not None},
        "consumed_revision": {ENV: REVISION},
        "oci_request_id": "STOP-7731",
    }
    carried_raw = json.dumps(carried, sort_keys=True)

    assert _unbound_fence_components(carried, generation) == []
    assert _revision_is_bound(carried, REVISION)
    assert _request_id_is_bound(carried_raw, "STOP-7731")
    assert _claimed_stops([carried]) == len(fake_oci.action_argv) == 1


# --------------------------------------------------------------------------------------------
# RED: joins the current producer does not export. Each names an observed value and asserts that the
# decision record carries it in some recoverable form.
# --------------------------------------------------------------------------------------------


def test_red_decision_record_binds_the_generation_consumed_at_actuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """The STOP decision must be joinable to the fence generation that authorized it.

    Producer today: ``run_reap_cycle`` takes ``fence.generation`` inside the cycle and passes it to
    ``actuate_if_generation``, but ``ReapCycleResult`` does not carry it and ``_record_decision``
    appends a record without any generation component.
    """
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv, "precondition: the STOP must reach the OCI boundary"
    assert len(run.consumed) == 1 and len(run.records) == 1
    generation = run.consumed[0]
    assert dict(generation)[ENV] is not None, "precondition: the consumed generation must name the published file"
    missing = _unbound_fence_components(run.records[0], generation)
    assert not missing, (
        "decision record does not bind the fence generation consumed at actuate_if_generation: "
        f"unbound components {missing} of {generation}; record={run.raw_records[0]}"
    )


def test_red_decision_record_binds_the_publication_revision_the_reaper_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """The reaper reads ``revision`` from each publication but never carries it into the decision.

    The publication is a native scene-writer payload. ``AggregateJobLoadSource`` ignores the field,
    so a decision cannot say which published revision authorized the STOP.
    """
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv, "precondition: the STOP must reach the OCI boundary"
    assert _revision_is_bound(run.records[0], REVISION), (
        f"decision record does not name the publication revision {REVISION} the reaper consumed for {ENV}; "
        f"record={run.raw_records[0]}"
    )


# Retired contradictory legacy oracles: the receipt controls below cover default
# identifier absence, explicit reader propagation, and already-converged STOP.


# --------------------------------------------------------------------------------------------
# PROPOSED: per-STOP lifecycle-action receipts. Each STOP decision carries the publication the
# fence actually consumed (revision, generation, exact bytes), the actuation outcome, and only the
# OCI identifiers an action response exposes. Absent identifiers are null with a missing reason.
# Interface-independent: every assertion reads the decision record that DecisionLogStore wrote.
# --------------------------------------------------------------------------------------------

GENERATION_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
RECEIPT_NULL_IDENTITY_FIELDS = (
    "caller_request_id",
    "audit_request_id",
    "audit_event_id",
    "audit_principal_id",
)


def _stop_receipts(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [receipt for receipt in record.get("lifecycle_receipts", []) if receipt.get("action") == "STOP"]


def _missing_fields(receipt: dict[str, Any]) -> set[str]:
    return {entry["field"] for entry in receipt.get("missing_reasons", [])}


def _as_generation_record(stat: tuple[int, int, int, int]) -> dict[str, int]:
    return dict(zip(GENERATION_FIELDS, stat, strict=True))


def _fake_action_request_id(stdout: str, stderr: str) -> str | None:
    """Test-only response-identifier reader: the fake prints ``opc-req-<id>`` on an action's stderr."""
    match = re.search(rf"^{REQUEST_ID_PREFIX}(\S+)$", stderr, re.MULTILINE)
    return None if match is None else match.group(1)


def _actuator(**kwargs: Any) -> OciCliStopActuator:
    return OciCliStopActuator(oci_bin=FAKE_OCI_BIN, timeout_seconds=5, **kwargs)


def test_stop_receipt_records_actual_consumed_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    publication = _publish(load_dir, ENV, revision=REVISION)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv, "precondition: the STOP must reach the OCI boundary"
    assert len(run.consumed) == 1 and len(run.records) == 1
    receipts = _stop_receipts(run.records[0])
    assert len(receipts) == 1, f"expected exactly one STOP receipt; record={run.raw_records[0]}"
    receipt = receipts[0]
    assert receipt["decision_id"] == run.records[0]["decision_id"]
    assert receipt["instance_id"] == INSTANCE_ID
    assert receipt["outcome"] == "issued"
    assert receipt["command_invoked"] is True
    assert receipt["final_state"] == "STOPPING", "final state is the action response's own lifecycle-state"
    (consumed,) = receipt["consumed_load"]
    assert consumed["environment"] == ENV
    assert consumed["revision"] == REVISION
    assert consumed["generation"] == _as_generation_record(dict(run.consumed[0])[ENV])
    assert consumed["publication_artifact_sha256"] == hashlib.sha256(publication.read_bytes()).hexdigest()


def test_already_converged_stop_records_no_action_rpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.state = "STOPPED"

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv == [], "convergence must not issue a STOP request"
    assert len(run.records) == 1
    (receipt,) = _stop_receipts(run.records[0])
    assert receipt["outcome"] == "already_converged"
    assert receipt["command_invoked"] is False
    assert receipt["final_state"] == "STOPPED"
    assert receipt["oci_response_request_id"] is None
    for field_name in RECEIPT_NULL_IDENTITY_FIELDS:
        assert receipt[field_name] is None, f"{field_name} must not be fabricated for a converged STOP"
    (consumed,) = receipt["consumed_load"]
    assert consumed["revision"] == REVISION
    assert consumed["generation"] is not None


def test_waiter_get_is_not_action_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.state = "STOPPED"
    fake_oci.get_request_id = "WAITER-GET-9"
    actuator = _actuator(response_request_id_reader=_fake_action_request_id)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci, actuator=actuator)

    assert fake_oci.get_argv, "precondition: the convergence check must issue a GET"
    assert fake_oci.action_argv == []
    (receipt,) = _stop_receipts(run.records[0])
    assert receipt["outcome"] == "already_converged"
    assert receipt["oci_response_request_id"] is None, "a waiter GET identifier is never an action receipt"
    assert "WAITER-GET-9" not in run.raw_records[0]


def test_missing_oci_response_id_remains_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """Default actuator has no response-identifier reader: exposure of the CLI field is unverified."""
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.request_id = "STOP-7731"

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv, "precondition: the STOP must reach the OCI boundary"
    (receipt,) = _stop_receipts(run.records[0])
    assert receipt["outcome"] == "issued"
    assert receipt["oci_response_request_id"] is None
    assert "oci_response_request_id" in _missing_fields(receipt), "absent identifier must be an explicit gap"
    assert "STOP-7731" not in run.raw_records[0], "an unread identifier must not leak into the record"


def test_action_response_identifier_joins_only_through_the_action_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.request_id = "STOP-7731"
    actuator = _actuator(response_request_id_reader=_fake_action_request_id)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci, actuator=actuator)

    (receipt,) = _stop_receipts(run.records[0])
    assert receipt["oci_response_request_id"] == "STOP-7731"
    assert "oci_response_request_id" not in _missing_fields(receipt)


def test_refused_fence_records_fenced_off_receipt_without_consumed_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)

    def publisher_replaces_snapshot() -> None:
        _publish(load_dir, ENV, revision=REVISION + 1)

    run = _reap(
        tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci, before_fence_sample=publisher_replaces_snapshot
    )

    assert fake_oci.action_argv == []
    (receipt,) = _stop_receipts(run.records[0])
    assert receipt["outcome"] == "fenced_off"
    assert receipt["command_invoked"] is False
    assert receipt["consumed_load"] == [], "a refused fence consumed no publication"
    assert "consumed_load" in _missing_fields(receipt)


def test_failed_stop_action_is_failed_not_converged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.action_fails = True

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert len(fake_oci.action_argv) == 1, "the failing action was invoked once"
    (receipt,) = _stop_receipts(run.records[0])
    assert receipt["outcome"] == "failed"
    assert receipt["command_invoked"] is True
    assert receipt["final_state"] is None
    assert receipt["oci_response_request_id"] is None


def test_lease_cap_stop_receipt_is_emergency_not_idle_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)

    run = _reap(
        tmp_path,
        monkeypatch,
        load_dir=load_dir,
        fake=fake_oci,
        instances=[_running(idle_seconds=7200)],
        max_lease_seconds=3600,
    )

    assert fake_oci.action_argv, "precondition: the lease-cap STOP must reach the OCI boundary"
    lease_receipts = [r for r in run.records[0].get("lifecycle_receipts", []) if r.get("reason_code") == "lease_cap"]
    (receipt,) = lease_receipts
    assert receipt["action"] == "STOP"
    assert receipt["outcome"] == "issued"
    assert receipt["consumed_load"] == [], "the lease cap bypasses the publication fence"
    assert "consumed_load" in _missing_fields(receipt)


def test_fence_consumed_publication_is_read_under_the_producer_lock(tmp_path: Path) -> None:
    """Proposal interface: the fence reads the consumed bytes while every producer lock is held."""
    publication = _publish(tmp_path, ENV, revision=REVISION)
    source = AggregateJobLoadSource(directory=tmp_path, stale_seconds=120.0, expected_environments=(ENV,))
    generation = source.fence_token()
    lock_path = tmp_path / ENV / "describe-load.json.lock"
    lock_held_during_action: list[bool] = []

    def action() -> None:
        fd = os.open(lock_path, os.O_RDONLY)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock_held_during_action.append(True)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    fenced, publications = source.actuate_recorded_if_generation(generation, action)

    assert fenced is True
    assert lock_held_during_action == [True]
    (consumed,) = publications
    assert consumed.environment == ENV
    assert consumed.revision == REVISION
    assert consumed.generation == dict(generation)[ENV]
    assert consumed.sha256 == hashlib.sha256(publication.read_bytes()).hexdigest()


def test_consumed_publication_bytes_are_retained_by_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """The receipt's digest must name retained bytes: exact consumed publication, addressable from the log."""
    load_dir = tmp_path / "load"
    publication = _publish(load_dir, ENV, revision=REVISION)

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    (receipt,) = _stop_receipts(run.records[0])
    (consumed,) = receipt["consumed_load"]
    relative = consumed["publication_artifact_path"]
    assert isinstance(relative, str) and not Path(relative).is_absolute() and ".." not in Path(relative).parts
    retained = tmp_path / relative
    assert retained.read_bytes() == publication.read_bytes(), "retained bytes must equal the bytes read under the fence"
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == consumed["publication_artifact_sha256"]
    assert not any(name.endswith("publication_artifact_path") for name in _missing_fields(receipt))


def test_unretained_publication_bytes_are_an_explicit_gap_not_a_silent_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """A retention failure is surfaced in the record; it does not pretend the bytes were kept."""
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    (tmp_path / "lifecycle-receipts").write_text("not a directory", encoding="utf-8")

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert len(fake_oci.action_argv) == 1, "retention failure is audit-grade; it must not refuse the STOP"
    (receipt,) = _stop_receipts(run.records[0])
    (consumed,) = receipt["consumed_load"]
    assert consumed["publication_artifact_path"] is None
    assert f"consumed_load.{ENV}.publication_artifact_path" in _missing_fields(receipt)
    assert any("retain" in error for error in run.records[0]["errors"]), run.records[0]["errors"]
