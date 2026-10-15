"""FIR-OCC label queue importer (S7): export validation, QC gate and fir-occ-v1 rows.

Labels are the operator's answers from pixels. Captions and detector output
never reach this module as label values. Every import is gated on the queue's
QC block: a null value, insufficient support, or a below-floor agreement or
gold accuracy refuses the import with ``FrameContractError``. A below-floor
set lists its item ids in ``repair_item_ids`` and is not imported as labels
[HITL-03, HITL-05, MLDATA-03].

The QC floors and support minima are read from the queue file's ``qc`` block
and are never module constants [rg-009]. Tier-(a) rows are never exhaustive.
Production resolves observation evidence and its applicability [MEAS-29]. Structural
validation cannot establish that a human observation actually happened. No such
record is supplied here. The separate generated-fixture importer regenerates its
allowlisted numpy recipe and emits persistently ineligible synthetic rows.

Canon v0.26.2: Observe measurement production [MEAS-29], Seeing with Fresh Eyes:
Meaning, Space, Data, Truth, ch. 4; Gold-embedded annotator QC [HITL-03], Agreement
is a diagnostic, not the truth [HITL-05], SME adjudication escalation [HITL-07],
Human-in-the-Loop ML; Resolve label multiplicity in writing [MLDATA-03], Designing
Machine Learning Systems. Numeric policy comes exclusively from queue.qc.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct
import zlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

from scripts.eval_harness.firbench_contract import FrameContractError
from scripts.eval_harness.gate_contract import RUBRIC_VERSION
from scripts.eval_harness.pilot_draw import GoldItem, GoldKind, PilotDrawError, StratumName
from scripts.eval_harness.union_adjudication import UnionAdjudicationInput

EXPORT_SCHEMA = "fir-occ-labels/v1"
QUEUE_SCHEMA = "fir-occ-queue/v1"
UNION_SCHEMA = "fir-occ-union-proposals/v1"
GOLD_SCHEMA = "fir-occ-gold/v1"
MODES = frozenset({"face", "union_delta"})
TIERS = frozenset({"a", "b"})
REGIONS = ("left_eye", "right_eye", "nose", "mouth")
OCCLUDERS = frozenset({"mask", "sunglasses", "hand", "other_object", "mixed"})
VISIBILITY = frozenset({"visible", "occluded", "out_of_frame", "uncertain"})
ANNOTATOR_IDENTITY = frozenset({"unknown", "unresolved"})
DECISIONS = frozenset({"face", "not_face", "cannot_tell"})
ROLES = frozenset({"primary", "consistency", "known_answer"})
SOURCES = frozenset({"buffalo", "candidate"})
QC_KEYS = frozenset(
    {
        "gold_share",
        "repeat_fraction",
        "repeat_percent_agreement_floor",
        "kappa_floor",
        "annotator_gold_accuracy_floor",
        "min_gold_decisions_per_annotator",
        "min_repeat_decisions_per_field",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _refuse(message: str, *, repair_item_ids: Sequence[str] = ()) -> FrameContractError:
    error = FrameContractError(message)
    error.repair_item_ids = tuple(sorted(set(repair_item_ids)))
    return error


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrameContractError(f"{name} must be a non-empty string")
    return value


def _nullable_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise FrameContractError(f"{name} must be a finite number")
    return float(value)


def _box(value: object, name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise FrameContractError(f"{name} must be [x, y, w, h]")
    x, y, w, h = (_number(part, f"{name}[{index}]") for index, part in enumerate(value))
    if w <= 0 or h <= 0:
        raise FrameContractError(f"{name} must have positive width and height")
    return (x, y, w, h)


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrameContractError(f"{name} must be an object")
    return value


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise FrameContractError(f"{name} must be an array")
    return value


def _keys(payload: Mapping[str, Any], required: frozenset[str], name: str) -> None:
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required)
    if missing:
        raise FrameContractError(f"{name} is missing required keys {missing}")
    if unknown:
        raise FrameContractError(f"{name} has unknown keys {unknown}")


# --- face and answer validation -------------------------------------------------------


def _face(raw: object, name: str) -> dict[str, Any]:
    payload = _object(raw, name)
    _keys(payload, frozenset({"source", "face_key", "box", "occluders", "visibility", "identity_status"}), name)
    if payload["source"] not in {"confirmed", "added"}:
        raise FrameContractError(f"{name}.source must be 'confirmed' or 'added'")
    occluders = payload["occluders"]
    if occluders is not None:
        occluders = _list(occluders, f"{name}.occluders")
        for member in occluders:
            if member not in OCCLUDERS:
                raise FrameContractError(f"{name}.occluders contains unknown occluder {member!r}")
        occluders = list(occluders)
    visibility = _object(payload["visibility"], f"{name}.visibility")
    _keys(visibility, frozenset(REGIONS), f"{name}.visibility")
    for region in REGIONS:
        if visibility[region] is not None and visibility[region] not in VISIBILITY:
            raise FrameContractError(f"{name}.visibility.{region} is not a rubric state")
    if payload["identity_status"] not in ANNOTATOR_IDENTITY:
        raise FrameContractError(f"{name}.identity_status must be 'unknown' or 'unresolved'")
    return {
        "source": payload["source"],
        "face_key": _text(payload["face_key"], f"{name}.face_key"),
        "box": list(_box(payload["box"], f"{name}.box")),
        "occluders": occluders,
        "visibility": {region: visibility[region] for region in REGIONS},
        "identity_status": payload["identity_status"],
    }


def _faces(raw: object, name: str) -> tuple[dict[str, Any], ...]:
    faces = tuple(_face(face, f"{name}[{index}]") for index, face in enumerate(_list(raw, name)))
    keys = [face["face_key"] for face in faces]
    if len(set(keys)) != len(keys):
        raise FrameContractError(f"{name} has duplicate face_key values")
    return faces


# --- export ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    presented_id: str
    status: str
    faces: tuple[dict[str, Any], ...]
    decision: str | None


@dataclass(frozen=True)
class LabelExport:
    sha256: str
    queue_id: str
    queue_sha256: str
    mode: str
    annotator_id: str
    annotation_tier: str
    rule_id: str
    observation_ref: str | None
    answers: tuple[Answer, ...]
    presented: Mapping[str, Mapping[str, Any]]
    state_sha256: str = ""


def _answer(raw: object, name: str, mode: str) -> Answer:
    payload = _object(raw, name)
    status = payload.get("status")
    if mode == "face":
        _keys(payload, frozenset({"presented_id", "status", "faces"}), name)
        faces = _faces(payload["faces"], f"{name}.faces")
        decision = None
    else:
        _keys(payload, frozenset({"presented_id", "status", "decision"}), name)
        faces = ()
        decision = payload["decision"]
    if status not in {"answered", "skipped"}:
        raise FrameContractError(f"{name}.status must be 'answered' or 'skipped'")
    if status == "skipped" and (faces or decision is not None):
        raise FrameContractError(f"{name} is skipped but carries an answer")
    if mode == "union_delta" and status == "answered" and decision not in DECISIONS:
        raise FrameContractError(f"{name}.decision must be face, not_face or cannot_tell")
    return Answer(_text(payload["presented_id"], f"{name}.presented_id"), status, faces, decision)


def parse_export(raw: object, *, sha256: str) -> LabelExport:
    """Validate an export document; raise ``FrameContractError`` on any schema violation."""
    payload = _object(raw, "export")
    _keys(
        payload,
        frozenset(
            {
                "schema",
                "queue_id",
                "queue_sha256",
                "mode",
                "annotator_id",
                "annotation_tier",
                "rule_id",
                "observation_ref",
                "answers",
                "hidden",
            }
        ),
        "export",
    )
    if payload["schema"] != EXPORT_SCHEMA:
        raise FrameContractError(f"export schema must be {EXPORT_SCHEMA!r}")
    if payload["mode"] not in MODES:
        raise FrameContractError("export.mode must be 'face' or 'union_delta'")
    if payload["annotation_tier"] not in TIERS:
        raise FrameContractError("export.annotation_tier must be 'a' or 'b'")
    if payload["rule_id"] != RUBRIC_VERSION:
        raise FrameContractError(f"export.rule_id must be {RUBRIC_VERSION!r}")
    queue_sha = _text(payload["queue_sha256"], "export.queue_sha256")
    if not _SHA256.match(queue_sha):
        raise FrameContractError("export.queue_sha256 must be a sha256 hex digest")
    answers = tuple(
        _answer(answer, f"export.answers[{index}]", payload["mode"])
        for index, answer in enumerate(_list(payload["answers"], "export.answers"))
    )
    hidden = _object(payload["hidden"], "export.hidden")
    _keys(hidden, frozenset({"presented"}), "export.hidden")
    presented = _object(hidden["presented"], "export.hidden.presented")
    checked: dict[str, Mapping[str, Any]] = {}
    for pid, entry in presented.items():
        record = _object(entry, f"export.hidden.presented[{pid}]")
        _keys(record, frozenset({"role", "item_id", "of", "gold_id"}), f"export.hidden.presented[{pid}]")
        if record["role"] not in ROLES:
            raise FrameContractError(f"presented[{pid}].role is not a known role")
        _text(pid, "presented id")
        for key in ("item_id", "of", "gold_id"):
            _nullable_text(record[key], f"presented[{pid}].{key}")
        checked[pid] = dict(record)
    answer_ids = [answer.presented_id for answer in answers]
    if len(set(answer_ids)) != len(answer_ids):
        raise FrameContractError("export.answers repeats a presented_id")
    if set(answer_ids) != set(checked):
        raise FrameContractError("export answers and hidden presented map do not cover the same ids")
    observation = payload["observation_ref"]
    export = LabelExport(
        sha256=sha256,
        queue_id=_text(payload["queue_id"], "export.queue_id"),
        queue_sha256=queue_sha,
        mode=payload["mode"],
        annotator_id=_text(payload["annotator_id"], "export.annotator_id"),
        annotation_tier=payload["annotation_tier"],
        rule_id=payload["rule_id"],
        observation_ref=_nullable_text(observation, "export.observation_ref"),
        answers=answers,
        presented=checked,
    )
    return replace(export, state_sha256=_state_hash(export))


def load_label_export(path: str | Path) -> LabelExport:
    """Load and validate an operator export; malformed or unreadable input is ``FrameContractError``."""
    try:
        data = Path(path).read_bytes()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameContractError(f"cannot read label export {path!s}: {exc}") from exc
    return parse_export(raw, sha256=hashlib.sha256(data).hexdigest())


# --- queue and gold -------------------------------------------------------------------


@dataclass(frozen=True)
class QueueItem:
    item_id: str
    image: str
    image_id: str
    image_sha256: str
    duplicate_group: str | None
    sources: tuple[str, ...]
    box: tuple[float, float, float, float] | None
    shown_boxes: tuple[tuple[float, float, float, float], ...]
    matched_gt: bool
    provenance: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class GoldRecord:
    gold_id: str
    image: str
    item: GoldItem
    faces: tuple[dict[str, Any], ...]
    decision: str | None
    provenance: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class Queue:
    sha256: str
    queue_id: str
    mode: str
    annotation_tier: str
    items: tuple[QueueItem, ...]
    qc: Mapping[str, Any]
    gold: tuple[GoldRecord, ...]
    declaration: Mapping[str, Any]
    root: Path = Path(".")
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)
    gold_metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)
    state_sha256: str = ""


_GOLD_KEYS = frozenset(
    {
        "gold_id",
        "image",
        "image_sha256",
        "media_id",
        "stratum",
        "kind",
        "answer_source",
        "authored_by",
        "live_queue_annotators",
    }
)


def _gold_item(raw: object, name: str, mode: str) -> GoldRecord:
    payload = _object(raw, name)
    provenance = dict(payload)
    payload = {k: v for k, v in payload.items() if k not in {"data_origin", "fixture_recipe"}}
    if mode == "union_delta":
        payload = {key: value for key, value in payload.items() if key != "faces"}
        expected = _GOLD_KEYS | {"decision"}
    else:
        expected = _GOLD_KEYS | {"faces"}
    _keys(payload, frozenset(expected), name)
    live = _list(payload["live_queue_annotators"], f"{name}.live_queue_annotators")
    try:
        item = GoldItem(
            sha256=_text(payload["image_sha256"], f"{name}.image_sha256"),
            media_id=_text(payload["media_id"], f"{name}.media_id"),
            stratum=StratumName(payload["stratum"]),
            kind=GoldKind(payload["kind"]),
            answer_source=payload["answer_source"],
            authored_by=payload["authored_by"],
            live_queue_annotators=tuple(_text(slot, f"{name}.live_queue_annotators") for slot in live),
        )
    except (PilotDrawError, ValueError) as exc:
        raise FrameContractError(f"{name} fails gold checks: {exc}") from exc
    if mode == "union_delta":
        decision = payload["decision"]
        if decision not in DECISIONS:
            raise FrameContractError(f"{name}.decision must be face, not_face or cannot_tell")
        return GoldRecord(
            _text(payload["gold_id"], f"{name}.gold_id"),
            _text(payload["image"], f"{name}.image"),
            item,
            (),
            decision,
            provenance,
        )
    faces = _faces(payload["faces"], f"{name}.faces")
    return GoldRecord(
        _text(payload["gold_id"], f"{name}.gold_id"),
        _text(payload["image"], f"{name}.image"),
        item,
        faces,
        None,
        provenance,
    )


def load_queue(path: str | Path, gold_path: str | Path) -> Queue:
    """Load a private queue (face or union-delta) with its gold file; never reads any image."""
    try:
        data = Path(path).read_bytes()
        raw = json.loads(data.decode("utf-8"))
        gold_raw = json.loads(Path(gold_path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameContractError(f"cannot read queue or gold file: {exc}") from exc
    payload = _object(raw, "queue")
    mode = "union_delta" if payload.get("schema") == UNION_SCHEMA else "face"
    if payload.get("schema") not in {QUEUE_SCHEMA, UNION_SCHEMA}:
        raise FrameContractError("queue schema must be fir-occ-queue/v1 or fir-occ-union-proposals/v1")
    if payload.get("mode", mode) != mode:
        raise FrameContractError("queue mode does not match its schema")
    if payload.get("annotation_tier") not in TIERS:
        raise FrameContractError("queue.annotation_tier must be 'a' or 'b'")
    qc = _object(payload.get("qc"), "queue.qc")
    _validate_qc(qc)
    items: list[QueueItem] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(_list(payload.get("items"), "queue.items")):
        item = _object(raw_item, f"queue.items[{index}]")
        item_id = _text(item.get("item_id"), f"queue.items[{index}].item_id")
        if item_id in seen:
            raise FrameContractError(f"queue repeats item_id {item_id!r}")
        seen.add(item_id)
        image_sha = _text(item.get("image_sha256"), f"queue.items[{index}].image_sha256")
        if not _SHA256.match(image_sha):
            raise FrameContractError(f"queue.items[{index}].image_sha256 must be a sha256 hex digest")
        sources = tuple(item.get("sources", ()))
        if mode == "union_delta" and (not sources or not set(sources) <= SOURCES):
            raise FrameContractError(f"queue.items[{index}].sources must name buffalo and/or candidate")
        box = _box(item.get("box"), f"queue.items[{index}].box") if mode == "union_delta" else None
        confirmed = tuple(
            _box(part, f"queue.items[{index}].confirmed_boxes[{number}]")
            for number, part in enumerate(
                _list(item.get("confirmed_boxes", []), f"queue.items[{index}].confirmed_boxes")
            )
        )
        if mode == "union_delta":
            shown = (box,)
        elif item.get("show_confirmed_boxes") is True:
            shown = confirmed
        else:
            shown = ()
        items.append(
            QueueItem(
                item_id=item_id,
                image=_text(item.get("image"), f"queue.items[{index}].image"),
                image_id=_text(item.get("image_id", item_id), f"queue.items[{index}].image_id"),
                image_sha256=image_sha,
                duplicate_group=_nullable_text(item.get("duplicate_group"), f"queue.items[{index}].duplicate_group"),
                sources=sources,
                box=box,
                shown_boxes=shown,
                matched_gt=bool(item.get("matched_gt", False)),
                provenance=copy.deepcopy(dict(item)),
            )
        )
    declaration: dict[str, Any] = {}
    if mode == "union_delta":
        thresholds = _object(payload.get("thresholds_declared_before_run"), "queue.thresholds_declared_before_run")
        declaration = {
            "matched_fppi_declared": payload.get("matched_fppi_declared"),
            "thresholds_declared_before_run": {key: thresholds.get(key) for key in sorted(SOURCES)},
        }
    if _object(gold_raw, "gold").get("schema") != GOLD_SCHEMA:
        raise _refuse(f"gold schema must be {GOLD_SCHEMA!r}")
    gold = tuple(
        _gold_item(raw_gold, f"gold.items[{index}]", mode)
        for index, raw_gold in enumerate(_list(_object(gold_raw, "gold").get("items"), "gold.items"))
    )
    queue = Queue(
        sha256=hashlib.sha256(data).hexdigest(),
        queue_id=_text(payload.get("queue_id"), "queue.queue_id"),
        mode=mode,
        annotation_tier=payload["annotation_tier"],
        items=tuple(items),
        qc=dict(qc),
        gold=gold,
        declaration=declaration,
        root=Path(path).resolve().parent,
        metadata=copy.deepcopy(dict(payload)),
        gold_metadata=copy.deepcopy(dict(gold_raw)),
    )
    return replace(queue, state_sha256=_state_hash(queue))


def _state_hash(value: LabelExport | Queue) -> str:
    """Bind the loaded normalized state as well as its original file hash.

    Frozen dataclasses can still contain mutable dictionaries. Imports refuse
    edits to those dictionaries instead of citing the hash of different answers
    or a different predeclared policy. Raw files are never rewritten here.
    """
    state = asdict(value)
    state.pop("state_sha256")
    if "root" in state:
        state["root"] = str(state["root"])
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- agreement, accuracy and the QC gate -----------------------------------------------


@dataclass(frozen=True)
class FieldAgreement:
    field: str
    n: int
    percent: float
    kappa: float | None
    reason: str | None = None


def _field_names(mode: str) -> tuple[str, ...]:
    if mode == "union_delta":
        return ("decision",)
    return ("occluders", *(f"visibility.{region}" for region in REGIONS), "identity_status")


def _field_value(answer: Answer | GoldRecord, field: str, mode: str) -> str:
    if mode == "union_delta":
        return json.dumps(answer.decision)
    faces = answer.faces
    values = []
    for face in faces:
        if field == "occluders":
            value: object = face["occluders"]
        elif field == "identity_status":
            value = face["identity_status"]
        else:
            value = face["visibility"][field.split(".", 1)[1]]
        values.append(json.dumps(value, sort_keys=True))
    return json.dumps(sorted(values)) + f"|faces={len(faces)}"


def _cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for first, second in pairs if first == second) / n
    first_marginal = Counter(first for first, _ in pairs)
    second_marginal = Counter(second for _, second in pairs)
    expected = sum(
        (first_marginal[label] / n) * (second_marginal[label] / n)
        for label in set(first_marginal) | set(second_marginal)
    )
    if math.isclose(expected, 1.0, rel_tol=0.0, abs_tol=1e-12):
        return None
    return (observed - expected) / (1.0 - expected)


def _repeat_pairs(export: LabelExport) -> dict[str, tuple[Answer, Answer, str]]:
    """Map each consistency repeat to (primary answer, repeat answer, queue item id)."""
    by_id = {answer.presented_id: answer for answer in export.answers}
    pairs: dict[str, tuple[Answer, Answer, str]] = {}
    for pid, record in export.presented.items():
        if record["role"] != "consistency":
            continue
        original = by_id.get(record["of"])
        repeat = by_id[pid]
        if original is None or original.status != "answered" or repeat.status != "answered":
            continue
        pairs[pid] = (original, repeat, str(record["item_id"]))
    return pairs


def repeat_agreement(export: LabelExport) -> dict[str, FieldAgreement]:
    """Per-field percent agreement and Cohen's kappa over blind repeats [HITL-05]."""
    pairs = _repeat_pairs(export)
    results: dict[str, FieldAgreement] = {}
    for field in _field_names(export.mode):
        values = [
            (_field_value(first, field, export.mode), _field_value(second, field, export.mode))
            for first, second, _ in pairs.values()
        ]
        agree = sum(1 for first, second in values if first == second)
        percent = agree / len(values) if values else 0.0
        kappa = _cohen_kappa(values)
        results[field] = FieldAgreement(
            field, len(values), percent, kappa, "kappa_undefined" if kappa is None else None
        )
    return results


def gold_accuracy(export: LabelExport, gold: Sequence[GoldRecord]) -> float:
    """Fraction of known-answer decisions that match the independent SME answer on every field."""
    by_gold = {record.gold_id: record for record in gold}
    total = 0
    correct = 0
    for answer in export.answers:
        record = export.presented[answer.presented_id]
        if record["role"] != "known_answer" or answer.status != "answered":
            continue
        known = by_gold.get(record["gold_id"])
        if known is None:
            raise FrameContractError(f"known-answer id {record['gold_id']!r} is not in the gold file")
        total += 1
        if all(
            _field_value(answer, field, export.mode) == _field_value(known, field, export.mode)
            for field in _field_names(export.mode)
        ):
            correct += 1
    if total == 0:
        raise FrameContractError("no known-answer decisions to score")
    return correct / total


def _validate_qc(qc: Mapping[str, Any]) -> None:
    _keys(qc, QC_KEYS, "queue.qc")
    for key, value in qc.items():
        if value is None:  # A small unfinished queue may load/export, but cannot import.
            continue
        if key.startswith("min_"):
            if type(value) is not int or value <= 0:
                raise _refuse(f"qc.{key} must be a positive integer")
        elif not 0 < _number(value, f"qc.{key}") <= 1:
            raise _refuse(f"qc.{key} must be in (0, 1]")


def _validate_binding(export: LabelExport, queue: Queue) -> None:
    if export.state_sha256 != _state_hash(export) or queue.state_sha256 != _state_hash(queue):
        raise _refuse("immutable export/queue state changed after loading; file hashes no longer bind it")
    if export.queue_sha256 != queue.sha256 or export.queue_id != queue.queue_id:
        raise _refuse("export was produced from a different queue file")
    if export.mode != queue.mode:
        raise _refuse(f"export mode {export.mode!r} does not match queue mode {queue.mode!r}")
    if export.annotation_tier != queue.annotation_tier:
        raise _refuse("export annotation_tier differs from queue")
    items = {item.item_id: item for item in queue.items}
    gold = {g.gold_id: g for g in queue.gold}
    if len(gold) != len(queue.gold):
        raise _refuse("duplicate known-answer ids cannot count as independent support")
    gold_ids, gold_images, repeat_items, primary_items = set(), set(), set(), set()
    for record in export.presented.values():
        role = record["role"]
        if role == "known_answer":
            known = gold.get(record["gold_id"])
            if known is None or record["of"] is not None or record["item_id"] is not None:
                raise _refuse("invalid known-answer assignment")
            if known.gold_id in gold_ids or known.item.sha256 in gold_images:
                raise _refuse("reused known answers cannot inflate independent support")
            if (
                export.annotator_id == known.item.authored_by
                or export.annotator_id not in known.item.live_queue_annotators
            ):
                raise _refuse("gold author must be independent of the evaluated annotator")
            gold_ids.add(known.gold_id)
            gold_images.add(known.item.sha256)
        else:
            if record["item_id"] not in items or record["gold_id"] is not None:
                raise _refuse("presentation names an item absent from the queue")
            if role == "primary":
                if record["of"] is not None or record["item_id"] in primary_items:
                    raise _refuse("duplicate primary assignment")
                primary_items.add(record["item_id"])
            else:
                original = export.presented.get(record["of"])
                if (
                    not original
                    or original["role"] != "primary"
                    or original["item_id"] != record["item_id"]
                    or record["item_id"] in repeat_items
                ):
                    raise _refuse("repeat must be a new presentation of one distinct primary")
                repeat_items.add(record["item_id"])
    groups: dict[str, str] = {}
    presented_groups: set[str] = set()
    for item in queue.items:
        if item.duplicate_group is not None:
            if item.item_id in primary_items:
                if item.duplicate_group in presented_groups:
                    raise _refuse("exact duplicate groups must be labelled once")
                presented_groups.add(item.duplicate_group)
            previous = groups.setdefault(item.duplicate_group, item.image_sha256)
            if previous != item.image_sha256:
                raise _refuse("exact duplicate group contains different image hashes")


def qc_report(export: LabelExport, queue: Queue) -> dict[str, Any]:
    """Inspectable pre-adjudication diagnostics; unknown support is never a pass.

    This report does not mutate answers or resolve an undefined kappa [HITL-05].
    """
    _validate_binding(export, queue)
    _validate_qc(queue.qc)
    null = sorted(k for k in QC_KEYS if queue.qc[k] is None)
    if null:
        raise _refuse(f"qc value is null for {null}; import refused until the operator sets them")
    fields, repair, sme, failures = {}, set(), set(), []
    pairs = _repeat_pairs(export)
    for name, metric in repeat_agreement(export).items():
        value = asdict(metric)
        if metric.n < queue.qc["min_repeat_decisions_per_field"]:
            value["status"] = "support_not_accrued"
        elif metric.percent < queue.qc["repeat_percent_agreement_floor"] or (
            metric.kappa is not None and metric.kappa < queue.qc["kappa_floor"]
        ):
            value["status"] = "below_floor"
        elif metric.kappa is None:
            value["status"] = "sme_required"
        else:
            value["status"] = "passed"
        if value["status"] != "passed":
            failures.append(f"{name}: {value['status']}, agreement {metric.percent:.3f}, kappa {metric.kappa}")
        if value["status"] in {"below_floor", "sme_required"}:
            affected = {
                item_id
                for a, b, item_id in pairs.values()
                if metric.kappa is None or _field_value(a, name, export.mode) != _field_value(b, name, export.mode)
            }
            sme.update(affected)
            if value["status"] == "below_floor":
                repair.update(affected)
        fields[name] = value
    gold_n = sum(
        a.status == "answered" and export.presented[a.presented_id]["role"] == "known_answer" for a in export.answers
    )
    accuracy = gold_accuracy(export, queue.gold) if gold_n else None
    gold_status = (
        "support_not_accrued"
        if gold_n < queue.qc["min_gold_decisions_per_annotator"]
        else "passed"
        if accuracy is not None and accuracy >= queue.qc["annotator_gold_accuracy_floor"]
        else "below_floor"
    )
    if gold_status != "passed":
        failures.append(f"gold: {gold_status}, accuracy {accuracy}")
        if gold_status == "below_floor":
            repair.update(_wrong_gold_ids(export, queue))
    # Uncertain and evaluation-critical items stay inspectable in the SME route.
    for a in export.answers:
        r = export.presented[a.presented_id]
        if r["role"] == "primary" and any(
            f["occluders"] is None or "uncertain" in f["visibility"].values() or None in f["visibility"].values()
            for f in a.faces
        ):
            sme.add(r["item_id"])
    return {
        "export_sha256": export.sha256,
        "fields": fields,
        "annotators": {export.annotator_id: {"n": gold_n, "accuracy": accuracy, "status": gold_status}},
        "repair_item_ids": sorted(repair),
        "sme_item_ids": sorted(sme),
        "failures": failures,
    }


def _require_qc(export: LabelExport, queue: Queue, *, resolved_fields: frozenset[str] = frozenset()) -> dict[str, Any]:
    report = qc_report(export, queue)
    if any(v["status"] == "support_not_accrued" for v in report["fields"].values()) or any(
        v["status"] == "support_not_accrued" for v in report["annotators"].values()
    ):
        raise _refuse("insufficient support: support_not_accrued")
    failing = [
        name
        for name, v in report["fields"].items()
        if v["status"] != "passed" and not (v["status"] == "sme_required" and name in resolved_fields)
    ]
    if failing or any(v["status"] != "passed" for v in report["annotators"].values()):
        error = _refuse(
            f"below-floor QC refuses import: kappa/agreement/gold; {report['failures']}",
            repair_item_ids=report["repair_item_ids"],
        )
        error.sme_item_ids = tuple(report["sme_item_ids"])
        error.qc_report = report
        raise error
    return report


def _gold_accuracy_or_none(export: LabelExport, queue: Queue) -> float | None:
    if not queue.gold:
        return None
    return gold_accuracy(export, queue.gold)


def _wrong_gold_ids(export: LabelExport, queue: Queue) -> list[str]:
    by_gold = {record.gold_id: record for record in queue.gold}
    wrong = []
    for answer in export.answers:
        record = export.presented[answer.presented_id]
        if record["role"] != "known_answer" or answer.status != "answered":
            continue
        known = by_gold[record["gold_id"]]
        if any(
            _field_value(answer, field, export.mode) != _field_value(known, field, export.mode)
            for field in _field_names(export.mode)
        ):
            wrong.append(str(record["gold_id"]))
    return wrong


# --- fir-occ-v1 rows -------------------------------------------------------------------

_UNKNOWN_REGIONS = dict.fromkeys(REGIONS)


def _annotation(export: LabelExport, queue: Queue, face: Mapping[str, Any] | None) -> dict[str, Any]:
    exhaustive = False if export.annotation_tier == "a" else None
    return {
        "occluders": None if face is None else face["occluders"],
        "visibility": dict(_UNKNOWN_REGIONS) if face is None else dict(face["visibility"]),
        "annotation_tier": export.annotation_tier,
        "exhaustive": exhaustive,
        "provenance_ref": f"{EXPORT_SCHEMA}:{export.sha256}",
        "rule_id": export.rule_id,
        "observation_ref": export.observation_ref,
        "qc_ref": f"fir-occ-queue-qc:{queue.sha256}",
    }


def _rows_for(
    export: LabelExport, queue: Queue, answer: Answer, item: QueueItem, *, duplicate_of: str | None
) -> list[dict[str, Any]]:
    base = {
        "item_id": item.item_id,
        "image_sha256": item.image_sha256,
        "image_id": item.image_id,
        "duplicate_of": duplicate_of,
        "annotation_tier": export.annotation_tier,
        "rule_id": export.rule_id,
    }
    if answer.status == "skipped":
        return [
            {
                **base,
                "unit_id": item.item_id,
                "response": "nonresponse",
                "face_key": None,
                "box": None,
                "identity_status": None,
                "source": None,
                "annotation": _annotation(export, queue, None),
            }
        ]
    if not answer.faces:
        return [
            {
                **base,
                "unit_id": item.item_id,
                "response": "answered_no_face",
                "face_key": None,
                "box": None,
                "identity_status": None,
                "source": None,
                "annotation": _annotation(export, queue, None),
            }
        ]
    return [
        {
            **base,
            "unit_id": f"{item.item_id}#{face['face_key']}",
            "response": "answered",
            "face_key": face["face_key"],
            "box": face["box"],
            "identity_status": face["identity_status"],
            "source": face["source"],
            "annotation": _annotation(export, queue, face),
        }
        for face in answer.faces
    ]


def _members(queue: Queue, item: QueueItem) -> list[QueueItem]:
    if item.duplicate_group is None:
        return []
    return [
        other
        for other in queue.items
        if other.duplicate_group == item.duplicate_group and other.item_id != item.item_id
    ]


def _face_rows(export: LabelExport, queue: Queue) -> tuple[dict[str, Any], ...]:
    """Return one fir-occ-v1 row per face, nonresponse row and propagated duplicate.

    Refused with ``FrameContractError`` unless the queue's QC passes. Tier-(a) rows
    are never exhaustive. Blind repeats and known-answer decisions are QC-only and
    never produce rows.
    """
    if export.mode != "face":
        raise FrameContractError("to_face_instances takes a face-mode export")
    items = {item.item_id: item for item in queue.items}
    rows: list[dict[str, Any]] = []
    represented: set[str] = set()
    for answer in export.answers:
        record = export.presented[answer.presented_id]
        if record["role"] != "primary":
            continue
        item = items.get(str(record["item_id"]))
        if item is None:
            raise FrameContractError(f"export names item {record['item_id']!r} absent from the queue")
        represented.add(item.item_id)
        rows.extend(_rows_for(export, queue, answer, item, duplicate_of=None))
        for member in _members(queue, item):
            represented.add(member.item_id)
            rows.extend(_rows_for(export, queue, answer, member, duplicate_of=item.item_id))
    for item in queue.items:
        if item.item_id not in represented:
            rows.append(
                {
                    "unit_id": item.item_id,
                    "item_id": item.item_id,
                    "image_sha256": item.image_sha256,
                    "image_id": item.image_id,
                    "duplicate_of": None,
                    "annotation_tier": export.annotation_tier,
                    "rule_id": export.rule_id,
                    "response": "not_presented",
                    "face_key": None,
                    "box": None,
                    "identity_status": None,
                    "source": None,
                    "annotation": _annotation(export, queue, None),
                }
            )
    return tuple(rows)


def union_delta_counts(export: LabelExport, queue: Queue) -> tuple[UnionAdjudicationInput, ...]:
    """Image rows for ``union_adjudication.detector_gap_bound``.

    Only ``face`` and ``not_face`` decisions contribute; ``cannot_tell`` and skips
    are excluded rather than counted as misses. Source attribution comes from the
    queue, never from the export. Declared thresholds and FPPI must be set before
    the run; a null value refuses the counts.
    """
    if export.mode != "union_delta" or queue.mode != "union_delta":
        raise FrameContractError("union_delta_counts needs a union-delta export and proposals file")
    _require_qc(export, queue)
    declaration = queue.declaration
    if declaration.get("matched_fppi_declared") is None or any(
        value is None for value in declaration["thresholds_declared_before_run"].values()
    ):
        raise FrameContractError("union declaration (matched_fppi and thresholds) must be set before the run")
    items = {item.item_id: item for item in queue.items}
    rows: list[UnionAdjudicationInput] = []
    for answer in export.answers:
        record = export.presented[answer.presented_id]
        if record["role"] != "primary" or answer.decision not in {"face", "not_face"}:
            continue
        item = items[str(record["item_id"])]
        is_face = answer.decision == "face"
        rows.append(
            UnionAdjudicationInput(
                image_id=item.image_id,
                # T-14 restricts the union to human-verified faces, so union boxes equal verified faces.
                union_boxes=int(is_face),
                human_true_faces=int(is_face),
                tp_buffalo_i=int(is_face and "buffalo" in item.sources),
                tp_candidate_i=int(is_face and "candidate" in item.sources),
                matched_fppi_declared=float(declaration["matched_fppi_declared"]),
                thresholds_declared_before_run={
                    key: float(value) for key, value in declaration["thresholds_declared_before_run"].items()
                },
            )
        )
    return tuple(rows)


# --- evidence and recovery -------------------------------------------------------------


def _read_document(path: Path) -> tuple[Mapping[str, Any], str]:
    try:
        data = path.read_bytes()
        raw = json.loads(data)
    except (OSError, ValueError, UnicodeError) as exc:
        raise _refuse(f"cannot resolve evidence record {path}: {exc}") from exc
    return _object(raw, "evidence record"), hashlib.sha256(data).hexdigest()


def _linked_file(raw: object, root: Path) -> Path:
    link = _object(raw, "evidence link")
    _keys(link, frozenset({"path", "sha256"}), "evidence link")
    path = root / _text(link["path"], "evidence path")
    _, digest = _read_document(path)
    if digest != link["sha256"]:
        raise _refuse("evidence link hash mismatch")
    return path


def _primary_answers(export: LabelExport) -> dict[str, Answer]:
    return {
        str(export.presented[a.presented_id]["item_id"]): a
        for a in export.answers
        if export.presented[a.presented_id]["role"] == "primary"
    }


def _same_answer(first: Answer, second: Answer) -> bool:
    return (first.status, first.faces, first.decision) == (second.status, second.faces, second.decision)


def _sme_fields(
    evidence: Mapping[str, Any],
    candidate: LabelExport,
    validation: LabelExport,
    queue: Queue,
    report: Mapping[str, Any],
    scope: set[str],
) -> frozenset[str]:
    resolved: set[str] = set()
    for raw in _list(evidence.get("sme_resolutions", []), "sme_resolutions"):
        r = _object(raw, "SME resolution")
        name = r.get("field")
        if name not in report["fields"] or name in resolved:
            raise _refuse("SME resolution has an unknown or duplicate field")
        if r.get("candidate_sha256") != candidate.sha256 or set(_list(r.get("item_ids"), "SME item_ids")) != scope:
            raise _refuse("SME resolution must cover the exact corrected candidate and item scope")
        if r.get("expert_id") != validation.annotator_id:
            raise _refuse("SME expert lacks independent gold validation in this run")
        if r.get("disagreement_rule") != evidence["declaration"]["disagreement_rule"]:
            raise _refuse("SME disagreement rule differs from the declared rule")
        _text(r.get("rationale"), "SME rationale")
        metric = report["fields"][name]
        expected = "accept_undefined_kappa" if metric["kappa"] is None else "accept_corrected_field"
        if r.get("disposition") != expected or metric["status"] not in {"passed", "sme_required"}:
            raise _refuse("SME disposition cannot waive numeric floors or missing repeat support")
        v = _object(r.get("independent_validation"), "SME independent_validation")
        _text(v.get("method"), "SME independent validation method")
        _text(v.get("limits"), "SME independent validation limits")
        _list(v.get("exceptions"), "SME independent validation exceptions")
        known = {g.gold_id: g for g in queue.gold}
        answers = [
            a
            for a in validation.answers
            if a.status == "answered" and validation.presented[a.presented_id]["role"] == "known_answer"
        ]
        n = len(answers)
        accuracy = (
            sum(
                _field_value(a, name, validation.mode)
                == _field_value(known[validation.presented[a.presented_id]["gold_id"]], name, validation.mode)
                for a in answers
            )
            / n
            if n
            else None
        )
        if (
            type(v.get("denominator")) is not int
            or v["denominator"] != n
            or n < queue.qc["min_gold_decisions_per_annotator"]
            or accuracy is None
            or _number(v.get("accuracy"), "SME accuracy") != accuracy
            or accuracy < queue.qc["annotator_gold_accuracy_floor"]
        ):
            raise _refuse("SME field validation fails independent gold accuracy/support")
        resolved.add(name)
    return frozenset(resolved)


def _acceptance(export: LabelExport, queue: Queue, *, synthetic: bool) -> tuple[dict[str, Any], LabelExport]:
    """Keep original QC historical; qualify only the separately bound new candidate.

    acceptance_path is a separate file beside the queue, so linking the candidate
    hash does not create a queue/export hash cycle. Each input is content-pinned.
    Declarations are attestations, not proof of real independent human conduct.
    """
    _validate_binding(export, queue)
    path_value = queue.metadata.get("acceptance_path")
    if path_value is None:
        report = _require_qc(export, queue)
        return {"candidate_sha256": export.sha256, "accepted_qc": report, "run_id": export.queue_id}, export
    # A declared recovery cannot fall back to its old answers when evidence goes missing.
    path = queue.root / _text(path_value, "acceptance_path")
    evidence, evidence_sha = _read_document(path)
    if evidence.get("schema") != "fir-occ-acceptance/v1" or evidence.get("candidate_sha256") != export.sha256:
        raise _refuse("acceptance evidence is not bound to this candidate hash")
    prior = load_label_export(_linked_file(evidence.get("prior_export"), path.parent))
    prior_report = qc_report(prior, queue)
    if evidence.get("original_qc") != prior_report:
        raise _refuse("original QC evidence was rewritten or does not match the preserved export")
    # Same scope and worker; changed primary labels are candidates, never edits to history.
    if (
        prior.annotator_id != export.annotator_id
        or prior.presented != export.presented
        or prior.rule_id != export.rule_id
        or prior.annotation_tier != export.annotation_tier
        or prior.sha256 == export.sha256
    ):
        raise _refuse("corrected candidate must preserve original scope, worker and presentation history")
    old_answers = {a.presented_id: a for a in prior.answers}
    for a in export.answers:
        if export.presented[a.presented_id]["role"] != "primary" and not _same_answer(a, old_answers[a.presented_id]):
            raise _refuse("old gold/repeat answers cannot be rewritten as fresh QC")
    declaration = _object(evidence.get("declaration"), "QC declaration")
    scope = set(_primary_answers(export))
    if (
        declaration.get("candidate_sha256") != export.sha256
        or set(_list(declaration.get("scope"), "declared scope")) != scope
        or declaration.get("rule_id") != export.rule_id
        or declaration.get("qc") != dict(queue.qc)
    ):
        raise _refuse("new QC declaration must freeze candidate, entire scope, rule and support policy")
    _text(declaration.get("run_id"), "QC run_id")
    _text(declaration.get("disagreement_rule"), "QC disagreement_rule")
    author = _text(declaration.get("qc_author"), "independent QC author")
    evaluator = _text(declaration.get("evaluator"), "QC evaluator")
    kind = declaration.get("validation_kind", "fresh_qc")
    if kind not in {"fresh_qc", "qualified_sme"} or (kind == "fresh_qc" and evaluator != export.annotator_id):
        raise _refuse("fresh QC cannot delete/replace a worker; an expert needs qualified SME resolution")
    if (
        author in {export.annotator_id, evaluator}
        or declaration.get("declared_before_answers") is not True
        or declaration.get("independently_blinded") is not True
        or declaration.get("prior_answers_disclosed") is not False
        or declaration.get("repair_examples_used_as_gold") is not False
    ):
        raise _refuse("new QC must be declared, independently authored and blinded to prior answers/outcomes")
    vq_path = _linked_file(evidence.get("validation_queue"), path.parent)
    vg_path = _linked_file(evidence.get("validation_gold"), path.parent)
    ve_path = _linked_file(evidence.get("validation_export"), path.parent)
    vq = load_queue(vq_path, vg_path)
    ve = load_label_export(ve_path)
    _validate_binding(ve, vq)
    if synthetic:
        _require_generated(vq)
    else:
        _require_real_origin(vq)
    if (
        ve.annotator_id != evaluator
        or ve.rule_id != export.rule_id
        or ve.annotation_tier != export.annotation_tier
        or vq.qc != queue.qc
        or declaration.get("validation_queue_sha256") != vq.sha256
        or declaration.get("assignment") != ve.presented
        or vq.sha256 == queue.sha256
        or vq.queue_id == queue.queue_id
        or set(ve.presented) & set(prior.presented)
    ):
        raise _refuse("fresh QC assignment, policy, worker or run binding is invalid/recycled")
    original_gold = {g.item.sha256 for g in queue.gold} | {i.image_sha256 for i in queue.items}
    original_ids = {g.gold_id for g in queue.gold}
    original_media = {g.item.media_id for g in queue.gold}
    if any(
        g.item.sha256 in original_gold
        or g.gold_id in original_ids
        or g.item.media_id in original_media
        or g.item.authored_by != author
        for g in vq.gold
    ):
        raise _refuse("fresh independent gold cannot recycle old gold, disclosed answers or repair examples")
    candidate_answers, validation_answers = _primary_answers(export), _primary_answers(ve)
    candidate_items = {i.item_id: i for i in queue.items}
    validation_items = {i.item_id: i for i in vq.items}
    if set(validation_answers) != scope or any(
        not _same_answer(a, validation_answers[item_id])
        or candidate_items[item_id].image_sha256 != validation_items[item_id].image_sha256
        for item_id, a in candidate_answers.items()
    ):
        raise _refuse("fresh QC must evaluate this corrected candidate, with its complete item scope")
    report = qc_report(ve, vq)
    resolved = _sme_fields(evidence, export, ve, vq, report, scope)
    report = _require_qc(ve, vq, resolved_fields=resolved)
    if kind == "qualified_sme":
        required = {name for name, value in prior_report["fields"].items() if value["status"] != "passed"}
        for item_id, answer in candidate_answers.items():
            original = _primary_answers(prior)[item_id]
            required.update(
                name
                for name in _field_names(export.mode)
                if _field_value(answer, name, export.mode) != _field_value(original, name, export.mode)
            )
        if not required or not required <= resolved:
            raise _refuse("qualified SME recovery requires a supported disposition for every disputed/corrected field")
    return {
        "candidate_sha256": export.sha256,
        "prior_export_sha256": prior.sha256,
        "original_qc": prior_report,
        "accepted_qc": report,
        "evidence_sha256": evidence_sha,
        "validation_export_sha256": ve.sha256,
        "validation_queue_sha256": vq.sha256,
        "run_id": declaration["run_id"],
        "disagreement_rule": declaration["disagreement_rule"],
        "sme_resolutions": copy.deepcopy(evidence.get("sme_resolutions", [])),
    }, prior


def _require_observation(export: LabelExport, queue: Queue, run_id: str) -> dict[str, Any] | None:
    """Resolve bounded contextual inspection and explicit reuse applicability [MEAS-29].

    This validates an external record's structure/bindings. It cannot prove the
    truth of human attestations. No supplied string, matching version or fixture
    assertion alone is accepted as observation evidence.
    """
    if export.annotation_tier != "a":
        return None
    if not export.observation_ref:
        raise _refuse("real tier-a import requires available genuine observation evidence")
    try:
        record, digest = _read_document(queue.root / export.observation_ref)
        if (
            record.get("schema") != "fir-occ-observation/v1"
            or record.get("record_kind") != "bounded_human_observation"
            or record.get("data_origin") in {"generated_fixture", "synthetic", "test"}
        ):
            raise _refuse("observation must be a genuine bounded contextual human inspection record")
        for key in ("observer_id", "observed_at", "scope", "method", "operator_accounts", "limits"):
            _text(record.get(key), f"observation.{key}")
        _list(record.get("exceptions"), "observation.exceptions")
        applicable = _object(record.get("applicability"), "observation applicability")
        _require_applicability(
            _object(record.get("context"), "observed context"),
            _object(queue.metadata.get("measurement_context"), "current measurement context"),
            applicable,
            export,
            queue,
            run_id,
        )
        return {"sha256": digest, "reference": export.observation_ref, "applicability": copy.deepcopy(applicable)}
    except FrameContractError as exc:
        raise _refuse(f"observation evidence refused: {exc}") from exc


def _require_applicability(
    context: Mapping[str, Any],
    current: Mapping[str, Any],
    applicable: Mapping[str, Any],
    export: LabelExport,
    queue: Queue,
    run_id: str,
) -> None:
    """Validate a contextual comparison only; this is not evidence of an observation."""
    keys = frozenset(
        {"rule", "instructions", "operators", "collection_workflow", "adjudication_workflow", "tool_behavior"}
    )
    for ctx in (context, current):
        _keys(ctx, keys, "measurement context")
        for key in keys - {"operators"}:
            _text(ctx[key], f"context.{key}")
        operators = _list(ctx["operators"], "context.operators")
        if not operators or any(not isinstance(v, str) or not v.strip() for v in operators):
            raise _refuse("observation context requires operators")
    if current["rule"] != export.rule_id or export.annotator_id not in current["operators"]:
        raise _refuse("observation current rule/operators do not cover export")
    if (
        applicable.get("candidate_sha256") != export.sha256
        or applicable.get("queue_sha256") != queue.sha256
        or applicable.get("run_id") != run_id
        or applicable.get("applicable") is not True
        or applicable.get("beyond_scope") is not False
        or applicable.get("uncertain") is not False
    ):
        raise _refuse("observation applicability is unresolved, uncertain or outside its bounded scope")
    _text(applicable.get("limits"), "observation applicability limits")
    assessment = _object(applicable.get("context_assessment"), "observation context assessment")
    _keys(assessment, keys, "observation context assessment")
    for key in keys:
        item = _object(assessment[key], f"applicability.{key}")
        if (
            item.get("observed") != context[key]
            or item.get("current") != current[key]
            or item.get("covered") is not True
        ):
            raise _refuse(f"observation does not cover current {key}")
        _text(item.get("rationale"), f"observation {key} coverage rationale")
        if context[key] != current[key]:
            _text(item.get("changes"), f"observation {key} changes")


# --- constrained numpy fixtures: no external image loaders ------------------------------


def _generated_image_sha(recipe: object) -> str:
    """Regenerate fixed 8x8 RGB uint8 pixels and canonical PNG bytes, never read pixels."""
    import numpy as np

    r = _object(recipe, "fixture_recipe")
    _keys(r, frozenset({"generator_id", "seed"}), "fixture_recipe")
    if r["generator_id"] != "numpy-rgb8/v1" or type(r["seed"]) is not int or not 0 <= r["seed"] < 2**32:
        raise _refuse("fixture requires allowlisted numpy generator and fixed uint32 seed")
    pixels = np.random.default_rng(r["seed"]).integers(0, 255, size=(8, 8, 3), dtype=np.uint8)
    raw = b"".join(b"\x00" + row.tobytes() for row in pixels)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return hashlib.sha256(data).hexdigest()


def _require_generated(queue: Queue) -> None:
    allowed_root = {"schema", "queue_id", "mode", "annotation_tier", "items", "qc", "data_origin", "acceptance_path"}
    if (
        set(queue.metadata) - allowed_root
        or queue.metadata.get("data_origin") != "generated_fixture"
        or set(queue.gold_metadata) - {"schema", "data_origin", "items"}
        or queue.gold_metadata.get("data_origin") != "generated_fixture"
    ):
        raise _refuse("synthetic helper requires generated_fixture origin without real source references/loaders")
    allowed_item = {
        "item_id",
        "image",
        "image_id",
        "image_sha256",
        "duplicate_group",
        "show_confirmed_boxes",
        "confirmed_boxes",
        "sampling_arm",
        "inclusion_probability",
        "source_bucket",
        "caption",
        "detector_boxes",
        "data_origin",
        "fixture_recipe",
        "sources",
        "box",
        "matched_gt",
    }
    for raw, allowed in [(i.provenance, allowed_item) for i in queue.items] + [
        (g.provenance, set(_GOLD_KEYS) | {"faces", "decision", "data_origin", "fixture_recipe"}) for g in queue.gold
    ]:
        if set(raw) - allowed or raw.get("data_origin") != "generated_fixture":
            raise _refuse("synthetic helper rejects real/mixed/unknown origins and real source references")
        if raw.get("image_sha256") != _generated_image_sha(raw.get("fixture_recipe")):
            raise _refuse("synthetic generated-image hash differs from regenerated numpy fixture")
        image = _text(raw.get("image"), "generated image name")
        if Path(image).name != image or ":" in image or "\\" in image:
            raise _refuse("synthetic fixture may not carry real source paths/URLs")


def _import_rows(
    export: LabelExport,
    queue: Queue,
    acceptance: Mapping[str, Any],
    prior: LabelExport,
    *,
    synthetic: bool,
    observation: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    rows = copy.deepcopy(_face_rows(export, queue))
    originals = _primary_answers(prior)
    for row in rows:
        original = originals.get(row["duplicate_of"] or row["item_id"])
        row["pre_adjudication"] = asdict(original) if original else None
        row["acceptance"] = copy.deepcopy(dict(acceptance))
        row["observation_evidence"] = copy.deepcopy(observation)
        if synthetic:
            row.update(synthetic=True, analysis_eligible=False, data_origin="generated_fixture")
            # Also travels through consumers that forward only the annotation.
            row["annotation"].update(synthetic=True, analysis_eligible=False)
    return rows


def _require_real_origin(queue: Queue) -> None:
    origins = (
        [queue.metadata, queue.gold_metadata] + [i.provenance for i in queue.items] + [g.provenance for g in queue.gold]
    )
    if any(r.get("data_origin") not in {None, "real"} or r.get("fixture_recipe") is not None for r in origins):
        raise _refuse("synthetic/mixed/unknown origins cannot qualify production real analysis")


def to_face_instances(export: LabelExport, queue: Queue) -> tuple[dict[str, Any], ...]:
    """Production import: qualified QC plus available, applicable real observation.

    There is deliberately no override argument. Generated rows are never real
    evidence. Tier-a never becomes exhaustive. Prior answers/QC stay inspectable.
    """
    if export.mode != "face":
        raise FrameContractError("to_face_instances takes a face-mode export")
    acceptance, prior = _acceptance(export, queue, synthetic=False)
    observation = _require_observation(export, queue, acceptance["run_id"])
    _require_real_origin(queue)
    return _import_rows(export, queue, acceptance, prior, synthetic=False, observation=observation)


def to_synthetic_face_instances(export: LabelExport, queue: Queue) -> tuple[dict[str, Any], ...]:
    """Controlled regenerated numpy fixtures only; never confers analysis eligibility."""
    if export.mode != "face":
        raise FrameContractError("to_synthetic_face_instances takes a face-mode export")
    _require_generated(queue)
    acceptance, prior = _acceptance(export, queue, synthetic=True)
    return _import_rows(export, queue, acceptance, prior, synthetic=True)


def require_real_analysis_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    """Consumer boundary: reject persisted fixture rows, including annotation-only copies."""
    for row in rows:
        annotation = _object(row.get("annotation", {}), "row.annotation")
        if (
            row.get("synthetic") is True
            or row.get("analysis_eligible") is False
            or row.get("data_origin") == "generated_fixture"
            or annotation.get("synthetic") is True
            or annotation.get("analysis_eligible") is False
        ):
            raise _refuse("synthetic rows are ineligible for real analysis")
        if row.get("annotation_tier", annotation.get("annotation_tier")) == "a" and not row.get("observation_evidence"):
            raise _refuse("real analysis requires resolved observation evidence")
