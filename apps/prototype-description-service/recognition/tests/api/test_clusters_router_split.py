"""Slice 6 guard: the ``clusters.py`` god-router split into 4 concern routers.

Pins the invariant that the split preserves the full cluster route surface and
that each concern router (`clusters_admission`, `clusters_snapshot`,
`clusters_topology`, `clusters_maintenance`) is a non-empty, importable
`APIRouter` whose paths form a disjoint partition of the original surface. The
monolithic `clusters` module must be gone (greenfield: delete-over-shim).
"""

from __future__ import annotations

import importlib

import pytest

EXPECTED_CLUSTER_ROUTES: set[tuple[str, str]] = {
    ("POST", "/clustering/jobs"),
    ("POST", "/clusters/recover-orphans"),
    ("GET", "/clusters"),
    ("GET", "/tenants/{tenant_uuid}/clusters/snapshot"),
    ("GET", "/tenants/{tenant_uuid}/clusters/targeted-snapshot"),
    ("GET", "/tenants/{tenant_uuid}/clusters/delta"),
    ("GET", "/clusters/top-unlabeled"),
    ("GET", "/clusters/{cluster_id}/members"),
    ("POST", "/clusters/{cluster_id}/dismiss"),
    ("DELETE", "/clusters/{cluster_id}/dismiss"),
    ("PATCH", "/clusters/{cluster_id}"),
    ("POST", "/clusters/create-for-identity"),
    ("POST", "/clusters/{cluster_id}/merge"),
    ("POST", "/clusters/{cluster_id}/split"),
    ("POST", "/topology-commands/split"),
    ("POST", "/clusters/reassign"),
    ("POST", "/clusters/revert-merge"),
    ("POST", "/clusters/{cluster_id}/assign"),
    ("PATCH", "/clusters/{cluster_id}/representatives/{representative_id}/pin"),
    ("GET", "/clusters/centroid-health"),
    ("POST", "/clusters/maintenance/refresh-centroids"),
}


def _routes(router) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in router.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.add((method, route.path))
    return out


def test_concern_routers_partition_cluster_surface() -> None:
    from recognition.interface_adapters.http.routers import (
        clusters_admission,
        clusters_maintenance,
        clusters_snapshot,
        clusters_topology,
    )

    concern_sets = [
        _routes(clusters_admission.router),
        _routes(clusters_snapshot.router),
        _routes(clusters_topology.router),
        _routes(clusters_maintenance.router),
    ]
    assert all(concern_sets), "every concern router must own at least one route"

    union: set[tuple[str, str]] = set().union(*concern_sets)
    total = sum(len(s) for s in concern_sets)
    assert len(union) == total, "concern routers must own disjoint route sets"
    assert union == EXPECTED_CLUSTER_ROUTES


def test_monolith_clusters_module_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("recognition.interface_adapters.http.routers.clusters")


def test_aggregate_router_serves_all_cluster_routes() -> None:
    from recognition.interface_adapters.http.router import router

    assert EXPECTED_CLUSTER_ROUTES <= _routes(router)
