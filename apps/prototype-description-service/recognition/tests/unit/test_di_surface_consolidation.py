"""Guard for the DI-surface consolidation (Slice 7).

The legacy `http.dependencies` re-export module and the
`schemas.suggestion_details` leaf shim were deleted; `http.deps` is now the
single canonical DI surface (one `__all__`, no parallel surface to drift).
"""

from __future__ import annotations

import importlib

import pytest

# Representative providers, one from every definition submodule, that callers
# must be able to resolve from the single `deps` facade.
_CANONICAL_PROVIDERS = (
    "require_auth",  # deps.auth
    "require_write_access",
    "get_session",  # deps.session
    "get_clustering_session",
    "get_authenticated_tenant_id",  # deps.tenant
    "get_tenant_id",
    "get_cluster_service_builder",  # deps.services
    "get_retention_policy_service",
    "get_suggestion_refresh_service",
    "get_decision_store",  # deps.stores
)


def test_legacy_dependencies_module_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("recognition.interface_adapters.http.dependencies")


def test_suggestion_details_shim_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("recognition.interface_adapters.schemas.suggestion_details")


def test_deps_is_single_canonical_surface() -> None:
    deps = importlib.import_module("recognition.interface_adapters.http.deps")
    for name in _CANONICAL_PROVIDERS:
        assert hasattr(deps, name), f"deps facade missing provider: {name}"
        assert name in deps.__all__, f"provider not in deps.__all__: {name}"
