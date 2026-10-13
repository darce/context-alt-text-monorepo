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

import json
import os
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
    caller captured it. A STOP action moves the fake instance to STOPPED.
    """

    state: str = "RUNNING"
    request_id: str | None = None
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
            return subprocess.CompletedProcess(argv, 0, stdout=body if captured_out else None, stderr=None)
        if argv[1:4] == ["compute", "instance", "action"]:
            self.action_argv.append(argv)
            self.action_output_captured.append(captured_out or captured_err)
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
        actuator=OciCliStopActuator(oci_bin=FAKE_OCI_BIN, timeout_seconds=5),
        fence_delay_seconds=0,
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


def test_red_decision_record_carries_the_oci_actuation_response_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """The STOP's OCI response identifier must reach the decision so audit can join to the request.

    Producer today: ``OciCliStopActuator.stop_instance`` runs the action with ``subprocess.run(cmd,
    check=True, timeout=...)`` and no output capture, so the response is discarded before the
    decision is written. The fake's identifier is delivered only when the producer captures it.
    """
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.request_id = "STOP-7731"

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv, "precondition: the STOP must reach the OCI boundary"
    assert any(_request_id_is_bound(raw, "STOP-7731") for raw in run.raw_records), (
        "OCI STOP response identifier is absent from the decision record; "
        f"actuation output captured={fake_oci.action_output_captured}; records={run.raw_records}"
    )


def test_red_claimed_stop_must_match_an_issued_oci_action_when_instance_already_converged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_oci: FakeOciCli
) -> None:
    """A decision must not claim an honoured STOP that no OCI request produced.

    Producer today: the convergence check inside ``stop_instance`` returns without an action when
    OCI already reports STOPPED. ``_reap_stop_attempt`` treats the absence of an exception as
    actuation, so the record claims one honoured STOP while zero requests were issued. The claim is
    derived from a poll, not from an OCI actuation response.
    """
    load_dir = tmp_path / "load"
    _publish(load_dir, ENV, revision=REVISION)
    fake_oci.state = "STOPPED"

    run = _reap(tmp_path, monkeypatch, load_dir=load_dir, fake=fake_oci)

    assert fake_oci.action_argv == [], "precondition: the convergence check must issue no STOP request"
    claimed = _claimed_stops(run.records)
    assert claimed == len(fake_oci.action_argv), (
        f"decision claims {claimed} honoured STOP(s) but {len(fake_oci.action_argv)} OCI action request(s) "
        f"were issued; record={run.raw_records}"
    )
