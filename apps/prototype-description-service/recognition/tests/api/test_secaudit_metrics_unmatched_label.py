"""Regression coverage for unmatched request metric label cardinality."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from recognition.interface_adapters.http.middleware.metrics import (
    MetricsMiddleware,
    MetricsRegistry,
)


def test_distinct_unmatched_paths_share_one_histogram_label() -> None:
    registry = CollectorRegistry()
    app = FastAPI()
    app.add_middleware(MetricsMiddleware, metrics=MetricsRegistry(registry=registry))

    with TestClient(app) as client:
        assert client.get("/secaudit-missing-one").status_code == 404
        assert client.get("/secaudit-missing-two").status_code == 404

    samples = [
        sample
        for family in registry.collect()
        for sample in family.samples
        if sample.name.startswith("http_request_duration_seconds_")
    ]
    assert samples
    assert {sample.labels["path"] for sample in samples} == {"unmatched"}
    counts = [sample for sample in samples if sample.name == "http_request_duration_seconds_count"]
    assert len(counts) == 1
    assert counts[0].labels == {"method": "GET", "path": "unmatched", "status": "404"}
    assert counts[0].value == 2
