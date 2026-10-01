"""The bench manifest must fit the analyze route's media-id representation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bench.corpus import load_bench_manifest
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.conftest import write_manifest
from scripts.eval_harness.manifest import GoldenManifest


def _load_metadata_manifest(path: Path) -> GoldenManifest:
    return load_bench_manifest(
        path,
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="media-id ceiling check does not open image bytes",
    )


def test_manifest_media_id_ceiling_includes_999999_and_rejects_1000000(tmp_path) -> None:
    boundary_path = write_manifest(tmp_path / "at-ceiling.json", [999_999])
    manifest = _load_metadata_manifest(boundary_path)
    assert [entry.media_id for entry in manifest.entries] == [999_999]

    over_ceiling_path = write_manifest(tmp_path / "over-ceiling.json", [1_000_000])
    with pytest.raises(BenchError, match="exceeds analyze route ceiling") as exc:
        _load_metadata_manifest(over_ceiling_path)
    assert exc.value.code == "media_id_exceeds_analyze_ceiling"
