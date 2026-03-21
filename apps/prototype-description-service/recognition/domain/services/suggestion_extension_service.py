"""Domain service scaffold for suggestion-system extensions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeAlias, cast
from uuid import UUID

from sqlalchemy import nulls_last, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterMergeSuggestion, IdentityCluster, IdentitySuggestion
from db.models import NameSuggestion as NameSuggestionModel
from recognition.domain.suggestion import NameSuggestion, SuggestedLabelSource, SuggestionStatus
from recognition.infrastructure.repositories._helpers import coerce_uuid

SuggestionModelRecord: TypeAlias = IdentitySuggestion | ClusterMergeSuggestion | NameSuggestionModel


class SuggestionExtensionService:
    """Backend-domain contract for name suggestions, expiry, and bulk accept flows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_name_suggestions(
        self,
        tenant_id: str,
        *,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NameSuggestion]:
        tenant_uuid = self._require_uuid(tenant_id, field_name="tenant_id")
        if min_confidence is not None and not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        now = datetime.now(tz=UTC)
        stmt = (
            select(NameSuggestionModel)
            .where(NameSuggestionModel.tenant_id == tenant_uuid)
            .where(NameSuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .where(self._active_expiry_clause(NameSuggestionModel, now))
            .order_by(nulls_last(NameSuggestionModel.confidence_score.desc()), NameSuggestionModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if min_confidence is not None:
            stmt = stmt.where(NameSuggestionModel.confidence_score.is_not(None)).where(
                NameSuggestionModel.confidence_score >= min_confidence
            )

        result = await self._session.execute(stmt)
        return [self._to_name_suggestion(model) for model in result.scalars().all()]

    async def accept_name_suggestion(self, tenant_id: str, suggestion_id: str) -> NameSuggestion:
        tenant_uuid = self._require_uuid(tenant_id, field_name="tenant_id")
        suggestion = await self._get_name_suggestion(tenant_uuid=tenant_uuid, suggestion_id=suggestion_id)
        if suggestion.resolution != SuggestionStatus.PENDING.value:
            return self._to_name_suggestion(suggestion)

        if self._is_expired(suggestion):
            self._mark_expired(suggestion, resolved_at=datetime.now(tz=UTC))
            await self._session.flush()
            await self._session.refresh(suggestion)
            return self._to_name_suggestion(suggestion)

        cluster = await self._session.get(IdentityCluster, suggestion.cluster_id)
        if cluster is None or cluster.tenant_id != tenant_uuid:
            raise LookupError(f"cluster not found for suggestion {suggestion_id}")

        resolved_at = datetime.now(tz=UTC)
        self._apply_name_label(cluster, suggestion.suggested_name)
        suggestion.resolution = SuggestionStatus.ACCEPTED.value
        suggestion.resolved_at = resolved_at
        await self._session.flush()
        await self._session.refresh(suggestion)
        return self._to_name_suggestion(suggestion)

    async def reject_name_suggestion(self, tenant_id: str, suggestion_id: str) -> NameSuggestion:
        tenant_uuid = self._require_uuid(tenant_id, field_name="tenant_id")
        suggestion = await self._get_name_suggestion(tenant_uuid=tenant_uuid, suggestion_id=suggestion_id)
        if suggestion.resolution == SuggestionStatus.PENDING.value:
            if self._is_expired(suggestion):
                self._mark_expired(suggestion, resolved_at=datetime.now(tz=UTC))
            else:
                suggestion.resolution = SuggestionStatus.REJECTED.value
                suggestion.resolved_at = datetime.now(tz=UTC)
            await self._session.flush()
            await self._session.refresh(suggestion)
        return self._to_name_suggestion(suggestion)

    async def bulk_accept(
        self,
        tenant_id: str,
        *,
        suggestion_type: str,
        min_confidence: float,
    ) -> dict[str, int]:
        tenant_uuid = self._require_uuid(tenant_id, field_name="tenant_id")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        if suggestion_type == "assignment":
            accepted = await self._bulk_accept_rows(tenant_uuid, IdentitySuggestion, min_confidence)
            return {"accepted_count": accepted, "skipped_count": 0}
        if suggestion_type == "merge":
            accepted = await self._bulk_accept_rows(tenant_uuid, ClusterMergeSuggestion, min_confidence)
            return {"accepted_count": accepted, "skipped_count": 0}
        if suggestion_type == "name":
            return await self._bulk_accept_name_suggestions(tenant_uuid, min_confidence)
        raise ValueError("suggestion_type must be one of: assignment, merge, name")

    async def expire_stale(self, tenant_id: str) -> int:
        tenant_uuid = self._require_uuid(tenant_id, field_name="tenant_id")
        resolved_at = datetime.now(tz=UTC)
        expired = 0
        expired += await self._expire_rows(tenant_uuid, IdentitySuggestion, resolved_at)
        expired += await self._expire_rows(tenant_uuid, ClusterMergeSuggestion, resolved_at)
        expired += await self._expire_rows(tenant_uuid, NameSuggestionModel, resolved_at)
        if expired:
            await self._session.flush()
        return expired

    async def _bulk_accept_rows(
        self,
        tenant_uuid: UUID,
        model_type: type[IdentitySuggestion] | type[ClusterMergeSuggestion],
        min_confidence: float,
    ) -> int:
        resolved_at = datetime.now(tz=UTC)
        stmt = (
            select(model_type)
            .where(model_type.tenant_id == tenant_uuid)
            .where(model_type.resolution == SuggestionStatus.PENDING.value)
            .where(self._active_expiry_clause(model_type, resolved_at))
            .where(model_type.confidence_score.is_not(None))
            .where(model_type.confidence_score >= min_confidence)
        )
        rows = cast(list[IdentitySuggestion | ClusterMergeSuggestion], (await self._session.execute(stmt)).scalars().all())
        for row in rows:
            row.resolution = SuggestionStatus.ACCEPTED.value
            row.resolved_at = resolved_at
        if rows:
            await self._session.flush()
        return len(rows)

    async def _bulk_accept_name_suggestions(self, tenant_uuid: UUID, min_confidence: float) -> dict[str, int]:
        resolved_at = datetime.now(tz=UTC)
        stmt = (
            select(NameSuggestionModel)
            .where(NameSuggestionModel.tenant_id == tenant_uuid)
            .where(NameSuggestionModel.resolution == SuggestionStatus.PENDING.value)
            .where(self._active_expiry_clause(NameSuggestionModel, resolved_at))
            .where(NameSuggestionModel.confidence_score.is_not(None))
            .where(NameSuggestionModel.confidence_score >= min_confidence)
            .order_by(NameSuggestionModel.confidence_score.desc(), NameSuggestionModel.created_at.asc())
        )
        suggestions = (await self._session.execute(stmt)).scalars().all()

        accepted_count = 0
        skipped_count = 0
        seen_cluster_ids: set[str] = set()
        for suggestion in suggestions:
            cluster_key = str(suggestion.cluster_id)
            if cluster_key in seen_cluster_ids:
                skipped_count += 1
                continue

            cluster = await self._session.get(IdentityCluster, suggestion.cluster_id)
            if cluster is None or cluster.tenant_id != tenant_uuid:
                skipped_count += 1
                continue
            if cluster.user_confirmed and cluster.label and cluster.label != suggestion.suggested_name:
                skipped_count += 1
                continue

            self._apply_name_label(cluster, suggestion.suggested_name)
            suggestion.resolution = SuggestionStatus.ACCEPTED.value
            suggestion.resolved_at = resolved_at
            accepted_count += 1
            seen_cluster_ids.add(cluster_key)

        if accepted_count:
            await self._session.flush()
        return {"accepted_count": accepted_count, "skipped_count": skipped_count}

    async def _expire_rows(
        self,
        tenant_uuid: UUID,
        model_type: type[IdentitySuggestion] | type[ClusterMergeSuggestion] | type[NameSuggestionModel],
        resolved_at: datetime,
    ) -> int:
        stmt = (
            select(model_type)
            .where(model_type.tenant_id == tenant_uuid)
            .where(model_type.resolution == SuggestionStatus.PENDING.value)
            .where(model_type.expires_at.is_not(None))
            .where(model_type.expires_at <= resolved_at)
        )
        rows = cast(list[SuggestionModelRecord], (await self._session.execute(stmt)).scalars().all())
        for row in rows:
            self._mark_expired(row, resolved_at=resolved_at)
        return len(rows)

    async def _get_name_suggestion(self, *, tenant_uuid: UUID, suggestion_id: str) -> NameSuggestionModel:
        suggestion_uuid = self._require_uuid(suggestion_id, field_name="suggestion_id")
        stmt = (
            select(NameSuggestionModel)
            .where(NameSuggestionModel.tenant_id == tenant_uuid)
            .where(NameSuggestionModel.id == suggestion_uuid)
        )
        suggestion = (await self._session.execute(stmt)).scalar_one_or_none()
        if suggestion is None:
            raise LookupError(f"name suggestion not found: {suggestion_id}")
        return suggestion

    @staticmethod
    def _active_expiry_clause(
        model_type: type[IdentitySuggestion] | type[ClusterMergeSuggestion] | type[NameSuggestionModel],
        now: datetime,
    ):
        return or_(model_type.expires_at.is_(None), model_type.expires_at > now)

    @staticmethod
    def _apply_name_label(cluster: IdentityCluster, suggested_name: str) -> None:
        cluster.label = suggested_name
        cluster.user_confirmed = True
        cluster.confirmation_count = int(cluster.confirmation_count or 0) + 1
        cluster.confirmation_source = "label"
        cluster.dismissed_at = None

    @staticmethod
    def _is_expired(suggestion: NameSuggestionModel) -> bool:
        return suggestion.expires_at is not None and suggestion.expires_at <= datetime.now(tz=UTC)

    @staticmethod
    def _mark_expired(suggestion: SuggestionModelRecord, *, resolved_at: datetime) -> None:
        suggestion.resolution = SuggestionStatus.EXPIRED.value
        suggestion.resolved_at = resolved_at

    @staticmethod
    def _to_name_suggestion(model: NameSuggestionModel) -> NameSuggestion:
        return NameSuggestion(
            id=str(model.id),
            cluster_id=str(model.cluster_id),
            suggested_name=model.suggested_name,
            source=SuggestedLabelSource(model.source),
            status=SuggestionStatus(model.resolution),
            confidence_score=float(model.confidence_score) if model.confidence_score is not None else None,
            source_job_id=str(model.source_job_id) if model.source_job_id is not None else None,
            created_at=model.created_at,
            expires_at=model.expires_at,
            resolved_at=model.resolved_at,
        )

    @staticmethod
    def _require_uuid(value: str, *, field_name: str) -> UUID:
        coerced = coerce_uuid(value, on_failure="none")
        if coerced is None:
            raise ValueError(f"{field_name} must be a valid UUID")
        return coerced
