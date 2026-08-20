"""DESCQUAL-2 cost-and-instrument pilot: draw, packets, gold QC (HITL-03)."""

from __future__ import annotations

import ast
import inspect
import itertools
import json
import math
import random
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.eval_harness import pilot_draw as pilot_draw_mod
from scripts.eval_harness.audit_sampling import allocate, draw, project_strata_image_counts
from scripts.eval_harness.manifest import (
    ConfirmationSource,
    FactKind,
    FactPolarity,
    ReferenceFact,
)
from scripts.eval_harness.pilot_draw import (
    ANNOTATION_PACKET_ROW_KEYS,
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
        assert set(packet) == _LICENSED_PACKET_ROW_KEYS
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
_LICENSED_PACKET_ROW_KEYS = frozenset(
    {
        "sha256",
        "media_id",
        "stratum",
        "inclusion_probability",
        "annotation_batch",
        "source_path",
        "annotator_slots",
        "reference_facts",
    }
)


def _icc_groups_of_size(k: int) -> tuple[tuple[float, ...], ...]:
    # Distinct cluster means + within-group spread so ICC is not 0/1/a data leaf.
    return tuple(
        (float(10 * i), float(10 * i + 1), float(10 * i + 3)) for i in range(k)
    )


_ICC_PROBE_GROUPS: tuple[tuple[tuple[float, ...], ...], ...] = (
    ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 1.0)),
    ((2.0, 3.0, 4.0), (8.0, 9.0, 10.0), (0.0, 1.0, 2.0), (20.0, 21.0, 22.0)),
    _icc_groups_of_size(5),
    _icc_groups_of_size(8),
    _icc_groups_of_size(16),
    _icc_groups_of_size(32),
    _icc_groups_of_size(64),
)
_GROUPS_PARAM_NAMES = frozenset({"groups", "clusters", "cluster", "icc_groups", "ys"})
_UNPROBEABLE = object()
_MISSING = object()


def _owned_callables(module: object = pilot_draw_mod) -> list[tuple[str, object]]:
    return [
        (name, obj)
        for name, obj in inspect.getmembers(module)
        if callable(obj) and inspect.getmodule(obj) is module
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


def _name_carries_design_stat_token(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    return any(token in lowered for token in _DESIGN_STAT_KEYS)


def _defined_symbol_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    if isinstance(tree, ast.Module):
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.append(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.append(alias.asname or alias.name)
    return names


def _one_way_icc(groups: Sequence[Sequence[float]]) -> float:
    # Oracle for BR-48: the one-way ANOVA ICC this pilot is not licensed to produce.
    flat = [x for group in groups for x in group]
    n = len(flat)
    k = len(groups)
    grand = sum(flat) / n
    msb = sum(len(group) * (sum(group) / len(group) - grand) ** 2 for group in groups) / (
        k - 1
    )
    msw = sum(
        (value - sum(group) / len(group)) ** 2 for group in groups for value in group
    ) / (n - k)
    mean_size = n / k
    return (msb - msw) / (msb + (mean_size - 1) * msw)


def _numeric_leaves(value: object, *, depth: int = 0) -> list[float]:
    if depth > 4 or value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, Mapping):
        leaves: list[float] = []
        for item in value.values():
            leaves.extend(_numeric_leaves(item, depth=depth + 1))
        return leaves
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        leaves = []
        for item in value:
            leaves.extend(_numeric_leaves(item, depth=depth + 1))
        return leaves
    leaves = []
    for attr in _DESIGN_STAT_KEYS:
        if hasattr(value, attr):
            leaves.extend(_numeric_leaves(getattr(value, attr), depth=depth + 1))
    return leaves


def _required_params(fn: object) -> list[inspect.Parameter] | None:
    try:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return [
        param
        for param in sig.parameters.values()
        if param.default is param.empty
        and param.kind
        in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
        and param.name not in {"self", "cls"}
    ]


def _annotation_str(annotation: object) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation.strip()
    return getattr(annotation, "__name__", str(annotation)).strip()


def _probe_fixture_map() -> dict[str, object]:
    payload = _payload()
    entries_by_sha256 = _entries_by_sha256(payload)
    return {
        "pilot": _draw(),
        "entries_by_sha256": entries_by_sha256,
        "selection_manifest_path": _FIR12_MANIFEST,
        "n": _PILOT_N,
        "seed": _PILOT_SEED,
        "gold_n": 3,
        "batch_id": "pilot-2026-08-20",
        "kind": GoldKind.RANDOM,
        "rng": random.Random(_PILOT_SEED),
        "candidates": sorted(entries_by_sha256)[:8],
        "used": set(),
        "entries": payload["entries"],
        "entry": next(iter(entries_by_sha256.values())),
        "name": "n",
        "value": _PILOT_N,
        "raw": StratumName.E_CLEAN.value,
        "label": "stratum",
    }


def _typed_fixture(
    annotation: str, fixtures: Mapping[str, object], groups: object
) -> object:
    key = annotation.replace(" ", "")
    if key == "str":
        return fixtures["batch_id"]
    if key == "int":
        return fixtures["n"]
    if key in {"Path", "str|Path", "Path|str"}:
        return fixtures["selection_manifest_path"]
    if key == "PilotDraw":
        return fixtures["pilot"]
    if key == "GoldKind":
        return fixtures["kind"]
    if "Random" in key:
        return fixtures["rng"]
    if key.startswith("set["):
        return set()
    if key in {"Sequence[str]", "list[str]", "tuple[str,...]", "tuple[str, ...]"}:
        return fixtures["candidates"]
    if "Mapping" in key:
        return fixtures["entries_by_sha256"]
    if key == "object":
        return groups
    return _MISSING


def _place_arg(
    param: inspect.Parameter, value: object
) -> tuple[tuple[object, ...], dict[str, object]]:
    if param.kind is param.KEYWORD_ONLY:
        return (), {param.name: value}
    return (value,), {}


def _unknown_param_fillers(
    groups: Sequence[Sequence[float]],
) -> tuple[object, ...]:
    as_tuples = tuple(tuple(group) for group in groups)
    k = len(as_tuples)
    n = sum(len(group) for group in as_tuples)
    return (
        as_tuples,
        None,
        1.0,
        True,
        (),
        tuple(1.0 for _ in range(k)),
        tuple(1.0 for _ in range(n)),
        "probe",
    )


def _param_candidate_values(
    param: inspect.Parameter,
    groups: Sequence[Sequence[float]],
    fixtures: Mapping[str, object],
) -> list[object]:
    as_tuples = tuple(tuple(group) for group in groups)
    if param.name in _GROUPS_PARAM_NAMES:
        return [as_tuples]
    if param.name in fixtures:
        bound = fixtures[param.name]
        return [set(bound) if isinstance(bound, set) else bound]
    typed = _typed_fixture(_annotation_str(param.annotation), fixtures, as_tuples)
    if typed is not _MISSING:
        return [typed]
    return list(_unknown_param_fillers(as_tuples))


def _iter_bindings(
    fn: object,
    groups: Sequence[Sequence[float]],
    fixtures: Mapping[str, object],
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    required = _required_params(fn)
    if required is None:
        return []
    as_tuples = tuple(tuple(group) for group in groups)
    if not required:
        return [((), {})]
    if len(required) == 1:
        return [_place_arg(required[0], as_tuples)]
    value_lists = [
        _param_candidate_values(param, as_tuples, fixtures) for param in required
    ]
    bindings: list[tuple[tuple[object, ...], dict[str, object]]] = []
    for combo in itertools.product(*value_lists):
        args: list[object] = []
        kwargs: dict[str, object] = {}
        for param, value in zip(required, combo, strict=True):
            extra_args, extra_kwargs = _place_arg(param, value)
            args.extend(extra_args)
            kwargs.update(extra_kwargs)
        bindings.append((tuple(args), kwargs))
    return bindings


def _matches_one_way_icc(got: object, groups: Sequence[Sequence[float]]) -> bool:
    if got is _UNPROBEABLE:
        return False
    want = _one_way_icc(groups)
    return any(
        math.isclose(number, want, rel_tol=1e-9, abs_tol=1e-12)
        for number in _numeric_leaves(got)
    )


def _returns_one_way_icc(
    fn: object, fixtures: Mapping[str, object] | None = None
) -> bool:
    # BR-51: a raise on one fixture (min-n) is not "not an estimator"; try the rest.
    probe_fixtures = fixtures if fixtures is not None else _probe_fixture_map()
    for groups in _ICC_PROBE_GROUPS:
        for args, kwargs in _iter_bindings(fn, groups, probe_fixtures):
            try:
                got = fn(*args, **kwargs)  # type: ignore[operator]
            except Exception:
                continue
            if _matches_one_way_icc(got, groups):
                return True
    return False


def _callable_is_unprobeable(fn: object) -> bool:
    return _required_params(fn) is None


def _reliability_estimator_violations(
    module: object = pilot_draw_mod,
) -> tuple[list[str], list[str]]:
    fixtures = _probe_fixture_map()
    icc_offenders: list[str] = []
    unprobeable: list[str] = []
    for name, obj in _owned_callables(module):
        if inspect.isclass(obj):
            continue
        if _callable_is_unprobeable(obj):
            unprobeable.append(name)
            continue
        if _returns_one_way_icc(obj, fixtures):
            icc_offenders.append(name)
    tree = ast.parse(Path(module.__file__).read_text())  # type: ignore[union-attr]
    for name, fn in _isolated_functions(tree):
        if _callable_is_unprobeable(fn):
            unprobeable.append(f"isolated:{name}")
            continue
        if _returns_one_way_icc(fn, fixtures):
            icc_offenders.append(f"isolated:{name}")
    return icc_offenders, unprobeable


def _assert_no_reliability_estimator(module: object = pilot_draw_mod) -> None:
    icc_offenders, unprobeable = _reliability_estimator_violations(module)
    assert unprobeable == [], (
        "module-level callable(s) have no inspectable signature, so the ICC "
        "probe cannot call them (AUDIT-11, TEST-15): "
        f"{unprobeable}"
    )
    assert icc_offenders == [], (
        "pilot module callables returned a one-way ICC estimate, which the "
        "cost-and-instrument pilot is not licensed to produce (BR-17, AUDIT-11): "
        f"{icc_offenders}"
    )


@contextmanager
def _inject_module_callable(source: str, name: str):
    if hasattr(pilot_draw_mod, name):
        raise RuntimeError(f"{name} already exists on pilot_draw")
    exec(source, pilot_draw_mod.__dict__)
    try:
        injected = getattr(pilot_draw_mod, name, None)
        if not callable(injected):
            raise RuntimeError(f"exec did not define callable {name}")
        yield injected
    finally:
        if hasattr(pilot_draw_mod, name):
            delattr(pilot_draw_mod, name)


def _isolated_functions(tree: ast.AST) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace: dict[str, object] = {}
            try:
                exec(compile(module, "<pilot-icc-probe>", "exec"), namespace)
            except Exception:
                continue
            fn = namespace.get(node.name)
            if callable(fn):
                found.append((node.name, fn))
            continue
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda)):
            continue
        labels = [target.id for target in node.targets if isinstance(target, ast.Name)]
        expr = ast.Expression(body=node.value)
        ast.fix_missing_locations(expr)
        try:
            fn = eval(compile(expr, "<pilot-icc-lambda>", "eval"), {})
        except Exception:
            continue
        if callable(fn):
            found.append((labels[0] if labels else "<lambda>", fn))
    return found


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
    tree = ast.parse(Path(pilot_draw_mod.__file__).read_text())
    named = [
        name
        for name in _defined_symbol_names(tree)
        if _name_carries_design_stat_token(name)
    ]
    assert named == []
    owned_named = [
        name
        for name, _obj in _owned_callables()
        if _name_carries_design_stat_token(name)
    ]
    assert owned_named == []


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
    for row in packets:
        assert set(row) == _LICENSED_PACKET_ROW_KEYS

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


def test_annotation_packet_row_schema_is_exact():
    packets = emit_annotation_packet(
        pilot=_draw(),
        entries_by_sha256=_entries_by_sha256(),
        batch_id="pilot-2026-08-20",
    )
    assert packets
    for packet in packets:
        assert set(packet) == _LICENSED_PACKET_ROW_KEYS
    assert ANNOTATION_PACKET_ROW_KEYS == _LICENSED_PACKET_ROW_KEYS
    assert set(packets[0]) == ANNOTATION_PACKET_ROW_KEYS


def test_no_module_callable_returns_one_way_icc():
    _assert_no_reliability_estimator()


_ONE_WAY_ICC_BODY = """\
    flat = [x for group in groups for x in group]
    n = len(flat)
    k = len(groups)
    grand = sum(flat) / n
    msb = sum(len(group) * (sum(group) / len(group) - grand) ** 2 for group in groups) / (
        k - 1
    )
    msw = sum(
        (value - sum(group) / len(group)) ** 2 for group in groups for value in group
    ) / (n - k)
    mean_size = n / k
    return (msb - msw) / (msb + (mean_size - 1) * msw)
"""

_COORDINATOR_ICC_EXTRA_ARG = f"""\
def _agreement_ratio2(groups, weights):
{_ONE_WAY_ICC_BODY}
"""

_NEUTRAL_EXTRA_ARG_ICC = f"""\
def _item_overlap(xs, extra):
    groups = xs
{_ONE_WAY_ICC_BODY}
"""

_MIN_N_ICC_TEMPLATE = f"""\
def __NAME__(groups):
    if len(groups) < 5:
        raise ValueError("need at least five groups")
{_ONE_WAY_ICC_BODY}
"""

_ORDINARY_HELPER_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "annotated_kwonly_helper",
        """\
def annotated_kwonly_helper(*, left: str, right: str) -> str:
    return f"{left}:{right}"
""",
    ),
    (
        "unannotated_kwonly_helper",
        """\
def unannotated_kwonly_helper(*, left, right):
    return f"{left}:{right}"
""",
    ),
    (
        "annotated_positional_helper",
        """\
def annotated_positional_helper(left: str, right: str) -> str:
    return f"{left}:{right}"
""",
    ),
    (
        "unannotated_positional_helper",
        """\
def unannotated_positional_helper(left, right):
    return f"{left}:{right}"
""",
    ),
    (
        "_join_labels",
        """\
def _join_labels(left: str, right: str) -> str:
    return f"{left}:{right}"
""",
    ),
)


def test_estimator_with_extra_required_parameter_is_rejected():
    with _inject_module_callable(_COORDINATOR_ICC_EXTRA_ARG, "_agreement_ratio2"):
        icc_offenders, unprobeable = _reliability_estimator_violations()
        assert "_agreement_ratio2" not in unprobeable
        assert "_agreement_ratio2" in icc_offenders


def test_estimator_with_neutral_extra_parameter_names_is_rejected():
    with _inject_module_callable(_NEUTRAL_EXTRA_ARG_ICC, "_item_overlap"):
        icc_offenders, unprobeable = _reliability_estimator_violations()
        assert "_item_overlap" not in unprobeable
        assert "_item_overlap" in icc_offenders


@pytest.mark.parametrize(
    "name",
    ["_cluster_agreement", "_within_share"],
)
def test_min_n_guarded_icc_estimator_is_rejected(name: str):
    source = _MIN_N_ICC_TEMPLATE.replace("__NAME__", name)
    with _inject_module_callable(source, name):
        icc_offenders, unprobeable = _reliability_estimator_violations()
        assert name not in unprobeable
        assert name in icc_offenders


@pytest.mark.parametrize(
    ("name", "source"),
    _ORDINARY_HELPER_SOURCES,
    ids=[name for name, _source in _ORDINARY_HELPER_SOURCES],
)
def test_ordinary_helper_is_not_a_reliability_estimator(name: str, source: str):
    with _inject_module_callable(source, name):
        icc_offenders, unprobeable = _reliability_estimator_violations()
        assert name not in unprobeable
        assert name not in icc_offenders
        _assert_no_reliability_estimator()


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
