"""Unit tests for BlockCheck."""

from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.block import BlockCheck
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import IdentityClusterBlockRepository
from recognition.shared.ids import generate_id


def _make_candidate() -> AssignmentCandidate:
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.ones(4, dtype=np.float32),
        cluster_id=str(generate_id()),
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.9,
    )


@pytest.mark.asyncio
async def test_block_check_rejects_blocked_candidate() -> None:
    repo = AsyncMock(spec=IdentityClusterBlockRepository)
    repo.is_blocked.return_value = True

    candidate = _make_candidate()
    check = BlockCheck(repo)
    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.is_fatal is True
    assert result.should_reject is True
    assert result.metadata == {"block_active": True}
    repo.is_blocked.assert_awaited_once_with(
        tenant_id=candidate.identity.tenant_id,
        identity_id=candidate.identity.id,
        cluster_id=candidate.cluster_id,
    )


@pytest.mark.asyncio
async def test_block_check_allows_unblocked_candidate() -> None:
    repo = AsyncMock(spec=IdentityClusterBlockRepository)
    repo.is_blocked.return_value = False

    candidate = _make_candidate()
    check = BlockCheck(repo)
    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.metadata == {"block_active": False}
