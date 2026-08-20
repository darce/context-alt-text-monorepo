"""FIR-12 end-to-end CPU runner composition — EVAL-16/18/19, MLDATA-07/09, rg-015.

TEST-15: each assertion is proven live against a /tmp mutant of fir_bakeoff_run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness.fir_bakeoff_run import (
    GALLERY_STRATUM,
    PROBE_STRATA,
    FirBakeoffRunError,
    _identities,
    build_run_plan,
    score_run,
)
from scripts.eval_harness.open_set_identification import SearchResult
from scripts.eval_harness.strata_join import StratumJoinError, _entry_identities, load_stratum_index

_EMPTY_CELLS = ["mask_sufficient_n", "veil", "goggles", "hair_occl"]
_DECLARED_IMAGES = {
    "A_true_occluder": 32,
    "B_eyewear": 80,
    "C_pose": 34,
    "D_capture": 87,
    "E_clean": 407,
}


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "manifests" / "fir12-selection-v1.json"
        if candidate.is_file():
            return parent
    raise RuntimeError("cannot locate repo root from test path")


def _frozen_manifest() -> Path:
    return _repo_root() / "benchmarks" / "manifests" / "fir12-selection-v1.json"


def _entry(
    media_id: int,
    stratum: str,
    identities: list[str],
    sha_char: str,
) -> dict[str, Any]:
    return {
        "sha256": sha_char * 64,
        "media_id": media_id,
        "stratum": stratum,
        "present_identities": identities,
    }


def _write_manifest(
    tmp_path: Path,
    entries: list[dict[str, Any]],
    *,
    strata_counts: dict[str, Any],
    declared_empty_cells: list[str] | None = None,
) -> Path:
    payload = {
        "schema": "bakeoff-selection/1",
        "entries": entries,
        "strata_counts": strata_counts,
        "declared_empty_cells": list(
            _EMPTY_CELLS if declared_empty_cells is None else declared_empty_cells
        ),
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _counts(**images: int) -> dict[str, Any]:
    return {name: {"images": n, "unique_subjects_faces_gt0": 0} for name, n in images.items()}


def _base_entries() -> list[dict[str, Any]]:
    return [
        _entry(1, "E_clean", ["Alice"], "a"),
        _entry(2, "E_clean", ["Alice"], "b"),
        _entry(3, "E_clean", ["Bob"], "c"),
        _entry(4, "E_clean", ["Bob"], "d"),
        _entry(5, "E_clean", ["Dale", "Eve"], "i"),
        _entry(10, "A_true_occluder", ["Alice"], "e"),
        _entry(11, "B_eyewear", ["Bob"], "f"),
        _entry(12, "C_pose", ["Alice"], "g"),
        _entry(13, "D_capture", ["Carol"], "h"),
    ]


def _base_counts(*, a_images: int = 1) -> dict[str, Any]:
    return _counts(
        A_true_occluder=a_images,
        B_eyewear=1,
        C_pose=1,
        D_capture=1,
        E_clean=5,
    )


def _plan(tmp_path: Path, *, a_images: int = 1, seed: int = 7):
    path = _write_manifest(tmp_path, _base_entries(), strata_counts=_base_counts(a_images=a_images))
    return build_run_plan(selection_manifest_path=path, seed=seed)


def _hit(name: str, score: float) -> SearchResult:
    return SearchResult(detected=True, top1_score=score, top1_name=name, true_name=name)


def _undetected_mated(name: str) -> SearchResult:
    return SearchResult(detected=False, top1_score=None, top1_name=None, true_name=name)


def _nonmated_hit(predicted: str, score: float) -> SearchResult:
    return SearchResult(detected=True, top1_score=score, top1_name=predicted, true_name=None)


def _n_enrolled(plan) -> int:
    return len(plan.split.g1) + len(plan.split.g2)


def _probe_searches(**cells: dict[str, list]) -> dict[str, dict[str, list]]:
    payload: dict[str, dict[str, list]] = {
        name: {"mated": [], "nonmated": []} for name in PROBE_STRATA
    }
    payload.update(cells)
    return payload


def test_keyword_only_public_entrypoints(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _base_entries(), strata_counts=_base_counts())
    with pytest.raises(TypeError):
        build_run_plan(path, 0)  # type: ignore[misc]
    plan = build_run_plan(selection_manifest_path=path, seed=0)
    with pytest.raises(TypeError):
        score_run(plan, {}, 0.5, 2)  # type: ignore[misc]


def test_seed_is_recorded_and_reproducible(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _base_entries(), strata_counts=_base_counts())
    a = build_run_plan(selection_manifest_path=path, seed=11)
    b = build_run_plan(selection_manifest_path=path, seed=11)
    c = build_run_plan(selection_manifest_path=path, seed=12)
    assert a.seed == 11
    assert a.split == b.split
    assert a.probe_entries == b.probe_entries
    assert a.split != c.split or a.split.g1_template_ids != c.split.g1_template_ids


def test_gallery_templates_come_from_e_clean_only(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    enrolled_ids = set(plan.split.g1) | set(plan.split.g2)
    assert enrolled_ids == {"Alice", "Bob", "Dale", "Eve"}
    probe_media = {
        entry.media_id
        for stratum in PROBE_STRATA
        for entry in plan.probe_entries[stratum]
    }
    assert probe_media == {10, 11, 12, 13}
    assert all(entry.stratum in PROBE_STRATA for stratum in PROBE_STRATA for entry in plan.probe_entries[stratum])
    assert GALLERY_STRATUM not in plan.probe_entries or plan.probe_entries.get(GALLERY_STRATUM, ()) == ()
    assert all(entry.stratum == GALLERY_STRATUM for entry in plan.gallery_entries)
    assert {entry.media_id for entry in plan.gallery_entries} == {1, 2, 3, 4, 5}


def test_group_photo_subjects_are_not_dropped(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assigned = set(plan.split.g1) | set(plan.split.g2)
    assert "Dale" in assigned
    assert "Eve" in assigned


def test_empty_e_clean_roster_raises(tmp_path: Path) -> None:
    entries = [
        _entry(10, "A_true_occluder", ["Alice"], "e"),
        _entry(11, "B_eyewear", ["Bob"], "f"),
        _entry(12, "C_pose", ["Alice"], "g"),
        _entry(13, "D_capture", ["Carol"], "h"),
    ]
    path = _write_manifest(
        tmp_path,
        entries,
        strata_counts=_counts(
            A_true_occluder=1, B_eyewear=1, C_pose=1, D_capture=1, E_clean=0
        ),
    )
    with pytest.raises(FirBakeoffRunError, match="empty gallery"):
        build_run_plan(selection_manifest_path=path, seed=0)


def test_zero_mated_stratum_renders_unmeasured_fnir_and_keeps_fpi(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    foils = [
        _nonmated_hit("Alice", 0.90),
        _nonmated_hit("Bob", 0.20),
    ]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": [], "nonmated": foils},
        ),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
        overall_nonmated=foils,
    )
    point = report.points["A_true_occluder"]
    assert point.measured is False
    assert point.fnir is None
    assert point.fpi == 1
    assert point.n_nonmated == 2
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    assert row["fnir"] == "not measured"
    assert row["fnir"] != 0
    assert row["fnir"] != 0.0
    assert row["fpi"] == 1
    assert type(row["fpi"]) is int
    assert row["measured"] is False
    assert row["n_mated"] == 0
    assert row["n_nonmated"] == 2
    assert row["declared_empty"] is False


def test_declared_empty_cells_stay_in_the_table(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
    )
    rows = {item["stratum"]: item for item in report.to_rows()}
    for cell in _EMPTY_CELLS:
        assert cell in rows
        assert rows[cell]["declared_empty"] is True
        assert rows[cell]["fnir"] == "not measured"
        assert rows[cell]["measured"] is False
        assert rows[cell]["n_images"] == 0
        assert rows[cell]["unique_subjects"] == 0
        assert rows[cell]["manifest_images"] == 0
        assert type(rows[cell]["fpi"]) is int


def test_unique_subjects_on_every_row(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
    )
    for row in report.to_rows():
        assert "unique_subjects" in row
        assert isinstance(row["unique_subjects"], int)
    rows = {item["stratum"]: item for item in report.to_rows()}
    assert rows["E_clean"]["unique_subjects"] == 4
    assert rows["A_true_occluder"]["unique_subjects"] == 1
    assert rows["D_capture"]["unique_subjects"] == 1


def test_partial_stratum_run_reports_coverage_gaps(tmp_path: Path) -> None:
    plan = _plan(tmp_path, a_images=4)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
    )
    rows = {item["stratum"]: item for item in report.to_rows()}
    assert rows["A_true_occluder"]["n_images"] == 1
    assert rows["A_true_occluder"]["manifest_images"] == 4
    assert rows["A_true_occluder"]["incomplete"] is True
    assert rows["A_true_occluder"]["manifest_images"] != rows["A_true_occluder"]["n_images"]
    gaps = report.coverage_gaps()
    assert gaps == report.stratum_report.coverage_gaps()
    by_stratum = {gap["stratum"]: gap for gap in gaps}
    assert by_stratum["A_true_occluder"] == {
        "stratum": "A_true_occluder",
        "joined_images": 1,
        "declared_images": 4,
    }
    assert gaps


def test_manifest_images_passed_through_not_recomputed(tmp_path: Path) -> None:
    plan = _plan(tmp_path, a_images=4)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
    )
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    bucket = report.stratum_report.buckets["A_true_occluder"]
    assert row["manifest_images"] == bucket.manifest_images == 4
    assert row["n_images"] == 1


def test_mated_entry_with_true_name_none_raises(tmp_path: Path) -> None:
    """Upstream ``_is_fnir_miss`` already rejects this; composition must not swallow it."""
    plan = _plan(tmp_path)
    misfiled = SearchResult(
        detected=True, top1_score=0.90, top1_name="Alice", true_name=None
    )
    with pytest.raises(ValueError, match="mated SearchResult requires true_name"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [misfiled], "nonmated": []},
            ),
            tau=0.50,
            n_enrolled_gallery_subjects=_n_enrolled(plan),
        )


def test_undetected_mated_probe_counts_as_fnir_miss(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_hit("Alice", 0.90), _undetected_mated("Bob")],
                "nonmated": [],
            },
        ),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
    )
    point = report.points["A_true_occluder"]
    assert point.measured is True
    assert point.fnir == pytest.approx(0.5)
    assert point.n_fnir_misses == 1
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    assert row["fnir"] == "0.500"
    assert row["measured"] is True


def test_fpi_is_integer_count_not_rate_over_nonmated(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    enrolled = _n_enrolled(plan)
    baseline_foils = [
        _nonmated_hit("Alice", 0.85),
        _nonmated_hit("Alice", 0.10),
    ]
    flooded_foils = [
        _nonmated_hit("Alice", 0.85),
        _nonmated_hit("Alice", 0.10),
        _nonmated_hit("Alice", 0.05),
        _nonmated_hit("Bob", 0.00),
        SearchResult(
            detected=False, top1_score=None, top1_name=None, true_name=None
        ),
    ]
    baseline = score_run(
        plan=plan,
        searches=_probe_searches(
            B_eyewear={
                "mated": [_hit("Bob", 0.90)],
                "nonmated": baseline_foils,
            },
        ),
        tau=0.50,
        n_enrolled_gallery_subjects=enrolled,
        overall_nonmated=baseline_foils,
    )
    flooded = score_run(
        plan=plan,
        searches=_probe_searches(
            B_eyewear={
                "mated": [_hit("Bob", 0.90)],
                "nonmated": flooded_foils,
            },
        ),
        tau=0.50,
        n_enrolled_gallery_subjects=enrolled,
        overall_nonmated=flooded_foils,
    )
    b_row = {item["stratum"]: item for item in baseline.to_rows()}["B_eyewear"]
    f_row = {item["stratum"]: item for item in flooded.to_rows()}["B_eyewear"]
    assert b_row["fpi"] == 1
    assert f_row["fpi"] == 1
    assert type(f_row["fpi"]) is int
    assert f_row["n_nonmated"] == 5
    assert f_row["fpi"] != pytest.approx(1 / 5)
    assert baseline.points["B_eyewear"].fpi_per_enrolled_subject == pytest.approx(
        1 / enrolled
    )
    assert flooded.points["B_eyewear"].fpi_per_enrolled_subject == pytest.approx(
        1 / enrolled
    )


def test_overall_point_pools_injected_searches(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    foils = [_nonmated_hit("Bob", 0.80)]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_hit("Alice", 0.90)],
                "nonmated": foils,
            },
            C_pose={
                "mated": [_undetected_mated("Alice")],
                "nonmated": [],
            },
        ),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
        overall_nonmated=foils,
    )
    assert report.overall.n_mated == 2
    assert report.overall.n_nonmated == 1
    assert report.overall.fnir == pytest.approx(0.5)
    assert report.overall.fpi == 1
    assert report.overall.measured is True
    assert report.seed == plan.seed


def test_frozen_manifest_plan_counts() -> None:
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    assert plan.seed == 0
    assert len(plan.split.g1) + len(plan.split.g2) == 109
    assert "Tidal Quarry" in set(plan.split.g1) | set(plan.split.g2)
    assert "Dappled Meadow" in set(plan.split.g1) | set(plan.split.g2)
    assert len(plan.probe_entries["A_true_occluder"]) == 32
    assert len(plan.probe_entries["B_eyewear"]) == 80
    assert len(plan.probe_entries["C_pose"]) == 34
    assert len(plan.probe_entries["D_capture"]) == 87
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
        n_enrolled_gallery_subjects=_n_enrolled(plan),
    )
    rows = {item["stratum"]: item for item in report.to_rows()}
    for name, declared in _DECLARED_IMAGES.items():
        assert rows[name]["manifest_images"] == declared
    assert rows["A_true_occluder"]["n_images"] == 32
    assert rows["B_eyewear"]["n_images"] == 80
    assert rows["C_pose"]["n_images"] == 34
    assert rows["D_capture"]["n_images"] == 87
    assert rows["E_clean"]["n_images"] < rows["E_clean"]["manifest_images"]
    assert rows["E_clean"]["incomplete"] is True
    assert report.coverage_gaps()
    for cell in _EMPTY_CELLS:
        assert rows[cell]["declared_empty"] is True
        assert rows[cell]["fnir"] == "not measured"


def test_overall_nonmated_is_declared_once_not_pooled(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    foils = [
        _nonmated_hit("Alice", 0.90),
        _nonmated_hit("Bob", 0.20),
    ]
    searches = {
        name: {"mated": [], "nonmated": foils} for name in PROBE_STRATA
    }
    report = score_run(
        plan=plan,
        searches=searches,
        tau=0.50,
        overall_nonmated=foils,
    )
    for name in PROBE_STRATA:
        point = report.points[name]
        assert point.fpi == 1
        assert point.n_nonmated == 2
    assert report.overall.fpi == 1
    assert report.overall.n_nonmated == 2
    assert report.overall.fpi != 4
    assert report.overall.n_nonmated != 8


def test_omitting_overall_nonmated_with_stratum_nonmated_raises(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    foils = [
        _nonmated_hit("Alice", 0.90),
        _nonmated_hit("Bob", 0.20),
    ]
    searches = {
        name: {"mated": [], "nonmated": foils} for name in PROBE_STRATA
    }
    with pytest.raises(FirBakeoffRunError) as excinfo:
        score_run(plan=plan, searches=searches, tau=0.50)
    msg = str(excinfo.value)
    assert "open-set workload must be declared once" in msg
    for name in PROBE_STRATA:
        assert name in msg


def test_mated_searches_still_pool_across_strata(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_hit("Alice", 0.90)],
                "nonmated": [],
            },
            C_pose={
                "mated": [_undetected_mated("Alice")],
                "nonmated": [],
            },
        ),
        tau=0.50,
    )
    assert report.overall.n_mated == 2
    assert report.overall.n_nonmated == 0
    assert report.overall.fnir == pytest.approx(0.5)
    assert report.overall.measured is True


def test_missing_populated_probe_stratum_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    searches = {
        name: {"mated": [], "nonmated": []}
        for name in PROBE_STRATA
        if name != "B_eyewear"
    }
    with pytest.raises(FirBakeoffRunError) as excinfo:
        score_run(plan=plan, searches=searches, tau=0.50)
    assert "B_eyewear" in str(excinfo.value)


def test_empty_searches_raises_for_populated_probe_strata(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    with pytest.raises(FirBakeoffRunError) as excinfo:
        score_run(plan=plan, searches={}, tau=0.50)
    msg = str(excinfo.value)
    for name in PROBE_STRATA:
        assert name in msg


def test_explicit_empty_mated_list_is_unmeasured_not_missing(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    foils = [_nonmated_hit("Alice", 0.90)]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            B_eyewear={"mated": [], "nonmated": foils},
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    point = report.points["B_eyewear"]
    assert point.measured is False
    assert point.fnir is None
    assert point.n_mated == 0
    assert point.fpi == 1
    row = {item["stratum"]: item for item in report.to_rows()}["B_eyewear"]
    assert row["fnir"] == "not measured"
    assert row["measured"] is False
    assert row["declared_empty"] is False


def test_enrolled_gallery_mismatch_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    expected = _n_enrolled(plan)
    assert expected != 1
    with pytest.raises(FirBakeoffRunError) as excinfo:
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=0.50,
            n_enrolled_gallery_subjects=1,
        )
    msg = str(excinfo.value)
    assert "1" in msg
    assert str(expected) in msg


def test_enrolled_gallery_defaults_to_split_size(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    expected = _n_enrolled(plan)
    foils = [_nonmated_hit("Bob", 0.80)]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_hit("Alice", 0.90)],
                "nonmated": foils,
            },
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    assert report.overall.n_enrolled_gallery_subjects == expected
    assert report.overall.fpi_per_enrolled_subject == pytest.approx(1 / expected)


def test_non_finite_tau_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    with pytest.raises(FirBakeoffRunError, match="tau"):
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=float("nan"),
        )


def test_to_rows_carries_tau_and_enrolled_normalization(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    expected = _n_enrolled(plan)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
    )
    assert report.to_rows()
    for row in report.to_rows():
        assert row["tau"] == 0.50
        assert "fpi_per_enrolled_subject" in row
        assert row["n_enrolled_gallery_subjects"] == expected

def _still_media(templates) -> set[int]:
    """Include `{media}:{subject}` prefixes so stripped media_ids cannot hide a leak."""
    media: set[int] = set()
    for template in templates:
        media.update(template.media_ids)
        prefix, sep, _rest = template.template_id.partition(":")
        if sep and prefix.isdigit():
            media.add(int(prefix))
    return media


def test_frozen_manifest_galleries_media_disjoint_across_seeds() -> None:
    path = _frozen_manifest()
    for seed in range(64):
        plan = build_run_plan(selection_manifest_path=path, seed=seed)
        g1_media = _still_media(plan.split.g1.values())
        g2_media = _still_media(plan.split.g2.values())
        probe_media = _still_media(plan.split.probe_templates)
        assert g1_media & g2_media == set(), seed
        assert (g1_media | g2_media) & probe_media == set(), seed
        assert (g1_media | g2_media) & set(plan.split.probe_media_ids) == set(), seed


def test_frozen_manifest_withholds_shared_probe_stills_at_seed_0() -> None:
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    assigned = set(plan.split.g1) | set(plan.split.g2)
    assert "Tidal Quarry" in assigned
    assert "Dappled Meadow" in assigned
    withheld = plan.split.withheld_probe_templates
    assert withheld
    withheld_ids = {t.template_id for t in withheld}
    assert withheld_ids.isdisjoint(plan.split.probe_template_ids)
    assert withheld_ids.isdisjoint(plan.split.g1_template_ids)
    assert withheld_ids.isdisjoint(plan.split.g2_template_ids)


def test_present_identities_rejects_str_and_dict() -> None:
    with pytest.raises(FirBakeoffRunError, match="present_identities"):
        _identities({"present_identities": "Alice"})
    with pytest.raises(FirBakeoffRunError, match="present_identities"):
        _identities({"present_identities": {"Alice": 1}})
    with pytest.raises(StratumJoinError, match="present_identities"):
        _entry_identities({"present_identities": "Alice"}, where="entries[0]")
    with pytest.raises(StratumJoinError, match="present_identities"):
        _entry_identities({"present_identities": {"Alice": 1}}, where="entries[0]")


def test_present_identities_list_and_absent_are_legal(tmp_path: Path) -> None:
    assert _identities({}) == ()
    assert _identities({"present_identities": []}) == ()
    assert _identities({"present_identities": ["Alice"]}) == ("Alice",)
    assert _identities({"present_identities": ("Alice",)}) == ("Alice",)
    assert _entry_identities({}, where="entries[0]") is None
    assert _entry_identities({"present_identities": []}, where="entries[0]") == ()
    assert _entry_identities({"present_identities": ["Alice"]}, where="entries[0]") == (
        "Alice",
    )
    entries = [
        _entry(1, "E_clean", ["Alice"], "a"),
        _entry(2, "E_clean", ["Alice"], "b"),
        _entry(3, "E_clean", ["Bob"], "c"),
        _entry(4, "E_clean", ["Bob"], "d"),
        {"sha256": "z" * 64, "media_id": 9, "stratum": "E_clean"},
        _entry(10, "A_true_occluder", ["Alice"], "e"),
        _entry(11, "B_eyewear", ["Bob"], "f"),
        _entry(12, "C_pose", ["Alice"], "g"),
        _entry(13, "D_capture", ["Carol"], "h"),
    ]
    path = _write_manifest(
        tmp_path,
        entries,
        strata_counts=_counts(
            A_true_occluder=1, B_eyewear=1, C_pose=1, D_capture=1, E_clean=5
        ),
    )
    index = load_stratum_index(path)
    assert index.subjects_by_media_id[1] == ("Alice",)
    assert 9 not in index.subjects_by_media_id
    plan = build_run_plan(selection_manifest_path=path, seed=0)
    assigned = set(plan.split.g1) | set(plan.split.g2)
    assert assigned == {"Alice", "Bob"}
