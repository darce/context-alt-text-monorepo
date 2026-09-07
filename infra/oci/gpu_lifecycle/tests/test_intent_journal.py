"""The operator grant must be fenced, durable, and reconstructable.

Each test here names the defect it pins:

* GPUOPS-1-CANON-04 (RES-10) -- the grant's only authority was the wall clock,
  so a backwards NTP correction re-armed a dead `start`.
* GPUOPS-1-CANON-03 (RES-17) -- the write-ahead record lived on tmpfs and did
  not survive the reboot that its durable half (the running lease) did.
* GPUOPS-1-CANON-08 (HAI-06) -- `requested_by` was clobbered by the next POST
  and no outcome was kept, so "who started the A10 at 03:00?" was unanswerable.
* GPUOPS-1-CANON-06 (FLOW-08) -- a deferred stop expired silently and the GPU
  ran to the lease cap with no drop counter and no correction event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.hostclock import BootIdentityUnavailableError
from infra.oci.gpu_lifecycle.intent import (
    MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS,
    IntentAction,
    IntentStatus,
    read_effective_intent,
)
from infra.oci.gpu_lifecycle.intent_journal import (
    CorruptIntentJournalError,
    IntentJournal,
    JournalRecordKind,
)
from infra.oci.gpu_lifecycle.reaper import StaticJobLoadSource, run_reap_cycle

NOW = datetime(2026, 9, 6, 22, 30, tzinfo=UTC)
BOOT_ID = "journal-test-boot"
NONCE = "123e4567-e89b-42d3-a456-426614174000"
TTL_SECONDS = 1800


class _Clock:
    """A wall clock and a monotonic clock that can be moved independently."""

    def __init__(self, *, wall: datetime = NOW, monotonic: float = 1000.0) -> None:
        self.wall = wall
        self.monotonic = monotonic

    def advance(self, seconds: float) -> None:
        self.wall = self.wall + timedelta(seconds=seconds)
        self.monotonic += seconds


@dataclass
class RecordingActuator:
    started: list[str]
    stopped: list[str]

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)

    def stop_instance(self, instance_id: str) -> None:
        self.stopped.append(instance_id)


def _write_intent(
    root: Path,
    *,
    action: str = "start",
    requested_at: datetime = NOW,
    nonce: str = NONCE,
    requested_by: str = "operator@example.test",
    ttl_seconds: int = TTL_SECONDS,
    environment: str = "prod",
) -> Path:
    path = root / environment / "gpu-intent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "action": action,
                "requested_at": requested_at.isoformat(),
                "expires_at": (requested_at + timedelta(seconds=ttl_seconds)).isoformat(),
                "ttl_seconds": ttl_seconds,
                "requested_by": requested_by,
                "nonce": nonce,
            }
        ),
        encoding="utf-8",
    )
    return path


def _journal(path: Path, clock: _Clock, *, boot_id: str = BOOT_ID, **kwargs: object) -> IntentJournal:
    return IntentJournal(
        path=path,
        boot_id=boot_id,
        monotonic=lambda: clock.monotonic,
        now=lambda: clock.wall,
        **kwargs,  # type: ignore[arg-type]
    )


# --- GPUOPS-1-CANON-04: the grant needs a fence, not a wall clock ------------


def test_backwards_clock_cannot_rearm_a_spent_start_grant(tmp_path: Path) -> None:
    """The defect: a backwards NTP step revives the arm that disables the cost cap."""
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="start")
    clock = _Clock()
    journal = _journal(tmp_path / "intent-journal.jsonl", clock)

    armed = read_effective_intent(intent_dir, clock.wall, fence=journal)
    assert armed.action is IntentAction.START

    # The grant runs its full TTL and is spent.
    clock.advance(TTL_SECONDS + 30)
    spent = read_effective_intent(intent_dir, clock.wall, fence=journal)
    assert spent.action is IntentAction.AUTO
    assert spent.status is IntentStatus.EXPIRED

    # NTP steps the wall clock back 90s -- inside the reader's own future-skew
    # allowance, so `requested_at` still looks sane while `expires_at` is once
    # again in the future. The wall-clock-only reader re-arms START. The
    # monotonic origin did not move, and the nonce is burned.
    assert MAX_INTENT_REQUESTED_AT_FUTURE_SKEW_SECONDS + 90 > 90
    clock.wall = clock.wall - timedelta(seconds=90)
    assert read_effective_intent(intent_dir, clock.wall).action is IntentAction.START
    resurrected = read_effective_intent(intent_dir, clock.wall, fence=journal)
    assert resurrected.action is IntentAction.AUTO, "a backwards clock re-armed a spent grant"
    assert resurrected.status is IntentStatus.EXPIRED
    assert "spent" in (resurrected.reason or "")


def test_monotonic_expiry_wins_even_while_the_wall_clock_says_unexpired(tmp_path: Path) -> None:
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="start")
    clock = _Clock()
    journal = _journal(tmp_path / "intent-journal.jsonl", clock)
    assert read_effective_intent(intent_dir, clock.wall, fence=journal).action is IntentAction.START

    # Only the monotonic clock advances: the host's wall clock is stuck.
    clock.monotonic += TTL_SECONDS + 1
    verdict = read_effective_intent(intent_dir, clock.wall, fence=journal)
    assert verdict.action is IntentAction.AUTO
    assert verdict.status is IntentStatus.EXPIRED
    assert "burned" in (verdict.reason or "")


def test_wall_clock_expiry_refuses_the_grant_without_burning_it(tmp_path: Path) -> None:
    """A forward clock jump must not spend a grant the trustworthy origin still holds."""
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="start")
    clock = _Clock()
    journal = _journal(tmp_path / "intent-journal.jsonl", clock)
    assert read_effective_intent(intent_dir, clock.wall, fence=journal).action is IntentAction.START

    clock.wall = clock.wall + timedelta(seconds=TTL_SECONDS + 60)
    refused = read_effective_intent(intent_dir, clock.wall, fence=journal)
    assert refused.action is IntentAction.AUTO
    kinds = {record.kind for record in journal.history(NONCE)}
    assert JournalRecordKind.BURNED not in kinds


# --- GPUOPS-1-CANON-03: the record must be durable and explain itself --------


def test_reboot_revokes_the_grant_loudly_instead_of_silently_reverting(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    intent_dir = tmp_path / "run"
    journal_path = tmp_path / "intent-journal.jsonl"
    _write_intent(intent_dir, action="start", requested_by="demo-operator")
    clock = _Clock()
    assert read_effective_intent(intent_dir, clock.wall, fence=_journal(journal_path, clock)).action is (
        IntentAction.START
    )

    # The backend reboots. The tmpfs intent would normally be gone, but the
    # durable half survives, so this pins the worse case: the file is still
    # there and only the monotonic origin is lost.
    after_reboot = _journal(journal_path, clock, boot_id="boot-after-reboot")
    with caplog.at_level("ERROR"):
        revoked = read_effective_intent(intent_dir, clock.wall, fence=after_reboot)

    assert revoked.action is IntentAction.AUTO
    assert "demo-operator" in caplog.text
    assert "reboot" in caplog.text
    burned = [record for record in after_reboot.history(NONCE) if record.kind is JournalRecordKind.BURNED]
    assert burned, "the reboot revocation must leave a durable record to replay"


def test_the_journal_survives_the_tmpfs_intent_file(tmp_path: Path) -> None:
    """The write-ahead record outlives the file it describes (RES-17)."""
    intent_dir = tmp_path / "run"
    journal_path = tmp_path / "intent-journal.jsonl"
    intent_path = _write_intent(intent_dir, action="start", requested_by="first-operator")
    clock = _Clock()
    journal = _journal(journal_path, clock)
    read_effective_intent(intent_dir, clock.wall, fence=journal)

    intent_path.unlink()
    assert read_effective_intent(intent_dir, clock.wall, fence=journal).action is IntentAction.AUTO
    observed = [record for record in journal.history(NONCE) if record.kind is JournalRecordKind.OBSERVED]
    assert [record.requested_by for record in observed] == ["first-operator"]


# --- GPUOPS-1-CANON-08: reconstruct the decision that spent the money --------


def test_requested_by_is_not_clobbered_by_the_next_publication(tmp_path: Path) -> None:
    intent_dir = tmp_path / "run"
    journal = _journal(tmp_path / "intent-journal.jsonl", clock := _Clock())

    _write_intent(intent_dir, action="start", requested_by="alice", nonce=NONCE)
    read_effective_intent(intent_dir, clock.wall, fence=journal)
    clock.advance(60)
    second_nonce = "123e4567-e89b-42d3-a456-426614174001"
    _write_intent(intent_dir, action="stop", requested_by="bob", nonce=second_nonce, requested_at=clock.wall)
    read_effective_intent(intent_dir, clock.wall, fence=journal)

    requesters = {record.nonce: record.requested_by for record in journal.history()}
    assert requesters[NONCE] == "alice"
    assert requesters[second_nonce] == "bob"


def test_reap_cycle_records_who_asked_and_what_the_controller_did(tmp_path: Path) -> None:
    intent_dir = tmp_path / "run"
    journal_path = tmp_path / "intent-journal.jsonl"
    _write_intent(intent_dir, action="stop", requested_by="night-operator")
    clock = _Clock()
    journal = _journal(journal_path, clock)
    actuator = RecordingActuator([], [])

    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance(instance_id="ocid1.gpu", state="RUNNING", idle_for_seconds=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=actuator,
        fence_delay_seconds=0,
        use_recorded_lease_age=False,
        gpu_state_path=tmp_path / "gpu-state.json",
        intent_dir=intent_dir,
        intent_journal=journal,
        now=clock.wall,
    )

    assert result.intent.action is IntentAction.STOP
    assert actuator.stopped == ["ocid1.gpu"]
    cycles = [record for record in journal.history(NONCE) if record.kind is JournalRecordKind.CYCLE]
    assert len(cycles) == 1
    assert cycles[0].requested_by == "night-operator"
    assert cycles[0].payload is not None
    assert cycles[0].payload["mode"] == "reap"
    assert cycles[0].payload["actuated"] == [["STOP", "ocid1.gpu"]]


def test_an_auto_cycle_with_no_grant_does_not_evict_the_records_that_matter(tmp_path: Path) -> None:
    journal = _journal(tmp_path / "intent-journal.jsonl", _Clock())
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance(instance_id="ocid1.gpu", state="RUNNING", idle_for_seconds=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=RecordingActuator([], []),
        fence_delay_seconds=0,
        use_recorded_lease_age=False,
        gpu_state_path=tmp_path / "gpu-state.json",
        intent_journal=journal,
    )
    assert journal.history() == []


# --- GPUOPS-1-CANON-06: a deferred stop must be re-armed or reported ---------


def _defer_stop(journal: IntentJournal, intent_dir: Path, clock: _Clock) -> None:
    """Run one reap cycle whose stop is blocked by in-flight work."""
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=[GpuInstance(instance_id="ocid1.gpu", state="RUNNING", idle_for_seconds=90)],
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=3),
        actuator=RecordingActuator([], []),
        fence_delay_seconds=0,
        use_recorded_lease_age=False,
        gpu_state_path=intent_dir.parent / "gpu-state.json",
        intent_dir=intent_dir,
        intent_journal=journal,
        now=clock.wall,
    )


def test_a_deferred_stop_is_rearmed_past_its_wall_clock_expiry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="stop", requested_by="demo-operator")
    clock = _Clock()
    journal = _journal(tmp_path / "intent-journal.jsonl", clock, deferred_stop_rearm_seconds=3600.0)

    _defer_stop(journal, intent_dir, clock)
    assert any(record.kind is JournalRecordKind.DEFERRED for record in journal.history(NONCE))

    # The describe run outlives the intent TTL.
    clock.advance(TTL_SECONDS + 300)
    with caplog.at_level("WARNING"):
        rearmed = read_effective_intent(intent_dir, clock.wall, fence=journal)

    assert rearmed.action is IntentAction.STOP, "the operator's stop was dropped at its TTL"
    assert "re-armed" in caplog.text
    assert any(record.kind is JournalRecordKind.REARMED for record in journal.history(NONCE))


def test_an_undeferred_stop_still_expires_at_its_ttl(tmp_path: Path) -> None:
    """Re-arming is the late-event policy for a *deferred* stop only."""
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="stop")
    clock = _Clock()
    journal = _journal(tmp_path / "intent-journal.jsonl", clock)
    read_effective_intent(intent_dir, clock.wall, fence=journal)

    clock.advance(TTL_SECONDS + 1)
    assert read_effective_intent(intent_dir, clock.wall, fence=journal).action is IntentAction.AUTO


def test_an_exhausted_rearm_budget_drops_the_stop_loudly_and_durably(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="stop", requested_by="demo-operator")
    clock = _Clock()
    journal = _journal(tmp_path / "intent-journal.jsonl", clock, deferred_stop_rearm_seconds=600.0)

    _defer_stop(journal, intent_dir, clock)
    clock.advance(TTL_SECONDS + 601)
    with caplog.at_level("WARNING"):
        dropped = read_effective_intent(intent_dir, clock.wall, fence=journal)

    assert dropped.action is IntentAction.AUTO
    assert dropped.status is IntentStatus.EXPIRED
    assert "dropped" in caplog.text
    assert "demo-operator" in caplog.text
    records = [record for record in journal.history(NONCE) if record.kind is JournalRecordKind.DROPPED]
    assert len(records) == 1
    # A dropped grant is spent: it must not come back on a later cycle.
    clock.advance(60)
    assert read_effective_intent(intent_dir, clock.wall, fence=journal).action is IntentAction.AUTO


# --- structural integrity ---------------------------------------------------


def test_a_corrupt_journal_refuses_the_grant_instead_of_defaulting_open(tmp_path: Path) -> None:
    """rg-008: fail fast on structural damage, never silently return empty."""
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="start")
    journal_path = tmp_path / "intent-journal.jsonl"
    journal = _journal(journal_path, clock := _Clock())
    read_effective_intent(intent_dir, clock.wall, fence=journal)

    journal_path.write_text("{not json}\n" + journal_path.read_text(encoding="utf-8"), encoding="utf-8")
    refused = read_effective_intent(intent_dir, clock.wall, fence=journal)
    assert refused.action is IntentAction.AUTO
    assert "fence" in (refused.reason or "") or "journal" in (refused.reason or "")
    with pytest.raises(CorruptIntentJournalError):
        journal.history()


def test_a_torn_trailing_line_is_tolerated(tmp_path: Path) -> None:
    """A crash mid-append is the one corruption the journal expects."""
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="start")
    journal_path = tmp_path / "intent-journal.jsonl"
    journal = _journal(journal_path, clock := _Clock())
    read_effective_intent(intent_dir, clock.wall, fence=journal)

    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version": 1, "kind": "cyc')
    assert read_effective_intent(intent_dir, clock.wall, fence=journal).action is IntentAction.START


def test_the_journal_is_bounded(tmp_path: Path) -> None:
    """rg-007: an unattended host must not fill /var with lifecycle history."""
    journal = _journal(tmp_path / "intent-journal.jsonl", _Clock(), max_records=5)
    for index in range(20):
        journal._append(JournalRecordKind.CYCLE, nonce=f"nonce-{index}")
    assert len(journal.history()) == 5


def test_a_fence_that_raises_revokes_the_grant(tmp_path: Path) -> None:
    intent_dir = tmp_path / "run"
    _write_intent(intent_dir, action="start")

    class ExplodingFence:
        def evaluate(self, intent, *, wall_clock_expired, now):  # noqa: ANN001, ANN202
            raise RuntimeError("journal filesystem is read-only")

    refused = read_effective_intent(intent_dir, NOW, fence=ExplodingFence())
    assert refused.action is IntentAction.AUTO
    assert "grant refused" in (refused.reason or "")


def test_a_journal_without_a_boot_identity_fails_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_text = Path.read_text

    def read_text(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if str(path) == "/proc/sys/kernel/random/boot_id":
            raise OSError("simulated host without Linux boot identity")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(BootIdentityUnavailableError):
        IntentJournal(path=tmp_path / "intent-journal.jsonl")


def test_invalid_journal_configuration_is_rejected_at_construction(tmp_path: Path) -> None:
    for kwargs in (
        {"max_records": 0},
        {"deferred_stop_rearm_seconds": -1.0},
        {"deferred_stop_rearm_seconds": float("inf")},
        {"lock_timeout_seconds": -1.0},
        {"boot_id": " "},
    ):
        with pytest.raises(ValueError):
            IntentJournal(path=tmp_path / "intent-journal.jsonl", **{"boot_id": BOOT_ID, **kwargs})
