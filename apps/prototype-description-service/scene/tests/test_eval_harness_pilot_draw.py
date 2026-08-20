"""DESCQUAL-2 cost-and-instrument pilot: draw, packets, gold QC (HITL-03)."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.eval_harness.audit_sampling import allocate, draw, project_strata_image_counts
from scripts.eval_harness import pilot_draw as pilot_draw_mod
from scripts.eval_harness.manifest import (
    ConfirmationSource,
    FactKind,
    FactPolarity,
    ReferenceFact,
)
from scripts.eval_harness.pilot_draw import (
    BAKEOFF_SELECTION_SCHEMA,
    GOLD_RATE_PERCENT,
    PILOT_ANNOTATOR_SLOTS,
    PILOT_GOLD_SME,
    GoldAnswerSource,
    GoldItem,
    GoldKind,
    PilotDrawError,
    StratumName,
    draw_pilot,
    emit_annotation_packet,
    select_gold_items,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIR12_MANIFEST = _REPO_ROOT / "benchmarks/manifests/fir12-selection-v1.json"
_PILOT_N = 30
_PILOT_SEED = 20260820


def _payload() -> dict:
    return json.loads(_FIR12_MANIFEST.read_text())


def _entries_by_sha256(payload: dict | None = None) -> dict[str, dict]:
    body = payload if payload is not None else _payload()
    return {entry["sha256"]: entry for entry in body["entries"]}


def _draw(*, n: int = _PILOT_N, seed: int = _PILOT_SEED, **kwargs):
    return draw_pilot(
        selection_manifest_path=_FIR12_MANIFEST,
        n=n,
        seed=seed,
        **kwargs,
    )


def _mini_entry(
    *,
    sha256: str,
    stratum: str,
    media_id: int,
    identities: list[str] | None = None,
) -> dict[str, object]:
    return {
        "sha256": sha256,
        "stratum": stratum,
        "media_id": media_id,
        "source_path": f"/tmp/{sha256}.jpg",
        "present_identities": identities if identities is not None else [f"id-{media_id}"],
    }


def _write_manifest(
    path: Path,
    *,
    n_per: int = 8,
    declared_empty: list[object] | None = None,
    schema: str = BAKEOFF_SELECTION_SCHEMA,
    extra_entries: list[dict[str, object]] | None = None,
    omit: str | None = None,
) -> Path:
    entries: list[dict[str, object]] = []
    media_id = 1
    for stratum in StratumName:
        for index in range(n_per):
            identities = [f"id-{media_id}"]
            if stratum is StratumName.E_CLEAN and index == 0:
                identities = ["alice", "bob"]
            entries.append(
                _mini_entry(
                    sha256=f"{stratum.value}-{index:03d}",
                    stratum=stratum.value,
                    media_id=media_id,
                    identities=identities,
                )
            )
            media_id += 1
    if extra_entries:
        entries.extend(extra_entries)
    counts: dict[str, dict[str, int]] = {}
    for stratum in StratumName:
        counts[stratum.value] = {
            "images": sum(1 for entry in entries if entry["stratum"] == stratum.value),
            "unique_subjects_faces_gt0": 1,
        }
    payload: dict[str, object] = {
        "schema": schema,
        "declared_empty_cells": (
            ["never-recompute-me", "mask_sufficient_n"]
            if declared_empty is None
            else declared_empty
        ),
        "strata_counts": counts,
        "entries": entries,
    }
    if omit is not None:
        payload.pop(omit, None)
    path.write_text(json.dumps(payload))
    return path


def test_draw_pilot_is_reproducible_under_seed():
    first = _draw(seed=_PILOT_SEED)
    second = _draw(seed=_PILOT_SEED)
    other = _draw(seed=_PILOT_SEED + 1)
    assert [unit.unit_id for unit in first.sample.units] == [
        unit.unit_id for unit in second.sample.units
    ]
    assert [unit.unit_id for unit in first.sample.units] != [
        unit.unit_id for unit in other.sample.units
    ]
    assert first.seed == _PILOT_SEED
    assert other.seed == _PILOT_SEED + 1


def test_draw_pilot_composes_allocate_then_draw():
    payload = _payload()
    members: dict[str, list[str]] = {name.value: [] for name in StratumName}
    for entry in payload["entries"]:
        members[entry["stratum"]].append(entry["sha256"])
    declared = project_strata_image_counts(payload["strata_counts"])
    allocation = allocate(strata_sizes=declared, n=_PILOT_N)
    expected = draw(strata_members=members, allocation=allocation, seed=_PILOT_SEED)
    pilot = _draw()
    assert list(pilot.sample.unit_ids) == list(expected.unit_ids)
    assert dict(pilot.allocation.counts) == dict(allocation.counts)
    assert len(pilot.sample.units) == _PILOT_N
    assert len(set(pilot.sample.unit_ids)) == _PILOT_N


def test_drawn_units_keep_inclusion_probability():
    pilot = _draw()
    payload = _payload()
    declared = project_strata_image_counts(payload["strata_counts"])
    for unit in pilot.sample.units:
        n_h = pilot.allocation[unit.stratum]
        n_frame = declared[unit.stratum]
        assert 0 < unit.inclusion_probability <= 1
        assert unit.inclusion_probability == pytest.approx(n_h / n_frame)


def test_draw_pilot_rejects_non_int_n_and_seed():
    with pytest.raises(PilotDrawError, match="n must be an int"):
        _draw(n=True)  # type: ignore[arg-type]
    with pytest.raises(PilotDrawError, match="seed must be an int"):
        _draw(seed=True)  # type: ignore[arg-type]


def test_draw_pilot_rejects_wrong_schema(tmp_path: Path):
    path = _write_manifest(tmp_path / "bad.json", schema="bakeoff-selection/0")
    with pytest.raises(PilotDrawError, match="bakeoff-selection/1"):
        draw_pilot(selection_manifest_path=path, n=10, seed=1)


def test_draw_pilot_rejects_missing_declared_empty_cells(tmp_path: Path):
    path = _write_manifest(tmp_path / "missing.json", omit="declared_empty_cells")
    with pytest.raises(PilotDrawError, match="declared_empty_cells"):
        draw_pilot(selection_manifest_path=path, n=10, seed=1)


def test_emit_annotation_packet_is_one_dual_annotator_row_per_drawn_image():
    payload = _payload()
    entries = _entries_by_sha256(payload)
    pilot = _draw()
    packets = emit_annotation_packet(
        pilot=pilot,
        entries_by_sha256=entries,
        batch_id="pilot-2026-08-20",
    )
    assert len(packets) == _PILOT_N
    assert [row["sha256"] for row in packets] == [str(unit.unit_id) for unit in pilot.sample.units]
    for packet, unit in zip(packets, pilot.sample.units, strict=True):
        entry = entries[str(unit.unit_id)]
        assert packet["media_id"] == entry["media_id"]
        assert packet["stratum"] == unit.stratum
        assert packet["inclusion_probability"] == unit.inclusion_probability
        assert packet["annotation_batch"] == "pilot-2026-08-20"
        assert packet["source_path"] == entry["source_path"]
        assert packet["annotator_slots"] == [PILOT_ANNOTATOR_SLOTS[0], PILOT_ANNOTATOR_SLOTS[1]]
        assert len(packet["annotator_slots"]) == 2
        assert packet["reference_facts"] == []
    json.dumps(packets)


def test_packet_reference_fact_skeleton_requires_annotator_id():
    payload = _payload()
    packets = emit_annotation_packet(
        pilot=_draw(),
        entries_by_sha256=_entries_by_sha256(payload),
        batch_id="pilot-2026-08-20",
    )
    packet = packets[0]
    fact = ReferenceFact(
        text="a visible bicycle",
        kind=FactKind.OBJECT,
        polarity=FactPolarity.TRUE,
        phrases=["bicycle"],
        confirmed_by=ConfirmationSource.OPERATOR,
        annotator_id=packet["annotator_slots"][0],
        annotation_batch=packet["annotation_batch"],
        annotated_at="2026-08-20T00:00:00Z",
        source_pool="pilot-pool",
    )
    assert fact.annotator_id == PILOT_ANNOTATOR_SLOTS[0]
    assert fact.annotation_batch == "pilot-2026-08-20"
    with pytest.raises(ValidationError, match="annotator_id"):
        ReferenceFact(
            text="a visible bicycle",
            kind=FactKind.OBJECT,
            polarity=FactPolarity.TRUE,
            phrases=["bicycle"],
            confirmed_by="operator",
            annotation_batch=packet["annotation_batch"],
            annotated_at="2026-08-20T00:00:00Z",
            source_pool="pilot-pool",
        )


def test_gold_items_are_outside_the_drawn_sample():
    payload = _payload()
    entries = _entries_by_sha256(payload)
    pilot = _draw()
    gold = select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=_PILOT_SEED)
    sampled = {str(unit.unit_id) for unit in pilot.sample.units}
    gold_ids = {item.sha256 for item in gold}
    assert gold_ids.isdisjoint(sampled)
    assert len(gold) == 3
    assert len(gold_ids) == 3
    assert _PILOT_N * GOLD_RATE_PERCENT // 100 == 3


def test_gold_mix_is_random_batch_matched_and_hard():
    payload = _payload()
    entries = _entries_by_sha256(payload)
    pilot = _draw()
    gold = select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=_PILOT_SEED)
    kinds = {item.kind for item in gold}
    assert kinds == {GoldKind.RANDOM, GoldKind.BATCH_MATCHED, GoldKind.HARD}
    counts: dict[str, int] = {}
    for unit in pilot.sample.units:
        counts[unit.stratum] = counts.get(unit.stratum, 0) + 1
    top = max(counts.values())
    plurality = min(name for name, count in counts.items() if count == top)
    matched = next(item for item in gold if item.kind is GoldKind.BATCH_MATCHED)
    assert matched.stratum.value == plurality
    hard = next(item for item in gold if item.kind is GoldKind.HARD)
    entry = entries[hard.sha256]
    assert entry["stratum"] in {
        StratumName.A_TRUE_OCCLUDER,
        StratumName.B_EYEWEAR,
    } or len(entry["present_identities"]) >= 2


def test_gold_selection_is_deterministic_under_seed():
    payload = _payload()
    entries = _entries_by_sha256(payload)
    pilot = _draw()
    first = select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=_PILOT_SEED)
    second = select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=_PILOT_SEED)
    other = select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=_PILOT_SEED + 1)
    assert [item.sha256 for item in first] == [item.sha256 for item in second]
    assert [item.sha256 for item in first] != [item.sha256 for item in other]


def test_gold_rate_zero_on_nonempty_draw_raises(tmp_path: Path):
    path = _write_manifest(tmp_path / "small.json", n_per=4)
    pilot = draw_pilot(selection_manifest_path=path, n=5, seed=1)
    assert len(pilot.sample.units) == 5
    entries = {entry["sha256"]: entry for entry in json.loads(path.read_text())["entries"]}
    with pytest.raises(PilotDrawError, match="zero units"):
        select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=1)


def test_gold_cannot_be_selected_when_sample_is_a_census(tmp_path: Path):
    path = _write_manifest(tmp_path / "census.json", n_per=8)
    payload = json.loads(path.read_text())
    n = len(payload["entries"])
    assert n >= 30
    pilot = draw_pilot(selection_manifest_path=path, n=n, seed=1)
    entries = {entry["sha256"]: entry for entry in payload["entries"]}
    with pytest.raises(PilotDrawError, match="outside the sample"):
        select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=1)


def test_gold_item_refuses_caption_pool_source():
    with pytest.raises(PilotDrawError, match="caption pool"):
        GoldItem(
            sha256="abc",
            media_id=1,
            stratum=StratumName.E_CLEAN,
            kind=GoldKind.RANDOM,
            answer_source="caption_pool",  # type: ignore[arg-type]
            authored_by=PILOT_GOLD_SME,
            live_queue_annotators=PILOT_ANNOTATOR_SLOTS,
        )


def test_gold_item_refuses_live_queue_author():
    with pytest.raises(PilotDrawError, match="live annotation queue"):
        GoldItem(
            sha256="abc",
            media_id=1,
            stratum=StratumName.E_CLEAN,
            kind=GoldKind.RANDOM,
            answer_source=GoldAnswerSource.SME_ARBITRATED,
            authored_by=PILOT_ANNOTATOR_SLOTS[0],
            live_queue_annotators=PILOT_ANNOTATOR_SLOTS,
        )


def test_select_gold_items_uses_sme_not_on_live_queue():
    gold = select_gold_items(
        pilot=_draw(),
        entries_by_sha256=_entries_by_sha256(),
        seed=_PILOT_SEED,
    )
    for item in gold:
        assert item.answer_source is GoldAnswerSource.SME_ARBITRATED
        assert item.authored_by == PILOT_GOLD_SME
        assert item.authored_by not in item.live_queue_annotators
        assert item.live_queue_annotators == PILOT_ANNOTATOR_SLOTS


def test_report_rows_pass_through_declared_empty_cells_verbatim():
    payload = _payload()
    pilot = _draw()
    rows = pilot.report_rows()
    declared = [row["declared_empty"] for row in rows if "declared_empty" in row]
    assert declared == payload["declared_empty_cells"]
    assert declared == ["mask_sufficient_n", "veil", "goggles", "hair_occl"]
    stratum_rows = [row for row in rows if "stratum" in row]
    assert [row["stratum"] for row in stratum_rows] == list(payload["strata_counts"])
    for row in stratum_rows:
        n_declared = payload["strata_counts"][row["stratum"]]["images"]
        assert row["N_h"] == n_declared
        assert row["n_h"] == pilot.allocation[row["stratum"]]
        assert row["inclusion_probability"] == pytest.approx(row["n_h"] / row["N_h"])


def test_report_rows_do_not_recompute_declared_empty_cells(tmp_path: Path):
    trap = ["never-recompute-me", "mask_sufficient_n"]
    path = _write_manifest(tmp_path / "trap.json", n_per=8, declared_empty=trap)
    pilot = draw_pilot(selection_manifest_path=path, n=10, seed=1)
    declared = [row["declared_empty"] for row in pilot.report_rows() if "declared_empty" in row]
    assert declared == trap
    assert "never-recompute-me" in declared


def test_public_surface_has_no_replacement_draw_path():
    owned = [
        name
        for name, obj in inspect.getmembers(pilot_draw_mod)
        if callable(obj) and inspect.getmodule(obj) is pilot_draw_mod
    ]
    offenders = [name for name in owned if re.search(r"replac|refill|redraw|substitut", name, re.I)]
    assert offenders == []


def test_pilot_module_does_not_estimate_icc_or_deff():
    source = inspect.getsource(pilot_draw_mod)
    assert "estimate_icc" not in source
    assert "design_effect" not in source
    assert "draw_two_stage" not in source
    assert "cluster_params" not in source
    assert "size_for_margin" not in source


def test_precision_floors_are_passed_to_allocate():
    pilot = _draw(n=84, precision_floors={"B_eyewear": 0.10})
    assert pilot.allocation["B_eyewear"] == 44
    assert sum(pilot.allocation.values()) == 84


def test_emit_rejects_blank_batch_id():
    with pytest.raises(PilotDrawError, match="batch_id"):
        emit_annotation_packet(
            pilot=_draw(),
            entries_by_sha256=_entries_by_sha256(),
            batch_id="  ",
        )


def test_gold_kind_and_stratum_are_enums():
    assert GoldKind.RANDOM == "random"
    assert GoldKind.BATCH_MATCHED == "batch_matched"
    assert GoldKind.HARD == "hard"
    assert {member.value for member in StratumName} == {
        "A_true_occluder",
        "B_eyewear",
        "C_pose",
        "D_capture",
        "E_clean",
    }
