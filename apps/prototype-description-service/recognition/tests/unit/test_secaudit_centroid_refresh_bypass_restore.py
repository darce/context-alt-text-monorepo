"""SECAUDIT-1: centroid refresh must not leak transaction-local RLS bypass."""

from types import SimpleNamespace

import pytest

from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def scalar_one(self):
        return self.value


class _RecordingSession:
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def __init__(self, previous, fail_refresh):
        self.previous = previous
        self.fail_refresh = fail_refresh
        self.calls = []

    def get_bind(self):
        return self.bind

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "current_setting" in sql:
            return _Result(self.previous)
        if sql.startswith("REFRESH") and self.fail_refresh:
            raise RuntimeError("refresh failed")
        return _Result(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [None, "", "false", "true"])
@pytest.mark.parametrize("fail_refresh", [False, True])
async def test_refresh_restores_previous_bypass(previous, fail_refresh):
    session = _RecordingSession(previous, fail_refresh)
    repo = SqlAlchemyClusterRepository(session)

    if fail_refresh:
        with pytest.raises(RuntimeError, match="refresh failed"):
            await repo.refresh_centroids_view()
    else:
        await repo.refresh_centroids_view()

    statements = [sql for sql, _ in session.calls]
    assert statements[0] == "SELECT current_setting('app.bypass_rls', true)"
    assert statements[1] == "SET LOCAL app.bypass_rls = 'true'"
    assert statements[2] == "REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"
    assert statements[3:-1] == ([] if fail_refresh else ["SELECT COUNT(*) FROM mv_identity_cluster_centroids"])
    assert session.calls[-1] == (
        "SELECT set_config('app.bypass_rls', :value, true)",
        {"value": previous or "false"},
    )
