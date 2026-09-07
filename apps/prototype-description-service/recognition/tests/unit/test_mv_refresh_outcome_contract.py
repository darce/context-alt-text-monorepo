"""The MV refresh outcome is a contract boundary, not a duck-typed value."""

from __future__ import annotations

import pytest

from recognition.domain.repositories import MvRefreshOutcome, require_mv_refresh_outcome


def test_require_mv_refresh_outcome_passes_a_real_outcome_through() -> None:
    for outcome in MvRefreshOutcome:
        assert require_mv_refresh_outcome(outcome, source="test") is outcome


@pytest.mark.parametrize("bad", [True, False, None, "refreshed", 1])
def test_require_mv_refresh_outcome_names_the_offending_type(bad: object) -> None:
    with pytest.raises(TypeError) as excinfo:
        require_mv_refresh_outcome(bad, source="SomeRepository.refresh_centroids_view_concurrent")

    message = str(excinfo.value)
    assert "MvRefreshOutcome" in message
    assert type(bad).__name__ in message
    assert "SomeRepository.refresh_centroids_view_concurrent" in message


@pytest.mark.asyncio
async def test_centroid_maintainer_rejects_a_legacy_boolean_repository() -> None:
    from recognition.application.persistence.centroid_maintainer import CentroidMaintainer

    class _LegacyBooleanRepository:
        async def refresh_centroids_view_concurrent(self):
            return True

    maintainer = CentroidMaintainer(_LegacyBooleanRepository())

    with pytest.raises(TypeError) as excinfo:
        await maintainer.refresh_centroids_view_concurrent()

    assert "bool" in str(excinfo.value)


@pytest.mark.asyncio
async def test_centroid_maintainer_passes_a_conforming_outcome_through() -> None:
    from recognition.application.persistence.centroid_maintainer import CentroidMaintainer

    class _ConformingRepository:
        async def refresh_centroids_view_concurrent(self):
            return MvRefreshOutcome.SKIPPED_HEADROOM

    maintainer = CentroidMaintainer(_ConformingRepository())

    assert await maintainer.refresh_centroids_view_concurrent() is MvRefreshOutcome.SKIPPED_HEADROOM
