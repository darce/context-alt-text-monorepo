"""FIR-5 S5: perf_leg — detect+embed throughput + cost/1k + budget validation.

Covers FIR5-S5-BR-04: the cost/1k math, throughput measurement (via injected
wall time — no real timing flake), and load_budget structural validation
(rg-008) were previously untested.
"""

from __future__ import annotations

import json

import pytest

from scripts.eval_harness.perf_leg import (
    DEFAULT_BUDGET_PATH,
    PERF_LABEL,
    PerfLegError,
    cost_per_1k_images,
    load_budget,
    measure_detect_embed_throughput,
)


def test_cost_per_1k_images_known_value():
    # 10 img/s → 100 s per 1000 imgs → 100/3600 h × $3.60/h = $0.10.
    assert cost_per_1k_images(images_per_sec=10.0, usd_per_hour=3.60) == pytest.approx(0.10)
    # Free device → zero cost, not None.
    assert cost_per_1k_images(images_per_sec=10.0, usd_per_hour=0.0) == pytest.approx(0.0)


def test_cost_per_1k_images_guards():
    assert cost_per_1k_images(images_per_sec=0.0, usd_per_hour=3.60) is None
    assert cost_per_1k_images(images_per_sec=-1.0, usd_per_hour=3.60) is None
    assert cost_per_1k_images(images_per_sec=10.0, usd_per_hour=-0.01) is None


def _budget_file(tmp_path, obj):
    p = tmp_path / "budget.json"
    p.write_text(json.dumps(obj))
    return p


def test_load_budget_default_is_valid():
    raw = load_budget()
    assert isinstance(raw["devices"], dict) and raw["devices"]
    for spec in raw["devices"].values():
        assert "usd_per_hour" in spec
    # The default path resolves to the shipped budget file.
    assert DEFAULT_BUDGET_PATH.is_file()


def test_load_budget_rejects_malformed(tmp_path):
    with pytest.raises(PerfLegError, match="not found"):
        load_budget(tmp_path / "missing.json")
    with pytest.raises(PerfLegError, match="root must be an object"):
        load_budget(_budget_file(tmp_path, [1, 2, 3]))
    with pytest.raises(PerfLegError, match="non-empty object"):
        load_budget(_budget_file(tmp_path, {"devices": {}}))
    with pytest.raises(PerfLegError, match="usd_per_hour"):
        load_budget(_budget_file(tmp_path, {"devices": {"a10": {"notes": "x"}}}))


def test_measure_detect_embed_throughput_injected_walltime(tmp_path):
    budget = _budget_file(tmp_path, {"schema": "acx-perf/v1", "devices": {"a1_flex": {"usd_per_hour": 0.152}}})
    images = ["i0", "i1", "i2", "i3"]  # 4 images

    def process(_img):
        return [object(), object()]  # 2 embeddings per image

    out = measure_detect_embed_throughput(
        process, images, device="a1_flex", budget_path=budget, wall_seconds=2.0
    )
    assert out["label"] == PERF_LABEL
    assert out["n_images"] == 4
    assert out["n_embeddings"] == 8
    assert out["images_per_sec"] == pytest.approx(2.0)  # 4 imgs / 2 s
    assert out["embeddings_per_sec"] == pytest.approx(4.0)  # 8 / 2 s
    assert out["sec_per_image"] == pytest.approx(0.5)  # 2 s / 4 imgs
    # cost/1k = (1000/2)/3600 h × $0.152 = 0.5 h/1k... → 0.021111
    assert out["cost_per_1k_usd"] == pytest.approx((1000.0 / 2.0) / 3600.0 * 0.152, rel=1e-4)
    assert out["device"] == "a1_flex"
    assert out["usd_per_hour"] == pytest.approx(0.152)


def test_measure_detect_embed_throughput_guards(tmp_path):
    budget = _budget_file(tmp_path, {"devices": {"a1_flex": {"usd_per_hour": 0.152}}})

    def process(_img):
        return [object()]

    with pytest.raises(PerfLegError, match="empty"):
        measure_detect_embed_throughput(process, [], budget_path=budget)
    with pytest.raises(PerfLegError, match="unknown device"):
        measure_detect_embed_throughput(process, ["i0"], device="gpu99", budget_path=budget)
    with pytest.raises(PerfLegError, match="wall time must be > 0"):
        measure_detect_embed_throughput(process, ["i0"], budget_path=budget, wall_seconds=0.0)
