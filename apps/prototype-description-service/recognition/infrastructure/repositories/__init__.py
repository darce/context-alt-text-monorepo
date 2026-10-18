"""Repository implementations for database persistence.

Keep exports lazy so narrow CLI tools can import one repository without
eagerly traversing the full application/http graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository
    from recognition.infrastructure.repositories.atlas_repository import AtlasRepository
    from recognition.infrastructure.repositories.audit_repository import AuditRepository
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
    from recognition.infrastructure.repositories.constraint_repository import SqlAlchemyConstraintRepository
    from recognition.infrastructure.repositories.identity_cluster_block_repository import (
        SqlAlchemyIdentityClusterBlockRepository,
    )
    from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
    from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository
    from recognition.infrastructure.repositories.merge_suggestion_repository import SqlAlchemyMergeSuggestionRepository
    from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
    from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository

__all__ = [
    "AtlasRepository",
    "SqlAlchemyClusterRepository",
    "SqlAlchemyConstraintRepository",
    "SqlAlchemyIdentityClusterBlockRepository",
    "SqlAlchemyMemberRepository",
    "SqlAlchemySuggestionRepository",
    "SqlAlchemyMergeSuggestionRepository",
    "SqlAlchemyJobRepository",
    "SqlAlchemyApiKeyRepository",
    "AuditRepository",
    "SqlAlchemyScanQueueRepository",
]

_EXPORTS = {
    "AtlasRepository": (
        "recognition.infrastructure.repositories.atlas_repository",
        "AtlasRepository",
    ),
    "SqlAlchemyApiKeyRepository": (
        "recognition.infrastructure.repositories.api_key_repository",
        "SqlAlchemyApiKeyRepository",
    ),
    "AuditRepository": (
        "recognition.infrastructure.repositories.audit_repository",
        "AuditRepository",
    ),
    "SqlAlchemyClusterRepository": (
        "recognition.infrastructure.repositories.cluster_repository",
        "SqlAlchemyClusterRepository",
    ),
    "SqlAlchemyConstraintRepository": (
        "recognition.infrastructure.repositories.constraint_repository",
        "SqlAlchemyConstraintRepository",
    ),
    "SqlAlchemyIdentityClusterBlockRepository": (
        "recognition.infrastructure.repositories.identity_cluster_block_repository",
        "SqlAlchemyIdentityClusterBlockRepository",
    ),
    "SqlAlchemyJobRepository": (
        "recognition.infrastructure.repositories.job_repository",
        "SqlAlchemyJobRepository",
    ),
    "SqlAlchemyMemberRepository": (
        "recognition.infrastructure.repositories.member_repository",
        "SqlAlchemyMemberRepository",
    ),
    "SqlAlchemyMergeSuggestionRepository": (
        "recognition.infrastructure.repositories.merge_suggestion_repository",
        "SqlAlchemyMergeSuggestionRepository",
    ),
    "SqlAlchemyScanQueueRepository": (
        "recognition.infrastructure.repositories.scan_queue_repository",
        "SqlAlchemyScanQueueRepository",
    ),
    "SqlAlchemySuggestionRepository": (
        "recognition.infrastructure.repositories.suggestion_repository",
        "SqlAlchemySuggestionRepository",
    ),
}


def __getattr__(name: str) -> object:
    try:
        module_name, export_name = _EXPORTS[name]
    except KeyError as exc:  # pragma: no cover
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    value = getattr(module, export_name)
    globals()[name] = value
    return value
