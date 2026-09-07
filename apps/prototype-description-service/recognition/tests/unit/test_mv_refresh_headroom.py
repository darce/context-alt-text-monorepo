from __future__ import annotations

import logging
from collections.abc import Iterable

import pytest

from shared.disk_headroom import DiskHeadroom, DiskHeadroomSettings
from shared.health import HealthStatus


class _FakeResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _FakeAutocommitConnection:
    def __init__(self, *, mv_bytes: int, counts: Iterable[int] = ()) -> None:
        self.mv_bytes = mv_bytes
        self.counts = iter(counts)
        self.executed: list[str] = []

    async def execute(self, statement, *args):  # noqa: ANN001
        del args
        sql = str(statement)
        self.executed.append(sql)
        if "pg_total_relation_size" in sql:
            return _FakeResult(self.mv_bytes)
        if "SELECT COUNT" in sql:
            return _FakeResult(next(self.counts, 0))
        return _FakeResult(0)


@pytest.fixture(autouse=True)
def reset_unguarded_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    import recognition.infrastructure.repositories.cluster_repository as cluster_repository

    monkeypatch.setattr(cluster_repository, "_UNGUARDED_REFRESH_WARNING_LOGGED", False)


def _probe(*, free_bytes: int, path: str = "/run/acx/pg-headroom") -> DiskHeadroom:
    return DiskHeadroom(
        probe_path=path,
        free_bytes=free_bytes,
        total_bytes=1_000,
        status=HealthStatus.OK,
        reason="test probe",
    )


@pytest.mark.asyncio
async def test_short_headroom_skips_refresh_and_resets_bypass(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    import recognition.infrastructure.repositories.cluster_repository as cluster_repository

    settings = DiskHeadroomSettings(probe_path="/run/acx/pg-headroom", min_bytes=100)
    monkeypatch.setattr(cluster_repository, "get_disk_headroom_settings", lambda: settings)
    monkeypatch.setattr(cluster_repository, "probe_disk_headroom", lambda _path: _probe(free_bytes=99))
    connection = _FakeAutocommitConnection(mv_bytes=40)

    with caplog.at_level(logging.WARNING, logger=cluster_repository.__name__):
        outcome = await cluster_repository._refresh_mv_concurrent_with_bypass(connection)

    assert outcome is cluster_repository.MvRefreshOutcome.SKIPPED_HEADROOM
    assert not any("REFRESH MATERIALIZED VIEW" in sql for sql in connection.executed)
    assert connection.executed[-1] == "RESET app.bypass_rls"
    warning = next(record.message for record in caplog.records if "Skipping refresh" in record.message)
    assert "free_bytes=99" in warning
    assert "required_bytes=100" in warning
    assert "mv_bytes=40" in warning
    assert "probe_path=/run/acx/pg-headroom" in warning


@pytest.mark.asyncio
async def test_enough_headroom_refreshes_and_returns_refreshed(monkeypatch: pytest.MonkeyPatch) -> None:
    import recognition.infrastructure.repositories.cluster_repository as cluster_repository

    settings = DiskHeadroomSettings(probe_path="/run/acx/pg-headroom", min_bytes=100)
    monkeypatch.setattr(cluster_repository, "get_disk_headroom_settings", lambda: settings)
    monkeypatch.setattr(cluster_repository, "probe_disk_headroom", lambda _path: _probe(free_bytes=100))
    connection = _FakeAutocommitConnection(mv_bytes=40, counts=[3, 4])

    outcome = await cluster_repository._refresh_mv_concurrent_with_bypass(connection)

    assert outcome is cluster_repository.MvRefreshOutcome.REFRESHED
    assert any("REFRESH MATERIALIZED VIEW CONCURRENTLY" in sql for sql in connection.executed)
    assert connection.executed[-1] == "RESET app.bypass_rls"


@pytest.mark.asyncio
async def test_disabled_guard_refreshes_and_warns_once(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    import recognition.infrastructure.repositories.cluster_repository as cluster_repository

    settings = DiskHeadroomSettings(probe_path=None, min_bytes=100)
    monkeypatch.setattr(cluster_repository, "get_disk_headroom_settings", lambda: settings)
    monkeypatch.setattr(
        cluster_repository,
        "probe_disk_headroom",
        lambda _path: (_ for _ in ()).throw(AssertionError("disabled guard must not probe")),
    )
    with caplog.at_level(logging.WARNING, logger=cluster_repository.__name__):
        first = await cluster_repository._refresh_mv_concurrent_with_bypass(
            first_connection := _FakeAutocommitConnection(mv_bytes=40, counts=[0, 0])
        )
        second = await cluster_repository._refresh_mv_concurrent_with_bypass(
            second_connection := _FakeAutocommitConnection(mv_bytes=40, counts=[0, 0])
        )

    assert first is cluster_repository.MvRefreshOutcome.REFRESHED
    assert second is cluster_repository.MvRefreshOutcome.REFRESHED
    assert not any("pg_total_relation_size" in sql for sql in first_connection.executed)
    assert not any("pg_total_relation_size" in sql for sql in second_connection.executed)
    warnings = [record for record in caplog.records if "without a disk-headroom guard" in record.message]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_repository_propagates_skipped_headroom_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    import recognition.infrastructure.repositories.cluster_repository as cluster_repository

    class _Connection(_FakeAutocommitConnection):
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def execution_options(self, **_options):
            return self

    class _Bind:
        def connect(self):
            return _Connection(mv_bytes=40)

    class _Session:
        bind = _Bind()

    monkeypatch.setattr(cluster_repository, "is_sqlite", lambda _session: False)
    monkeypatch.setattr(
        cluster_repository,
        "get_disk_headroom_settings",
        lambda: DiskHeadroomSettings(probe_path="/run/acx/pg-headroom", min_bytes=100),
    )
    monkeypatch.setattr(cluster_repository, "probe_disk_headroom", lambda _path: _probe(free_bytes=99))

    repo = cluster_repository.SqlAlchemyClusterRepository(_Session())

    outcome = await repo.refresh_centroids_view_concurrent()

    assert outcome is cluster_repository.MvRefreshOutcome.SKIPPED_HEADROOM


@pytest.mark.asyncio
async def test_repository_returns_failed_outcome_after_logged_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import recognition.infrastructure.repositories.cluster_repository as cluster_repository

    class _Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def execution_options(self, **_options):
            return self

    class _Bind:
        def connect(self):
            return _Connection()

    class _Session:
        bind = _Bind()

    async def _raise(_connection):
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(cluster_repository, "is_sqlite", lambda _session: False)
    monkeypatch.setattr(cluster_repository, "_refresh_mv_concurrent_with_bypass", _raise)

    repo = cluster_repository.SqlAlchemyClusterRepository(_Session())

    outcome = await repo.refresh_centroids_view_concurrent()

    assert outcome is cluster_repository.MvRefreshOutcome.FAILED
