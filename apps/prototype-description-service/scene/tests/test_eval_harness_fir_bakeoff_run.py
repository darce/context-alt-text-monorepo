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
    RunPlan,
    _identities,
    both_gallery_probe_entries,
    both_gallery_search_count,
    build_run_plan,
    expected_mated_search_count,
    mated_galleries_for,
    mated_identities_for,
    occluded_probes_for,
    score_run,
)
from scripts.eval_harness.gallery_split import GalleryName
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


def _gallery_of(plan, subject: str) -> GalleryName:
    if subject in plan.split.g1:
        return GalleryName.G1
    if subject in plan.split.g2:
        return GalleryName.G2
    raise AssertionError(f"{subject!r} is not enrolled")


def _other_gallery(plan, subject: str) -> GalleryName:
    own = _gallery_of(plan, subject)
    return GalleryName.G2 if own is GalleryName.G1 else GalleryName.G1


def _hit(
    name: str,
    score: float,
    *,
    gallery: GalleryName | str,
    media_id: int,
) -> SearchResult:
    return SearchResult(
        detected=True,
        top1_score=score,
        top1_name=name,
        true_name=name,
        gallery=gallery,
        media_id=media_id,
    )


def _undetected_mated(
    name: str, *, gallery: GalleryName | str, media_id: int
) -> SearchResult:
    return SearchResult(
        detected=False,
        top1_score=None,
        top1_name=None,
        true_name=name,
        gallery=gallery,
        media_id=media_id,
    )


def _nonmated_hit(
    predicted: str,
    score: float,
    *,
    gallery: GalleryName | str,
    media_id: int,
) -> SearchResult:
    return SearchResult(
        detected=True,
        top1_score=score,
        top1_name=predicted,
        true_name=None,
        gallery=gallery,
        media_id=media_id,
    )


def _alice_hit(plan, score: float = 0.90, *, media_id: int = 10) -> SearchResult:
    return _hit("Alice", score, gallery=_gallery_of(plan, "Alice"), media_id=media_id)


def _alice_miss(plan, *, media_id: int = 10) -> SearchResult:
    return _undetected_mated(
        "Alice", gallery=_gallery_of(plan, "Alice"), media_id=media_id
    )


def _bob_hit(plan, score: float = 0.90, *, media_id: int = 11) -> SearchResult:
    return _hit("Bob", score, gallery=_gallery_of(plan, "Bob"), media_id=media_id)


def _alice_foil(plan, predicted: str, score: float, *, media_id: int = 10) -> SearchResult:
    return _nonmated_hit(
        predicted, score, gallery=_other_gallery(plan, "Alice"), media_id=media_id
    )


def _bob_foil(plan, predicted: str, score: float, *, media_id: int = 11) -> SearchResult:
    return _nonmated_hit(
        predicted, score, gallery=_other_gallery(plan, "Bob"), media_id=media_id
    )


def _union_enrolled(plan) -> int:
    return len(plan.split.g1) + len(plan.split.g2)


def _roster_n(plan, gallery: GalleryName) -> int:
    return len(plan.split.g1) if gallery is GalleryName.G1 else len(plan.split.g2)


def _first_foil_entry(plan, gallery: GalleryName):
    for stratum in PROBE_STRATA:
        for entry in plan.probe_entries[stratum]:
            if mated_identities_for(entry, split=plan.split, gallery=gallery):
                continue
            return entry
    raise AssertionError(f"no foil probe for {gallery}")


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


def test_gallery_stratum_renders_enrolled_not_probed() -> None:
    """BR-16 / MLDATA-09: E_clean is enrolled, not an untested probe cell."""
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
    )
    assert GALLERY_STRATUM not in report.points
    row = {item["stratum"]: item for item in report.to_rows()}[GALLERY_STRATUM]
    assert row["n_images"] == 342
    assert row["declared_empty"] is False
    assert row["measured"] is False
    assert row["fnir"] == "enrolled, not probed"
    assert row["fnir"] != "not measured"
    assert row["n_mated"] == 0
    assert row["search_shortfall"] == 0


def test_gallery_searches_are_not_pooled_into_overall_fnir(tmp_path: Path) -> None:
    """BR-16: an E_clean key must not dilute the occluded-probe headline."""
    plan = _plan(tmp_path)
    foils = [_alice_foil(plan, "Bob", 0.80)]
    searches = _probe_searches(
        A_true_occluder={
            "mated": [_alice_miss(plan)],
            "nonmated": foils,
        },
    )
    searches[GALLERY_STRATUM] = {
        "mated": [
            _alice_hit(plan),
            _bob_hit(plan),
            _hit("Dale", 0.90, gallery=_gallery_of(plan, "Dale"), media_id=5),
        ],
        "nonmated": [],
    }
    report = score_run(
        plan=plan,
        searches=searches,
        tau=0.50,
        overall_nonmated=foils,
    )
    assert GALLERY_STRATUM not in report.points
    assert report.overall.n_mated == 1
    assert report.overall.n_fnir_misses == 1
    assert report.overall.fnir == pytest.approx(1.0)
    assert report.overall.fnir != pytest.approx(0.25)
    assert report.overall.n_mated != 4
    row = {item["stratum"]: item for item in report.to_rows()}[GALLERY_STRATUM]
    assert row["fnir"] == "enrolled, not probed"


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
    for subject_id in enrolled_ids:
        template = plan.split.g1.get(subject_id) or plan.split.g2[subject_id]
        assert template.media_ids != ()


def test_group_photo_subjects_are_not_dropped(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assigned = set(plan.split.g1) | set(plan.split.g2)
    assert "Dale" in assigned
    assert "Eve" in assigned
    dale = plan.split.g1.get("Dale") or plan.split.g2["Dale"]
    eve = plan.split.g1.get("Eve") or plan.split.g2["Eve"]
    assert dale.media_ids == (5,)
    assert eve.media_ids == (5,)
    assert dale.media_ids != ()


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
        _alice_foil(plan, "Alice", 0.90),
        _alice_foil(plan, "Bob", 0.20),
    ]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": [], "nonmated": foils},
        ),
        tau=0.50,
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
    assert row["search_shortfall"] == 1
    assert row["incomplete"] is True


def test_declared_empty_cells_stay_in_the_table(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
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
        assert rows[cell]["fpi"] is None
        assert rows[cell]["n_nonmated"] == 0


def test_unique_subjects_on_every_row(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
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
    )
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    bucket = report.stratum_report.buckets["A_true_occluder"]
    assert row["manifest_images"] == bucket.manifest_images == 4
    assert row["n_images"] == 1


def test_mated_entry_with_true_name_none_raises(tmp_path: Path) -> None:
    """BR-18: a mated filing whose true_name is missing is not enrolled in the gallery."""
    plan = _plan(tmp_path)
    misfiled = SearchResult(
        detected=True,
        top1_score=0.90,
        top1_name="Alice",
        true_name=None,
        gallery=_gallery_of(plan, "Alice"),
        media_id=10,
    )
    with pytest.raises(FirBakeoffRunError, match="not enrolled"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [misfiled], "nonmated": []},
            ),
            tau=0.50,
        )


def test_undetected_mated_probe_counts_as_fnir_miss(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_alice_hit(plan), _alice_miss(plan)],
                "nonmated": [],
            },
        ),
        tau=0.50,
    )
    point = report.points["A_true_occluder"]
    assert point.measured is True
    assert point.fnir == pytest.approx(0.5)
    assert point.n_fnir_misses == 1
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    assert row["fnir"] == "0.500"
    assert row["measured"] is True
    assert row["search_shortfall"] == 0
    assert row["incomplete"] is False


def test_fpi_is_integer_count_not_rate_over_nonmated(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    foil_gallery = _other_gallery(plan, "Bob")
    enrolled = _roster_n(plan, foil_gallery)
    union = _union_enrolled(plan)
    baseline_foils = [
        _bob_foil(plan, "Alice", 0.85),
        _bob_foil(plan, "Alice", 0.10),
    ]
    flooded_foils = [
        _bob_foil(plan, "Alice", 0.85),
        _bob_foil(plan, "Alice", 0.10),
        _bob_foil(plan, "Alice", 0.05),
        _bob_foil(plan, "Bob", 0.00),
        SearchResult(
            detected=False,
            top1_score=None,
            top1_name=None,
            true_name=None,
            gallery=foil_gallery,
            media_id=11,
        ),
    ]
    baseline = score_run(
        plan=plan,
        searches=_probe_searches(
            B_eyewear={
                "mated": [],
                "nonmated": baseline_foils,
            },
        ),
        tau=0.50,
        overall_nonmated=baseline_foils,
    )
    flooded = score_run(
        plan=plan,
        searches=_probe_searches(
            B_eyewear={
                "mated": [],
                "nonmated": flooded_foils,
            },
        ),
        tau=0.50,
        overall_nonmated=flooded_foils,
    )
    b_row = {item["stratum"]: item for item in baseline.to_rows()}["B_eyewear"]
    f_row = {item["stratum"]: item for item in flooded.to_rows()}["B_eyewear"]
    assert b_row["fpi"] == 1
    assert f_row["fpi"] == 1
    assert type(f_row["fpi"]) is int
    assert f_row["n_nonmated"] == 5
    assert f_row["fpi"] != pytest.approx(1 / 5)
    assert enrolled != union
    assert baseline.points["B_eyewear"].n_enrolled_gallery_subjects == enrolled
    assert baseline.points["B_eyewear"].fpi_per_enrolled_subject == pytest.approx(
        1 / enrolled
    )
    assert flooded.points["B_eyewear"].fpi_per_enrolled_subject == pytest.approx(
        1 / enrolled
    )
    assert baseline.points["B_eyewear"].fpi_per_enrolled_subject != pytest.approx(
        1 / union
    )


def test_overall_point_pools_injected_searches(tmp_path: Path) -> None:
    """MLDATA-07: overall FNIR is search-weighted, not an unweighted mean of cells.

    A has two mated hits (FNIR 0) and C has one miss (FNIR 1). Search-weighted
    overall is 1/3; the unweighted mean of {0, 1} is 0.5.
    """
    plan = _copresent_plan(tmp_path)
    alice_g = _gallery_of(plan, "Alice")
    bob_g = _gallery_of(plan, "Bob")
    assert alice_g != bob_g
    pair = [
        _hit("Alice", 0.90, gallery=alice_g, media_id=10),
        _hit("Bob", 0.90, gallery=bob_g, media_id=10),
    ]
    foils = [_bob_foil(plan, "Alice", 0.80)]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": pair, "nonmated": []},
            B_eyewear={"mated": [], "nonmated": foils},
            C_pose={"mated": [_alice_miss(plan, media_id=12)], "nonmated": []},
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    assert report.points["A_true_occluder"].fnir == pytest.approx(0.0)
    assert report.points["C_pose"].fnir == pytest.approx(1.0)
    assert report.overall.n_mated == 3
    assert report.overall.n_nonmated == 1
    assert report.overall.fnir == pytest.approx(1 / 3)
    assert report.overall.fnir != pytest.approx(0.5)
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


def test_explicit_empty_overall_nonmated_is_unmeasured_fpi(tmp_path: Path) -> None:
    """BR-15 / EVAL-18: overall_nonmated=() is not an FPI of zero.

    Stratum cells can still count their own foils; the headline must not
    publish perfect open-set rejection over an undeclared non-mated set.
    """
    plan = _plan(tmp_path)
    foils = [_alice_foil(plan, "Alice", 0.90)]
    searches = _probe_searches(
        A_true_occluder={"mated": [_alice_hit(plan)], "nonmated": foils},
        B_eyewear={"mated": [_bob_hit(plan)], "nonmated": []},
        C_pose={"mated": [_alice_hit(plan, media_id=12)], "nonmated": []},
    )
    report = score_run(
        plan=plan,
        searches=searches,
        tau=0.50,
        overall_nonmated=(),
    )
    assert report.points["A_true_occluder"].fpi == 1
    assert report.overall.n_mated == 3
    assert report.overall.measured is True
    assert report.overall.n_nonmated == 0
    assert report.overall.fpi is None
    assert report.overall.fpi != 0
    assert report.overall.fpi_per_enrolled_subject is None


def test_omitted_foils_do_not_score_perfect_open_set_rejection(tmp_path: Path) -> None:
    """BR-15 / EVAL-18: no strangers met → FPI unmeasured, not 0 / 0.0 rate."""
    plan = _plan(tmp_path)
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_alice_hit(plan)],
                "nonmated": [],
            },
        ),
        tau=0.50,
    )
    assert report.overall.n_mated == 1
    assert report.overall.fnir == pytest.approx(0.0)
    assert report.overall.n_nonmated == 0
    assert report.overall.measured is True
    assert report.overall.fpi is None
    assert report.overall.fpi != 0
    assert report.overall.fpi_per_enrolled_subject is None
    assert report.overall.fpi_per_enrolled_subject != pytest.approx(0.0)
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    assert row["fpi"] is None
    assert row["fpi"] != 0


def test_closed_set_fpi_zero_requires_explicit_flag(tmp_path: Path) -> None:
    """BR-15: a genuine closed-set FPI of 0 is declared, never reached by omission."""
    plan = _plan(tmp_path)
    searches = _probe_searches(
        A_true_occluder={
            "mated": [_alice_hit(plan)],
            "nonmated": [],
        },
    )
    omitted = score_run(plan=plan, searches=searches, tau=0.50)
    declared = score_run(
        plan=plan,
        searches=searches,
        tau=0.50,
        closed_set=True,
    )
    assert omitted.overall.fpi is None
    assert declared.overall.fpi == 0
    assert type(declared.overall.fpi) is int
    assert declared.overall.n_nonmated == 0
    with pytest.raises(FirBakeoffRunError, match="closed_set"):
        score_run(
            plan=plan,
            searches=searches,
            tau=0.50,
            closed_set=True,
            overall_nonmated=[_alice_foil(plan, "Bob", 0.80)],
        )


def _stratum_foils(plan) -> dict[str, list[SearchResult]]:
    return {
        "A_true_occluder": [
            _alice_foil(plan, "Alice", 0.90),
            _alice_foil(plan, "Bob", 0.20),
        ],
        "B_eyewear": [
            _bob_foil(plan, "Alice", 0.90),
            _bob_foil(plan, "Bob", 0.20),
        ],
        "C_pose": [
            _alice_foil(plan, "Alice", 0.90, media_id=12),
            _alice_foil(plan, "Bob", 0.20, media_id=12),
        ],
        "D_capture": [
            _nonmated_hit("Alice", 0.90, gallery=GalleryName.G1, media_id=13),
            _nonmated_hit("Bob", 0.20, gallery=GalleryName.G1, media_id=13),
        ],
    }


def test_overall_nonmated_is_declared_once_not_pooled(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    by_stratum = _stratum_foils(plan)
    foils = by_stratum["A_true_occluder"]
    searches = {
        name: {"mated": [], "nonmated": by_stratum[name]} for name in PROBE_STRATA
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
    with pytest.raises(FirBakeoffRunError, match="declared once"):
        score_run(plan=plan, searches=searches, tau=0.50)


def test_omitting_overall_nonmated_with_stratum_nonmated_raises(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    by_stratum = _stratum_foils(plan)
    searches = {
        name: {"mated": [], "nonmated": by_stratum[name]} for name in PROBE_STRATA
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
                "mated": [_alice_hit(plan)],
                "nonmated": [],
            },
            C_pose={
                "mated": [_alice_miss(plan, media_id=12)],
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


def test_empty_search_lists_on_populated_probe_cell_are_incomplete() -> None:
    """BR-17 / EVAL-16 / EVAL-19: a present key with empty lists is not complete-and-zero.

    Round-3 BR-09 required the key. Reconcile len(mated) against the plan so a
    caller who drops undetected mates or zero-face non-mates cannot look measured.
    """
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    assert len(plan.probe_entries["A_true_occluder"]) == 32
    expected_a = expected_mated_search_count(plan, stratum="A_true_occluder")
    assert expected_a != 32
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
    )
    row = {item["stratum"]: item for item in report.to_rows()}["A_true_occluder"]
    assert row["n_images"] == 32
    assert row["n_mated"] == 0
    assert row["search_shortfall"] == expected_a
    assert row["incomplete"] is True
    assert row["measured"] is False
    assert row["fnir"] == "not measured"
    for name in PROBE_STRATA:
        cell = {item["stratum"]: item for item in report.to_rows()}[name]
        expected = expected_mated_search_count(plan, stratum=name)
        assert cell["search_shortfall"] == expected
        assert cell["incomplete"] is True
        assert cell["n_mated"] == 0


def test_explicit_empty_mated_list_is_unmeasured_not_missing(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    foils = [_bob_foil(plan, "Alice", 0.90)]
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
    assert row["search_shortfall"] == 1
    assert row["incomplete"] is True


def test_enrolled_gallery_mismatch_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    union = _union_enrolled(plan)
    legal = {_roster_n(plan, GalleryName.G1), _roster_n(plan, GalleryName.G2)}
    assert union not in legal
    with pytest.raises(FirBakeoffRunError) as excinfo:
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=0.50,
            n_enrolled_gallery_subjects=union,
        )
    msg = str(excinfo.value)
    assert str(union) in msg
    assert str(_roster_n(plan, GalleryName.G1)) in msg
    assert str(_roster_n(plan, GalleryName.G2)) in msg
    with pytest.raises(FirBakeoffRunError):
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=0.50,
            n_enrolled_gallery_subjects=99,
        )


def test_enrolled_gallery_follows_declared_search_gallery(tmp_path: Path) -> None:
    """BR-12: FPI denom is the searched gallery, not len(g1)+len(g2)."""
    plan = _plan(tmp_path)
    union = _union_enrolled(plan)
    foil_gallery = _other_gallery(plan, "Alice")
    enrolled = _roster_n(plan, foil_gallery)
    assert enrolled != union
    foils = [_alice_foil(plan, "Bob", 0.80)]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": [], "nonmated": foils},
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    point = report.points["A_true_occluder"]
    assert point.n_enrolled_gallery_subjects == enrolled
    assert point.n_enrolled_gallery_subjects != union
    assert point.fpi_per_enrolled_subject == pytest.approx(1 / enrolled)
    assert point.fpi_per_enrolled_subject != pytest.approx(1 / union)
    assert point.galleries == (foil_gallery,)
    assert report.overall.n_enrolled_gallery_subjects == enrolled
    assert report.overall.galleries == (foil_gallery,)
    with pytest.raises(FirBakeoffRunError):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [], "nonmated": foils},
            ),
            tau=0.50,
            n_enrolled_gallery_subjects=union,
            overall_nonmated=foils,
        )


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
    union = _union_enrolled(plan)
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
    )
    assert report.to_rows()
    for row in report.to_rows():
        assert row["tau"] == 0.50
        assert "fpi_per_enrolled_subject" in row
        assert "gallery" in row
        if row["n_mated"] == 0 and row["n_nonmated"] == 0:
            assert row["n_enrolled_gallery_subjects"] is None
            assert row["n_enrolled_gallery_subjects"] != union
    with pytest.raises(FirBakeoffRunError):
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=0.50,
            n_enrolled_gallery_subjects=union,
        )
    with pytest.raises(FirBakeoffRunError, match="tau"):
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=float("inf"),
        )

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


def test_withheld_probe_templates_reach_report_at_seed_0() -> None:
    """BR-14 / MLDATA-07 / MLDATA-09: a filter that removes probes must be in the table.

    Frozen seed 0 withholds exactly two leftover templates whose media collide
    with enrollment. Withholding 2 and withholding 40 must not render the same.
    """
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    withheld_ids = {t.template_id for t in plan.withheld_probe_templates}
    assert withheld_ids == {"632:Burnished Ridgeway", "353:Pewter Hollow"}
    assert len(plan.withheld_probe_templates) == 2
    report = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
    )
    assert report.withheld_probe_templates == plan.withheld_probe_templates
    assert len(report.withheld_probe_templates) == 2
    rows = report.to_rows()
    assert rows
    for row in rows:
        assert row["n_withheld_probe_templates"] == 2
        assert row["n_withheld_probe_templates"] != 0


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


def _copresent_plan(tmp_path: Path, *, seed: int = 7):
    entries = [
        _entry(1, "E_clean", ["Alice"], "a"),
        _entry(2, "E_clean", ["Alice"], "b"),
        _entry(3, "E_clean", ["Bob"], "c"),
        _entry(4, "E_clean", ["Bob"], "d"),
        _entry(5, "E_clean", ["Dale", "Eve"], "i"),
        _entry(10, "A_true_occluder", ["Alice", "Bob"], "e"),
        _entry(11, "B_eyewear", ["Bob"], "f"),
        _entry(12, "C_pose", ["Alice"], "g"),
        _entry(13, "D_capture", ["Carol"], "h"),
    ]
    path = _write_manifest(tmp_path, entries, strata_counts=_base_counts())
    return build_run_plan(selection_manifest_path=path, seed=seed)


def test_build_run_plan_consumes_probes_for(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert set(plan.probe_sets) == {GalleryName.G1, GalleryName.G2}
    for gallery, probe_set in plan.probe_sets.items():
        assert probe_set.gallery is gallery
        assert probe_set.n_nonmated > 0
    mated_g1, foils_g1 = occluded_probes_for(plan, gallery=GalleryName.G1)
    mated_g2, foils_g2 = occluded_probes_for(plan, gallery=GalleryName.G2)
    assert mated_g1 or foils_g1
    assert mated_g2 or foils_g2


def test_search_against_undeclared_gallery_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    bogus = SearchResult(
        detected=True,
        top1_score=0.90,
        top1_name="Alice",
        true_name="Alice",
        gallery="g3",
        media_id=10,
    )
    with pytest.raises(FirBakeoffRunError, match="declared gallery"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [bogus], "nonmated": []},
            ),
            tau=0.50,
        )


def test_mated_true_name_not_enrolled_in_declared_gallery_raises(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    wrong = SearchResult(
        detected=True,
        top1_score=0.90,
        top1_name="Dale",
        true_name="Dale",
        gallery=_gallery_of(plan, "Alice"),
        media_id=10,
    )
    with pytest.raises(FirBakeoffRunError, match="not enrolled"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [wrong], "nonmated": []},
            ),
            tau=0.50,
        )


def test_nonmated_search_that_drops_enrolled_identity_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    dropped = _nonmated_hit(
        "Alice",
        0.90,
        gallery=_gallery_of(plan, "Alice"),
        media_id=10,
    )
    with pytest.raises(FirBakeoffRunError, match="filed as non-mated"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [], "nonmated": [dropped]},
            ),
            tau=0.50,
            overall_nonmated=[dropped],
        )


def test_stranger_probe_filed_as_mated_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    stranger = _hit("Carol", 0.90, gallery=GalleryName.G1, media_id=13)
    with pytest.raises(FirBakeoffRunError, match="filed as mated"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                D_capture={"mated": [stranger], "nonmated": []},
            ),
            tau=0.50,
        )


def test_copresent_probe_with_one_gallery_raises(tmp_path: Path) -> None:
    plan = _copresent_plan(tmp_path)
    both = both_gallery_probe_entries(plan)
    assert any(entry.media_id == 10 for entry in both)
    with pytest.raises(FirBakeoffRunError, match="both galleries"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                A_true_occluder={"mated": [_alice_hit(plan)], "nonmated": []},
            ),
            tau=0.50,
        )


def test_copresent_probe_yields_two_searches(tmp_path: Path) -> None:
    plan = _copresent_plan(tmp_path)
    alice_g = _gallery_of(plan, "Alice")
    bob_g = _gallery_of(plan, "Bob")
    assert alice_g != bob_g
    pair = [
        _hit("Alice", 0.90, gallery=alice_g, media_id=10),
        _hit("Bob", 0.90, gallery=bob_g, media_id=10),
    ]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": pair, "nonmated": []},
        ),
        tau=0.50,
    )
    assert report.points["A_true_occluder"].n_mated == 2
    assert report.points["A_true_occluder"].n_mated != 1


def test_frozen_seed0_six_occluded_stills_are_enrolled_in_both_galleries() -> None:
    """Seed-0 frozen frame: 6 co-present stills → 12 searches, not 6."""
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    both = both_gallery_probe_entries(plan)
    n_stills = len(both)
    n_searches = both_gallery_search_count(plan)
    assert n_stills == 6
    assert n_searches == 12
    assert n_searches != n_stills
    assert n_searches == sum(
        len(mated_galleries_for(entry, plan=plan)) for entry in both
    )
    by_stratum: dict[str, list[SearchResult]] = {name: [] for name in PROBE_STRATA}
    for entry in both:
        gallery = mated_galleries_for(entry, plan=plan)[0]
        true_name = mated_identities_for(entry, split=plan.split, gallery=gallery)[0]
        by_stratum[entry.stratum].append(
            _hit(true_name, 0.90, gallery=gallery, media_id=entry.media_id)
        )
    searches = _probe_searches(
        **{
            name: {"mated": items, "nonmated": []}
            for name, items in by_stratum.items()
            if items
        }
    )
    with pytest.raises(FirBakeoffRunError, match="both galleries"):
        score_run(plan=plan, searches=searches, tau=0.50)


def test_frozen_seed0_copresent_stills_yield_twelve_searches() -> None:
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    both = both_gallery_probe_entries(plan)
    assert len(both) == 6
    by_stratum: dict[str, list[SearchResult]] = {name: [] for name in PROBE_STRATA}
    for entry in both:
        for gallery in mated_galleries_for(entry, plan=plan):
            true_name = mated_identities_for(entry, split=plan.split, gallery=gallery)[0]
            by_stratum[entry.stratum].append(
                _hit(true_name, 0.90, gallery=gallery, media_id=entry.media_id)
            )
    injected = sum(len(items) for items in by_stratum.values())
    assert injected == 12
    searches = _probe_searches(
        **{
            name: {"mated": items, "nonmated": []}
            for name, items in by_stratum.items()
            if items
        }
    )
    report = score_run(plan=plan, searches=searches, tau=0.50)
    scored = sum(report.points[name].n_mated for name in PROBE_STRATA)
    assert scored == 12
    assert scored != 6


def test_honest_per_gallery_count_is_accepted_at_seed_0() -> None:
    """BR-12 inversion: 53 at seed 0 is the honest G1 size and must not raise."""
    plan = build_run_plan(selection_manifest_path=_frozen_manifest(), seed=0)
    n_g1 = len(plan.split.g1)
    n_g2 = len(plan.split.g2)
    union = n_g1 + n_g2
    assert n_g1 == 53
    assert n_g2 == 56
    assert union == 109
    accepted = score_run(
        plan=plan,
        searches=_probe_searches(),
        tau=0.50,
        n_enrolled_gallery_subjects=53,
    )
    assert accepted.overall.n_enrolled_gallery_subjects is None
    with pytest.raises(FirBakeoffRunError) as excinfo:
        score_run(
            plan=plan,
            searches=_probe_searches(),
            tau=0.50,
            n_enrolled_gallery_subjects=109,
        )
    assert "109" in str(excinfo.value)
    assert "53" in str(excinfo.value)
    g1_name = next(iter(plan.split.g1))
    g1_foil = _first_foil_entry(plan, GalleryName.G1)
    g1_foils = [
        _nonmated_hit(g1_name, 0.90, gallery=GalleryName.G1, media_id=g1_foil.media_id)
    ]
    g1_report = score_run(
        plan=plan,
        searches=_probe_searches(
            **{
                g1_foil.stratum: {"mated": [], "nonmated": g1_foils},
            }
        ),
        tau=0.50,
        n_enrolled_gallery_subjects=53,
        overall_nonmated=g1_foils,
    )
    point = g1_report.points[g1_foil.stratum]
    assert point.n_enrolled_gallery_subjects == 53
    assert point.n_enrolled_gallery_subjects != 109
    assert point.galleries == (GalleryName.G1,)
    assert point.fpi_per_enrolled_subject == pytest.approx(1 / 53)
    assert g1_report.overall.n_enrolled_gallery_subjects == 53
    g2_foil = _first_foil_entry(plan, GalleryName.G2)
    g2_foils = [
        _nonmated_hit(
            next(iter(plan.split.g2)),
            0.90,
            gallery=GalleryName.G2,
            media_id=g2_foil.media_id,
        )
    ]
    with pytest.raises(FirBakeoffRunError, match="g2"):
        score_run(
            plan=plan,
            searches=_probe_searches(
                **{
                    g2_foil.stratum: {"mated": [], "nonmated": g2_foils},
                }
            ),
            tau=0.50,
            n_enrolled_gallery_subjects=53,
            overall_nonmated=g2_foils,
        )


def test_report_names_searched_gallery(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    foil_g = _other_gallery(plan, "Alice")
    mate_g = _gallery_of(plan, "Alice")
    foils = [_alice_foil(plan, "Bob", 0.80)]
    g1_only = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": [], "nonmated": foils},
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    pooled = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_alice_hit(plan)],
                "nonmated": foils,
            },
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    g1_row = {item["stratum"]: item for item in g1_only.to_rows()}["A_true_occluder"]
    pooled_row = {item["stratum"]: item for item in pooled.to_rows()}["A_true_occluder"]
    assert g1_row["gallery"] == (foil_g.value,)
    assert set(pooled_row["gallery"]) == {mate_g.value, foil_g.value}
    assert g1_row["gallery"] != pooled_row["gallery"]
    assert g1_only.points["A_true_occluder"].n_enrolled_gallery_subjects == _roster_n(
        plan, foil_g
    )
    assert pooled.points["A_true_occluder"].n_enrolled_gallery_subjects is None


def test_overall_pooled_point_has_unmeasured_enrolled_denominator(
    tmp_path: Path,
) -> None:
    """Overall FNIR may span G1 and G2; that point has no honest FPI denom."""
    plan = _plan(tmp_path)
    union = _union_enrolled(plan)
    foils = [_alice_foil(plan, "Bob", 0.80)]
    report = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={
                "mated": [_alice_hit(plan)],
                "nonmated": foils,
            },
            B_eyewear={"mated": [_bob_hit(plan)], "nonmated": []},
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    assert {g.value for g in report.overall.galleries} == {"g1", "g2"}
    assert report.overall.n_enrolled_gallery_subjects is None
    assert report.overall.n_enrolled_gallery_subjects != union
    assert report.overall.fpi == 1
    assert report.overall.fpi_per_enrolled_subject is None
    foil_only = score_run(
        plan=plan,
        searches=_probe_searches(
            A_true_occluder={"mated": [], "nonmated": foils},
        ),
        tau=0.50,
        overall_nonmated=foils,
    )
    foil_n = _roster_n(plan, _other_gallery(plan, "Alice"))
    assert foil_only.overall.n_enrolled_gallery_subjects == foil_n
    assert foil_only.overall.n_enrolled_gallery_subjects != union


def test_mated_identities_for_unknown_gallery_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    entry = plan.probe_entries["A_true_occluder"][0]
    with pytest.raises(FirBakeoffRunError, match="declared gallery"):
        mated_identities_for(entry, split=plan.split, gallery="banana")


def test_search_against_omitted_declared_gallery_raises(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    g1_only = RunPlan(
        split=plan.split,
        probe_entries=plan.probe_entries,
        seed=plan.seed,
        index=plan.index,
        gallery_entries=plan.gallery_entries,
        probe_sets={GalleryName.G1: plan.probe_sets[GalleryName.G1]},
    )
    search = _hit("Alice", 0.90, gallery=GalleryName.G2, media_id=10)
    with pytest.raises(FirBakeoffRunError, match="declared gallery"):
        score_run(
            plan=g1_only,
            searches=_probe_searches(
                A_true_occluder={"mated": [search], "nonmated": []},
            ),
            tau=0.50,
        )

