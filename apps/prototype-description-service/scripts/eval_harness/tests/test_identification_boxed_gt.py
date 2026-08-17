"""S2R3-08 — identification P/R refuses unboxed identity claims.

An entry can load with present_identities and empty face_boxes (roster_only
allows that). Identification must not treat those names as labeled GT.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.face_metrics import require_boxed_identification_gt
from scripts.eval_harness.manifest import (
    AnnotationMode,
    ManifestError,
    ScoreInvariant,
    load_manifest,
)
from scripts.eval_harness.report import (
    Audience,
    build_reports,
    score_face_run_record,
    score_run_record,
)
from scripts.eval_harness.schema import DocKind

_LINEAGE = {
    "labeler_id": "test-labeler",
    "batch_id": "test-batch",
    "capture_session_id": "test-session",
    "pass_index": 0,
    "labeled_at": "2026-08-14T00:00:00Z",
    "tool_version": "test",
    "saw_machine_proposals": False,
    "label_source": "operator_blind",
    "decision": "named",
    "confidence": "high",
    "arbitration_of": None,
}


def _record(identities: list[str], *, face_count: int = 1, media_id: int = 1, path: str = "mock_images/alice.jpg") -> dict:
    # Dict identity rows (greenfield rejects bare strings — VLM6-PANEL6L-SR-01);
    # callers pass plain names, unpositioned=True since these claims carry no
    # predicted box geometry (this file exercises identification P/R, not
    # positional accuracy).
    identity_rows = [{"name": name, "unpositioned": True} for name in identities]
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": media_id,
                "path": path,
                "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
                "identities": identity_rows,
                "face_count": face_count,
                "error": None,
            }
        ],
    }


def _unboxed_alice() -> dict:
    return {
        "path": "mock_images/alice.jpg",
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": ["Alice Example"],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "annotation_mode": "roster_only",
    }


def _named_box(name: str) -> dict:
    return {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": _LINEAGE,
    }


def _boxed_alice() -> dict:
    entry = _unboxed_alice()
    entry["face_boxes"] = [_named_box("Alice Example")]
    return entry


def _assert_identification_refused(ident: dict) -> None:
    assert ident["refused"] is True
    assert ident["invariant"] == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
    assert ident["precision"] is None
    assert ident["recall"] is None
    assert ident["macro_precision"] is None
    assert ident["macro_recall"] is None
    assert ident["true_rejections"] is None
    assert ident["wrong_names"] is None


def test_unboxed_claim_loads_as_roster_only(tmp_path: Path) -> None:
    """Load stays legal — the defect is scoring, not the roster_only schema."""
    doc = {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        "roster": ["Alice Example"],
        "entries": [
            {
                "path": "mock_images/alice.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [],
            }
        ],
    }
    path = tmp_path / "unboxed.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    manifest = load_manifest(str(path), skip_hash_verification=True)
    assert manifest.annotation_mode is AnnotationMode.ROSTER_ONLY
    assert manifest.entries[0].present_identities == ["Alice Example"]
    assert manifest.entries[0].face_boxes == []


def test_unboxed_correct_name_refuses_identification() -> None:
    """Correct name on an unboxed claim must not yield p=1 r=1 tp=1."""
    scored = score_run_record(_record(["Alice Example"]), [_unboxed_alice()])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    assert ident.get("tp") not in (1,)


def test_unboxed_wrong_name_refuses_identification() -> None:
    """Wrong name on an unboxed claim must not emit a scored wrong_names row."""
    scored = score_run_record(_record(["Bob Example"]), [_unboxed_alice()])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    assert ident["wrong_names"] != [["mock_images/alice.jpg", "Bob Example"]]


def test_unboxed_miss_refuses_identification() -> None:
    """A miss on an unboxed claim must not yield recall=0 / fn=1."""
    scored = score_run_record(_record([]), [_unboxed_alice()])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    assert ident["recall"] is not False
    assert ident.get("fn") not in (1,)


def test_mixed_boxed_and_unboxed_refuses_whole_identification() -> None:
    """Must not drop the unboxed entry and score the boxed sibling as p=1 r=1."""
    boxed = _boxed_alice()
    unboxed = {
        "path": "mock_images/bob.jpg",
        "media_id": 2,
        "face_count": 1,
        "present_identities": ["Bob Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "annotation_mode": "roster_only",
    }
    record = _record(["Alice Example"])
    record["items"].append(
        {
            "media_id": 2,
            "path": "mock_images/bob.jpg",
            "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
            "identities": [],
            "face_count": 1,
            "error": None,
        }
    )
    scored = score_run_record(record, [boxed, unboxed])
    ident = scored["faces"]["identification"]
    _assert_identification_refused(ident)
    # Dropping Bob from the denominator would leave Alice as a perfect score.
    assert ident["precision"] != 1.0
    assert ident["recall"] != 1.0


def test_boxed_identity_still_scores_identification() -> None:
    """Positive pair: a named box is identification GT and P/R is computed."""
    scored = score_run_record(_record(["Alice Example"]), [_boxed_alice()])
    ident = scored["faces"]["identification"]
    assert ident.get("refused") is not True
    assert ident["precision"] == 1.0
    assert ident["recall"] == 1.0
    assert ident["wrong_names"] == []


def test_require_boxed_skips_policy_disabled_unboxed_claim() -> None:
    """S2R4-06: the helper must use identification_pr's population.

    A recognition_enabled=False unboxed row is not a live claim. The helper
    used to refuse the whole score when one such row sat next to an honest
    boxed sibling.
    """
    boxed = _boxed_alice()
    disabled = {
        "path": "mock_images/theo.jpg",
        "media_id": 2,
        "face_count": 1,
        "present_identities": ["Theo Example"],
        "policy": {"recognition_enabled": False},
        "face_boxes": [],
    }
    require_boxed_identification_gt([boxed, disabled])
    require_boxed_identification_gt([disabled])


def test_require_boxed_still_refuses_enabled_unboxed_sibling() -> None:
    """A live unboxed claim still refuses even when a disabled row is present."""
    boxed = _boxed_alice()
    disabled = {
        "path": "mock_images/theo.jpg",
        "media_id": 2,
        "present_identities": ["Theo Example"],
        "policy": {"recognition_enabled": False},
        "face_boxes": [],
    }
    live = {
        "path": "mock_images/bob.jpg",
        "media_id": 3,
        "present_identities": ["Bob Example"],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
    }
    with pytest.raises(ManifestError) as exc_info:
        require_boxed_identification_gt([boxed, disabled, live])
    assert exc_info.value.invariant == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
    assert "Bob Example" in str(exc_info.value)
    assert "Theo Example" not in str(exc_info.value)


def test_policy_disabled_unboxed_does_not_refuse_identification() -> None:
    """S2R4-06: a policy-disabled unboxed row is not a live identification claim."""
    boxed = _boxed_alice()
    disabled = {
        "path": "mock_images/bob.jpg",
        "media_id": 2,
        "face_count": 1,
        "present_identities": ["Bob Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": False},
        "face_boxes": [],
        "annotation_mode": "roster_only",
    }
    record = _record(["Alice Example"])
    record["items"].append(
        {
            "media_id": 2,
            "path": "mock_images/bob.jpg",
            "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
            "identities": [],
            "face_count": 1,
            "error": None,
        }
    )
    scored = score_run_record(record, [boxed, disabled])
    ident = scored["faces"]["identification"]
    assert ident.get("refused") is not True
    assert ident["precision"] == 1.0
    assert ident["recall"] == 1.0
    assert ident["precision"] is not None
    assert "mock_images/bob.jpg" in ident["excluded_images"]
    json_doc, _md = build_reports(record, [boxed, disabled])
    built = json.loads(json_doc)["faces"]["identification"]
    assert built.get("refused") is not True
    assert built["precision"] == 1.0


def test_markdown_names_refused_identification() -> None:
    """S2R4-19: pin the explanation substance, not the production constant.

    A lying sentence that keeps 'per-face box lineage' (e.g. 'identification
    P/R is computed even when claims carry no per-face box lineage') must
    fail this pin. Importing REFUSAL_EXPLANATIONS here would stay green.
    """
    _json_doc, md = build_reports(_record(["Alice Example"]), [_unboxed_alice()])
    face_id = md.split("## Face identification")[1]
    assert f"- REFUSED ({ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS}):" in md
    assert (
        "identification P/R is not computed from identity claims that carry no "
        "per-face box lineage"
    ) in face_id
    assert "identification P/R is not computed from zero scored observations" not in face_id
    assert "micro precision:" not in face_id
    assert "used anyway" not in face_id
    assert "is computed even when" not in face_id


def _unit(vec: list[float]) -> list[float]:
    import math

    n = math.sqrt(sum(v * v for v in vec))
    return [v / n for v in vec]


def _partially_boxed_group() -> tuple[dict, dict, dict]:
    """Exhaustive group: 3 claimed names, only the first box is named.

    The two unnamed boxes are detection-complete and identification-incomplete.
    """
    names = ["Alice Example", "Bob Builder", "Cara Cole"]
    dim = 8
    alice = _unit([1.0] + [0.0] * (dim - 1))
    bob = _unit([0.0, 1.0] + [0.0] * (dim - 2))
    cara = _unit([0.0, 0.0, 1.0] + [0.0] * (dim - 3))

    def _det(bbox: list[float], emb: list[float]) -> dict:
        return {
            "bbox_px": bbox,
            "landmarks_px": [[0.0, 0.0]] * 5,
            "embedding": emb,
            "det_score": 0.95,
        }

    def _box(cx: float, cy: float, w: float, h: float, name: str | None) -> dict:
        return {"x": cx, "y": cy, "w": w, "h": h, "name": name, "source": "iptc"}

    entry = {
        "path": "celebs01/group.jpg",
        "media_id": 1,
        "face_count": 3,
        "present_identities": names,
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [
            _box(50 / 300, 0.5, 80 / 300, 0.8, names[0]),
            _box(150 / 300, 0.5, 80 / 300, 0.8, None),
            _box(250 / 300, 0.5, 80 / 300, 0.8, None),
        ],
        "annotation_mode": "exhaustive",
        "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
    }
    face_run = {
        "schema": "acx-eval/v1",
        "kind": DocKind.FACE_RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "t",
            "leg": "candidate",
        },
        "items": [
            {
                "media_id": 1,
                "path": "celebs01/group.jpg",
                "model_id": "m",
                "embedding_dim": dim,
                "image_size": [300, 100],
                "faces": [
                    _det([10.0, 10.0, 80.0, 80.0], alice),
                    _det([110.0, 10.0, 80.0, 80.0], bob),
                    _det([210.0, 10.0, 80.0, 80.0], cara),
                ],
            }
        ],
    }
    manifest = {"annotation_mode": "exhaustive", "roster": names, "entries": [entry]}
    return face_run, manifest, entry


def test_partially_boxed_group_require_boxed_raises() -> None:
    """The helper already names the hole; the face scorer must not ignore it."""
    _face_run, _manifest, entry = _partially_boxed_group()
    with pytest.raises(ManifestError) as exc_info:
        require_boxed_identification_gt([entry])
    assert exc_info.value.invariant == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
    assert "Bob Builder" in str(exc_info.value)
    assert "Cara Cole" in str(exc_info.value)


def test_score_face_run_record_refuses_partially_boxed_group() -> None:
    """S2R4-01: face-bakeoff must not publish ID P/R or unknown-rejection credit.

    Two unboxed claims must not vanish from the identification denominator
    and reappear as stranger rejects. Detection (boxes cover face_count)
    stays computable.
    """
    face_run, manifest, _entry = _partially_boxed_group()
    scored = score_face_run_record(face_run, manifest)
    full = scored["slices"]["full_corpus_identification"]
    headline = scored["slices"]["headline_identification"]
    unknown = scored["slices"]["unknown_rejection"]
    for block in (full, headline):
        assert block["refused"] is True
        assert block["invariant"] == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
        assert block["precision"] is None
        assert block["recall"] is None
        assert block.get("n_named_probes") is None
    assert unknown["refused"] is True
    assert unknown["invariant"] == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
    assert unknown["rate"] is None
    assert unknown["n"] is None
    assert unknown.get("correct_rejects") is None
    # Detection remains a count of boxes, which this group does have.
    det = scored["detection"]
    assert det.get("refused") is not True
    assert det["tp"] == 3
    assert det["fp"] == 0
    assert det["fn"] == 0
    coupling = scored["gate_proposal"]["identification_detection_coupling"]
    assert coupling.get("refused") is True
    assert coupling.get("identification_recall") is None


def _audience_mixed_boxing() -> tuple[dict, list[dict]]:
    """Public boxed sibling + private UNBOXED sibling (S2R4-02)."""
    public = _boxed_alice()
    public["path"] = "celebs01/alice.jpg"
    public["provenance"] = {
        "source": "celeb",
        "license": "public_domain",
        "publishable": True,
    }
    private = {
        "path": "localwp/uploads/bob-birthday.jpg",
        "media_id": 2,
        "face_count": 1,
        "present_identities": ["Bob Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "annotation_mode": "roster_only",
        "provenance": {
            "source": "localwp",
            "license": "consented",
            "publishable": False,
        },
    }
    record = _record(["Alice Example"], path="celebs01/alice.jpg")
    record["items"].append(
        {
            "media_id": 2,
            "path": "localwp/uploads/bob-birthday.jpg",
            "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
            "identities": [],
            "face_count": 1,
            "error": None,
        }
    )
    return record, [public, private]


def test_public_filter_does_not_make_unboxed_sibling_computable() -> None:
    """S2R4-02 / S2R5-03: LOCAL refuses the unfiltered corpus.

    PUBLIC is a different estimand. The publishable boxed sibling is scored
    on that population, and the artifact declares it. S2R4-02's unfiltered
    overlay used to over-refuse a metric the public subset supports honestly.
    """
    record, entries = _audience_mixed_boxing()
    local_json, _local_md = build_reports(record, entries, audience=Audience.LOCAL)
    public_json, public_md = build_reports(record, entries, audience=Audience.PUBLIC)
    local_ident = json.loads(local_json)["faces"]["identification"]
    public_doc = json.loads(public_json)
    public_ident = public_doc["faces"]["identification"]
    assert local_ident["refused"] is True
    assert local_ident["invariant"] == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
    assert public_ident.get("refused") is not True
    assert public_ident["precision"] == 1.0
    assert public_ident["recall"] == 1.0
    redaction = public_doc["redaction"]
    assert redaction["audience"] == "public"
    assert redaction["total_items"] == 2
    assert redaction["withheld_items"] == 1
    estimand = public_doc["estimand"]
    assert estimand["population"] == "publishable_items"
    assert estimand["resolved_on"] == "publishable_items"
    assert estimand["n_items"] == 1
    assert estimand["n_entries"] == 1
    assert estimand["withheld_items"] == 1
    assert estimand["total_items"] == 2
    assert "estimand" in public_md
    assert "publishable_items" in public_md
    assert ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS not in public_md


def test_public_detection_resolves_coverage_on_publishable_population() -> None:
    """S2R5-03: private uncovered evidence must not silently change public detection.

    LOCAL refuses uncovered face_count. PUBLIC scores the covered publishable
    sibling and declares that the estimand is the publishable subset — the
    opposite of resolving coverage on a different population than the check.
    """
    public = _boxed_alice()
    public["path"] = "celebs01/alice.jpg"
    public["annotation_mode"] = "exhaustive"
    public["provenance"] = {
        "source": "celeb",
        "license": "public_domain",
        "publishable": True,
    }
    private = {
        "path": "localwp/uploads/group.jpg",
        "media_id": 2,
        "face_count": 2,
        "present_identities": [],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "annotation_mode": "exhaustive",
        "provenance": {
            "source": "localwp",
            "license": "consented",
            "publishable": False,
        },
    }
    record = _record(["Alice Example"], path="celebs01/alice.jpg")
    record["items"].append(
        {
            "media_id": 2,
            "path": "localwp/uploads/group.jpg",
            "describe": {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}},
            "identities": [],
            "face_count": 0,
            "error": None,
        }
    )
    local_json, _local_md = build_reports(record, [public, private], audience=Audience.LOCAL)
    public_json, public_md = build_reports(record, [public, private], audience=Audience.PUBLIC)
    local_det = json.loads(local_json)["faces"]["detection"]
    public_doc = json.loads(public_json)
    public_det = public_doc["faces"]["detection"]
    assert local_det["refused"] is True
    assert local_det["invariant"] == ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT
    assert public_det.get("refused") is not True
    assert public_det["precision"] == 1.0
    assert public_det["recall"] == 1.0
    assert public_doc["estimand"]["population"] == "publishable_items"
    assert public_doc["estimand"]["resolved_on"] == "publishable_items"
    assert "estimand" in public_md
    assert ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT not in public_md
