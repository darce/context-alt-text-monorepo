from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import CurationReplayRecord, IdentityCluster


@dataclass(frozen=True)
class CurationSyncResult:
    """Result contract for one curation replay operation."""

    status: Literal["acknowledged", "conflict"]
    backend_version: int
    conflict_code: str | None = None
    machine_payload: dict[str, Any] | None = None


class CurationSyncService:
    """Apply one curation replay operation for a tenant."""

    _PERSON_OPERATION_TYPES: ClassVar[set[str]] = {
        "person_created",
        "person_updated",
        "person_deleted",
    }
    _CLUSTER_OPERATION_TYPES: ClassVar[set[str]] = {
        "cluster_person_bound",
        "cluster_person_unbound",
        "cluster_dismissed",
        "cluster_undismissed",
    }
    _SUPPORTED_OPERATION_TYPES: ClassVar[set[str]] = _PERSON_OPERATION_TYPES | _CLUSTER_OPERATION_TYPES

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def apply_batch(self, tenant_id: str, operations: list[Any]) -> list[CurationSyncResult]:
        return [await self.apply(tenant_id=tenant_id, operation=operation) for operation in operations]

    async def apply(self, tenant_id: str, operation: Any) -> CurationSyncResult:
        normalized_tenant_id = tenant_id.strip()
        if not normalized_tenant_id:
            raise ValueError("tenant_id is required")

        operation_type = self._required_str(operation, "operation_type")
        if operation_type not in self._SUPPORTED_OPERATION_TYPES:
            raise ValueError(f"unsupported operation_type: {operation_type}")

        idempotency_key = self._required_str(operation, "idempotency_key")
        tenant_uuid = self._parse_uuid(normalized_tenant_id, field_name="tenant_id")
        cached = await self._load_replay_result(tenant_uuid, idempotency_key)
        if cached is not None:
            return cached

        expected_base_version = self._int_value(operation, "expected_base_version")

        if operation_type in self._PERSON_OPERATION_TYPES:
            result = await self._apply_person_operation(tenant_uuid, operation_type, operation)
            await self._store_replay_result(tenant_uuid, idempotency_key, result)
            return result

        cluster_uuid = self._resolve_cluster_uuid(operation)
        cluster = await self._load_cluster(tenant_uuid, cluster_uuid)
        current_backend_version = await self._current_backend_version(tenant_uuid)

        if cluster is None:
            result = CurationSyncResult(
                status="conflict",
                backend_version=current_backend_version,
                conflict_code="cluster_not_found",
                machine_payload={"cluster_uuid": str(cluster_uuid), "reason": "cluster_not_found"},
            )
            await self._store_replay_result(tenant_uuid, idempotency_key, result)
            return result

        desired_dismissed = self._resolve_desired_dismissed(operation_type)
        current_roster_id = str(cluster.roster_id) if cluster.roster_id is not None else None
        current_dismissed = cluster.dismissed_at is not None
        desired_roster_id = self._resolve_desired_roster_id(operation, operation_type, current_roster_id)
        cluster_backend_version = self._version_from_datetime(cluster.updated_at)

        dismissal_matches = desired_dismissed is None or current_dismissed == desired_dismissed
        if current_roster_id == desired_roster_id and dismissal_matches:
            result = CurationSyncResult(status="acknowledged", backend_version=cluster_backend_version)
            await self._store_replay_result(tenant_uuid, idempotency_key, result)
            return result

        if expected_base_version < cluster_backend_version:
            result = CurationSyncResult(
                status="conflict",
                backend_version=cluster_backend_version,
                conflict_code="version_conflict",
                machine_payload={
                    "cluster_uuid": str(cluster.id),
                    "current_roster_id": current_roster_id,
                    "dismissed": current_dismissed,
                },
            )
            await self._store_replay_result(tenant_uuid, idempotency_key, result)
            return result

        cluster.roster_id = UUID(desired_roster_id) if desired_roster_id is not None else None
        if desired_dismissed is True:
            cluster.dismissed_at = datetime.now(tz=UTC)
        elif desired_dismissed is False:
            cluster.dismissed_at = None
        cluster.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        acknowledged_version = await self._current_backend_version(tenant_uuid)

        result = CurationSyncResult(
            status="acknowledged",
            backend_version=acknowledged_version,
        )
        await self._store_replay_result(tenant_uuid, idempotency_key, result)
        return result

    @classmethod
    def reset_idempotency_cache(cls) -> None:
        # Legacy no-op retained for compatibility with older tests.
        return

    async def _apply_person_operation(self, tenant_id: UUID, operation_type: str, operation: Any) -> CurationSyncResult:
        payload = self._payload(operation)
        person_uuid = payload.get("person_uuid")
        if not isinstance(person_uuid, str) or not person_uuid.strip():
            raise ValueError("person_uuid is required for person operations")

        self._parse_uuid(person_uuid, field_name="person_uuid")

        return CurationSyncResult(
            status="acknowledged",
            backend_version=await self._current_backend_version(tenant_id),
        )

    async def _load_replay_result(self, tenant_id: UUID, idempotency_key: str) -> CurationSyncResult | None:
        result = await self._session.execute(
            select(CurationReplayRecord).where(
                CurationReplayRecord.tenant_id == tenant_id,
                CurationReplayRecord.idempotency_key == idempotency_key,
            )
        )
        record = result.scalar_one_or_none()
        if not isinstance(record, CurationReplayRecord):
            return None

        machine_payload: dict[str, Any] | None = None
        if isinstance(record.machine_payload_json, str) and record.machine_payload_json.strip():
            try:
                decoded = json.loads(record.machine_payload_json)
                machine_payload = decoded if isinstance(decoded, dict) else None
            except json.JSONDecodeError:
                machine_payload = None

        return CurationSyncResult(
            status="acknowledged" if record.result_status == "acknowledged" else "conflict",
            backend_version=max(0, int(record.backend_version)),
            conflict_code=record.conflict_code,
            machine_payload=machine_payload,
        )

    async def _store_replay_result(self, tenant_id: UUID, idempotency_key: str, result: CurationSyncResult) -> None:
        existing = await self._load_replay_result(tenant_id, idempotency_key)
        if existing is not None:
            return

        machine_payload_json: str | None = None
        if isinstance(result.machine_payload, dict):
            machine_payload_json = json.dumps(result.machine_payload, sort_keys=True)

        self._session.add(
            CurationReplayRecord(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                result_status=result.status,
                backend_version=max(0, int(result.backend_version)),
                conflict_code=result.conflict_code,
                machine_payload_json=machine_payload_json,
            )
        )
        await self._session.flush()

    async def _load_cluster(self, tenant_id: UUID, cluster_id: UUID) -> IdentityCluster | None:
        result = await self._session.execute(
            select(IdentityCluster).where(IdentityCluster.tenant_id == tenant_id, IdentityCluster.id == cluster_id)
        )
        row = result.scalar_one_or_none()
        return row if isinstance(row, IdentityCluster) else None

    async def _current_backend_version(self, tenant_id: UUID) -> int:
        result = await self._session.execute(
            select(func.max(IdentityCluster.updated_at)).where(IdentityCluster.tenant_id == tenant_id)
        )
        latest_updated_at = result.scalar_one_or_none()
        return self._version_from_datetime(latest_updated_at)

    def _resolve_cluster_uuid(self, operation: Any) -> UUID:
        payload = self._payload(operation)
        payload_cluster = payload.get("cluster_uuid")
        entity_key = self._required_str(operation, "entity_key")
        candidate = str(payload_cluster).strip() if isinstance(payload_cluster, str) else entity_key
        return self._parse_uuid(candidate, field_name="cluster_uuid")

    def _resolve_desired_roster_id(self, operation: Any, operation_type: str, current_roster_id: str | None) -> str | None:
        if operation_type in {"cluster_dismissed", "cluster_undismissed"}:
            return current_roster_id

        if operation_type == "cluster_person_unbound":
            return None

        payload = self._payload(operation)
        person_uuid = payload.get("person_uuid")
        if not isinstance(person_uuid, str) or not person_uuid.strip():
            raise ValueError("person_uuid is required for cluster_person_bound")

        return str(self._parse_uuid(person_uuid, field_name="person_uuid"))

    def _resolve_desired_dismissed(self, operation_type: str) -> bool | None:
        if operation_type == "cluster_dismissed":
            return True
        if operation_type == "cluster_undismissed":
            return False
        return None

    def _payload(self, operation: Any) -> dict[str, Any]:
        value = getattr(operation, "payload", None)
        if isinstance(value, dict):
            return value
        if isinstance(operation, dict):
            payload = operation.get("payload")
            if isinstance(payload, dict):
                return payload
        return {}

    def _required_str(self, operation: Any, field_name: str) -> str:
        value: Any
        if isinstance(operation, dict):
            value = operation.get(field_name)
        else:
            value = getattr(operation, field_name, None)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")

        return value.strip()

    def _int_value(self, operation: Any, field_name: str) -> int:
        value: Any
        if isinstance(operation, dict):
            value = operation.get(field_name, 0)
        else:
            value = getattr(operation, field_name, 0)

        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be an integer") from None

    def _parse_uuid(self, value: str, *, field_name: str) -> UUID:
        try:
            return UUID(str(value).strip())
        except ValueError:
            raise ValueError(f"{field_name} must be a valid UUID") from None

    def _version_from_datetime(self, value: Any) -> int:
        if isinstance(value, datetime):
            return max(0, int(value.timestamp() * 1_000_000))
        return 0
