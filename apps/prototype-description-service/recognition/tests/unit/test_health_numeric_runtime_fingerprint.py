"""Health detail publishes the complete numeric runtime fingerprint."""

import json

import pytest

from recognition.application.health import (
    CheckResult,
    HealthStatus,
    _with_numeric_runtime_fingerprint,
)
from recognition.infrastructure import face_pipeline
from recognition.infrastructure.face_pipeline import NumericRuntimeFingerprint


def _fingerprint(*, hdbscan_version: str = "0.8.44") -> NumericRuntimeFingerprint:
    return NumericRuntimeFingerprint(
        opencv_version="5.0.0.93",
        opencv_major=5,
        onnxruntime_version="1.28.0",
        numpy_version="2.5.1",
        scipy_version="1.18.0",
        pillow_version="12.3.0",
        hdbscan_version=hdbscan_version,
        pgvector_version="0.5.0",
        opencv_distribution_versions=(
            ("opencv-python", "5.0.0.93"),
            ("opencv-contrib-python-headless", "5.0.0.93"),
        ),
    )


def _result(detail: str = "original cache detail") -> CheckResult:
    return CheckResult("model_cache", HealthStatus.OK, detail)


def _fingerprint_json(detail: str) -> tuple[str, dict[str, object]]:
    marker = "; numeric_runtime_fingerprint="
    assert marker in detail
    encoded = detail.split(marker, maxsplit=1)[1]
    assert detail.endswith(encoded)
    return encoded, json.loads(encoded)


def test_health_detail_publishes_every_numeric_runtime_version_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = _fingerprint()
    monkeypatch.setattr(face_pipeline, "numeric_runtime_fingerprint", lambda: fingerprint)

    result = _with_numeric_runtime_fingerprint(_result())

    assert result.detail.startswith("original cache detail; numeric_runtime_fingerprint=")
    encoded, payload = _fingerprint_json(result.detail)
    assert set(payload) == {
        "opencv_version",
        "opencv_major",
        "onnxruntime_version",
        "numpy_version",
        "scipy_version",
        "pillow_version",
        "hdbscan_version",
        "pgvector_version",
        "opencv_distribution_versions",
        "comparison_token",
    }
    assert payload == {
        "opencv_version": fingerprint.opencv_version,
        "opencv_major": fingerprint.opencv_major,
        "onnxruntime_version": fingerprint.onnxruntime_version,
        "numpy_version": fingerprint.numpy_version,
        "scipy_version": fingerprint.scipy_version,
        "pillow_version": fingerprint.pillow_version,
        "hdbscan_version": fingerprint.hdbscan_version,
        "pgvector_version": fingerprint.pgvector_version,
        "opencv_distribution_versions": [
            list(distribution) for distribution in fingerprint.opencv_distribution_versions
        ],
        "comparison_token": fingerprint.comparability_token,
    }
    assert payload["comparison_token"] == fingerprint.comparability_token
    fingerprint_fields = {key: value for key, value in payload.items() if key != "comparison_token"}
    fingerprint_fields["opencv_distribution_versions"] = tuple(
        tuple(distribution) for distribution in payload["opencv_distribution_versions"]
    )
    assert NumericRuntimeFingerprint(**fingerprint_fields) == fingerprint
    assert result.detail.endswith(encoded)


def test_hdbscan_runtime_change_updates_health_fingerprint_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _fingerprint()
    changed = _fingerprint(hdbscan_version="0.8.45")
    fingerprints = iter((baseline, changed))
    monkeypatch.setattr(face_pipeline, "numeric_runtime_fingerprint", lambda: next(fingerprints))

    baseline_result = _with_numeric_runtime_fingerprint(_result())
    changed_result = _with_numeric_runtime_fingerprint(_result())

    baseline_json, baseline_payload = _fingerprint_json(baseline_result.detail)
    changed_json, changed_payload = _fingerprint_json(changed_result.detail)
    assert baseline.comparability_token != changed.comparability_token
    assert baseline_payload["hdbscan_version"] != changed_payload["hdbscan_version"]
    assert baseline_payload["comparison_token"] != changed_payload["comparison_token"]
    assert baseline_json != changed_json
    assert {
        key: value for key, value in baseline_payload.items() if key not in {"hdbscan_version", "comparison_token"}
    } == {
        key: value for key, value in changed_payload.items() if key not in {"hdbscan_version", "comparison_token"}
    }


def test_health_detail_keeps_original_detail_when_fingerprint_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> NumericRuntimeFingerprint:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(face_pipeline, "numeric_runtime_fingerprint", fail)

    result = _with_numeric_runtime_fingerprint(_result("cache passed"))

    assert result.detail == "cache passed; numeric_runtime_fingerprint_unavailable=RuntimeError"
