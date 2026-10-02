"""One mocked E2E: dual fake clients → report dir; score uses no network."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.bench import score_report as score_report_module
from scripts.bench.driver import init_run_dir, run_pair
from scripts.bench.score_report import LICENSE_BANNER, score_head_to_head
from scripts.bench.stack_pair import BenchError, load_stack_pair
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
    manifest_payload = json.loads(manifest.read_text())
    manifest_payload["iou_threshold"] = 0.75
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
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
    for stack_id in clients:
        identities_path = out / "legs" / stack_id / "exports" / "media_identities.json"
        identities = json.loads(identities_path.read_text())
        for identity in identities:
            identity["bbox"]["x"] = 2
        identities_path.write_text(json.dumps(identities), encoding="utf-8")
        export_digests_path = identities_path.parent / "export_sha256.json"
        export_digests = json.loads(export_digests_path.read_text(encoding="utf-8"))
        export_digests[identities_path.name] = hashlib.sha256(identities_path.read_bytes()).hexdigest()
        export_digests_path.write_text(json.dumps(export_digests), encoding="utf-8")
    from scripts.bench.tests.conftest import write_stub_preflight

    for stack_id in clients:
        write_stub_preflight(out, stack_id)

    strict_calls: list[dict[str, object] | None] = []
    strict_detection_pr = score_report_module.detection_pr_strict
    bootstrap_inputs: list[tuple[list[object], list[object]]] = []
    bootstrap_paired_delta = score_report_module.bootstrap_paired_delta

    def observe_strict_detection_pr(items, *, annotation_mode=None, run_manifest=None):
        strict_calls.append(run_manifest)
        return strict_detection_pr(
            items,
            annotation_mode=annotation_mode,
            run_manifest=run_manifest,
        )

    def observe_bootstrap_paired_delta(a, b, seed, **kwargs):
        if kwargs.get("cell") == "detection_recall@frame_e2e/label_map_primary":
            bootstrap_inputs.append((list(a), list(b)))
        return bootstrap_paired_delta(a, b, seed, **kwargs)

    monkeypatch.setattr(score_report_module, "detection_pr_strict", observe_strict_detection_pr)
    monkeypatch.setattr(score_report_module, "bootstrap_paired_delta", observe_bootstrap_paired_delta)
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
    assert all(call == {"iou_threshold": 0.75} for call in strict_calls)
    assert len(bootstrap_inputs) == 1
    for series in bootstrap_inputs[0]:
        assert [(item.tp, item.fp, item.fn) for item in series] == [(0, 1, 1), (0, 1, 1)]
    tiers = {c.get("tier") for c in cells if isinstance(c, dict) and "tier" in c}
    assert tiers & {"CONFIRMATORY", "DIRECTIONAL", "DIAGNOSTIC"}
    primary = [
        c for c in cells if c.get("cell") == "detection_recall@frame_e2e/label_map_primary"
    ]
    assert primary
    for cell in primary:
        assert cell["value"] == 0.0
        assert cell["true_positives"] == 0
        assert cell["false_positives"] == 2
        assert cell["false_negatives"] == 2
        assert cell["precision"] == 0.0
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


def test_score_refuses_v3_manifest_without_ratified_iou_threshold(tmp_path: Path) -> None:
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

    with pytest.raises(BenchError, match=str(out / "manifest.json")) as exc:
        score_head_to_head(out)

    assert exc.value.code == "manifest_iou_threshold_missing"


def test_empty_detection_population_emits_directional_cells(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1, 2])
    payload = json.loads(manifest.read_text())
    payload["iou_threshold"] = 0.5
    for entry in payload["entries"]:
        entry["face_count"] = 0
        entry["face_boxes"] = []
        entry["present_identities"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")
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

    assert score_head_to_head(out).exists()
    accepted = json.loads((out / "score" / "accepted_set.json").read_text())
    assert accepted["accepted_set_size"] == 2
    assert accepted["detection_scoring_set_size"] == 0
    frames = json.loads((out / "score" / "frames.json").read_text())
    primary = [
        cell for cell in frames["cells"]
        if cell["cell"] == "detection_recall@frame_e2e/label_map_primary"
    ]
    assert len(primary) == 2
    for cell in primary:
        assert cell["tier"] == "DIRECTIONAL"
        assert cell["true_positives"] == 0
        assert cell["false_positives"] == 0
        assert cell["false_negatives"] == 0
        assert cell["ci_half_width"] is None
        assert cell["p_value"] is None
        assert cell["primary_claim_type"] == "unsupported"
