"""APP-1 bounded stale usage reservation sweep tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts.usage_reservation_sweeper import sweep_stale_reservations


@dataclass
class _Reservation:
    reservation_id: str


class _FakeRepository:
    def __init__(self, rows: list[_Reservation], *, release_count: int | None = None) -> None:
        self.rows = rows
        self.release_count = release_count
        self.list_calls: list[tuple[float, int]] = []
        self.released: list[list[_Reservation]] = []

    async def list_stale_reservations(self, stale_after_seconds: float, *, limit: int):
        self.list_calls.append((stale_after_seconds, limit))
        return self.rows[:limit]

    async def release_batch(self, rows: list[_Reservation]) -> int:
        self.released.append(rows)
        count = len(rows) if self.release_count is None else self.release_count
        if count:
            self.rows = self.rows[count:]
        return count


@pytest.mark.asyncio
async def test_sweeper_releases_stale_rows_in_bounded_batches() -> None:
    repository = _FakeRepository([_Reservation("one"), _Reservation("two"), _Reservation("three")])

    report = await sweep_stale_reservations(
        repository,
        max_batches=5,
        batch_size=2,
        stale_after_seconds=60,
    )

    assert report.stalled is False
    assert report.released == 3
    assert report.stale_seen == 3
    assert [batch[1] for batch in repository.list_calls] == [2, 2, 2]
    assert [row.reservation_id for batch in repository.released for row in batch] == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_sweeper_exits_non_zero_after_no_progress_cycles() -> None:
    repository = _FakeRepository([_Reservation("stuck")], release_count=0)

    report = await sweep_stale_reservations(
        repository,
        max_batches=10,
        batch_size=1,
        stale_after_seconds=60,
        no_progress_limit=3,
    )

    assert report.stalled is True
    assert report.exit_code == 1
    assert report.no_progress_cycles == 3
    assert len(repository.released) == 3


@pytest.mark.asyncio
async def test_sweeper_accepts_an_empty_repository_as_success() -> None:
    repository = _FakeRepository([])

    report = await sweep_stale_reservations(repository, max_batches=2, batch_size=5, stale_after_seconds=0)

    assert report.exit_code == 0
    assert report.batches == 1
    assert report.released == 0
