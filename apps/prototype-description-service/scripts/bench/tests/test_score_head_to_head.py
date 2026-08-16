"""score_head_to_head statistical wiring — must go red if CIs/Holm/populations are faked."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.bench.driver import init_run_dir
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import golden_entry, valid_pair_dict, write_pair, write_stub_preflight

PRIMARY = "detection_recall@frame_e2e/label_map_primary"
SECONDARY_PREC = "detection_precision@frame_e2e/label_map_primary"
NATIVE_ID = "identification_recall@frame_fir5_native/label_map_primary"
A_STACK = "acx-dev-insightface"
B_STACK = "acx-dev-fir"


def _box(name: str = "Alice Q") -> dict:
    return {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": name, "source": "iptc"}


def _pred(media_id: int, *, label: str = "Alice Q", miss: bool = False) -> dict:
    box = {"x": 0, "y": 0, "width": 10, "height": 10} if miss else {"x": 400, "y": 400, "width": 200, "height": 200}
    return {
        "identity_id": f"id-{media_id}",
        "media_id": media_id,
        "cluster_id": "c1",
        "cluster_label": label,
        "is_auto_label": False,
        "bbox": box,
    }


def _write_manifest(
    path: Path,
    entries: list[dict],
    roster: list[str] | None = None,
    *,
    annotation_mode: str = "exhaustive",
) -> Path:
    body = {
        "manifest_version": 3,
        "annotation_mode": annotation_mode,
        "roster": roster or ["Alice Q"],
        "entries": entries,
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _write_leg(run_dir: Path, stack_id: str, identities: list[dict], media_ids: list[int]) -> None:
    leg = run_dir / "legs" / stack_id
    (leg / "exports").mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for mid in media_ids:
        rec = {
            "manifest_media_id": mid,
            "manifest_path": f"fixtures/m{mid}.jpg",
            "content_sha256": f"{mid:064x}",
            "stack_media_id": mid,
            "image_width": 1000,
            "image_height": 1000,
            "phase": "analyze",
            "outcome": "ok",
            "attempt": 1,
            "terminal_ingest_outcome": "success",
        }
        lines.append(json.dumps(rec))
        lines.append(json.dumps({**rec, "phase": "ingest"}))
    (leg / "items.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (leg / "exports" / "media_identities.json").write_text(json.dumps(identities), encoding="utf-8")
    (leg / "exports" / "clusters.json").write_text(
        json.dumps([{"id": "c1", "label": "Alice Q", "is_auto_label": False}]),
        encoding="utf-8",
    )
    (leg / "exports" / "cluster_members.json").write_text(
        json.dumps([{"cluster_id": "c1", "members": [{"media_id": r["media_id"]} for r in identities]}]),
        encoding="utf-8",
    )
    write_stub_preflight(run_dir, stack_id)


def _init(
    tmp_path: Path,
    media_ids: list[int],
    entries: list[dict],
    *,
    floor: float = 0.5,
    annotation_mode: str = "exhaustive",
) -> Path:
    manifest = _write_manifest(
        tmp_path / "manifest.json", entries, annotation_mode=annotation_mode
    )
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(accepted_set_floor=floor)))
    run_dir = tmp_path / "run"
    init_run_dir(run_dir, pair, manifest)
    return run_dir


def _cells(run_dir: Path, name: str) -> list[dict]:
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    return [c for c in frames["cells"] if c.get("cell") == name]


def test_score_requires_preflight_json(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    for stack_id in (A_STACK, B_STACK):
        (run_dir / "legs" / stack_id / "preflight.json").unlink()
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "preflight_missing"
    else:
        raise AssertionError("score must refuse a run-dir without preflight.json")


def test_unnamed_cell_has_null_ci_not_fabricated_zero(tmp_path: Path) -> None:
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    score_head_to_head(run_dir)
    native = _cells(run_dir, NATIVE_ID)
    assert native
    for cell in native:
        assert cell["ci_half_width"] is None
        assert cell["ci_lower"] is None
        assert cell["p_value"] is None
        assert cell.get("bootstrap_resamples") is None


def test_primary_fully_discordant_ci_is_zero_width(tmp_path: Path) -> None:
    mids = [1, 2, 3, 4, 5, 6]
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in mids
    ]
    run_dir = _init(tmp_path, mids, entries)
    a_ids = [_pred(i) for i in mids]
    b_ids = [_pred(i, miss=True) for i in mids]
    _write_leg(run_dir, A_STACK, a_ids, mids)
    _write_leg(run_dir, B_STACK, b_ids, mids)
    score_head_to_head(run_dir)
    primary = _cells(run_dir, PRIMARY)
    assert primary
    for cell in primary:
        assert cell["ci_half_width"] is not None
        assert cell["ci_half_width"] == 0.0  # Δ is 1.0 on every resample
        assert cell["p_value"] is not None
        assert cell["p_value"] < 0.01
    by_stack = {c["stack_id"]: c for c in primary}
    assert by_stack[A_STACK]["value"] == 1.0
    assert by_stack[B_STACK]["value"] == 0.0


def test_secondary_holm_uses_real_bootstrap_p(tmp_path: Path) -> None:
    mids = [1, 2, 3, 4, 5, 6]
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in mids
    ]
    run_dir = _init(tmp_path, mids, entries)
    _write_leg(run_dir, A_STACK, [_pred(i) for i in mids], mids)
    _write_leg(run_dir, B_STACK, [_pred(i, miss=True) for i in mids], mids)
    score_head_to_head(run_dir)
    prec = _cells(run_dir, SECONDARY_PREC)
    assert prec
    for cell in prec:
        assert cell.get("p_value") is not None
        assert cell["p_value"] < 0.01
        assert cell["holm_significant"] is True
        assert cell["holm_p_value"] == cell["p_value"]
        assert cell["holm_threshold"] is not None
        assert cell["p_value"] <= cell["holm_threshold"]
        assert "holm_rank" in cell
        assert cell.get("holm_status") != "not_computed"
        assert cell["tier"] == "CONFIRMATORY"


def test_detection_excludes_boxless_from_precision(tmp_path: Path) -> None:
    """Box-less accepted entry with a pred must not add an FP to detection precision."""
    boxed = golden_entry(1, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()])
    boxless = golden_entry(2, face_count=0, present_identities=[], face_boxes=[])
    run_dir = _init(tmp_path, [1, 2], [boxed, boxless])
    identities = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, identities, [1, 2])
    _write_leg(run_dir, B_STACK, identities, [1, 2])
    score_head_to_head(run_dir)
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    assert frames["detection_scoring_set_size"] == 1
    prec = _cells(run_dir, SECONDARY_PREC)
    assert prec
    for cell in prec:
        assert cell["false_positives"] == 0
        assert cell["true_positives"] == 1
        assert cell["precision"] == 1.0


def test_discordant_pair_widens_ci_through_score_path(tmp_path: Path) -> None:
    mids = [1, 2, 3, 4, 5, 6]
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in mids
    ]
    run_dir = _init(tmp_path, mids, entries)
    a_ids = [_pred(i) for i in (1, 2, 3)] + [_pred(i, miss=True) for i in (4, 5, 6)]
    b_ids = [_pred(i, miss=True) for i in (1, 2, 3)] + [_pred(i) for i in (4, 5, 6)]
    _write_leg(run_dir, A_STACK, a_ids, mids)
    _write_leg(run_dir, B_STACK, b_ids, mids)
    score_head_to_head(run_dir)
    primary = _cells(run_dir, PRIMARY)
    assert primary
    for cell in primary:
        assert cell["ci_half_width"] is not None
        assert cell["ci_half_width"] > 0.05
        assert cell["tier"] == "DIRECTIONAL"
        assert cell["reason"] == "ci_half_width_above_precision_floor"


def test_identical_legs_primary_half_width_zero_when_populated(tmp_path: Path) -> None:
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    score_head_to_head(run_dir)
    primary = _cells(run_dir, PRIMARY)
    assert primary
    for cell in primary:
        assert cell["ci_half_width"] == 0.0
        assert cell["ci_lower"] == 0.0
        assert cell["ci_upper"] == 0.0
        assert cell["p_value"] == 1.0


def test_score_path_passes_holm_family_size(tmp_path: Path, monkeypatch) -> None:
    from scripts.bench import score_report as score_mod

    seen: dict[str, object] = {}
    orig = score_mod.holm_bonferroni

    def spy(pairs, alpha=0.05, *, family_size=None):
        seen["n_pairs"] = len(pairs)
        seen["family_size"] = family_size
        return orig(pairs, alpha, family_size=family_size)

    monkeypatch.setattr(score_mod, "holm_bonferroni", spy)
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    score_head_to_head(run_dir)
    assert seen["family_size"] == 3
    assert seen["n_pairs"] == 3


def test_mixed_recognition_enabled_shortens_identification_series(tmp_path: Path, monkeypatch) -> None:
    from scripts.bench import score_report as score_mod

    pairs: list[tuple[str | None, int]] = []
    orig = score_mod.bootstrap_paired_delta

    def spy(a, b, *args, **kwargs):
        pairs.append((kwargs.get("cell"), len(a)))
        return orig(a, b, *args, **kwargs)

    monkeypatch.setattr(score_mod, "bootstrap_paired_delta", spy)
    mids = [1, 2, 3, 4, 5, 6]
    entries = []
    for i in mids:
        entry = golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()])
        if i == 6:
            entry["policy"] = {"recognition_enabled": False}
        entries.append(entry)
    run_dir = _init(tmp_path, mids, entries)
    ids = [_pred(i) for i in mids]
    _write_leg(run_dir, A_STACK, ids, mids)
    _write_leg(run_dir, B_STACK, ids, mids)
    score_head_to_head(run_dir)
    by_cell = {name: length for name, length in pairs}
    assert by_cell[PRIMARY] == 6
    assert by_cell[SECONDARY_PREC] == 6
    assert by_cell["identification_recall@frame_e2e/label_map_primary"] == 5
    assert by_cell["identification_precision@frame_e2e/label_map_primary"] == 5
    det = _cells(run_dir, PRIMARY)
    assert det
    for cell in det:
        assert cell["true_positives"] + cell["false_negatives"] == 6
        assert cell.get("bootstrap_status") not in {None, "bootstrap_series_mismatch"}


def test_holm_family_uses_declared_secondary_size(tmp_path: Path) -> None:
    """Detection-only corpus must Holm-correct at m=|declared|, not m=1."""
    mids = [1, 2, 3, 4, 5, 6]
    entries = []
    for i in mids:
        entry = golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()])
        entry["policy"] = {"recognition_enabled": False}
        entries.append(entry)
    run_dir = _init(tmp_path, mids, entries)
    _write_leg(run_dir, A_STACK, [_pred(i) for i in mids], mids)
    _write_leg(run_dir, B_STACK, [_pred(i, miss=True) for i in mids], mids)
    score_head_to_head(run_dir)
    prec = _cells(run_dir, SECONDARY_PREC)
    assert prec
    for cell in prec:
        assert cell["holm_threshold"] == 0.05 / 3
        assert cell.get("holm_status") != "not_computed"
    id_cells = _cells(run_dir, "identification_recall@frame_e2e/label_map_primary")
    assert id_cells
    for cell in id_cells:
        assert cell.get("holm_status") == "not_computed"
        assert cell.get("holm_p_value") == 1.0
        assert cell.get("holm_significant") is False
        assert cell.get("tier") != "CONFIRMATORY"


def test_primary_score_path_emits_confirmatory(tmp_path: Path) -> None:
    mids = [1, 2, 3, 4, 5, 6]
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in mids
    ]
    run_dir = _init(tmp_path, mids, entries)
    _write_leg(run_dir, A_STACK, [_pred(i) for i in mids], mids)
    _write_leg(run_dir, B_STACK, [_pred(i, miss=True) for i in mids], mids)
    score_head_to_head(run_dir)
    primary = _cells(run_dir, PRIMARY)
    assert primary
    for cell in primary:
        assert cell["tier"] == "CONFIRMATORY"
        assert cell["ci_half_width"] == 0.0
        assert cell.get("bootstrap_status") == "ok"


def test_holm_p_couples_to_cell_with_distinct_magnitudes(tmp_path: Path) -> None:
    """Distinct per-secondary p so a family permutation cannot preserve coupling."""
    mids = [1, 2, 3, 4, 5, 6]
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in mids
    ]
    run_dir = _init(tmp_path, mids, entries)
    a_ids = [_pred(i) for i in mids]
    b_ids: list[dict] = []
    for i in mids:
        labeled = i == 6
        b_ids.append(
            {
                **_pred(i, label="Alice Q" if labeled else ""),
                "is_auto_label": not labeled,
            }
        )
        if i <= 3:
            b_ids.append(
                {
                    **_pred(i, label="", miss=True),
                    "identity_id": f"extra-{i}",
                    "is_auto_label": True,
                }
            )
        if i == 1:
            b_ids.append(
                {
                    **_pred(i, label="Bob Z", miss=True),
                    "identity_id": f"bob-{i}",
                    "is_auto_label": False,
                }
            )
    _write_leg(run_dir, A_STACK, a_ids, mids)
    _write_leg(run_dir, B_STACK, b_ids, mids)
    score_head_to_head(run_dir)
    secondaries = [
        "detection_precision@frame_e2e/label_map_primary",
        "identification_recall@frame_e2e/label_map_primary",
        "identification_precision@frame_e2e/label_map_primary",
    ]
    by_name: dict[str, dict] = {}
    for name in secondaries:
        cells = _cells(run_dir, name)
        assert cells
        cell = cells[0]
        assert cell["holm_p_value"] == cell["p_value"]
        by_name[name] = cell
    p_values = [by_name[n]["p_value"] for n in secondaries]
    assert len(set(p_values)) == 3
    ranked = sorted(secondaries, key=lambda n: (by_name[n]["p_value"], n))
    for rank, name in enumerate(ranked, start=1):
        assert by_name[name]["holm_rank"] == rank


def test_join_hole_raises_instead_of_zero_pad(tmp_path: Path, monkeypatch) -> None:
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    from scripts.bench.export_map import to_face_metric_inputs
    from scripts.bench.stack_pair import BenchError

    orig = to_face_metric_inputs

    def drop_first(*args, **kwargs):
        det, ident = orig(*args, **kwargs)
        return det[1:], ident[1:]

    monkeypatch.setattr("scripts.bench.score_report.to_face_metric_inputs", drop_first)
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "join_row_missing"
    else:
        raise AssertionError("missing metric row must fail closed")


def test_partial_bootstrap_score_path_demotes_would_be_confirmatory(tmp_path: Path) -> None:
    """Real partial bootstrap on a Holm-significant secondary (FIR-8 R4-01, R4-04).

    3 exhaustive hit/miss images plus 1 zero-pred image. Detection precision
    is Holm-significant with ci_half_width=0. The cell would be CONFIRMATORY
    if the !=ok demotion in assign_tier were removed, or if score_head_to_head
    dropped the ctx bootstrap_status stamp. The missing-key fail-open-default
    seam is pinned by test_assign_tier_missing_bootstrap_status_is_fail_closed,
    not this integration test.
    """
    from scripts.bench.score_report import BOOTSTRAP_RESAMPLES

    mids = [1, 2, 3, 4]
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in mids
    ]
    run_dir = _init(tmp_path, mids, entries)
    _write_leg(run_dir, A_STACK, [_pred(i) for i in (1, 2, 3)], mids)
    _write_leg(run_dir, B_STACK, [_pred(i, miss=True) for i in (1, 2, 3)], mids)
    score_head_to_head(run_dir)
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    assert frames["preflight_present"] is True
    prec = _cells(run_dir, SECONDARY_PREC)
    assert prec
    for cell in prec:
        assert cell["holm_significant"] is True
        assert cell["bootstrap_status"] == "partial"
        assert cell["bootstrap_n_used"] < BOOTSTRAP_RESAMPLES
        assert cell["bootstrap_n_used"] > 0
        assert cell["tier"] == "DIRECTIONAL"
        assert cell["reason"] == "bootstrap_status"
        assert "ci_lower" in cell and cell["ci_lower"] is None
        assert "ci_upper" in cell and cell["ci_upper"] is None
        assert "ci_half_width" in cell and cell["ci_half_width"] is None
        assert "ci_level" in cell and cell["ci_level"] is None


def test_score_refuses_invalid_preflight_json(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    (run_dir / "legs" / A_STACK / "preflight.json").write_text("{}", encoding="utf-8")
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "preflight_invalid"
    else:
        raise AssertionError("empty-object preflight.json must refuse")


def test_score_refuses_non_utf8_preflight_json(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    (run_dir / "legs" / A_STACK / "preflight.json").write_bytes(b"\xff\xfe\x00\x01\x9c")
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "preflight_invalid"
    else:
        raise AssertionError("non-UTF-8 preflight.json must refuse")


def test_score_refuses_non_object_preflight_json(tmp_path: Path) -> None:
    from scripts.bench.score_report import PROV01_PREFLIGHT_KEYS
    from scripts.bench.stack_pair import BenchError

    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    (run_dir / "legs" / B_STACK / "preflight.json").write_text("[]", encoding="utf-8")
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "preflight_invalid"
    else:
        raise AssertionError("list preflight.json must refuse")
    # A list of the 11 key names would pass key-presence (`key in list`)
    # if the isinstance(dict) guard were dropped.
    (run_dir / "legs" / B_STACK / "preflight.json").write_text(
        json.dumps(list(PROV01_PREFLIGHT_KEYS)), encoding="utf-8"
    )
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "preflight_invalid"
    else:
        raise AssertionError("key-name-list preflight.json must refuse")


def test_score_refuses_unparseable_preflight_json(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries)
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    (run_dir / "legs" / B_STACK / "preflight.json").write_text("{not-json", encoding="utf-8")
    try:
        score_head_to_head(run_dir)
    except BenchError as exc:
        assert exc.code == "preflight_invalid"
    else:
        raise AssertionError("malformed preflight.json must refuse")


def test_identification_boxless_corpus_is_directional(tmp_path: Path) -> None:
    # roster_only: face_count=1 with zero boxes is a valid coverage hole.
    # exhaustive would fail load (boxes_cover_face_count).
    entries = [golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[]) for i in (1, 2)]
    run_dir = _init(tmp_path, [1, 2], entries, annotation_mode="roster_only")
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    score_head_to_head(run_dir)
    id_recall = _cells(run_dir, "identification_recall@frame_e2e/label_map_primary")
    assert id_recall
    for cell in id_recall:
        assert cell["tier"] == "DIRECTIONAL"
        assert cell["reason"] == "detection_exhaustiveness_unasserted"


def test_roster_only_surfaces_detection_refusal_not_silent_skip(tmp_path: Path) -> None:
    """Boxed roster_only images must refuse detection P/R in frames.json.

    TEST-15: silent skip (no detection cell) or invented P/R would pass a
    weaker contract. Identification still scores.
    """
    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries, annotation_mode="roster_only")
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    score_head_to_head(run_dir)
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    detection_cells = [
        cell
        for cell in frames["cells"]
        if str(cell.get("cell", "")).startswith("detection_")
        or str(cell.get("metric", "")).startswith("detection")
    ]
    assert detection_cells, "roster_only detection must surface a refusal, not disappear"
    for cell in detection_cells:
        assert cell.get("refused") is True
        assert cell.get("invariant") == "detection_refuses_roster_only"
        assert cell.get("value") is None
        assert cell.get("precision") is None
        assert cell.get("recall") is None
        assert cell.get("true_positives") is None
    primary = _cells(run_dir, PRIMARY)
    assert primary
    for cell in primary:
        assert cell.get("refused") is True
        assert cell.get("invariant") == "detection_refuses_roster_only"
    id_recall = _cells(run_dir, "identification_recall@frame_e2e/label_map_primary")
    assert id_recall
    for cell in id_recall:
        assert cell.get("refused") is not True
        assert cell.get("true_positives") is not None


def test_roster_only_accepted_set_has_empty_detection_scoring_set(tmp_path: Path) -> None:
    """Document-level roster_only must empty detection_scoring_set.

    TEST-15: entry-level is_detection_exhaustive (face_count == len(boxes))
    would populate the set even though every detection cell is refused.
    """
    from scripts.bench.score_report import compute_accepted_set

    entries = [
        golden_entry(i, face_count=1, present_identities=["Alice Q"], face_boxes=[_box()]) for i in (1, 2)
    ]
    run_dir = _init(tmp_path, [1, 2], entries, annotation_mode="roster_only")
    ids = [_pred(1), _pred(2)]
    _write_leg(run_dir, A_STACK, ids, [1, 2])
    _write_leg(run_dir, B_STACK, ids, [1, 2])
    score_head_to_head(run_dir)
    accepted = compute_accepted_set(run_dir)
    assert accepted.detection_scoring_set == []
    assert accepted.detection_scoring_set_size == 0
    frames = json.loads((run_dir / "score" / "frames.json").read_text())
    assert frames["detection_scoring_set_size"] == 0
    written = json.loads((run_dir / "score" / "accepted_set.json").read_text())
    assert written["detection_scoring_set_size"] == 0
