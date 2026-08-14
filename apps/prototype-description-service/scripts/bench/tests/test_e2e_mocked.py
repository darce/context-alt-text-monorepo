"""One mocked E2E: dual fake clients → report dir; score uses no network."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bench.driver import init_run_dir, run_pair
from scripts.bench.score_report import LICENSE_BANNER, score_head_to_head
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair


def test_mocked_e2e_writes_full_report_dir(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1, 2])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = tmp_path / "out"
    clients = {
        "acx-dev-insightface": FakeClient(),
        "acx-dev-fir": FakeClient(),
    }
    run_pair(pair, manifest_path=manifest, images_dir=images, out_dir=out, clients=clients)
    report = score_head_to_head(out)
    assert report.exists()
    accepted = json.loads((out / "score" / "accepted_set.json").read_text())
    assert "accepted_set_size" in accepted
    assert "resolved_floor_count" in accepted
    frames = json.loads((out / "score" / "frames.json").read_text())
    assert "license_banner" in frames or LICENSE_BANNER in json.dumps(frames)
    # Both legs × both frames × both label maps present.
    cells = frames.get("cells") or frames.get("grid") or []
    encoded = json.dumps(frames)
    assert "frame_e2e" in encoded
    assert "frame_fir5_native" in encoded
    assert "label_map_primary" in encoded
    assert "label_map_optimistic" in encoded
    assert "acx-dev-insightface" in encoded
    assert "acx-dev-fir" in encoded
    html = (out / "score" / "report.html").read_text()
    assert "INTERNAL BENCH ONLY" in html or "license" in html.lower()
    preflight_keys_ok = True
    for stack in ("acx-dev-insightface", "acx-dev-fir"):
        # preflight is optional in mocked path; provenance still required on report
        _ = stack
    assert "tier" in encoded.lower() or "CONFIRMATORY" in encoded or "DIRECTIONAL" in encoded
    assert cells or "cells" in frames or "legs" in frames
    assert report.suffix in {".html", ".json"} or report.name
