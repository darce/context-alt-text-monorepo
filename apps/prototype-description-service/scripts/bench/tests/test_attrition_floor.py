"""Floor resolution + differential-attrition ordering + zero-detection stays in recall denom."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.bench.score_report import (
    compute_accepted_set,
    resolve_floor_count,
    score_head_to_head,
)
from scripts.bench.stack_pair import BenchError, load_stack_pair
from scripts.bench.tests.conftest import valid_pair_dict, write_pair


def test_fractional_floor_resolution() -> None:
    # N=150, 0.90 → 135
    assert resolve_floor_count(0.90, 150) == 135
    assert resolve_floor_count(0.90, 4) == max(2, math.ceil(0.90 * 4))


def test_absolute_floor_resolution() -> None:
    assert resolve_floor_count(2, 10) == 2
    assert resolve_floor_count(135, 150) == 135


def test_zero_detection_accepted_item_stays_in_denominator(tmp_path: Path) -> None:
    """Roster-present zero-export item is a scored miss, not dropped from recall denom."""
    run_dir = _two_leg_run(tmp_path, media_ids=[1, 2], zero_export={2})
    accepted = compute_accepted_set(run_dir)
    assert 2 in accepted.manifest_media_ids
    report_dir = score_head_to_head(run_dir)
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    # Some detection cell must have labeled count including the zero-export item.
    encoded = json.dumps(frames)
    assert accepted.zero_detection_media_count >= 1
    assert frames["zero_detection_media_count"] == accepted.zero_detection_media_count
    assert report_dir.exists()


def test_analyze_failure_is_not_ingest_attrition(tmp_path: Path) -> None:
    run_dir = _two_leg_run(tmp_path, media_ids=[1, 2], zero_export=set())
    # Mark media 2 analyze-failed on both legs after a successful ingest row.
    for stack in ("acx-dev-insightface", "acx-dev-fir"):
        path = run_dir / "legs" / stack / "items.jsonl"
        recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        recs = [r for r in recs if not (r.get("manifest_media_id") == 2 and r.get("phase") == "analyze")]
        recs.append(
            {
                "manifest_media_id": 2,
                "phase": "analyze",
                "outcome": "failed",
                "attempt": 2,
                "terminal_ingest_outcome": "success",
                "error_code": "analyze_failed",
            }
        )
        path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
        export_path = run_dir / "legs" / stack / "exports" / "media_identities.json"
        rows = [r for r in json.loads(export_path.read_text()) if r.get("media_id") != 2]
        export_path.write_text(json.dumps(rows), encoding="utf-8")
    accepted = compute_accepted_set(run_dir)
    assert 2 not in accepted.manifest_media_ids
    assert accepted.attrition_ingest_analyze >= 1
    attrition = json.loads((run_dir / "score" / "attrition.json").read_text()) if (run_dir / "score" / "attrition.json").is_file() else None
    from scripts.bench.score_report import write_attrition
    from scripts.bench.corpus import ItemOutcomeStore, load_bench_manifest

    # Metadata-only rescore (records/manifest fields, no image bytes opened) — same
    # contract as score_report.py::_load_manifest_from_run (VLM6-MERGE-01).
    manifest = load_bench_manifest(
        run_dir / "manifest.json",
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="attrition rescore is metadata-only; image bytes never opened",
    )
    records_by = {
        p.name: ItemOutcomeStore(p / "items.jsonl").read_all() for p in (run_dir / "legs").iterdir() if p.is_dir()
    }
    write_attrition(run_dir, accepted, manifest, records_by)
    payload = json.loads((run_dir / "score" / "attrition.json").read_text())
    missing = {row["manifest_media_id"]: row["phase"] for row in payload["missing"]}
    assert missing.get(2) == "analyze"
    _ = attrition


def test_join_attrition_when_ingest_row_missing(tmp_path: Path) -> None:
    run_dir = _two_leg_run(tmp_path, media_ids=[1, 2], zero_export=set())
    for stack in ("acx-dev-insightface", "acx-dev-fir"):
        path = run_dir / "legs" / stack / "items.jsonl"
        recs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        recs = [r for r in recs if not (r.get("manifest_media_id") == 2 and r.get("phase") == "ingest")]
        path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    accepted = compute_accepted_set(run_dir)
    assert 2 not in accepted.manifest_media_ids
    assert accepted.attrition_join >= 1
    from scripts.bench.score_report import write_attrition
    from scripts.bench.corpus import ItemOutcomeStore, load_bench_manifest

    # Metadata-only rescore — same contract as score_report.py::_load_manifest_from_run
    # (VLM6-MERGE-01): no image bytes are opened here, only manifest fields.
    manifest = load_bench_manifest(
        run_dir / "manifest.json",
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="attrition rescore is metadata-only; image bytes never opened",
    )
    records_by = {
        p.name: ItemOutcomeStore(p / "items.jsonl").read_all() for p in (run_dir / "legs").iterdir() if p.is_dir()
    }
    write_attrition(run_dir, accepted, manifest, records_by)
    payload = json.loads((run_dir / "score" / "attrition.json").read_text())
    missing = {row["manifest_media_id"]: row["phase"] for row in payload["missing"]}
    assert missing.get(2) == "roster"


def test_baseline_superset_checked_false_unless_run_asserted(tmp_path: Path) -> None:
    run_dir = _two_leg_run(tmp_path, media_ids=[1, 2], zero_export=set())
    accepted = compute_accepted_set(run_dir)
    assert accepted.baseline_superset_checked is False
    run_doc = json.loads((run_dir / "run.json").read_text())
    run_doc["baseline_superset_checked"] = True
    (run_dir / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")
    accepted2 = compute_accepted_set(run_dir)
    assert accepted2.baseline_superset_checked is True


def test_export_media_not_in_roster_fail_closed(tmp_path: Path) -> None:
    run_dir = _two_leg_run(tmp_path, media_ids=[1, 2], zero_export=set())
    foreign = {
        "identity_id": "x",
        "media_id": 999,
        "cluster_id": "c1",
        "cluster_label": "Alice Q",
        "is_auto_label": False,
        "bbox": {"x": 400, "y": 400, "width": 200, "height": 200},
    }
    path = run_dir / "legs" / "acx-dev-insightface" / "exports" / "media_identities.json"
    rows = json.loads(path.read_text())
    rows.append(foreign)
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        compute_accepted_set(run_dir)
    assert exc.value.code == "export_media_not_in_roster"


def test_manifest_id_echo_export_row_is_refused(tmp_path: Path) -> None:
    """Export row keyed by manifest id (not stack_media_id) must fail closed."""
    run_dir = _two_leg_run(tmp_path, media_ids=[1, 2], zero_export=set())
    for stack in ("acx-dev-insightface", "acx-dev-fir"):
        items = run_dir / "legs" / stack / "items.jsonl"
        recs = [json.loads(line) for line in items.read_text().splitlines() if line.strip()]
        for rec in recs:
            if rec.get("manifest_media_id") == 1:
                rec["stack_media_id"] = 42
        items.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
        export_path = run_dir / "legs" / stack / "exports" / "media_identities.json"
        rows = json.loads(export_path.read_text())
        for row in rows:
            if row.get("media_id") == 1:
                row["media_id"] = 42
        # Manifest-id echo: media_id=2 is a real manifest id but not a stack id here
        # (stack ids are 42 for media 1 and 2 for media 2). Add a row with media_id=1
        # after remapping media 1's stack id to 42 — old OR-chain would accept 1.
        rows.append(
            {
                "identity_id": "echo",
                "media_id": 1,
                "cluster_id": "c1",
                "cluster_label": "Alice Q",
                "is_auto_label": False,
                "bbox": {"x": 400, "y": 400, "width": 200, "height": 200},
            }
        )
        export_path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        compute_accepted_set(run_dir)
    assert exc.value.code == "export_media_not_in_roster"


def test_differential_attrition_writes_artifacts_then_refuses(tmp_path: Path) -> None:
    # One-sided: leg A accepts 1,2,3; leg B accepts only 1. |3-0|/3 = 1.0 > 0.05
    run_dir = _asymmetric_run(tmp_path, a_ok=[1, 2, 3], b_ok=[1])
    with pytest.raises(BenchError) as exc:
        score_head_to_head(run_dir)
    assert exc.value.code == "differential_attrition_exceeded"
    assert (run_dir / "score" / "accepted_set.json").is_file()
    assert (run_dir / "score" / "attrition.json").is_file()
    frames_path = run_dir / "score" / "frames.json"
    if frames_path.is_file():
        frames = json.loads(frames_path.read_text())
        cells = frames.get("cells") or []
        assert cells == [] or frames.get("pr_cells_emitted") is False


def _write_leg(run_dir: Path, stack_id: str, ok_ids: list[int], *, zero_export: set[int] | None = None) -> None:
    zero_export = zero_export or set()
    leg = run_dir / "legs" / stack_id
    (leg / "exports").mkdir(parents=True, exist_ok=True)
    lines = []
    identities = []
    for mid in ok_ids:
        rec = {
            "manifest_media_id": mid,
            "manifest_path": f"img_{mid}.jpg",
            "content_sha256": "a" * 64,
            "stack_media_id": mid,
            "image_width": 1000,
            "image_height": 1000,
            "phase": "analyze",
            "outcome": "ok",
            "attempt": 1,
            "terminal_ingest_outcome": "success",
        }
        lines.append(json.dumps(rec))
        lines.append(
            json.dumps({**rec, "phase": "ingest"})
        )
        if mid not in zero_export:
            identities.append(
                {
                    "identity_id": f"id-{mid}",
                    "media_id": mid,
                    "cluster_id": "c1",
                    "cluster_label": "Alice Q",
                    "is_auto_label": False,
                    "bbox": {"x": 400, "y": 400, "width": 200, "height": 200},
                }
            )
    (leg / "items.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (leg / "exports" / "media_identities.json").write_text(json.dumps(identities), encoding="utf-8")
    (leg / "exports" / "clusters.json").write_text(
        json.dumps([{"id": "c1", "label": "Alice Q", "is_auto_label": False}]),
        encoding="utf-8",
    )
    (leg / "exports" / "cluster_members.json").write_text(
        json.dumps([{"cluster_id": "c1", "members": [{"media_id": m} for m in ok_ids if m not in zero_export]}]),
        encoding="utf-8",
    )
    (leg / "preflight.json").write_text(
        json.dumps(
            {
                "stack_id": stack_id,
                "base_url": "https://dev.api.altcontext.com"
                if "insight" in stack_id
                else "https://fir.api.altcontext.com",
                "expected_profile": "insightface" if "insight" in stack_id else "face_pipeline",
                "expected_pgvector_dim": 512 if "insight" in stack_id else 128,
                "resolved_profile": "insightface" if "insight" in stack_id else "face_pipeline",
                "resolved_pgvector_dim": 512 if "insight" in stack_id else 128,
                "opencv_major": 5,
                "opencv_major_source": "operator_attested",
                "checked_at": "2026-07-29T00:00:00Z",
                "ready_excerpt": {},
                "health_detailed_excerpt": {},
            }
        ),
        encoding="utf-8",
    )


def _write_run_meta(run_dir: Path, tmp_path: Path, media_ids: list[int]) -> None:
    from scripts.bench.tests.conftest import write_manifest

    manifest = write_manifest(tmp_path / "manifest.json", media_ids, roster=["Alice Q"])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(accepted_set_floor=0.5)))
    from scripts.bench.driver import init_run_dir

    init_run_dir(run_dir, pair, manifest)
    (run_dir / "manifest.json").write_bytes(manifest.read_bytes())


def _two_leg_run(tmp_path: Path, media_ids: list[int], zero_export: set[int]) -> Path:
    run_dir = tmp_path / "run"
    _write_run_meta(run_dir, tmp_path, media_ids)
    _write_leg(run_dir, "acx-dev-insightface", media_ids, zero_export=zero_export)
    _write_leg(run_dir, "acx-dev-fir", media_ids, zero_export=zero_export)
    return run_dir


def _asymmetric_run(tmp_path: Path, a_ok: list[int], b_ok: list[int]) -> Path:
    all_ids = sorted(set(a_ok) | set(b_ok))
    run_dir = tmp_path / "run"
    _write_run_meta(run_dir, tmp_path, all_ids)
    _write_leg(run_dir, "acx-dev-insightface", a_ok)
    _write_leg(run_dir, "acx-dev-fir", b_ok)
    return run_dir
