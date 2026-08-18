"""VLM6-RV3-Q4-01: bench driver metadata-only loads ignore ambient GOLDEN_IMAGES_DIR."""

from __future__ import annotations

from pathlib import Path

from scripts.bench.driver import run_pair
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair


def test_run_pair_ignores_empty_golden_images_dir(tmp_path: Path, monkeypatch) -> None:
    """Driver reads media ids only at start; empty env dir must not fail the load.

    Mutation: removing metadata_only=True from driver.run_pair load_manifest
    fails with ManifestError: image file missing.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair_path = write_pair(tmp_path / "pair.yaml")
    run_pair(
        load_stack_pair(pair_path),
        manifest_path=manifest,
        images_dir=images,
        out_dir=tmp_path / "out",
        clients={
            "acx-dev-insightface": FakeClient(),
            "acx-dev-fir": FakeClient(),
        },
        skip_preflight=True,
    )
    assert (tmp_path / "out").exists()
