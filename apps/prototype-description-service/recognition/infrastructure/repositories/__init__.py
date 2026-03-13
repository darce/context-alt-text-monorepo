"""Repository implementations for database persistence."""

from recognition.infrastructure.repositories.api_key_repository import SqlAlchemyApiKeyRepository
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
