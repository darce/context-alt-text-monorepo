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
    run_pair(
        pair,
        manifest_path=manifest,
        images_dir=images,
        out_dir=out,
        clients=clients,
        skip_preflight=True,
    )
    from scripts.bench.tests.conftest import write_stub_preflight

    for stack_id in clients:
        write_stub_preflight(out, stack_id)
    report = score_head_to_head(out)
    assert report.exists()
    accepted = json.loads((out / "score" / "accepted_set.json").read_text())
    assert accepted["accepted_set_size"] == 2
    assert accepted["resolved_floor_count"] == 2
    frames = json.loads((out / "score" / "frames.json").read_text())
    assert "license_banner" in frames or LICENSE_BANNER in json.dumps(frames)
    cells = frames.get("cells")
    assert isinstance(cells, list) and cells
    encoded = json.dumps(frames)
    assert "frame_e2e" in encoded
    assert "frame_fir5_native" in encoded
    assert "label_map_primary" in encoded
    assert "label_map_optimistic" in encoded
    assert "acx-dev-insightface" in encoded
    assert "acx-dev-fir" in encoded
    html = (out / "score" / "report.html").read_text()
    assert "INTERNAL BENCH ONLY" in html
    tiers = {c.get("tier") for c in cells if isinstance(c, dict) and "tier" in c}
    assert tiers & {"CONFIRMATORY", "DIRECTIONAL", "DIAGNOSTIC"}
    primary = [
        c for c in cells if c.get("cell") == "detection_recall@frame_e2e/label_map_primary"
    ]
    assert primary
    for cell in primary:
        assert cell["value"] == 1.0
        assert cell["true_positives"] == 2
        assert cell["false_negatives"] == 0
        assert cell["precision"] == 1.0
        assert cell["ci_half_width"] == 0.0
        assert cell["p_value"] == 1.0
    native_id = [
        c
        for c in cells
        if c.get("cell") == "identification_recall@frame_fir5_native/label_map_primary"
    ]
    assert native_id
    for cell in native_id:
        assert cell.get("ci_half_width") is None
        assert "holm_significant" not in cell or cell.get("holm_significant") in {None, False}
    assert report.suffix == ".html"
