"""Unit tests for scripts/gpu_spike_bench.py — zero OCI/GPU/network [TEST-01]."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Allow `import gpu_spike_bench` when pytest collects from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gpu_spike_bench import (  # noqa: E402
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

    def start(self, instance_id: str) -> None:
        self._start_count += 1
        if (
            self.fail_on_start_after is not None
            and self._start_count > self.fail_on_start_after
        ):
            raise RuntimeError(f"injected start failure for {instance_id}")
        self.starts.append(instance_id)
        if self.start_polls_until_running <= 0:
            self.state = "RUNNING"
        else:
            self.state = "STARTING"
            self._pending_start_polls = self.start_polls_until_running

    def stop(self, instance_id: str) -> None:
        self._stop_count += 1
        if (
            self.fail_on_stop_after is not None
            and self._stop_count > self.fail_on_stop_after
        ):
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
        self.posts: list[dict[str, Any]] = []
        self.fail_nth_post: int | None = None
        self._post_count = 0
        # Per-call wall-clock advance injected via clock from outside tests.
        self.advance_clock: FakeClock | None = None
        self.completion_duration_s: float = 0.5

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> HttpResponse:
        self.gets.append(url)
        self._ready_probes += 1
        if self.advance_clock is not None:
            self.advance_clock.advance(0.01)
        if self._ready_probes > self.ready_after and url.rstrip("/").endswith("/v1/models"):
            return HttpResponse(status_code=200, body=b'{"data":[]}')
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
                        "choices": [
                            {"message": {"content": "A test image description."}}
                        ]
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
        boot_volume_gb=400,
        vpus_per_gb=120,
        a10_quota_confirmed=True,
    )
    assert artifact["schema"] == "acx-gpu-spike/v1"
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
    assert artifact["boot_volume_size_in_gbs"] == 400
    assert artifact["boot_volume_vpus_per_gb"] == 120
    assert artifact["oci_capacity"]["a10_quota_confirmed"] is True
    assert_no_null_measurement_values(artifact)


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
        boot_volume_gb=400,
        vpus_per_gb=120,
    )
    fail_art = build_spike_artifact(
        cold_boot=ColdBootResult(1, 0.5, 0.5, 0.5),
        warm_start=fail_result,
        throughput=ThroughputResult([1.0], 1.0, 1.0, 1.0),
        model_id="m",
        boot_volume_gb=400,
        vpus_per_gb=120,
    )
    assert pass_art["measurements"]["warm_start_p95_seconds"]["meets_target"] is True
    assert fail_art["measurements"]["warm_start_p95_seconds"]["meets_target"] is False
    assert fail_art["measurements"]["warm_start_p95_seconds"]["value"] > WARM_START_P95_TARGET_SECONDS


def test_default_artifact_path_is_dated() -> None:
    from datetime import date

    path = default_artifact_path(today=date(2026, 7, 12))
    assert path == Path("docs/tasks/vlm/VLM-3-gpu-spike-2026-07-12.json")


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
        for key, value in fields.items():
            assert artifact[key] == value

    assert "boot_volume_size_in_gbs" not in json.loads(
        (artifact_dir / "VLM-3-gpu-spike-2026-07-14.json").read_text()
    )
    assert "boot_volume_vpus_per_gb" not in json.loads(
        (artifact_dir / "VLM-3-gpu-spike-2026-07-14-400gb.json").read_text()
    )
    assert "boot_volume_vpus_per_gb" not in json.loads(
        (
            artifact_dir / "VLM-3-gpu-spike-2026-07-14-750gb-balanced.json"
        ).read_text()
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
    assert (
        "Status: provisional; license verdict pending; measured JSON reports not regenerated"
        in memo
    )
    assert "n=3 warm starts" in report
    assert "n=1 image" in report
    assert "acx-oci.env" not in topology
    assert "oci-lib.sh" not in topology
    assert "variables.tf" in topology
    assert "gpu-lifecycle-install.sh" in topology
    assert "AVAILABLE and used by the 2026-07-14 spike host" in topology


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
    assert result.model_load_seconds == pytest.approx(
        result.cold_boot_seconds - result.instance_running_seconds
    )
    assert actuator.state == "RUNNING"
    assert actuator.starts == ["ocid1.instance.oc1..gpu"]


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


def test_throughput_posts_chat_completions_and_stats() -> None:
    clock = FakeClock()
    http = FakeHttp(ready_after=0)
    http.advance_clock = clock
    http.completion_duration_s = 1.5
    images = _write_images(Path(pytest.importorskip("tempfile").mkdtemp()), n=3)
    # Use tmp_path via fixture-like path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        images = _write_images(Path(td), n=3)
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
        a10_quota_confirmed=True,
        poll_interval_seconds=0.1,
    )

    assert out.is_file()
    artifact = json.loads(out.read_text())
    assert artifact["status"] == ARTIFACT_STATUS_MEASURED
    assert_no_null_measurement_values(artifact)
    assert artifact["oci_capacity"]["a10_quota_confirmed"] is True
    assert artifact["boot_volume_size_in_gbs"] == 400
    assert artifact["boot_volume_vpus_per_gb"] == 120
    assert result.warm_start_meets_target is True
    # finally STOP [RES-07]
    assert actuator.state == "STOPPED"
    assert actuator.stops  # at least warm-start + final


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
            poll_interval_seconds=0.1,
            lifecycle_timeout_seconds=0.2,
        )

    assert exc_info.value.phase == "cleanup"
    assert not out.exists()


# ---------------------------------------------------------------------------
# Dry-run CLI
# ---------------------------------------------------------------------------


def test_dry_run_prints_plan_and_touches_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    )
    assert plan["warm_start_runs"] == 5
    assert plan["images"] == ["a.png"]
    assert plan["boot_volume_gb"] == 750
    assert plan["vpus_per_gb"] == 10
    assert any("RES-07" in p for p in plan["phases"])


def test_cli_requires_image_without_dry_run() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--instance-ocid",
                "ocid1.instance.oc1..gpu",
                "--endpoint-url",
                "http://gpu.example:8000",
            ]
        )
    assert exc_info.value.code == 2  # argparse error


def test_cli_requires_hardware_provenance_for_live_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = _write_images(tmp_path, n=1)[0]

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--instance-ocid",
                "test-instance",
                "--endpoint-url",
                "http://gpu.example:8000",
                "--image",
                str(image),
            ]
        )

    assert exc_info.value.code == 2
    assert "--boot-volume-gb and --vpus-per-gb are required" in capsys.readouterr().err


def test_phase_error_message_names_phase() -> None:
    err = PhaseError("warm_start", "boom")
    assert "warm_start" in str(err)
    assert err.phase == "warm_start"
