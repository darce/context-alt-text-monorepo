"""TEST-15 pin: metadata-only report scoring must skip hash verification by
name, and every other load_bench_manifest caller must keep verifying by
default (VLM6-MERGE-01).

_load_manifest_from_run (score_report.py) never opens image bytes — it only
reads manifest fields already pinned by a completed run — so it is entitled
to skip_hash_verification=True. load_bench_manifest's *default* behaviour
(no images_dir, no explicit skip) must keep raising ManifestError, because
every other caller (driver.py's run_leg/run_pair preflight checks) relies on
that default to catch a corrupted/relabeled corpus before any path that may
read image bytes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bench.corpus import load_bench_manifest
from scripts.bench.score_report import _load_manifest_from_run
from scripts.bench.tests.conftest import write_manifest
from scripts.eval_harness.manifest import ManifestError


def test_load_manifest_from_run_succeeds_on_nonexistent_image_paths(tmp_path: Path) -> None:
    """(a) Metadata-only report scoring must not require image bytes to exist."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # write_manifest points entries at fixtures/m{id}.jpg, which are never
    # created on disk here — proving _load_manifest_from_run reads metadata
    # only and never touches the filesystem paths it names.
    write_manifest(run_dir / "manifest.json", [1, 2])
    for mid in (1, 2):
        assert not (run_dir / f"fixtures/m{mid}.jpg").exists()

    manifest = _load_manifest_from_run(run_dir)

    assert {e.media_id for e in manifest.entries} == {1, 2}


def test_load_bench_manifest_default_still_raises_without_images_dir(tmp_path: Path) -> None:
    """(b) load_bench_manifest's default kwargs (no skip) must keep refusing."""
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest_path, [1])

    with pytest.raises(ManifestError):
        load_bench_manifest(manifest_path, None)
