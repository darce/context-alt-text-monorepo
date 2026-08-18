"""VLM6-RV3-Q4-01: bench metadata-only loads ignore ambient GOLDEN_IMAGES_DIR."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bench.corpus import load_bench_manifest
from scripts.bench.score_report import _load_manifest_from_run
from scripts.bench.tests.conftest import write_manifest
from scripts.eval_harness.manifest import ManifestError


def test_load_bench_manifest_metadata_only_ignores_empty_golden_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Byte-free wrapper must not resolve an empty ambient GOLDEN_IMAGES_DIR.

    Mutation: dropping metadata_only=True from this call (or from the
    load_manifest forward) fails with ManifestError: image file missing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    path = write_manifest(tmp_path / "manifest.json", [1])
    manifest = load_bench_manifest(
        path,
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="metadata-only bench load; image bytes never opened",
    )
    assert {e.media_id for e in manifest.entries} == {1}


def test_load_manifest_from_run_ignores_empty_golden_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Score/report reader is byte-free; empty ambient dir must not fail the load.

    Mutation: removing metadata_only=True from _load_manifest_from_run
    fails with ManifestError: image file missing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_manifest(run_dir / "manifest.json", [1, 2])
    manifest = _load_manifest_from_run(run_dir)
    assert {e.media_id for e in manifest.entries} == {1, 2}


def test_load_bench_manifest_metadata_only_with_images_dir_raises(tmp_path: Path) -> None:
    """Contract: metadata_only=True cannot pair with an explicit images_dir.

    Mutation: swallowing images_dir when metadata_only=True makes this pass.
    """
    images = tmp_path / "images"
    images.mkdir()
    path = write_manifest(tmp_path / "manifest.json", [1])
    with pytest.raises(ManifestError, match="metadata_only"):
        load_bench_manifest(
            path,
            images_dir=str(images),
            metadata_only=True,
            skip_hash_verification=True,
            hash_skip_reason="contract: cannot pair with images_dir",
        )
