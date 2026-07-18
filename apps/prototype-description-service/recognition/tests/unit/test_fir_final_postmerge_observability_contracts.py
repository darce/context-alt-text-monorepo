"""RED contracts for FINALB-06 face-pipeline worker observability.

TESTS ONLY. Specify an infrastructure/application-neutral metrics observer
seam injected into ``FacePipelineFaceDetector`` via ``build_embedding_runtime``.
Must fail on current code until GREEN lands.

Finding FINALB-06:
  - Adapter must not import HTTP interface metrics middleware.
  - Worker process must own a process-local registry + configurable Prometheus
    HTTP exporter (mocked ``start_http_server`` in unit tests — never bind).
  - Wait observations and admission-timeout increments must reach the injected
    worker registry; exposition includes
    ``face_pipeline_submit_wait_seconds`` and
    ``face_pipeline_admission_timeouts_total``.
  - Low cardinality: no media/path/url labels.
  - Shared runtime singleton must not own process-specific metrics; the
    detector/composition seam does.

Canon: OBS-05, OBS-08, TEST-06, TEST-08; architecture: infrastructure ↛ HTTP.
Heuristics-canon @ 3e1135039ba1e5f98dc50ce46ee5b290e4bdde35.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import inspect
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image
from prometheus_client import CollectorRegistry, generate_latest

from recognition.application.embedding.detector import DetectionTimeoutError
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_PATH = (
    _SERVICE_ROOT
    / "recognition"
    / "infrastructure"
    / "embeddings"
    / "face_pipeline_adapter.py"
)
_RUNTIME_FACTORY_PATH = (
    _SERVICE_ROOT
    / "recognition"
    / "infrastructure"
    / "embeddings"
    / "runtime_factory.py"
)
_WORKER_PATH = _SERVICE_ROOT / "recognition" / "worker" / "scan_worker.py"
_HTTP_METRICS_IMPORT = "recognition.interface_adapters.http.middleware.metrics"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_settings_caches() -> None:
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_settings_caches() -> None:
    yield
    _clear_settings_caches()
    fpa.reset_shared_face_pipeline_runtime_for_tests()


def _align_dims_to_sface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGVECTOR_DIM", "128")
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    _clear_settings_caches()


def _mock_runtime(monkeypatch: pytest.MonkeyPatch) -> fpa.FacePipelineRuntime:
    _align_dims_to_sface(monkeypatch)
    manifest = fpa.sface_embedding_model_manifest()
    return fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=manifest,
        models_dir=DEFAULT_MODELS_DIR,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _metric_sample_value(
    registry: CollectorRegistry, sample_name: str, labels: dict[str, str] | None = None
) -> float:
    total = 0.0
    found = False
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name != sample_name:
                continue
            if labels is not None and dict(sample.labels) != labels:
                continue
            total += float(sample.value)
            found = True
    if not found:
        raise AssertionError(f"metric sample {sample_name!r} not found (labels={labels!r})")
    return total


def _detector_metrics_param_name() -> str | None:
    sig = inspect.signature(fpa.FacePipelineFaceDetector.__init__)
    for candidate in ("metrics", "metrics_observer", "observer", "face_pipeline_metrics"):
        if candidate in sig.parameters:
            return candidate
    return None


def _load_face_pipeline_metrics_cls() -> type:
    """GREEN module: recognition.observability.face_pipeline_metrics.FacePipelineMetrics."""
    try:
        mod = importlib.import_module("recognition.observability.face_pipeline_metrics")
    except ImportError as exc:
        pytest.fail(
            "FINALB-06: missing recognition.observability.face_pipeline_metrics "
            "(infrastructure/application-neutral metrics observers; must not live "
            f"under interface_adapters.http). ImportError: {exc}"
        )
    cls = getattr(mod, "FacePipelineMetrics", None)
    assert cls is not None, (
        "FINALB-06: face_pipeline_metrics module must export FacePipelineMetrics "
        "bound to a CollectorRegistry with submit-wait + admission-timeout series"
    )
    return cls


# ---------------------------------------------------------------------------
# FINALB-06 — dependency direction + injection seam
# ---------------------------------------------------------------------------


def test_adapter_source_does_not_import_http_metrics_middleware() -> None:
    """FINALB-06: infrastructure adapter must not depend on HTTP interface layer."""
    src = _ADAPTER_PATH.read_text(encoding="utf-8")
    if _HTTP_METRICS_IMPORT in src:
        pytest.fail(
            "FINALB-06: face_pipeline_adapter.py imports "
            f"{_HTTP_METRICS_IMPORT}. Inject a neutral metrics observer instead "
            "(architecture: infrastructure ↛ HTTP adapters)."
        )
    if "get_default_metrics" in src:
        pytest.fail(
            "FINALB-06: adapter must not late-import get_default_metrics from the HTTP "
            "middleware registry; pass an injected observer through the detector ctor "
            "and build_embedding_runtime."
        )


def test_face_pipeline_detector_accepts_metrics_observer_kwarg() -> None:
    """FINALB-06: detector construction seam accepts an injected metrics observer."""
    param = _detector_metrics_param_name()
    assert param is not None, (
        "FINALB-06: FacePipelineFaceDetector.__init__ must accept a metrics "
        "observer kwarg (metrics / metrics_observer / observer / face_pipeline_metrics). "
        f"Current signature: {inspect.signature(fpa.FacePipelineFaceDetector.__init__)}"
    )


def test_build_embedding_runtime_accepts_and_forwards_metrics() -> None:
    """FINALB-06: shared composition seam forwards metrics into the detector."""
    from recognition.infrastructure.embeddings import runtime_factory as rf

    sig = inspect.signature(rf.build_embedding_runtime)
    metrics_params = {
        name
        for name in ("metrics", "metrics_observer", "observer", "face_pipeline_metrics")
        if name in sig.parameters
    }
    assert metrics_params, (
        "FINALB-06: build_embedding_runtime must accept a metrics observer kwarg "
        "so worker/HTTP/inline sites can inject a process-local registry without "
        "the shared runtime singleton owning process-specific collectors. "
        f"Current signature: {sig}"
    )
    # Source must forward into FacePipelineFaceDetector (not drop the arg).
    src = _RUNTIME_FACTORY_PATH.read_text(encoding="utf-8")
    assert "FacePipelineFaceDetector" in src
    # At least one metrics-related name must appear near detector construction.
    assert re_search_metrics_forward(src), (
        "FINALB-06: runtime_factory must forward the metrics observer into "
        "FacePipelineFaceDetector(...)"
    )


def re_search_metrics_forward(src: str) -> bool:
    import re

    # Look for FacePipelineFaceDetector( ... metrics... ) allowing multi-line.
    return bool(
        re.search(
            r"FacePipelineFaceDetector\s*\([^)]*\b(metrics|metrics_observer|observer|face_pipeline_metrics)\b",
            src,
            flags=re.DOTALL,
        )
    )


@pytest.mark.asyncio
async def test_injected_observer_records_wait_and_admission_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FINALB-06: wait + timeout samples land on the *injected* registry.

    Not the HTTP process singleton. Labels stay low-cardinality (no media/path/url).
    """
    FacePipelineMetrics = _load_face_pipeline_metrics_cls()
    registry = CollectorRegistry()
    metrics = FacePipelineMetrics(registry=registry)

    param = _detector_metrics_param_name()
    assert param is not None, (
        "FINALB-06: detector must accept metrics observer before injection can be proven"
    )

    runtime = _mock_runtime(monkeypatch)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fp_obs")
    semaphore = asyncio.Semaphore(1)
    submitted = 0
    submit_lock = threading.Lock()
    release_workers = threading.Event()
    timeout_s = 0.05

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        nonlocal submitted
        with submit_lock:
            submitted += 1
        release_workers.wait(timeout=10.0)
        return []

    ctor_kwargs: dict[str, Any] = {
        "timeout": timeout_s,
        "executor": executor,
        "submit_semaphore": semaphore,
        param: metrics,
    }
    det = fpa.FacePipelineFaceDetector(runtime, **ctor_kwargs)
    monkeypatch.setattr(det, "_detect_sync", slow_detect)
    payload = _png_bytes(Image.new("RGB", (4, 4), color=(11, 12, 13)))

    try:
        t1 = asyncio.create_task(_expect_timeout(det, payload))
        for _ in range(100):
            with submit_lock:
                if submitted >= 1:
                    break
            await asyncio.sleep(0.02)
        await t1
        assert semaphore._value == 0

        with pytest.raises(DetectionTimeoutError):
            await asyncio.wait_for(det.detect([payload]), timeout=timeout_s * 8)

        timeouts = _metric_sample_value(registry, "face_pipeline_admission_timeouts_total")
        wait_count = _metric_sample_value(registry, "face_pipeline_submit_wait_seconds_count")
        assert timeouts >= 1, (
            f"FINALB-06: injected registry admission timeouts must increment; got {timeouts}"
        )
        assert wait_count >= 1, (
            f"FINALB-06: injected registry submit-wait count must increase; got {wait_count}"
        )

        # Exposition includes both series names (OBS-05 / OBS-08).
        exposition = generate_latest(registry).decode("utf-8")
        assert "face_pipeline_submit_wait_seconds" in exposition
        assert "face_pipeline_admission_timeouts_total" in exposition

        for metric in registry.collect():
            if metric.name not in {
                "face_pipeline_submit_wait_seconds",
                "face_pipeline_admission_timeouts",
            }:
                continue
            for sample in metric.samples:
                keys = set(sample.labels)
                assert "media_id" not in keys
                assert "path" not in keys
                assert "url" not in keys
    finally:
        release_workers.set()
        await asyncio.sleep(0.05)
        executor.shutdown(wait=False, cancel_futures=True)


async def _expect_timeout(det: fpa.FacePipelineFaceDetector, payload: bytes) -> None:
    with pytest.raises(DetectionTimeoutError):
        await det.detect([payload])


# ---------------------------------------------------------------------------
# FINALB-06 — worker process-local exporter
# ---------------------------------------------------------------------------


def test_scan_worker_config_exposes_metrics_export_policy() -> None:
    """FINALB-06: worker config owns exporter port + explicit disable switch.

    Port must be validated/bounded. Exporter is disabled only explicitly when
    policy chooses — not silently absent.
    """
    from recognition.worker.scan_worker import ScanWorkerConfig

    fields = {f.name: f for f in dataclasses.fields(ScanWorkerConfig)}
    port_field = next(
        (
            name
            for name in ("metrics_port", "prometheus_port", "metrics_http_port")
            if name in fields
        ),
        None,
    )
    assert port_field is not None, (
        "FINALB-06: ScanWorkerConfig must expose a metrics exporter port field "
        f"(metrics_port / prometheus_port / metrics_http_port). Fields: {sorted(fields)}"
    )
    # Optional explicit disable (bool) is allowed alongside port.
    # Port default must not be an unbound ephemeral bind in unit tests; GREEN
    # validates range (e.g. 1024–65535) at construction.


def test_scan_worker_starts_metrics_exporter_via_mocked_start_http_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FINALB-06: worker starts Prometheus HTTP exporter through a test seam.

    Never bind a real port in unit tests — mock ``start_http_server``.
    """
    from recognition.worker import scan_worker as sw

    started: list[dict[str, Any]] = []

    def _fake_start_http_server(port: int, addr: str = "", registry: Any = None, **kwargs: Any) -> None:
        started.append({"port": int(port), "addr": addr, "registry": registry, **kwargs})

    # Prefer patching the worker module's binding; fall back to prometheus_client.
    if hasattr(sw, "start_http_server"):
        monkeypatch.setattr(sw, "start_http_server", _fake_start_http_server)
    else:
        import prometheus_client

        monkeypatch.setattr(prometheus_client, "start_http_server", _fake_start_http_server)
        # Also patch common import sites the GREEN code may use.
        monkeypatch.setattr(
            "prometheus_client.start_http_server",
            _fake_start_http_server,
            raising=False,
        )

    # Build config with an explicit validated port when the field exists.
    config_kwargs: dict[str, Any] = {"postgres_dsn": "sqlite+aiosqlite:///:memory:"}
    field_names = {f.name for f in dataclasses.fields(sw.ScanWorkerConfig)}
    port_field = next(
        (n for n in ("metrics_port", "prometheus_port", "metrics_http_port") if n in field_names),
        None,
    )
    assert port_field is not None, (
        "FINALB-06: ScanWorkerConfig missing metrics port field (see prior test)"
    )
    config_kwargs[port_field] = 9199
    # If an enable flag exists, force it on.
    for flag in ("metrics_export_enabled", "enable_metrics_export", "metrics_enabled"):
        if flag in field_names:
            config_kwargs[flag] = True

    try:
        worker = sw.ScanWorker(sw.ScanWorkerConfig(**config_kwargs))
    except TypeError as exc:
        pytest.fail(f"FINALB-06: ScanWorkerConfig rejected metrics port kwargs: {exc}")

    # Preferred explicit seam; fall back to private helper names GREEN may use.
    start_fn = None
    for name in (
        "start_metrics_exporter",
        "start_prometheus_exporter",
        "_start_metrics_exporter",
        "_ensure_metrics_exporter",
    ):
        cand = getattr(worker, name, None)
        if callable(cand):
            start_fn = cand
            break
    assert start_fn is not None, (
        "FINALB-06: ScanWorker must expose start_metrics_exporter() (or equivalent) "
        "so unit tests can exercise exporter startup without run_forever(). "
        "Implementation must call prometheus_client.start_http_server with the "
        "process-local registry (mocked in tests — never bind a real port here)."
    )

    start_fn()
    assert started, (
        "FINALB-06: metrics exporter startup must call start_http_server "
        "(mocked); got no invocations — silent missing export reads as health (OBS-08)"
    )
    assert started[0]["port"] == 9199
    assert started[0]["registry"] is not None, (
        "FINALB-06: exporter must bind the worker process-local CollectorRegistry, "
        "not the implicit global default alone"
    )


def test_scan_worker_metrics_port_is_validated() -> None:
    """FINALB-06: invalid / unbounded ports fail closed at config construction."""
    from recognition.worker.scan_worker import ScanWorkerConfig

    field_names = {f.name for f in dataclasses.fields(ScanWorkerConfig)}
    port_field = next(
        (n for n in ("metrics_port", "prometheus_port", "metrics_http_port") if n in field_names),
        None,
    )
    assert port_field is not None, "FINALB-06: metrics port field required on ScanWorkerConfig"

    # Negative / zero / over-range must be rejected (or disabled only via explicit flag).
    for bad in (-1, 0, 70000, 999999):
        kwargs: dict[str, Any] = {"postgres_dsn": "sqlite+aiosqlite:///:memory:", port_field: bad}
        try:
            cfg = ScanWorkerConfig(**kwargs)
        except (ValueError, TypeError):
            continue
        # If construction allowed the value, a dedicated validator method must exist
        # and reject it when exporter is enabled.
        validate = getattr(cfg, "validate_metrics_port", None) or getattr(
            ScanWorkerConfig, "validate_metrics_port", None
        )
        if callable(validate):
            with pytest.raises((ValueError, TypeError)):
                validate(bad) if validate is getattr(ScanWorkerConfig, "validate_metrics_port", None) else validate()
            continue
        pytest.fail(
            f"FINALB-06: metrics port {bad} accepted without validation. "
            "Reject out-of-range ports at ScanWorkerConfig construction (or via "
            "explicit validator) so the worker cannot bind an unbound port."
        )


def test_worker_source_does_not_rely_on_api_metrics_endpoint_alone() -> None:
    """FINALB-06: worker is a separate process — API /metrics is not sufficient."""
    src = _WORKER_PATH.read_text(encoding="utf-8")
    # Worker may still import a neutral metrics module; it must not assume the
    # FastAPI /metrics route covers saturation for this process.
    if not (
        "start_http_server" in src or "metrics_port" in src or "prometheus_port" in src
    ):
        pytest.fail(
            "FINALB-06: scan_worker.py must own process-local Prometheus export "
            "(start_http_server + metrics_port). API /metrics only scrapes the API "
            "process registry and cannot surface worker face_pipeline saturation."
        )
