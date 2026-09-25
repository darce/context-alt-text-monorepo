"""Production registration regressions for deferred cluster routes."""

from __future__ import annotations

from fastapi import FastAPI


def _route_pairs(app: FastAPI) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        for method in methods:
            if method not in {"HEAD", "OPTIONS"}:
                routes.add((method, route.path))
    return routes


def test_production_app_registers_both_deferred_cluster_routes() -> None:
    from api.main import app

    expected = {
        ("GET", "/recognition/clusters/{cluster_id}/merge-candidates"),
        ("POST", "/recognition/clusters/{cluster_id}/revert-merge"),
    }
    missing = expected - _route_pairs(app)
    assert not missing, f"production api.main app is missing cluster routes: {sorted(missing)}"
