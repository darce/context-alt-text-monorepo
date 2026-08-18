"""VLM-6 S2B: timing percentiles, warm-up, cold-load, peak-VRAM capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import httpx
import pytest

from scripts.eval_harness.bakeoff import BakeoffClient, _stamp_timing_and_gpu
from scripts.eval_harness.bakeoff import main as bakeoff_main
from scripts.eval_harness.bench_capture import (
    CaptureStatus,
    LoadLoop,
    VramSampler,
    collect_item_latencies,
    summarize_latencies,
)

_IMAGE_BYTES = b"fake-s2b-image-bytes"


def test_summarize_latencies_nearest_rank_on_1_to_100() -> None:
    """PERF-01: nearest-rank percentiles are the headline, not the mean."""
    values = [float(n) for n in range(1, 101)]
    summary = summarize_latencies(values)
    assert summary["n"] == 100
    assert summary["p50_s"] == 50.0
    assert summary["p95_s"] == 95.0
    assert summary["p99_s"] == 99.0
    assert summary["max_s"] == 100.0
    assert summary["mean_s"] == 50.5


def test_summarize_latencies_single_value() -> None:
    summary = summarize_latencies([1.2346])
    assert summary == {
        "n": 1,
        "p50_s": 1.235,
        "p95_s": 1.235,
        "p99_s": 1.235,
        "max_s": 1.235,
        "mean_s": 1.235,
    }


def test_summarize_latencies_empty_is_none_not_zero() -> None:
    """rg-015: empty input must not invent numeric zeros."""
    summary = summarize_latencies([])
    assert summary == {
        "n": 0,
        "p50_s": None,
        "p95_s": None,
        "p99_s": None,
        "max_s": None,
        "mean_s": None,
    }


def test_summarize_latencies_nearest_rank_n5_p50() -> None:
    """TEST-15: N=5 p50 = ceil(0.5*5) = 3. ``int`` would yield 2."""
    assert summarize_latencies([1.0, 2.0, 3.0, 4.0, 5.0])["p50_s"] == 3.0


def test_summarize_latencies_nearest_rank_n10_p99_is_max() -> None:
    """TEST-15: N=10 p99 = ceil(0.99*10) = 10 (= max). ``int`` would yield 9."""
    values = [float(n) for n in range(1, 11)]
    summary = summarize_latencies(values)
    assert summary["p99_s"] == 10.0
    assert summary["p99_s"] == summary["max_s"]


def test_summarize_latencies_nearest_rank_n4_p50() -> None:
    """TEST-15: N=4 p50 = ceil(0.5*4) = 2."""
    assert summarize_latencies([1.0, 2.0, 3.0, 4.0])["p50_s"] == 2.0


def test_collect_item_latencies_sums_passes_and_skips_none() -> None:
    record = {
        "items": [
            {
                "latency_s": 9.9,
                "describe": {
                    "passes": [
                        {"pass": "describe_facts", "latency_s": 1.2},
                        {"pass": "ground_weave", "latency_s": 0.8},
                    ]
                },
            },
            {"latency_s": None, "describe": None, "error": "missing"},
            {
                "latency_s": 0.5,
                "describe": {"passes": [{"pass": "caption", "latency_s": None}]},
            },
            {"latency_s": 0.4, "describe": {"alt_text_draft": "x"}},
        ]
    }
    assert collect_item_latencies(record) == [2.0, 0.5, 0.4]


def test_collect_item_latencies_excludes_error_items() -> None:
    """rg-015: timeouts / CircuitOpen must not enter per_item percentiles."""
    record: dict[str, Any] = {
        "items": [
            {"latency_s": 1.0, "error": None},
            {"latency_s": 900.0, "error": "TimeoutError: timed out"},
            {"latency_s": 0.001, "error": "CircuitOpenError: circuit open"},
            {"latency_s": None, "error": None},
        ]
    }
    assert collect_item_latencies(record) == [1.0]
    _stamp_timing_and_gpu(
        record,
        warmup={"requests": 0, "succeeded": 0, "failed": 0, "elapsed_s": 0.0},
        cold_load_s=None,
        gpu={"status": CaptureStatus.UNAVAILABLE},
    )
    assert record["timing"]["per_item"]["n"] == 1
    assert record["timing"]["items_with_error"] == 2
    assert record["timing"]["items_without_latency"] == 1
    assert record["timing"]["loop"] == LoadLoop.CLOSED_SERIAL
    assert "open_loop" not in record["timing"]


def _csv_runner(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
    return CompletedProcess(
        args=["nvidia-smi"],
        returncode=0,
        stdout="250, 24576\n",
        stderr="",
    )


def test_vram_sampler_single_gpu_peak() -> None:
    sampler = VramSampler(interval_s=0.05, runner=_csv_runner)
    sampler.start()
    result = sampler.stop()
    assert result["source"] == "nvidia-smi"
    assert result["status"] == CaptureStatus.MEASURED
    assert result["peak_used_mb"] == 250
    assert result["total_mb"] == 24576
    assert result["gpu_count"] == 1
    assert result["per_gpu_peak_used_mb"] == [250]
    assert result["samples"] >= 1
    assert result["interval_s"] == 0.05


def _dual_csv_runner(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
    return CompletedProcess(
        args=["nvidia-smi"],
        returncode=0,
        stdout="10000, 24576\n10000, 24576\n",
        stderr="",
    )


def test_vram_sampler_dual_gpu_sums_used_and_totals() -> None:
    """Sharded 10+10 GiB must not collapse to max(used) on one card."""
    sampler = VramSampler(interval_s=0.05, runner=_dual_csv_runner)
    sampler.start()
    result = sampler.stop()
    assert result["status"] == CaptureStatus.MEASURED
    assert result["peak_used_mb"] == 20000
    assert result["total_mb"] == 49152
    assert result["gpu_count"] == 2
    assert result["per_gpu_peak_used_mb"] == [10000, 10000]


def test_vram_sampler_missing_binary_is_unavailable() -> None:
    def missing(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
        raise FileNotFoundError("nvidia-smi")

    sampler = VramSampler(interval_s=0.05, runner=missing)
    sampler.start()
    result = sampler.stop()
    assert result["status"] == CaptureStatus.UNAVAILABLE
    assert result["peak_used_mb"] is None
    assert result["total_mb"] is None
    assert result["samples"] == 0
    assert "nvidia-smi" in result["reason"]


def test_vram_sampler_zero_samples_is_unavailable() -> None:
    def empty(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
        return CompletedProcess(args=["nvidia-smi"], returncode=0, stdout="", stderr="")

    sampler = VramSampler(interval_s=0.05, runner=empty)
    sampler.start()
    result = sampler.stop()
    assert result["status"] == CaptureStatus.UNAVAILABLE
    assert result["peak_used_mb"] is None
    assert result["samples"] == 0
    assert result["reason"]


def _write_manifest(tmp_path: Path, n_images: int = 2) -> Path:
    entries = []
    digest = hashlib.sha256(_IMAGE_BYTES).hexdigest()
    for i in range(n_images):
        name = f"img{i}.jpg"
        (tmp_path / name).write_bytes(_IMAGE_BYTES)
        entries.append(
            {
                "path": name,
                "sha256": digest,
                "media_id": i + 1,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {"caption": f"caption-{i}"},
                "base_caption": "",
                "must_right": [],
                "easy_wrong": ["Wrong Name"],
                "policy": {"recognition_enabled": False},
                "provenance": {"source": "fixture", "license": "fixture"},
            }
        )
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "roster_only",
                "roster": ["Wrong Name"],
                "entries": entries,
            }
        )
    )
    return path


def _counting_transport(captured: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"path": request.url.path})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A caption."}}]},
        )

    return httpx.MockTransport(handler)


def _install_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.BaseTransport) -> None:
    original = BakeoffClient.__init__

    def wrapped(self: BakeoffClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(BakeoffClient, "__init__", wrapped)


def _fail_first_n_transport(fail_first: int, captured: list[dict[str, Any]]) -> httpx.MockTransport:
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        captured.append({"path": request.url.path, "n": seen["n"]})
        if seen["n"] <= fail_first:
            return httpx.Response(500, json={"error": "not ready"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A caption."}}]},
        )

    return httpx.MockTransport(handler)


def _run_bakeoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
    *,
    captured: list[dict[str, Any]] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(tmp_path))
    captured = captured if captured is not None else []
    _install_transport(monkeypatch, transport or _counting_transport(captured))
    manifest = _write_manifest(tmp_path)
    out = tmp_path / "run.json"
    bakeoff_main(
        [
            "--endpoint",
            "http://candidate.test:8080",
            "--model-id",
            "stub-model",
            "--manifest",
            str(manifest),
            "--out",
            str(out),
            *extra,
        ]
    )
    return json.loads(out.read_text())


def test_bakeoff_warmup_issues_extra_requests_before_scored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    record = _run_bakeoff(
        tmp_path,
        monkeypatch,
        ["--warmup", "2", "--vram-sample-interval-s", "0", "--cold-load-s", "12.5"],
        captured=captured,
    )
    assert len(captured) == 4  # 2 warmup + 2 scored (single-pass)
    assert record["timing"]["per_item"]["n"] == 2
    warmup = record["timing"]["warmup"]
    assert warmup["requests"] == 2
    assert warmup["succeeded"] == 2
    assert warmup["failed"] == 0
    assert warmup["elapsed_s"] >= 0
    assert record["timing"]["cold_load_s"] == 12.5
    assert record["timing"]["loop"] == LoadLoop.CLOSED_SERIAL
    assert "open_loop" not in record["timing"]
    assert record["timing"]["concurrency"] == 1
    assert record["timing"]["items_with_error"] == 0
    assert record["gpu"]["status"] == CaptureStatus.UNAVAILABLE
    assert record["gpu"]["reason"] == "sampling disabled"


def test_bakeoff_warmup_does_not_open_scoring_breaker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Warm-up 500s must not trip the scoring client's 3-strike breaker."""
    captured: list[dict[str, Any]] = []
    record = _run_bakeoff(
        tmp_path,
        monkeypatch,
        ["--warmup", "3", "--vram-sample-interval-s", "0", "--stall-limit", "5"],
        captured=captured,
        transport=_fail_first_n_transport(3, captured),
    )
    assert len(record["items"]) == 2
    assert all(item.get("error") is None for item in record["items"])
    assert record["timing"]["per_item"]["n"] == 2
    assert record["timing"]["items_with_error"] == 0
    assert not any("CircuitOpen" in str(item.get("error") or "") for item in record["items"])
    warmup = record["timing"]["warmup"]
    assert warmup["requests"] == 3
    assert warmup["succeeded"] == 0
    assert warmup["failed"] == 3


def test_bakeoff_gpu_unavailable_when_nvidia_smi_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: Any, **_kwargs: Any) -> CompletedProcess[str]:
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr("scripts.eval_harness.bench_capture.subprocess.run", missing)
    record = _run_bakeoff(tmp_path, monkeypatch, ["--warmup", "0", "--vram-sample-interval-s", "0.05"])
    assert record["gpu"]["status"] == CaptureStatus.UNAVAILABLE
    assert record["gpu"]["peak_used_mb"] is None
    assert record["gpu"]["samples"] == 0
    assert "nvidia-smi" in record["gpu"]["reason"]
    assert record["timing"]["warmup"]["requests"] == 0
    assert record["timing"]["cold_load_s"] is None
    assert record["timing"]["per_item"]["n"] == 2
