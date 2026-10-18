"""Shared health-test seams."""

from __future__ import annotations


def install_healthy_observability_session(app) -> None:
    """Pool-aware liveness contract stub that keeps these assertions independent of a live database."""
    from unittest.mock import AsyncMock, MagicMock

    from db.settings import get_database_settings
    from recognition.interface_adapters.http import deps as dependencies

    dim = int(get_database_settings().pgvector_dimension)
    rows = [
        ("media_identities", "embedding", dim),
        ("identity_cluster_representatives", "embedding", dim),
        ("mv_identity_cluster_centroids", "centroid", dim),
    ]
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    class _NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    session.begin_nested = MagicMock(return_value=_NestedTransaction())

    async def _session_yielder():
        yield session

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder
