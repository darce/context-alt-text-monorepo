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
import re
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


# ---------------------------------------------------------------------------
# COORD-FINAL-01 — post-restart metrics continuity + exporter composition root
# ---------------------------------------------------------------------------
#
# Finding: each ScanWorker.__init__ builds a fresh FacePipelineMetrics(),
# __aenter__ starts the HTTP exporter, and a module-global flag prevents a
# second bind. After the outer _main restart loop constructs a replacement
# worker, detectors write to a new registry while the HTTP server still serves
# the first (dead) registry — post-restart metrics silently disappear. Unit
# tests that enter a worker also bind a real port 9108.
#
# Contracts: hoist one process metrics object before the restart loop, inject
# it into every ScanWorker, start the exporter once from the composition root
# (mocked start_http_server in tests), bind loopback by default, type the
# observer protocol (not Any).


def _metrics_ctor_param_names() -> tuple[str, ...]:
    return ("metrics", "metrics_observer", "observer", "face_pipeline_metrics")


def _scan_worker_metrics_param() -> str | None:
    from recognition.worker.scan_worker import ScanWorker

    sig = inspect.signature(ScanWorker.__init__)
    for name in _metrics_ctor_param_names():
        if name in sig.parameters:
            return name
    return None


def _scan_worker_config_addr_field() -> str | None:
    from recognition.worker.scan_worker import ScanWorkerConfig

    fields = {f.name for f in dataclasses.fields(ScanWorkerConfig)}
    for name in ("metrics_addr", "metrics_bind_address", "prometheus_addr", "metrics_host"):
        if name in fields:
            return name
    return None


def _patch_start_http_server(monkeypatch: pytest.MonkeyPatch, sw: Any) -> list[dict[str, Any]]:
    """Record start_http_server calls; never bind a real port."""
    started: list[dict[str, Any]] = []

    def _fake_start_http_server(
        port: int, addr: str = "", registry: Any = None, **kwargs: Any
    ) -> None:
        started.append({"port": int(port), "addr": addr, "registry": registry, **kwargs})

    if hasattr(sw, "start_http_server"):
        monkeypatch.setattr(sw, "start_http_server", _fake_start_http_server)
    else:
        import prometheus_client

        monkeypatch.setattr(prometheus_client, "start_http_server", _fake_start_http_server)
    return started


def _worker_config_kwargs(**overrides: Any) -> dict[str, Any]:
    """Build ScanWorkerConfig kwargs with export disabled unless overridden."""
    from recognition.worker.scan_worker import ScanWorkerConfig

    field_names = {f.name for f in dataclasses.fields(ScanWorkerConfig)}
    kwargs: dict[str, Any] = {"postgres_dsn": "sqlite+aiosqlite:///:memory:"}
    if "metrics_export_enabled" in field_names:
        kwargs["metrics_export_enabled"] = False
    port_field = next(
        (n for n in ("metrics_port", "prometheus_port", "metrics_http_port") if n in field_names),
        None,
    )
    if port_field is not None and port_field not in overrides:
        kwargs[port_field] = 9199
    kwargs.update(overrides)
    return kwargs


def _reset_worker_metrics_guard(sw: Any) -> None:
    """Clear process-wide exporter guard so unit tests stay isolated."""
    for name in ("_METRICS_EXPORTER_STARTED", "METRICS_EXPORTER_STARTED"):
        if hasattr(sw, name):
            setattr(sw, name, False)


def test_scan_worker_accepts_injected_metrics_observer() -> None:
    """COORD-FINAL-01: ScanWorker construction accepts an injected metrics observer.

    Default construction may still create one for direct use, but the restart
    composition path must be able to inject a process-hoisted instance.
    """
    param = _scan_worker_metrics_param()
    assert param is not None, (
        "COORD-FINAL-01: ScanWorker.__init__ must accept a metrics observer kwarg "
        f"({', '.join(_metrics_ctor_param_names())}) so _main can hoist one "
        "FacePipelineMetrics across the outer restart loop. "
        f"Current signature: {inspect.signature(__import__('recognition.worker.scan_worker', fromlist=['ScanWorker']).ScanWorker.__init__)}"
    )


def test_face_pipeline_metrics_observer_protocol_is_typed_not_any() -> None:
    """COORD-FINAL-01: neutral FacePipelineMetricsObserver protocol (not Any).

    Protocol must expose observe_submit_wait(float) and record_admission_timeout().
    Adapter + factory signatures must annotate against the protocol, not Any.
    """
    try:
        mod = importlib.import_module("recognition.observability.face_pipeline_metrics")
    except ImportError as exc:
        pytest.fail(
            "COORD-FINAL-01: recognition.observability.face_pipeline_metrics must "
            f"export FacePipelineMetricsObserver. ImportError: {exc}"
        )
    proto = getattr(mod, "FacePipelineMetricsObserver", None)
    assert proto is not None, (
        "COORD-FINAL-01: export FacePipelineMetricsObserver (typing.Protocol) with "
        "observe_submit_wait(float) and record_admission_timeout()"
    )
    # Structural members (Protocol methods or annotations).
    for method in ("observe_submit_wait", "record_admission_timeout"):
        assert method in getattr(proto, "__annotations__", {}) or callable(
            getattr(proto, method, None)
        ) or method in getattr(proto, "__protocol_attrs__", set()) or method in dir(proto), (
            f"COORD-FINAL-01: FacePipelineMetricsObserver must declare {method}()"
        )

    # Concrete metrics class should be a structural subtype.
    FacePipelineMetrics = getattr(mod, "FacePipelineMetrics", None)
    assert FacePipelineMetrics is not None
    concrete = FacePipelineMetrics()
    assert callable(getattr(concrete, "observe_submit_wait", None))
    assert callable(getattr(concrete, "record_admission_timeout", None))

    # Adapter + factory: metrics param must not be typed as bare Any.
    from recognition.infrastructure.embeddings import runtime_factory as rf

    det_hints = inspect.signature(fpa.FacePipelineFaceDetector.__init__).parameters
    rf_hints = inspect.signature(rf.build_embedding_runtime).parameters
    for label, params in (
        ("FacePipelineFaceDetector.__init__", det_hints),
        ("build_embedding_runtime", rf_hints),
    ):
        metrics_param = next(
            (params[n] for n in _metrics_ctor_param_names() if n in params),
            None,
        )
        assert metrics_param is not None, (
            f"COORD-FINAL-01: {label} must accept a metrics observer parameter"
        )
        ann = metrics_param.annotation
        ann_str = str(ann)
        # Reject plain Any / Any | None without a protocol name.
        if ann is inspect.Parameter.empty:
            pytest.fail(
                f"COORD-FINAL-01: {label} metrics param must be annotated with "
                "FacePipelineMetricsObserver | None (not untyped)"
            )
        if "Any" in ann_str and "FacePipelineMetricsObserver" not in ann_str:
            pytest.fail(
                f"COORD-FINAL-01: {label} metrics param is typed as {ann_str!r}; "
                "use FacePipelineMetricsObserver | None instead of Any"
            )
        if "FacePipelineMetricsObserver" not in ann_str:
            # Also accept string annotations / from __future__ postponed.
            src_name = (
                _ADAPTER_PATH
                if "FacePipelineFaceDetector" in label
                else _RUNTIME_FACTORY_PATH
            )
            src = src_name.read_text(encoding="utf-8")
            if "FacePipelineMetricsObserver" not in src:
                pytest.fail(
                    f"COORD-FINAL-01: {label} metrics annotation is {ann_str!r}; "
                    "require FacePipelineMetricsObserver protocol (not Any)"
                )


@pytest.mark.asyncio
async def test_worker_construct_and_aenter_do_not_bind_metrics_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COORD-FINAL-01: construction + __aenter__ must not start the exporter.

    Exporter startup belongs to the process composition root and is exercised
    via explicit start_metrics_exporter() with start_http_server mocked.
    Ordinary unit tests that enter a worker must not bind port 9108.
    """
    from recognition.worker import scan_worker as sw

    _reset_worker_metrics_guard(sw)
    started = _patch_start_http_server(monkeypatch, sw)

    # Stub runtime so aenter does not touch models/network.
    async def _fake_ensure(self: Any) -> None:
        return None

    async def _fake_heartbeat(self: Any) -> None:
        return None

    monkeypatch.setattr(sw.ScanWorker, "_ensure_embedding_runtime", _fake_ensure)
    monkeypatch.setattr(
        sw.ScanWorker, "_heartbeat_embedding_runtime_capability", _fake_heartbeat
    )

    # Export enabled so a RED auto-start path would actually call start_http_server.
    cfg_kwargs = _worker_config_kwargs(metrics_export_enabled=True, metrics_port=9199)
    worker = sw.ScanWorker(sw.ScanWorkerConfig(**cfg_kwargs))
    assert not started, (
        "COORD-FINAL-01: ScanWorker construction must not bind a metrics listener; "
        f"start_http_server already called: {started!r}"
    )

    async with worker:
        pass

    assert not started, (
        "COORD-FINAL-01: ScanWorker.__aenter__ must not start the Prometheus "
        "exporter (binds real port in unit tests; also couples restart to a "
        "one-shot module guard that freezes the first dead registry). Start "
        "the exporter once from the process composition root "
        f"(_main / explicit start_metrics_exporter). Got calls: {started!r}"
    )


@pytest.mark.asyncio
async def test_restart_workers_share_injected_metrics_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COORD-FINAL-01: replacement ScanWorkers must share one metrics instance.

    Two workers representing an outer restart must use the same object identity
    for the injected observer and forward that same object into the detector
    composition seam (build_embedding_runtime).
    """
    from recognition.worker import scan_worker as sw

    FacePipelineMetrics = _load_face_pipeline_metrics_cls()
    shared = FacePipelineMetrics()
    param = _scan_worker_metrics_param()
    assert param is not None, (
        "COORD-FINAL-01: cannot prove shared injection without ScanWorker metrics kwarg"
    )

    forwarded: list[Any] = []

    async def _capture_build(
        *,
        settings: Any,
        http_client: Any = None,
        adapter_provider: Any = None,
        metrics: Any = None,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        forwarded.append(metrics if metrics is not None else kwargs.get("metrics_observer"))
        from recognition.application.embedding.detector import UnavailableFaceDetector
        from recognition.application.embedding.generator import UnavailableEmbeddingGenerator

        return (
            UnavailableFaceDetector("coord-final-01-test"),
            UnavailableEmbeddingGenerator("coord-final-01-test"),
        )

    monkeypatch.setattr(sw, "build_embedding_runtime", _capture_build)
    monkeypatch.setattr(
        sw,
        "get_recognition_settings",
        lambda: type(
            "S",
            (),
            {
                "runtime_mode": "prod",
                "blob_root": Path("/tmp/coord-final-01-blobs"),
                "face_pipeline": type("FP", (), {"profile": "insightface"})(),
            },
        )(),
    )

    cfg = sw.ScanWorkerConfig(**_worker_config_kwargs(metrics_export_enabled=False))
    w1 = sw.ScanWorker(cfg, **{param: shared})
    w2 = sw.ScanWorker(cfg, **{param: shared})

    # Force embedding runtime init so metrics reach build_embedding_runtime.
    await w1._ensure_embedding_runtime()
    await w2._ensure_embedding_runtime()

    assert forwarded == [shared, shared], (
        "COORD-FINAL-01: both restart workers must inject the *same* process "
        f"metrics object into build_embedding_runtime; got {forwarded!r} "
        f"(shared id={id(shared)})"
    )

    # Explicit exporter seam (composition root) must bind that shared registry.
    _reset_worker_metrics_guard(sw)
    started = _patch_start_http_server(monkeypatch, sw)
    # Re-enable export on a config clone for the exporter call only.
    export_cfg = sw.ScanWorkerConfig(
        **_worker_config_kwargs(metrics_export_enabled=True, metrics_port=9199)
    )
    exporter_worker = sw.ScanWorker(export_cfg, **{param: shared})
    start_fn = getattr(exporter_worker, "start_metrics_exporter", None)
    assert callable(start_fn), (
        "COORD-FINAL-01: start_metrics_exporter() required as explicit composition seam"
    )
    start_fn()
    assert started, "COORD-FINAL-01: explicit exporter start must call start_http_server"
    assert started[0]["registry"] is shared.registry, (
        "COORD-FINAL-01: exporter must serve the hoisted shared registry, not a "
        "fresh per-worker CollectorRegistry"
    )


def test_main_hoists_process_metrics_outside_restart_loop() -> None:
    """COORD-FINAL-01: _main creates one metrics instance before the restart loop.

    Source contract (no execution): FacePipelineMetrics constructed outside the
    ``while True`` restart body and passed into each ScanWorker construction.
    """
    from recognition.worker import scan_worker as sw

    src = inspect.getsource(sw._main)
    assert "FacePipelineMetrics" in src or "face_pipeline_metrics" in src.lower(), (
        "COORD-FINAL-01: _main must hoist FacePipelineMetrics (or equivalent process "
        "metrics factory) so the outer restart loop reuses one registry"
    )
    # Heuristic: metrics construction must appear before the restart while-True,
    # and ScanWorker(...) inside the loop must pass metrics=.
    while_idx = src.find("while True:")
    assert while_idx != -1, "COORD-FINAL-01: expected outer restart `while True` in _main"

    before = src[:while_idx]
    after = src[while_idx:]
    metrics_before = (
        "FacePipelineMetrics(" in before
        or "face_pipeline_metrics" in before
        or re_search_process_metrics_hoist(before)
    )
    assert metrics_before, (
        "COORD-FINAL-01: create the process FacePipelineMetrics *before* the "
        "outer `while True` restart loop (not inside each ScanWorker())"
    )
    # Inside the loop: ScanWorker must receive the hoisted metrics.
    assert re.search(
        r"ScanWorker\s*\([^)]*\b(metrics|metrics_observer|observer|face_pipeline_metrics)\s*=",
        after,
        flags=re.DOTALL,
    ), (
        "COORD-FINAL-01: ScanWorker(...) inside the restart loop must inject the "
        "hoisted process metrics (metrics=/metrics_observer=/...)"
    )


def re_search_process_metrics_hoist(src: str) -> bool:
    import re

    return bool(
        re.search(
            r"(FacePipelineMetrics\s*\(|create_.*metrics|process_.*metrics\s*=)",
            src,
        )
    )


def test_exporter_binds_once_to_shared_registry_across_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COORD-FINAL-01: one bind per process to the shared registry; restart reuses it.

    A second worker (restart) must not call start_http_server again with a
    different registry. Composition root starts once; subsequent workers only
    reuse the already-served registry.
    """
    from recognition.worker import scan_worker as sw

    FacePipelineMetrics = _load_face_pipeline_metrics_cls()
    shared = FacePipelineMetrics()
    param = _scan_worker_metrics_param()
    assert param is not None, "COORD-FINAL-01: metrics injection required"

    _reset_worker_metrics_guard(sw)
    started = _patch_start_http_server(monkeypatch, sw)

    cfg = sw.ScanWorkerConfig(
        **_worker_config_kwargs(metrics_export_enabled=True, metrics_port=9199)
    )
    w1 = sw.ScanWorker(cfg, **{param: shared})
    w2 = sw.ScanWorker(cfg, **{param: shared})

    start1 = getattr(w1, "start_metrics_exporter", None)
    start2 = getattr(w2, "start_metrics_exporter", None)
    assert callable(start1) and callable(start2)

    start1()
    start2()  # restart path — must be a no-op for bind

    assert len(started) == 1, (
        "COORD-FINAL-01: exporter must bind exactly once per process; "
        f"got {len(started)} start_http_server calls: {started!r}"
    )
    assert started[0]["registry"] is shared.registry, (
        "COORD-FINAL-01: the single bind must expose the shared process registry"
    )


def test_scan_worker_metrics_bind_address_defaults_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COORD-FINAL-01: unauthenticated exporter binds 127.0.0.1 by default.

    Env: RECOGNITION_SCAN_WORKER_METRICS_ADDR (operators may override). Invalid
    / empty values fail closed at config construction.
    """
    from recognition.worker import scan_worker as sw

    addr_field = _scan_worker_config_addr_field()
    assert addr_field is not None, (
        "COORD-FINAL-01: ScanWorkerConfig must expose a metrics bind address field "
        "(metrics_addr / metrics_bind_address / prometheus_addr / metrics_host) "
        "defaulting to 127.0.0.1 via RECOGNITION_SCAN_WORKER_METRICS_ADDR so the "
        "exporter is not accidentally exposed on all interfaces"
    )

    monkeypatch.delenv("RECOGNITION_SCAN_WORKER_METRICS_ADDR", raising=False)
    # Prefer env-driven default when field uses default_factory; else check default.
    cfg = sw.ScanWorkerConfig(**_worker_config_kwargs())
    default_addr = getattr(cfg, addr_field)
    assert default_addr in {"127.0.0.1", "localhost"}, (
        f"COORD-FINAL-01: default {addr_field}={default_addr!r}; expected loopback "
        "127.0.0.1 (or localhost) — do not default to ''/0.0.0.0 all-interfaces"
    )

    monkeypatch.setenv("RECOGNITION_SCAN_WORKER_METRICS_ADDR", "127.0.0.1")
    cfg_env = sw.ScanWorkerConfig(**_worker_config_kwargs())
    assert getattr(cfg_env, addr_field) == "127.0.0.1"

    # Explicit operator override allowed.
    monkeypatch.setenv("RECOGNITION_SCAN_WORKER_METRICS_ADDR", "0.0.0.0")
    try:
        cfg_all = sw.ScanWorkerConfig(**_worker_config_kwargs())
        assert getattr(cfg_all, addr_field) == "0.0.0.0"
    except (ValueError, TypeError):
        # If 0.0.0.0 is rejected at config time, constructor override must still work.
        cfg_all = sw.ScanWorkerConfig(**_worker_config_kwargs(**{addr_field: "0.0.0.0"}))
        assert getattr(cfg_all, addr_field) == "0.0.0.0"

    # Empty / whitespace must fail closed.
    for bad in ("", "   "):
        monkeypatch.setenv("RECOGNITION_SCAN_WORKER_METRICS_ADDR", bad)
        try:
            sw.ScanWorkerConfig(**_worker_config_kwargs())
        except (ValueError, TypeError):
            continue
        # Direct field override path.
        try:
            sw.ScanWorkerConfig(**_worker_config_kwargs(**{addr_field: bad}))
        except (ValueError, TypeError):
            continue
        pytest.fail(
            f"COORD-FINAL-01: metrics bind address {bad!r} must be rejected "
            "(fail closed; no accidental all-interfaces bind via empty addr)"
        )

    # Exporter passes addr into start_http_server.
    param = _scan_worker_metrics_param()
    FacePipelineMetrics = _load_face_pipeline_metrics_cls()
    shared = FacePipelineMetrics()
    _reset_worker_metrics_guard(sw)
    started = _patch_start_http_server(monkeypatch, sw)
    monkeypatch.setenv("RECOGNITION_SCAN_WORKER_METRICS_ADDR", "127.0.0.1")
    export_kwargs = _worker_config_kwargs(metrics_export_enabled=True, metrics_port=9199)
    # Rebuild so env-driven addr is picked up when field uses default_factory.
    cfg = sw.ScanWorkerConfig(**export_kwargs)
    # If default_factory already evaluated at import, force field.
    if getattr(cfg, addr_field) != "127.0.0.1":
        cfg = sw.ScanWorkerConfig(**{**export_kwargs, addr_field: "127.0.0.1"})

    ctor_kwargs = {param: shared} if param else {}
    if param is None:
        pytest.fail("COORD-FINAL-01: metrics injection required for exporter addr proof")
    worker = sw.ScanWorker(cfg, **ctor_kwargs)
    start_fn = getattr(worker, "start_metrics_exporter", None)
    assert callable(start_fn)
    start_fn()
    assert started, "COORD-FINAL-01: expected mocked start_http_server invocation"
    assert started[0].get("addr") in {"127.0.0.1", "localhost"}, (
        "COORD-FINAL-01: start_http_server must receive the loopback bind address "
        f"(got {started[0]!r}); prometheus defaults to all interfaces when addr=''"
    )
