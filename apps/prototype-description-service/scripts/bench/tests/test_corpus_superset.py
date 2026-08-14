"""Baseline superset blocker at run start (CF-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bench.corpus import assert_baseline_superset
from scripts.bench.driver import run_pair
from scripts.bench.stack_pair import BenchError, load_stack_pair
from scripts.bench.tests.conftest import (
    FakeClient,
    valid_pair_dict,
    write_hashed_manifest,
    write_manifest,
    write_pair,
)


def test_partial_intersection_is_blocker() -> None:
    with pytest.raises(BenchError) as exc:
        assert_baseline_superset({1, 2, 3}, {1, 2})
    assert exc.value.code == "baseline_not_superset"


def test_baseline_superset_passes() -> None:
    assert_baseline_superset({1, 2}, {1, 2, 3})


def test_run_start_blocks_before_media_write(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path / "manifest.json", [1, 2, 3])
    baseline = write_manifest(tmp_path / "baseline.json", [1, 2])
    payload = valid_pair_dict(baseline_manifest_path=str(baseline))
    pair = write_pair(tmp_path / "pair.yaml", payload)
    out = tmp_path / "out"
    images = tmp_path / "images"
    images.mkdir()
    with pytest.raises(BenchError) as exc:
        run_pair(
            load_stack_pair(pair),
            manifest_path=manifest,
            images_dir=images,
            out_dir=out,
            clients={
                "acx-dev-insightface": FakeClient(),
                "acx-dev-fir": FakeClient(),
            },
        )
    assert exc.value.code == "baseline_not_superset"
    # No media write / analyze before the blocker.
    assert not list(out.rglob("items.jsonl"))


def test_absent_baseline_key_skips_assert(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair_path = write_pair(tmp_path / "pair.yaml")
    config = load_stack_pair(pair_path)
    assert config.baseline_manifest_path is None
    fake_a = FakeClient()
    fake_b = FakeClient()
    run_pair(
        config,
        manifest_path=manifest,
        images_dir=images,
        out_dir=tmp_path / "out",
        clients={
            "acx-dev-insightface": fake_a,
            "acx-dev-fir": fake_b,
        },
        skip_preflight=True,
    )
    assert fake_a.analyze_calls
    assert fake_b.analyze_calls
