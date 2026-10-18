"""Integration tests for the batch identity-suggestions path (UXP-2 Slice 3a).

Exercises the real ROW_NUMBER windowed query under sqlite+aiosqlite and pins
literal filter parity between the batch route and the per-card route: pending
status + truthy cluster label only (auto-labels like ``cluster-1234`` pass,
``user_confirmed`` is NOT required).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentitySuggestion as SuggestionModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.suggestions.service import SuggestionService
from recognition.domain.cluster import IdentityCluster
from recognition.domain.suggestion import SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemySuggestionRepository
from recognition.interface_adapters.http.routers.suggestions import (
    list_identities_suggestions,
    list_suggestions,
)

BASE_TIME = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


@dataclass
class ParityFixture:
    """Seeded identities plus the cluster each one is expected to resolve to."""

    tenant_id: str
    identity_ids: list[str]
    expected_cluster_by_identity: dict[str, str]
    multi_suggestion_identities: list[str]
    unlabeled_first_identity: str
    auto_label_identity: str
    tie_break_identity: str
    resolved_first_identity: str
    suggestion_service: SuggestionService
    cluster_repo: SqlAlchemyClusterRepository


async def _seed_identity(db_session: AsyncSession, tenant_uuid: uuid.UUID, media_id: int) -> str:
    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant_uuid,
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
        embedding_model="stub-detector@test",
    )
    db_session.add(identity)
    await db_session.flush()
    return str(identity.id)


async def _seed_cluster(cluster_repo: SqlAlchemyClusterRepository, tenant_id: str, label: str | None) -> str:
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=label,
            is_labeled=bool(label),
            identity_count=1,
            created_at=None,
        )
    )
    assert cluster.id is not None
    return str(cluster.id)


def _add_suggestion(
    db_session: AsyncSession,
    tenant_uuid: uuid.UUID,
    identity_id: str,
    cluster_id: str,
    similarity: float,
    created_at: datetime,
    resolution: str = SuggestionStatus.PENDING.value,
) -> None:
    db_session.add(
        SuggestionModel(
            tenant_id=tenant_uuid,
            identity_id=uuid.UUID(identity_id),
            suggested_cluster_id=uuid.UUID(cluster_id),
            representative_similarity=similarity,
            avg_member_similarity=similarity,
            confidence_score=similarity,
            resolution=resolution,
            created_at=created_at,
        )
    )


@pytest_asyncio.fixture
async def parity_fixture(db_session: AsyncSession, tenant) -> ParityFixture:
    """60 identities exercising the batch failure modes named in the plan.

    - identities 0-4 carry 3 pending suggestions each (row-vs-identity bound guard)
    - identity 5: highest-similarity suggestion targets an UNLABELED cluster,
      second targets a labeled one (filter-before-rank guard)
    - identity 6: top suggestion targets a ``cluster-1234`` auto-label
      (deliberate filter-parity decision: it must resolve, not be filtered)
    - identity 7: two equal-similarity suggestions, newer created_at must win
      on both routes (tie-break parity)
    - identity 8: highest-similarity suggestion is ACCEPTED (resolved), second
      is pending+labeled (guards the pending filter living INSIDE the window)
    - identities 9-59: one pending labeled-cluster suggestion each
    """
    tenant_id = str(tenant.id)
    cluster_repo = SqlAlchemyClusterRepository(db_session)

    identity_ids = [await _seed_identity(db_session, tenant.id, media_id=1000 + i) for i in range(60)]
    expected: dict[str, str] = {}

    multi_ids = identity_ids[:5]
    for offset, identity_id in enumerate(multi_ids):
        winner = await _seed_cluster(cluster_repo, tenant_id, f"Multi Winner {offset}")
        expected[identity_id] = winner
        _add_suggestion(db_session, tenant.id, identity_id, winner, 0.90, BASE_TIME)
        for rank, similarity in enumerate([0.80, 0.70]):
            loser = await _seed_cluster(cluster_repo, tenant_id, f"Multi Loser {offset}-{rank}")
            _add_suggestion(db_session, tenant.id, identity_id, loser, similarity, BASE_TIME)

    unlabeled_first_identity = identity_ids[5]
    unlabeled_cluster = await _seed_cluster(cluster_repo, tenant_id, None)
    labeled_second = await _seed_cluster(cluster_repo, tenant_id, "Labeled Second Choice")
    _add_suggestion(db_session, tenant.id, unlabeled_first_identity, unlabeled_cluster, 0.95, BASE_TIME)
    _add_suggestion(db_session, tenant.id, unlabeled_first_identity, labeled_second, 0.85, BASE_TIME)
    expected[unlabeled_first_identity] = labeled_second

    auto_label_identity = identity_ids[6]
    auto_label_cluster = await _seed_cluster(cluster_repo, tenant_id, "cluster-1234")
    _add_suggestion(db_session, tenant.id, auto_label_identity, auto_label_cluster, 0.90, BASE_TIME)
    expected[auto_label_identity] = auto_label_cluster

    tie_break_identity = identity_ids[7]
    tie_older = await _seed_cluster(cluster_repo, tenant_id, "Tie Older")
    tie_newer = await _seed_cluster(cluster_repo, tenant_id, "Tie Newer")
    _add_suggestion(db_session, tenant.id, tie_break_identity, tie_older, 0.88, BASE_TIME - timedelta(hours=1))
    _add_suggestion(db_session, tenant.id, tie_break_identity, tie_newer, 0.88, BASE_TIME)
    expected[tie_break_identity] = tie_newer

    resolved_first_identity = identity_ids[8]
    accepted_cluster = await _seed_cluster(cluster_repo, tenant_id, "Already Accepted")
    pending_second = await _seed_cluster(cluster_repo, tenant_id, "Pending Second Choice")
    _add_suggestion(
        db_session,
        tenant.id,
        resolved_first_identity,
        accepted_cluster,
        0.97,
        BASE_TIME,
        resolution=SuggestionStatus.ACCEPTED.value,
    )
    _add_suggestion(db_session, tenant.id, resolved_first_identity, pending_second, 0.87, BASE_TIME)
    expected[resolved_first_identity] = pending_second

    for offset, identity_id in enumerate(identity_ids[9:]):
        cluster_id = await _seed_cluster(cluster_repo, tenant_id, f"Single {offset}")
        _add_suggestion(db_session, tenant.id, identity_id, cluster_id, 0.60 + (offset % 30) * 0.01, BASE_TIME)
        expected[identity_id] = cluster_id

    await db_session.commit()

    suggestion_service = SuggestionService(
        SqlAlchemySuggestionRepository(db_session),
        tenant_id,
        cluster_repository=cluster_repo,
        session=db_session,
    )
    return ParityFixture(
        tenant_id=tenant_id,
        identity_ids=identity_ids,
        expected_cluster_by_identity=expected,
        multi_suggestion_identities=multi_ids,
        unlabeled_first_identity=unlabeled_first_identity,
        auto_label_identity=auto_label_identity,
        tie_break_identity=tie_break_identity,
        resolved_first_identity=resolved_first_identity,
        suggestion_service=suggestion_service,
        cluster_repo=cluster_repo,
    )


@pytest.mark.asyncio
async def test_batch_matches_per_card_across_60_identity_fixture(parity_fixture: ParityFixture) -> None:
    """Batch and per-card routes return the SAME match for every identity in the fixture."""
    fx = parity_fixture

    batch = await list_identities_suggestions(
        identity_ids=",".join(fx.identity_ids),
        _tenant_id=fx.tenant_id,
        top_k=1,
        suggestion_service=fx.suggestion_service,
    )

    assert set(batch.matches.keys()) == set(fx.identity_ids), "every identity must resolve a suggestion"

    for identity_id in fx.identity_ids:
        per_card = await list_suggestions(
            identity_id=identity_id,
            _tenant_id=fx.tenant_id,
            min_confidence=None,
            top_k=1,
            suggestion_service=fx.suggestion_service,
            cluster_repo=fx.cluster_repo,
        )
        batch_rows = batch.matches[identity_id]
        assert len(batch_rows) == 1, f"top_k=1 must bound rows per identity, got {len(batch_rows)}"
        assert len(per_card.matches) == 1
        batch_match = batch_rows[0]
        per_card_match = per_card.matches[0]
        assert batch_match.suggestion_id == per_card_match.suggestion_id, f"parity broken for {identity_id}"
        assert batch_match.cluster_id == per_card_match.cluster_id
        assert batch_match.label == per_card_match.label
        assert batch_match.similarity == pytest.approx(per_card_match.similarity)
        assert batch_match.identity_count == per_card_match.identity_count
        assert batch_match.cluster_id == fx.expected_cluster_by_identity[identity_id]

    total_rows = sum(len(rows) for rows in batch.matches.values())
    assert total_rows <= len(fx.identity_ids) * 1


@pytest.mark.asyncio
async def test_filter_before_rank_resolves_unlabeled_first_identity(parity_fixture: ParityFixture) -> None:
    """An identity whose #1 suggestion targets an unlabeled cluster still resolves to its labeled #2."""
    fx = parity_fixture

    batch = await list_identities_suggestions(
        identity_ids=fx.unlabeled_first_identity,
        _tenant_id=fx.tenant_id,
        top_k=1,
        suggestion_service=fx.suggestion_service,
    )

    rows = batch.matches[fx.unlabeled_first_identity]
    assert [row.cluster_id for row in rows] == [fx.expected_cluster_by_identity[fx.unlabeled_first_identity]]
    assert rows[0].label == "Labeled Second Choice"


@pytest.mark.asyncio
async def test_pending_filter_inside_window_skips_resolved_top_suggestion(parity_fixture: ParityFixture) -> None:
    """An identity whose #1 suggestion is already ACCEPTED resolves to its pending #2 on BOTH routes.

    Guards the pending filter living INSIDE the windowed subquery: if it moved
    outside, the accepted row would consume rank 1 and top_k=1 would drop the
    identity entirely.
    """
    fx = parity_fixture
    expected_cluster = fx.expected_cluster_by_identity[fx.resolved_first_identity]

    batch = await list_identities_suggestions(
        identity_ids=fx.resolved_first_identity,
        _tenant_id=fx.tenant_id,
        top_k=1,
        suggestion_service=fx.suggestion_service,
    )
    rows = batch.matches[fx.resolved_first_identity]
    assert [row.cluster_id for row in rows] == [expected_cluster]
    assert rows[0].label == "Pending Second Choice"

    per_card = await list_suggestions(
        identity_id=fx.resolved_first_identity,
        _tenant_id=fx.tenant_id,
        min_confidence=None,
        top_k=1,
        suggestion_service=fx.suggestion_service,
        cluster_repo=fx.cluster_repo,
    )
    assert [row.cluster_id for row in per_card.matches] == [expected_cluster]
    assert per_card.matches[0].label == "Pending Second Choice"


@pytest.mark.asyncio
async def test_auto_label_cluster_passes_the_batch_filter(parity_fixture: ParityFixture) -> None:
    """``cluster-1234``-style auto-labels pass, matching the per-card route literally."""
    fx = parity_fixture

    batch = await list_identities_suggestions(
        identity_ids=fx.auto_label_identity,
        _tenant_id=fx.tenant_id,
        top_k=1,
        suggestion_service=fx.suggestion_service,
    )

    assert batch.matches[fx.auto_label_identity][0].label == "cluster-1234"


@pytest.mark.asyncio
async def test_tie_break_created_at_desc_parity(parity_fixture: ParityFixture) -> None:
    """Equal similarities resolve identically on both routes: newer created_at wins."""
    fx = parity_fixture

    batch = await list_identities_suggestions(
        identity_ids=fx.tie_break_identity,
        _tenant_id=fx.tenant_id,
        top_k=1,
        suggestion_service=fx.suggestion_service,
    )
    per_card = await list_suggestions(
        identity_id=fx.tie_break_identity,
        _tenant_id=fx.tenant_id,
        min_confidence=None,
        top_k=1,
        suggestion_service=fx.suggestion_service,
        cluster_repo=fx.cluster_repo,
    )

    expected_cluster = fx.expected_cluster_by_identity[fx.tie_break_identity]
    assert batch.matches[fx.tie_break_identity][0].cluster_id == expected_cluster
    assert per_card.matches[0].cluster_id == expected_cluster
    assert per_card.matches[0].label == "Tie Newer"


@pytest.mark.asyncio
async def test_top_k_two_bounds_rows_per_identity_not_globally(parity_fixture: ParityFixture) -> None:
    """top_k bounds rows PER identity: multi-suggestion identities return 2, singles return 1."""
    fx = parity_fixture
    multi_identity = fx.multi_suggestion_identities[0]
    single_identity = fx.identity_ids[9]

    batch = await list_identities_suggestions(
        identity_ids=f"{multi_identity},{single_identity}",
        _tenant_id=fx.tenant_id,
        top_k=2,
        suggestion_service=fx.suggestion_service,
    )

    assert len(batch.matches[multi_identity]) == 2
    assert len(batch.matches[single_identity]) == 1
    similarities = [row.similarity for row in batch.matches[multi_identity]]
    assert similarities == sorted(similarities, reverse=True)

    per_card = await list_suggestions(
        identity_id=multi_identity,
        _tenant_id=fx.tenant_id,
        min_confidence=None,
        top_k=2,
        suggestion_service=fx.suggestion_service,
        cluster_repo=fx.cluster_repo,
    )
    assert [row.cluster_id for row in per_card.matches] == [row.cluster_id for row in batch.matches[multi_identity]]
