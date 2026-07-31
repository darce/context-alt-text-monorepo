"""Detect+embed throughput + cost/1k leg for face bake-off (FIR-5 S5).

Explicitly NOT full-scan p95 (runtime path; FIR-6-owned). Label every report as
``detect+embed-only`` (COST-04/15).

Reads device budgets + $/hr from ``perf_budgets/face_bakeoff_budget.json``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

DEFAULT_BUDGET_PATH = Path(__file__).parent / "perf_budgets" / "face_bakeoff_budget.json"
PERF_LABEL = "detect+embed-only"


class PerfLegError(ValueError):
    """Budget file missing/malformed or throughput inputs invalid."""


def load_budget(path: str | Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the face bake-off budget JSON (rg-008)."""
    budget_path = Path(path) if path is not None else DEFAULT_BUDGET_PATH
    if not budget_path.is_file():
        raise PerfLegError(f"budget file not found: {budget_path}")
    raw = json.loads(budget_path.read_text())
    if not isinstance(raw, dict):
        raise PerfLegError("budget root must be an object")
    devices = raw.get("devices")
    if not isinstance(devices, dict) or not devices:
        raise PerfLegError("budget.devices must be a non-empty object")
    for name, spec in devices.items():
        if not isinstance(spec, dict):
            raise PerfLegError(f"budget.devices[{name!r}] must be an object")
        if "usd_per_hour" not in spec:
            raise PerfLegError(f"budget.devices[{name!r}] missing required usd_per_hour")
    return raw


def cost_per_1k_images(*, images_per_sec: float, usd_per_hour: float) -> float | None:
    """Estimated USD per 1000 images at sustained detect+embed throughput."""
    if images_per_sec <= 0 or usd_per_hour < 0:
        return None
    hours_per_1k = (1000.0 / images_per_sec) / 3600.0
    return hours_per_1k * usd_per_hour


def measure_detect_embed_throughput(
    process_fn: Callable[[Any], Sequence[Any]],
    images: Sequence[Any],
    *,
    device: str = "a1_flex",
    budget_path: str | Path | None = None,
    wall_seconds: float | None = None,
) -> dict[str, Any]:
    """Measure detect+embed-only throughput over ``images``.

    ``process_fn(image)`` returns the list of embeddings/faces produced for one
    image (length = embeddings count). Does not include persist/cluster/job.

    ``wall_seconds`` may be supplied to inject a measured wall time (tests);
    otherwise wall time is measured around the loop.
    """
    if not images:
        raise PerfLegError("images sequence is empty — cannot measure throughput")
    budget = load_budget(budget_path)
    devices = budget["devices"]
    if device not in devices:
        raise PerfLegError(
            f"unknown device {device!r}; known: {sorted(devices)}"
        )
    usd_per_hour = float(devices[device]["usd_per_hour"])

    n_images = len(images)
    n_embeddings = 0
    if wall_seconds is None:
        t0 = time.perf_counter()
        for img in images:
            faces = process_fn(img)
            n_embeddings += len(faces) if faces is not None else 0
        elapsed = time.perf_counter() - t0
    else:
        for img in images:
            faces = process_fn(img)
            n_embeddings += len(faces) if faces is not None else 0
        elapsed = float(wall_seconds)

    if elapsed <= 0:
        raise PerfLegError("elapsed wall time must be > 0")

    images_per_sec = n_images / elapsed
    embeddings_per_sec = n_embeddings / elapsed
    sec_per_image = elapsed / n_images
    cost_1k = cost_per_1k_images(images_per_sec=images_per_sec, usd_per_hour=usd_per_hour)

    return {
        "label": PERF_LABEL,
        "note": "detect+embed-only (COST-04/15); p95 full-scan latency is FIR-6-owned",
        "device": device,
        "usd_per_hour": usd_per_hour,
        "n_images": n_images,
        "n_embeddings": n_embeddings,
        "elapsed_s": round(elapsed, 6),
        "images_per_sec": round(images_per_sec, 6),
        "embeddings_per_sec": round(embeddings_per_sec, 6),
        "sec_per_image": round(sec_per_image, 6),
        "cost_per_1k_usd": None if cost_1k is None else round(cost_1k, 6),
        "budget_schema": budget.get("schema"),
        "device_notes": devices[device].get("notes"),
    }


__all__ = [
    "DEFAULT_BUDGET_PATH",
    "PERF_LABEL",
    "PerfLegError",
    "cost_per_1k_images",
    "load_budget",
    "measure_detect_embed_throughput",
]
