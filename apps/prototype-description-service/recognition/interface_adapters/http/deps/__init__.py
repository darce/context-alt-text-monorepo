"""Dependency providers for the recognition HTTP API.

This package is the single canonical DI surface. Import providers from here
(`recognition.interface_adapters.http.deps`); the focused submodules
(`deps.auth`, `deps.services`, `deps.session`, `deps.stores`, `deps.tenant`)
remain the definition sites. The legacy `http.dependencies` re-export module was
removed in the DI-consolidation slice — there is no parallel surface to drift
against.
"""

from __future__ import annotations

from recognition.interface_adapters.http.deps.auth import (
    AuthContext,
    get_current_tenant,
    require_auth,
    require_auth_key_only,
    require_write_access,
)
from recognition.interface_adapters.http.deps.services import (
    AuditRepositoryProtocol,
    RetentionExportServiceProtocol,
    RetentionPolicyServiceProtocol,
    RetentionPurgeServiceProtocol,
    TenantImportServiceProtocol,
    build_cluster_service,
    get_audit_repository,
    get_cluster_repository,
    get_cluster_service,
    get_cluster_service_builder,
    get_cluster_service_builder_clustering,
    get_job_repo,
    get_job_service,
    get_job_service_dependency,
    get_media_identity_service,
    get_merge_suggestion_repository,
    get_observability_repository,
    get_persisted_cluster_job_service,
    get_persisted_cluster_job_service_clustering,
    get_persisted_job_service,
    get_retention_export_service,
    get_retention_import_service,
    get_retention_policy_service,
    get_retention_purge_service,
    get_scan_queue_repo,
    get_scan_queue_service,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    get_scan_service_builder,
    get_settings,
    get_shared_insightface_adapter,
    get_suggestion_extension_service,
    get_suggestion_refresh_service,
    get_suggestion_service,
)
from recognition.interface_adapters.http.deps.session import (
    get_clustering_session,
    get_observability_session,
    get_optional_session,
    get_session,
)
from recognition.interface_adapters.http.deps.stores import (
    DecisionStore,
    InMemoryJobService,
    MediaIdentityService,
    get_decision_store,
)
from recognition.interface_adapters.http.deps.tenant import (
    get_authenticated_tenant_id,
    get_tenant_id,
    get_tenant_id_optional,
)

__all__ = [
    # Auth
    "AuthContext",
    "require_auth",
    "require_auth_key_only",
    "get_current_tenant",
    "require_write_access",
    # Session
    "get_session",
    "get_optional_session",
    "get_observability_session",
    "get_clustering_session",
    # Tenant
    "get_authenticated_tenant_id",
    "get_tenant_id",
    "get_tenant_id_optional",
    # Service factories
    "get_settings",
    "get_shared_insightface_adapter",
    "get_suggestion_extension_service",
    "get_suggestion_service",
    "get_suggestion_refresh_service",
    "get_cluster_repository",
    "get_observability_repository",
    "get_media_identity_service",
    "get_retention_policy_service",
    "get_retention_export_service",
    "get_retention_import_service",
    "get_retention_purge_service",
    "get_audit_repository",
    "get_merge_suggestion_repository",
    "build_cluster_service",
    "get_cluster_service",
    "get_cluster_service_builder",
    "get_cluster_service_builder_clustering",
    "get_scan_service_builder",
    "get_scan_queue_service_factory",
    "get_scan_queue_service",
    "get_scan_queue_service_optional",
    "get_scan_queue_repo",
    "get_job_repo",
    "get_job_service",
    "get_job_service_dependency",
    "get_persisted_cluster_job_service",
    "get_persisted_cluster_job_service_clustering",
    "get_persisted_job_service",
    # Service protocols
    "RetentionPolicyServiceProtocol",
    "RetentionExportServiceProtocol",
    "TenantImportServiceProtocol",
    "RetentionPurgeServiceProtocol",
    "AuditRepositoryProtocol",
    # Stores
    "InMemoryJobService",
    "DecisionStore",
    "MediaIdentityService",
    "get_decision_store",
]
