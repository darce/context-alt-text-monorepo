"""One mocked E2E: dual fake clients → report dir; score uses no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.bench import score_report as score_report_module
from scripts.bench.driver import init_run_dir, run_pair
from scripts.bench.score_report import LICENSE_BANNER, score_head_to_head
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair


def _fresh_reset_evidence() -> dict[str, dict[str, object]]:
    completed_at = datetime.now(UTC).isoformat()
    return {
        stack_id: {
            "reset_attested_by": "bench test operator",
            "reset_reference": "FIR23-STACK runbook reset",
            "reset_completed_at": completed_at,
            "prior_run_identity_rows_empty": True,
        }
        for stack_id in ("acx-dev-insightface", "acx-dev-fir")
    }


def test_mocked_e2e_writes_full_report_dir(tmp_path: Path, monkeypatch) -> None:
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
        pre_run_reset_by_stack=_fresh_reset_evidence(),
    )
    from scripts.bench.tests.conftest import write_stub_preflight

    for stack_id in clients:
        write_stub_preflight(out, stack_id)

    strict_calls: list[dict[str, object] | None] = []
    strict_detection_pr = score_report_module.detection_pr_strict

    def observe_strict_detection_pr(items, *, annotation_mode=None, run_manifest=None):
        strict_calls.append(run_manifest)
        return strict_detection_pr(
            items,
            annotation_mode=annotation_mode,
            run_manifest=run_manifest,
        )

    monkeypatch.setattr(score_report_module, "detection_pr_strict", observe_strict_detection_pr)
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
    assert "end-to-end embeddable-face yield among public exports" in html
    assert "Faces without embeddings are omitted from public export rows" in html
    assert "not detector-only recall" in html
    assert strict_calls
    assert all(call == {"iou_threshold": 0.5} for call in strict_calls)
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
