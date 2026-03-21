"""
Dependency providers for recognition HTTP API.

This package contains focused dependency modules:
- auth: Authentication and authorization
- services: Service factory functions
- session: Database session management
- stores: In-memory stores and lightweight services
- tenant: Tenant ID resolution

For backward compatibility, you may also import from the parent `dependencies` module.
"""

from recognition.interface_adapters.http.deps.auth import (
    AuthContext,
    get_current_tenant,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.services import (
    build_cluster_service,
    get_cluster_repository,
    get_cluster_service,
    get_cluster_service_builder,
    get_job_service,
    get_job_service_dependency,
    get_media_identity_service,
    get_observability_repository,
    get_persisted_cluster_job_service,
    get_persisted_job_service,
    get_scan_queue_service,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    get_scan_service_builder,
    get_settings,
    get_shared_insightface_adapter,
    get_suggestion_extension_service,
    get_suggestion_service,
)
from recognition.interface_adapters.http.deps.session import (
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
    get_tenant_id,
    get_tenant_id_optional,
)

__all__ = [
    # Auth
    "AuthContext",
    "require_auth",
    "get_current_tenant",
    "require_write_access",
    # Session
    "get_session",
    "get_optional_session",
    "get_observability_session",
    # Services
    "get_settings",
    "get_shared_insightface_adapter",
    "get_suggestion_extension_service",
    "get_suggestion_service",
    "get_cluster_repository",
    "get_observability_repository",
    "get_media_identity_service",
    "build_cluster_service",
    "get_cluster_service",
    "get_cluster_service_builder",
    "get_scan_service_builder",
    "get_scan_queue_service_factory",
    "get_scan_queue_service",
    "get_scan_queue_service_optional",
    "get_job_service",
    "get_job_service_dependency",
    "get_persisted_cluster_job_service",
    "get_persisted_job_service",
    # Stores
    "InMemoryJobService",
    "DecisionStore",
    "MediaIdentityService",
    "get_decision_store",
    # Tenant
    "get_tenant_id",
    "get_tenant_id_optional",
]
