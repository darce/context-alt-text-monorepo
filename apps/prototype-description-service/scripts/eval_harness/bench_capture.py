"""VLM-6 S2B: closed-serial timing summaries and peak-VRAM sampling.

Percentiles use the nearest-rank method (PERF-01): for a sorted sample of
length ``N`` and percentile ``P``, the rank is ``ceil(P/100 * N)`` (1-based).
The mean is recorded as a secondary field only. Empty input never fabricates
zeros (rg-015). Fetch is closed-serial (PERF-03): wait-then-send, concurrency 1.
"""

from __future__ import annotations

import math
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from subprocess import CompletedProcess
from typing import Any

_NVIDIA_SMI_QUERY = [
    "nvidia-smi",
    "--query-gpu=memory.used,memory.total",
    "--format=csv,noheader,nounits",
]


class CaptureStatus(StrEnum):
    """Whether a GPU high-water mark was measured (sr-007)."""

    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


class PerGpuSemantics(StrEnum):
    """How per-GPU used-MB arrays relate to the aggregate peak (sr-007, OBS-05).

    ``SNAPSHOT_AT_AGGREGATE_PEAK_SAMPLE``: ``per_gpu_used_mb_at_peak`` is the
    per-row used-MB vector from the sample that set ``peak_used_mb``. Independent
    per-index high-water lives on ``per_gpu_peak_used_mb``.
    """

    SNAPSHOT_AT_AGGREGATE_PEAK_SAMPLE = "snapshot_at_aggregate_peak_sample"


class LoadLoop(StrEnum):
    """How the harness issues load (PERF-03, sr-007).

    ``CLOSED_SERIAL``: fetch_run_record waits for each response before sending
    the next (concurrency 1). This is per-request service latency, not
    open-loop arrival — coordinated omission applies (PERF-03).
    """

    CLOSED_SERIAL = "closed_serial"


def _round3(value: float) -> float:
    return round(float(value), 3)


def _nearest_rank(sorted_vals: Sequence[float], percentile: float) -> float:
    n = len(sorted_vals)
    rank = max(1, min(n, math.ceil(percentile / 100.0 * n)))
    return _round3(sorted_vals[rank - 1])


def summarize_latencies(latencies_s: Sequence[float]) -> dict[str, Any]:
    """Return n / nearest-rank p50/p95/p99 / max / mean.

    Nearest-rank (PERF-01): rank = ceil(P/100 * N), 1-based, on the sorted
    sample. Headline figures are the percentiles; ``mean_s`` is secondary.
    Empty input returns ``n=0`` and ``None`` for every numeric field (rg-015).
    Values are rounded to 3 decimal places.
    """
    if not latencies_s:
        return {
            "n": 0,
            "p50_s": None,
            "p95_s": None,
            "p99_s": None,
            "max_s": None,
            "mean_s": None,
        }
    ordered = sorted(float(v) for v in latencies_s)
    return {
        "n": len(ordered),
        "p50_s": _nearest_rank(ordered, 50),
        "p95_s": _nearest_rank(ordered, 95),
        "p99_s": _nearest_rank(ordered, 99),
        "max_s": _round3(ordered[-1]),
        "mean_s": _round3(sum(ordered) / len(ordered)),
    }


def _pass_latencies(item: Mapping[str, Any]) -> list[float]:
    describe = item.get("describe")
    passes: Any = None
    if isinstance(describe, Mapping):
        passes = describe.get("passes")
    if not isinstance(passes, list):
        passes = item.get("passes")
    if not isinstance(passes, list):
        return []
    out: list[float] = []
    for entry in passes:
        if not isinstance(entry, Mapping):
            continue
        raw = entry.get("latency_s")
        if raw is None:
            continue
        out.append(float(raw))
    return out


def collect_item_latencies(record: Mapping[str, Any]) -> list[float]:
    """Per-item wall-clock from ``describe.passes[].latency_s`` (summed).

    Items with a truthy item-level ``error`` are omitted (timeouts at the
    request ceiling, CircuitOpen at ~0, rg-015). Items whose item-level
    ``latency_s`` is ``None`` and that carry no usable pass latencies are
    omitted; callers count them as ``items_without_latency``. When passes
    exist, their non-None ``latency_s`` values are summed. A single-pass
    item without a ``passes`` list falls back to ``item["latency_s"]``.
    """
    items = record.get("items")
    if not isinstance(items, list):
        return []
    collected: list[float] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("error"):
            continue
        pass_lats = _pass_latencies(item)
        if pass_lats:
            collected.append(sum(pass_lats))
            continue
        raw = item.get("latency_s")
        if raw is None:
            continue
        collected.append(float(raw))
    return collected


class VramSampler:
    """Background ``nvidia-smi`` peak-used sampler (OBS-05 high-water mark).

    ``stop()`` emits two per-GPU arrays that answer different questions:

    * ``per_gpu_used_mb_at_peak``: used-MB per GPU from the same sample that
      set ``peak_used_mb``. Internally consistent with ``gpu_count`` and
      ``total_mb`` (row-count changes must not mix a peak-sample snapshot with
      a different topology). ``per_gpu_semantics`` names this rule.
    * ``per_gpu_peak_used_mb``: independent per-index high-water across all
      samples. Length is the max GPU index seen (1-based slot count), which
      can exceed ``gpu_count`` when topology shrinks after an earlier sample.

    ``runner`` is injectable for tests. Missing binary, errors, or zero samples
    yield ``status=unavailable`` plus a one-line ``reason`` — never a fabricated
    0 MB (rg-015, AGT-06). Unavailable still carries ``per_gpu_semantics`` and
    null arrays. Non-finite ``interval_s`` is rejected at construction (rg-008).
    """

    def __init__(
        self,
        interval_s: float = 1.0,
        runner: Callable[..., CompletedProcess[str]] | None = None,
    ) -> None:
        interval = float(interval_s)
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("interval_s must be a non-negative finite float")
        self.interval_s = interval
        self._runner: Callable[..., CompletedProcess[str]] = runner or subprocess.run
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_used: int | None = None
        self._total: int | None = None
        self._gpu_count: int | None = None
        self._per_gpu_at_peak: list[int] = []
        self._per_gpu_peak: list[int] = []
        self._samples = 0
        self._reason: str | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vram-sampler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        # Sample immediately so a short run still records a high-water mark.
        if self._sample():
            return
        while not self._stop.wait(self.interval_s):
            if self._sample():
                return

    def _sample(self) -> bool:
        """Return True when further samples cannot succeed (missing binary)."""
        try:
            proc = self._runner(
                _NVIDIA_SMI_QUERY,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            self._reason = "nvidia-smi not found"
            return True
        except Exception as exc:
            self._reason = f"{type(exc).__name__}: {exc}".splitlines()[0]
            return False
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "nvidia-smi failed").strip().splitlines()
            self._reason = (err[0] if err else "nvidia-smi failed")[:200]
            return False
        used_vals: list[int] = []
        total_vals: list[int] = []
        for line in (proc.stdout or "").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                used_vals.append(int(float(parts[0])))
                total_vals.append(int(float(parts[1])))
            except ValueError:
                continue
        if not used_vals:
            self._reason = "nvidia-smi produced no parseable GPU rows"
            return False
        sample_used = sum(used_vals)
        sample_total = sum(total_vals)
        self._samples += 1
        for i, used in enumerate(used_vals):
            if i == len(self._per_gpu_peak):
                self._per_gpu_peak.append(used)
            elif used > self._per_gpu_peak[i]:
                self._per_gpu_peak[i] = used
        if self._peak_used is None or sample_used > self._peak_used:
            self._peak_used = sample_used
            self._total = sample_total
            self._gpu_count = len(used_vals)
            self._per_gpu_at_peak = list(used_vals)
        return False

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=6.0)
            self._thread = None
        if self._samples == 0:
            return {
                "source": "nvidia-smi",
                "status": CaptureStatus.UNAVAILABLE,
                "peak_used_mb": None,
                "total_mb": None,
                "gpu_count": None,
                "per_gpu_used_mb_at_peak": None,
                "per_gpu_peak_used_mb": None,
                "per_gpu_semantics": PerGpuSemantics.SNAPSHOT_AT_AGGREGATE_PEAK_SAMPLE,
                "samples": 0,
                "reason": self._reason or "zero samples",
            }
        return {
            "source": "nvidia-smi",
            "status": CaptureStatus.MEASURED,
            "peak_used_mb": self._peak_used,
            "total_mb": self._total,
            "gpu_count": self._gpu_count,
            "per_gpu_used_mb_at_peak": list(self._per_gpu_at_peak),
            "per_gpu_peak_used_mb": list(self._per_gpu_peak),
            "per_gpu_semantics": PerGpuSemantics.SNAPSHOT_AT_AGGREGATE_PEAK_SAMPLE,
            "samples": self._samples,
            "interval_s": self.interval_s,
        }
