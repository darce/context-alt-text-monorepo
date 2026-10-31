from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from sqlalchemy import BigInteger, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import CurationReplayRecord, IdentityCluster, IdentityMember


class CurationRefreshStatus(StrEnum):
    """Foundation replay states for post-curation refresh work.

    These values track the durable curation event lifecycle on replay rows.
    Slice 4 owns the richer suggestion-refresh outcomes from the spec.
    """

    NOT_APPLICABLE = "not_applicable"
    QUEUED = "queued"
    RUNNING = "running"
    NO_CANDIDATES = "no_candidates"
    TIMED_OUT = "timed_out"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class CurationSyncResult:
    """Result contract for one curation replay operation."""

    status: Literal["acknowledged", "conflict"]
    backend_version: int
    conflict_code: str | None = None
    machine_payload: dict[str, Any] | None = None


class CurationFollowupQueue(Protocol):
    async def queue_curation_followup(
        self,
        *,
        tenant_id: str,
        cluster_ids: list[str],
        identity_ids: list[str] | None = None,
        source_cluster_id: str | None = None,
        refresh_idempotency_key: str | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class _ChainHead:
    """Cluster version produced by the latest applied write of one same-batch chain."""

    version: int
    operation_type: str


# (tenant, cluster, explicit intent, shared expected base, positive local revision)
_ChainKey = tuple[UUID, UUID, UUID, int, int]
# Lives for exactly one apply_batch call, so a continuation proof never outlives the batch that produced it.
_BatchLedger = dict[_ChainKey, _ChainHead]


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
        "cluster_label_updated",
    }
    _NO_REFRESH_CLUSTER_OPERATION_TYPES: ClassVar[set[str]] = {
        "cluster_person_unbound",
    }
    _SUPPORTED_OPERATION_TYPES: ClassVar[set[str]] = _PERSON_OPERATION_TYPES | _CLUSTER_OPERATION_TYPES

    def __init__(self, session: AsyncSession, job_service: CurationFollowupQueue | None = None) -> None:
        self._session = session
        self._job_service = job_service

    async def apply_batch(self, tenant_id: str, operations: list[Any]) -> list[CurationSyncResult]:
        ledger: _BatchLedger = {}
        return [await self._apply(tenant_id=tenant_id, operation=operation, ledger=ledger) for operation in operations]

    async def apply(self, tenant_id: str, operation: Any) -> CurationSyncResult:
        return await self._apply(tenant_id=tenant_id, operation=operation, ledger=None)

    async def _apply(self, tenant_id: str, operation: Any, ledger: _BatchLedger | None) -> CurationSyncResult:
        normalized_tenant_id = tenant_id.strip()
        if not normalized_tenant_id:
            raise ValueError("tenant_id is required")

        operation_type = self._required_str(operation, "operation_type")
        if operation_type not in self._SUPPORTED_OPERATION_TYPES:
            raise ValueError(f"unsupported operation_type: {operation_type}")

        idempotency_key = self._required_str(operation, "idempotency_key")
        tenant_uuid = self._parse_uuid(normalized_tenant_id, field_name="tenant_id")
        request_fingerprint, operation = self._fingerprint_operation(tenant_uuid, operation)
        # Serialize absent-row retries too, before any effect or follow-up enqueue.
        # The lock ends with the caller's transaction, just like the effect and receipt.
        if not await self._lock_replay_key(tenant_uuid, idempotency_key):
            return CurationSyncResult(status="conflict", backend_version=0, conflict_code="replay_in_progress")
        cached = await self._load_replay_result(tenant_uuid, idempotency_key, request_fingerprint)
        if cached is not None:
            return cached

        expected_base_version = self._int_value(operation, "expected_base_version")

        if operation_type in self._PERSON_OPERATION_TYPES:
            result = await self._apply_person_operation(tenant_uuid, operation_type, operation)
            await self._store_replay_result(tenant_uuid, idempotency_key, operation_type, result, request_fingerprint)
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
            await self._store_replay_result(tenant_uuid, idempotency_key, operation_type, result, request_fingerprint)
            return result

        desired_dismissed = self._resolve_desired_dismissed(operation_type)
        current_roster_id = str(cluster.roster_id) if cluster.roster_id is not None else None
        current_dismissed = cluster.dismissed_at is not None
        current_label = cluster.label
        desired_label = self._resolve_desired_label(operation, operation_type, current_label)
        desired_roster_id = self._resolve_desired_roster_id(operation, operation_type, current_roster_id)
        cluster_backend_version = self._version_from_datetime(cluster.updated_at)

        dismissal_matches = desired_dismissed is None or current_dismissed == desired_dismissed
        if (
            current_roster_id == desired_roster_id
            and dismissal_matches
            and (current_label or "") == (desired_label or "")
        ):
            result = CurationSyncResult(
                status="acknowledged",
                backend_version=cluster_backend_version,
                machine_payload=self._acknowledged_machine_payload(
                    operation_type=operation_type,
                    cluster_uuid=cluster.id,
                    roster_id=desired_roster_id,
                    label=desired_label,
                ),
            )
            await self._queue_and_store_acknowledged_cluster_result(
                tenant_id=tenant_uuid,
                operation_type=operation_type,
                cluster_uuid=cluster.id,
                idempotency_key=idempotency_key,
                result=result,
                request_fingerprint=request_fingerprint,
            )
            return result

        chain_key = self._batch_chain_key(
            tenant_id=tenant_uuid,
            cluster_id=cluster.id,
            expected_base_version=expected_base_version,
            operation=operation,
        )
        continues_chain = self._continues_batch_chain(
            ledger=ledger,
            chain_key=chain_key,
            operation_type=operation_type,
            cluster_backend_version=cluster_backend_version,
        )
        if expected_base_version < cluster_backend_version and not continues_chain:
            result = CurationSyncResult(
                status="conflict",
                backend_version=cluster_backend_version,
                conflict_code="version_conflict",
                machine_payload={
                    "cluster_uuid": str(cluster.id),
                    "current_roster_id": current_roster_id,
                    "dismissed": current_dismissed,
                    "label": current_label,
                },
            )
            await self._store_replay_result(tenant_uuid, idempotency_key, operation_type, result, request_fingerprint)
            return result

        cluster.roster_id = UUID(desired_roster_id) if desired_roster_id is not None else None
        cluster.label = desired_label
        if operation_type == "cluster_person_bound" and desired_label:
            cluster.user_confirmed = True
        if desired_dismissed is True:
            cluster.dismissed_at = datetime.now(tz=UTC)
        elif desired_dismissed is False:
            cluster.dismissed_at = None
        cluster.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        if ledger is not None and chain_key is not None:
            ledger[chain_key] = _ChainHead(
                version=self._version_from_datetime(cluster.updated_at),
                operation_type=operation_type,
            )
        acknowledged_version = await self._current_backend_version(tenant_uuid)

        result = CurationSyncResult(
            status="acknowledged",
            backend_version=acknowledged_version,
            machine_payload=self._acknowledged_machine_payload(
                operation_type=operation_type,
                cluster_uuid=cluster.id,
                roster_id=desired_roster_id,
                label=desired_label,
            ),
        )
        await self._queue_and_store_acknowledged_cluster_result(
            tenant_id=tenant_uuid,
            operation_type=operation_type,
            cluster_uuid=cluster.id,
            idempotency_key=idempotency_key,
            result=result,
            request_fingerprint=request_fingerprint,
        )
        return result

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

    def _fingerprint_operation(self, tenant_id: UUID, operation: Any) -> tuple[str, dict[str, Any]]:
        """Freeze the complete route operation without losing JSON types or precision.

        CurationSyncRequest supplies these seven fields. Direct callers must supply
        the same JSON domain; never stringify an unknown guard or a map key. Maps
        are canonical, arrays stay ordered, and 1, 1.0 and true remain distinct.
        """
        def field(name: str, default: Any = None) -> Any:
            return operation.get(name, default) if isinstance(operation, dict) else getattr(operation, name, default)

        snapshot = {
            name: field(name)
            for name in ("operation_type", "entity_type", "entity_key", "idempotency_key")
        }
        for name in snapshot:
            self._required_str(snapshot, name)
        for name in ("expected_base_version", "local_revision"):
            value = field(name, 0)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative JSON integer")
            snapshot[name] = value
        snapshot["payload"] = field("payload", {})
        if type(snapshot["payload"]) is not dict:
            raise ValueError("payload must be a JSON object")

        def validate_json(value: Any) -> None:
            if type(value) in (str, int, bool, type(None)):
                return
            if type(value) is float and math.isfinite(value):
                return
            if type(value) is list:
                for item in value:
                    validate_json(item)
                return
            if type(value) is dict and all(type(key) is str for key in value):
                for item in value.values():
                    validate_json(item)
                return
            raise ValueError("operation must contain only finite JSON values and string map keys")

        validate_json(snapshot)
        canonical = json.dumps(
            {"schema": "curation-replay-v1", "tenant_id": str(tenant_id), "operation": snapshot},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        # Detach nested payloads before the first await: the applied effect must
        # consume exactly the identity we hashed even if a direct caller mutates it.
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), json.loads(canonical)["operation"]

    async def _lock_replay_key(self, tenant_id: UUID, idempotency_key: str) -> bool:
        if self._session.get_bind().dialect.name != "postgresql":
            # SQLite test storage still enforces tenant/key uniqueness on flush.
            return True
        lock_identity = json.dumps(["curation-replay", str(tenant_id), idempotency_key], separators=(",", ":"))
        lock_key = int.from_bytes(hashlib.sha256(lock_identity.encode("utf-8")).digest()[:8], "big", signed=True)
        return bool(await self._session.scalar(
            select(func.pg_catalog.pg_try_advisory_xact_lock(literal(lock_key, type_=BigInteger)))
        ))

    async def _load_replay_result(
        self, tenant_id: UUID, idempotency_key: str, request_fingerprint: str,
    ) -> CurationSyncResult | None:
        result = await self._session.execute(
            select(CurationReplayRecord).where(
                CurationReplayRecord.tenant_id == tenant_id,
                CurationReplayRecord.idempotency_key == idempotency_key,
            )
        )
        record = result.scalar_one_or_none()
        if not isinstance(record, CurationReplayRecord):
            return None

        if record.request_fingerprint is None or record.request_fingerprint != request_fingerprint:
            return CurationSyncResult(
                status="conflict",
                backend_version=max(0, int(record.backend_version)),
                conflict_code=("replay_fingerprint_unavailable" if record.request_fingerprint is None
                               else "replay_fingerprint_conflict"),
            )

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

    async def _store_replay_result(
        self,
        tenant_id: UUID,
        idempotency_key: str,
        operation_type: str,
        result: CurationSyncResult,
        request_fingerprint: str,
    ) -> None:
        machine_payload_json: str | None = None
        if isinstance(result.machine_payload, dict):
            machine_payload_json = json.dumps(result.machine_payload, sort_keys=True)

        refresh_status = self._initial_refresh_status(operation_type, result)
        refresh_requested_at = datetime.now(tz=UTC) if refresh_status is CurationRefreshStatus.QUEUED else None

        self._session.add(
            CurationReplayRecord(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                result_status=result.status,
                backend_version=max(0, int(result.backend_version)),
                conflict_code=result.conflict_code,
                machine_payload_json=machine_payload_json,
                refresh_status=refresh_status.value,
                refresh_requested_at=refresh_requested_at,
            )
        )
        await self._session.flush()

    def _initial_refresh_status(
        self,
        operation_type: str,
        result: CurationSyncResult,
    ) -> CurationRefreshStatus:
        if result.status != "acknowledged":
            return CurationRefreshStatus.NOT_APPLICABLE
        if operation_type in self._PERSON_OPERATION_TYPES:
            return CurationRefreshStatus.NOT_APPLICABLE
        if operation_type in self._NO_REFRESH_CLUSTER_OPERATION_TYPES:
            return CurationRefreshStatus.NOT_APPLICABLE
        return CurationRefreshStatus.QUEUED

    async def _queue_refresh_followup(
        self,
        *,
        tenant_id: UUID,
        operation_type: str,
        cluster_uuid: UUID,
        idempotency_key: str,
    ) -> None:
        if operation_type in self._PERSON_OPERATION_TYPES:
            return
        if operation_type in self._NO_REFRESH_CLUSTER_OPERATION_TYPES:
            return
        if self._job_service is None:
            raise RuntimeError("curation follow-up queue unavailable")
        identity_ids = await self._load_cluster_identity_ids(tenant_id=tenant_id, cluster_uuid=cluster_uuid)
        await self._job_service.queue_curation_followup(
            tenant_id=str(tenant_id),
            cluster_ids=[str(cluster_uuid)],
            identity_ids=identity_ids,
            refresh_idempotency_key=idempotency_key,
        )

    async def _load_cluster_identity_ids(self, *, tenant_id: UUID, cluster_uuid: UUID) -> list[str]:
        result = await self._session.execute(
            select(IdentityMember.identity_id)
            .where(IdentityMember.tenant_id == tenant_id, IdentityMember.cluster_id == cluster_uuid)
            .order_by(IdentityMember.assigned_at.asc(), IdentityMember.id.asc())
        )
        return [str(identity_id) for identity_id in result.scalars().all() if identity_id is not None]

    async def _queue_and_store_acknowledged_cluster_result(
        self,
        *,
        tenant_id: UUID,
        operation_type: str,
        cluster_uuid: UUID,
        idempotency_key: str,
        result: CurationSyncResult,
        request_fingerprint: str,
    ) -> None:
        await self._queue_refresh_followup(
            tenant_id=tenant_id,
            operation_type=operation_type,
            cluster_uuid=cluster_uuid,
            idempotency_key=idempotency_key,
        )
        await self._store_replay_result(tenant_id, idempotency_key, operation_type, result, request_fingerprint)

    def _acknowledged_machine_payload(
        self,
        *,
        operation_type: str,
        cluster_uuid: UUID,
        roster_id: str | None,
        label: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation_type": operation_type,
            "cluster_uuid": str(cluster_uuid),
        }
        if roster_id is not None:
            payload["person_uuid"] = roster_id
        if label:
            payload["label"] = label
        return payload

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

    def _batch_chain_key(
        self,
        *,
        tenant_id: UUID,
        cluster_id: UUID,
        expected_base_version: int,
        operation: Any,
    ) -> _ChainKey | None:
        local_revision = self._int_value(operation, "local_revision")
        if local_revision <= 0:
            return None
        intent_value = self._payload(operation).get("curation_intent_id")
        if not isinstance(intent_value, str):
            return None
        try:
            intent_id = UUID(intent_value.strip())
        except ValueError:
            return None
        if intent_id.int == 0:
            return None
        return (tenant_id, cluster_id, intent_id, expected_base_version, local_revision)

    def _continues_batch_chain(
        self,
        *,
        ledger: _BatchLedger | None,
        chain_key: _ChainKey | None,
        operation_type: str,
        cluster_backend_version: int,
    ) -> bool:
        # Only a bind may ride a same-batch chain, and only while the cluster still sits at the version the chain's
        # last write produced. Any other write since then moves the version and falls back to the conflict check.
        if ledger is None or chain_key is None or operation_type != "cluster_person_bound":
            return False
        head = ledger.get(chain_key)
        # Only an applied label proves the intent; a bind consumes that continuation.
        if head is None or head.operation_type != "cluster_label_updated":
            return False
        return head.version == cluster_backend_version

    def _resolve_cluster_uuid(self, operation: Any) -> UUID:
        payload = self._payload(operation)
        payload_cluster = payload.get("cluster_uuid")
        entity_key = self._required_str(operation, "entity_key")
        candidate = str(payload_cluster).strip() if isinstance(payload_cluster, str) else entity_key
        return self._parse_uuid(candidate, field_name="cluster_uuid")

    def _resolve_desired_roster_id(
        self, operation: Any, operation_type: str, current_roster_id: str | None
    ) -> str | None:
        if operation_type in {"cluster_dismissed", "cluster_undismissed", "cluster_label_updated"}:
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

    def _resolve_desired_label(self, operation: Any, operation_type: str, current_label: str | None) -> str | None:
        if operation_type == "cluster_person_bound":
            payload = self._payload(operation)
            person_name = payload.get("person_name")
            if isinstance(person_name, str) and person_name.strip():
                return person_name.strip()

        if operation_type != "cluster_label_updated":
            return current_label

        payload = self._payload(operation)
        if "label" not in payload:
            raise ValueError("label is required for cluster_label_updated")

        label = payload.get("label")
        if label is None:
            return None
        if not isinstance(label, str):
            raise ValueError("label must be a string or null for cluster_label_updated")
        if not label.strip():
            raise ValueError("label is required for cluster_label_updated")

        return label.strip()

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
