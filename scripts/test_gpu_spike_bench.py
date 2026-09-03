"""Unit tests for scripts/gpu_spike_bench.py — zero OCI/GPU/network [TEST-01]."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# Allow `import gpu_spike_bench` when pytest collects from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gpu_spike_bench as bench
from gpu_spike_bench import (
    ARTIFACT_STATUS_MEASURED,
    ARTIFACT_STATUS_PENDING,
    LIVE_MEASUREMENT_SOURCE,
    WARM_START_P95_TARGET_SECONDS,
    BenchError,
    ColdBootResult,
    HttpResponse,
    PhaseError,
    ThroughputResult,
    WarmStartResult,
    assert_no_null_measurement_values,
    build_spike_artifact,
    default_artifact_path,
    dry_run_plan,
    endpoint_ready,
    main,
    mean,
    percentile,
    run_bench,
    run_cold_boot,
    run_throughput,
    run_warm_start_loop,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += float(seconds)

    def advance(self, seconds: float) -> None:
        self._now += float(seconds)


class FakeActuator:
    """State machine STOPPED ↔ RUNNING; optional fail injection."""

    def __init__(self, initial: str = "STOPPED") -> None:
        self.state = initial.upper()
        self.starts: list[str] = []
        self.stops: list[str] = []
        self.gets: list[str] = []
        self.fail_on_start_after: int | None = None
        self.fail_on_stop_after: int | None = None
        self._start_count = 0
        self._stop_count = 0
        # Delay transitions by N get polls (0 = immediate).
        self.start_polls_until_running = 0
        self.stop_polls_until_stopped = 0
        self._pending_start_polls = 0
        self._pending_stop_polls = 0

    def verify_bench_dedicated(self, instance_id: str) -> None:
        del instance_id

    def describe_instance(self, instance_id: str) -> bench.InstanceObservation:
        del instance_id
        return bench.InstanceObservation("test-shape", 400, 120)

    def start(self, instance_id: str) -> None:
        self._start_count += 1
        if self.fail_on_start_after is not None and self._start_count > self.fail_on_start_after:
            raise RuntimeError(f"injected start failure for {instance_id}")
        self.starts.append(instance_id)
        if self.start_polls_until_running <= 0:
            self.state = "RUNNING"
        else:
            self.state = "STARTING"
            self._pending_start_polls = self.start_polls_until_running

    def stop(self, instance_id: str) -> None:
        self._stop_count += 1
        if self.fail_on_stop_after is not None and self._stop_count > self.fail_on_stop_after:
            raise RuntimeError(f"injected stop failure for {instance_id}")
        self.stops.append(instance_id)
        if self.stop_polls_until_stopped <= 0:
            self.state = "STOPPED"
        else:
            self.state = "STOPPING"
            self._pending_stop_polls = self.stop_polls_until_stopped

    def get_lifecycle_state(self, instance_id: str) -> str:
        self.gets.append(instance_id)
        if self.state == "STARTING":
            self._pending_start_polls -= 1
            if self._pending_start_polls <= 0:
                self.state = "RUNNING"
        elif self.state == "STOPPING":
            self._pending_stop_polls -= 1
            if self._pending_stop_polls <= 0:
                self.state = "STOPPED"
        return self.state


class FakeHttp:
    """Ready after N readiness probes; records chat completions."""

    def __init__(self, *, ready_after: int = 0, completion_status: int = 200) -> None:
        self.ready_after = ready_after
        self.completion_status = completion_status
        self._ready_probes = 0
        self.gets: list[str] = []
        self.get_headers: list[dict[str, str] | None] = []
        self.posts: list[dict[str, Any]] = []
        self.fail_nth_post: int | None = None
        self._post_count = 0
        # Per-call wall-clock advance injected via clock from outside tests.
        self.advance_clock: FakeClock | None = None
        self.completion_duration_s: float = 0.5

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse:
        self.gets.append(url)
        self.get_headers.append(headers)
        self._ready_probes += 1
        if self.advance_clock is not None:
            self.advance_clock.advance(0.01)
        if self._ready_probes > self.ready_after and url.rstrip("/").endswith("/v1/models"):
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "data": [
                            {"id": "m"},
                            {"id": "test-model"},
                            {"id": "expected"},
                            {"id": "Qwen3-VL-30B-A3B-Instruct"},
                        ]
                    }
                ).encode(),
            )
        return HttpResponse(status_code=503, body=b"not ready")

    def post(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        self._post_count += 1
        self.posts.append({"url": url, "json": json_body, "headers": headers})
        if self.advance_clock is not None:
            self.advance_clock.advance(self.completion_duration_s)
        if self.fail_nth_post is not None and self._post_count == self.fail_nth_post:
            return HttpResponse(status_code=500, body=b"boom")
        if url.rstrip("/").endswith("/v1/chat/completions"):
            # Readiness fallback (text-only) or real image completion.
            if self._ready_probes <= self.ready_after and "image_url" not in str(json_body):
                return HttpResponse(status_code=503, body=b"not ready")
            return HttpResponse(
                status_code=self.completion_status,
                body=json.dumps(
                    {
                        "model": json_body["model"],
                        "choices": [{"message": {"content": "A test image description."}}],
                    }
                ).encode(),
            )
        return HttpResponse(status_code=404, body=b"missing")


def _png_bytes() -> bytes:
    # Minimal valid-ish PNG header for media-type detection.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _write_images(tmp_path: Path, n: int = 2) -> list[Path]:
    paths: list[Path] = []
    for i in range(n):
        p = tmp_path / f"img-{i}.png"
        p.write_bytes(_png_bytes())
        paths.append(p)
    return paths


def _live_cli_args(image: Path) -> list[str]:
    return [
        "--instance-ocid",
        "test-instance",
        "--endpoint-url",
        "https://gpu.example",
        "--allow-endpoint-host",
        "gpu.example",
        "--live",
        "--image",
        str(image),
        "--model-id",
        "test-model",
        "--boot-volume-gb",
        "400",
        "--vpus-per-gb",
        "120",
        "--shape",
        "test-shape",
        "--quantization",
        "test-quantization",
        "--model-path",
        "/test/model.gguf",
    ]


# ---------------------------------------------------------------------------
# Percentile / mean [PERF-01]
# ---------------------------------------------------------------------------


def test_percentile_p50_and_p95_linear_interpolation() -> None:
    samples = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(samples, 50) == 30.0
    # p95 on 5 samples: rank = 4 * 0.95 = 3.8 → 40 + 0.8*(50-40) = 48
    assert percentile(samples, 95) == pytest.approx(48.0)
    assert percentile(samples, 0) == 10.0
    assert percentile(samples, 100) == 50.0


def test_percentile_single_sample_and_empty() -> None:
    assert percentile([7.5], 95) == 7.5
    with pytest.raises(ValueError):
        percentile([], 50)


def test_mean_of_samples() -> None:
    assert mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        mean([])


# ---------------------------------------------------------------------------
# Artifact emission
# ---------------------------------------------------------------------------


def test_build_spike_artifact_zero_nulls_and_status_flip() -> None:
    cold = ColdBootResult(
        cold_boot_seconds=120.0,
        model_load_seconds=40.0,
        instance_running_seconds=80.0,
        endpoint_ready_seconds=40.0,
    )
    warm = WarmStartResult(
        samples=[50.0, 55.0, 60.0, 70.0, 80.0],
        shutdown_samples=[4.0, 5.0, 6.0, 7.0, 8.0],
        p50=60.0,
        p95=78.0,
        meets_target=True,
        target_seconds=90.0,
    )
    thruput = ThroughputResult(
        samples=[1.0, 1.2, 1.5],
        p50=1.2,
        p95=1.47,
        mean=1.233333,
    )
    artifact = build_spike_artifact(
        cold_boot=cold,
        warm_start=warm,
        throughput=thruput,
        model_id="Qwen3-VL-30B-A3B-Instruct",
        shape="test-shape",
        quantization="test-quantization",
        model_path="/test/model.gguf",
        boot_volume_gb=400,
        vpus_per_gb=120,
        instance_observation=bench.InstanceObservation(
            shape="test-shape",
            boot_volume_gb=400,
            vpus_per_gb=120,
        ),
        a10_quota_confirmed=True,
    )
    assert artifact["schema"] == "acx-gpu-spike/v2"
    assert artifact["status"] == ARTIFACT_STATUS_MEASURED
    assert artifact["status"] != ARTIFACT_STATUS_PENDING
    measurements = artifact["measurements"]
    for key in (
        "cold_boot_seconds",
        "stopped_to_warm_start_seconds",
        "warm_start_p95_seconds",
        "model_load_seconds",
        "seconds_per_image",
    ):
        assert measurements[key]["value"] is not None
        assert measurements[key]["source"] == LIVE_MEASUREMENT_SOURCE
    assert measurements["cold_boot_seconds"]["value"] == 120.0
    assert measurements["model_load_seconds"]["value"] == 40.0
    assert measurements["stopped_to_warm_start_seconds"]["value"] == 60.0
    assert measurements["warm_start_p95_seconds"]["value"] == 78.0
    assert measurements["warm_start_p95_seconds"]["target_seconds"] == 90
    assert measurements["warm_start_p95_seconds"]["meets_target"] is True
    assert measurements["seconds_per_image"]["p50"] == 1.2
    assert measurements["seconds_per_image"]["p95"] == 1.47
    assert measurements["seconds_per_image"]["mean"] == pytest.approx(1.233333)
    assert measurements["seconds_per_image"]["samples"] == [1.0, 1.2, 1.5]
    assert measurements["shutdown_seconds"]["samples"] == [4.0, 5.0, 6.0, 7.0, 8.0]
    provenance = artifact["provenance"]
    assert "shape" not in artifact
    assert "boot_volume_size_in_gbs" not in artifact
    assert "boot_volume_vpus_per_gb" not in artifact
    assert "quantization" not in artifact["measurement_candidate"]
    assert "model_path" not in artifact["measurement_candidate"]
    assert provenance["shape"] == {
        "operator_asserted": "test-shape",
        "oci_observed": "test-shape",
        "source": "oci_observed",
        "matches": True,
    }
    assert provenance["boot_volume_gb"]["oci_observed"] == 400
    assert provenance["boot_volume_gb"]["source"] == "oci_observed"
    assert provenance["vpus_per_gb"]["oci_observed"] == 120
    assert provenance["quantization"] == {
        "operator_asserted": "test-quantization",
        "source": "operator_asserted",
    }
    assert provenance["model_path"] == {
        "operator_asserted": "/test/model.gguf",
        "source": "operator_asserted",
    }
    assert "estimated_model_bytes_gb" not in artifact["measurement_candidate"]
    assert artifact["oci_capacity"]["a10_quota_confirmed"] is True
    assert artifact["phase_evidence"]["lifecycle_poll"]["retries"] == 0
    assert_no_null_measurement_values(artifact)


def test_build_spike_artifact_asserted_only_is_not_measurement_complete() -> None:
    artifact = build_spike_artifact(
        cold_boot=ColdBootResult(1, 0.5, 0.5, 0.5),
        warm_start=WarmStartResult([2], [1], 2, 2, True),
        throughput=ThroughputResult([3], 3, 3, 3),
        model_id="m",
        shape="asserted-shape",
        quantization="asserted-quantization",
        model_path="/asserted/model.gguf",
        boot_volume_gb=400,
        vpus_per_gb=120,
    )

    assert artifact["status"] == ARTIFACT_STATUS_PENDING
    for field in ("shape", "boot_volume_gb", "vpus_per_gb"):
        assert artifact["provenance"][field]["source"] == "operator_asserted"
        assert artifact["provenance"][field]["oci_observed"] is None


def test_build_spike_artifact_records_provenance_mismatch_loudly() -> None:
    artifact = build_spike_artifact(
        cold_boot=ColdBootResult(1, 0.5, 0.5, 0.5),
        warm_start=WarmStartResult([2], [1], 2, 2, True),
        throughput=ThroughputResult([3], 3, 3, 3),
        model_id="m",
        shape="asserted-shape",
        quantization="asserted-quantization",
        model_path="/asserted/model.gguf",
        boot_volume_gb=400,
        vpus_per_gb=120,
        instance_observation=bench.InstanceObservation(
            shape="observed-shape",
            boot_volume_gb=750,
            vpus_per_gb=60,
        ),
    )

    assert artifact["status"] == bench.ARTIFACT_STATUS_PROVENANCE_MISMATCH
    for field in ("shape", "boot_volume_gb", "vpus_per_gb"):
        provenance = artifact["provenance"][field]
        assert provenance["operator_asserted"] != provenance["oci_observed"]
        assert provenance["source"] == "oci_observed"
        assert provenance["matches"] is False


def test_assert_no_null_measurement_values_rejects_nulls() -> None:
    with pytest.raises(BenchError, match="null"):
        assert_no_null_measurement_values(
            {
                "measurements": {
                    "cold_boot_seconds": {
                        "value": None,
                        "source": "pending",
                    }
                }
            }
        )


def test_warm_start_pass_fail_vs_target() -> None:
    pass_result = WarmStartResult(
        samples=[10.0, 20.0, 30.0],
        shutdown_samples=[1.0, 2.0, 3.0],
        p50=20.0,
        p95=29.0,
        meets_target=True,
        target_seconds=90.0,
    )
    fail_result = WarmStartResult(
        samples=[80.0, 90.0, 100.0, 110.0, 120.0],
        shutdown_samples=[1.0, 2.0, 3.0, 4.0, 5.0],
        p50=100.0,
        p95=118.0,
        meets_target=False,
        target_seconds=90.0,
    )
    pass_art = build_spike_artifact(
        cold_boot=ColdBootResult(1, 0.5, 0.5, 0.5),
        warm_start=pass_result,
        throughput=ThroughputResult([1.0], 1.0, 1.0, 1.0),
        model_id="m",
        shape="test-shape",
        quantization="test-quantization",
        model_path="/test/model.gguf",
        boot_volume_gb=400,
        vpus_per_gb=120,
    )
    fail_art = build_spike_artifact(
        cold_boot=ColdBootResult(1, 0.5, 0.5, 0.5),
        warm_start=fail_result,
        throughput=ThroughputResult([1.0], 1.0, 1.0, 1.0),
        model_id="m",
        shape="test-shape",
        quantization="test-quantization",
        model_path="/test/model.gguf",
        boot_volume_gb=400,
        vpus_per_gb=120,
    )
    assert pass_art["measurements"]["warm_start_p95_seconds"]["meets_target"] is True
    assert fail_art["measurements"]["warm_start_p95_seconds"]["meets_target"] is False
    assert fail_art["measurements"]["warm_start_p95_seconds"]["value"] > WARM_START_P95_TARGET_SECONDS


def test_default_artifact_path_identifies_run_configuration_and_timestamp() -> None:
    path = default_artifact_path(
        model_id="Example Org/Vision Model",
        shape="VM.GPU.A10.1",
        quantization="Q4_K_M",
        boot_volume_gb=400,
        vpus_per_gb=120,
        now=datetime(2026, 7, 12, 13, 14, 15, tzinfo=UTC),
    )
    assert path == Path(
        "docs/tasks/vlm/VLM-3-gpu-spike-20260712T131415Z-example-org-vision-model-vm-gpu-a10-1-q4-k-m-400gb-120vpu.json"
    )


def test_write_artifact_refuses_overwrite_unless_forced(tmp_path: Path) -> None:
    path = tmp_path / "spike.json"
    bench.write_artifact(path, {"run": 1})

    with pytest.raises(BenchError, match="already exists"):
        bench.write_artifact(path, {"run": 2})
    assert json.loads(path.read_text()) == {"run": 1}

    bench.write_artifact(path, {"run": 2}, force=True)
    assert json.loads(path.read_text()) == {"run": 2}


def test_committed_artifacts_only_reconstruct_filename_bounded_provenance() -> None:
    artifact_dir = Path(__file__).resolve().parents[1] / "docs" / "tasks" / "vlm"
    expected = {
        "VLM-3-gpu-spike-2026-07-14.json": {},
        "VLM-3-gpu-spike-2026-07-14-400gb.json": {
            "boot_volume_size_in_gbs": 400,
        },
        "VLM-3-gpu-spike-2026-07-14-400gb-60vpu.json": {
            "boot_volume_size_in_gbs": 400,
            "boot_volume_vpus_per_gb": 60,
        },
        "VLM-3-gpu-spike-2026-07-14-750gb-balanced.json": {
            "boot_volume_size_in_gbs": 750,
            "boot_volume_performance_tier": "balanced",
        },
    }

    for filename, fields in expected.items():
        artifact = json.loads((artifact_dir / filename).read_text())
        assert artifact["provenance_note"] == "reconstructed from filename"
        assert artifact["measurements"]["seconds_per_image"]["sample_size_note"] == "n=1 image"
        for key, value in fields.items():
            assert artifact[key] == value

    assert "boot_volume_size_in_gbs" not in json.loads((artifact_dir / "VLM-3-gpu-spike-2026-07-14.json").read_text())
    assert "boot_volume_vpus_per_gb" not in json.loads(
        (artifact_dir / "VLM-3-gpu-spike-2026-07-14-400gb.json").read_text()
    )
    assert "boot_volume_vpus_per_gb" not in json.loads(
        (artifact_dir / "VLM-3-gpu-spike-2026-07-14-750gb-balanced.json").read_text()
    )


def test_documentation_dispositions_preserve_evidence_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs" / "tasks" / "vlm"
    activation = (docs / "VLM-3-7c-activation-evidence.md").read_text()
    memo = (docs / "VLM-3-gpu-detailed-tier-decision-memo.md").read_text()
    report = (docs / "VLM-3-7a-spike-findings.md").read_text()
    topology = (repo_root / "infra" / "oci" / "INFRA-TOPOLOGY.md").read_text()

    assert "production reaper timer install +\nbackend deploy are open" in activation
    assert "memo FINAL" not in activation
    assert "memo remains provisional" in activation
    assert "Status: provisional; license verdict pending; measured JSON reports not regenerated" in memo
    assert "n=3 warm starts" in report
    assert "n=1 image" in report
    assert "Throughput is excellent" not in report
    assert "400 GB @ 30 VPU | no committed artifact; unsupported" in report
    assert "acx-oci.env" not in topology
    assert "oci-lib.sh" not in topology
    assert "variables.tf" in topology
    assert "gpu-lifecycle-install.sh" in topology
    assert "AVAILABLE and used by the 2026-07-14 spike host" in topology

    bench_script = repo_root / "scripts" / "gpu_spike_bench.py"
    assert bench_script.stat().st_mode & 0o111


# ---------------------------------------------------------------------------
# Phase behavior with fakes
# ---------------------------------------------------------------------------


def test_cold_boot_records_model_load_as_ready_minus_running() -> None:
    clock = FakeClock()
    actuator = FakeActuator("STOPPED")
    actuator.start_polls_until_running = 1
    http = FakeHttp(ready_after=1)
    http.advance_clock = clock

    # Drive time: each sleep advances; readiness probes also advance.
    result = run_cold_boot(
        actuator=actuator,
        http=http,
        clock=clock,
        instance_id="ocid1.instance.oc1..gpu",
        endpoint_url="http://gpu.example:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        poll_interval_seconds=1.0,
    )
    assert result.cold_boot_seconds > 0
    assert result.model_load_seconds >= 0
    assert result.model_load_seconds == pytest.approx(result.cold_boot_seconds - result.instance_running_seconds)
    assert actuator.state == "RUNNING"
    assert actuator.starts == ["ocid1.instance.oc1..gpu"]


@pytest.mark.parametrize("body", [b'{"data":[]}', b'{"data":[{"id":"other"}]}'])
def test_endpoint_ready_rejects_empty_or_wrong_model_list(body: bytes) -> None:
    class ModelsHttp(FakeHttp):
        def get(self, url: str, *, headers=None) -> HttpResponse:
            return HttpResponse(status_code=200, body=body)

    http = ModelsHttp()
    assert endpoint_ready(http, "https://gpu.example", model_id="expected") is False
    assert http.posts == []


def test_endpoint_ready_fallback_requires_expected_model() -> None:
    class FallbackHttp(FakeHttp):
        def get(self, url: str, *, headers=None) -> HttpResponse:
            return HttpResponse(status_code=503)

        def post(self, url: str, *, json_body, headers=None) -> HttpResponse:
            return HttpResponse(status_code=200, body=b'{"model":"other"}')

    assert endpoint_ready(FallbackHttp(), "https://gpu.example", model_id="expected") is False


def test_warm_start_loop_collects_samples_and_percentiles() -> None:
    clock = FakeClock()
    actuator = FakeActuator("RUNNING")
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    # Make each readiness probe take measurable time so samples > 0.
    http.completion_duration_s = 0.0

    result = run_warm_start_loop(
        actuator=actuator,
        http=http,
        clock=clock,
        instance_id="ocid1.instance.oc1..gpu",
        endpoint_url="http://gpu.example:8000",
        model_id="m",
        runs=3,
        poll_interval_seconds=0.5,
    )
    assert len(result.samples) == 3
    assert all(s >= 0 for s in result.samples)
    assert result.p50 == percentile(result.samples, 50)
    assert result.p95 == percentile(result.samples, 95)
    assert result.meets_target is (result.p95 <= WARM_START_P95_TARGET_SECONDS)
    assert len(actuator.stops) == 3
    assert len(actuator.starts) == 3


def test_warm_start_sample_excludes_shutdown_time() -> None:
    clock = FakeClock()
    actuator = FakeActuator("RUNNING")
    actuator.stop_polls_until_stopped = 3
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock

    result = run_warm_start_loop(
        actuator=actuator,
        http=http,
        clock=clock,
        instance_id="ocid1.instance.oc1..gpu",
        endpoint_url="http://gpu.example:8000",
        model_id="m",
        runs=1,
        poll_interval_seconds=0.5,
    )

    assert result.shutdown_samples == [pytest.approx(1.0)]
    assert result.samples == [pytest.approx(0.01)]


def test_throughput_posts_chat_completions_and_stats(tmp_path: Path) -> None:
    clock = FakeClock()
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    http.completion_duration_s = 1.5
    images = _write_images(tmp_path, n=3)
    result = run_throughput(
        http=http,
        clock=clock,
        endpoint_url="http://gpu.example:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        image_paths=images,
    )
    assert len(result.samples) == 3
    assert all(s == pytest.approx(1.5) for s in result.samples)
    assert result.mean == pytest.approx(1.5)
    assert result.p50 == pytest.approx(1.5)
    assert len(http.posts) == 3
    for post in http.posts:
        assert post["url"].endswith("/v1/chat/completions")
        content = post["json"]["messages"][1]["content"]
        assert any(part.get("type") == "image_url" for part in content)


def test_throughput_http_error_names_phase() -> None:
    clock = FakeClock()
    http = FakeHttp(completion_status=500)
    http.advance_clock = clock
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        images = _write_images(Path(td), n=1)
        with pytest.raises(PhaseError, match="throughput") as exc_info:
            run_throughput(
                http=http,
                clock=clock,
                endpoint_url="http://gpu.example:8000",
                model_id="m",
                image_paths=images,
            )
        assert exc_info.value.phase == "throughput"


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"model":"expected","choices":[{"message":{"content":""}}]}',
        b'{"model":"other","choices":[{"message":{"content":"caption"}}]}',
    ],
)
def test_throughput_rejects_invalid_completion_envelope(tmp_path: Path, body: bytes) -> None:
    class EnvelopeHttp(FakeHttp):
        def post(self, url: str, *, json_body, headers=None) -> HttpResponse:
            return HttpResponse(status_code=200, body=body)

    with pytest.raises(PhaseError, match="throughput"):
        run_throughput(
            http=EnvelopeHttp(),
            clock=FakeClock(),
            endpoint_url="https://gpu.example",
            model_id="expected",
            image_paths=_write_images(tmp_path, n=1),
        )


def test_throughput_records_valid_completion_envelope(tmp_path: Path) -> None:
    clock = FakeClock()
    http = FakeHttp()
    http.advance_clock = clock
    http.completion_duration_s = 0.25

    result = run_throughput(
        http=http,
        clock=clock,
        endpoint_url="https://gpu.example",
        model_id="expected",
        image_paths=_write_images(tmp_path, n=1),
    )

    assert result.samples == [pytest.approx(0.25)]


# ---------------------------------------------------------------------------
# Full run_bench orchestration
# ---------------------------------------------------------------------------


def test_run_bench_writes_artifact_and_stops_on_success(tmp_path: Path) -> None:
    clock = FakeClock()
    actuator = FakeActuator("STOPPED")
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    http.completion_duration_s = 0.25
    images = _write_images(tmp_path, n=2)
    out = tmp_path / "spike.json"

    result = run_bench(
        instance_ocid="ocid1.instance.oc1..gpu",
        endpoint_url="http://gpu.example:8000",
        model_id="Qwen3-VL-30B-A3B-Instruct",
        image_paths=images,
        warm_start_runs=2,
        actuator=actuator,
        http=http,
        clock=clock,
        artifact_out=out,
        boot_volume_gb=400,
        vpus_per_gb=120,
        shape="test-shape",
        quantization="test-quantization",
        model_path="/test/model.gguf",
        a10_quota_confirmed=True,
        poll_interval_seconds=0.1,
    )

    assert out.is_file()
    artifact = json.loads(out.read_text())
    assert artifact["status"] == ARTIFACT_STATUS_MEASURED
    assert_no_null_measurement_values(artifact)
    assert artifact["oci_capacity"]["a10_quota_confirmed"] is True
    assert artifact["provenance"]["boot_volume_gb"]["oci_observed"] == 400
    assert artifact["provenance"]["vpus_per_gb"]["oci_observed"] == 120
    assert result.warm_start_meets_target is True
    # finally STOP [RES-07]
    assert actuator.state == "STOPPED"
    assert actuator.stops  # at least warm-start + final


def test_run_bench_rejects_non_dedicated_instance_before_stop(tmp_path: Path) -> None:
    class NonDedicatedActuator(FakeActuator):
        def verify_bench_dedicated(self, instance_id: str) -> None:
            raise BenchError("dedicated tag mismatch")

    actuator = NonDedicatedActuator("RUNNING")

    with pytest.raises(PhaseError, match="dedicated"):
        run_bench(
            instance_ocid="test-instance",
            endpoint_url="https://gpu.example",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=actuator,
            http=FakeHttp(),
            clock=FakeClock(),
            artifact_out=tmp_path / "out.json",
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
        )

    assert actuator.stops == []


@pytest.mark.parametrize(
    "tags",
    [
        {"env": "production"},
        {"caller-selected-key": "caller-selected-value"},
    ],
)
def test_oci_actuator_requires_pinned_bench_dedicated_tag(
    monkeypatch: pytest.MonkeyPatch, tags: dict[str, str]
) -> None:
    actuator = bench.OciCliInstanceActuator(oci_bin="oci")
    monkeypatch.setattr(
        actuator,
        "_get_instance_data",
        lambda _instance_id: {"freeform-tags": tags},
    )

    with pytest.raises(BenchError, match="purpose=gpu-spike-bench"):
        actuator.verify_bench_dedicated("test-instance")


def test_oci_actuator_describes_instance_and_attached_boot_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        (
            {
                "data": {
                    "shape": "observed-shape",
                    "compartment-id": "test-compartment",
                    "availability-domain": "test-ad",
                }
            },
            {"data": [{"boot-volume-id": "test-boot-volume"}]},
            {"data": {"size-in-gbs": 750, "vpus-per-gb": 60}},
        )
    )
    commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return type("Proc", (), {"stdout": json.dumps(next(payloads))})()

    monkeypatch.setattr(bench.subprocess, "run", fake_run)

    observation = bench.OciCliInstanceActuator(oci_bin="oci").describe_instance("test-instance")

    assert observation == bench.InstanceObservation("observed-shape", 750, 60)
    assert commands[0][1:4] == ["compute", "instance", "get"]
    assert commands[1][1:4] == ["compute", "boot-volume-attachment", "list"]
    assert commands[2][1:4] == ["bv", "boot-volume", "get"]


def test_run_bench_finally_stops_on_mid_phase_error(tmp_path: Path) -> None:
    clock = FakeClock()
    actuator = FakeActuator("STOPPED")
    # Fail during warm-start (after cold boot succeeds).
    actuator.fail_on_start_after = 1  # cold boot start ok; next start fails
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    images = _write_images(tmp_path, n=1)
    out = tmp_path / "spike.json"

    with pytest.raises(PhaseError) as exc_info:
        run_bench(
            instance_ocid="ocid1.instance.oc1..gpu",
            endpoint_url="http://gpu.example:8000",
            model_id="m",
            image_paths=images,
            warm_start_runs=2,
            actuator=actuator,
            http=http,
            clock=clock,
            artifact_out=out,
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
            poll_interval_seconds=0.1,
        )

    assert exc_info.value.phase in {"warm_start", "cold_boot"}
    # Billing safety: finally path must leave instance STOPPED [RES-07].
    assert actuator.state == "STOPPED"
    assert not out.exists()


def test_run_bench_throughput_failure_still_stops(tmp_path: Path) -> None:
    clock = FakeClock()
    actuator = FakeActuator("STOPPED")
    http = FakeHttp(ready_after=0, completion_status=200)
    http.advance_clock = clock
    http.fail_nth_post = None
    # After warm starts, throughput posts fail via status.
    images = _write_images(tmp_path, n=1)

    # Monkey: make completion fail only when image_url present.
    original_post = http.post

    def _post_fail_images(url, *, json_body, headers=None):
        if "image_url" in str(json_body):
            if http.advance_clock is not None:
                http.advance_clock.advance(0.1)
            return HttpResponse(status_code=502, body=b"bad gateway")
        return original_post(url, json_body=json_body, headers=headers)

    http.post = _post_fail_images  # type: ignore[method-assign]

    with pytest.raises(PhaseError) as exc_info:
        run_bench(
            instance_ocid="ocid1.instance.oc1..gpu",
            endpoint_url="http://gpu.example:8000",
            model_id="m",
            image_paths=images,
            warm_start_runs=1,
            actuator=actuator,
            http=http,
            clock=clock,
            artifact_out=tmp_path / "out.json",
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
            poll_interval_seconds=0.1,
        )
    assert exc_info.value.phase == "throughput"
    assert actuator.state == "STOPPED"


def test_run_bench_final_stop_failure_raises_without_completed_artifact(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    actuator = FakeActuator("STOPPED")
    actuator.fail_on_stop_after = 1
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    out = tmp_path / "must-not-be-promoted.json"

    with pytest.raises(PhaseError) as exc_info:
        run_bench(
            instance_ocid="ocid1.instance.oc1..gpu",
            endpoint_url="http://gpu.example:8000",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=actuator,
            http=http,
            clock=clock,
            artifact_out=out,
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
            poll_interval_seconds=0.1,
            lifecycle_timeout_seconds=0.2,
        )

    assert exc_info.value.phase == "cleanup"
    assert not out.exists()


def test_run_bench_final_stopped_poll_timeout_raises_without_artifact(
    tmp_path: Path,
) -> None:
    class FinalStopHangs(FakeActuator):
        def stop(self, instance_id: str) -> None:
            if self._stop_count == 1:
                self._stop_count += 1
                self.stops.append(instance_id)
                self.state = "STOPPING"
                self._pending_stop_polls = 100
                return
            super().stop(instance_id)

    clock = FakeClock()
    actuator = FinalStopHangs("STOPPED")
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    out = tmp_path / "must-not-exist.json"

    with pytest.raises(PhaseError) as exc_info:
        run_bench(
            instance_ocid="ocid1.instance.oc1..gpu",
            endpoint_url="http://gpu.example:8000",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=actuator,
            http=http,
            clock=clock,
            artifact_out=out,
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
            poll_interval_seconds=0.1,
            lifecycle_timeout_seconds=0.2,
        )

    assert exc_info.value.phase == "cleanup"
    assert not out.exists()


# ---------------------------------------------------------------------------
# Dry-run CLI
# ---------------------------------------------------------------------------


def test_dry_run_prints_plan_and_touches_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    images = _write_images(tmp_path, n=1)
    code = main(
        [
            "--instance-ocid",
            "ocid1.instance.oc1..gpu",
            "--endpoint-url",
            "http://gpu.example:8000",
            "--image",
            str(images[0]),
            "--dry-run",
            "--artifact-out",
            str(tmp_path / "should-not-exist.json"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    plan = json.loads(out)
    assert plan["mode"] == "dry-run"
    assert plan["touches_oci"] is False
    assert plan["touches_endpoint"] is False
    assert "cold_boot" in plan["phases"][0]
    assert not (tmp_path / "should-not-exist.json").exists()


def test_cli_defaults_to_dry_run_without_constructing_oci(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("OCI actuator must not be constructed")

    monkeypatch.setattr(bench, "OciCliInstanceActuator", fail_if_constructed)

    assert (
        main(
            [
                "--instance-ocid",
                "test-instance",
                "--endpoint-url",
                "https://gpu.example",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"


def test_cli_live_without_confirmation_exits_before_constructing_oci(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    constructed = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("OCI actuator must not be constructed")

    monkeypatch.delenv("ACX_GPU_BENCH_LIVE", raising=False)
    monkeypatch.setattr(bench, "OciCliInstanceActuator", fail_if_constructed)

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--instance-ocid",
                "test-instance",
                "--endpoint-url",
                "https://gpu.example",
                "--live",
            ]
        )

    assert exc_info.value.code == 2
    assert constructed is False
    assert "ACX_GPU_BENCH_LIVE" in capsys.readouterr().err


def test_dry_run_plan_helper_structure() -> None:
    plan = dry_run_plan(
        instance_ocid="ocid.x",
        endpoint_url="http://e",
        model_id="m",
        image_paths=[Path("a.png")],
        warm_start_runs=5,
        artifact_out=Path("out.json"),
        a10_quota_confirmed=False,
        a100_or_l40s_headroom_confirmed=False,
        serverless_gpu_available=False,
        boot_volume_gb=750,
        vpus_per_gb=10,
        shape="test-shape",
        quantization="test-quantization",
        model_path="/test/model.gguf",
    )
    assert plan["warm_start_runs"] == 5
    assert plan["images"] == ["a.png"]
    assert plan["boot_volume_gb"] == 750
    assert plan["vpus_per_gb"] == 10
    assert any("RES-07" in p for p in plan["phases"])


def test_cli_requires_image_without_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_GPU_BENCH_LIVE", "I-UNDERSTAND-THIS-COSTS-MONEY")
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--instance-ocid",
                "ocid1.instance.oc1..gpu",
                "--endpoint-url",
                "http://gpu.example:8000",
                "--live",
                "--model-id",
                "m",
                "--boot-volume-gb",
                "400",
                "--vpus-per-gb",
                "120",
                "--shape",
                "test-shape",
                "--quantization",
                "test-quantization",
                "--model-path",
                "/test/model.gguf",
            ]
        )
    assert exc_info.value.code == 2  # argparse error


def test_cli_requires_hardware_provenance_for_live_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image = _write_images(tmp_path, n=1)[0]

    monkeypatch.setenv("ACX_GPU_BENCH_LIVE", "I-UNDERSTAND-THIS-COSTS-MONEY")
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--instance-ocid",
                "test-instance",
                "--endpoint-url",
                "http://gpu.example:8000",
                "--image",
                str(image),
                "--live",
            ]
        )

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "--boot-volume-gb" in error
    assert "--shape" in error


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--warm-start-runs", "0"),
        ("--poll-interval", "0"),
        ("--boot-volume-gb", "0"),
        ("--vpus-per-gb", "0"),
    ],
)
def test_cli_rejects_invalid_live_numeric_bounds_before_constructing_actuator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    value: str,
) -> None:
    constructed = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("OCI actuator must not be constructed")

    image = _write_images(tmp_path, n=1)[0]
    args = _live_cli_args(image)
    args.extend([flag, value])
    monkeypatch.setenv("ACX_GPU_BENCH_LIVE", "I-UNDERSTAND-THIS-COSTS-MONEY")
    monkeypatch.setattr(bench, "OciCliInstanceActuator", fail_if_constructed)

    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 2
    assert constructed is False


def test_cli_opens_every_image_before_constructing_live_actuator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed = False

    def fail_if_constructed(*args, **kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("OCI actuator must not be constructed")

    unreadable_image = tmp_path / "not-a-readable-image"
    unreadable_image.mkdir()
    monkeypatch.setenv("ACX_GPU_BENCH_LIVE", "I-UNDERSTAND-THIS-COSTS-MONEY")
    monkeypatch.setattr(bench, "OciCliInstanceActuator", fail_if_constructed)

    with pytest.raises(SystemExit) as exc_info:
        main(_live_cli_args(unreadable_image))

    assert exc_info.value.code == 2
    assert constructed is False


def test_7a_findings_withdraws_unproven_strict_pass() -> None:
    report = (Path(__file__).resolve().parents[1] / "docs/tasks/vlm/VLM-3-7a-spike-findings.md").read_text()

    assert "100 GB @ 10 VPU | no committed configuration provenance; unsupported" in report
    assert "400 GB @ 120 VPU | no committed VPU provenance; unsupported" in report
    assert "only strict pass" not in report


def test_phase_error_message_names_phase() -> None:
    err = PhaseError("warm_start", "boom")
    assert "warm_start" in str(err)
    assert err.phase == "warm_start"


def test_lifecycle_poll_retries_transient_reads_and_records_evidence() -> None:
    class FlakyActuator(FakeActuator):
        def __init__(self) -> None:
            super().__init__("RUNNING")
            self.failures = 2

        def get_lifecycle_state(self, instance_id: str) -> str:
            if self.failures:
                self.failures -= 1
                raise subprocess.CalledProcessError(1, ["oci"])
            return super().get_lifecycle_state(instance_id)

    evidence: dict[str, int] = {}
    elapsed = bench.wait_for_lifecycle(
        FlakyActuator(),
        "test-instance",
        "RUNNING",
        clock=FakeClock(),
        poll_interval_seconds=0.1,
        evidence=evidence,
    )

    assert elapsed == pytest.approx(0.2)
    assert evidence == {"retries": 2}


def test_lifecycle_poll_continuous_failures_stop_at_bounded_threshold() -> None:
    class BrokenActuator(FakeActuator):
        def get_lifecycle_state(self, instance_id: str) -> str:
            raise OSError(f"transient read for {instance_id}")

    clock = FakeClock()
    with pytest.raises(PhaseError, match="transient read.*consecutive"):
        bench.wait_for_lifecycle(
            BrokenActuator(),
            "test-instance",
            "RUNNING",
            clock=clock,
            timeout_seconds=100,
            poll_interval_seconds=0.1,
        )

    assert len(clock.sleeps) < 10


def test_ensure_stopped_tolerates_transient_read_after_stop() -> None:
    class FlakyStopActuator(FakeActuator):
        def __init__(self) -> None:
            super().__init__("RUNNING")
            self.reads_after_stop = 0

        def get_lifecycle_state(self, instance_id: str) -> str:
            if self.stops and self.reads_after_stop == 0:
                self.reads_after_stop += 1
                raise json.JSONDecodeError("partial payload", "{", 1)
            return super().get_lifecycle_state(instance_id)

    actuator = FlakyStopActuator()
    bench.ensure_stopped(
        actuator,
        "test-instance",
        clock=FakeClock(),
        poll_interval_seconds=0.1,
    )
    assert actuator.state == "STOPPED"


def test_describe_failure_on_running_instance_refuses_without_stop(tmp_path: Path) -> None:
    class DescribeFailureActuator(FakeActuator):
        def describe_instance(self, instance_id: str) -> bench.InstanceObservation:
            raise OSError(f"describe failed for {instance_id}")

    actuator = DescribeFailureActuator("RUNNING")
    with pytest.raises(PhaseError, match="precondition.*STOPPED"):
        run_bench(
            instance_ocid="test-instance",
            endpoint_url="http://localhost:8000",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=actuator,
            http=FakeHttp(),
            clock=FakeClock(),
            artifact_out=tmp_path / "out.json",
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
        )
    assert actuator.stops == []


def test_describe_failure_before_start_does_not_claim_cleanup(tmp_path: Path) -> None:
    class DescribeFailureActuator(FakeActuator):
        def describe_instance(self, instance_id: str) -> bench.InstanceObservation:
            raise OSError(f"describe failed for {instance_id}")

    actuator = DescribeFailureActuator("STOPPED")
    with pytest.raises(PhaseError, match="instance_provenance"):
        run_bench(
            instance_ocid="test-instance",
            endpoint_url="http://localhost:8000",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=actuator,
            http=FakeHttp(),
            clock=FakeClock(),
            artifact_out=tmp_path / "out.json",
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
        )

    assert actuator.starts == []
    assert actuator.stops == []


def test_endpoint_validation_rejects_public_resolution_without_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_address = ".".join(str(part) for part in (198, 51, 100, 7))
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (public_address, 443))],
    )
    with pytest.raises(BenchError, match="not private"):
        bench.validate_endpoint_url("https://public.invalid")


def test_cli_rejects_public_endpoint_before_constructing_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed: list[str] = []
    public_address = ".".join(str(part) for part in (8, 8, 4, 4))
    image = _write_images(tmp_path, n=1)[0]
    args = _live_cli_args(image)
    allow_index = args.index("--allow-endpoint-host")
    del args[allow_index : allow_index + 2]
    args[args.index("https://gpu.example")] = "https://public.invalid"
    monkeypatch.setenv(bench.LIVE_CONFIRMATION_ENV, bench.LIVE_CONFIRMATION_TOKEN)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (public_address, 443))],
    )
    monkeypatch.setattr(
        bench,
        "OciCliInstanceActuator",
        lambda **_kwargs: constructed.append("actuator"),
    )
    monkeypatch.setattr(bench, "UrlLibHttpClient", lambda: constructed.append("http"))

    with pytest.raises(SystemExit) as exc_info:
        main(args)
    assert exc_info.value.code == 2
    assert constructed == []


def test_endpoint_validation_accepts_private_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_address = ".".join(str(part) for part in (10, 20, 30, 40))
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (private_address, 8000))],
    )
    bench.validate_endpoint_url("http://private.invalid:8000")


def test_http_client_does_not_follow_redirects() -> None:
    assert bench.UrlLibHttpClient()._opener.handlers
    assert any(isinstance(handler, bench.NoRedirectHandler) for handler in bench.UrlLibHttpClient()._opener.handlers)


def test_cli_reads_api_key_from_named_environment_without_leaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "test-super-secret-bearer"
    image = _write_images(tmp_path, n=1)[0]
    artifact_out = tmp_path / "secret-check.json"
    http = FakeHttp()
    clock = FakeClock()
    http.advance_clock = clock
    monkeypatch.setenv(bench.LIVE_CONFIRMATION_ENV, bench.LIVE_CONFIRMATION_TOKEN)
    monkeypatch.setenv("TEST_GPU_API_KEY", secret)
    monkeypatch.setattr(bench, "validate_endpoint_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bench, "OciCliInstanceActuator", lambda **_kwargs: FakeActuator())
    monkeypatch.setattr(bench, "UrlLibHttpClient", lambda: http)
    monkeypatch.setattr(bench, "SystemClock", lambda: clock)
    assert (
        main(
            [
                *_live_cli_args(image),
                "--api-key-env",
                "TEST_GPU_API_KEY",
                "--artifact-out",
                str(artifact_out),
            ]
        )
        == 0
    )
    streams = capsys.readouterr()
    expected_header = {"Authorization": f"Bearer {secret}"}
    assert expected_header in http.get_headers
    assert any(post["headers"] == expected_header for post in http.posts)
    assert secret not in artifact_out.read_text()
    assert secret not in streams.out
    assert secret not in streams.err


def test_cli_removes_plain_api_key_flag() -> None:
    with pytest.raises(SystemExit) as exc_info:
        bench.build_parser().parse_args(
            [
                "--instance-ocid",
                "test-instance",
                "--endpoint-url",
                "http://localhost:8000",
                "--api-key",
                "must-not-be-accepted",
            ]
        )
    assert exc_info.value.code == 2


def test_cli_rejects_unset_api_key_env_before_actuator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = False
    image = _write_images(tmp_path, n=1)[0]
    monkeypatch.setenv(bench.LIVE_CONFIRMATION_ENV, bench.LIVE_CONFIRMATION_TOKEN)
    monkeypatch.delenv("MISSING_GPU_API_KEY", raising=False)

    def fail_if_constructed(**_kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("actuator must not be constructed")

    monkeypatch.setattr(bench, "OciCliInstanceActuator", fail_if_constructed)
    with pytest.raises(SystemExit) as exc_info:
        main([*_live_cli_args(image), "--api-key-env", "MISSING_GPU_API_KEY"])
    assert exc_info.value.code == 2
    assert constructed is False


def test_main_returns_nonzero_for_provenance_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = _write_images(tmp_path, n=1)[0]
    monkeypatch.setenv(bench.LIVE_CONFIRMATION_ENV, bench.LIVE_CONFIRMATION_TOKEN)
    monkeypatch.setattr(bench, "validate_endpoint_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bench, "OciCliInstanceActuator", lambda **_kwargs: FakeActuator())
    monkeypatch.setattr(bench, "UrlLibHttpClient", lambda: FakeHttp())
    monkeypatch.setattr(
        bench,
        "run_bench",
        lambda **_kwargs: (_ for _ in ()).throw(PhaseError("instance_provenance_mismatch", "artifact preserved")),
    )
    assert main(_live_cli_args(image)) == 1


def test_run_bench_writes_mismatch_artifact_then_fails(tmp_path: Path) -> None:
    class MismatchActuator(FakeActuator):
        def describe_instance(self, instance_id: str) -> bench.InstanceObservation:
            del instance_id
            return bench.InstanceObservation("different-shape", 750, 60)

    artifact_out = tmp_path / "mismatch.json"
    http = FakeHttp()
    clock = FakeClock()
    http.advance_clock = clock
    with pytest.raises(PhaseError, match="instance_provenance_mismatch"):
        run_bench(
            instance_ocid="test-instance",
            endpoint_url="http://localhost:8000",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=MismatchActuator(),
            http=http,
            clock=clock,
            artifact_out=artifact_out,
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
        )
    assert json.loads(artifact_out.read_text())["status"] == (bench.ARTIFACT_STATUS_PROVENANCE_MISMATCH)


def test_run_bench_writes_pending_artifact_then_fails_and_stops(
    tmp_path: Path,
) -> None:
    class UnobservedActuator(FakeActuator):
        def describe_instance(self, instance_id: str) -> bench.InstanceObservation | None:
            del instance_id
            return None

    actuator = UnobservedActuator()
    artifact_out = tmp_path / "pending.json"
    http = FakeHttp()
    clock = FakeClock()
    http.advance_clock = clock

    with pytest.raises(PhaseError, match="instance_provenance_pending"):
        run_bench(
            instance_ocid="test-instance",
            endpoint_url="http://localhost:8000",
            model_id="m",
            image_paths=_write_images(tmp_path, n=1),
            warm_start_runs=1,
            actuator=actuator,
            http=http,
            clock=clock,
            artifact_out=artifact_out,
            boot_volume_gb=400,
            vpus_per_gb=120,
            shape="test-shape",
            quantization="test-quantization",
            model_path="/test/model.gguf",
        )

    assert json.loads(artifact_out.read_text())["status"] == ARTIFACT_STATUS_PENDING
    assert actuator.stops
    assert actuator.state == "STOPPED"


def test_main_exits_nonzero_for_unobserved_instance_and_preserves_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnobservedActuator(FakeActuator):
        def describe_instance(self, instance_id: str) -> bench.InstanceObservation | None:
            del instance_id
            return None

    actuator = UnobservedActuator()
    artifact_out = tmp_path / "pending-main.json"
    image = _write_images(tmp_path, n=1)[0]
    http = FakeHttp()
    clock = FakeClock()
    http.advance_clock = clock
    monkeypatch.setenv(bench.LIVE_CONFIRMATION_ENV, bench.LIVE_CONFIRMATION_TOKEN)
    monkeypatch.setattr(bench, "validate_endpoint_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bench, "OciCliInstanceActuator", lambda **_kwargs: actuator)
    monkeypatch.setattr(bench, "UrlLibHttpClient", lambda: http)
    monkeypatch.setattr(bench, "SystemClock", lambda: clock)

    exit_code = main(
        [
            *_live_cli_args(image),
            "--warm-start-runs",
            "1",
            "--artifact-out",
            str(artifact_out),
        ]
    )

    assert exit_code == 1
    assert json.loads(artifact_out.read_text())["status"] == ARTIFACT_STATUS_PENDING
    assert actuator.stops
    assert actuator.state == "STOPPED"


def test_v1_committed_and_v2_fresh_artifacts_load() -> None:
    artifacts_root = Path(__file__).resolve().parents[1] / "docs" / "tasks" / "vlm"
    committed = sorted(artifacts_root.glob("VLM-3-gpu-spike-2026-07-14*.json"))
    assert len(committed) == 4
    for path in committed:
        assert bench.load_spike_artifact(path)["schema"] == "acx-gpu-spike/v1"

    fresh = build_spike_artifact(
        cold_boot=ColdBootResult(1, 0.5, 0.5, 0.5),
        warm_start=WarmStartResult([2], [1], 2, 2, True),
        throughput=ThroughputResult([3], 3, 3, 3),
        model_id="m",
        shape="test-shape",
        quantization="test-quantization",
        model_path="/test/model.gguf",
        boot_volume_gb=400,
        vpus_per_gb=120,
    )
    assert fresh["schema"] == "acx-gpu-spike/v2"
    assert bench.load_spike_artifact(fresh)["schema"] == "acx-gpu-spike/v2"
