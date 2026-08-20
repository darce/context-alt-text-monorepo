"""DESCQUAL-2 cost-and-instrument pilot: draw, packets, gold QC (HITL-03)."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Mapping, Sequence
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
    GOLD_MIX_ORDER,
    GOLD_RATE_PERCENT,
    PILOT_ANNOTATOR_SLOTS,
    PILOT_GOLD_SME,
    GoldAnswerSource,
    GoldItem,
    GoldKind,
    PilotDrawError,
    StratumName,
    _gold_count,
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


@pytest.mark.parametrize(
    ("declared_delta",),
    [
        (6,),   # declared > observed
        (-2,),  # declared < observed
    ],
    ids=["declared_gt_observed", "declared_lt_observed"],
)
def test_draw_pilot_rejects_declared_vs_entry_count_mismatch(
    tmp_path: Path, declared_delta: int
):
    """Pin the frame-size parity guard (AUDIT-08 / rg-005 / rg-015).

    report_rows publishes pi = n_h / DECLARED N_h. A silent mismatch
    between strata_counts and the entries actually present biases every
    design-based weight. Both directions must raise this guard's message,
    not an unrelated PilotDrawError.
    """
    path = _write_manifest(tmp_path / "mismatch.json", n_per=8)
    payload = json.loads(path.read_text())
    stratum = StratumName.B_EYEWEAR.value
    observed = payload["strata_counts"][stratum]["images"]
    assert observed == 8
    declared = observed + declared_delta
    assert declared != observed
    payload["strata_counts"][stratum]["images"] = declared
    path.write_text(json.dumps(payload))
    with pytest.raises(
        PilotDrawError,
        match="entry counts per stratum do not match declared strata_counts",
    ) as caught:
        draw_pilot(selection_manifest_path=path, n=10, seed=1)
    message = str(caught.value)
    assert "entries=" in message
    assert "declared=" in message
    assert f"'{stratum}': {observed}" in message
    assert f"'{stratum}': {declared}" in message


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
    assert _gold_count(_PILOT_N) == 3


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
    n = 4
    assert _gold_count(n) == 0
    pilot = draw_pilot(selection_manifest_path=path, n=n, seed=1)
    assert len(pilot.sample.units) == n
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


# Fail-closed public surface. A new public callable or method is a review
# checkpoint: the pilot must not grow an ICC/deff estimator (AUDIT-11) or a
# replacement-draw path (AUDIT-13). Do not silently append to these sets.
_PUBLIC_MODULE_CALLABLES = frozenset(
    {
        "GoldAnswerSource",
        "GoldItem",
        "GoldKind",
        "PilotDraw",
        "PilotDrawError",
        "StratumName",
        "draw_pilot",
        "emit_annotation_packet",
        "select_gold_items",
    }
)
_PUBLIC_METHODS_BY_CLASS = {
    "GoldAnswerSource": frozenset(),
    "GoldItem": frozenset(),
    "GoldKind": frozenset(),
    "PilotDraw": frozenset({"report_rows"}),
    "PilotDrawError": frozenset(),
    "StratumName": frozenset(),
}
_DESIGN_STAT_KEYS = frozenset(
    {"icc", "rho", "deff", "design_effect", "n_eff", "msb", "msw"}
)


def _owned_callables() -> list[tuple[str, object]]:
    return [
        (name, obj)
        for name, obj in inspect.getmembers(pilot_draw_mod)
        if callable(obj) and inspect.getmodule(obj) is pilot_draw_mod
    ]


def _public_module_callables() -> frozenset[str]:
    return frozenset(name for name, _obj in _owned_callables() if not name.startswith("_"))


def _own_public_methods(cls: type) -> frozenset[str]:
    names: set[str] = set()
    for name, member in vars(cls).items():
        if name.startswith("_"):
            continue
        if isinstance(member, (staticmethod, classmethod, property)) or callable(member):
            names.add(name)
    return frozenset(names)


def _fail_surface_change(*, label: str, actual: frozenset[str], expected: frozenset[str]) -> None:
    added = sorted(actual - expected)
    removed = sorted(expected - actual)
    pytest.fail(
        f"{label} changed: added={added} removed={removed}. "
        "This frozen set is the review checkpoint for the cost-and-instrument "
        "pilot (BR-17): justify a new public callable or method against "
        "AUDIT-11 (pilot must not estimate ICC/deff) and AUDIT-13 (no "
        "replacement-draw path, including methods such as PilotDraw.fill_gaps "
        "that inspect.getmembers on the module cannot see). Do not silently "
        "append to the allowlist."
    )


def _id_set_from_collection(value: object) -> set[str] | None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        units = getattr(value, "units", None)
        if units is None:
            return None
        return {str(getattr(unit, "unit_id", unit)) for unit in units}
    ids: set[str] = set()
    found = False
    for item in value:
        if isinstance(item, str):
            ids.add(item)
            found = True
            continue
        if isinstance(item, Mapping) and isinstance(item.get("sha256"), str):
            ids.add(item["sha256"])
            found = True
            continue
        sha = getattr(item, "sha256", None)
        unit_id = getattr(item, "unit_id", None)
        if isinstance(sha, str):
            ids.add(sha)
            found = True
        elif unit_id is not None:
            ids.add(str(unit_id))
            found = True
    return ids if found else None


def test_public_surface_has_no_replacement_draw_path():
    owned = [name for name, _obj in _owned_callables()]
    offenders = [name for name in owned if re.search(r"replac|refill|redraw|substitut", name, re.I)]
    assert offenders == []
    actual = _public_module_callables()
    if actual != _PUBLIC_MODULE_CALLABLES:
        _fail_surface_change(
            label="pilot_draw public module-level callable surface",
            actual=actual,
            expected=_PUBLIC_MODULE_CALLABLES,
        )
    public_classes = {
        name
        for name, obj in inspect.getmembers(pilot_draw_mod)
        if inspect.isclass(obj)
        and inspect.getmodule(obj) is pilot_draw_mod
        and not name.startswith("_")
    }
    if public_classes != frozenset(_PUBLIC_METHODS_BY_CLASS):
        _fail_surface_change(
            label="pilot_draw public class surface",
            actual=public_classes,
            expected=frozenset(_PUBLIC_METHODS_BY_CLASS),
        )
    for cls_name, expected in _PUBLIC_METHODS_BY_CLASS.items():
        actual_methods = _own_public_methods(getattr(pilot_draw_mod, cls_name))
        if actual_methods != expected:
            _fail_surface_change(
                label=f"{cls_name} public methods",
                actual=actual_methods,
                expected=expected,
            )


def test_pilot_module_does_not_estimate_icc_or_deff():
    source = inspect.getsource(pilot_draw_mod)
    assert "estimate_icc" not in source
    assert "design_effect" not in source
    assert "draw_two_stage" not in source
    assert "cluster_params" not in source
    assert "size_for_margin" not in source
    actual = _public_module_callables()
    if actual != _PUBLIC_MODULE_CALLABLES:
        _fail_surface_change(
            label="pilot_draw public module-level callable surface",
            actual=actual,
            expected=_PUBLIC_MODULE_CALLABLES,
        )


def test_drawn_unit_set_never_grows_and_entrypoints_return_no_icc():
    """Behaviour behind BR-17: the draw is a fixed subset; no ICC/deff out."""
    first = _draw()
    drawn = {str(unit.unit_id) for unit in first.sample.units}
    assert drawn <= set(first.frame_sha256s)
    assert len(drawn) == _PILOT_N
    assert len(set(first.sample.unit_ids)) == _PILOT_N
    second = _draw()
    assert {str(unit.unit_id) for unit in second.sample.units} == drawn

    entries = _entries_by_sha256()
    packets = emit_annotation_packet(
        pilot=first,
        entries_by_sha256=entries,
        batch_id="pilot-2026-08-20",
    )
    packet_ids = {row["sha256"] for row in packets}
    assert packet_ids == drawn
    assert not packet_ids > drawn

    gold = select_gold_items(
        pilot=first, entries_by_sha256=entries, seed=_PILOT_SEED
    )
    gold_ids = {item.sha256 for item in gold}
    assert gold_ids.isdisjoint(drawn)
    assert not gold_ids > drawn

    for row in first.report_rows():
        keys = {str(key).lower() for key in row}
        assert not (keys & _DESIGN_STAT_KEYS)
        if "declared_empty" in row:
            assert set(row) == {"declared_empty"}
        else:
            assert set(row) == {"stratum", "N_h", "n_h", "inclusion_probability"}

    for name in sorted(_own_public_methods(type(first))):
        bound = getattr(first, name)
        try:
            result = bound()
        except TypeError:
            continue
        collection = _id_set_from_collection(result)
        if collection is not None:
            assert not collection > drawn, (
                f"public method {name} returned a proper superset of the draw "
                f"(AUDIT-13: nonresponse is bias, not a larger n)"
            )
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
            for item in result:
                if isinstance(item, Mapping):
                    keys = {str(key).lower() for key in item}
                    assert not (keys & _DESIGN_STAT_KEYS)


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
    assert GOLD_MIX_ORDER == (GoldKind.HARD, GoldKind.BATCH_MATCHED, GoldKind.RANDOM)
    assert {member.value for member in StratumName} == {
        "A_true_occluder",
        "B_eyewear",
        "C_pose",
        "D_capture",
        "E_clean",
    }


@pytest.mark.parametrize(
    ("n", "expected_g"),
    [
        (30, 3),
        (84, 9),
        (198, 22),
    ],
)
def test_gold_count_is_rate_of_annotation_queue(n: int, expected_g: int):
    g = _gold_count(n)
    assert g == expected_g
    rate = GOLD_RATE_PERCENT / 100
    queue = n + g
    assert abs(g - rate * queue) <= 0.5
    assert abs(g / queue - rate) * queue <= 0.5


def test_three_gold_items_become_available_at_n_23():
    assert _gold_count(22) == 2
    assert _gold_count(23) == 3


def test_gold_mix_refuses_truncation_when_gold_n_below_three(tmp_path: Path):
    path = _write_manifest(tmp_path / "mix.json", n_per=8)
    n = 14
    assert _gold_count(n) == 2
    pilot = draw_pilot(selection_manifest_path=path, n=n, seed=1)
    entries = {entry["sha256"]: entry for entry in json.loads(path.read_text())["entries"]}
    with pytest.raises(PilotDrawError, match="HITL-03 mix") as caught:
        select_gold_items(pilot=pilot, entries_by_sha256=entries, seed=1)
    message = str(caught.value)
    assert "gold_n=2" in message
    assert "random" in message
    assert "batch_matched" in message
    assert "hard" in message
    assert "n=23" in message


def test_gold_mix_round_robin_remainder_not_dumped_on_one_kind():
    n = 84
    assert _gold_count(n) == 9
    payload = _payload()
    entries = _entries_by_sha256(payload)
    gold = select_gold_items(pilot=_draw(n=n), entries_by_sha256=entries, seed=_PILOT_SEED)
    counts = {kind: 0 for kind in GOLD_MIX_ORDER}
    for item in gold:
        counts[item.kind] += 1
    assert len(gold) == 9
    assert counts == {
        GoldKind.HARD: 3,
        GoldKind.BATCH_MATCHED: 3,
        GoldKind.RANDOM: 3,
    }


def test_select_gold_items_rejects_sha_outside_frozen_frame():
    payload = _payload()
    entries = dict(_entries_by_sha256(payload))
    entries["not-in-frame-deadbeef"] = {
        "sha256": "not-in-frame-deadbeef",
        "media_id": 999999,
        "stratum": StratumName.E_CLEAN.value,
        "source_path": "/tmp/foreign.jpg",
        "present_identities": ["x"],
    }
    with pytest.raises(PilotDrawError, match="not in the frozen frame"):
        select_gold_items(
            pilot=_draw(),
            entries_by_sha256=entries,
            seed=_PILOT_SEED,
        )


def _mutate_loader_payload(payload: dict[str, object], case: str) -> None:
    if case == "missing_strata_counts":
        del payload["strata_counts"]
        return
    if case == "missing_entries":
        del payload["entries"]
        return
    if case == "duplicate_sha256":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        entries.append(dict(entries[0]))
        return
    if case == "missing_sha256":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        del entries[0]["sha256"]
        return
    if case == "missing_media_id":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        del entries[0]["media_id"]
        return
    if case == "missing_source_path":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        del entries[0]["source_path"]
        return
    if case == "missing_present_identities":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        del entries[0]["present_identities"]
        return
    if case == "present_identities_type":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        entries[0]["present_identities"] = "veil"
        return
    if case == "empty_source_path":
        entries = payload["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries")
        entries[0]["source_path"] = ""
        return
    if case == "empty_entries":
        payload["entries"] = []
        return
    if case == "unknown_strata_counts_key":
        counts = payload["strata_counts"]
        if not isinstance(counts, dict):
            raise TypeError("strata_counts")
        counts["Z_bogus"] = {"images": 0, "unique_subjects_faces_gt0": 0}
        return
    if case == "declared_empty_cells_type":
        payload["declared_empty_cells"] = "veil"
        return
    raise ValueError(f"unknown loader case {case}")


@pytest.mark.parametrize(
    ("case", "fragment"),
    [
        ("missing_strata_counts", "missing strata_counts"),
        ("missing_entries", "missing entries"),
        ("duplicate_sha256", "duplicate sha256"),
        ("missing_sha256", "missing sha256"),
        ("missing_media_id", "missing media_id"),
        ("missing_source_path", "missing source_path"),
        ("missing_present_identities", "missing present_identities"),
        ("present_identities_type", "present_identities.*must be a sequence"),
        ("empty_source_path", "source_path.*must be a non-empty str"),
        ("empty_entries", "entries must be non-empty"),
        ("unknown_strata_counts_key", "unknown strata"),
        ("declared_empty_cells_type", "declared_empty_cells must be a JSON list"),
    ],
    ids=[
        "missing_strata_counts",
        "missing_entries",
        "duplicate_sha256",
        "missing_sha256",
        "missing_media_id",
        "missing_source_path",
        "missing_present_identities",
        "present_identities_type",
        "empty_source_path",
        "empty_entries",
        "unknown_strata_counts_key",
        "declared_empty_cells_type",
    ],
)
def test_draw_pilot_rejects_loader_guard_violations(
    tmp_path: Path, case: str, fragment: str
):
    path = _write_manifest(tmp_path / "guard.json", n_per=8)
    payload = json.loads(path.read_text())
    _mutate_loader_payload(payload, case)
    path.write_text(json.dumps(payload))
    with pytest.raises(PilotDrawError, match=fragment):
        draw_pilot(selection_manifest_path=path, n=10, seed=1)


def test_select_gold_items_rejects_catalog_missing_frame_sha256s():
    """A truncated catalog must not silently shrink the gold universe (MLDATA-09)."""
    payload = _payload()
    entries = dict(_entries_by_sha256(payload))
    pilot = _draw()
    drawn = {str(unit.unit_id) for unit in pilot.sample.units}
    undrawn = [sha for sha in entries if sha not in drawn]
    drop_n = 3
    assert len(undrawn) >= drop_n
    dropped = undrawn[:drop_n]
    for sha in dropped:
        del entries[sha]
    with pytest.raises(PilotDrawError, match=rf"missing {drop_n} frozen-frame") as caught:
        select_gold_items(
            pilot=pilot,
            entries_by_sha256=entries,
            seed=_PILOT_SEED,
        )
    message = str(caught.value)
    for sha in dropped:
        assert sha not in message


def test_draw_pilot_rejects_non_str_sha256(tmp_path: Path):
    path = _write_manifest(tmp_path / "guard.json", n_per=8)
    payload = json.loads(path.read_text())
    payload["entries"][0]["sha256"] = 12345
    path.write_text(json.dumps(payload))
    with pytest.raises(PilotDrawError, match=r"sha256.*must be a non-empty str"):
        draw_pilot(selection_manifest_path=path, n=10, seed=1)


def test_draw_pilot_rejects_empty_sha256(tmp_path: Path):
    path = _write_manifest(tmp_path / "guard.json", n_per=8)
    payload = json.loads(path.read_text())
    payload["entries"][0]["sha256"] = ""
    path.write_text(json.dumps(payload))
    with pytest.raises(PilotDrawError, match=r"sha256.*must be a non-empty str"):
        draw_pilot(selection_manifest_path=path, n=10, seed=1)


def test_draw_pilot_rejects_non_str_source_path(tmp_path: Path):
    path = _write_manifest(tmp_path / "guard.json", n_per=8)
    payload = json.loads(path.read_text())
    payload["entries"][0]["source_path"] = 99
    path.write_text(json.dumps(payload))
    with pytest.raises(PilotDrawError, match=r"source_path.*must be a non-empty str"):
        draw_pilot(selection_manifest_path=path, n=10, seed=1)


def test_gold_draw_is_invariant_to_catalog_insertion_order():
    items = list(_entries_by_sha256().items())
    forward = dict(items)
    reverse = dict(reversed(items))
    assert list(forward) != list(reverse)
    assert set(forward) == set(reverse)
    pilot = _draw()
    first = select_gold_items(
        pilot=pilot, entries_by_sha256=forward, seed=_PILOT_SEED
    )
    second = select_gold_items(
        pilot=pilot, entries_by_sha256=reverse, seed=_PILOT_SEED
    )
    assert [item.sha256 for item in first] == [item.sha256 for item in second]
    assert [item.kind for item in first] == [item.kind for item in second]
