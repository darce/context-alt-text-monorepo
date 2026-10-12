"""G3: persisted bundle lineage must pass the producer contract before P/R.

PROV-01 — Every output walks back to its evidence (Model Cards + AI
Engineering). TEST-15 — Prove the green can go red (The Pragmatic
Programmer, ch. 9). These regressions intentionally fail on source 73db482d.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench.preflight import PreflightError, _parse_model_bundle_provenance
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.conftest import golden_entry
from scripts.bench.tests.test_score_head_to_head import (
    A_STACK,
    B_STACK,
    _box,
    _init,
    _pred,
    _write_leg,
)

STACKS = (A_STACK, B_STACK)
BUNDLES = {
    A_STACK: {"model_name": "buffalo_l", "bundle_files": 5, "bundle_sha256": "a" * 64},
    B_STACK: {"model_name": "sface", "bundle_files": 1, "bundle_sha256": "b" * 64},
}
INVALID_BUNDLES = [
    pytest.param("bundle_sha256", None, id="missing-digest"),
    pytest.param("bundle_sha256", "", id="empty-digest"),
    pytest.param("bundle_sha256", "a" * 63, id="short-digest"),
    pytest.param("bundle_sha256", "g" * 64, id="nonhex-digest"),
    pytest.param("bundle_sha256", "A" * 64, id="uppercase-digest"),
    pytest.param("bundle_sha256", 123, id="nonstring-digest"),
    pytest.param("model_name", None, id="missing-name"),
    pytest.param("model_name", "  ", id="blank-name"),
    pytest.param("bundle_files", None, id="missing-count"),
    pytest.param("bundle_files", 0, id="zero-count"),
    pytest.param("bundle_files", -1, id="negative-count"),
    pytest.param("bundle_files", True, id="boolean-count"),
    pytest.param("bundle_files", 1.0, id="float-count"),
    pytest.param("bundle_files", ["a.onnx"], id="list-count"),
]


def _preflight_path(run_dir: Path, stack_id: str) -> Path:
    return run_dir / "legs" / stack_id / "preflight.json"


@pytest.fixture
def lineage_run(tmp_path: Path) -> Path:
    media_ids = [1, 2]
    entries = [
        golden_entry(mid, face_count=1, face_boxes=[_box()]) for mid in media_ids
    ]
    run_dir = _init(tmp_path, media_ids, entries)
    for stack_id in STACKS:
        _write_leg(run_dir, stack_id, [_pred(mid) for mid in media_ids], media_ids)
        path = _preflight_path(run_dir, stack_id)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["health_detailed_excerpt"]["model_cache"].update(BUNDLES[stack_id])
        _parse_model_bundle_provenance(doc["health_detailed_excerpt"])
        path.write_text(json.dumps(doc), encoding="utf-8")
    return run_dir


def _assert_no_metrics(run_dir: Path) -> None:
    frames_path = run_dir / "score" / "frames.json"
    if frames_path.exists():
        frames = json.loads(frames_path.read_text(encoding="utf-8"))
        assert frames.get("pr_cells_emitted") is False
        assert not frames.get("cells")
    assert not (run_dir / "score" / "report.html").exists()


@pytest.mark.parametrize("stack_id", STACKS)
@pytest.mark.parametrize(("field", "value"), INVALID_BUNDLES)
def test_score_refuses_invalid_bundle_before_metric_emission(
    lineage_run: Path, stack_id: str, field: str, value: object
) -> None:
    path = _preflight_path(lineage_run, stack_id)
    doc = json.loads(path.read_text(encoding="utf-8"))
    cache = doc["health_detailed_excerpt"]["model_cache"]
    if value is None:
        del cache[field]
    else:
        cache[field] = value
    # The existing producer validator is the oracle, not a new test-only rule.
    with pytest.raises(PreflightError) as producer:
        _parse_model_bundle_provenance(doc["health_detailed_excerpt"])
    assert producer.value.code == "model_bundle_unreported"
    path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(BenchError) as consumer:
        score_head_to_head(lineage_run)
    assert consumer.value.code in {"preflight_invalid", "model_bundle_unreported"}
    _assert_no_metrics(lineage_run)


def test_score_accepts_distinct_valid_bundles(lineage_run: Path) -> None:
    # Runtime fingerprints are equal; model names, counts and digests differ.
    for field in ("model_name", "bundle_files", "bundle_sha256"):
        assert BUNDLES[A_STACK][field] != BUNDLES[B_STACK][field]
    score_head_to_head(lineage_run)
    frames = json.loads((lineage_run / "score" / "frames.json").read_text())
    assert frames["pr_cells_emitted"] is True
    cells = [cell for cell in frames["cells"] if cell.get("value") is not None]
    assert cells
    for metric in ("detection_recall", "detection_precision"):
        selected = [
            cell for cell in cells
            if cell["cell"] == f"{metric}@frame_e2e/label_map_primary"
        ]
        assert len(selected) == 2
        assert {cell["value"] for cell in selected} == {1.0}


@pytest.mark.parametrize("stack_id", STACKS)
@pytest.mark.parametrize("drift", ["profile", "runtime"])
def test_score_still_refuses_unrelated_provenance_drift(
    lineage_run: Path, stack_id: str, drift: str
) -> None:
    path = _preflight_path(lineage_run, stack_id)
    doc = json.loads(path.read_text(encoding="utf-8"))
    cache = doc["health_detailed_excerpt"]["model_cache"]
    if drift == "profile":
        cache["profile"] = "wrong-profile"
    else:
        prefix, encoded = cache["detail"].split("numeric_runtime_fingerprint=", 1)
        fingerprint = json.loads(encoded)
        fingerprint["numpy_version"] = "different-version"
        cache["detail"] = prefix + "numeric_runtime_fingerprint=" + json.dumps(fingerprint)
    _parse_model_bundle_provenance(doc["health_detailed_excerpt"])
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        score_head_to_head(lineage_run)
    assert exc.value.code == "preflight_invalid"
    _assert_no_metrics(lineage_run)
