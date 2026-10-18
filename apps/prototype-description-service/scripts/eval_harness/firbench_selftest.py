"""FIRBENCH-1 S9 simulator: synthetic packets through the real S1 frame, S2 records and S3 scoring.

The suites check that the bench detects a designed effect and stays quiet under a null, with the
PSU as the independent unit [EXP-12, EXP-13, EXP-23, AUDIT-11]. Every verdict comes from S3
``finish_outcomes``, ``paired_cluster_bootstrap`` and ``decide`` run on a synthetic decision that the
real S0 validators seal. A synthetic decision copies the real manifest's policy values and replaces
only the frame, template and ratification entries with labelled synthetic ones. The real manifest is
read, never written. Nothing here reads real pixels, runs a model, or ratifies anything.

Every numeric generator, design and acceptance value lives in ``firbench_sim_v1.json``. The loader
checks the fixture against the decision manifest and refuses any policy mismatch. Structural enum
orders below are not policy.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from scripts.bench.score_report import bootstrap_paired_delta
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff
from scripts.eval_harness import firbench_legs as fl
from scripts.eval_harness import firbench_score as fs

SIMULATOR_SCHEMA = "firbench-simulator/v1"
ACCEPTANCE_SCHEMA = "firbench-acceptance/v1"
SUITES = ("null", "selection", "coverage", "power", "noninferiority", "mde", "floor", "stage")
_REPO_ROOT = Path(__file__).resolve().parents[4]

_LEGS = (fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface)
_IN_HOUSE = (fc.LegKind.sface, fc.LegKind.auraface)
_CORRECT, _MISSED, _REJECTED, _WRONG = 0, 1, 2, 3
_LEG_BIT_SHIFT = {fc.LegKind.sface: 2, fc.LegKind.auraface: 1, fc.LegKind.insightface: 0}
_SUITE_SCENARIO = {
    "null": "null",
    "selection": "selection_control",
    "coverage": "null",
    "power": "h1_power_global",
    "noninferiority": "h1_power_global",
    "mde": "null",
    "floor": "null",
    "stage": "stage_planting",
}
_TOP_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "layout",
        "seeds",
        "policy_mirror",
        "generator",
        "laws",
        "designs",
        "suite_designs",
        "acceptance",
        "synthetic_decision",
    }
)
_SEED_KEYS = frozenset(
    {
        "master_seed",
        "master_seed_derivation",
        "suite_registry",
        "icc_registry_percent",
        "suite_seed_derivation",
        "replicate_seed_derivation",
    }
)
_MIRROR_KEYS = frozenset(
    {
        "note",
        "p_d",
        "planning_icc",
        "planning_icc_sensitivity",
        "power",
        "alpha_family",
        "h1_margin",
        "h2_margin",
        "fpir_target",
        "min_n_independent",
        "cell_floor_n_independent",
        "n_boot",
        "bootstrap_seed",
        "alternative_delta_sizing_only",
    }
)
_DESIGN_REQUIRED = frozenset({"size_counts", "raw_n", "n_psu", "sum_squared_sizes", "target_n_eff", "cells"})
_DESIGN_OPTIONAL = frozenset({"expected_cells"})
_GENERATOR_KEYS = frozenset(
    {
        "pattern_order",
        "law_denominator",
        "miss_bit_names",
        "psu_random_effect",
        "faces_given_psu",
        "miss_class_law",
        "miss_class_note",
        "operating_threshold_tau",
        "score_margin",
        "second_score_gap",
        "score_note",
        "selection_tie_rule",
        "selection_note",
        "background_units_total",
        "background_distribution",
        "nonmated_gt_faces",
        "fold_protocol",
        "gallery",
        "pair_cell_labels",
        "stage_planting",
        "attribution_arms",
        "attribution_note",
        "legs",
        "frame_id",
        "frame_note",
    }
)
_ACCEPTANCE_KEYS = frozenset(
    {
        "full_replicates",
        "gated_icc",
        "sensitivity_icc",
        "negative_control_icc",
        "mc_se",
        "null_superior_max_rate",
        "null_boundary_max_rate",
        "selection_min_exclusive_rate",
        "coverage_min_rate",
        "coverage_max_rate",
        "power_min_rate",
        "h2_a_min_rate",
        "h2_b_max_rate",
        "h2_c_max_non_inferior_count",
        "mde_refusal_required_fraction",
        "mde_non_inferior_max_count",
        "bound_200",
        "wrong_identity_max_abs_diff",
        "cell_clear_clear_max_rate",
        "cell_clear_mask_min_rate",
        "cell_clear_mask_rule_note",
    }
)


def _fail(message: str) -> fc.FrameContractError:
    return fc.FrameContractError(f"firbench simulator: {message}")


def _strict(payload: object, required: frozenset[str], where: str, optional: frozenset[str] = frozenset()) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise _fail(f"{where} must be an object")
    unknown = sorted(set(payload) - required - optional)
    if unknown:
        raise _fail(f"{where} has unknown keys {unknown}")
    missing = sorted(required - set(payload))
    if missing:
        raise _fail(f"{where} is missing keys {missing}")
    return payload


def _exact(value: object) -> Fraction:
    """Exact rational from a decimal literal (floats go through their shortest repr)."""
    return Fraction(str(value))


@dataclass(frozen=True)
class SimulationParams:
    """Real decision manifest, validated fixture, selected suite and simulated planning ICC."""

    decision: fc.DecisionManifest
    fixture: Mapping[str, Any]
    suite: str = "null"
    icc: float = 0.10


# --- fixture loading and validation ----------------------------------------------------


def _check_policy(mirror: Mapping[str, Any], decision: fc.DecisionManifest) -> None:
    h1 = next(h for h in decision.hypotheses if h.kind is fc.HypothesisKind.superiority)
    h2 = next(h for h in decision.hypotheses if h.kind is fc.HypothesisKind.non_inferiority)
    actual = {
        "p_d": decision.p_d,
        "planning_icc": decision.planning_icc,
        "power": decision.power,
        "alpha_family": decision.alpha_family,
        "h1_margin": h1.margin,
        "h2_margin": h2.margin,
        "fpir_target": decision.primary.fpir_target,
        "min_n_independent": decision.min_n_independent,
        "cell_floor_n_independent": decision.cell_floor_n_independent,
        "n_boot": decision.interval.n_boot,
        "bootstrap_seed": decision.interval.seed,
    }
    for name, value in actual.items():
        if mirror[name] != value:
            raise _fail(f"fixture policy {name}={mirror[name]!r} differs from the decision manifest {value!r}")


def _design_key_parts(key: str) -> tuple[str, str, str | None]:
    parts = key.split("/")
    if len(parts) not in (2, 3):
        raise _fail(f"design key {key!r} must be family/icc or family/icc/sub")
    return parts[0], parts[1], (parts[2] if len(parts) == 3 else None)


def _design_definition(fixture: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    family, icc_key, sub = _design_key_parts(key)
    try:
        block = fixture["designs"][family][icc_key]
        if sub is not None:
            block = block[sub]
    except (KeyError, TypeError) as exc:
        raise _fail(f"design {key!r} is not declared") from exc
    return _strict(block, _DESIGN_REQUIRED, f"designs.{key}", _DESIGN_OPTIONAL)


def _sorted_sizes(size_counts: Mapping[str, int]) -> list[int]:
    sizes: list[int] = []
    for size in sorted(size_counts, key=int):
        if int(size) < 1 or int(size_counts[size]) < 1:
            raise _fail("size counts must be positive")
        sizes.extend([int(size)] * int(size_counts[size]))
    return sizes


def _sizing(sizes: Sequence[int], icc: Fraction) -> dict[str, Any]:
    raw = sum(sizes)
    sum_sq = sum(m * m for m in sizes)
    mean = Fraction(sum_sq, raw)
    deff = 1 + (mean - 1) * icc
    n_eff = Fraction(raw) / deff
    counts = Counter(sizes)
    return {
        "raw_n": raw,
        "n_psu": len(sizes),
        "size_counts": {str(size): counts[size] for size in sorted(counts)},
        "sum_squared_sizes": sum_sq,
        "size_weighted_mean": float(mean),
        "deff": float(deff),
        "attained_n_eff": float(n_eff),
        "attained_n_eff_exact": f"{n_eff.numerator}/{n_eff.denominator}",
        "_n_eff_exact": n_eff,
    }


def _public_sizing(sizing: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in sizing.items() if not key.startswith("_")}


def _allocate_cells(sizes: Sequence[int]) -> list[str]:
    """Whole PSUs over the ascending size order: even index -> clear_mask, odd -> clear_clear."""
    return ["clear_mask" if index % 2 == 0 else "clear_clear" for index in range(len(sizes))]


def _check_design(fixture: Mapping[str, Any], key: str) -> None:
    definition = _design_definition(fixture, key)
    _, icc_key, _ = _design_key_parts(key)
    sizes = _sorted_sizes(definition["size_counts"])
    sizing = _sizing(sizes, _exact(icc_key))
    if sizing["raw_n"] != definition["raw_n"] or sizing["n_psu"] != definition["n_psu"]:
        raise _fail(f"design {key} raw_n or n_psu differs from its size counts")
    if sizing["sum_squared_sizes"] != definition["sum_squared_sizes"]:
        raise _fail(f"design {key} sum of squared sizes differs from its size counts")
    target = definition["target_n_eff"]
    if target is not None and sizing["_n_eff_exact"] != Fraction(target):
        raise _fail(f"design {key} attains n_eff {sizing['attained_n_eff']}, not the declared {target}")
    if definition["cells"] == "alternate_sorted":
        cells: dict[str, list[int]] = {"clear_mask": [], "clear_clear": []}
        for size, label in zip(sizes, _allocate_cells(sizes), strict=True):
            cells[label].append(size)
        expected = _strict(
            {name: value for name, value in definition.get("expected_cells", {}).items()},
            frozenset(cells),
            f"designs.{key}.expected_cells",
        )
        for label, declared in expected.items():
            observed = dict(Counter(cells[label]))
            if observed != {int(size): int(count) for size, count in declared.items()}:
                raise _fail(f"design {key} cell {label} differs from the frozen allocation")
    elif definition["cells"] != "none":
        raise _fail(f"design {key} has an unknown cell rule {definition['cells']!r}")


def _validate_fixture(fixture: Mapping[str, Any], decision: fc.DecisionManifest) -> None:
    _strict(fixture, _TOP_KEYS, "fixture")
    if fixture["schema"] != SIMULATOR_SCHEMA:
        raise _fail(f"fixture schema must be {SIMULATOR_SCHEMA}")
    _strict(fixture["seeds"], _SEED_KEYS, "seeds")
    _strict(fixture["policy_mirror"], _MIRROR_KEYS, "policy_mirror")
    _check_policy(fixture["policy_mirror"], decision)
    _strict(fixture["generator"], _GENERATOR_KEYS, "generator")
    _strict(fixture["acceptance"], _ACCEPTANCE_KEYS, "acceptance")
    if int(fixture["acceptance"]["bound_200"]["replicates"]) != 200:
        raise _fail("bound_200 must use 200 replicates")
    laws = fixture["laws"]
    denominator = int(laws["denominator"])
    for name in ("null", "h1_power", "h2_boundary", "selection_control"):
        law = laws[name]
        if len(law) != 8 or sum(law) != denominator or min(law) < 0:
            raise _fail(f"law {name} must have eight non-negative weights summing to {denominator}")
        for leg, declared in zip(_LEGS, laws["theoretical_fnir"][name], strict=True):
            if _law_fnir(law, leg, denominator) != _exact(declared):
                raise _fail(f"theoretical FNIR of {name} for {leg.value} differs from its law")
    control_marginal = [0] * 8
    planted_marginal = [0] * 8
    for control_pattern, planted_pattern, weight in laws["h1_power_joint_coupling"]:
        control_marginal[control_pattern] += weight
        planted_marginal[planted_pattern] += weight
    if control_marginal != laws["null"] or planted_marginal != laws["h1_power"]:
        raise _fail("h1_power_joint_coupling marginals must equal the null and h1_power laws")
    for family, block in fixture["designs"].items():
        if family == "cell_allocation_rule":
            continue
        for icc_key, value in block.items():
            if "size_counts" in value:
                _check_design(fixture, f"{family}/{icc_key}")
            else:
                for sub in value:
                    _check_design(fixture, f"{family}/{icc_key}/{sub}")
    for suite in SUITES:
        if suite not in fixture["suite_designs"]:
            raise _fail(f"suite_designs lacks {suite}")


def load_params(path: Path | str, *, decision: fc.DecisionManifest) -> SimulationParams:
    """Load the committed simulator fixture. Refuse it unless every value matches the decision manifest."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _fail(f"cannot read fixture {target}: {exc}") from exc
    try:
        payload = json.loads(text, object_pairs_hook=fc._reject_duplicate_keys, parse_constant=fc._reject_non_finite)
    except json.JSONDecodeError as exc:
        raise _fail(f"fixture {target} is not valid JSON: {exc}") from exc
    _validate_fixture(payload, decision)
    icc = float(payload["policy_mirror"]["planning_icc"])
    return SimulationParams(decision=decision, fixture=payload, suite="null", icc=icc)


def _suite_iccs(fixture: Mapping[str, Any], suite: str) -> tuple[float, ...]:
    block = fixture["suite_designs"][suite]
    return tuple(float(key) for key in block if not key.startswith("branch_b"))


def _as_suite(params: SimulationParams, suite: str) -> SimulationParams:
    """Revalidate the parameters and select the suite. Every public suite calls this first."""
    if not isinstance(params, SimulationParams):
        raise _fail("params must be SimulationParams")
    _validate_fixture(params.fixture, params.decision)
    if suite not in SUITES:
        raise _fail(f"unknown suite {suite!r}")
    if not any(params.icc == value for value in _suite_iccs(params.fixture, suite)):
        raise _fail(f"suite {suite} does not support icc {params.icc}")
    return dataclasses.replace(params, suite=suite)


def _check_run(replicates: int, seed: int) -> None:
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise _fail("replicates must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise _fail("seed must be a non-negative integer")


def _suite_seed(fixture: Mapping[str, Any], master: int, suite: str, icc: float) -> int:
    registry = fixture["seeds"]["suite_registry"]
    icc_registry = {float(k): int(v) for k, v in fixture["seeds"]["icc_registry_percent"].items()}
    sequence = np.random.SeedSequence(master, spawn_key=(int(registry[suite]), icc_registry[icc]))
    return int(sequence.generate_state(1, dtype=np.uint64)[0])


def _replicate_seed(suite_seed: int, replicate: int) -> int:
    return int(np.random.SeedSequence(suite_seed, spawn_key=(replicate,)).generate_state(1, dtype=np.uint64)[0])


# --- exact theory oracles ---------------------------------------------------------------


def _law_fnir(weights: Sequence[int], leg: fc.LegKind, denominator: int) -> Fraction:
    shift = _LEG_BIT_SHIFT[leg]
    return Fraction(sum(w for x, w in enumerate(weights) if (x >> shift) & 1), denominator)


def _law_discordance(weights: Sequence[int], left: fc.LegKind, right: fc.LegKind, denominator: int) -> Fraction:
    a, b = _LEG_BIT_SHIFT[left], _LEG_BIT_SHIFT[right]
    return Fraction(sum(w for x, w in enumerate(weights) if ((x >> a) & 1) != ((x >> b) & 1)), denominator)


def law_theory(params: SimulationParams, name: str) -> dict[str, Fraction]:
    """Exact FNIR per leg and pairwise discordance for a named law (Fraction oracles)."""
    weights = params.fixture["laws"][name]
    denominator = int(params.fixture["laws"]["denominator"])
    out = {f"fnir_{leg.value}": _law_fnir(weights, leg, denominator) for leg in _LEGS}
    out["discordance_sface_auraface"] = _law_discordance(weights, _LEGS[0], _LEGS[1], denominator)
    out["discordance_auraface_insightface"] = _law_discordance(weights, _LEGS[1], _LEGS[2], denominator)
    out["discordance_sface_insightface"] = _law_discordance(weights, _LEGS[0], _LEGS[2], denominator)
    return out


def exact_icc_oracle(params: SimulationParams, name: str, icc: Fraction) -> Fraction:
    """Exact Dirichlet ICC of each leg and each linear paired contrast. All equal 1/(k+1) = icc.

    With q the category law and k = 1/ICC - 1, the PSU-level variance of a linear statistic sum_c pi_c g_c is
    (sum_c q_c g_c^2 - (sum_c q_c g_c)^2)/(k+1). The per-face variance has the same bracket, so the ICC is 1/(k+1).
    """
    weights = params.fixture["laws"][name]
    denominator = int(params.fixture["laws"]["denominator"])
    q = [Fraction(w, denominator) for w in weights]
    k_plus_one = 1 / icc
    ratios: list[Fraction] = []

    def add(g: Callable[[int], int]) -> None:
        mean = sum(q[x] * g(x) for x in range(8))
        second = sum(q[x] * g(x) * g(x) for x in range(8))
        bracket = second - mean * mean
        if bracket == 0:
            raise _fail(f"law {name} has no variance for an oracle ratio")
        ratios.append((bracket / k_plus_one) / bracket)

    for leg in _LEGS:
        shift = _LEG_BIT_SHIFT[leg]
        add(lambda x, shift=shift: (x >> shift) & 1)
    for left, right in ((_LEGS[0], _LEGS[1]), (_LEGS[1], _LEGS[2])):
        a, b = _LEG_BIT_SHIFT[left], _LEG_BIT_SHIFT[right]
        add(lambda x, a=a, b=b: ((x >> a) & 1) - ((x >> b) & 1))
    if any(ratio != icc for ratio in ratios):
        raise _fail("Dirichlet ICC oracle does not equal the declared ICC")
    return icc


def design_sizing(params: SimulationParams, key: str) -> dict[str, Any]:
    """Public sizing of a declared design (exact arithmetic, no outcomes)."""
    definition = _design_definition(params.fixture, key)
    _, icc_key, _ = _design_key_parts(key)
    return _public_sizing(_sizing(_sorted_sizes(definition["size_counts"]), _exact(icc_key)))


# --- designs (frame structure, fixed before any outcome) ---------------------------------


@dataclass(frozen=True)
class _FaceInfo:
    face_id: str
    image_id: str
    psu_id: str
    identity: str
    fold: int
    fold_role: fc.FoldRole
    cell: tuple[str, str]
    gallery_sha: str


@dataclass(frozen=True)
class _Design:
    key: str
    icc: float
    frame: ff.Frame
    faces: tuple[_FaceInfo, ...]
    identities: tuple[str, ...]
    background: tuple[tuple[str, str, str], ...]  # (record id, image id, psu id)
    psu_ids: tuple[str, ...]
    psu_cell: Mapping[str, str]
    faces_by_psu: Mapping[str, tuple[int, ...]]
    sizing_mated: Mapping[str, Any]
    sizing_image: Mapping[str, Any]
    sizing_nonmated: Mapping[str, Any]
    cell_sizing: Mapping[str, Any]
    frame_sha: str
    template_sha: str
    tau: float
    margin: float
    gap: float
    leg_keys: Mapping[tuple[fc.LegKind, fc.Arm], str]
    alignment: Mapping[fc.LegKind, fc.AlignmentMode]


def _image(key: str, image_id: str, psu_id: str) -> ff.ImageUnit:
    digest = hashlib.sha256(f"{SIMULATOR_SCHEMA}:{key}:{image_id}".encode("utf-8")).hexdigest()
    return ff.ImageUnit(
        image_id=image_id,
        sha256=digest,
        sampling_arm=fc.SamplingArm.probability,
        inclusion_probability=1.0,
        session_id=psu_id,
    )


def _leg_config(fixture: Mapping[str, Any]) -> tuple[dict, dict]:
    keys: dict[tuple[fc.LegKind, fc.Arm], str] = {}
    alignment: dict[fc.LegKind, fc.AlignmentMode] = {}
    arms = [fc.Arm.native] + [fc.Arm(name) for name in fixture["generator"]["attribution_arms"]]
    for leg in _LEGS:
        spec = fixture["generator"]["legs"][leg.value]
        alignment[leg] = fc.AlignmentMode(spec["alignment_mode"])
        for arm in arms:
            keys[(leg, arm)] = fc.LegId(
                kind=leg,
                arm=arm,
                space_fingerprint=spec["space_fingerprint"],
                opencv_version=spec["opencv_version"],
                ort_version=spec["ort_version"],
            ).key()
    return keys, alignment


def _public_design(design: _Design) -> dict[str, Any]:
    """Stable sizing wire for each design branch; flat sizing fields alias ``mated``.

    ``mated`` counts GT faces, ``image`` includes their images plus known empty
    images, and ``nonmated`` counts those empty-image background source units,
    not nonmated GT faces. Each uses its own PSU sizes and effective sample size;
    ``cells`` carries each cell's mated sizing and independent-PSU floor status.
    """
    mated = design.sizing_mated
    return {
        "key": design.key,
        "icc": design.icc,
        "raw_n": mated["raw_n"],
        "n_psu": mated["n_psu"],
        "size_counts": mated["size_counts"],
        "sum_squared_sizes": mated["sum_squared_sizes"],
        "size_weighted_mean": mated["size_weighted_mean"],
        "deff": mated["deff"],
        "attained_n_eff": mated["attained_n_eff"],
        "attained_n_eff_exact": mated["attained_n_eff_exact"],
        "mated": _public_sizing(mated),
        "image": design.sizing_image,
        "nonmated": design.sizing_nonmated,
        "cells": design.cell_sizing,
        "frame_sha256": design.frame_sha,
        "template_sha256": design.template_sha,
        "background_units": len(design.background),
    }


def _build_design(params: SimulationParams, key: str) -> _Design:
    fixture = params.fixture
    definition = _design_definition(fixture, key)
    _, icc_key, _ = _design_key_parts(key)
    icc = float(icc_key)
    icc_exact = _exact(icc_key)
    sizes = _sorted_sizes(definition["size_counts"])
    cells_rule = definition["cells"]
    cell_names = _allocate_cells(sizes) if cells_rule == "alternate_sorted" else ["clear_clear"] * len(sizes)
    slug = key.replace("/", "-").replace(".", "")
    labels = fixture["generator"]["pair_cell_labels"]
    label_of = {name: tuple(labels[name]) for name in ("clear_mask", "clear_clear", "background")}
    psu_ids = [f"psu-{slug}-{index:03d}" for index in range(len(sizes))]
    psu_cell = dict(zip(psu_ids, cell_names, strict=True))
    images: list[ff.ImageUnit] = []
    faces: list[ff.GtFace] = []
    for index, (psu_id, size) in enumerate(zip(psu_ids, sizes, strict=True)):
        for j in range(size):
            image_id = f"img-{slug}-{index:03d}-{j:02d}"
            images.append(_image(key, image_id, psu_id))
            faces.append(
                ff.GtFace(
                    face_id=f"gt-{slug}-{index:03d}-{j:02d}",
                    image_id=image_id,
                    box=(0.0, 0.0, 1.0, 1.0),
                    identity_status=fc.IdentityStatus.named,
                    identity_id=f"id-{slug}-{index:03d}-{j:02d}",
                )
            )
    background_n = int(fixture["generator"]["background_units_total"])
    background: list[tuple[str, str, str]] = []
    for b in range(background_n):
        psu_id = psu_ids[b % len(psu_ids)]
        image_id = f"bg-{slug}-{b:04d}"
        images.append(_image(key, image_id, psu_id))
        background.append((f"background:{image_id}", image_id, psu_id))
    enrolled = frozenset(face.identity_id for face in faces if face.identity_id is not None)
    k = int(params.decision.fold_protocol.k)
    fold_seed = int(params.decision.fold_protocol.seed)
    gallery = {
        fold: hashlib.sha256(
            json.dumps(
                {"schema": SIMULATOR_SCHEMA, "design": key, "fold": fold, "enrolled": sorted(enrolled)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for fold in range(k)
    }
    spec = fc.FrameSpec(
        frame_id=str(fixture["generator"]["frame_id"]),
        admissibility=fc.Admissibility.confirmatory,
        sealed=True,
        source_sha256=None,
        exhaustive=True,
    )
    frame = ff.build_frame(
        spec=spec,
        images=images,
        faces=faces,
        planning_icc=icc,
        k=k,
        seed=fold_seed,
        test_fold=0,
        gallery_sha256_by_fold=gallery,
        enrolled_identity_ids=enrolled,
    )
    frame_sha = hashlib.sha256(ff.frame_json(frame).encode("utf-8")).hexdigest()
    frame = dataclasses.replace(frame, spec=dataclasses.replace(spec, source_sha256=frame_sha))
    template_sha = hashlib.sha256(
        json.dumps(
            {"schema": SIMULATOR_SCHEMA, "design": key, "icc": icc, "identities": sorted(enrolled)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    # S1 names a component by its smallest image id, which can be a background image. Re-key every
    # session-named PSU, background unit and cell label to the component id that S1 actually assigned.
    sessions = [f"psu-{slug}-{index:03d}" for index in range(len(sizes))]
    component_of: dict[str, str] = {}
    for image in images:
        if image.image_id.startswith(f"img-{slug}-") and image.session_id not in component_of:
            component_of[str(image.session_id)] = frame.psu_map[image.image_id]
    psu_ids = [component_of[name] for name in sessions]
    psu_cell = {component_of[name]: label for name, label in zip(sessions, cell_names, strict=True)}
    background = [(rid, iid, component_of[str(session)]) for rid, iid, session in background]
    face_info: list[_FaceInfo] = []
    for face in frame.faces:
        psu_id = frame.psu_map[face.image_id]
        fold = frame.folds[psu_id]
        face_info.append(
            _FaceInfo(
                face_id=face.face_id,
                image_id=face.image_id,
                psu_id=psu_id,
                identity=str(face.identity_id),
                fold=fold,
                fold_role=frame.fold_roles[fold],
                cell=label_of[psu_cell[psu_id]],
                gallery_sha=frame.gallery_sha256_by_fold[fold],
            )
        )
    faces_by_psu: dict[str, list[int]] = {psu: [] for psu in psu_ids}
    for index, info in enumerate(face_info):
        faces_by_psu[info.psu_id].append(index)
    background_by_psu = {psu: 0 for psu in psu_ids}
    for _, _, psu_id in background:
        background_by_psu[psu_id] += 1
    mated_sizes = [len(faces_by_psu[psu]) for psu in psu_ids]
    image_sizes = [len(faces_by_psu[psu]) + background_by_psu[psu] for psu in psu_ids]
    nonmated_sizes = [background_by_psu[psu] for psu in psu_ids if background_by_psu[psu] > 0]
    cell_groups: dict[str, list[int]] = {}
    for psu, size in zip(psu_ids, mated_sizes, strict=True):
        cell_groups.setdefault(psu_cell[psu], []).append(size)
    cell_sizing = (
        {
            label: {**_public_sizing(_sizing(sizes_in_cell, icc_exact)), "psu_floor_met": len(sizes_in_cell) >= params.decision.cell_floor_n_independent}
            for label, sizes_in_cell in sorted(cell_groups.items())
        }
        if cells_rule != "none"
        else {}
    )
    leg_keys, alignment = _leg_config(fixture)
    return _Design(
        key=key,
        icc=icc,
        frame=frame,
        faces=tuple(face_info),
        identities=tuple(info.identity for info in face_info),
        background=tuple(background),
        psu_ids=tuple(psu_ids),
        psu_cell=psu_cell,
        faces_by_psu={psu: tuple(positions) for psu, positions in faces_by_psu.items()},
        sizing_mated=_sizing(mated_sizes, icc_exact),
        sizing_image=_public_sizing(_sizing(image_sizes, icc_exact)),
        sizing_nonmated=_public_sizing(_sizing(nonmated_sizes, icc_exact)),
        cell_sizing=cell_sizing,
        frame_sha=frame_sha,
        template_sha=template_sha,
        tau=float(fixture["generator"]["operating_threshold_tau"]),
        margin=float(fixture["generator"]["score_margin"]),
        gap=float(fixture["generator"]["second_score_gap"]),
        leg_keys=leg_keys,
        alignment=alignment,
    )


def _design_key(params: SimulationParams, suite: str, icc: float | None = None) -> str:
    block = params.fixture["suite_designs"][suite]
    value = block[f"{(params.icc if icc is None else icc):.2f}"]
    if isinstance(value, list):
        raise _fail(f"suite {suite} declares several designs; use its explicit design keys")
    return value


def _branch_key(params: SimulationParams, suite: str, branch: str) -> str:
    return params.fixture["suite_designs"][suite][branch]


# --- decisions (synthetic, sealed by the real S0 validators) ----------------------------


def _synthetic_decision(params: SimulationParams, design: _Design, h2_leg: fc.LegKind) -> fc.DecisionManifest:
    base = params.decision
    syn = params.fixture["synthetic_decision"]
    guard = syn["guardrail"]
    hypotheses = tuple(
        dataclasses.replace(h, legs=(h2_leg, fc.LegKind.insightface))
        if h.kind is fc.HypothesisKind.non_inferiority
        else h
        for h in base.hypotheses
    )
    manifest = dataclasses.replace(
        base,
        decision_id=f"{syn['decision_id_prefix']}/{design.key}/{h2_leg.value}",
        planning_icc=design.icc,
        frames=(design.frame.spec,),
        gallery_lineage=fc.GalleryLineage(
            split_seed=base.gallery_lineage.split_seed,
            templates_sha256=design.template_sha,
        ),
        hypotheses=hypotheses,
        guardrails=(
            fc.Guardrail(
                id=guard["id"],
                metric=guard["metric"],
                rule=guard["rule"],
                cohort_scope=guard["cohort_scope"],
                role=fc.GuardrailRole(guard["role"]),
            ),
        ),
        ratification=fc.Ratification(decision_ref=syn["ratification_ref"], ratified_at=syn["ratified_at"]),
        seal=None,
    )
    return fc.seal(manifest, sealed_at=syn["sealed_at"])


class _Decisions:
    """Sealed synthetic decision per H2 in-house leg, built once for one design."""

    def __init__(self, params: SimulationParams, design: _Design) -> None:
        self._params = params
        self._design = design
        self._cache: dict[fc.LegKind, fc.DecisionManifest] = {}

    def for_h2(self, leg: fc.LegKind) -> fc.DecisionManifest:
        if leg not in self._cache:
            self._cache[leg] = _synthetic_decision(self._params, self._design, leg)
        return self._cache[leg]


# --- packets: patterns, classes and records ---------------------------------------------


@dataclass(frozen=True)
class _Draws:
    """Latent per-face draws shared by the control and planted packets of one replicate."""

    miss_class: Mapping[fc.LegKind, np.ndarray]
    other: Mapping[fc.LegKind, np.ndarray]
    score: Mapping[fc.LegKind, np.ndarray]
    background_top: Mapping[fc.LegKind, np.ndarray]
    background_score: Mapping[fc.LegKind, np.ndarray]


@dataclass(frozen=True)
class _Packet:
    """One paired run: native records for every GT mate and leg, background units and attribution rows."""

    native: Mapping[fc.LegKind, tuple[fl.FaceSearchRecord, ...]]
    background: tuple[fl.FaceSearchRecord, ...]
    background_psu: tuple[str, ...]
    attribution: tuple[fl.FaceSearchRecord, ...]
    classes: Mapping[fc.LegKind, np.ndarray]

    @property
    def records(self) -> tuple[fl.FaceSearchRecord, ...]:
        rows: list[fl.FaceSearchRecord] = []
        for leg in _LEGS:
            rows.extend(self.native[leg])
        rows.extend(self.background)
        rows.extend(self.attribution)
        return tuple(rows)


@dataclass(frozen=True)
class _Realization:
    control: _Packet
    planted: _Packet
    drops: int
    draws: _Draws


def _miss_class_weights(fixture: Mapping[str, Any]) -> tuple[int, ...]:
    law = fixture["generator"]["miss_class_law"]
    return tuple(int(law[name]) for name in ("missed", "rejected", "wrong_identity"))


def _classify(miss: np.ndarray, draw: np.ndarray, weights: tuple[int, ...]) -> np.ndarray:
    """Correct where the face is not missed; otherwise missed, rejected or wrong by the shared integer draw."""
    boundaries = np.cumsum(weights)
    codes = np.array([_MISSED, _REJECTED, _WRONG], dtype=np.int8)
    miss_class = codes[np.searchsorted(boundaries, draw, side="right")]
    return np.where(miss, miss_class, np.int8(_CORRECT)).astype(np.int8)


def _record(
    design: _Design,
    leg: fc.LegKind,
    arm: fc.Arm,
    cls: int,
    index: int,
    other_index: int,
    score_u: float,
) -> fl.FaceSearchRecord:
    info = design.faces[index]
    own = info.identity
    other = design.identities[other_index]
    if cls == _MISSED:
        stage = fc.SearchStage.detected if design.alignment[leg] is fc.AlignmentMode.fused_internal else fc.SearchStage.missed
        top: tuple[tuple[str, float], ...] = ()
    else:
        stage = fc.SearchStage.embedded
        if cls == _WRONG:
            score = design.tau + design.margin * score_u
            top = ((other, score), (own, score - design.gap))
        else:
            sign = 1.0 if cls == _CORRECT else -1.0
            score = design.tau + sign * design.margin * score_u
            top = ((own, score), (other, score - design.gap))
    return fl.FaceSearchRecord(
        face_id=info.face_id,
        image_id=info.image_id,
        psu_id=info.psu_id,
        identity_id=own,
        identity_status=fc.IdentityStatus.named,
        fold=info.fold,
        fold_role=info.fold_role,
        cell=info.cell,
        unit_id=None,
        sampling_arm=fc.SamplingArm.probability,
        inclusion_probability=1.0,
        cohort=None,
        leg_key=design.leg_keys[(leg, arm)],
        arm=arm,
        arm_availability=fc.ArmStatus.available,
        alignment_mode=design.alignment[leg],
        stage_reached=stage,
        top_k=top,
        gallery_sha256=info.gallery_sha,
        timing_receipt_ref=None,
    )


def _unavailable_row(design: _Design, leg: fc.LegKind, arm: fc.Arm, index: int) -> fl.FaceSearchRecord:
    info = design.faces[index]
    return fl.FaceSearchRecord(
        face_id=info.face_id,
        image_id=info.image_id,
        psu_id=info.psu_id,
        identity_id=info.identity,
        identity_status=fc.IdentityStatus.named,
        fold=info.fold,
        fold_role=info.fold_role,
        cell=info.cell,
        unit_id=None,
        sampling_arm=fc.SamplingArm.probability,
        inclusion_probability=1.0,
        cohort=None,
        leg_key=design.leg_keys[(leg, arm)],
        arm=arm,
        arm_availability=fc.ArmStatus.unavailable_fused,
        alignment_mode=design.alignment[leg],
        stage_reached=None,
        top_k=(),
        gallery_sha256=info.gallery_sha,
        timing_receipt_ref=None,
    )


def _leg_rows(design: _Design, leg: fc.LegKind, cls: np.ndarray, draws: _Draws, arm: fc.Arm) -> tuple[fl.FaceSearchRecord, ...]:
    n = len(design.faces)
    other = draws.other[leg]
    score = draws.score[leg]
    return tuple(
        _record(design, leg, arm, int(cls[i]), i, int((i + other[i]) % n), float(score[i])) for i in range(n)
    )


def _background_rows(design: _Design, draws: _Draws) -> tuple[fl.FaceSearchRecord, ...]:
    rows: list[fl.FaceSearchRecord] = []
    for leg in _LEGS:
        for b, (unit_id, image_id, psu_id) in enumerate(design.background):
            fold = design.frame.folds[psu_id]
            score = design.tau - design.margin * float(draws.background_score[leg][b])
            top_index = int(draws.background_top[leg][b])
            rows.append(
                fl.FaceSearchRecord(
                    face_id=unit_id,
                    image_id=image_id,
                    psu_id=psu_id,
                    identity_id=None,
                    identity_status=fc.IdentityStatus.unknown,
                    fold=fold,
                    fold_role=design.frame.fold_roles[fold],
                    cell=("background", "background"),
                    unit_id=unit_id,
                    sampling_arm=fc.SamplingArm.probability,
                    inclusion_probability=1.0,
                    cohort=None,
                    leg_key=design.leg_keys[(leg, fc.Arm.native)],
                    arm=fc.Arm.native,
                    arm_availability=fc.ArmStatus.available,
                    alignment_mode=design.alignment[leg],
                    stage_reached=fc.SearchStage.embedded,
                    top_k=((design.identities[top_index], score),),
                    gallery_sha256=design.frame.gallery_sha256_by_fold[fold],
                    timing_receipt_ref=None,
                )
            )
    return tuple(rows)


def _packet(
    design: _Design,
    classes: Mapping[fc.LegKind, np.ndarray],
    draws: _Draws,
    background: tuple[fl.FaceSearchRecord, ...],
    *,
    baseline: Mapping[fc.LegKind, np.ndarray] | None,
    attribution_arms: Sequence[fc.Arm],
) -> _Packet:
    native = {leg: _leg_rows(design, leg, classes[leg], draws, fc.Arm.native) for leg in _LEGS}
    attribution: list[fl.FaceSearchRecord] = []
    if baseline is not None:
        for arm in attribution_arms:
            for leg in _IN_HOUSE:
                attribution.extend(_leg_rows(design, leg, baseline[leg], draws, arm))
            attribution.extend(_unavailable_row(design, fc.LegKind.insightface, arm, i) for i in range(len(design.faces)))
    return _Packet(
        native=native,
        background=background,
        background_psu=tuple(psu for _, _, psu in design.background),
        attribution=tuple(attribution),
        classes=dict(classes),
    )


def _joint_triples(fixture: Mapping[str, Any], scenario: str, design: _Design) -> list[tuple[tuple[int, int, int], ...]]:
    laws = fixture["laws"]
    coupled = tuple((int(c), int(p), int(w)) for c, p, w in laws["h1_power_joint_coupling"])

    def diagonal(weights: Sequence[int]) -> tuple[tuple[int, int, int], ...]:
        return tuple((c, c, w) for c, w in enumerate(weights) if w > 0)

    null = diagonal(laws["null"])
    if scenario in ("null", "stage_planting"):
        return [null] * len(design.psu_ids)
    if scenario == "selection_control":
        return [diagonal(laws["selection_control"])] * len(design.psu_ids)
    if scenario == "h2_boundary":
        return [diagonal(laws["h2_boundary"])] * len(design.psu_ids)
    if scenario == "h1_power_global":
        return [coupled] * len(design.psu_ids)
    if scenario == "h1_power_cell_only":
        return [coupled if design.psu_cell[psu] == "clear_mask" else null for psu in design.psu_ids]
    raise _fail(f"scenario {scenario} has no joint law")


def _joint_miss_bits(
    design: _Design, fixture: Mapping[str, Any], scenario: str, rng: np.random.Generator
) -> tuple[dict[fc.LegKind, np.ndarray], dict[fc.LegKind, np.ndarray]]:
    """Control and planted miss bits. One Dirichlet per PSU over the joint law, faces drawn given the PSU."""
    if scenario == "h2_spanning":
        return _spanning_bits(design, fixture)
    denominator = int(fixture["laws"]["denominator"])
    triples_by_psu = _joint_triples(fixture, scenario, design)
    k = 1.0 / design.icc - 1.0
    n = len(design.faces)
    control_pattern = np.zeros(n, dtype=np.int64)
    planted_pattern = np.zeros(n, dtype=np.int64)
    for psu_id, triples in zip(design.psu_ids, triples_by_psu, strict=True):
        positions = np.asarray(design.faces_by_psu[psu_id], dtype=np.int64)
        weights = np.array([w for _, _, w in triples], dtype=float)
        with np.errstate(divide="ignore"):
            logits = np.log(rng.gamma(k * (weights / denominator)))
        probs = np.exp(logits - logits.max())
        probs = probs / probs.sum()
        choices = rng.choice(len(triples), size=positions.size, p=probs)
        control_pattern[positions] = np.array([c for c, _, _ in triples], dtype=np.int64)[choices]
        planted_pattern[positions] = np.array([p for _, p, _ in triples], dtype=np.int64)[choices]
    control = {leg: ((control_pattern >> _LEG_BIT_SHIFT[leg]) & 1).astype(bool) for leg in _LEGS}
    planted = {leg: ((planted_pattern >> _LEG_BIT_SHIFT[leg]) & 1).astype(bool) for leg in _LEGS}
    return control, planted


def _spanning_bits(design: _Design, fixture: Mapping[str, Any]) -> tuple[dict[fc.LegKind, np.ndarray], dict[fc.LegKind, np.ndarray]]:
    counts = fixture["laws"]["h2_spanning"]["per_16_face_psu"]
    order = (
        ["aura"] * counts["positive_aura_miss_ins_correct"]
        + ["ins"] * counts["negative_aura_correct_ins_miss"]
        + ["both"] * counts["both_miss"]
        + ["none"] * counts["both_correct"]
    )
    n = len(design.faces)
    aura = np.zeros(n, dtype=bool)
    ins = np.zeros(n, dtype=bool)
    for psu_id in design.psu_ids:
        positions = design.faces_by_psu[psu_id]
        if len(positions) == 1:
            continue
        if len(positions) != len(order):
            raise _fail(f"h2_spanning PSU {psu_id} must have {len(order)} faces")
        for position, kind in zip(positions, order, strict=True):
            aura[position] = kind in ("aura", "both")
            ins[position] = kind in ("ins", "both")
    zeros = np.zeros(n, dtype=bool)
    return {fc.LegKind.sface: zeros, fc.LegKind.auraface: aura, fc.LegKind.insightface: ins}, {
        fc.LegKind.sface: zeros,
        fc.LegKind.auraface: aura.copy(),
        fc.LegKind.insightface: ins.copy(),
    }


def _draw_latents(design: _Design, fixture: Mapping[str, Any], rng: np.random.Generator) -> _Draws:
    total = sum(_miss_class_weights(fixture))
    n = len(design.faces)
    n_ids = len(design.identities)
    n_background = len(design.background)
    miss_class: dict[fc.LegKind, np.ndarray] = {}
    other: dict[fc.LegKind, np.ndarray] = {}
    score: dict[fc.LegKind, np.ndarray] = {}
    background_top: dict[fc.LegKind, np.ndarray] = {}
    background_score: dict[fc.LegKind, np.ndarray] = {}
    for leg in _LEGS:
        miss_class[leg] = rng.integers(0, total, size=n)
        other[leg] = rng.integers(1, n_ids, size=n)
        score[leg] = 1.0 - rng.random(size=n)
        background_top[leg] = rng.integers(0, n_ids, size=n_background)
        background_score[leg] = 1.0 - rng.random(size=n_background)
    return _Draws(miss_class, other, score, background_top, background_score)


def _stage_drops(fixture: Mapping[str, Any], control: Mapping[fc.LegKind, np.ndarray], rng: np.random.Generator) -> np.ndarray:
    """Predeclared floor(fraction * n_mated) drops, stratified over embedded correct and wrong, shared by both arms."""
    fraction = _exact(fixture["generator"]["stage_planting"]["fraction"])
    n = len(control[fc.LegKind.sface])
    drops = math.floor(fraction * n)
    sface, aura = control[fc.LegKind.sface], control[fc.LegKind.auraface]
    embedded = ((sface == _CORRECT) | (sface == _WRONG)) & ((aura == _CORRECT) | (aura == _WRONG))
    eligible = np.nonzero(embedded)[0]
    wrong_pool = eligible[(sface[eligible] == _WRONG) | (aura[eligible] == _WRONG)]
    correct_pool = np.setdiff1d(eligible, wrong_pool, assume_unique=True)
    if drops > eligible.size:
        raise _fail("stage planting has fewer eligible embedded faces than declared drops")
    wrong_drops = round(drops * wrong_pool.size / eligible.size)
    correct_drops = drops - wrong_drops
    if wrong_drops > wrong_pool.size or correct_drops > correct_pool.size:
        raise _fail("stage planting stratum is smaller than its declared drops")
    chosen = np.concatenate(
        [rng.permutation(wrong_pool)[:wrong_drops], rng.permutation(correct_pool)[:correct_drops]]
    )
    mask = np.zeros(n, dtype=bool)
    mask[chosen] = True
    return mask


def _realize(
    design: _Design,
    params: SimulationParams,
    scenario: str,
    seed: int,
    *,
    background_records: bool = False,
) -> _Realization:
    """Control and planted packets for one replicate. Both packets share every latent draw.

    Background records are materialised only for the public ``simulate`` packets. Suites read the
    background PSU list, which is fixed by the design, so they skip the 9,000 per-replicate rows.
    """
    fixture = params.fixture
    rng = np.random.default_rng(seed)
    control_miss, planted_miss = _joint_miss_bits(design, fixture, scenario, rng)
    draws = _draw_latents(design, fixture, rng)
    weights = _miss_class_weights(fixture)
    control_cls = {leg: _classify(control_miss[leg], draws.miss_class[leg], weights) for leg in _LEGS}
    planted_cls = {leg: _classify(planted_miss[leg], draws.miss_class[leg], weights) for leg in _LEGS}
    drops = 0
    attribution_arms: tuple[fc.Arm, ...] = ()
    if scenario == "stage_planting":
        mask = _stage_drops(fixture, control_cls, rng)
        drops = int(mask.sum())
        for leg in _IN_HOUSE:
            planted_cls[leg] = np.where(mask, np.int8(_MISSED), control_cls[leg]).astype(np.int8)
        attribution_arms = tuple(fc.Arm(name) for name in fixture["generator"]["attribution_arms"])
    background = _background_rows(design, draws) if background_records else ()
    control_packet = _packet(
        design,
        control_cls,
        draws,
        background,
        baseline=control_cls if attribution_arms else None,
        attribution_arms=attribution_arms,
    )
    planted_packet = _packet(
        design,
        planted_cls,
        draws,
        background,
        baseline=control_cls if attribution_arms else None,
        attribution_arms=attribution_arms,
    )
    return _Realization(control=control_packet, planted=planted_packet, drops=drops, draws=draws)


def simulate(
    params: SimulationParams, *, seed: int
) -> tuple[ff.Frame, tuple[fl.FaceSearchRecord, ...], tuple[fl.FaceSearchRecord, ...]]:
    """Frame plus the paired control and planted record packets for the suite's default scenario."""
    checked = _as_suite(params, params.suite)
    design = _build_design(checked, _design_key(checked, checked.suite))
    realized = _realize(design, checked, _SUITE_SCENARIO[checked.suite], int(seed), background_records=True)
    return design.frame, realized.control.records, realized.planted.records


# --- results, forcing and verdict helpers -----------------------------------------------


def _results(
    design: _Design,
    decision: fc.DecisionManifest,
    packet: _Packet,
    h2_leg: fc.LegKind,
) -> fs.LegResults:
    """LegResults from one packet: real S3 finish_outcomes per leg over every GT mate."""
    arrays: dict[fc.LegKind, fs.LegArrays] = {}
    for leg in _LEGS:
        records = packet.native[leg]
        arrays[leg] = fs.LegArrays(
            leg,
            tuple(r.face_id for r in records),
            fs.finish_outcomes(records, design.tau, decision.boundary_semantics),
            tuple(r.psu_id for r in records),
            tuple(1.0 for _ in records),
        )
    return fs.LegResults(design.frame.spec, arrays, packet.background_psu, h2_leg, {})


def _force(design: _Design, realized_packet: _Packet, leg: fc.LegKind, mode: str, draws: _Draws) -> _Packet:
    """Replace one non-selected in-house arm with all-miss or all-correct. Other observations are untouched."""
    n = len(design.faces)
    if mode == "all_miss":
        cls = np.full(n, _MISSED, dtype=np.int8)
    elif mode == "all_correct":
        cls = np.full(n, _CORRECT, dtype=np.int8)
    else:
        raise _fail(f"unknown forcing mode {mode}")
    classes = dict(realized_packet.classes)
    classes[leg] = cls
    native = dict(realized_packet.native)
    native[leg] = _leg_rows_forced(design, leg, cls, draws)
    return dataclasses.replace(realized_packet, native=native, classes=classes)


def _leg_rows_forced(design: _Design, leg: fc.LegKind, cls: np.ndarray, draws: _Draws) -> tuple[fl.FaceSearchRecord, ...]:
    n = len(design.faces)
    other = draws.other[leg]
    return tuple(
        _record(design, leg, fc.Arm.native, int(cls[i]), i, int((i + other[i]) % n), 1.0) for i in range(n)
    )


def _row_of(verdict: fs.Verdict, hypothesis_id: str) -> fs.HypothesisVerdict:
    return next(row for row in verdict.hypotheses if row.id == hypothesis_id)


def _h1_superior(verdict: fs.Verdict) -> bool:
    return _row_of(verdict, "H1").state is fc.VerdictState.superior


def _h2_non_inferior(verdict: fs.Verdict) -> bool:
    return _row_of(verdict, "H2").state is fc.VerdictState.non_inferior


def _rate(count: int, n: int) -> float:
    return count / n if n else 0.0


def _mc_se(rate: float, n: int) -> float:
    return math.sqrt(rate * (1.0 - rate) / n) if n else 0.0


def _miss_array(packet: _Packet, leg: fc.LegKind) -> np.ndarray:
    return packet.classes[leg] != _CORRECT


def _discordance(packet: _Packet, left: fc.LegKind, right: fc.LegKind) -> float:
    return float(np.mean(_miss_array(packet, left) != _miss_array(packet, right)))


def _mean_planted_minus_control(realized: _Realization, leg: fc.LegKind, indices: np.ndarray | None = None) -> float:
    planted = realized.planted.classes[leg]
    control = realized.control.classes[leg]
    if indices is not None:
        planted, control = planted[indices], control[indices]
    return float(np.mean(planted != _CORRECT) - np.mean(control != _CORRECT))


def _row(
    params: SimulationParams,
    *,
    suite: str,
    replicates: int,
    seed: int,
    design: Mapping[str, Any],
    metrics: Mapping[str, Any],
    passed: Callable[[], bool],
) -> dict[str, Any]:
    full = replicates == int(params.fixture["acceptance"]["full_replicates"])
    full = full and int(params.decision.interval.n_boot) == int(params.fixture["policy_mirror"]["n_boot"])
    return {
        "suite": suite,
        "icc": params.icc,
        "replicates_requested": replicates,
        "replicates_completed": replicates,
        "n_boot": int(params.decision.interval.n_boot),
        "seed": int(seed),
        "full_acceptance_evidence": bool(full),
        "design": dict(design),
        "metrics": dict(metrics),
        "passed": bool(passed()) if full else None,
    }


def _result(semantic: dict[str, Any], started: float) -> dict[str, Any]:
    return {"semantic": semantic, "timing": {"seconds": round(time.perf_counter() - started, 6)}}


def _icc_check_theory(params: SimulationParams, law: str) -> float:
    return float(exact_icc_oracle(params, law, _exact(params.icc)))


# --- suites ----------------------------------------------------------------------------


def _null_branch_a(params: SimulationParams, replicates: int, seed: int) -> dict[str, Any]:
    design = _build_design(params, _design_key(params, "null"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    superior = 0
    observed: list[float] = []
    discordance: list[float] = []
    for r in range(replicates):
        realized = _realize(design, params, "null", _replicate_seed(seed, r))
        verdict = fs.decide(decision, _results(design, decision, realized.control, fc.LegKind.auraface))
        superior += int(_h1_superior(verdict))
        h1 = _row_of(verdict, "H1")
        if h1.interval is not None and h1.interval.icc is not None:
            observed.append(h1.interval.icc)
        discordance.append(_discordance(realized.control, _LEGS[0], _LEGS[1]))
    rate = _rate(superior, replicates)
    return {
        "superior": superior,
        "rate": rate,
        "mc_se": _mc_se(rate, replicates),
        "design": _public_design(design),
        "empirical_discordance": float(np.mean(discordance)),
        "observed_icc_mean": float(np.mean(observed)) if observed else None,
    }


def _null_branch_b(params: SimulationParams, replicates: int, seed: int) -> dict[str, Any]:
    design = _build_design(params, _branch_key(params, "null", "branch_b_boundary"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    rejects = 0
    forced_pass = 0
    for r in range(replicates):
        realized = _realize(design, params, "h2_boundary", _replicate_seed(seed, r))
        forced = _force(design, realized.control, fc.LegKind.sface, "all_miss", realized.draws)
        verdict = fs.decide(decision, _results(design, decision, forced, fc.LegKind.auraface))
        forced_pass += int(_h1_superior(verdict))
        rejects += int(_h2_non_inferior(verdict))
    rate = _rate(rejects, replicates)
    return {
        "rejects": rejects,
        "rate": rate,
        "mc_se": _mc_se(rate, replicates),
        "h1_forced_pass": forced_pass,
        "design": _public_design(design),
    }


def run_null_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """AE-2b. Branch (a): step-1 superior rate at Delta 0. Branch (b): step-2 boundary rate with H1 forced."""
    started = time.perf_counter()
    params = _as_suite(params, "null")
    _check_run(replicates, seed)
    branch_a = _null_branch_a(params, replicates, seed)
    theory = law_theory(params, "null")
    metrics: dict[str, Any] = {
        "h1_superior_count": branch_a["superior"],
        "h1_superior_rate": branch_a["rate"],
        "h1_superior_mc_se": branch_a["mc_se"],
        "theory": {
            "fnir": {leg.value: float(theory[f"fnir_{leg.value}"]) for leg in _LEGS},
            "discordance": float(theory["discordance_sface_auraface"]),
            "icc": _icc_check_theory(params, "null"),
        },
        "empirical": {
            "discordance": branch_a["empirical_discordance"],
            "observed_icc_mean": branch_a["observed_icc_mean"],
        },
    }
    design_block: dict[str, Any] = {"branches": {"step1_null": branch_a["design"]}, **branch_a["design"]}
    checks = [branch_a["rate"] <= float(params.fixture["acceptance"]["null_superior_max_rate"])]
    if params.icc == float(params.fixture["acceptance"]["gated_icc"]):
        branch_b = _null_branch_b(params, replicates, seed)
        metrics.update(
            {
                "h2_boundary_reject_count": branch_b["rejects"],
                "h2_boundary_reject_rate": branch_b["rate"],
                "h2_boundary_mc_se": branch_b["mc_se"],
                "h1_forced_pass_count": branch_b["h1_forced_pass"],
            }
        )
        design_block["branches"]["step2_boundary"] = branch_b["design"]
        checks.append(branch_b["rate"] <= float(params.fixture["acceptance"]["null_boundary_max_rate"]))
    else:
        metrics["h2_boundary_branch"] = "not_declared_at_this_icc"
    semantic = _row(
        params,
        suite="null",
        replicates=replicates,
        seed=seed,
        design=design_block,
        metrics=metrics,
        passed=lambda: all(checks),
    )
    return _result(semantic, started)


def run_selection_control(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """Sealing control. The smaller in-house estimate is picked after the run, then H1 is forced (INVALID by design)."""
    started = time.perf_counter()
    params = _as_suite(params, "selection")
    _check_run(replicates, seed)
    design = _build_design(params, _design_key(params, "selection"))
    decisions = _Decisions(params, design)
    tie_leg = fc.LegKind(params.fixture["generator"]["selection_tie_rule"])
    rejects = 0
    forced_pass = 0
    chosen_counts = {fc.LegKind.sface.value: 0, fc.LegKind.auraface.value: 0}
    for r in range(replicates):
        realized = _realize(design, params, "selection_control", _replicate_seed(seed, r))
        insight_miss = _miss_array(realized.control, fc.LegKind.insightface)
        estimates = {leg: float(np.mean(_miss_array(realized.control, leg)) - np.mean(insight_miss)) for leg in _IN_HOUSE}
        if estimates[fc.LegKind.auraface] < estimates[fc.LegKind.sface]:
            chosen = fc.LegKind.auraface
        elif estimates[fc.LegKind.sface] < estimates[fc.LegKind.auraface]:
            chosen = fc.LegKind.sface
        else:
            chosen = tie_leg
        chosen_counts[chosen.value] += 1
        other_arm = fc.LegKind.sface if chosen is fc.LegKind.auraface else fc.LegKind.auraface
        mode = "all_miss" if other_arm is fc.LegKind.sface else "all_correct"
        forced = _force(design, realized.control, other_arm, mode, realized.draws)
        decision = decisions.for_h2(chosen)
        verdict = fs.decide(decision, _results(design, decision, forced, chosen))
        forced_pass += int(_h1_superior(verdict))
        rejects += int(_h2_non_inferior(verdict))
    rate = _rate(rejects, replicates)
    threshold = float(params.fixture["acceptance"]["selection_min_exclusive_rate"])
    metrics = {
        "h2_postselection_reject_count": rejects,
        "h2_postselection_reject_rate": rate,
        "h2_postselection_mc_se": _mc_se(rate, replicates),
        "h1_forced_pass_count": forced_pass,
        "selected_leg_counts": chosen_counts,
        "negative_control": True,
        "validity": "INVALID postselection negative control. H2 is chosen after the run; not a product verdict.",
    }
    semantic = _row(
        params,
        suite="selection",
        replicates=replicates,
        seed=seed,
        design={"branches": {"selection_h2": _public_design(design)}, **_public_design(design)},
        metrics=metrics,
        passed=lambda: rate > threshold and forced_pass == replicates,
    )
    return _result(semantic, started)


def run_coverage_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """AE-3: PSU percentile coverage and image-level comparator coverage on the same replicate arrays."""
    started = time.perf_counter()
    params = _as_suite(params, "coverage")
    _check_run(replicates, seed)
    design = _build_design(params, _design_key(params, "coverage"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    n_boot = int(decision.interval.n_boot)
    boot_seed = int(decision.interval.seed)
    level = 0.95
    true_delta = Fraction(0)
    psu_cover = 0
    image_cover = 0
    for r in range(replicates):
        realized = _realize(design, params, "null", _replicate_seed(seed, r))
        out_s = fs.finish_outcomes(realized.control.native[fc.LegKind.sface], design.tau, decision.boundary_semantics)
        out_a = fs.finish_outcomes(realized.control.native[fc.LegKind.auraface], design.tau, decision.boundary_semantics)
        psus = [rec.psu_id for rec in realized.control.native[fc.LegKind.sface]]
        psu_interval = fs.paired_cluster_bootstrap(out_s, out_a, psus, n_boot=n_boot, seed=boot_seed, level=level)
        a = [float(o is not fc.FaceOutcome.correct) for o in out_s]
        b = [float(o is not fc.FaceOutcome.correct) for o in out_a]
        image_interval = bootstrap_paired_delta(a, b, boot_seed, B=n_boot)
        if image_interval.bootstrap_status != "ok" or image_interval.ci_lower is None or image_interval.ci_upper is None:
            raise _fail(f"image comparator returned status {image_interval.bootstrap_status}")
        psu_cover += int(psu_interval.lower <= float(true_delta) <= psu_interval.upper)
        image_cover += int(image_interval.ci_lower <= float(true_delta) <= image_interval.ci_upper)
    psu_rate = _rate(psu_cover, replicates)
    image_rate = _rate(image_cover, replicates)
    lo = float(params.fixture["acceptance"]["coverage_min_rate"])
    hi = float(params.fixture["acceptance"]["coverage_max_rate"])
    negative = params.icc == float(params.fixture["acceptance"]["negative_control_icc"])
    metrics = {
        "psu_coverage_count": psu_cover,
        "psu_coverage_rate": psu_rate,
        "psu_coverage_mc_se": _mc_se(psu_rate, replicates),
        "image_coverage_count": image_cover,
        "image_coverage_rate": image_rate,
        "image_coverage_mc_se": _mc_se(image_rate, replicates),
        "true_delta": float(true_delta),
        "interval_level": level,
        "negative_control": negative,
    }
    semantic = _row(
        params,
        suite="coverage",
        replicates=replicates,
        seed=seed,
        design=_public_design(design),
        metrics=metrics,
        passed=(lambda: lo <= image_rate <= hi) if negative else (lambda: lo <= psu_rate <= hi),
    )
    return _result(semantic, started)


def _cell_decision(
    design: _Design, packet: _Packet, cell: str, decision: fc.DecisionManifest
) -> tuple[bool, int, fs.PairedInterval | None]:
    """Per-cell H1 interval, scored only when the cell meets the independent-PSU floor (score_io rule)."""
    indices = [i for i, info in enumerate(design.faces) if design.psu_cell[info.psu_id] == cell]
    psus = [design.faces[i].psu_id for i in indices]
    psu_count = len(set(psus))
    if psu_count < decision.cell_floor_n_independent:
        return False, psu_count, None
    s_records = [packet.native[fc.LegKind.sface][i] for i in indices]
    a_records = [packet.native[fc.LegKind.auraface][i] for i in indices]
    out_s = fs.finish_outcomes(s_records, design.tau, decision.boundary_semantics)
    out_a = fs.finish_outcomes(a_records, design.tau, decision.boundary_semantics)
    interval = fs.paired_cluster_bootstrap(
        out_s,
        out_a,
        psus,
        n_boot=int(decision.interval.n_boot),
        seed=int(decision.interval.seed),
        level=0.95,
    )
    return interval.lower > 0.0, psu_count, interval


def run_power_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """AE-4. Global planted delta 0.10 at n_eff 115, plus cell-only planting on clear_mask PSUs."""
    started = time.perf_counter()
    params = _as_suite(params, "power")
    _check_run(replicates, seed)
    design = _build_design(params, _design_key(params, "power"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    detect = 0
    control_superior = 0
    observed: list[float] = []
    for r in range(replicates):
        realized = _realize(design, params, "h1_power_global", _replicate_seed(seed, r))
        planted_verdict = fs.decide(decision, _results(design, decision, realized.planted, fc.LegKind.auraface))
        control_verdict = fs.decide(decision, _results(design, decision, realized.control, fc.LegKind.auraface))
        detect += int(_h1_superior(planted_verdict))
        control_superior += int(_h1_superior(control_verdict))
        h1 = _row_of(planted_verdict, "H1")
        if h1.interval is not None and h1.interval.icc is not None:
            observed.append(h1.interval.icc)
    cell = _cell_only_power(params, design, decision, replicates, seed)
    rate = _rate(detect, replicates)
    null_rate = _rate(control_superior, replicates)
    theory_h1 = law_theory(params, "h1_power")
    theory_null = law_theory(params, "null")
    metrics = {
        "h1_detect_count": detect,
        "h1_detect_rate": rate,
        "h1_detect_mc_se": _mc_se(rate, replicates),
        "control_superior_count": control_superior,
        "control_superior_rate": null_rate,
        "control_superior_mc_se": _mc_se(null_rate, replicates),
        "cell_only": cell["metrics"],
        "theory": {
            "fnir_planted": {leg.value: float(theory_h1[f"fnir_{leg.value}"]) for leg in _LEGS},
            "planted_minus_control_sface": float(theory_h1["fnir_sface"] - theory_null["fnir_sface"]),
            "icc": _icc_check_theory(params, "h1_power"),
        },
        "empirical": {"observed_icc_mean": float(np.mean(observed)) if observed else None},
    }
    detect_min = float(params.fixture["acceptance"]["power_min_rate"])
    clear_clear_max = float(params.fixture["acceptance"]["cell_clear_clear_max_rate"])
    clear_mask_min = float(params.fixture["acceptance"]["cell_clear_mask_min_rate"])
    semantic = _row(
        params,
        suite="power",
        replicates=replicates,
        seed=seed,
        design={"branches": {"global_h1": _public_design(design), "cell_only": cell["design"]}, **_public_design(design)},
        metrics=metrics,
        passed=lambda: rate >= detect_min
        and cell["metrics"]["clear_clear"]["detect_rate"] <= clear_clear_max
        and cell["metrics"]["clear_mask"]["detect_rate"] >= clear_mask_min,
    )
    return _result(semantic, started)


def _cell_only_power(
    params: SimulationParams, design: _Design, decision: fc.DecisionManifest, replicates: int, seed: int
) -> dict[str, Any]:
    counts = {"clear_mask": 0, "clear_clear": 0}
    scored = {"clear_mask": 0, "clear_clear": 0}
    contrasts: dict[str, list[float]] = {"clear_mask": [], "clear_clear": []}
    psu_counts: dict[str, int] = {}
    for r in range(replicates):
        realized = _realize(design, params, "h1_power_cell_only", _replicate_seed(seed, r))
        for cell in ("clear_mask", "clear_clear"):
            detected, psu_count, interval = _cell_decision(design, realized.planted, cell, decision)
            psu_counts[cell] = psu_count
            counts[cell] += int(detected)
            scored[cell] += int(interval is not None)
            indices = np.array([i for i, info in enumerate(design.faces) if design.psu_cell[info.psu_id] == cell])
            contrasts[cell].append(_mean_planted_minus_control(realized, fc.LegKind.sface, indices))
    theory_mask = float(law_theory(params, "h1_power")["fnir_sface"] - law_theory(params, "null")["fnir_sface"])
    metrics = {
        cell: {
            "detect_count": counts[cell],
            "detect_rate": _rate(counts[cell], replicates),
            "detect_mc_se": _mc_se(_rate(counts[cell], replicates), replicates),
            "scored_count": scored[cell],
            "n_psu": psu_counts.get(cell, 0),
            "observed_planted_minus_control_sface": float(np.mean(contrasts[cell])),
            "theory_planted_minus_control_sface": theory_mask if cell == "clear_mask" else 0.0,
        }
        for cell in ("clear_mask", "clear_clear")
    }
    return {
        "metrics": {"clear_mask": metrics["clear_mask"], "clear_clear": metrics["clear_clear"]},
        "design": {"key": design.key, "cells": design.cell_sizing},
    }


def run_noninferiority_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """H2 branches. (a) Equal in-house leg at n_eff 400 under planted H1. (b) Boundary, H1 forced. (c) Spanning CI, H1 forced."""
    started = time.perf_counter()
    params = _as_suite(params, "noninferiority")
    _check_run(replicates, seed)
    design = _build_design(params, _design_key(params, "noninferiority"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    margin = float(params.decision.hypotheses[1].margin)
    equal_rejects = 0
    equal_h1 = 0
    boundary_rejects = 0
    spanning_nonin = 0
    spanning_spans = 0
    spanning_widths: list[float] = []
    for r in range(replicates):
        seed_r = _replicate_seed(seed, r)
        planted = _realize(design, params, "h1_power_global", seed_r)
        verdict_a = fs.decide(decision, _results(design, decision, planted.planted, fc.LegKind.auraface))
        equal_rejects += int(_h2_non_inferior(verdict_a))
        equal_h1 += int(_h1_superior(verdict_a))
        boundary = _realize(design, params, "h2_boundary", seed_r)
        forced_b = _force(design, boundary.control, fc.LegKind.sface, "all_miss", boundary.draws)
        boundary_rejects += int(_h2_non_inferior(fs.decide(decision, _results(design, decision, forced_b, fc.LegKind.auraface))))
        spanning = _realize(design, params, "h2_spanning", seed_r)
        forced_c = _force(design, spanning.control, fc.LegKind.sface, "all_miss", spanning.draws)
        verdict_c = fs.decide(decision, _results(design, decision, forced_c, fc.LegKind.auraface))
        spanning_nonin += int(_h2_non_inferior(verdict_c))
        h2 = _row_of(verdict_c, "H2")
        if h2.interval is not None:
            spanning_spans += int(h2.interval.lower <= margin <= h2.interval.upper)
            spanning_widths.append(h2.interval.upper - h2.interval.lower)
    rate_a = _rate(equal_rejects, replicates)
    rate_b = _rate(boundary_rejects, replicates)
    lo = float(params.fixture["acceptance"]["h2_a_min_rate"])
    hi = float(params.fixture["acceptance"]["h2_b_max_rate"])
    metrics = {
        "equal_reject_count": equal_rejects,
        "equal_reject_rate": rate_a,
        "equal_reject_mc_se": _mc_se(rate_a, replicates),
        "equal_h1_superior_count": equal_h1,
        "boundary_reject_count": boundary_rejects,
        "boundary_reject_rate": rate_b,
        "boundary_reject_mc_se": _mc_se(rate_b, replicates),
        "spanning_noninferior_count": spanning_nonin,
        "spanning_ci_spans_margin_count": spanning_spans,
        "spanning_ci_mean_width": float(np.mean(spanning_widths)) if spanning_widths else None,
        "theory_boundary": {
            "auraface_fnir": float(law_theory(params, "h2_boundary")["fnir_auraface"]),
            "insightface_fnir": float(law_theory(params, "h2_boundary")["fnir_insightface"]),
        },
    }
    semantic = _row(
        params,
        suite="noninferiority",
        replicates=replicates,
        seed=seed,
        design={
            "branches": {"a_equal_leg": _public_design(design), "b_boundary": _public_design(design), "c_spanning": _public_design(design)},
            **_public_design(design),
        },
        metrics=metrics,
        passed=lambda: rate_a >= lo and rate_b <= hi and spanning_nonin <= int(params.fixture["acceptance"]["h2_c_max_non_inferior_count"]),
    )
    return _result(semantic, started)


def run_mde_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """MDE refusal at n_eff 300 and margin 0.05, for a truly equal in-house leg, with H1 forced."""
    started = time.perf_counter()
    params = _as_suite(params, "mde")
    _check_run(replicates, seed)
    design = _build_design(params, _design_key(params, "mde"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    refusals = 0
    noninferior = 0
    mde_values: list[float] = []
    n_eff_values: list[float] = []
    for r in range(replicates):
        realized = _realize(design, params, "null", _replicate_seed(seed, r))
        forced = _force(design, realized.control, fc.LegKind.sface, "all_miss", realized.draws)
        verdict = fs.decide(decision, _results(design, decision, forced, fc.LegKind.auraface))
        h2 = _row_of(verdict, "H2")
        refusals += int(h2.reason is fc.InconclusiveReason.margin_unreachable_mde_gt_delta)
        noninferior += int(h2.state is fc.VerdictState.non_inferior)
        if h2.mde is not None:
            mde_values.append(h2.mde)
        n_eff_values.append(h2.n_eff)
    fraction = _rate(refusals, replicates)
    required = float(params.fixture["acceptance"]["mde_refusal_required_fraction"])
    max_noninferior = int(params.fixture["acceptance"]["mde_non_inferior_max_count"])
    semantic = _row(
        params,
        suite="mde",
        replicates=replicates,
        seed=seed,
        design=_public_design(design),
        metrics={
            "refusal_count": refusals,
            "refusal_fraction": fraction,
            "noninferior_count": noninferior,
            "h2_mde_value_mean": float(np.mean(mde_values)) if mde_values else None,
            "h2_n_eff_mean": float(np.mean(n_eff_values)),
        },
        passed=lambda: fraction >= required and noninferior <= max_noninferior,
    )
    return _result(semantic, started)


def run_floor_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """Eligibility floors: refuse 49 PSUs, score 50, and never score sub-30 cells.

    ``at_floor_passed`` means every replicate obtained an H1 interval (floor
    eligibility); ``at_floor_pass_count`` retains the actual integer count.
    """
    started = time.perf_counter()
    params = _as_suite(params, "floor")
    _check_run(replicates, seed)
    below_key, at_key = _floor_design_keys(params)
    below = _build_design(params, below_key)
    at = _build_design(params, at_key)
    below_decision = _Decisions(params, below).for_h2(fc.LegKind.auraface)
    at_decision = _Decisions(params, at).for_h2(fc.LegKind.auraface)
    reasons: Counter[str] = Counter()
    below_intervals = 0
    cell_scored_below = 0
    at_passed = 0
    at_insufficient = 0
    for r in range(replicates):
        seed_r = _replicate_seed(seed, r)
        realized = _realize(below, params, "null", seed_r)
        verdict = fs.decide(below_decision, _results(below, below_decision, realized.control, fc.LegKind.auraface))
        reasons["none" if verdict.reason is None else verdict.reason.value] += 1
        below_intervals += sum(1 for row in verdict.hypotheses if row.interval is not None)
        for cell in ("clear_mask", "clear_clear"):
            _, psu_count, interval = _cell_decision(below, realized.control, cell, below_decision)
            cell_scored_below += int(interval is not None and psu_count < below_decision.cell_floor_n_independent)
        realized_at = _realize(at, params, "null", seed_r)
        verdict_at = fs.decide(at_decision, _results(at, at_decision, realized_at.control, fc.LegKind.auraface))
        at_insufficient += int(verdict_at.reason is fc.InconclusiveReason.insufficient_independent_psus)
        at_passed += int(_row_of(verdict_at, "H1").interval is not None)
        for cell in ("clear_mask", "clear_clear"):
            _, psu_count, interval = _cell_decision(at, realized_at.control, cell, at_decision)
            cell_scored_below += int(interval is not None and psu_count < at_decision.cell_floor_n_independent)
    below_reason = reasons.most_common(1)[0][0] if reasons else "none"
    semantic = _row(
        params,
        suite="floor",
        replicates=replicates,
        seed=seed,
        design={"branches": {"floor_below": _public_design(below), "floor_at": _public_design(at)}, **_public_design(below)},
        metrics={
            "below_floor_reason": below_reason,
            "below_floor_reason_counts": dict(sorted(reasons.items())),
            "below_floor_interval_count": below_intervals,
            "below_floor_psus": below.sizing_mated["n_psu"],
            "at_floor_psus": at.sizing_mated["n_psu"],
            "at_floor_passed": at_passed == replicates,
            "at_floor_pass_count": at_passed,
            "at_floor_insufficient_count": at_insufficient,
            "cell_below_floor_scored": cell_scored_below,
        },
        passed=lambda: below_reason == fc.InconclusiveReason.insufficient_independent_psus.value
        and below_intervals == 0
        and at_passed == replicates
        and at_insufficient == 0
        and cell_scored_below == 0,
    )
    return _result(semantic, started)


def _floor_design_keys(params: SimulationParams) -> tuple[str, str]:
    value = params.fixture["suite_designs"]["floor"][f"{params.icc:.2f}"]
    if not isinstance(value, list) or len(value) != 2:
        raise _fail("floor suite needs exactly two declared designs")
    return value[0], value[1]


def run_stage_suite(params: SimulationParams, *, replicates: int, seed: int) -> dict[str, Any]:
    """Stage planting: predeclared upstream drops shared by both in-house arms, with attribution rows."""
    started = time.perf_counter()
    params = _as_suite(params, "stage")
    _check_run(replicates, seed)
    design = _build_design(params, _design_key(params, "stage"))
    decision = _Decisions(params, design).for_h2(fc.LegKind.auraface)
    max_diff = float(params.fixture["acceptance"]["wrong_identity_max_abs_diff"])
    arms = [fc.Arm(name) for name in params.fixture["generator"]["attribution_arms"]]
    totals = Counter()
    drops_total = 0
    gaps_planted = 0
    gaps_control = 0
    wrong_abs_max = 0.0
    wrong_within = 0
    missed_exact = 0
    attribution_rows: dict[str, int] = {}
    n_mated = len(design.faces)
    for r in range(replicates):
        realized = _realize(design, params, "stage_planting", _replicate_seed(seed, r))
        drops_total += realized.drops
        for leg in _IN_HOUSE:
            control_out = fs.finish_outcomes(realized.control.native[leg], design.tau, decision.boundary_semantics)
            planted_out = fs.finish_outcomes(realized.planted.native[leg], design.tau, decision.boundary_semantics)
            c_miss = sum(o is fc.FaceOutcome.missed for o in control_out)
            p_miss = sum(o is fc.FaceOutcome.missed for o in planted_out)
            embedded = (fc.FaceOutcome.correct, fc.FaceOutcome.wrong_identity, fc.FaceOutcome.rejected)
            c_emb = sum(o in embedded for o in control_out)
            p_emb = sum(o in embedded for o in planted_out)
            c_wrong = sum(o is fc.FaceOutcome.wrong_identity for o in control_out)
            p_wrong = sum(o is fc.FaceOutcome.wrong_identity for o in planted_out)
            totals[f"control_missed_{leg.value}"] += c_miss
            totals[f"planted_missed_{leg.value}"] += p_miss
            totals[f"control_embedded_{leg.value}"] += c_emb
            totals[f"planted_embedded_{leg.value}"] += p_emb
            totals[f"control_embedded_wrong_{leg.value}"] += c_wrong
            totals[f"planted_embedded_wrong_{leg.value}"] += p_wrong
            missed_exact += int(p_miss - c_miss == realized.drops)
            c_rate = c_wrong / c_emb if c_emb else 0.0
            p_rate = p_wrong / p_emb if p_emb else 0.0
            wrong_abs_max = max(wrong_abs_max, abs(p_rate - c_rate))
        for packet, target in ((realized.control, "control"), (realized.planted, "planted")):
            gap = _attribution_gaps(packet, arms)
            if target == "control":
                gaps_control += gap
            else:
                gaps_planted += gap
            attribution_rows.setdefault(target, sum(1 for row in packet.attribution if row.arm_availability is fc.ArmStatus.available))
        within = all(
            abs(_embedded_wrong_rate(realized.planted, leg, design) - _embedded_wrong_rate(realized.control, leg, design)) <= max_diff
            for leg in _IN_HOUSE
        )
        wrong_within += int(within)
    expected_gaps = drops_total * len(_IN_HOUSE) * len(arms)
    metrics: dict[str, Any] = {
        **{name: int(value) for name, value in sorted(totals.items())},
        "drop_count": drops_total,
        "drop_count_per_replicate": drops_total / replicates,
        "missed_delta_exact_count": missed_exact,
        "native_attribution_gaps": gaps_planted,
        "expected_native_attribution_gaps": expected_gaps,
        "control_native_attribution_gaps": gaps_control,
        "embedded_wrong_abs_diff_max": wrong_abs_max,
        "embedded_wrong_within_bound_count": wrong_within,
        "attribution_rows_per_packet": attribution_rows,
        "n_mated": n_mated,
    }
    for leg in _IN_HOUSE:
        name = leg.value
        metrics[f"rates_{name}"] = {
            "control_missed": totals[f"control_missed_{name}"] / (replicates * n_mated),
            "planted_missed": totals[f"planted_missed_{name}"] / (replicates * n_mated),
            "control_embedded_wrong": totals[f"control_embedded_wrong_{name}"] / max(totals[f"control_embedded_{name}"], 1),
            "planted_embedded_wrong": totals[f"planted_embedded_wrong_{name}"] / max(totals[f"planted_embedded_{name}"], 1),
        }
    semantic = _row(
        params,
        suite="stage",
        replicates=replicates,
        seed=seed,
        design=_public_design(design),
        metrics=metrics,
        passed=lambda: wrong_within == replicates
        and missed_exact == replicates * len(_IN_HOUSE)
        and gaps_control == 0
        and gaps_planted == expected_gaps,
    )
    return _result(semantic, started)


def _embedded_wrong_rate(packet: _Packet, leg: fc.LegKind, design: _Design) -> float:
    classes = packet.classes[leg]
    embedded = classes != _MISSED
    return float(np.sum(classes[embedded] == _WRONG) / np.sum(embedded)) if np.any(embedded) else 0.0


def _attribution_gaps(packet: _Packet, arms: Sequence[fc.Arm]) -> int:
    native = {(rec.leg_key.split("__")[0], rec.face_id): rec.stage_reached for leg in _LEGS for rec in packet.native[leg]}
    gaps = 0
    for row in packet.attribution:
        if row.arm_availability is not fc.ArmStatus.available:
            continue
        kind = row.leg_key.split("__")[0]
        if native[(kind, row.face_id)] is not row.stage_reached:
            gaps += 1
    return gaps


_SUITE_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "null": run_null_suite,
    "selection": run_selection_control,
    "coverage": run_coverage_suite,
    "power": run_power_suite,
    "noninferiority": run_noninferiority_suite,
    "mde": run_mde_suite,
    "floor": run_floor_suite,
    "stage": run_stage_suite,
}


# --- acceptance report -----------------------------------------------------------------


def _pending_claims() -> dict[str, str]:
    return {
        "AE-10": "coordinator-recorded laptop static scan; not computed by S9",
        "AE-5": "real canary evidence; not supplied to the simulator",
        "AE-6-real": "real-data historical parity; not supplied to the simulator",
        "AE-12": "real-data evidence; not supplied to the simulator",
    }


def acceptance_report(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Report synthetic suites; real claims stay pending and unsupplied fixture checks stay not_run."""
    rows = sorted(
        (dict(item["semantic"]) for item in results),
        key=lambda row: (row["suite"], row["icc"], row["replicates_requested"]),
    )
    gated = 0.10
    gated_rows = {row["suite"]: row for row in rows if row["icc"] == gated}
    evals: dict[str, Any] = {}
    for name, suite in (
        ("AE-2b", "null"),
        ("selection-control", "selection"),
        ("AE-3", "coverage"),
        ("AE-4", "power"),
        ("H2-branches", "noninferiority"),
        ("MDE-refusal", "mde"),
        ("eligibility-floors", "floor"),
        ("stage-defect", "stage"),
    ):
        row = gated_rows.get(suite)
        if row is None:
            evals[name] = {"status": "not_run"}
            continue
        complete = row["replicates_completed"] == row["replicates_requested"]
        status = (
            "not_full_evidence"
            if not complete or row["full_acceptance_evidence"] is not True or row["passed"] is None
            else ("pass" if row["passed"] else "fail")
        )
        evals[name] = {
            "status": status,
            "full_acceptance_evidence": row["full_acceptance_evidence"],
            "replicates_requested": row["replicates_requested"],
            "replicates_completed": row["replicates_completed"],
            "metrics": row["metrics"],
        }
    pending = _pending_claims()
    for name, details in pending.items():
        # AE-6 is historical real-data parity; its fixture checks are a separate claim.
        evals["AE-6" if name == "AE-6-real" else name] = {"status": "pending", "details": details}
    for name in ("AE-1", "AE-6-fixture", "AE-7", "AE-8", "AE-9"):
        evals[name] = {
            "status": "not_run",
            "details": "fixture checks run separately; no verified fixture results supplied to acceptance_report",
        }
    findings = [
        f"sensitivity {row['suite']} at icc {row['icc']} failed (report only)"
        for row in rows
        if row["icc"] != gated and row["passed"] is False and row["suite"] in ("null", "coverage", "power")
    ]
    negative = next((row for row in rows if row["suite"] == "coverage" and row["metrics"].get("negative_control")), None)
    if negative is not None:
        evals["coverage-negative-control"] = {
            "status": "expected_fail_observed" if negative["passed"] is False else "not_failed",
            "replicates_requested": negative["replicates_requested"],
            "metrics": negative["metrics"],
        }
    required = ("null", "selection", "coverage", "power", "noninferiority", "mde", "floor", "stage")
    full = all(
        suite in gated_rows
        and gated_rows[suite]["full_acceptance_evidence"] is True
        and gated_rows[suite]["replicates_completed"] == gated_rows[suite]["replicates_requested"]
        and gated_rows[suite]["passed"] is True
        for suite in required
    )
    timings = [float(item["timing"]["seconds"]) for item in results]
    return {
        "semantic": {
            "schema": ACCEPTANCE_SCHEMA,
            "rows": rows,
            "evals": evals,
            "suites_run": sorted({row["suite"] for row in rows}),
            "suites_missing": sorted(set(required) - {row["suite"] for row in rows}),
            "full_acceptance_evidence": bool(full),
            "findings": findings,
            "pending": pending,
        },
        "timing": {"seconds_total": round(sum(timings), 6), "per_row_seconds": timings},
    }


# --- command line ----------------------------------------------------------------------


def _default_runs(fixture: Mapping[str, Any], suites: Sequence[str]) -> list[tuple[str, float]]:
    runs: list[tuple[str, float]] = []
    for suite in dict.fromkeys(suites):
        for icc in _suite_iccs(fixture, suite):
            runs.append((suite, icc))
    return runs


def _acceptance_cli_status(
    report: Mapping[str, Any], *, gated_icc: float, negative_control_icc: float
) -> tuple[int, str]:
    """Judge executed full rows without changing the report or its evidence scope."""
    semantic = report["semantic"]
    failures: list[str] = []
    for row in semantic["rows"]:
        if row["full_acceptance_evidence"] is not True:
            continue
        negative = row["suite"] == "coverage" and row["icc"] == negative_control_icc
        if row["icc"] != gated_icc and not negative:
            continue
        expected = False if negative else True
        if row["replicates_completed"] != row["replicates_requested"] or row["passed"] is not expected:
            label = "coverage negative control" if negative else row["suite"]
            failures.append(f"{label} at ICC {row['icc']:g}")
    if failures:
        return 1, "failed full acceptance checks: " + ", ".join(sorted(set(failures)))
    if semantic["full_acceptance_evidence"] and all(
        row["full_acceptance_evidence"] is True
        and row["replicates_completed"] == row["replicates_requested"]
        and row["passed"] is not None
        for row in semantic["rows"]
    ):
        return 0, "full synthetic acceptance passed; real claims remain pending"
    return 0, "partial evidence; full acceptance not established"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="firbench_selftest", description="FIRBENCH-1 S9 simulator and acceptance")
    parser.add_argument("--params", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--replicates", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--suites", default=",".join(SUITES))
    args = parser.parse_args(argv)
    suites = [name.strip() for name in args.suites.split(",") if name.strip()]
    unknown = sorted(set(suites) - set(SUITES))
    if unknown:
        raise SystemExit(f"unknown suites {unknown}")
    out_dir = fc.require_private_output_path(args.out, repo_root=_REPO_ROOT)
    decision = fc.load_decision_manifest(args.decision)
    params = load_params(args.params, decision=decision)
    replicates = int(args.replicates) if args.replicates is not None else int(params.fixture["acceptance"]["full_replicates"])
    master = int(args.seed) if args.seed is not None else int(params.fixture["seeds"]["master_seed"])
    results: list[dict[str, Any]] = []
    for suite, icc in _default_runs(params.fixture, suites):
        run_params = dataclasses.replace(params, icc=icc)
        seed = _suite_seed(params.fixture, master, suite, icc)
        results.append(_SUITE_RUNNERS[suite](run_params, replicates=replicates, seed=seed))
    report = acceptance_report(results)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "acceptance.json"
    target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    status, message = _acceptance_cli_status(
        report,
        gated_icc=float(params.fixture["policy_mirror"]["planning_icc"]),
        negative_control_icc=float(params.fixture["acceptance"]["negative_control_icc"]),
    )
    sys.stdout.write(f"wrote {target}: {message}\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
