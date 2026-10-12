"""G3 causal joins for describe demand and the GPU load publication (scene package).

Authoring rules for this file:

* Producers are real. ``DescribeOperationRepository.accept`` commits demand leases,
  ``load_snapshot`` allocates the publication revision and counts demand in one transaction, and
  ``write_load_snapshot`` publishes the native JSON file the reaper reads.
* The database is an in-memory SQLite engine with the production table definitions, the same
  harness as the existing describe-load suite. No Postgres, no RLS, no GPU, no OCI, no host path.
* The ground truth is an independent query over committed lease rows, evaluated in Python with the
  same clock the producer receives and before the producer runs. CONTROL tests prove that this
  query matches the producer's own ``lease_demand`` count, so the join oracle is not a copy of the
  producer's SQL.

RED tests name the operation-to-revision join the producer does not export. Today the publication
file is overwritten on every revision, the revision table keeps only the latest value, and no
operation or lease row names the revision that first counted it. A "latest global revision" join
would therefore misattribute an earlier operation to a later publication. Each RED asserts that a
persisted artifact carries the first-counting binding, whatever its encoding, as long as the operation
and the revision appear in the same record.

Typed missing-interface proposal (not imported here, so its absence is not a behavior defect): the
publish transaction persists, for each operation it counts, the revision that counted it. The
attribution is that first revision, derived from the same committed transaction, never the latest
global revision.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import (
    DescribeDemandLease,
    DescribeOperation,
    DescribeRun,
    DescribeRunItem,
    DescribeStartup,
)
from scene.application.describe_load import load_snapshot, write_load_snapshot
from scene.application.describe_operation_repository import DescribeOperationRepository
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DemandLeaseState

LEASE_SECONDS = 180.0
REVISION_BASE = 4096  # reseed above any small literal so a revision value cannot collide with a count
DIGEST = "d" * 64
INSTANCE_ID = "ocid1.instance.oc1..gtmrscene"
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Publication:
    revision: int
    lease_demand: int
    counted: frozenset[str]
    snapshot: dict[str, Any]


class Harness:
    """A fresh in-memory database with the production describe tables, plus a native publication path."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.publication_path = tmp_path / "describe-load.json"
        self.gpu_state_path = tmp_path / "gpu-state.json"
        monkeypatch.setenv("ACX_GPU_STATE_PATH", str(self.gpu_state_path))
        monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(tmp_path / "no-intent" / "gpu-intent.json"))
        monkeypatch.setenv("ACX_GPU_INTENT_DURABLE_PATH", str(tmp_path / "no-intent-durable" / "gpu-intent.json"))
        self.engine: AsyncEngine | None = None
        self.sessions: async_sessionmaker | None = None

    async def open(self) -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(
                    list[Table],
                    [
                        DescribeStartup.__table__,
                        DescribeOperation.__table__,
                        DescribeDemandLease.__table__,
                        DescribeRun.__table__,
                        DescribeRunItem.__table__,
                    ],
                ),
            )
            await conn.execute(
                text(
                    "CREATE TABLE describe_load_snapshot_revisions ("
                    "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                    "revision INTEGER NOT NULL)"
                )
            )
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    def _publish_gpu_state(self, now: datetime) -> None:
        """A fresh STOPPED lifecycle state, so demand is neither blocked nor excluded by GPU policy."""
        self.gpu_state_path.write_text(
            json.dumps(
                {
                    "state": "stopped",
                    "instance_id": INSTANCE_ID,
                    "written_at": now.timestamp(),
                    "reason": None,
                }
            ),
            encoding="utf-8",
        )

    async def accept(self, *, tenant_id: uuid.UUID, operation_id: str, now: datetime) -> None:
        assert self.sessions is not None
        async with self.sessions() as session:
            await DescribeOperationRepository(session, lease_seconds=LEASE_SECONDS).accept(
                tenant_id=tenant_id,
                request_digest=DIGEST,
                operation_id=operation_id,
                now=now,
            )
            await session.commit()

    async def publish(self, *, now: datetime, minimum_revision: int) -> Publication:
        """Count demand with the real producer, publish the real file, and return the independent oracle."""
        assert self.sessions is not None
        self._publish_gpu_state(now)
        counted = await _counted_by_independent_query(self.sessions, now=now)
        async with self.sessions() as session:
            snapshot = await load_snapshot(session, now=now, minimum_revision=minimum_revision)
        write_load_snapshot(snapshot, self.publication_path)
        return Publication(
            revision=int(snapshot["revision"]),
            lease_demand=int(snapshot["lease_demand"]),
            counted=counted,
            snapshot=snapshot,
        )

    async def persisted_bindings(
        self,
        *,
        operation_ids: set[str],
        revisions: set[int],
    ) -> dict[str, set[int]]:
        """Operation-to-revision pairs carried by one persisted record (a JSON object or a DB row)."""
        assert self.engine is not None
        bindings: dict[str, set[int]] = {}

        def bind(scalars: list[object]) -> None:
            operations = {value for value in scalars if isinstance(value, str) and value in operation_ids}
            found = {
                value
                for value in scalars
                if isinstance(value, int) and not isinstance(value, bool) and value in revisions
            }
            if not found:
                return
            for operation in operations:
                bindings.setdefault(operation, set()).update(found)

        if self.publication_path.exists():
            payload = json.loads(self.publication_path.read_text(encoding="utf-8"))
            for record in _objects(payload):
                bind(list(_scalars(record)))
        async with self.engine.connect() as conn:
            tables = [
                row[0]
                for row in (await conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))).all()
            ]
            for table in tables:
                for row in (await conn.execute(text(f'SELECT * FROM "{table}"'))).all():
                    bind(list(row))
        return bindings


def _objects(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _scalars(value: object) -> Iterator[object]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _scalars(item)
    elif isinstance(value, list):
        for item in value:
            yield from _scalars(item)
    else:
        yield value


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _counted_by_independent_query(sessions: async_sessionmaker, *, now: datetime) -> frozenset[str]:
    """Operations whose demand must be counted at ``now``: active, unexpired, and both rows retained.

    Written from the lease semantics and evaluated in Python. It is not the producer's SQL.
    """
    async with sessions() as session:
        rows = (
            await session.execute(
                select(
                    DescribeDemandLease.operation_id,
                    DescribeDemandLease.state,
                    DescribeDemandLease.expires_at,
                    DescribeDemandLease.retain_until,
                    DescribeOperation.retain_until,
                ).join(
                    DescribeOperation,
                    (DescribeDemandLease.tenant_id == DescribeOperation.tenant_id)
                    & (DescribeDemandLease.operation_id == DescribeOperation.operation_id),
                )
            )
        ).all()
    counted = set()
    for operation_id, state, expires_at, lease_retain_until, operation_retain_until in rows:
        if (
            state == DemandLeaseState.ACTIVE
            and _as_utc(expires_at) > now
            and _as_utc(lease_retain_until) > now
            and _as_utc(operation_retain_until) > now
        ):
            counted.add(operation_id)
    return frozenset(counted)


def _first_counting_revisions(publications: Sequence[Publication]) -> dict[str, int]:
    """Oracle: each operation attributes to the first publication whose transaction counted it."""
    first: dict[str, int] = {}
    for publication in publications:
        for operation_id in sorted(publication.counted):
            first.setdefault(operation_id, publication.revision)
    return first


def _latest_revision_join(publications: Sequence[Publication]) -> dict[str, int]:
    """The forbidden shortcut: attribute every counted operation to the latest global revision."""
    latest = publications[-1]
    return dict.fromkeys(latest.counted, latest.revision)


def _exported_first_revisions(bindings: dict[str, set[int]]) -> dict[str, int]:
    return {operation_id: min(revisions) for operation_id, revisions in bindings.items() if revisions}


def _ids(*values: str) -> set[str]:
    return set(values)


# --------------------------------------------------------------------------------------------
# CONTROL: behavior that exists today and must survive the join change.
# --------------------------------------------------------------------------------------------


def test_control_counted_demand_matches_the_independent_lease_predicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(tmp_path, monkeypatch)

    async def scenario() -> Publication:
        await harness.open()
        try:
            operation = uuid.uuid4().hex
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=operation, now=T0)
            return await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
        finally:
            await harness.close()

    publication = asyncio.run(scenario())

    assert publication.lease_demand == len(publication.counted) == 1
    assert publication.snapshot["in_flight"] == publication.lease_demand
    assert publication.revision == REVISION_BASE + 1


def test_control_pre_existing_expired_demand_is_neither_counted_nor_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    expired = uuid.uuid4().hex
    live = uuid.uuid4().hex

    async def scenario() -> tuple[Publication, dict[str, set[int]]]:
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=expired, now=T0 - timedelta(seconds=600))
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=live, now=T0)
            publication = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            bindings = await harness.persisted_bindings(
                operation_ids=_ids(expired, live), revisions={publication.revision}
            )
            return publication, bindings
        finally:
            await harness.close()

    publication, bindings = asyncio.run(scenario())

    assert publication.counted == frozenset({live})
    assert publication.lease_demand == 1
    assert expired not in bindings, "an expired lease from before the publication must not be attributed to it"


def test_control_equal_or_older_publication_cannot_replace_the_consumed_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(tmp_path, monkeypatch)

    async def scenario() -> tuple[Publication, Publication, str, str]:
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=uuid.uuid4().hex, now=T0)
            first = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=uuid.uuid4().hex, now=T0 + timedelta(seconds=2))
            second = await harness.publish(now=T0 + timedelta(seconds=3), minimum_revision=first.revision)
            consumed = harness.publication_path.read_text(encoding="utf-8")
            write_load_snapshot(first.snapshot, harness.publication_path)
            after_older = harness.publication_path.read_text(encoding="utf-8")
            return first, second, consumed, after_older
        finally:
            await harness.close()

    first, second, consumed, after_older = asyncio.run(scenario())

    assert second.revision > first.revision
    assert json.loads(consumed)["revision"] == second.revision
    assert after_older == consumed, "an older revision must not replace the publication the reaper consumes"


def test_control_unexplained_bulk_work_creates_no_operation_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(tmp_path, monkeypatch)

    async def scenario() -> tuple[Publication, dict[str, set[int]]]:
        await harness.open()
        try:
            assert harness.sessions is not None
            async with harness.sessions() as session:
                await DescribeRunRepository(session).create_run(tenant_id=uuid.uuid4(), media_ids=[10, 11])
                await session.commit()
            publication = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            bindings = await harness.persisted_bindings(operation_ids=set(), revisions={publication.revision})
            return publication, bindings
        finally:
            await harness.close()

    publication, bindings = asyncio.run(scenario())

    assert publication.snapshot["batch_in_progress"] is True
    assert publication.lease_demand == 0
    assert bindings == {}


def test_control_latest_revision_shortcut_is_distinguishable_from_first_counting_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oracle sanity: the expected attribution must differ from the forbidden shortcut on real revisions."""
    harness = Harness(tmp_path, monkeypatch)
    first_operation = uuid.uuid4().hex

    async def scenario() -> list[Publication]:
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=first_operation, now=T0)
            first = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=uuid.uuid4().hex, now=T0 + timedelta(seconds=5))
            second = await harness.publish(now=T0 + timedelta(seconds=6), minimum_revision=first.revision)
            return [first, second]
        finally:
            await harness.close()

    publications = asyncio.run(scenario())

    expected = _first_counting_revisions(publications)
    shortcut = _latest_revision_join(publications)
    assert expected[first_operation] == publications[0].revision
    assert shortcut[first_operation] == publications[1].revision
    assert expected[first_operation] != shortcut[first_operation]


def test_control_join_scanner_detects_a_binding_persisted_in_a_row_or_in_the_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oracle sanity: the RED scanner must see a binding wherever one is persisted, or the RED is vacuous.

    Each mutation is test-only and in memory. The first adds a binding row to a probe table in the
    production-shaped SQLite fixture. The second adds an attribution record to the real publication
    file. Each then runs the same scanner and oracle the RED tests use.
    """
    operation = uuid.uuid4().hex

    async def row_binding() -> dict[str, set[int]]:
        harness = Harness(tmp_path / "row", monkeypatch)
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=operation, now=T0)
            publication = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            assert harness.engine is not None
            async with harness.engine.begin() as conn:
                await conn.execute(
                    text("CREATE TABLE gtmr_binding_probe (operation_id VARCHAR(128), revision INTEGER)")
                )
                await conn.execute(
                    text("INSERT INTO gtmr_binding_probe (operation_id, revision) VALUES (:op, :rev)"),
                    {"op": operation, "rev": publication.revision},
                )
            bindings = await harness.persisted_bindings(operation_ids={operation}, revisions={publication.revision})
            assert _exported_first_revisions(bindings) == {operation: publication.revision}
            return bindings
        finally:
            await harness.close()

    async def file_binding() -> dict[str, set[int]]:
        harness = Harness(tmp_path / "file", monkeypatch)
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=operation, now=T0)
            publication = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            harness.publication_path.write_text(
                json.dumps(
                    {
                        **publication.snapshot,
                        "attributions": [{"operation_id": operation, "revision": publication.revision}],
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            bindings = await harness.persisted_bindings(operation_ids={operation}, revisions={publication.revision})
            assert _exported_first_revisions(bindings) == {operation: publication.revision}
            return bindings
        finally:
            await harness.close()

    assert asyncio.run(row_binding()) == {operation: {REVISION_BASE + 1}}
    assert asyncio.run(file_binding()) == {operation: {REVISION_BASE + 1}}


# --------------------------------------------------------------------------------------------
# RED: the operation-to-revision join the producer does not export.
# --------------------------------------------------------------------------------------------


def test_red_committed_operation_is_bound_to_the_revision_that_first_counted_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed operation must be joinable to the publication revision whose transaction counted it.

    Producer today: ``load_snapshot`` commits the lease expiry and the revision in one transaction,
    but no operation or lease row stores that revision, and the publication file carries only
    aggregate counts (``lease_demand``), not operation identities.
    """
    harness = Harness(tmp_path, monkeypatch)
    operation = uuid.uuid4().hex

    async def scenario() -> tuple[Publication, dict[str, int]]:
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=operation, now=T0)
            publication = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            bindings = await harness.persisted_bindings(operation_ids={operation}, revisions={publication.revision})
            return publication, _exported_first_revisions(bindings)
        finally:
            await harness.close()

    publication, exported = asyncio.run(scenario())

    assert publication.counted == frozenset({operation}), "precondition: the operation must be counted"
    expected = {operation: publication.revision}
    assert exported == expected, (
        f"operation has no persisted binding to the revision that counted it: expected {expected}, exported "
        f"{exported}; publication={publication.snapshot}"
    )


def test_red_later_publication_keeps_each_operation_bound_to_its_first_counting_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later publication must not re-attribute an earlier operation to the latest revision.

    The expected binding comes from the publish sequence the real producer returned, not from a
    literal. The file is overwritten on the second publication, so the first binding must already
    be persisted somewhere that survives it.
    """
    harness = Harness(tmp_path, monkeypatch)
    first_operation = uuid.uuid4().hex
    second_operation = uuid.uuid4().hex

    async def scenario() -> tuple[list[Publication], dict[str, int]]:
        await harness.open()
        try:
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=first_operation, now=T0)
            first = await harness.publish(now=T0 + timedelta(seconds=1), minimum_revision=REVISION_BASE)
            await harness.accept(tenant_id=uuid.uuid4(), operation_id=second_operation, now=T0 + timedelta(seconds=5))
            second = await harness.publish(now=T0 + timedelta(seconds=6), minimum_revision=first.revision)
            bindings = await harness.persisted_bindings(
                operation_ids={first_operation, second_operation},
                revisions={first.revision, second.revision},
            )
            return [first, second], _exported_first_revisions(bindings)
        finally:
            await harness.close()

    publications, exported = asyncio.run(scenario())

    expected = _first_counting_revisions(publications)
    assert expected == {first_operation: publications[0].revision, second_operation: publications[1].revision}
    assert exported == expected, (
        "operations are not persisted with the revision that first counted them: "
        f"expected {expected}, exported {exported}; latest publication={publications[-1].snapshot}"
    )
