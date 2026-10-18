"""FIR-OCC label queue generator and importer (S7).

Synthetic numpy images, synthetic ids and fixed seeds only. No real names,
pixels or private files. The generator is exercised through its CLI entry
point and its emitted HTML; the importer is exercised through real JSON files.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import re
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness import fir_occ_labels as occ
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness.union_adjudication import detector_gap_bound

REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR = REPO_ROOT / "benchmarks" / "tools" / "fir_occ_label_queue.py"
FRAME_FIXTURE = Path(__file__).parent / "fixtures" / "firbench_interchange_v1" / "frame-v1.json"
RULE = "face-label-rule/v1"
N_PRIMARY = 200
# Delegated pre-data QC policy (MCP 16734, 16736) written into the synthetic queue qc block.
QC = {
    "gold_share": 0.10,
    "repeat_fraction": 0.10,
    "repeat_percent_agreement_floor": 0.90,
    "kappa_floor": 0.80,
    "annotator_gold_accuracy_floor": 0.90,
    "min_gold_decisions_per_annotator": 20,
    "min_repeat_decisions_per_field": 20,
}
REGIONS = ("left_eye", "right_eye", "nose", "mouth")


def _load_generator():
    spec = importlib.util.spec_from_file_location("fir_occ_label_queue", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(seed: object) -> str:
    return hashlib.sha256(f"synthetic-{seed}".encode()).hexdigest()


def _png(pixels: np.ndarray) -> bytes:
    height, width, _ = pixels.shape
    raw = b"".join(b"\x00" + pixels[row].astype(np.uint8).tobytes() for row in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _fixture_sha(seed: int) -> str:
    pixels = np.random.default_rng(seed).integers(0, 255, size=(8, 8, 3), dtype=np.uint8)
    return hashlib.sha256(_png(pixels)).hexdigest()


def _write_images(directory: Path, names: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        index = int(Path(name).stem.split("-")[1]) + (5000 if name.startswith("gold-") else 0)
        rng = np.random.default_rng(20260919 + index)
        (directory / name).write_bytes(_png(rng.integers(0, 255, size=(8, 8, 3), dtype=np.uint8)))


def _sync(doc: dict, images: Path) -> dict:
    """Record the real sha256 of each synthetic image file, as the generator verifies it."""
    for item in doc["items"]:
        item["image_sha256"] = hashlib.sha256((images / item["image"]).read_bytes()).hexdigest()
    return doc


def _write_json(path: Path, doc: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, sort_keys=True, indent=1).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _face(occluders, *, eyes="visible", right="visible", nose="visible", mouth="visible", identity="unresolved"):
    return {
        "source": "added",
        "face_key": "a0",
        "box": [1.0, 1.0, 4.0, 4.0],
        "occluders": occluders,
        "visibility": {"left_eye": eyes, "right_eye": right, "nose": nose, "mouth": mouth},
        "identity_status": identity,
    }


def _bit(k: int, field: str) -> int:
    """Hash-derived binary choice, so any 20-item sample varies on every field."""
    return hashlib.sha256(f"{field}|{k}".encode()).digest()[0] % 2


def _answer_faces(k: int) -> list[dict]:
    """Deterministic synthetic answer; every field takes both values in almost any 20-item sample."""
    return [
        _face(
            ["mask"] if _bit(k, "occluders") == 0 else [],
            eyes="occluded" if _bit(k, "left") == 0 else "visible",
            right="occluded" if _bit(k, "right") == 0 else "visible",
            nose="uncertain" if _bit(k, "nose") == 0 else "visible",
            mouth="out_of_frame" if _bit(k, "mouth") == 0 else "visible",
            identity="unknown" if _bit(k, "identity") == 0 else "unresolved",
        )
    ]


def _queue_doc(n: int = N_PRIMARY, *, tier: str = "a", qc: dict | None = None, groups: dict | None = None) -> dict:
    groups = groups or {}
    items = []
    for k in range(n):
        representative = next((i for i in range(k + 1) if groups.get(i) == groups[k]), k) if groups.get(k) else k
        seed = 20260919 + representative
        items.append(
            {
                "item_id": f"img-{k:04d}",
                "image": f"img-{k:04d}.png",
                "image_sha256": _fixture_sha(seed),
                "data_origin": "generated_fixture",
                "fixture_recipe": {"generator_id": "numpy-rgb8/v1", "seed": seed},
                "sampling_arm": "probability",
                "inclusion_probability": 0.5,
                "source_bucket": "mask_tagged",
                "duplicate_group": groups.get(k),
                "show_confirmed_boxes": False,
                "confirmed_boxes": [],
                "caption": f"CAPTION-SENTINEL-{k}",
                "detector_boxes": [[901.0, 902.0, 903.0, 904.0]],
            }
        )
    return {
        "schema": "fir-occ-queue/v1",
        "data_origin": "generated_fixture",
        "queue_id": "occ-q-0001",
        "mode": "face",
        "annotation_tier": tier,
        "items": items,
        "qc": dict(QC if qc is None else qc),
    }


def _gold_doc(n: int = 20, *, authored_by: str = "sme-01", live=("ann-01",), answer_source="sme_arbitrated") -> dict:
    items = []
    for k in range(n):
        items.append(
            {
                "gold_id": f"gold-{k:02d}",
                "image": f"gold-{k:02d}.png",
                "image_sha256": _fixture_sha(20260919 + 5000 + k),
                "data_origin": "generated_fixture",
                "fixture_recipe": {"generator_id": "numpy-rgb8/v1", "seed": 20260919 + 5000 + k},
                "media_id": f"gm-{k:02d}",
                "stratum": "B_eyewear",
                "kind": "hard",
                "answer_source": answer_source,
                "authored_by": authored_by,
                "live_queue_annotators": list(live),
                "faces": _answer_faces(k),
            }
        )
    return {"schema": "fir-occ-gold/v1", "data_origin": "generated_fixture", "items": items}


def _pid(role: str, ident: str) -> str:
    return "p" + hashlib.sha256(f"occ-q-0001|{role}|{ident}".encode()).hexdigest()[:12]


def _export_doc(queue_doc: dict, queue_sha: str, gold_doc: dict | None, *, annotator="ann-01", observation_ref=None):
    """Build an export the way the page does: primaries, blind repeats and gold under opaque ids."""
    answers, presented, primary_pids = [], {}, {}
    seen_groups: set[str] = set()
    primaries = []
    for item in queue_doc["items"]:
        group = item.get("duplicate_group")
        if group is not None:
            if group in seen_groups:
                continue
            seen_groups.add(group)
        primaries.append(item)
    for item in primaries:
        k = int(item["item_id"].split("-")[1])
        pid = _pid("primary", item["item_id"])
        primary_pids[item["item_id"]] = pid
        presented[pid] = {"role": "primary", "item_id": item["item_id"], "of": None, "gold_id": None}
        answers.append({"presented_id": pid, "status": "answered", "faces": _answer_faces(k)})
    for item in primaries[:20]:
        k = int(item["item_id"].split("-")[1])
        pid = _pid("consistency", item["item_id"])
        presented[pid] = {
            "role": "consistency",
            "item_id": item["item_id"],
            "of": primary_pids[item["item_id"]],
            "gold_id": None,
        }
        answers.append({"presented_id": pid, "status": "answered", "faces": _answer_faces(k)})
    for gold in (gold_doc or {"items": []})["items"]:
        pid = _pid("known_answer", gold["gold_id"])
        presented[pid] = {"role": "known_answer", "item_id": None, "of": None, "gold_id": gold["gold_id"]}
        answers.append({"presented_id": pid, "status": "answered", "faces": copy.deepcopy(gold["faces"])})
    return {
        "schema": "fir-occ-labels/v1",
        "queue_id": queue_doc["queue_id"],
        "queue_sha256": queue_sha,
        "mode": "face",
        "annotator_id": annotator,
        "annotation_tier": queue_doc["annotation_tier"],
        "rule_id": RULE,
        "observation_ref": observation_ref,
        "answers": answers,
        "hidden": {"presented": presented},
    }


def _session(tmp_path: Path, *, queue=None, gold=None, export_mut=None, observation_ref=None):
    queue = _queue_doc() if queue is None else queue
    gold = _gold_doc() if gold is None else gold
    queue_path = tmp_path / "queue.json"
    gold_path = tmp_path / "gold.json"
    queue_sha = _write_json(queue_path, queue)
    _write_json(gold_path, gold)
    export = _export_doc(queue, queue_sha, gold, observation_ref=observation_ref)
    if export_mut is not None:
        export_mut(export)
    export_path = tmp_path / "export.json"
    _write_json(export_path, export)
    return occ.load_queue(queue_path, gold_path), occ.load_label_export(export_path), export_path


PRIVATE = Path("benchmarks") / "private" / "fir-occ"


def _generate(tmp_path: Path, *, queue_path=None, union_path=None, gold_path=None, seed="S", repeat="0.10", out=None):
    module = _load_generator()
    argv = ["--images", str(tmp_path / "images"), "--rule-id", RULE, "--repeat-fraction", repeat, "--seed", seed]
    argv += ["--repo-root", str(tmp_path)]
    if queue_path is not None:
        argv += ["--queue", str(queue_path)]
    if union_path is not None:
        argv += ["--union-delta", str(union_path)]
    if gold_path is not None:
        argv += ["--gold", str(gold_path)]
    out = out or tmp_path / PRIVATE / "queue-test.html"
    if not out.is_absolute():
        out = tmp_path / out
    argv += ["--out", str(out)]
    return module.main(argv), out


def _payload(html: str) -> dict:
    match = re.search(r'<script id="fir-occ-payload" type="application/json">(.*?)</script>', html, re.S)
    assert match is not None
    return json.loads(match.group(1))


def _hidden(payload: dict) -> dict:
    return json.loads(base64.b64decode(payload["hidden"]).decode())


@pytest.fixture()
def staged(tmp_path: Path):
    """Images on disk for the 200 primary items and 20 gold items."""
    names = [f"img-{k:04d}.png" for k in range(N_PRIMARY)] + [f"gold-{k:02d}.png" for k in range(20)]
    _write_images(tmp_path / "images", names)
    queue_path = tmp_path / "queue.json"
    gold_path = tmp_path / "gold.json"
    queue_path.write_text(json.dumps(_sync(_queue_doc(), tmp_path / "images")), encoding="utf-8")
    gold_path.write_text(json.dumps(_sync(_gold_doc(), tmp_path / "images")), encoding="utf-8")
    return tmp_path, queue_path, gold_path


# --- generator (CLI, emitted HTML) -----------------------------------------------------


def test_generator_refuses_output_outside_benchmarks_private(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    out = tmp_path / "benchmarks" / "reports" / "q.html"
    rc, _ = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path, out=out)
    assert rc != 0
    assert not out.exists()


def test_generated_html_has_no_external_reference_caption_or_detector_text(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    rc, out = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path)
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "CAPTION-SENTINEL" not in html
    assert "detector" not in html.lower()
    assert "901.0" not in html
    assert "<link" not in html and "<script src" not in html


def test_five_blind_repeats_are_inserted_and_reproducible_from_seed(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    queue = _sync(_queue_doc(n=50), tmp_path / "images")
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    gold_path.write_text(json.dumps(_sync(_gold_doc(n=5), tmp_path / "images")), encoding="utf-8")
    rc, out = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path, seed="S", repeat="0.10")
    assert rc == 0
    first = out.read_bytes()
    roles = [entry["role"] for entry in _hidden(_payload(out.read_text(encoding="utf-8")))["presented"].values()]
    assert roles.count("consistency") == 5
    rc, again = _generate(
        tmp_path, queue_path=queue_path, gold_path=gold_path, seed="S", repeat="0.10", out=PRIVATE / "again.html"
    )
    assert rc == 0 and again.read_bytes() == first
    rc, other = _generate(
        tmp_path, queue_path=queue_path, gold_path=gold_path, seed="T", repeat="0.10", out=PRIVATE / "other.html"
    )
    assert rc == 0 and other.read_bytes() != first


def test_html_has_no_repeat_gold_or_blind_token(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    rc, out = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path)
    assert rc == 0
    html = out.read_text(encoding="utf-8").lower()
    for token in ("repeat", "gold", "blind"):
        assert token not in html


def test_missing_image_and_malformed_queue_fail_closed(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    (tmp_path / "images" / "img-0003.png").unlink()
    rc, out = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path)
    assert rc != 0 and not out.exists()
    queue_path.write_text("{not json", encoding="utf-8")
    rc, out = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path, out=PRIVATE / "b.html")
    assert rc != 0 and not (PRIVATE / "b.html").exists()


def test_gold_items_must_pass_pilot_draw_gold_checks(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    gold_path.write_text(json.dumps(_gold_doc(authored_by="ann-01")), encoding="utf-8")
    with pytest.raises(fc.FrameContractError, match="live annotation queue"):
        occ.load_queue(queue_path, gold_path)
    gold_path.write_text(json.dumps(_gold_doc(answer_source="caption_pool")), encoding="utf-8")
    with pytest.raises(fc.FrameContractError):
        occ.load_queue(queue_path, gold_path)


def test_union_delta_mode_shows_only_unmatched_proposals(staged) -> None:
    tmp_path, _, gold_path = staged
    proposals = {
        "schema": "fir-occ-union-proposals/v1",
        "queue_id": "occ-u-0001",
        "annotation_tier": "a",
        "matched_fppi_declared": 0.01,
        "thresholds_declared_before_run": {"buffalo": 0.5, "candidate": 0.5},
        "qc": dict(QC),
        "items": [
            {
                "item_id": f"prop-{k:04d}",
                "image_id": f"image-{k:04d}",
                "image": f"img-{k:04d}.png",
                "image_sha256": _sha(k),
                "box": [2.0, 2.0, 3.0, 3.0],
                "sources": ["buffalo"],
                "matched_gt": k % 4 == 0,
            }
            for k in range(8)
        ],
    }
    _sync(proposals, tmp_path / "images")
    union_path = tmp_path / "proposals.json"
    union_path.write_text(json.dumps(proposals), encoding="utf-8")
    union_gold = _sync(_gold_doc(n=1), tmp_path / "images")
    for item in union_gold["items"]:
        item["decision"] = "face"
    _write_json(gold_path, union_gold)
    rc, out = _generate(tmp_path, union_path=union_path, gold_path=gold_path)
    assert rc == 0
    payload = _payload(out.read_text(encoding="utf-8"))
    assert payload["mode"] == "union_delta"
    # 6 unmatched proposals, 1 blind repeat (round half up of 0.10 x 6) and 1 gold item.
    assert len(payload["items"]) == 8
    shown = [entry for entry in _hidden(payload)["presented"].values() if entry["item_id"]]
    assert {entry["item_id"] for entry in shown} == {f"prop-{k:04d}" for k in range(8) if k % 4 != 0}
    assert sum(1 for item in payload["items"] if item["boxes"]) == 7
    assert "buffalo" not in out.read_text(encoding="utf-8")


def test_generated_html_round_trips_through_importer_with_fake_annotator(staged) -> None:
    tmp_path, queue_path, gold_path = staged
    queue_path.write_text(json.dumps(_sync(_queue_doc(n=N_PRIMARY), tmp_path / "images")), encoding="utf-8")
    rc, out = _generate(tmp_path, queue_path=queue_path, gold_path=gold_path)
    assert rc == 0
    payload = _payload(out.read_text(encoding="utf-8"))
    hidden = _hidden(payload)["presented"]
    gold = occ.load_queue(queue_path, gold_path).gold
    answers = []
    for item in payload["items"]:
        entry = hidden[item["pid"]]
        if entry["role"] == "known_answer":
            faces = next(g.faces for g in gold if g.gold_id == entry["gold_id"])
        else:
            faces = _answer_faces(int(entry["item_id"].split("-")[1]))
        answers.append({"presented_id": item["pid"], "status": "answered", "faces": faces})
    export = {
        "schema": "fir-occ-labels/v1",
        "queue_id": payload["queue_id"],
        "queue_sha256": payload["queue_sha256"],
        "mode": "face",
        "annotator_id": "ann-01",
        "annotation_tier": "a",
        "rule_id": RULE,
        "observation_ref": None,
        "answers": answers,
        "hidden": _hidden(payload),
    }
    export_path = tmp_path / "e2e-export.json"
    _write_json(export_path, export)
    queue = occ.load_queue(queue_path, gold_path)
    rows = occ.to_synthetic_face_instances(occ.load_label_export(export_path), queue)
    assert len(rows) == N_PRIMARY
    assert all(row["annotation"]["exhaustive"] is False for row in rows)


# --- importer ---------------------------------------------------------------------------


def test_load_label_export_rejects_wrong_schema_as_frame_contract_error(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    _write_json(path, {"schema": "fir-occ-labels/v0"})
    with pytest.raises(fc.FrameContractError):
        occ.load_label_export(path)


def test_skip_is_nonresponse_and_duplicate_group_propagates(tmp_path: Path) -> None:
    # Group outside the first 20 primaries so the blind-repeat support is unaffected by the skip.
    queue = _queue_doc(groups={150: "g1", 151: "g1"})

    def skip_representative(export: dict) -> None:
        assert export["answers"][150]["presented_id"] == _pid("primary", "img-0150")
        export["answers"][150] = {
            "presented_id": export["answers"][150]["presented_id"],
            "status": "skipped",
            "faces": [],
        }

    queue_obj, export, _ = _session(tmp_path, queue=queue, export_mut=skip_representative)
    by_unit = {row["unit_id"]: row for row in occ.to_synthetic_face_instances(export, queue_obj)}
    assert by_unit["img-0150"]["response"] == "nonresponse"
    assert by_unit["img-0150"]["face_key"] is None
    assert by_unit["img-0151"]["response"] == "nonresponse"
    assert by_unit["img-0151"]["duplicate_of"] == "img-0150"


def test_duplicate_group_labels_propagate_to_members(tmp_path: Path) -> None:
    queue = _queue_doc(groups={0: "g1", 1: "g1"})
    queue_obj, export, _ = _session(tmp_path, queue=queue)
    by_unit = {row["unit_id"]: row for row in occ.to_synthetic_face_instances(export, queue_obj)}
    assert by_unit["img-0001#a0"]["duplicate_of"] == "img-0000"
    assert by_unit["img-0001#a0"]["annotation"] == by_unit["img-0000#a0"]["annotation"]


def test_kappa_matches_hand_computed_value(tmp_path: Path) -> None:
    labels = [("a", "a")] * 5 + [("a", "b")] + [("b", "a")] + [("b", "b")] * 3
    mapping = {"a": ["mask"], "b": []}
    answers = []
    presented = {}
    for index, (first, second) in enumerate(labels):
        original, repeat = f"o{index}", f"r{index}"
        presented[original] = {"role": "primary", "item_id": f"img-{index:04d}", "of": None, "gold_id": None}
        presented[repeat] = {"role": "consistency", "item_id": f"img-{index:04d}", "of": original, "gold_id": None}
        answers.append({"presented_id": original, "status": "answered", "faces": [_face(mapping[first])]})
        answers.append({"presented_id": repeat, "status": "answered", "faces": [_face(mapping[second])]})
    export_path = tmp_path / "kappa-export.json"
    _write_json(
        export_path,
        {
            "schema": "fir-occ-labels/v1",
            "queue_id": "q",
            "queue_sha256": "0" * 64,
            "mode": "face",
            "annotator_id": "ann-01",
            "annotation_tier": "a",
            "rule_id": RULE,
            "observation_ref": None,
            "answers": answers,
            "hidden": {"presented": presented},
        },
    )
    export = occ.load_label_export(export_path)
    agreement = occ.repeat_agreement(export)
    assert agreement["occluders"].n == 10
    assert agreement["occluders"].percent == pytest.approx(0.8)
    assert agreement["occluders"].kappa == pytest.approx(7 / 12)


def test_rows_carry_tier_and_tier_a_is_never_exhaustive(tmp_path: Path) -> None:
    queue_obj, export, _ = _session(tmp_path)
    rows = occ.to_synthetic_face_instances(export, queue_obj)
    assert rows and all(row["annotation_tier"] == "a" for row in rows)
    assert all(row["annotation"]["exhaustive"] is not True for row in rows)


def test_rows_validate_against_frame_v1_face_annotation(tmp_path: Path) -> None:
    queue_obj, export, _ = _session(tmp_path)
    rows = [row for row in occ.to_synthetic_face_instances(export, queue_obj) if row["face_key"] is not None]
    frame = json.loads(FRAME_FIXTURE.read_text(encoding="utf-8"))
    frame["faces"] = [
        {
            "face_id": row["unit_id"],
            "image_id": row["item_id"],
            "box": row["box"],
            "identity_status": row["identity_status"],
            "identity_id": None,
            "cohort": None,
            "annotation": row["annotation"],
        }
        for row in rows[:5]
    ]
    with pytest.raises(fc.FrameContractError):
        fc.validate_interchange("frame-v1", frame)
    # The ordinary production annotation retains exactly the schema's original fields.
    for face in frame["faces"]:
        original = next(a.faces[0] for a in export.answers if a.faces)
        face["annotation"] = occ._annotation(export, queue_obj, original)
    fc.validate_interchange("frame-v1", frame)


@pytest.mark.parametrize("key", sorted(QC))
def test_null_qc_value_refuses_import(tmp_path: Path, key: str) -> None:
    queue = _queue_doc(qc={**QC, key: None})
    queue_obj, export, _ = _session(tmp_path, queue=queue)
    with pytest.raises(fc.FrameContractError, match=key):
        occ.to_synthetic_face_instances(export, queue_obj)


def test_below_floor_kappa_is_refused_with_repair_list(tmp_path: Path) -> None:
    def disagree_left_eye(export: dict) -> None:
        for answer in export["answers"]:
            if export["hidden"]["presented"][answer["presented_id"]]["role"] == "consistency":
                face = answer["faces"][0]
                face["visibility"]["left_eye"] = (
                    "uncertain" if face["visibility"]["left_eye"] == "visible" else "visible"
                )

    queue_obj, export, _ = _session(tmp_path, export_mut=disagree_left_eye)
    with pytest.raises(fc.FrameContractError, match="kappa") as info:
        occ.to_synthetic_face_instances(export, queue_obj)
    assert info.value.repair_item_ids
    assert all(item.startswith("img-") for item in info.value.repair_item_ids)


def test_insufficient_support_refuses_without_repair_list(tmp_path: Path) -> None:
    queue_obj, export, _ = _session(tmp_path, gold=_gold_doc(n=19))
    with pytest.raises(fc.FrameContractError, match="support") as info:
        occ.to_synthetic_face_instances(export, queue_obj)
    assert info.value.repair_item_ids == ()


def test_production_observation_reference_must_resolve(tmp_path: Path) -> None:
    queue_obj, export, _ = _session(tmp_path, observation_ref="synthetic:no-human-observation")
    with pytest.raises(fc.FrameContractError, match="observation"):
        occ.to_face_instances(export, queue_obj)
    queue_obj, export, _ = _session(tmp_path / "null", observation_ref=None)
    with pytest.raises(fc.FrameContractError, match="observation"):
        occ.to_face_instances(export, queue_obj)


def test_gold_accuracy_is_per_annotator_fraction(tmp_path: Path) -> None:
    queue_obj, export, _ = _session(tmp_path)
    assert occ.gold_accuracy(export, queue_obj.gold) == pytest.approx(1.0)


def test_union_delta_counts_feed_detector_gap_bound(tmp_path: Path) -> None:
    proposals = {
        "schema": "fir-occ-union-proposals/v1",
        "queue_id": "occ-u-0002",
        "annotation_tier": "a",
        "matched_fppi_declared": 0.01,
        "thresholds_declared_before_run": {"buffalo": 0.5, "candidate": 0.5},
        "qc": dict(QC),
        "items": [
            {
                "item_id": f"prop-{k:04d}",
                "image_id": f"image-{k:04d}",
                "image": f"img-{k:04d}.png",
                "image_sha256": _sha(k),
                "box": [2.0, 2.0, 3.0, 3.0],
                "sources": ["buffalo"] if k % 3 == 0 else (["candidate"] if k % 3 == 1 else ["buffalo", "candidate"]),
                "matched_gt": False,
            }
            for k in range(N_PRIMARY)
        ],
    }
    union_path = tmp_path / "proposals.json"
    proposal_sha = _write_json(union_path, proposals)
    gold = _gold_doc()
    for item in gold["items"]:
        item["decision"] = "face"
    gold_path = tmp_path / "gold.json"
    _write_json(gold_path, gold)
    answers, presented = [], {}
    for k, item in enumerate(proposals["items"]):
        pid = _pid("primary", item["item_id"])
        presented[pid] = {"role": "primary", "item_id": item["item_id"], "of": None, "gold_id": None}
        answers.append({"presented_id": pid, "status": "answered", "decision": "face" if k % 2 == 0 else "not_face"})
    for k, item in enumerate(proposals["items"][:20]):
        pid = _pid("consistency", item["item_id"])
        presented[pid] = {
            "role": "consistency",
            "item_id": item["item_id"],
            "of": _pid("primary", item["item_id"]),
            "gold_id": None,
        }
        answers.append({"presented_id": pid, "status": "answered", "decision": "face" if k % 2 == 0 else "not_face"})
    for g in gold["items"]:
        pid = _pid("known_answer", g["gold_id"])
        presented[pid] = {"role": "known_answer", "item_id": None, "of": None, "gold_id": g["gold_id"]}
        answers.append({"presented_id": pid, "status": "answered", "decision": "face"})
    export_doc = {
        "schema": "fir-occ-labels/v1",
        "queue_id": "occ-u-0002",
        "queue_sha256": proposal_sha,
        "mode": "union_delta",
        "annotator_id": "ann-01",
        "annotation_tier": "a",
        "rule_id": RULE,
        "observation_ref": None,
        "answers": answers,
        "hidden": {"presented": presented},
    }
    export_path = tmp_path / "union-export.json"
    _write_json(export_path, export_doc)
    queue_obj = occ.load_queue(union_path, gold_path)
    rows = occ.union_delta_counts(occ.load_label_export(export_path), queue_obj)
    assert len(rows) == N_PRIMARY
    expected_tp_buffalo = sum(1 for k in range(N_PRIMARY) if k % 2 == 0 and k % 3 in (0, 2))
    expected_tp_candidate = sum(1 for k in range(N_PRIMARY) if k % 2 == 0 and k % 3 in (1, 2))
    expected_faces = sum(1 for k in range(N_PRIMARY) if k % 2 == 0)
    assert detector_gap_bound(rows) == pytest.approx((expected_tp_buffalo - expected_tp_candidate) / expected_faces)
