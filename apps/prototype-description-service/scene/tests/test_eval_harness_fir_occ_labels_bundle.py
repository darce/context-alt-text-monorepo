"""Packaged S7 label evidence (firbench-label-evidence/v1).

Every queue, answer, observation and acceptance document here is a software-only
structural fixture. No test asserts that a human observed anything, that an annotator
acted, or that real analysis evidence exists. The positive case proves byte packaging
and replay through the actual S7 readers, nothing more.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from scene.tests import test_eval_harness_fir_occ_labels as base
from scripts.eval_harness import fir_occ_labels as occ
from scripts.eval_harness.firbench_contract import FrameContractError

FRAME = hashlib.sha256(b"software fixture frame.json bytes").hexdigest()
PRIVATE = Path("benchmarks") / "private" / "fir-occ"
BUNDLE = "label-evidence"
# Closure members by role, relative to PRIVATE. Each one is genuinely read by the S7 path.
LAYOUT = {
    "export": "q/export.json",
    "queue": "q/queue.json",
    "gold": "q/gold.json",
    "acceptance": "acc/acceptance.json",
    "prior": "acc/prior.json",
    "validation_queue": "val/vq.json",
    "validation_gold": "val/vg.json",
    "validation_export": "val/ve.json",
    "observation": "obs/observation.json",
}
LINK_ROLE = {
    "prior": "prior_export",
    "validation_queue": "validation_queue",
    "validation_gold": "validation_gold",
    "validation_export": "validation_export",
}
CONTEXT = {
    "rule": base.RULE,
    "instructions": "fixture instructions",
    "operators": ["ann-01"],
    "collection_workflow": "fixture collection",
    "adjudication_workflow": "fixture review",
    "tool_behavior": "fixture keyboard and drawing behavior",
}


def _real(doc: dict) -> dict:
    """Drop the generator's fixture markers so only the readers' real-origin gate decides."""
    doc.pop("data_origin", None)
    for record in doc.get("items", []):
        for key in ("data_origin", "fixture_recipe", "caption", "detector_boxes"):
            record.pop(key, None)
    return doc


def _fresh_gold(doc: dict) -> dict:
    for k, record in enumerate(doc["items"]):
        record["gold_id"] = f"fresh-gold-{k}"
        record["media_id"] = f"fresh-media-{k}"
        record["image_sha256"] = base._fixture_sha(30000 + k)
    return doc


def _observation(export_sha: str, queue_sha: str) -> dict:
    assessment = {
        key: {"observed": value, "current": value, "covered": True, "rationale": "fixture: same bounded context"}
        for key, value in CONTEXT.items()
    }
    return {
        "schema": "fir-occ-observation/v1",
        "record_kind": "bounded_human_observation",
        "observer_id": "software-fixture-observer",
        "observed_at": "2026-01-01T00:00:00Z",
        "scope": "software fixture: structural shape only",
        "method": "software fixture: no observation occurred",
        "operator_accounts": "software fixture: no operator account",
        "limits": "structural fixture; asserts no human conduct",
        "exceptions": [],
        "context": copy.deepcopy(CONTEXT),
        "applicability": {
            "candidate_sha256": export_sha,
            "queue_sha256": queue_sha,
            "run_id": "new-run",
            "applicable": True,
            "beyond_scope": False,
            "uncertain": False,
            "limits": "software fixture only",
            "context_assessment": assessment,
        },
    }


def _wire(root: Path, *, tier: str = "a", observation_ref: str | None = "../obs/observation.json") -> dict[str, Path]:
    """Write a structurally complete recovery wire under root/benchmarks/private/fir-occ."""
    private = root / PRIVATE
    paths = {key: private / rel for key, rel in LAYOUT.items()}
    queue = _real(base._queue_doc(tier=tier))
    queue["queue_id"] = "occ-q-0001"
    queue["acceptance_path"] = "../acc/acceptance.json"
    queue["measurement_context"] = copy.deepcopy(CONTEXT)
    qsha = base._write_json(paths["queue"], queue)
    gold = _real(base._gold_doc())
    base._write_json(paths["gold"], gold)
    prior = base._export_doc(queue, qsha, gold)
    for answer in prior["answers"][:5]:  # historical failure, later corrected by the candidate
        answer["faces"][0]["visibility"]["left_eye"] = "uncertain"
    base._write_json(paths["prior"], prior)
    candidate = copy.deepcopy(prior)
    for k, answer in enumerate(candidate["answers"][:5]):
        answer["faces"] = base._answer_faces(k)
    candidate["observation_ref"] = observation_ref
    esha = base._write_json(paths["export"], candidate)
    vq = _real(base._queue_doc(tier=tier))
    vq["queue_id"] = "fresh-validation"
    vqsha = base._write_json(paths["validation_queue"], vq)
    vg = _fresh_gold(_real(base._gold_doc(authored_by="independent-qc-author")))
    base._write_json(paths["validation_gold"], vg)
    ve = base._export_doc(vq, vqsha, vg)
    remap = {pid: f"new-{pid}" for pid in ve["hidden"]["presented"]}
    ve["hidden"]["presented"] = {
        remap[pid]: {**record, "of": remap.get(record["of"])} for pid, record in ve["hidden"]["presented"].items()
    }
    for answer in ve["answers"]:
        answer["presented_id"] = remap[answer["presented_id"]]
    vesha = base._write_json(paths["validation_export"], ve)
    queue_obj, prior_obj = occ.load_queue(paths["queue"], paths["gold"]), occ.load_label_export(paths["prior"])
    acceptance = {
        "schema": "fir-occ-acceptance/v1",
        "candidate_sha256": esha,
        "prior_export": {"path": "prior.json", "sha256": hashlib.sha256(paths["prior"].read_bytes()).hexdigest()},
        "original_qc": occ.qc_report(prior_obj, queue_obj),
        "declaration": {
            "run_id": "new-run",
            "candidate_sha256": esha,
            "rule_id": base.RULE,
            "disagreement_rule": "fixture-disagreement/v2",
            "qc": dict(base.QC),
            "scope": [item["item_id"] for item in queue["items"]],
            "qc_author": "independent-qc-author",
            "evaluator": "ann-01",
            "declared_before_answers": True,
            "independently_blinded": True,
            "prior_answers_disclosed": False,
            "repair_examples_used_as_gold": False,
            "assignment": ve["hidden"]["presented"],
            "validation_queue_sha256": vqsha,
        },
        "validation_queue": {"path": "../val/vq.json", "sha256": vqsha},
        "validation_gold": {
            "path": "../val/vg.json",
            "sha256": hashlib.sha256(paths["validation_gold"].read_bytes()).hexdigest(),
        },
        "validation_export": {"path": "../val/ve.json", "sha256": vesha},
        "sme_resolutions": [],
    }
    base._write_json(paths["acceptance"], acceptance)
    if observation_ref is not None:
        base._write_json(paths["observation"], _observation(esha, qsha))
    return paths


def _freeze(root: Path, paths: dict[str, Path], *, frame: str = FRAME):
    return occ.freeze_label_evidence(paths["export"], paths["queue"], paths["gold"], repo_root=root, frame_sha256=frame)


def _name(key: str) -> str:
    return f"{BUNDLE}/{PRIVATE.as_posix()}/{LAYOUT[key]}"


def _persist(run: Path, bundle) -> None:
    """Test-side stand-in for the runtime: write exact bundle bytes with O_EXCL."""
    for name, data in bundle.files.items():
        target = run / name
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)


def _rebound(descriptor: dict, name: str, data: bytes) -> dict:
    desc = copy.deepcopy(descriptor)
    for entry in desc["files"]:
        if entry["path"] == name:
            entry["sha256"] = hashlib.sha256(data).hexdigest()
    return desc


def _rewrite(run: Path, descriptor: dict, key: str, data: bytes) -> dict:
    """Replace one closure member, then rebind every descriptor and link hash that names it."""
    desc = _rebound(descriptor, _name(key), data)
    (run / _name(key)).write_bytes(data)
    if key in LINK_ROLE:
        acc_name = _name("acceptance")
        acc = json.loads((run / acc_name).read_bytes())
        acc[LINK_ROLE[key]]["sha256"] = hashlib.sha256(data).hexdigest()
        acc_bytes = json.dumps(acc, sort_keys=True, indent=1).encode()
        (run / acc_name).write_bytes(acc_bytes)
        desc = _rebound(desc, acc_name, acc_bytes)
    return desc


def _edit(run: Path, descriptor: dict, key: str, mutate) -> dict:
    doc = json.loads((run / _name(key)).read_bytes())
    mutate(doc)
    return _rewrite(run, descriptor, key, json.dumps(doc, sort_keys=True, indent=1).encode())


def _set_bytes(paths: dict[str, Path], key: str, data: bytes) -> None:
    """Replace one wire member and keep its acceptance link hash honest, so the parser is what refuses."""
    paths[key].write_bytes(data)
    if key in LINK_ROLE:
        acc = json.loads(paths["acceptance"].read_bytes())
        acc[LINK_ROLE[key]]["sha256"] = hashlib.sha256(data).hexdigest()
        paths["acceptance"].write_text(json.dumps(acc, sort_keys=True, indent=1))


def _snapshot(root: Path) -> dict[str, tuple[bytes | None, int]]:
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            data = path.read_bytes() if path.is_file() else None
            state[path.relative_to(root).as_posix()] = (data, path.lstat().st_mtime_ns)
    return state


def _rows_from_originals(paths: dict[str, Path]) -> tuple[dict, ...]:
    export = occ.load_label_export(paths["export"])
    queue = occ.load_queue(paths["queue"], paths["gold"])
    return occ.to_face_instances(export, queue)


@pytest.fixture()
def wired(tmp_path: Path) -> dict[str, Path]:
    return _wire(tmp_path)


def test_fixture_is_a_complete_wire_that_the_actual_s7_readers_qualify(wired) -> None:
    # Sanity for the software fixture only: existing readers accept the structure.
    rows = _rows_from_originals(wired)
    assert rows and all(row["annotation_tier"] == "a" for row in rows)
    assert all(row["observation_evidence"] is not None for row in rows)
    occ.require_real_analysis_rows(rows)


def test_descriptor_has_exact_keys_and_sorted_bound_files(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    desc = bundle.descriptor
    assert set(desc) == {"schema", "frame_sha256", "export_path", "queue_path", "gold_path", "files"}
    assert desc["schema"] == "firbench-label-evidence/v1"
    assert desc["frame_sha256"] == FRAME
    assert desc["export_path"] == _name("export")
    assert desc["queue_path"] == _name("queue")
    assert desc["gold_path"] == _name("gold")
    paths = [entry["path"] for entry in desc["files"]]
    assert paths == sorted(paths) and len(set(paths)) == len(paths)
    assert {frozenset(entry) for entry in desc["files"]} == {frozenset({"path", "sha256"})}
    assert {entry["path"]: entry["sha256"] for entry in desc["files"]} == {
        name: hashlib.sha256(data).hexdigest() for name, data in bundle.files.items()
    }


def test_bundle_is_the_exact_read_closure_with_original_bytes(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    assert set(bundle.files) == {_name(key) for key in LAYOUT}
    for key, path in wired.items():
        assert bundle.files[_name(key)] == path.read_bytes()


def test_bundle_omits_observation_for_tier_b_because_no_reader_opens_it(tmp_path) -> None:
    paths = _wire(tmp_path, tier="b", observation_ref=None)
    bundle = _freeze(tmp_path, paths)
    assert _name("observation") not in bundle.files
    assert len(bundle.files) == len(LAYOUT) - 1


def test_freeze_writes_nothing_and_reads_no_pixels(tmp_path, wired) -> None:
    before = _snapshot(tmp_path)
    assert not list(tmp_path.rglob("*.png"))  # queue images are named but never exist here
    _freeze(tmp_path, wired)
    assert _snapshot(tmp_path) == before


def test_copied_bytes_replay_through_actual_s7_after_originals_are_removed(tmp_path, wired) -> None:
    expected = tuple(_rows_from_originals(wired))
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    descriptor = json.loads(json.dumps(bundle.descriptor))  # manifest round trip
    shutil.rmtree(tmp_path / "benchmarks")
    assert occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME) == expected


def test_requalify_is_readonly(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    before = _snapshot(run)
    occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME)
    assert _snapshot(run) == before


def test_tier_b_bundle_replays_without_observation(tmp_path) -> None:
    paths = _wire(tmp_path, tier="b", observation_ref=None)
    expected = tuple(_rows_from_originals(paths))
    bundle = _freeze(tmp_path, paths)
    run = tmp_path / "run"
    _persist(run, bundle)
    shutil.rmtree(tmp_path / "benchmarks")
    assert occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME) == expected


# --- genuine gates: refusal before any bundle exists -----------------------------------


def test_tier_a_without_observation_reference_is_refused(tmp_path) -> None:
    paths = _wire(tmp_path, observation_ref=None)
    with pytest.raises(FrameContractError, match="observation"):
        _freeze(tmp_path, paths)


@pytest.mark.parametrize("reference", ["fixture-only:no-human-observation", "true", "observed"])
def test_reference_string_without_a_record_is_refused(tmp_path, reference) -> None:
    paths = _wire(tmp_path, observation_ref=f"../obs/{reference}")
    with pytest.raises(FrameContractError, match="cannot resolve evidence record"):
        _freeze(tmp_path, paths)


@pytest.mark.parametrize("origin", ["generated_fixture", "synthetic", "test"])
def test_observation_marked_as_fixture_origin_is_refused(tmp_path, wired, origin) -> None:
    doc = json.loads(wired["observation"].read_bytes())
    doc["data_origin"] = origin
    wired["observation"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="origin"):
        _freeze(tmp_path, wired)


@pytest.mark.parametrize("value", ["true", 1, False])
def test_observation_applicability_must_be_boolean_true(tmp_path, wired, value) -> None:
    doc = json.loads(wired["observation"].read_bytes())
    doc["applicability"]["applicable"] = value
    wired["observation"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="observation"):
        _freeze(tmp_path, wired)


def test_observation_that_is_a_bare_boolean_is_not_evidence(tmp_path, wired) -> None:
    wired["observation"].write_text("true")
    with pytest.raises(FrameContractError, match="object"):
        _freeze(tmp_path, wired)


def test_synthetic_queue_cannot_be_frozen_as_real_evidence(tmp_path) -> None:
    session = tmp_path / PRIVATE / "gen"
    base._session(session, queue=base._queue_doc(tier="b"))
    qpath, gpath, epath = session / "queue.json", session / "gold.json", session / "export.json"
    with pytest.raises(FrameContractError, match="origin"):
        occ.freeze_label_evidence(epath, qpath, gpath, repo_root=tmp_path, frame_sha256=FRAME)


def test_synthetic_helper_rows_stay_persistently_ineligible(tmp_path) -> None:
    base._session(tmp_path, queue=base._queue_doc(tier="b"))
    queue = occ.load_queue(tmp_path / "queue.json", tmp_path / "gold.json")
    rows = occ.to_synthetic_face_instances(occ.load_label_export(tmp_path / "export.json"), queue)
    assert rows and all(row["analysis_eligible"] is False and row["synthetic"] is True for row in rows)
    with pytest.raises(FrameContractError, match="synthetic"):
        occ.require_real_analysis_rows(rows)


def test_real_readers_refuse_insufficient_support_before_any_bundle(tmp_path) -> None:
    queue = _real(base._queue_doc(n=5, tier="b"))
    paths = {
        "export": tmp_path / PRIVATE / "q/export.json",
        "queue": tmp_path / PRIVATE / "q/queue.json",
        "gold": tmp_path / PRIVATE / "q/gold.json",
    }
    qsha = base._write_json(paths["queue"], queue)
    gold = _real(base._gold_doc())
    base._write_json(paths["gold"], gold)
    base._write_json(paths["export"], base._export_doc(queue, qsha, gold))
    with pytest.raises(FrameContractError, match="support"):
        _freeze(tmp_path, paths)


# --- claim keys and boolean/string eligibility are never trusted -----------------------


@pytest.mark.parametrize(
    ("where", "key", "value"),
    [
        ("queue", "analysis_eligible", False),
        ("queue_item", "synthetic", False),
        ("gold_item", "qualified", True),
        ("observation", "analysis_eligible", True),
        ("acceptance", "qualified", True),
        ("export", "synthetic", False),
    ],
)
def test_eligibility_claim_keys_are_refused_even_when_false(tmp_path, wired, where, key, value) -> None:
    target = {
        "queue": "queue",
        "queue_item": "queue",
        "gold_item": "gold",
        "observation": "observation",
        "acceptance": "acceptance",
        "export": "export",
    }[where]
    doc = json.loads(wired[target].read_bytes())
    if where in ("queue_item", "gold_item"):
        doc["items"][0][key] = value
    else:
        doc[key] = value
    wired[target].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="claim"):
        _freeze(tmp_path, wired)


@pytest.mark.parametrize("frame", ["", "ABC", True, 1, "g" * 64, FRAME.upper()])
def test_frame_hash_must_be_a_lowercase_sha256_string(tmp_path, wired, frame) -> None:
    with pytest.raises(FrameContractError, match="frame_sha256"):
        _freeze(tmp_path, wired, frame=frame)


# --- links: absolute, escaping, symlink, ambiguous, cyclic ------------------------------


def test_absolute_acceptance_path_is_refused(tmp_path, wired) -> None:
    doc = json.loads(wired["queue"].read_bytes())
    doc["acceptance_path"] = str(wired["acceptance"])
    wired["queue"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="absolute"):
        _freeze(tmp_path, wired)


def test_absolute_observation_reference_is_refused(tmp_path, wired) -> None:
    doc = json.loads(wired["export"].read_bytes())
    doc["observation_ref"] = str(wired["observation"])
    wired["export"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="absolute"):
        _freeze(tmp_path, wired)


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("queue", "../../../../outside.json"),
        ("observation", "../../../../escape.json"),
        ("validation_export", "../../../../../etc/passwd"),
    ],
)
def test_escaping_link_is_refused(tmp_path, wired, where, value) -> None:
    if where == "queue":
        doc = json.loads(wired["queue"].read_bytes())
        doc["acceptance_path"] = value
        wired["queue"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    elif where == "observation":
        doc = json.loads(wired["export"].read_bytes())
        doc["observation_ref"] = value
        wired["export"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    else:
        doc = json.loads(wired["acceptance"].read_bytes())
        doc["validation_export"]["path"] = value
        wired["acceptance"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="escapes"):
        _freeze(tmp_path, wired)


@pytest.mark.parametrize(
    "value", ["../acc/./acceptance.json", "../acc//acceptance.json", "../acc/x/../acceptance.json"]
)
def test_ambiguous_non_canonical_link_is_refused(tmp_path, wired, value) -> None:
    doc = json.loads(wired["queue"].read_bytes())
    doc["acceptance_path"] = value
    wired["queue"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="ambiguous"):
        _freeze(tmp_path, wired)


def test_symlinked_support_record_is_refused(tmp_path, wired) -> None:
    real = wired["validation_export"].with_name("ve-real.json")
    real.write_bytes(wired["validation_export"].read_bytes())
    wired["validation_export"].unlink()
    os.symlink(real.name, wired["validation_export"])
    with pytest.raises(FrameContractError, match="symlink"):
        _freeze(tmp_path, wired)


def test_symlinked_directory_on_the_path_is_refused(tmp_path, wired) -> None:
    obs = wired["observation"].parent
    real = obs.with_name("obs-real")
    obs.rename(real)
    os.symlink(real.name, obs)
    with pytest.raises(FrameContractError, match="symlink"):
        _freeze(tmp_path, wired)


@pytest.mark.parametrize(
    ("where", "value"),
    [("acceptance", "acceptance.json"), ("queue", "../q/queue.json")],
)
def test_cyclic_link_back_to_an_ancestor_is_refused(tmp_path, wired, where, value) -> None:
    doc = json.loads(wired["acceptance"].read_bytes())
    if where == "acceptance":
        doc["prior_export"] = {"path": value, "sha256": "0" * 64}
    else:
        doc["validation_gold"] = {"path": value, "sha256": "0" * 64}
    wired["acceptance"].write_text(json.dumps(doc, sort_keys=True, indent=1))
    with pytest.raises(FrameContractError, match="cyclic"):
        _freeze(tmp_path, wired)


def test_missing_closure_member_is_named(tmp_path, wired) -> None:
    wired["validation_gold"].unlink()
    with pytest.raises(FrameContractError, match="cannot resolve evidence record"):
        _freeze(tmp_path, wired)


def test_original_outside_benchmarks_private_is_refused(tmp_path, wired) -> None:
    loose = tmp_path / "benchmarks" / "loose"
    loose.mkdir(parents=True)
    moved = loose / "export.json"
    shutil.copyfile(wired["export"], moved)
    with pytest.raises(FrameContractError, match="benchmarks/private"):
        occ.freeze_label_evidence(moved, wired["queue"], wired["gold"], repo_root=tmp_path, frame_sha256=FRAME)


def test_parent_segments_in_original_paths_are_refused(tmp_path, wired) -> None:
    dotted = tmp_path / PRIVATE / "q" / ".." / "q" / "export.json"
    with pytest.raises(FrameContractError, match="ambiguous"):
        occ.freeze_label_evidence(dotted, wired["queue"], wired["gold"], repo_root=tmp_path, frame_sha256=FRAME)


# --- strict JSON: duplicates and non-finite numbers --------------------------------------


@pytest.mark.parametrize("key", sorted(LAYOUT))
def test_duplicate_json_keys_are_refused_in_every_closure_document(tmp_path, wired, key) -> None:
    text = wired[key].read_text()
    _set_bytes(wired, key, text.replace("{", '{"__dup__": 1, "__dup__": 2, ', 1).encode())
    with pytest.raises(FrameContractError, match="repeats JSON keys"):
        _freeze(tmp_path, wired)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
@pytest.mark.parametrize("key", sorted(LAYOUT))
def test_nonfinite_json_numbers_are_refused_in_every_closure_document(tmp_path, wired, key, token) -> None:
    text = wired[key].read_text()
    _set_bytes(wired, key, text.replace("{", f'{{"__n__": {token}, ', 1).encode())
    with pytest.raises(FrameContractError, match="non-finite"):
        _freeze(tmp_path, wired)


# --- requalify: exact descriptor, closure and bytes -------------------------------------


@pytest.mark.parametrize("key", sorted(LAYOUT))
def test_any_byte_change_to_a_support_file_is_refused(tmp_path, wired, key) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    target = run / _name(key)
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(FrameContractError, match="changed after packaging"):
        occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME)


@pytest.mark.parametrize(
    ("key", "mutate", "match"),
    [
        ("observation", lambda d: d["applicability"].update(applicable=False), "observation"),
        ("observation", lambda d: d.update(data_origin="generated_fixture"), "origin"),
        ("acceptance", lambda d: d["declaration"].update(qc_author="ann-01"), "independently"),
        ("acceptance", lambda d: d.update(candidate_sha256="0" * 64), "candidate"),
        ("prior", lambda d: d["answers"][0].update(faces=[]), "rewritten"),
        ("validation_export", lambda d: d.update(annotator_id="ann-02"), "independent"),
        ("validation_gold", lambda d: d["items"][0].update(authored_by="ann-01"), "live annotation queue"),
        ("validation_queue", lambda d: d["items"][0].update(image_sha256="1" * 64), "different queue file"),
    ],
)
def test_rebound_semantic_tamper_is_still_refused_by_actual_s7_gates(tmp_path, wired, key, mutate, match) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    descriptor = _edit(run, bundle.descriptor, key, mutate)
    with pytest.raises(FrameContractError, match=match):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


@pytest.mark.parametrize("key", sorted(LAYOUT))
def test_duplicate_json_is_refused_even_when_the_hash_is_rebound(tmp_path, wired, key) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    dup = (run / _name(key)).read_text().replace("{", '{"__dup__": 1, "__dup__": 2, ', 1).encode()
    descriptor = _rewrite(run, bundle.descriptor, key, dup)
    with pytest.raises(FrameContractError, match="repeats JSON keys"):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


@pytest.mark.parametrize("token", ["NaN", "1e999"])
def test_nonfinite_is_refused_even_when_the_hash_is_rebound(tmp_path, wired, token) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    bad = (run / _name("observation")).read_text().replace("{", f'{{"__n__": {token}, ', 1).encode()
    descriptor = _rewrite(run, bundle.descriptor, "observation", bad)
    with pytest.raises(FrameContractError, match="non-finite"):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


def test_frame_hash_mismatch_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    other = hashlib.sha256(b"another frame").hexdigest()
    with pytest.raises(FrameContractError, match="not bound to this frame"):
        occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=other)


def test_descriptor_frame_tamper_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    descriptor = dict(copy.deepcopy(bundle.descriptor), frame_sha256="2" * 64)
    with pytest.raises(FrameContractError, match="not bound to this frame"):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(analysis_eligible=True), "unknown keys"),
        (lambda d: d.pop("files"), "missing required keys"),
        (lambda d: d.update(schema="firbench-label-evidence/v0"), "schema"),
        (lambda d: d.update(frame_sha256=True), "not bound to this frame"),
        (lambda d: d["files"][0].update(eligible=True), "unknown keys"),
        (lambda d: d.update(files=list(reversed(d["files"]))), "sorted"),
        (lambda d: d["files"].append(dict(d["files"][0])), "sorted"),
        (lambda d: d.update(export_path="/abs/" + d["export_path"]), "absolute"),
        (lambda d: d.update(queue_path=d["queue_path"].replace("/q/", "/q/../q/")), "ambiguous"),
        (lambda d: d.update(gold_path="label-evidence/other/gold.json"), "label-evidence/benchmarks/private"),
        (lambda d: d["files"][0].update(sha256="ABC"), "sha256"),
        (lambda d: d.update(gold_path=_name("validation_gold").replace("val/vg", "val/none")), "absent from files"),
    ],
)
def test_descriptor_shape_is_exact(tmp_path, wired, mutate, match) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    descriptor = copy.deepcopy(bundle.descriptor)
    mutate(descriptor)
    with pytest.raises(FrameContractError, match=match):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


def test_missing_bundle_file_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    (run / _name("gold")).unlink()
    with pytest.raises(FrameContractError, match="missing"):
        occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME)


def test_unexpected_bundle_file_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    (run / _name("gold").replace("gold.json", "extra.json")).write_text("{}")
    with pytest.raises(FrameContractError, match="unexpected"):
        occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME)


def test_descriptor_enumerating_a_file_outside_the_closure_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    extra = _name("gold").replace("gold.json", "zz-extra.json")
    (run / extra).write_text("{}")
    descriptor = copy.deepcopy(bundle.descriptor)
    descriptor["files"].append({"path": extra, "sha256": hashlib.sha256(b"{}").hexdigest()})
    descriptor["files"].sort(key=lambda entry: entry["path"])
    with pytest.raises(FrameContractError, match="outside the S7 read closure"):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


def test_descriptor_missing_a_closure_member_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    dropped = _name("validation_export")
    (run / dropped).unlink()
    descriptor = copy.deepcopy(bundle.descriptor)
    descriptor["files"] = [entry for entry in descriptor["files"] if entry["path"] != dropped]
    with pytest.raises(FrameContractError, match="does not enumerate"):
        occ.requalify_label_evidence(run, descriptor, frame_sha256=FRAME)


def test_symlink_inside_run_local_evidence_is_refused(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    target = run / _name("gold")
    real = target.with_name("gold-real.json")
    real.write_bytes(target.read_bytes())
    target.unlink()
    os.symlink(real.name, target)
    with pytest.raises(FrameContractError, match="symlink"):
        occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME)


def test_requalify_refusal_writes_nothing(tmp_path, wired) -> None:
    bundle = _freeze(tmp_path, wired)
    run = tmp_path / "run"
    _persist(run, bundle)
    (run / _name("gold")).write_bytes(b"{}")
    before = _snapshot(run)
    with pytest.raises(FrameContractError):
        occ.requalify_label_evidence(run, bundle.descriptor, frame_sha256=FRAME)
    assert _snapshot(run) == before
