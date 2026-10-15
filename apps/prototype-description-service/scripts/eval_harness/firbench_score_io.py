"""Persisted-run FIRBENCH scoring (Builds 7–10).

Only declared GT inventory, search ledgers and the pinned timing receipt are read.
MCP16810 separates query folds from searched-gallery membership. Core statistics
remain in firbench_score; this module owns assembly and evidence eligibility.

Optional predeclared manifest.firbench evidence is explicit:
``data_origin_by_image[id] = {origin, provenance_ref}``,
``external_mention_denominators[leg_key] = count``, and
``cost_report = {total_cost, accepted_descriptions, provenance_ref}``.
Timing policy uses ``ms/GT_face``: the linear 95th percentile of native image
work, allocated equally across the image's fixed expected GT faces. Empty-GT
image costs are retained as image overhead and create no face sample.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as frames
from scripts.eval_harness import firbench_score as core
from scripts.eval_harness.firbench_legs import FaceSearchRecord


def _fail(message: str) -> fc.FrameContractError:
    return fc.FrameContractError(message)


def _json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_bytes(), object_pairs_hook=fc._reject_duplicate_keys, parse_constant=fc._reject_non_finite
        )
    except (OSError, ValueError, UnicodeError) as exc:
        raise _fail(f"cannot read {path.name}: {exc}") from exc


def _unique(rows, key, value):
    result = {}
    for row in rows:
        if row[key] in result:
            raise _fail(f"duplicate {key}: {row[key]}")
        result[row[key]] = row[value]
    return result


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _fail(f"{name} must be a finite number")
    return float(value)


def occluder_label(values: Sequence[str] | None) -> str:
    """Null is unknown; an explicit empty set is clear; sets stay composite."""
    if values is None:
        return "unknown"
    if isinstance(values, str) or any(not isinstance(v, str) or not v for v in values):
        raise _fail("occluders must be an array of labels or null")
    return "+".join(sorted(set(values))) if values else "clear"


def _result(data=None, *, reason=None, status=None):
    return {"status": status or ("available" if reason is None else "unavailable"), "reason": reason, "data": data}


def pair_fmr(rows, *, tau: float | None, boundary: fc.BoundarySemantics) -> dict:
    """1:1 FMR uses supplied complete pairs, never search top-K."""
    if rows is None:
        return _result(reason="pair_scores_not_supplied", status="not_evaluated")
    negatives = []
    for row in rows:
        if set(row) != {"is_mated", "score"} or type(row["is_mated"]) is not bool:
            raise _fail("pair scores require is_mated:boolean and score:number")
        score = _finite(row["score"], "pair score")
        if not row["is_mated"]:
            negatives.append(score)
    if tau is None:
        return _result(reason="calibration_unavailable")
    if not negatives:
        return _result(reason="no_nonmated_pairs")
    count = sum(core._accepts(s, tau, nonmated=True, boundary=boundary) for s in negatives)
    return _result({"false_matches": count, "n_nonmated_pairs": len(negatives), "rate": count / len(negatives)})


@dataclass
class Inventory:
    payload: dict
    spec: fc.FrameSpec
    images: dict
    faces: dict
    psus: dict
    folds: dict
    identity_folds: dict
    test_fold: int
    pools: dict


def _inventory(payload, decision, enrolled) -> Inventory:
    fc.validate_interchange("frame-v1", payload)
    spec = decision.frame(payload["frame_id"])
    for name in ("admissibility", "sealed", "source_sha256", "exhaustive"):
        if payload[name] != getattr(spec, name):
            raise _fail(f"persisted frame {name} differs from decision")
    if spec.exhaustive is not True:
        raise _fail("exhaustive GT is required")
    if payload["planning_icc"] != decision.planning_icc or decision.planning_icc is None:
        raise _fail("frame planning_icc differs from decision")
    k, seed = decision.fold_protocol.k, decision.fold_protocol.seed
    if k is None or seed is None:
        raise _fail("declared fold protocol is required")
    images = {}
    for raw in payload["images"]:
        image = frames.ImageUnit(**raw)
        if image.image_id in images:
            raise _fail("duplicate image_id")
        images[image.image_id] = image
    faces = {}
    for raw in payload["faces"]:
        values = dict(raw)
        annotation = dict(values.pop("annotation"))
        annotation["visibility"] = frames.Visibility(**annotation["visibility"])
        values["annotation"] = frames.FaceAnnotation(**annotation)
        values["cohort"] = None if values["cohort"] is None else frames.Cohort(**values["cohort"])
        values["identity_status"] = fc.IdentityStatus(values["identity_status"])
        values["box"] = tuple(values["box"])
        face = frames.GtFace(**values)
        if face.face_id in faces:
            raise _fail("duplicate face_id")
        faces[face.face_id] = face
    psus = _unique(payload["psu_map"], "image_id", "psu_id")
    folds = _unique(payload["folds"], "psu_id", "fold")
    identities = _unique(payload["identity_folds"], "identity_id", "fold")
    canonical = frames.build_psu_components(tuple(images.values()), tuple(faces.values()))
    if psus != canonical:
        raise _fail("persisted PSU partition differs from exhaustive GT")
    identity_components = frames.identity_to_component(tuple(faces.values()), psus)
    expected_folds = frames.identity_disjoint_folds(psus, identity_components, k=k, seed=seed)
    if folds != expected_folds:
        raise _fail("persisted folds differ from declared protocol")
    if identities != {i: folds[p] for i, p in identity_components.items()}:
        raise _fail("missing or contradictory identity fold provenance")
    test = seed % k
    roles = _unique(payload["fold_roles"], "fold", "role")
    if roles != {f: "test" if f == test else "fit" for f in range(k)}:
        raise _fail("primary rotation must use seed % k, remaining folds fit")
    pools = {}
    # Keep full GT for provenance, timing and per-face rows. Only identity-resolved
    # faces may contribute face source units; unresolved faces add no PSU edges.
    resolved_faces = tuple(f for f in faces.values() if f.identity_status is not fc.IdentityStatus.unresolved)
    for fold in range(k):
        try:
            pools[fold] = frames.build_nonmated_pool(
                resolved_faces,
                tuple(images.values()),
                folds,
                fold=fold,
                component_map=psus,
                exhaustive=True,
                planning_icc=decision.planning_icc,
                enrolled_identity_ids=frozenset(enrolled[fold]),
            )
        except TypeError as exc:
            raise _fail("S1 MCP16810 enrolled_identity_ids interface is not installed") from exc
    pool = pools[test]
    if payload["n_units"] != pool.n_units or not math.isclose(
        payload["n_nonmated_eff"], pool.n_nonmated_eff, abs_tol=1e-12, rel_tol=0
    ):
        raise _fail("persisted nonmated counts differ from declared gallery and GT")
    sizes = list(Counter(psus[f.image_id] for f in faces.values()).values())
    deff = frames.design_effect(sizes, decision.planning_icc) if sizes else 1.0
    if not math.isclose(payload["design_effect"], deff, abs_tol=1e-12, rel_tol=0) or not math.isclose(
        payload["n_eff"], len(faces) / deff, abs_tol=1e-12, rel_tol=0
    ):
        raise _fail("frame n_eff must describe whole GT inventory")
    counts = Counter(i.sampling_arm.value for i in images.values())
    if payload["sampling_arm_counts"] != {a.value: counts[a.value] for a in fc.SamplingArm}:
        raise _fail("sampling arm inventory mismatch")
    return Inventory(payload, spec, images, faces, psus, folds, identities, test, pools)


def _registry(firbench, decision):
    k = decision.fold_protocol.k
    if type(k) is not int or k < 2 or type(decision.fold_protocol.seed) is not int:
        raise _fail("declared fold protocol is required")
    rows = firbench.get("gallery_membership")
    if not isinstance(rows, list) or not rows:
        raise _fail("predeclared gallery_membership registry is required")
    result, shared = {}, {}
    full_identity_folds = None
    for row in rows:
        key, fold = row["leg_key"], row["fold"]
        if key not in firbench["leg_keys"] or type(fold) is not int or not 0 <= fold < k:
            raise _fail("gallery registry leg/fold mismatch")
        fc._require_sha(row["gallery_sha256"], "gallery_sha256")
        ids = row["enrolled_identity_ids"]
        identity_folds = row["identity_folds"]
        if not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise _fail("enrolled_identity_ids must explicitly declare unique identities (empty allowed)")
        if (
            not isinstance(identity_folds, dict)
            or any(not isinstance(i, str) or type(f) is not int or not 0 <= f < k for i, f in identity_folds.items())
            or not set(ids) <= set(identity_folds)
        ):
            raise _fail("gallery requires full identity fold provenance")
        if full_identity_folds is not None and identity_folds != full_identity_folds:
            raise _fail("contradictory gallery identity fold provenance")
        full_identity_folds = identity_folds
        if (key, fold) in result:
            raise _fail("duplicate gallery registry row")
        membership = frozenset(ids)
        if fold in shared and shared[fold] != membership:
            raise _fail("native legs must share declared gallery membership")
        shared[fold] = membership
        for identity, labels in row.get("enrolled_occluders", {}).items():
            if identity not in membership:
                raise _fail("enrolled occluder identity is outside gallery")
            occluder_label(labels)
        result[key, fold] = row
    if set(result) != {(key, fold) for key in firbench["leg_keys"] for fold in range(k)}:
        raise _fail("gallery registry must cover every leg and query fold")
    return result, shared


def _records(run_dir, firbench, inventory, registry):
    records = []
    for key in sorted(firbench["leg_keys"]):
        if Path(key).name != key or key in {".", ".."}:
            raise _fail("unsafe leg_key")
        path = run_dir / "legs" / key / "searches.jsonl"
        try:
            lines = path.read_text().splitlines()
        except OSError as exc:
            raise _fail(f"missing searches for {key}") from exc
        seen = set()
        for line in lines:
            raw = json.loads(line, object_pairs_hook=fc._reject_duplicate_keys, parse_constant=fc._reject_non_finite)
            fc.validate_interchange("face-search-record-v1", raw)
            image = inventory.images.get(raw["image_id"])
            if image is None:
                raise _fail("search image outside persisted inventory")
            psu = inventory.psus[image.image_id]
            fold = inventory.folds[psu]
            declaration = registry[key, fold]
            if (
                raw["leg_key"] != key
                or raw["psu_id"] != psu
                or raw["fold"] != fold
                or raw["fold_role"] != ("test" if fold == inventory.test_fold else "fit")
            ):
                raise _fail("search leg/PSU/fold binding mismatch")
            if len(key.split("__")) != 5 or raw["arm"] != key.split("__")[1]:
                raise _fail("search pipeline arm differs from leg key")
            if raw["timing_receipt_ref"] is not None and raw["timing_receipt_ref"] != (
                f"{key}/{raw['arm']}/{raw['face_id']}"
            ):
                raise _fail("search timing receipt reference binding mismatch")
            if raw["gallery_sha256"] != declaration["gallery_sha256"]:
                raise _fail("search gallery SHA mismatch")
            if raw["sampling_arm"] != image.sampling_arm or raw["inclusion_probability"] != image.inclusion_probability:
                raise _fail("search sampling provenance mismatch")
            token = (raw["face_id"], raw["arm"])
            if token in seen:
                raise _fail("duplicate face/arm search")
            seen.add(token)
            if any(name not in declaration["enrolled_identity_ids"] for name, score in raw["top_k"]):
                raise _fail("search result identity outside declared gallery")
            face = inventory.faces.get(raw["face_id"])
            if face is not None:
                mated = face.identity_id in declaration["enrolled_identity_ids"] if face.identity_id else False
                if (
                    raw["image_id"] != face.image_id
                    or raw["identity_status"] != face.identity_status
                    or raw["identity_id"] != (face.identity_id if mated else None)
                    or raw["unit_id"] != (
                        None if mated or face.identity_status is fc.IdentityStatus.unresolved else face.face_id
                    )
                ):
                    raise _fail("search GT identity/unit binding mismatch")
                if raw["cohort"] != (None if face.cohort is None else face.cohort.to_json()):
                    raise _fail("search cohort differs from GT annotation")
                expected = (
                    occluder_label(face.annotation.occluders),
                    occluder_label(declaration.get("enrolled_occluders", {}).get(face.identity_id)),
                )
                if tuple(raw["cell"]) != expected:
                    raise _fail("search cell differs from GT query/enrolled labels")
            elif raw["unit_id"] not in (None, f"background:{image.image_id}") or raw["identity_id"] is not None:
                raise _fail("detector-only row cannot mint a GT source unit")
            values = dict(raw)
            values.pop("schema_version")
            for name, enum in (
                ("identity_status", fc.IdentityStatus),
                ("fold_role", fc.FoldRole),
                ("sampling_arm", fc.SamplingArm),
                ("arm", fc.Arm),
                ("arm_availability", fc.ArmStatus),
                ("alignment_mode", fc.AlignmentMode),
            ):
                values[name] = enum(values[name])
            values["stage_reached"] = None if raw["stage_reached"] is None else fc.SearchStage(raw["stage_reached"])
            values["top_k"] = tuple((name, _finite(score, "top-k score")) for name, score in raw["top_k"])
            values["cell"] = tuple(raw["cell"])
            records.append(FaceSearchRecord(**values))
        arms = {fc.Arm(key.split("__")[1])}
        for arm in arms:
            actual = {r.face_id for r in records if r.leg_key == key and r.arm == arm and r.face_id in inventory.faces}
            if actual != set(inventory.faces):
                raise _fail("search ledger must represent every GT face, including misses/unavailable")
    return records


def _units(inventory, fold, sampling_arm):
    # Core's protocol expects cohort mappings, whereas S1 owns typed Cohort objects.
    rows = []
    for unit in inventory.pools[fold].units:
        image_id = (
            inventory.faces[unit.unit_id].image_id
            if unit.unit_id in inventory.faces
            else unit.unit_id.removeprefix("background:")
        )
        if inventory.images[image_id].sampling_arm is sampling_arm:
            rows.append(
                SimpleNamespace(
                    unit_id=unit.unit_id,
                    psu_id=unit.psu_id,
                    fold=unit.fold,
                    cohort=None if unit.cohort is None else unit.cohort.to_json(),
                )
            )
    return rows


def _mated(records):
    return [r for r in records if core._is_mated(r) and r.arm_availability is fc.ArmStatus.available]


def _interval(rows, tau, decision, *, min_psus=None):
    psus = [r.psu_id for r in rows]
    if len(set(psus)) < (decision.min_n_independent if min_psus is None else min_psus):
        return _result(reason="insufficient_independent_psus")
    outcomes = core.finish_outcomes(rows, tau, decision.boundary_semantics)
    ci = core.paired_cluster_bootstrap(
        outcomes,
        [fc.FaceOutcome.correct] * len(rows),
        psus,
        weights=[core._weight(r) for r in rows],
        n_boot=decision.interval.n_boot,
        seed=decision.interval.seed,
        level=0.95,
    )
    return _result({"lower": ci.lower, "upper": ci.upper, "level": ci.level, "method": "psu_percentile"})


def _operating(records, units, tau, decision):
    if tau is None:
        return {"fnir": _result(reason="calibration_unavailable"), "fpir": _result(reason="calibration_unavailable")}
    mated = _mated(records)
    fnir = _result(reason="no_available_mated_queries")
    if mated:
        outcomes = core.finish_outcomes(mated, tau, decision.boundary_semantics)
        weights = [core._weight(r) for r in mated]
        misses = [o is not fc.FaceOutcome.correct for o in outcomes]
        psus = [r.psu_id for r in mated]
        neff = core._n_eff(psus, decision.planning_icc)
        fnir = _result(
            {
                "misses": sum(misses),
                "n_mated": len(mated),
                "n_eff": neff,
                "design_effect": len(mated) / neff,
                "rate": sum(w * m for w, m in zip(weights, misses, strict=True)) / sum(weights),
                "interval": _interval(mated, tau, decision),
            }
        )
    fpir = _result(reason="empty_nonmated_pool")
    if units:
        if any(r.unit_id is not None and r.arm_availability is not fc.ArmStatus.available for r in records):
            return {"fnir": fnir, "fpir": _result(reason="native_nonmated_search_unavailable")}
        point = core.curve(records, units=units, thresholds=[tau], boundary=decision.boundary_semantics)[0]
        psus = [u.psu_id for u in units]
        neff = core._n_eff(psus, decision.planning_icc)
        flags = {
            r.unit_id
            for r in records
            if r.unit_id is not None
            and r.arm_availability is fc.ArmStatus.available
            and core._nonmated_outcome(r, tau, decision.boundary_semantics) is fc.FaceOutcome.false_accept
        }
        eligible = len(set(psus)) >= decision.min_n_independent
        bound = _result(reason="insufficient_independent_psus")
        if eligible:
            b = core.fpir_upper_bound(
                fpi=point.fpi,
                n_units=len(units),
                n_nonmated_eff=neff,
                planning_psu_ids=psus,
                unit_false_accept=[u.unit_id in flags for u in units],
                n_boot=decision.interval.n_boot,
                seed=decision.interval.seed,
            )
            bound = _result({"upper": b.upper, "level": b.level, "method": b.method, "approximate": b.approximate})
        fpir = _result(
            {
                "fpi": point.fpi,
                "n_units": len(units),
                "n_nonmated_eff": neff,
                "rate": point.fpir,
                "iid_ucl": _result(
                    {
                        "upper": core.clopper_pearson_upper(point.fpi, len(units)),
                        "level": 0.95,
                        "method": "clopper_pearson",
                        "approximate": True,
                    }
                )
                if eligible
                else _result(reason="insufficient_independent_psus"),
                "clustered_ucl": bound,
            }
        )
    return {"fnir": fnir, "fpir": fpir}


def _calibrate(records, units, identity_folds, fit_folds, decision):
    if not units:
        return None, _result(reason="empty_calibration_pool")
    if any(r.unit_id is not None and r.arm_availability is not fc.ArmStatus.available for r in records):
        return None, _result(reason="fit_nonmated_search_unavailable")
    try:
        tau = core.calibrate_tau(
            records,
            units=units,
            calibration_folds=fit_folds,
            identity_folds=identity_folds,
            fpir_target=decision.primary.fpir_target,
            boundary=decision.boundary_semantics,
        )
    except TypeError as exc:
        raise _fail("S3 MCP16810 identity_folds interface is not installed") from exc
    except fc.TauInfeasibleError:
        return None, _result(reason="tau_infeasible")
    point = core.curve(records, units=units, thresholds=[tau], boundary=decision.boundary_semantics)[0]
    fold_taus = []
    for fold in sorted(fit_folds):
        subset = [u for u in units if u.fold == fold]
        if not subset:
            continue
        try:
            value = core.calibrate_tau(
                [r for r in records if r.fold == fold],
                units=subset,
                calibration_folds=fit_folds,
                identity_folds=identity_folds,
                fpir_target=decision.primary.fpir_target,
                boundary=decision.boundary_semantics,
            )
            fold_taus.append(value)
        except fc.TauInfeasibleError:
            pass
    lower = math.nextafter(tau, -math.inf)
    next_point = core.curve(records, units=units, thresholds=[lower], boundary=decision.boundary_semantics)[0]
    return tau, _result(
        {
            "value": tau,
            "calibration_spread": max(fold_taus) - min(fold_taus) if fold_taus else 0.0,
            "pooled_units": len(units),
            "fpi_at_tau": {"count": point.fpi, "rate": point.fpir},
            "fpi_next_lower": _result(
                {
                    "threshold": lower,
                    "count": next_point.fpi,
                    "rate": next_point.fpir,
                    "fnir": _result(next_point.fnir)
                    if next_point.fnir is not None
                    else _result(reason="no_mated_fit_queries"),
                }
            ),
        }
    )


def data_origin(image, firbench):
    if image.synthetic_parent_id is not None:
        return "synthetic"
    declaration = firbench.get("data_origin_by_image", {}).get(image.image_id)
    # An explicit provenance reference is required for a real-data claim.
    if (
        isinstance(declaration, dict)
        and declaration.get("provenance_ref")
        and declaration.get("origin") in {"real", "synthetic"}
    ):
        return declaration["origin"]
    return "unknown"


def _cells(key, records, tau, inventory, firbench, decision):
    groups = defaultdict(list)
    for r in _mated(records):
        origin = data_origin(inventory.images[r.image_id], firbench)
        groups[(*r.cell, origin)].append(r)
    output = []
    for (query, enrolled, origin), rows in sorted(groups.items()):
        psus = [r.psu_id for r in rows]
        scored = tau is not None and len(set(psus)) >= decision.cell_floor_n_independent
        global_psus = {
            inventory.psus[i.image_id]
            for i in inventory.images.values()
            if i.sampling_arm is fc.SamplingArm.probability
            and inventory.folds[inventory.psus[i.image_id]] == inventory.test_fold
        }
        interval = (
            _interval(rows, tau, decision, min_psus=decision.cell_floor_n_independent)
            if scored and len(global_psus) >= decision.min_n_independent
            else None
        )
        outcomes = core.finish_outcomes(rows, tau, decision.boundary_semantics) if scored else ()
        weights = [core._weight(r) for r in rows]
        output.append(
            {
                "leg_key": key,
                "query_occluder": query,
                "enrolled_occluder": enrolled,
                "data_origin": origin,
                "n_units": len(rows),
                "n_identities": len({r.identity_id for r in rows}),
                "n_psu": len(set(psus)),
                "n_eff": core._n_eff(psus, decision.planning_icc),
                "scored": scored,
                "fnir": sum(w * (o is not fc.FaceOutcome.correct) for w, o in zip(weights, outcomes, strict=True))
                / sum(weights)
                if scored
                else None,
                "interval": None
                if interval is None or interval["data"] is None
                else {k: interval["data"][k] for k in ("lower", "upper", "level")},
            }
        )
    return output


def timing_exposure(receipt, records, inventory, key):
    """p95 of amortized image work per expected GT face (not detector rows).

    Within primary-test probability scope, each GT face gets its image's native
    work divided by that image's GT count, plus all empty-GT image work / N_GT.
    Exactly N_GT samples conserve all work; empty images create no bins. Returns
    RAM-only linear p95 in ms/GT_face; no GT faces means unscored.
    """
    costs = receipt.get("timing_receipt_ms")
    if not isinstance(costs, dict):
        return None, "timing_receipt_missing"
    known_refs = {r.timing_receipt_ref for r in records if r.leg_key == key and r.arm is fc.Arm.native}
    known_refs.update(f"{key}/native/image:{image_id}" for image_id in inventory.images)
    if any(ref.startswith(f"{key}/native/") and ref not in known_refs for ref in costs):
        return None, "unattributed_native_timing_cost"
    native = [
        r
        for r in records
        if r.leg_key == key
        and r.arm is fc.Arm.native
        and r.fold == inventory.test_fold
        and r.sampling_arm is fc.SamplingArm.probability
    ]
    refs = set()
    totals = Counter()
    for r in native:
        ref = r.timing_receipt_ref
        if not ref or ref in refs or ref not in costs:
            return None, "incomplete_or_duplicate_timing_receipt"
        refs.add(ref)
        value = _finite(costs[ref], "timing cost")
        if value < 0:
            raise _fail("negative timing cost")
        totals[r.image_id] += value
    samples = []
    empty_image_work = 0.0
    for image_id in inventory.images:
        if inventory.images[image_id].sampling_arm is not fc.SamplingArm.probability:
            continue
        if inventory.folds[inventory.psus[image_id]] != inventory.test_fold:
            continue
        overhead = f"{key}/native/image:{image_id}"
        if overhead in costs:
            value = _finite(costs[overhead], "image timing cost")
            if value < 0:
                raise _fail("negative image timing cost")
            totals[image_id] += value
        expected = sum(f.image_id == image_id for f in inventory.faces.values())
        if image_id not in totals:
            return None, "incomplete_timing_receipt"
        if expected:
            samples.extend([totals[image_id] / expected] * expected)
        else:
            empty_image_work += totals[image_id]
    if not samples:
        return None, "no_gt_face_timing_exposure"
    empty_share = empty_image_work / len(samples)
    samples = [value + empty_share for value in samples]
    return float(np.quantile(samples, 0.95, method="linear")), None


_RULE = re.compile(
    r"^\s*(?:(?P<metric>[a-z][a-z0-9_]*)\s*)?(?P<op><=|>=|<|>)\s*(?P<limit>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>[a-zA-Z0-9_/]+)?\s*$"
)
_UNITS = {
    "p95_ms_per_face": "ms/GT_face",
    "false_names_per_1k_mentions": "names/1000_mentions",
    "per_cohort_fpir": "rate",
    "worst_pair_cell_fnir": "rate",
    "cost_per_accepted_description": "cost/accepted_description",
}


def parse_rule(rule, metric):
    """Only explicit numeric comparisons are executable policy; prose stays unscored."""
    match = _RULE.fullmatch(rule or "")
    if not match or match["metric"] not in (None, metric):
        return None
    if match["unit"] not in (None, _UNITS.get(metric)):
        return None
    if metric == "p95_ms_per_face" and match["unit"] != _UNITS[metric]:
        return None  # historical per-detection/per-face timing units are ambiguous
    return match["op"], float(match["limit"])


def _guardrails(decision, firbench, contexts, cells, receipt, digest, inventory, all_records):
    output, readings = [], {}
    for guard in decision.guardrails:
        rule = parse_rule(guard.rule, guard.metric)
        candidates, reason = [], "missing_or_unknown_rule"
        evidence = {
            "leg_key": None,
            "cohort": None,
            "n_units": None,
            "n_psu": None,
            "n_eff": None,
            "limit": rule[1] if rule and guard.metric != "p95_ms_per_face" else None,
            "reason": reason,
        }
        if rule:
            reason = "missing_metric_data"
            for key, ctx in contexts.items():
                tau, rows, units = ctx["tau"], ctx["test"], ctx["units"]
                if tau is None:
                    reason = "calibration_unavailable"
                    candidates = []
                    break
                value = None
                local = dict(evidence, leg_key=key)
                if guard.metric == "p95_ms_per_face":
                    value, reason = timing_exposure(receipt, all_records, inventory, key)
                    local.update(
                        n_units=sum(f.image_id in {r.image_id for r in rows} for f in inventory.faces.values())
                    )
                elif guard.metric == "worst_pair_cell_fnir":
                    named = [
                        c
                        for c in cells
                        if c["leg_key"] == key
                        and c["query_occluder"] != "unknown"
                        and c["enrolled_occluder"] != "unknown"
                    ]
                    if not named or any(not c["scored"] for c in named):
                        reason = "named_cells_below_floor_or_absent"
                    else:
                        value = max(c["fnir"] for c in named)
                elif guard.metric == "false_names_per_1k_mentions":
                    denominator = firbench.get("external_mention_denominators", {}).get(key)
                    if denominator is not None and _finite(denominator, "mention denominator") > 0:
                        false_names = 0
                        for r in rows:
                            if r.arm_availability is not fc.ArmStatus.available:
                                continue
                            if r.identity_status is fc.IdentityStatus.unresolved:
                                # Either membership could apply. At a legacy tie a mate
                                # can emit a name even though a nonmate would reject it.
                                if any(
                                    core._accepts(score, tau, nonmated=False, boundary=decision.boundary_semantics)
                                    for name, score in r.top_k
                                ):
                                    reason = "unresolved_identity"
                                    break
                                # No possible accepted name: a known zero contribution
                                # to this count, without assigning an identity outcome.
                                continue
                            mated = core._is_mated(r)
                            false_names += sum(
                                name != r.identity_id or not mated
                                for name, score in r.top_k
                                if core._accepts(score, tau, nonmated=not mated, boundary=decision.boundary_semantics)
                            )
                        else:
                            value = false_names * 1000.0 / denominator
                    else:
                        reason = "external_mention_denominator_missing"
                elif guard.metric == "per_cohort_fpir":
                    if any(
                        (u.unit_id in inventory.faces and u.cohort is None)
                        or (u.cohort is not None and any(label is None for label in u.cohort.values()))
                        for u in units
                    ):
                        reason = "cohort_labels_unknown"
                        candidates = []
                        break
                    cohorts = defaultdict(list)
                    for u in units:
                        if u.cohort is not None:
                            for field, label in u.cohort.items():
                                cohorts[f"{field}={label if label is not None else 'unknown'}"].append(u)
                    if not cohorts:
                        reason = "cohort_nonmated_units_missing"
                        candidates = []
                    for cohort, group in sorted(cohorts.items()):
                        psus = [u.psu_id for u in group]
                        neff = core._n_eff(psus, decision.planning_icc)
                        if len(set(psus)) < decision.min_n_independent or not core.fpir_resolvable(
                            decision.primary.fpir_target, neff
                        ):
                            reason = "cohort_fpir_unresolvable"
                            candidates = []
                            break
                        selected = {u.unit_id for u in group}
                        point = core.curve(
                            [r for r in rows if r.unit_id in selected],
                            units=group,
                            thresholds=[tau],
                            boundary=decision.boundary_semantics,
                        )[0]
                        candidates.append(
                            (
                                point.fpir,
                                dict(local, cohort=cohort, n_units=len(group), n_psu=len(set(psus)), n_eff=neff),
                            )
                        )
                    if reason == "cohort_fpir_unresolvable":
                        break
                    # Background-only units remain global, never assigned to a face cohort.
                    if not cohorts:
                        break
                    continue
                elif guard.metric == "cost_per_accepted_description" and guard.role is fc.GuardrailRole.report_only:
                    cost = firbench.get("cost_report")
                    if isinstance(cost, dict) and cost.get("provenance_ref"):
                        total = _finite(cost.get("total_cost"), "total cost")
                        count = cost.get("accepted_descriptions")
                        if type(count) is int and count > 0 and total >= 0:
                            value = total / count
                if value is None:
                    candidates = []
                    break
                candidates.append((value, local))
        state, value = core.GuardrailState.unscored, None
        if candidates:
            op, limit = rule
            value, evidence = (
                max(candidates, key=lambda x: x[0]) if op in {"<", "<="} else min(candidates, key=lambda x: x[0])
            )
            passed = {"<=": value <= limit, "<": value < limit, ">=": value >= limit, ">": value > limit}[op]
            state = core.GuardrailState.pass_ if passed else core.GuardrailState.fail
            evidence["reason"] = None
        else:
            evidence["reason"] = reason
        readings[guard.id] = core.GuardrailReading(state, value)
        output.append(
            {
                "id": guard.id,
                "metric": guard.metric,
                "role": guard.role.value,
                "state": state.value,
                "value": None if guard.metric == "p95_ms_per_face" else value,
                "timings_sha256": digest if guard.metric == "p95_ms_per_face" else None,
                "evidence": evidence,
            }
        )
    return output, readings


def _joint_gaps(key, native, all_records, tau, inventory, decision):
    output = []
    for arm in (fc.Arm.gt_crop_redetect, fc.Arm.cached_yunet_landmark_replay):
        space = key.split("__")
        attr = [
            r
            for r in all_records
            if r.arm is arm
            and r.leg_key.split("__")[0] == space[0]
            and r.leg_key.split("__")[2:] == space[2:]
            and r.fold == inventory.test_fold
            and r.sampling_arm is fc.SamplingArm.probability
        ]
        left = {r.face_id: r for r in native if r.face_id in inventory.faces and core._is_mated(r)}
        right = {r.face_id: r for r in attr if r.face_id in left}
        pairs = [
            f
            for f in sorted(left)
            if f in right
            and left[f].arm_availability is fc.ArmStatus.available
            and right[f].arm_availability is fc.ArmStatus.available
        ]
        psus = [left[f].psu_id for f in pairs]
        reason = (
            "calibration_unavailable"
            if tau is None
            else "attribution_arm_not_run"
            if not attr
            else "insufficient_independent_psus"
            if len(set(psus)) < decision.min_n_independent
            else None
        )
        ci = None
        if reason is None:
            ci = core.paired_cluster_bootstrap(
                core.finish_outcomes([left[f] for f in pairs], tau, decision.boundary_semantics),
                core.finish_outcomes([right[f] for f in pairs], tau, decision.boundary_semantics),
                psus,
                weights=[core._weight(left[f]) for f in pairs],
                n_boot=decision.interval.n_boot,
                seed=decision.interval.seed,
                level=0.95,
            )
        output.append(
            {
                "leg_key": key,
                "arm": arm.value,
                "scored": ci is not None,
                "reason": reason,
                "n_pairs": len(pairs),
                "n_psu": len(set(psus)),
                "n_eff": core._n_eff(psus, decision.planning_icc),
                "delta": None if ci is None else ci.delta,
                "interval": None if ci is None else {"lower": ci.lower, "upper": ci.upper, "level": ci.level},
                "unavailable_counts": {
                    "native": sum(r.arm_availability is not fc.ArmStatus.available for r in left.values()),
                    "attribution": sum(
                        f not in right or right[f].arm_availability is not fc.ArmStatus.available for f in left
                    ),
                },
            }
        )
    return output


def _curve_points(records, units, tau, decision):
    """Descriptive empirical sweep after fit: exact ties plus finite endpoints.

    No threshold here feeds calibration or the verdict. Missing native source
    searches make FPIR unavailable, rather than manufacturing correct rejects.
    Task reference lines (.001/.01/.05) belong to the report's FPIR axis.
    """
    if (
        tau is None
        or not units
        or any(r.unit_id is not None and r.arm_availability is not fc.ArmStatus.available for r in records)
    ):
        return []
    scores = {float(score) for r in records if r.arm_availability is fc.ArmStatus.available for _, score in r.top_k}
    values = scores | {tau}
    thresholds = set(values)
    for value in values:
        thresholds.update(
            t for t in (math.nextafter(value, -math.inf), math.nextafter(value, math.inf)) if math.isfinite(t)
        )
    return [
        {"threshold": p.threshold, "fpir": p.fpir, "fnir": p.fnir}
        for p in core.curve(records, units=units, thresholds=sorted(thresholds), boundary=decision.boundary_semantics)
    ]


def _native_cohorts(contexts, decision):
    """Validate actual paired support before considering calibration availability."""
    cohorts = {fc.LegKind(key.split("__")[0]): _mated(c["test"]) for key, c in contexts.items()}
    for h in decision.hypotheses:
        for kind in h.legs:
            if kind not in cohorts:
                raise _fail(f"missing native hypothesis leg {kind}")
        left, right = ({r.face_id: (r.psu_id, core._weight(r)) for r in cohorts[kind]} for kind in h.legs)
        if left.keys() != right.keys():
            raise _fail("paired native legs must contain exactly the same mated GT face ids")
        if left != right:
            raise _fail("paired native legs carry different PSU ids or weights")
    return cohorts


def _unavailable_verdict(decision, results, cohorts):
    """Apply eligibility only when core's outcome arrays cannot represent a leg.

    Do not invent outcomes at an absent tau. Keep the same ratification, PSU,
    resolvability and unscored-veto precedence as core.decide; no interval is read.
    Available comparisons retain their real design sizes and MDE calculations.
    """
    try:
        fc.require_verdict_allowed(decision, frame=results.frame)
        ratified = True
    except fc.UnratifiedDecisionError:
        ratified = False
    psus = set(results.unit_psu_ids) | {r.psu_id for rows in cohorts.values() for r in rows}
    reason = (
        (
            fc.InconclusiveReason.insufficient_independent_psus
            if len(psus) < decision.min_n_independent
            else fc.InconclusiveReason.primary_fpir_unresolvable
            if not core.fpir_resolvable(
                decision.primary.fpir_target, core._n_eff(results.unit_psu_ids, decision.planning_icc)
            )
            else fc.InconclusiveReason.required_guardrail_unscored
        )
        if ratified
        else None
    )
    state = fc.VerdictState.inconclusive if ratified else fc.VerdictState.unratified
    hypotheses = []
    for step, h in enumerate(decision.hypotheses, 1):
        alpha = decision.alpha_family / (len(decision.hypotheses) - step + 1)
        neff = core._n_eff([r.psu_id for r in cohorts[h.legs[0]]], decision.planning_icc)
        mde = (
            None
            if any(kind not in results.legs for kind in h.legs)
            else core.minimum_detectable_effect(
                n_eff=neff, p_d=decision.p_d, power=decision.power, one_sided_alpha=alpha
            )
        )
        hypotheses.append(
            core.HypothesisVerdict(
                h.id,
                h.kind,
                step,
                alpha,
                1 - 2 * alpha,
                neff,
                mde,
                None,
                state if ratified else None,
                reason,
            )
        )
    path = f"eligibility:{reason.value}" if ratified else "unratified:numbers_only"
    return core.Verdict(results.frame.frame_id, state, reason, tuple(hypotheses), (path,))


def _decision_binding(firbench, decision, run_dir=None):
    digest = firbench["decision_sha256"]
    fc._require_sha(digest, "decision_sha256")
    # Derive authority from the actual private run location, never manifest metadata.
    repo = None
    if run_dir is not None:
        for parent in Path(run_dir).resolve().parents:
            if parent.name == "private" and parent.parent.name == "benchmarks":
                repo = parent.parent.parent
                break
    if repo is None and digest == fc.manifest_sha256(decision):
        return
    path = firbench.get("decision_path")
    if not path:
        raise _fail("decision digest does not bind supplied decision")
    if repo is None:
        repo = Path(__file__).resolve().parents[4]
    target = (repo / path).resolve()
    if not target.is_relative_to(repo):
        raise _fail("decision_path escapes repository")
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest or fc.load_decision_manifest(target) != decision:
        raise _fail("decision digest does not bind supplied decision")


def _face_outcomes(records, inventory, registry, contexts, boundary):
    """Join validated GT searches to their native tau, without changing inference.

    Fit rows expose provenance only. Attribution arms use the matching native
    embedding space's frozen threshold; detector-only searches remain in the raw
    ledgers and background accounting, never in this GT inventory view.
    """
    output = []
    for record in sorted(records, key=lambda r: (r.leg_key, r.face_id)):
        face = inventory.faces.get(record.face_id)
        if face is None:
            continue
        declaration = registry[record.leg_key, record.fold]
        mated = (
            None
            if face.identity_status is fc.IdentityStatus.unresolved
            else face.identity_id in declaration["enrolled_identity_ids"]
        )
        native = record.leg_key.split("__")
        native[1] = fc.Arm.native.value
        tau = contexts.get("__".join(native), {}).get("tau")
        outcome = None
        if record.fold_role is fc.FoldRole.fit:
            reason = "fit_fold_not_scored"
        elif record.arm_availability is not fc.ArmStatus.available:
            reason = "arm_unavailable"
        elif mated is None:
            reason = "unresolved_identity"
        elif tau is None:
            reason = "calibration_unavailable"
        else:
            outcome = core._outcome(record, tau, boundary)
            reason = None if outcome is not None else "outcome_unavailable"
        output.append(
            {
                "face_id": face.face_id,
                "image_id": face.image_id,
                "psu_id": inventory.psus[face.image_id],
                "fold": record.fold,
                "fold_role": record.fold_role.value,
                "sampling_arm": inventory.images[face.image_id].sampling_arm.value,
                "leg_key": record.leg_key,
                "arm": record.arm.value,
                "arm_availability": record.arm_availability.value,
                "stage_reached": None if record.stage_reached is None else record.stage_reached.value,
                "identity_status": face.identity_status.value,
                "mated": mated,
                "cell": list(record.cell),
                "outcome": None if outcome is None else outcome.value,
                "outcome_available": outcome is not None,
                "outcome_reason": reason,
            }
        )
    return output


def _score_run(run_dir: Path, *, decision: fc.DecisionManifest, pair_scores=None) -> dict:
    """Assemble validated scores-v1 from an already-spent persisted run.

    No CLI adapter, image read, wall clock, output write or receipt rewrite occurs.
    A missing concurrent producer contract is an explicit integration refusal.
    """
    run_dir = Path(run_dir)
    payload = _json(run_dir / "frame.json")
    firbench = _json(run_dir / "manifest.json")["firbench"]
    _decision_binding(firbench, decision, run_dir)
    if len(set(firbench["leg_keys"])) != len(firbench["leg_keys"]):
        raise _fail("duplicate run leg keys")
    registry, enrolled = _registry(firbench, decision)
    inventory = _inventory(payload, decision, enrolled)
    if firbench["frame"] != {
        n: payload[n] for n in ("frame_id", "admissibility", "sealed", "source_sha256", "exhaustive")
    }:
        raise _fail("run manifest frame binding mismatch")
    for row in registry.values():
        if any(row["identity_folds"].get(i) != f for i, f in inventory.identity_folds.items()):
            raise _fail("gallery identity fold map contradicts full frame provenance")
    all_records = _records(run_dir, firbench, inventory, registry)
    timing_path = run_dir / "timings.json"
    try:
        timing_bytes = timing_path.read_bytes()
    except OSError:
        timing_bytes = None
    receipt = (
        {}
        if timing_bytes is None
        else json.loads(timing_bytes, object_pairs_hook=fc._reject_duplicate_keys, parse_constant=fc._reject_non_finite)
    )
    digest = None if timing_bytes is None else hashlib.sha256(timing_bytes).hexdigest()
    k = decision.fold_protocol.k
    fit = frozenset(set(range(k)) - {inventory.test_fold})
    contexts, legs, cells, curves, waterfall, gaps = {}, [], [], [], [], []
    arrays = {}
    for key in sorted(firbench["leg_keys"]):
        rows = [r for r in all_records if r.leg_key == key and r.arm is fc.Arm.native]
        if not rows:
            continue
        kind = fc.LegKind(key.split("__")[0])
        if any(fc.LegKind(existing.split("__")[0]) is kind for existing in contexts):
            raise _fail("multiple native embedding spaces for one hypothesis leg")
        probability = [r for r in rows if r.sampling_arm is fc.SamplingArm.probability]
        test = [r for r in probability if r.fold == inventory.test_fold]
        fit_rows = [r for r in probability if r.fold in fit]
        fit_units = [u for fold in sorted(fit) for u in _units(inventory, fold, fc.SamplingArm.probability)]
        full_map = registry[key, inventory.test_fold]["identity_folds"]
        tau, calibration = _calibrate(fit_rows, fit_units, full_map, fit, decision)
        units = _units(inventory, inventory.test_fold, fc.SamplingArm.probability)
        contexts[key] = {"tau": tau, "test": test, "units": units}
        legs.append(
            {
                "leg_key": key,
                "tau": calibration,
                "operating_point": _operating(test, units, tau, decision),
                "pair_fmr": pair_fmr(
                    None if pair_scores is None else pair_scores.get(key), tau=tau, boundary=decision.boundary_semantics
                ),
            }
        )
        mated = _mated(test)
        if tau is not None:
            arrays[kind] = core.LegArrays(
                kind,
                tuple(r.face_id for r in mated),
                core.finish_outcomes(mated, tau, decision.boundary_semantics),
                tuple(r.psu_id for r in mated),
                tuple(core._weight(r) for r in mated),
            )
        # Challenge records are deliberately separate from all confirmatory inference.
        # The frozen wire has no sampling-arm axis: publish them under explicit arm-qualified
        # descriptive keys; never put their outcomes or units in arrays/contexts.
        for sampling in fc.SamplingArm:
            selected = [r for r in rows if r.fold == inventory.test_fold and r.sampling_arm is sampling]
            label = key if sampling is fc.SamplingArm.probability else f"{key}::sampling=challenge"
            cells.extend(_cells(label, selected, tau, inventory, firbench, decision))
            selected_units = _units(inventory, inventory.test_fold, sampling)
            curves.append({"leg_key": label, "points": _curve_points(selected, selected_units, tau, decision)})
            counts = Counter(
                r.stage_reached.value
                for r in selected
                if core._is_mated(r) and r.arm_availability is fc.ArmStatus.available and r.stage_reached is not None
            )
            waterfall.extend(
                {"leg_key": label, "arm": "native", "stage": stage, "count": count}
                for stage, count in sorted(counts.items())
            )
        gaps.extend(_joint_gaps(key, test, all_records, tau, inventory, decision))
    if not contexts:
        raise _fail("no native leg searches")
    cohorts = _native_cohorts(contexts, decision)
    guardrails, readings = _guardrails(decision, firbench, contexts, cells, receipt, digest, inventory, all_records)
    # Missing thresholds are a real eligibility gap even if no user guardrail happens to name it.
    # Refuse instead of passing empty arrays to a statistical test.
    unscored_veto = any(
        g.role is fc.GuardrailRole.veto and readings[g.id].state is core.GuardrailState.unscored
        for g in decision.guardrails
    )
    if any(c["tau"] is None for c in contexts.values()) and not unscored_veto:
        raise _fail("calibration unavailable: cannot build the complete hypothesis verdict")
    h2 = next(
        (
            leg
            for h in decision.hypotheses
            if h.kind is fc.HypothesisKind.non_inferiority
            for leg in h.legs
            if leg in (fc.LegKind.sface, fc.LegKind.auraface)
        ),
        decision.primary.comparison[1],
    )
    units = next(iter(contexts.values()))["units"]
    unit_psus = tuple(u.psu_id for u in units)
    results = core.LegResults(inventory.spec, arrays, unit_psus, h2, readings)
    verdict = (
        _unavailable_verdict(decision, results, cohorts)
        if any(c["tau"] is None for c in contexts.values())
        else core.decide(decision, results)
    )
    # Count each actual mated GT query once across legs; availability may differ.
    support = {}
    for rows in cohorts.values():
        support.update({r.face_id: r.psu_id for r in rows})
    psus = tuple(support[f] for f in sorted(support))
    n_eff = core._n_eff(psus, decision.planning_icc)
    neff_units = core._n_eff(unit_psus, decision.planning_icc)
    sensitivity = []
    for icc in core.ICC_SENSITIVITY_ROWS:
        hypotheses = []
        for step, h in enumerate(decision.hypotheses, 1):
            neff = core._n_eff([r.psu_id for r in cohorts[h.legs[0]]], icc)
            mde = (
                None
                if any(kind not in arrays for kind in h.legs)
                else core.minimum_detectable_effect(
                    n_eff=neff,
                    p_d=decision.p_d,
                    power=decision.power,
                    one_sided_alpha=decision.alpha_family / (len(decision.hypotheses) - step + 1),
                )
            )
            hypotheses.append({"id": h.id, "scored": mde is not None, "mde": mde, "n_eff": neff})
        sensitivity.append(
            {
                "planning_icc": icc,
                "design_effect": core._design_effect(psus, icc) if psus else 1.0,
                "n_eff": core._n_eff(psus, icc),
                "n_nonmated_eff": core._n_eff(unit_psus, icc),
                "primary_resolvable": core.fpir_resolvable(decision.primary.fpir_target, core._n_eff(unit_psus, icc)),
                "hypotheses": hypotheses,
            }
        )
    output = {
        "schema_version": 1,
        "decision_sha256": firbench["decision_sha256"],
        "frame_id": inventory.spec.frame_id,
        "admissibility": inventory.spec.admissibility.value,
        "boundary_semantics": decision.boundary_semantics.value,
        "n_psu": len(set(psus) | set(unit_psus)),
        "min_n_independent": decision.min_n_independent,
        "cell_floor_n_independent": decision.cell_floor_n_independent,
        "p_d": decision.p_d,
        "power": decision.power,
        "planning_icc": decision.planning_icc,
        "design_effect": len(psus) / n_eff if psus else 1.0,
        "n_eff": n_eff,
        "n_units": len(units),
        "n_nonmated_eff": neff_units,
        "icc_sensitivity": sensitivity,
        "primary": {
            "fpir_target": decision.primary.fpir_target,
            "resolvable": core.fpir_resolvable(decision.primary.fpir_target, neff_units),
            "required_n_nonmated_eff": 3.0 / decision.primary.fpir_target,
        },
        "verdict": {"state": verdict.state.value, "reason": None if verdict.reason is None else verdict.reason.value},
        "decision_path": list(verdict.decision_path),
        "hypotheses": [
            {
                "id": h.id,
                "kind": h.kind.value,
                "step_index": h.step_index,
                "one_sided_alpha": h.one_sided_alpha,
                "mde": h.mde,
                "n_eff": h.n_eff,
                "interval": None
                if h.interval is None
                else {"lower": h.interval.lower, "upper": h.interval.upper, "level": h.interval.level},
                "state": None if h.state is None else h.state.value,
                "reason": None if h.reason is None else h.reason.value,
            }
            for h in verdict.hypotheses
        ],
        "guardrails": guardrails,
        "legs": legs,
        "cells": cells,
        "curves": curves,
        "waterfall": waterfall,
        "joint_gaps": gaps,
        "face_outcomes": _face_outcomes(all_records, inventory, registry, contexts, decision.boundary_semantics),
    }
    fc.validate_interchange("scores-v1", output)
    return output


def score_run(run_dir: Path, *, decision: fc.DecisionManifest, pair_scores=None) -> dict:
    """Read persisted evidence and return validated scores-v1; never reopen pixels."""
    try:
        return _score_run(run_dir, decision=decision, pair_scores=pair_scores)
    except fc.FrameContractError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise _fail(f"invalid persisted scoring evidence: {exc}") from exc
