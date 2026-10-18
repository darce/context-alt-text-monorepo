"""S7 evidence gates. All pixels/actors/answers here are generated test fixtures.

No fixture asserts that a human observation occurred. Production observation
coverage is refusal coverage; recovery is exercised through the synthetic boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scene.tests import test_eval_harness_fir_occ_labels as base
from scripts.eval_harness import fir_occ_labels as occ
from scripts.eval_harness.firbench_contract import FrameContractError

QC = {
    "gold_share": 0.10,
    "repeat_fraction": 0.10,
    "repeat_percent_agreement_floor": 0.90,
    "kappa_floor": 0.80,
    "annotator_gold_accuracy_floor": 0.90,
    "min_gold_decisions_per_annotator": 20,
    "min_repeat_decisions_per_field": 20,
}


def recipe(seed):
    return {"generator_id": "numpy-rgb8/v1", "seed": seed}


def pixel_sha(seed):
    pixels = np.random.default_rng(seed).integers(0, 255, size=(8, 8, 3), dtype=np.uint8)
    return hashlib.sha256(base._png(pixels)).hexdigest()


def generated(doc, *, offset=0):
    doc["data_origin"] = "generated_fixture"
    for k, item in enumerate(doc["items"]):
        item["data_origin"] = "generated_fixture"
        item["fixture_recipe"] = recipe(offset + k)
        item["image_sha256"] = pixel_sha(offset + k)
    return doc


def session(tmp_path, *, constant=False, recovering=False):
    qdoc = generated(base._queue_doc())
    qdoc["qc"] = dict(QC)
    if recovering:
        qdoc["acceptance_path"] = "acceptance.json"
    gdoc = generated(base._gold_doc(), offset=5000)
    if constant:
        for g in gdoc["items"]:
            g["faces"] = base._answer_faces(0)
    qpath, gpath, epath = (tmp_path / name for name in ("queue.json", "gold.json", "export.json"))
    qsha = base._write_json(qpath, qdoc)
    base._write_json(gpath, gdoc)
    edoc = base._export_doc(qdoc, qsha, gdoc)
    if constant:
        for a in edoc["answers"]:
            a["faces"] = base._answer_faces(0)
    base._write_json(epath, edoc)
    return qdoc, gdoc, edoc, qpath, gpath, epath


def load(paths):
    _, _, _, qpath, gpath, epath = paths
    return occ.load_label_export(epath), occ.load_queue(qpath, gpath)


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.mark.parametrize("reference", [None, "missing-record.json"])
def test_production_rejects_null_or_unresolved_observation(tmp_path, reference):
    paths = session(tmp_path)
    paths[2]["observation_ref"] = reference
    base._write_json(paths[-1], paths[2])
    export, queue = load(paths)
    with pytest.raises(FrameContractError, match="observation"):
        occ.to_face_instances(export, queue)


def test_production_has_no_bypass(tmp_path):
    paths = session(tmp_path)
    export, queue = load(paths)
    with pytest.raises(TypeError):
        occ.to_face_instances(export, queue, allow_unobserved_fixture=True)


def test_canonical_seven_keys_and_old_alias_refusal(tmp_path):
    paths = session(tmp_path)
    export, queue = load(paths)
    assert queue.qc == QC
    assert occ.to_synthetic_face_instances(export, queue)
    for key in QC:
        bad = copy.deepcopy(paths[0])
        del bad["qc"][key]
        base._write_json(paths[3], bad)
        with pytest.raises(FrameContractError, match="qc"):
            occ.load_queue(paths[3], paths[4])
    bad["qc"] = {**QC, "field_agreement_floor": 0.90}
    base._write_json(paths[3], bad)
    with pytest.raises(FrameContractError, match="qc"):
        occ.load_queue(paths[3], paths[4])


@pytest.mark.parametrize(
    "mutation", ["root", "mixed", "hash", "recipe", "source", "root_source", "gold_origin", "gold"]
)
def test_synthetic_boundary_rejects_relabelled_real_unknown_and_tampered_inputs(tmp_path, mutation):
    paths = session(tmp_path)
    qdoc, gdoc, edoc, qpath, gpath, epath = paths
    if mutation == "root":
        qdoc["data_origin"] = "real"
    elif mutation == "mixed":
        qdoc["items"][100]["data_origin"] = "unknown"
    elif mutation == "hash":
        qdoc["items"][0]["image_sha256"] = "0" * 64
    elif mutation == "recipe":
        qdoc["items"][0]["fixture_recipe"]["generator_id"] = "load-real-image"
    elif mutation == "source":
        qdoc["items"][0]["source_ref"] = "private-original"
    elif mutation == "root_source":
        qdoc["image_loader"] = "arbitrary-loader"
    elif mutation == "gold_origin":
        gdoc["data_origin"] = "unknown"
    else:
        gdoc["items"][0]["data_origin"] = "real"
    edoc["queue_sha256"] = base._write_json(qpath, qdoc)
    base._write_json(gpath, gdoc)
    base._write_json(epath, edoc)
    with pytest.raises(FrameContractError):
        export, queue = load(paths)
        occ.to_synthetic_face_instances(export, queue)


def test_synthetic_rows_are_persistently_ineligible_for_real_analysis(tmp_path):
    export, queue = load(session(tmp_path))
    rows = occ.to_synthetic_face_instances(export, queue)
    assert all(r["synthetic"] is True and r["analysis_eligible"] is False for r in rows)
    with pytest.raises(FrameContractError, match="synthetic"):
        occ.require_real_analysis_rows(rows)
    with pytest.raises(FrameContractError):
        occ.to_face_instances(export, queue)


def recovery(tmp_path, *, constant=False):
    paths = session(tmp_path, constant=constant, recovering=True)
    qdoc, gdoc, original, qpath, gpath, epath = paths
    if not constant:
        # Historical failure. Correct a primary without editing its old repeat.
        for a in original["answers"][:5]:
            a["faces"][0]["visibility"]["left_eye"] = "uncertain"
    prior_path = tmp_path / "prior.json"
    base._write_json(prior_path, original)
    candidate = copy.deepcopy(original)
    if not constant:
        for k, a in enumerate(candidate["answers"][:5]):
            a["faces"] = base._answer_faces(k)
    else:
        candidate["observation_ref"] = "fixture-only:no-human-observation"
    candidate_sha = base._write_json(epath, candidate)
    vq = generated(base._queue_doc())
    vq["qc"] = dict(QC)
    vq["queue_id"] = "fresh-validation"
    vg = generated(base._gold_doc(authored_by="independent-qc-author"), offset=10000)
    for k, g in enumerate(vg["items"]):
        g["gold_id"] = f"fresh-gold-{k}"
        g["media_id"] = f"fresh-media-{k}"
        if constant:
            g["faces"] = base._answer_faces(0)
    vqpath, vgpath, vepath = (tmp_path / n for n in ("validation-queue.json", "fresh-gold.json", "fresh-answers.json"))
    vqsha = base._write_json(vqpath, vq)
    base._write_json(vgpath, vg)
    ve = base._export_doc(vq, vqsha, vg)
    if constant:
        for a in ve["answers"]:
            a["faces"] = base._answer_faces(0)
    old_ids = list(ve["hidden"]["presented"])
    remap = {pid: f"new-{pid}" for pid in old_ids}
    ve["hidden"]["presented"] = {
        remap[pid]: {**record, "of": remap.get(record["of"])} for pid, record in ve["hidden"]["presented"].items()
    }
    for answer in ve["answers"]:
        answer["presented_id"] = remap[answer["presented_id"]]
    base._write_json(vepath, ve)
    prior = occ.load_label_export(prior_path)
    queue = occ.load_queue(qpath, gpath)
    evidence = {
        "schema": "fir-occ-acceptance/v1",
        "candidate_sha256": candidate_sha,
        "prior_export": ref(prior_path),
        "original_qc": occ.qc_report(prior, queue),
        "declaration": {
            "run_id": "new-run",
            "candidate_sha256": candidate_sha,
            "rule_id": base.RULE,
            "disagreement_rule": "fixture-disagreement/v2",
            "qc": dict(QC),
            "scope": [i["item_id"] for i in qdoc["items"]],
            "qc_author": "independent-qc-author",
            "evaluator": "ann-01",
            "declared_before_answers": True,
            "independently_blinded": True,
            "prior_answers_disclosed": False,
            "repair_examples_used_as_gold": False,
            "assignment": ve["hidden"]["presented"],
            "validation_queue_sha256": vqsha,
        },
        "validation_queue": ref(vqpath),
        "validation_gold": ref(vgpath),
        "validation_export": ref(vepath),
        "sme_resolutions": [],
    }
    if constant:
        for field in occ.repeat_agreement(prior):
            evidence["sme_resolutions"].append(
                {
                    "candidate_sha256": candidate_sha,
                    "field": field,
                    "item_ids": evidence["declaration"]["scope"],
                    "expert_id": "ann-01",
                    "disagreement_rule": "fixture-disagreement/v2",
                    "rationale": "diagnostic has one category",
                    "disposition": "accept_undefined_kappa",
                    "independent_validation": {
                        "method": "independent known answers for this field",
                        "denominator": 20,
                        "accuracy": 1.0,
                        "exceptions": [],
                        "limits": "generated fixtures only",
                    },
                }
            )
    base._write_json(tmp_path / "acceptance.json", evidence)
    return paths, evidence, prior_path, vepath


def test_fresh_supported_qc_accepts_corrected_candidate_without_rewriting_failed_run(tmp_path):
    paths, evidence, prior_path, _ = recovery(tmp_path)
    before = prior_path.read_bytes()
    export, queue = load(paths)
    assert evidence["original_qc"]["repair_item_ids"]
    rows = occ.to_synthetic_face_instances(export, queue)
    assert prior_path.read_bytes() == before
    assert rows[0]["acceptance"]["candidate_sha256"] == export.sha256
    assert rows[0]["pre_adjudication"]["faces"][0]["visibility"]["left_eye"] == "uncertain"
    assert rows[0]["annotation"]["visibility"]["left_eye"] != "uncertain"
    assert rows[0]["acceptance"]["original_qc"] == evidence["original_qc"]
    with pytest.raises(FrameContractError):
        occ.to_face_instances(export, queue)


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate",
        "old_support",
        "unblinded",
        "rewrite_qc",
        "scope",
        "worker",
        "weak_gold",
        "weak_repeat",
        "old_repeats",
    ],
)
def test_recovery_refuses_unqualified_evidence(tmp_path, mutation):
    paths, evidence, _, vepath = recovery(tmp_path)
    if mutation == "candidate":
        evidence["candidate_sha256"] = "0" * 64
    elif mutation == "old_support":
        evidence["validation_export"] = evidence["prior_export"]
    elif mutation == "unblinded":
        evidence["declaration"]["independently_blinded"] = False
    elif mutation == "rewrite_qc":
        evidence["original_qc"]["repair_item_ids"] = []
    elif mutation == "scope":
        evidence["declaration"]["scope"].pop()
    elif mutation == "worker":
        evidence["declaration"]["evaluator"] = "replacement-worker"
    else:
        ve = json.loads(vepath.read_text())
        if mutation == "old_repeats":
            evidence["declaration"]["assignment"] = paths[2]["hidden"]["presented"]
        else:
            role = "known_answer" if mutation == "weak_gold" else "consistency"
            a = next(a for a in ve["answers"] if ve["hidden"]["presented"][a["presented_id"]]["role"] == role)
            ve["answers"].remove(a)
            del ve["hidden"]["presented"][a["presented_id"]]
            base._write_json(vepath, ve)
            evidence["validation_export"] = ref(vepath)
            evidence["declaration"]["assignment"] = ve["hidden"]["presented"]
    base._write_json(tmp_path / "acceptance.json", evidence)
    with pytest.raises(FrameContractError):
        occ.to_synthetic_face_instances(*load(paths))


def test_supported_sme_resolves_undefined_diagnostic_without_fabricating_kappa(tmp_path):
    paths, evidence, _, _ = recovery(tmp_path, constant=True)
    export, queue = load(paths)
    rows = occ.to_synthetic_face_instances(export, queue)
    qc = rows[0]["acceptance"]["accepted_qc"]
    assert all(v["kappa"] is None and v["reason"] == "kappa_undefined" for v in qc["fields"].values())
    assert rows[0]["acceptance"]["sme_resolutions"] == evidence["sme_resolutions"]


@pytest.mark.parametrize("mutation", ["missing", "title_only", "support", "accuracy", "field", "candidate"])
def test_undefined_sme_cannot_waive_support_or_claim_expertise_by_title(tmp_path, mutation):
    paths, evidence, _, _ = recovery(tmp_path, constant=True)
    r = evidence["sme_resolutions"][0]
    if mutation == "missing":
        evidence["sme_resolutions"].pop()
    elif mutation == "title_only":
        r["expert_id"] = "titled-but-unvalidated-sme"
    elif mutation in {"support", "accuracy"}:
        r["independent_validation"]["denominator" if mutation == "support" else "accuracy"] = (
            19 if mutation == "support" else 0.89
        )
    elif mutation == "field":
        r["field"] = "unrelated-field"
    else:
        r["candidate_sha256"] = "0" * 64
    base._write_json(tmp_path / "acceptance.json", evidence)
    with pytest.raises(FrameContractError):
        occ.to_synthetic_face_instances(*load(paths))


def test_separately_qualified_sme_can_resolve_a_corrected_version(tmp_path):
    paths, evidence, prior_path, vepath = recovery(tmp_path)
    before = prior_path.read_bytes()
    evidence["declaration"].update(validation_kind="qualified_sme", evaluator="expert-fixture")
    vgpath = Path(evidence["validation_gold"]["path"])
    vg = json.loads(vgpath.read_text())
    for g in vg["items"]:
        g["live_queue_annotators"] = ["expert-fixture"]
    base._write_json(vgpath, vg)
    evidence["validation_gold"] = ref(vgpath)
    ve = json.loads(vepath.read_text())
    ve["annotator_id"] = "expert-fixture"
    base._write_json(vepath, ve)
    evidence["validation_export"] = ref(vepath)
    evidence["sme_resolutions"] = [
        {
            "candidate_sha256": evidence["candidate_sha256"],
            "field": "visibility.left_eye",
            "item_ids": evidence["declaration"]["scope"],
            "expert_id": "expert-fixture",
            "disagreement_rule": "fixture-disagreement/v2",
            "rationale": "generated corrected candidate verified",
            "disposition": "accept_corrected_field",
            "independent_validation": {
                "method": "fresh independent known answers for the corrected field",
                "denominator": 20,
                "accuracy": 1.0,
                "exceptions": [],
                "limits": "generated fixtures only",
            },
        }
    ]
    base._write_json(tmp_path / "acceptance.json", evidence)
    rows = occ.to_synthetic_face_instances(*load(paths))
    assert prior_path.read_bytes() == before
    assert rows[0]["pre_adjudication"]["faces"][0]["visibility"]["left_eye"] == "uncertain"
    assert rows[0]["acceptance"]["accepted_qc"]["annotators"]["expert-fixture"]["n"] == 20
    assert "ann-01" in rows[0]["acceptance"]["original_qc"]["annotators"]


def test_null_occluders_remain_distinct_from_explicit_empty_set(tmp_path):
    paths = session(tmp_path)
    paths[2]["answers"][150]["faces"][0]["occluders"] = None
    paths[2]["answers"][151]["faces"][0]["occluders"] = []
    base._write_json(paths[-1], paths[2])
    rows = {r["item_id"]: r for r in occ.to_synthetic_face_instances(*load(paths))}
    assert rows["img-0150"]["annotation"]["occluders"] is None
    assert rows["img-0151"]["annotation"]["occluders"] == []


def comparison(export, queue):
    # Context strings for structural comparison only: no human record is made.
    context = {
        "rule": base.RULE,
        "instructions": "fixture instructions",
        "operators": ["ann-01"],
        "collection_workflow": "fixture collection",
        "adjudication_workflow": "fixture review",
        "tool_behavior": "fixture keyboard and drawing behavior",
    }
    assessment = {
        k: {"observed": v, "current": v, "covered": True, "rationale": "comparison example only"}
        for k, v in context.items()
    }
    applicability = {
        "candidate_sha256": export.sha256,
        "queue_sha256": queue.sha256,
        "run_id": queue.queue_id,
        "applicable": True,
        "beyond_scope": False,
        "uncertain": False,
        "limits": "structural comparison only; does not establish an observation",
        "context_assessment": assessment,
    }
    return context, copy.deepcopy(context), applicability


@pytest.mark.parametrize(
    "mutation", ["inapplicable", "material", "uncertain", "candidate", "run", "operator", "missing", "undocumented"]
)
def test_context_applicability_refuses_unsupported_reuse(tmp_path, mutation):
    export, queue = load(session(tmp_path))
    context, current, a = comparison(export, queue)
    if mutation == "inapplicable":
        a["applicable"] = False
    elif mutation == "material":
        a["beyond_scope"] = True
    elif mutation == "uncertain":
        a["uncertain"] = True
    elif mutation == "candidate":
        a["candidate_sha256"] = "0" * 64
    elif mutation == "run":
        a["run_id"] = "unrelated"
    elif mutation == "operator":
        current["operators"] = ["uncovered"]
    elif mutation == "missing":
        del a["context_assessment"]["tool_behavior"]
    else:
        current["tool_behavior"] = "changed measurement behavior"
        a["context_assessment"]["tool_behavior"]["current"] = current["tool_behavior"]
    with pytest.raises(FrameContractError):
        occ._require_applicability(context, current, a, export, queue, queue.queue_id)


def test_documented_context_comparison_is_not_human_observation_evidence(tmp_path):
    export, queue = load(session(tmp_path))
    context, current, a = comparison(export, queue)
    current["tool_behavior"] += "; unrelated build identifier changed"
    a["context_assessment"]["tool_behavior"].update(
        current=current["tool_behavior"],
        changes="build metadata only; keyboard/drawing behavior identical",
        rationale="same bounded measurement context in this structural example",
    )
    occ._require_applicability(context, current, a, export, queue, queue.queue_id)
    # A valid comparison supplies no available human observation to production.
    with pytest.raises(FrameContractError, match="observation"):
        occ.to_face_instances(export, queue)


def test_existing_non_observation_document_cannot_satisfy_production_gate(tmp_path):
    paths = session(tmp_path)
    record = tmp_path / "not-an-observation.json"
    base._write_json(record, {"schema": "fixture-structural-example/v1", "applicability": {"applicable": False}})
    paths[2]["observation_ref"] = str(record)
    base._write_json(paths[-1], paths[2])
    with pytest.raises(FrameContractError, match="observation"):
        occ.to_face_instances(*load(paths))


@pytest.mark.parametrize("mutation", ["gold", "repeat"])
def test_direct_run_with_nineteen_decisions_is_neither_pass_nor_fail(tmp_path, mutation):
    paths = session(tmp_path)
    edoc = paths[2]
    role = "known_answer" if mutation == "gold" else "consistency"
    a = next(a for a in edoc["answers"] if edoc["hidden"]["presented"][a["presented_id"]]["role"] == role)
    edoc["answers"].remove(a)
    del edoc["hidden"]["presented"][a["presented_id"]]
    base._write_json(paths[-1], edoc)
    export, queue = load(paths)
    report = occ.qc_report(export, queue)
    metrics = report["annotators"] if mutation == "gold" else report["fields"]
    assert all(v["status"] == "support_not_accrued" for v in metrics.values())
    with pytest.raises(FrameContractError, match="support"):
        occ.to_synthetic_face_instances(export, queue)


def test_missing_recovery_evidence_cannot_fall_back_to_old_repeats(tmp_path):
    paths, _, _, _ = recovery(tmp_path)
    export, queue = load(paths)
    # The correction now agrees with the old repeats, which are historical only.
    assert not occ.qc_report(export, queue)["failures"]
    (tmp_path / "acceptance.json").unlink()
    with pytest.raises(FrameContractError, match="evidence"):
        occ.to_synthetic_face_instances(export, queue)


@pytest.mark.parametrize("mutation", ["answers", "assignment", "policy"])
def test_loaded_answers_assignments_and_qc_cannot_change_under_the_same_hash(tmp_path, mutation):
    export, queue = load(session(tmp_path))
    if mutation == "answers":
        export.answers[0].faces[0]["occluders"] = ["hand"]
    elif mutation == "assignment":
        export.presented[export.answers[0].presented_id]["item_id"] = "img-0100"
    else:
        queue.qc["kappa_floor"] = 0.01
    with pytest.raises(FrameContractError, match="immutable"):
        occ.to_synthetic_face_instances(export, queue)
