"""FIR-11 Slice 2 R1 — in-tree roster_only detection refusal (S2-01 / S2-02).

The live flatten path used to drop annotation_mode, so score_run_record's
default scored roster_only detection as if it were exhaustive. These tests
drive the real flatteners (fusion_runner, CLI score) and go red if the
refusal is removed or made opt-in again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydantic import ValidationError

from scripts.eval_harness.face_metrics import (
    DETECTION_EMPTY_OBSERVATIONS_INVARIANT,
    IDENTIFICATION_EMPTY_OBSERVATIONS_INVARIANT,
)
from scripts.eval_harness.fusion_runner import manifest_entries_as_dicts
from scripts.eval_harness.manifest import (
    AnnotationMode,
    GoldenEntry,
    ManifestError,
    REFUSAL_EXPLANATIONS,
    ScoreInvariant,
    load_manifest,
    refusal_explanation,
)
from scripts.eval_harness.report import (
    ReportError,
    _MODE_RESTRICTIVENESS,
    _annotation_mode_of,
    _entries_as_dicts,
    _invariant_is,
    _mode_restrictiveness,
    _resolve_score_annotation_mode,
    build_reports,
    score_face_run_record,
    score_run_record,
)

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

# Overshoot: 3 predicted vs 1 labeled. Scored → precision=0.333 fp=2.
# Refused → precision is None, refused=True.
_OVERSHOOT_RECORD = {
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
            "media_id": 1,
            "path": "mock_images/alice.jpg",
            "describe": {
                "alt_text_draft": "Alice Example by the pool.",
                "visual_facts": {"objects": []},
            },
            # Dict identity row (greenfield rejects bare strings — VLM6-PANEL6L-SR-01);
            # shape mirrors fusion_runner.py::_identity_rows.
            "identities": [
                {
                    "name": "Alice Example",
                    "bbox": {"x": 0.5, "y": 0.4, "width": 0.2, "height": 0.3},
                    "unpositioned": False,
                }
            ],
            "face_count": 3,
            "error": None,
        }
    ],
}


def _overshoot_record_for(manifest_path: Path) -> dict:
    """Deep-copy _OVERSHOOT_RECORD stamped with the real score-time manifest sha.

    The CLI ``score`` path folds fetch/score manifest drift into the verdict
    (VLM6-F-03 / EVAL-13) and hard-fails on both a mismatched and a missing
    fetch-time ``manifest_sha256``. A fixed placeholder can never match a
    tmp_path-scoped manifest, so compute the real sha the same way cli.py does.
    """
    import copy

    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest as _load_manifest

    record = copy.deepcopy(_OVERSHOOT_RECORD)
    manifest = _load_manifest(str(manifest_path), skip_hash_verification=True)
    record["provenance"]["manifest_sha256"] = _manifest_sha(manifest)
    return record


EXHAUSTIVE_DETECTION = {"tp": 1, "fp": 2, "fn": 0, "precision": 1 / 3, "recall": 1.0}


def _manifest_doc(mode: str) -> dict:
    return {
        "manifest_version": 3,
        "annotation_mode": mode,
        # VLM6-DELTA-17: 2 roster members so easy_wrong can name a real
        # (non-must_right) roster identity — an empty easy_wrong trips the
        # CLI's branch-only empty-rubric gate (SCORE_GATE_PREFIX_EMPTY_RUBRIC,
        # cli.py) ahead of the refusal-consent exit these tests target. Mirrors
        # the pattern in test_r6d4_cli_score_omits_annotation_mode.py.
        "roster": ["Alice Example", "Bob Distractor"],
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
                "easy_wrong": ["Bob Distractor"],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [
                    {
                        "x": 0.5,
                        "y": 0.4,
                        "w": 0.2,
                        "h": 0.3,
                        "name": "Alice Example",
                        "source": "operator",
                        "lineage": _LINEAGE,
                    }
                ],
            }
        ],
    }


def _write_manifest(tmp_path: Path, mode: str) -> Path:
    path = tmp_path / f"{mode}.json"
    path.write_text(json.dumps(_manifest_doc(mode)), encoding="utf-8")
    return path


def _write_unboxed_manifest(tmp_path: Path, mode: str) -> Path:
    """Same fixture minus face_boxes — identification must also refuse.

    VLM6-DELTA-17: with identification also refused, the CLI's category-vacuity
    gate (cli.py ~1916: fires only when ``not ident_block.get("refused")``) does
    not intercept ahead of the exit-3 refusal-consent path these CLI tests
    target. Mirrors the unboxed-manifest category-vacuity-bypass pattern in
    test_regen_eval_report_gate.py (VLM6-DELTA-15) and
    test_identification_boxed_gt.py (VLM6-DELTA-16).
    """
    doc = _manifest_doc(mode)
    doc["entries"][0]["face_boxes"] = []
    path = tmp_path / f"{mode}-unboxed.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_fusion_flatten_stamps_annotation_mode(tmp_path: Path) -> None:
    manifest = load_manifest(str(_write_manifest(tmp_path, "roster_only")), skip_hash_verification=True)
    entries = manifest_entries_as_dicts(manifest)
    assert entries[0]["annotation_mode"] == "roster_only"


class _DumpEntry:
    """Stand-in whose model_dump can carry annotation_mode (GoldenEntry cannot)."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return dict(self._payload)


class _FusionManifest:
    def __init__(self, mode: str, entries: list) -> None:
        self.annotation_mode = mode
        self.entries = entries


def test_fusion_flatten_fill_only_preserves_per_entry_stamp() -> None:
    """S2R6E-04 sibling: fusion flatten fills missing stamps and never overwrites.

    GoldenEntry has no annotation_mode field, so the collision uses a
    stand-in dump. Both halves are required: overwrite-all stays green
    on fill-only, and a no-op door stays green on preserve-only.
    """
    stamped = {
        "path": "mock_images/stamped.jpg",
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "context_pack": {},
        "provenance": None,
        "annotation_mode": "roster_only",
    }
    unstamped = {
        "path": "mock_images/unstamped.jpg",
        "media_id": 2,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [],
        "context_pack": {},
        "provenance": None,
    }
    rows = manifest_entries_as_dicts(
        _FusionManifest(
            "exhaustive",
            [_DumpEntry(stamped), _DumpEntry(unstamped)],
        )
    )
    assert rows[0]["annotation_mode"] == "roster_only"
    assert rows[1]["annotation_mode"] == "exhaustive"


def test_fusion_flatten_projects_scorer_contract_keys_only(tmp_path: Path) -> None:
    """S2R5-10: flatten is an explicit projection, not a silent model_dump widen.

    S2R4-05 restored face_boxes by spreading every model field. Extra keys
    (sha256, expected_attachments, difficulty, …) are not the scorer
    contract. A ``{**e.model_dump(), ...}`` revert dies here.
    """
    from scripts.eval_harness.fusion_runner import SCORER_ENTRY_KEYS

    manifest = load_manifest(str(_write_manifest(tmp_path, "roster_only")), skip_hash_verification=True)
    entries = manifest_entries_as_dicts(manifest)
    leaked = {"sha256", "expected_attachments", "difficulty", "reference_facts", "base_caption"}
    assert leaked.isdisjoint(entries[0])
    assert "face_boxes" in entries[0]
    assert set(entries[0]) == set(SCORER_ENTRY_KEYS) | {"annotation_mode"}


def test_fusion_flatten_preserves_face_boxes(tmp_path: Path) -> None:
    """S2R4-05: flatten must keep box lineage so boxed GT still scores ID.

    Dropping face_boxes made require_boxed_identification_gt refuse honest,
    fully-boxed ground truth. The CLI flatten keeps boxes via model_dump.
    """
    manifest = load_manifest(str(_write_manifest(tmp_path, "roster_only")), skip_hash_verification=True)
    entries = manifest_entries_as_dicts(manifest)
    assert "face_boxes" in entries[0]
    dumped = manifest.entries[0].model_dump()["face_boxes"]
    assert entries[0]["face_boxes"] == dumped
    assert dumped, "fixture must carry a named box"
    assert any(box.get("name") == "Alice Example" for box in entries[0]["face_boxes"])
    json_doc, _md = build_reports(_OVERSHOOT_RECORD, entries)
    ident = json.loads(json_doc)["faces"]["identification"]
    assert ident.get("refused") is not True
    assert ident["precision"] == 1.0
    assert ident["recall"] == 1.0


def test_fusion_runner_build_reports_refuses_roster_only_detection(tmp_path: Path) -> None:
    """Real in-tree entry: disk roster_only → flatten → build_reports (no kwarg).

    Goes red if the refusal is removed or if flatten drops annotation_mode.
    """
    manifest = load_manifest(str(_write_manifest(tmp_path, "roster_only")), skip_hash_verification=True)
    entries = manifest_entries_as_dicts(manifest)
    json_doc, _md = build_reports(_OVERSHOOT_RECORD, entries)
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert det["precision"] is None
    assert det["fp"] is None


def test_score_run_record_without_mode_or_stamp_refuses() -> None:
    """A caller that forgets the mode must refuse, never score."""
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        }
    ]
    scored = score_run_record(_OVERSHOOT_RECORD, entries)
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE
    assert det["precision"] is None
    assert det["fp"] is None


def test_exhaustive_fusion_flatten_detection_unchanged(tmp_path: Path) -> None:
    """Exhaustive P/R through the same flatten path matches the pre-fix pin."""
    manifest = load_manifest(str(_write_manifest(tmp_path, "exhaustive")), skip_hash_verification=True)
    entries = manifest_entries_as_dicts(manifest)
    json_doc, _md = build_reports(_OVERSHOOT_RECORD, entries)
    det = json.loads(json_doc)["faces"]["detection"]
    assert det.get("refused") is not True
    assert det["tp"] == EXHAUSTIVE_DETECTION["tp"]
    assert det["fp"] == EXHAUSTIVE_DETECTION["fp"]
    assert det["fn"] == EXHAUSTIVE_DETECTION["fn"]
    assert det["precision"] == pytest.approx(EXHAUSTIVE_DETECTION["precision"])
    assert det["recall"] == pytest.approx(EXHAUSTIVE_DETECTION["recall"])


def test_cli_score_refuses_roster_only_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI score stamps entries and omits the kwarg (S2R2-10 omission branch).

    S2R3-16: refused detection is exit 3 by default. A CI job that checks
    only process status must not treat a missing detection score as clean.

    VLM6-DELTA-17: this branch's category-vacuity gate (cli.py ~1916) fires
    ahead of the int-3 refusal-consent exit whenever identification is scored
    (not refused) on an undersized single-image corpus. Use an unboxed
    manifest so identification also refuses and the gate's
    ``not ident_block.get("refused")`` guard stays false — same bypass
    mechanism as VLM6-DELTA-15/16.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path = _write_unboxed_manifest(tmp_path, "roster_only")
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps(_overshoot_record_for(man_path)), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    assert exc.value.code == 3
    report = json.loads(record_path.with_name("run-report.json").read_text(encoding="utf-8"))
    det = report["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert det["precision"] is None
    md = record_path.with_name("run-report.md").read_text(encoding="utf-8")
    det_section = md.split("## Face detection")[1].split("## Face identification")[0]
    assert f"- REFUSED ({ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY}):" in det_section
    assert (
        "detection P/R is not computed unless annotation_mode is exhaustive"
        in det_section
    )
    captured = capsys.readouterr()
    assert f"detection=REFUSED({ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY})" in captured.out
    assert "--allow-refused" in captured.err


def test_cli_score_allow_refused_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S2R3-16: --allow-refused is the explicit opt-in for a refused score.

    VLM6-DELTA-17: unboxed manifest for the same category-vacuity-bypass
    reason as test_cli_score_refuses_roster_only_detection above.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path = _write_unboxed_manifest(tmp_path, "roster_only")
    record_path = tmp_path / "run.json"
    record_path.write_text(json.dumps(_overshoot_record_for(man_path)), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(
        [
            "score",
            "--manifest",
            str(man_path),
            "--run-record",
            str(record_path),
            "--allow-refused",
        ]
    )
    captured = capsys.readouterr()
    assert f"detection=REFUSED({ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY})" in captured.out
    assert captured.err == ""


def test_cli_score_help_documents_allow_refused_exit_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.eval_harness.cli as cli_mod

    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--allow-refused" in help_text
    assert "exit 3" in help_text


def _stamped(mode: str) -> list[dict]:
    return [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": mode,
        }
    ]


def test_explicit_exhaustive_cannot_widen_roster_only_stamp() -> None:
    """S2R2-01: explicit exhaustive + roster_only stamp refuses (data wins)."""
    scored = score_run_record(
        _OVERSHOOT_RECORD,
        _stamped("roster_only"),
        annotation_mode=AnnotationMode.EXHAUSTIVE,
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert det["precision"] is None
    assert det["fp"] is None


def test_stamped_roster_only_without_kwarg_refuses() -> None:
    """S2R2-10: stamp is load-bearing when the explicit kwarg is omitted."""
    scored = score_run_record(_OVERSHOOT_RECORD, _stamped("roster_only"))
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert det["precision"] is None


def test_partial_stamp_does_not_promote_to_unstamped_siblings() -> None:
    """S2R2-03: one exhaustive stamp must not cover an unstamped overshoot."""
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": "exhaustive",
        },
        {
            "path": "mock_images/other.jpg",
            "media_id": 99,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        },
    ]
    scored = score_run_record(_OVERSHOOT_RECORD, entries)
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE
    assert det["precision"] is None


def test_unrecognised_mode_has_own_invariant() -> None:
    """S2R2-12: a typo is not reported as an omitted mode."""
    scored = score_run_record(
        _OVERSHOOT_RECORD,
        _stamped("exhaustive"),
        annotation_mode="exhaustve",
    )
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE
    assert det["precision"] is None


def test_mixed_stamps_still_fail_loud_with_explicit_exhaustive() -> None:
    """S2R2-01: explicit must not suppress the mixed-stamp guard."""
    entries = [
        {**_stamped("exhaustive")[0], "media_id": 1},
        {
            "path": "mock_images/other.jpg",
            "media_id": 99,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": "roster_only",
        },
    ]
    with pytest.raises(ReportError, match="mixed annotation_mode"):
        score_run_record(_OVERSHOOT_RECORD, entries, annotation_mode="exhaustive")


def test_markdown_names_refused_detection() -> None:
    """S2R4-11: pin the published roster_only sentence as a literal.

    The invariant name comes from ScoreInvariant; the explanation is spelled
    out. Importing REFUSAL_EXPLANATIONS stays green under a lying table.
    A mutated roster_only sentence, or a swap with the empty-observations
    sentence, dies here.
    """
    manifest_entries = _stamped("roster_only")
    _json_doc, md = build_reports(_OVERSHOOT_RECORD, manifest_entries)
    det_section = md.split("## Face detection")[1].split("## Face identification")[0]
    assert f"- REFUSED ({ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY}):" in det_section
    assert (
        "detection P/R is not computed unless annotation_mode is exhaustive"
        in det_section
    )
    assert (
        "detection P/R is not computed from zero scored observations"
        not in det_section
    )
    assert "used anyway" not in det_section
    assert "precision: null" not in det_section


def test_refusal_explanation_maps_every_invariant() -> None:
    """S2R4-11 / S2R5-04: pin invariant → explanation, not a prose fragment."""
    assert set(REFUSAL_EXPLANATIONS) == set(ScoreInvariant)
    texts = list(REFUSAL_EXPLANATIONS.values())
    assert len(texts) == len(set(texts))
    for member in ScoreInvariant:
        assert refusal_explanation(member) == REFUSAL_EXPLANATIONS[member]
        assert refusal_explanation(member.value) == REFUSAL_EXPLANATIONS[member]
    assert (
        REFUSAL_EXPLANATIONS[ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY]
        == "detection P/R is not computed unless annotation_mode is exhaustive"
    )
    assert (
        REFUSAL_EXPLANATIONS[ScoreInvariant.DETECTION_REFUSES_EMPTY_OBSERVATIONS]
        == "detection P/R is not computed from zero scored observations"
    )
    assert (
        REFUSAL_EXPLANATIONS[ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS]
        == (
            "identification P/R is not computed from identity claims that carry no "
            "per-face box lineage"
        )
    )
    assert (
        REFUSAL_EXPLANATIONS[ScoreInvariant.IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS]
        == "identification P/R is not computed from zero scored observations"
    )


def test_markdown_refusal_matches_fired_invariant_not_stock_sentences() -> None:
    """S2R5-04: exhaustive + full lineage + zero items must not print stock lies.

    The two historical sentences name missing exhaustive mode and missing
    box lineage. This fixture has both. The fired invariants are the empty-
    observation pair; those published sentences are spelled out as literals.
    A swap of the roster_only and empty-observations sentences dies here.
    """
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": "exhaustive",
            "face_boxes": [
                {
                    "x": 0.5,
                    "y": 0.4,
                    "w": 0.2,
                    "h": 0.3,
                    "name": "Alice Example",
                    "source": "iptc",
                    "lineage": _LINEAGE,
                }
            ],
        }
    ]
    _json_doc, md = build_reports(_zero_observation_record(), entries)
    det_section = md.split("## Face detection")[1].split("## Face identification")[0]
    ident_section = md.split("## Face identification")[1].split("## Per-item failures")[0]
    assert f"- REFUSED ({ScoreInvariant.DETECTION_REFUSES_EMPTY_OBSERVATIONS}):" in det_section
    assert (
        "detection P/R is not computed from zero scored observations"
        in det_section
    )
    assert (
        "detection P/R is not computed unless annotation_mode is exhaustive"
        not in det_section
    )
    assert (
        f"- REFUSED ({ScoreInvariant.IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS}):"
        in ident_section
    )
    assert (
        "identification P/R is not computed from zero scored observations"
        in ident_section
    )
    assert (
        "identification P/R is not computed from identity claims that carry no "
        "per-face box lineage"
        not in ident_section
    )


def _face_run_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "t",
            "leg": "candidate",
        },
        "items": [],
    }


def test_empty_entries_refuse_explicit_exhaustive() -> None:
    """S2R3-01: empty list + explicit exhaustive refuses, never scores.

    `missing` is only assigned inside the per-entry loop. An empty list
    never enters that loop, so the resolver used to return the explicit
    mode and fail-open exhaustive. Zero entries cannot witness a
    detection contract — refuse with a named invariant.
    """
    with pytest.raises(ManifestError) as exc_info:
        _resolve_score_annotation_mode("exhaustive", [])
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES


def test_empty_entries_score_run_record_refuses_explicit_exhaustive() -> None:
    """S2R3-01: caption path maps the empty-list invariant onto a refusal."""
    scored = score_run_record(_OVERSHOOT_RECORD, [], annotation_mode="exhaustive")
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES
    assert det["precision"] is None
    assert det["fp"] is None


def test_empty_entries_hard_error_through_score_face() -> None:
    """S2R3-01: the empty lattice cell is a named raise on the face path."""
    manifest = {"annotation_mode": "exhaustive", "roster": [], "entries": []}
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_face_run_record(), manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES


def _zero_observation_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [],
    }


def test_zero_observations_against_nonempty_exhaustive_refuses() -> None:
    """S2R4-08: empty items + nonempty exhaustive must not publish None/0.

    The empty-entries invariant checks the manifest, not observations.
    A run that scored nothing used to pass both the partial-corpus gate
    and the refused-metric gate.
    """
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                {
                    "x": 0.5,
                    "y": 0.4,
                    "w": 0.2,
                    "h": 0.3,
                    "name": "Alice Example",
                }
            ],
            "annotation_mode": "exhaustive",
        }
    ]
    scored = score_run_record(
        _zero_observation_record(), entries, annotation_mode="exhaustive"
    )
    assert scored["counts"] == {"total": 0, "scored": 0, "failed": 0}
    det = scored["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == DETECTION_EMPTY_OBSERVATIONS_INVARIANT
    assert det["precision"] is None
    assert det["recall"] is None
    assert det["tp"] is None
    assert det["fp"] is None
    assert det["fn"] is None
    ident = scored["faces"]["identification"]
    assert ident["refused"] is True
    assert ident["invariant"] == IDENTIFICATION_EMPTY_OBSERVATIONS_INVARIANT
    assert ident["precision"] is None
    assert ident["recall"] is None


def _mapping_entry(*, annotation_mode: object) -> dict:
    entry = {
        "path": "x.jpg",
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "name": "Alice Example"}],
    }
    if annotation_mode is not _OMIT:
        entry["annotation_mode"] = annotation_mode
    return entry


_OMIT = object()


def test_stamp_does_not_fill_blank_or_whitespace_entry_mode() -> None:
    """S2R3-02: a raw-mapping parent mode is not per-entry evidence.

    Previously None / omitted were filled to the parent (exhaustive),
    which is the same widening ``score_run_record(..., annotation_mode=
    'exhaustive')`` already refuses. Blank/whitespace stay explicit
    empty tokens. None / omitted stay absent — they are not inherited.
    """
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": [],
        "entries": [
            {"annotation_mode": ""},
            {"annotation_mode": "   "},
            {"annotation_mode": None},
            {},
        ],
    }
    entries, _, _ = _entries_as_dicts(manifest)
    assert entries[0]["annotation_mode"] == ""
    assert entries[1]["annotation_mode"] == "   "
    assert entries[2]["annotation_mode"] is None
    assert "annotation_mode" not in entries[3]


def test_blank_entry_stamp_is_not_inherited_from_exhaustive_parent() -> None:
    """S2R3-02: parent exhaustive must not mint exhaustive onto a blank stamp.

    The live hole: fill-blanks treated "" as omitted, stamped exhaustive,
    and score_face_run_record published the R2 overshoot numbers.
    """
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": [_mapping_entry(annotation_mode="")],
    }
    entries, _, _ = _entries_as_dicts(manifest)
    assert entries[0]["annotation_mode"] == ""
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_face_run_record(), manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE


def test_stamp_does_not_overwrite_roster_only_when_parent_is_exhaustive() -> None:
    """TEST-15 / S2R3-03: a raw-mapping flatten must not overwrite a real stamp.

    Stamping the parent exhaustive onto a roster_only entry would hide
    the conflict and let score_face_run_record publish zeros. This pin
    dies on that overwrite mutant.
    """
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": [_mapping_entry(annotation_mode="roster_only")],
    }
    entries, _, _ = _entries_as_dicts(manifest)
    assert entries[0]["annotation_mode"] == "roster_only"
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_face_run_record(), manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY


def test_resolver_omitted_explicit_uses_data_stamp() -> None:
    """S2R3-18: CLI omit-kwarg contract, pinned on the resolver.

    Lane C owns cli.py, so this pin is the resolver contract `_cmd_score`
    relies on: omitted explicit + stamp → data wins. Mutating the resolver
    to invent exhaustive on omission dies here. A `_cmd_score(...,
    annotation_mode="exhaustive")` revert cannot be red-proofed without
    editing cli.py.
    """
    assert (
        _resolve_score_annotation_mode(None, [{"annotation_mode": "roster_only"}])
        is AnnotationMode.ROSTER_ONLY
    )
    assert (
        _resolve_score_annotation_mode(None, [{"annotation_mode": "exhaustive"}])
        is AnnotationMode.EXHAUSTIVE
    )


def test_annotation_mode_of_mapping_key_beats_attribute() -> None:
    """S2R4-12: dict-subclass attribute must not outrank the mapping key.

    Most-restrictive-wins: roster_only in the mapping beats an exhaustive
    attribute. Attribute-first resolution used to invent exhaustive.
    """

    class SplitMode(dict):
        annotation_mode = AnnotationMode.EXHAUSTIVE

    payload = SplitMode(
        annotation_mode="roster_only",
        roster=["Alice Example"],
        entries=[_mapping_entry(annotation_mode="roster_only")],
    )
    assert _annotation_mode_of(payload) is AnnotationMode.ROSTER_ONLY
    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_face_run_record(), payload)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY


def test_score_invariants_are_imported_not_respelt() -> None:
    """S2R4-21 / S2R5-08: raise token and catch-set share ScoreInvariant members."""
    with pytest.raises(ManifestError) as exc_info:
        _resolve_score_annotation_mode("exhaustive", [])
    assert exc_info.value.invariant is ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES
    scored = score_run_record(_OVERSHOOT_RECORD, [], annotation_mode="exhaustive")
    assert (
        scored["faces"]["detection"]["invariant"]
        is ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES
    )
    assert _invariant_is(
        scored["faces"]["detection"]["invariant"],
        ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES,
    )
    assert not _invariant_is(
        "detection_refuses_empty_entries",
        ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES,
    )


def test_respelt_empty_entries_string_is_not_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S2R5-08: a re-spelt raise token must diverge from the catch set."""
    import scripts.eval_harness.report as report_mod

    def boom(*_args: object, **_kwargs: object) -> AnnotationMode:
        raise ManifestError("empty", invariant="detection_refuses_empty_entries")

    monkeypatch.setattr(report_mod, "_resolve_score_annotation_mode", boom)
    with pytest.raises(ManifestError) as exc_info:
        score_run_record(_OVERSHOOT_RECORD, [], annotation_mode="exhaustive")
    assert exc_info.value.invariant == "detection_refuses_empty_entries"
    assert exc_info.value.invariant is not ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES


def test_mode_restrictiveness_covers_every_annotation_mode() -> None:
    """S2R4-17: table must be the AnnotationMode key set.

    Import-time also raises RuntimeError on drift. The test names the
    equality so a lying extra/missing key cannot hide behind a score-time
    KeyError that both suites never hit.
    """
    assert set(_MODE_RESTRICTIVENESS) == set(AnnotationMode)
    assert (
        _MODE_RESTRICTIVENESS[AnnotationMode.ROSTER_ONLY]
        > _MODE_RESTRICTIVENESS[AnnotationMode.EXHAUSTIVE]
    )


def test_restrictiveness_unknown_mode_is_typed_refusal() -> None:
    """S2R3-13: unknown mode is a named ManifestError, not a bare KeyError."""
    with pytest.raises(ManifestError) as exc_info:
        _mode_restrictiveness("not-a-mode")  # type: ignore[arg-type]
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE


def test_mixed_and_missing_reports_mixed() -> None:
    """S2R3-09: mixed is more dangerous than missing; do not mask it.

    A document that is both missing a stamp on one entry and mixed
    across the others used to return the missing-stamp refusal only.
    Mixed must win, and the message must also name the missing stamps.
    """
    entries = [
        {**_stamped("exhaustive")[0], "media_id": 1},
        {
            "path": "mock_images/other.jpg",
            "media_id": 99,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "annotation_mode": "roster_only",
        },
        {
            "path": "mock_images/unstamped.jpg",
            "media_id": 100,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        },
    ]
    with pytest.raises(ReportError, match="mixed annotation_mode") as exc_info:
        score_run_record(_OVERSHOOT_RECORD, entries)
    assert "missing stamp" in str(exc_info.value)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_MIXED_ANNOTATION_MODE


def test_per_entry_lattice_is_raw_mapping_only() -> None:
    """S2R3-10: GoldenEntry cannot carry a per-entry stamp.

    The resolver lattice is reachable only via raw mappings. Adding
    `annotation_mode` to GoldenEntry would change that design and die here.
    """
    assert "annotation_mode" not in GoldenEntry.model_fields
    with pytest.raises(ValidationError):
        GoldenEntry(
            path="x.jpg",
            sha256="a" * 64,
            media_id=1,
            face_count=0,
            present_identities=[],
            must_right=[],
            easy_wrong=[],
            policy={"recognition_enabled": True},
            annotation_mode="roster_only",
        )
    typed = GoldenEntry(
        path="x.jpg",
        sha256="a" * 64,
        media_id=1,
        face_count=0,
        present_identities=[],
        must_right=[],
        easy_wrong=[],
        policy={"recognition_enabled": True},
    )
    assert "annotation_mode" not in typed.model_dump()
