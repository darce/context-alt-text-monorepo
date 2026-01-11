"""
Dependency providers for recognition HTTP API.

This module re-exports from focused submodules for backward compatibility.
New code should import directly from the specific submodule:
- `deps.session` - Database session management
- `deps.auth` - Authentication and authorization
- `deps.services` - Service factory functions
- `deps.stores` - In-memory stores and lightweight services
"""

from __future__ import annotations

# Re-export authentication
from recognition.interface_adapters.http.deps.auth import (
    AuthContext,
    get_current_tenant,
    require_auth,
    require_write_access,
)

# Re-export service factories
from recognition.interface_adapters.http.deps.services import (
    build_cluster_service,
    get_cluster_repository,
    get_cluster_service,
    get_cluster_service_builder,
    get_job_repo,
    get_job_service,
    get_job_service_dependency,
    get_media_identity_service,
    get_observability_repository,
    get_persisted_job_service,
    get_scan_queue_repo,
    get_scan_queue_service,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    get_scan_service_builder,
    get_settings,
    get_shared_insightface_adapter,
    get_suggestion_service,
)

# Re-export session management
from recognition.interface_adapters.http.deps.session import (
    get_observability_session,
    get_optional_session,
    get_session,
)

# Re-export stores and lightweight services
from recognition.interface_adapters.http.deps.stores import (
    DecisionStore,
    InMemoryJobService,
    MediaIdentityService,
    get_decision_store,
)

__all__ = [
    # Session management
    "get_session",
    "get_optional_session",
    "get_observability_session",
    # Authentication
    "AuthContext",
    "require_auth",
    "get_current_tenant",
    "require_write_access",
    # Service factories
    "get_settings",
    "get_shared_insightface_adapter",
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
    "get_scan_queue_repo",
    "get_job_repo",
    "get_job_service",
    "get_job_service_dependency",
    "get_persisted_job_service",
    # Stores
    "InMemoryJobService",
    "DecisionStore",
    "MediaIdentityService",
    "get_decision_store",
]
