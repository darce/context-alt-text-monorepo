"""FIR-11 Slice 2 R6 — CLI exit-gate pins (S2R5-02 / 05 / 12 / 13).

These drive the shipped ``cli.main`` entry points. A gate that re-scores
instead of reading the published report, or that treats any consent as
every consent, must go red here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


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


def _named_box(name: str) -> dict[str, Any]:
    return {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": _LINEAGE,
    }


def _manifest_doc(*, mode: str, boxed: bool) -> dict[str, Any]:
    return {
        "manifest_version": 3,
        "annotation_mode": mode,
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
                "face_boxes": [_named_box("Alice Example")] if boxed else [],
            }
        ],
    }


def _run_record(*, face_count: int = 3) -> dict[str, Any]:
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
                "media_id": 1,
                "path": "mock_images/alice.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example by the pool.",
                    "visual_facts": {"objects": []},
                },
                "identities": ["Alice Example"],
                "face_count": face_count,
                "error": None,
            }
        ],
    }


def _write_score_inputs(
    tmp_path: Path, *, mode: str, boxed: bool, record: dict[str, Any] | None = None
) -> tuple[Path, Path]:
    man_path = tmp_path / f"{mode}.json"
    man_path.write_text(json.dumps(_manifest_doc(mode=mode, boxed=boxed)), encoding="utf-8")
    rec_path = tmp_path / "run.json"
    rec_path.write_text(json.dumps(record if record is not None else _run_record()), encoding="utf-8")
    return man_path, rec_path


# ---------------------------------------------------------------------------
# S2R5-13 — gate must read the published report, not a second score call
# ---------------------------------------------------------------------------


def _wrap_published_detection(
    build_reports, *, refused: bool, invariant: str = "published-only-refusal"
):
    """Rewrite only the published honesty field; a real rescore is untouched."""

    def _wrapped(*args: Any, **kwargs: Any) -> tuple[str, str]:
        json_doc, md_doc = build_reports(*args, **kwargs)
        parsed = json.loads(json_doc)
        if refused:
            parsed["faces"]["detection"] = {
                "refused": True,
                "invariant": invariant,
                "precision": None,
                "recall": None,
                "tp": None,
                "fp": None,
                "fn": None,
            }
        else:
            parsed["faces"]["detection"] = {
                "precision": 1.0,
                "recall": 1.0,
                "tp": 1,
                "fp": 0,
                "fn": 0,
            }
        return json.dumps(parsed, indent=2, sort_keys=True) + "\n", md_doc

    return _wrapped


def test_score_gate_exits_3_when_published_report_is_refused_even_if_rescore_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-13 case A: published refused + real rescore clean → exit 3.

    Exhaustive boxed GT makes ``score_run_record`` clean. The wrap stamps
    refusal only onto the published JSON. Gating a second score call
    (any name) exits 0 — the pre-fix hole.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _write_score_inputs(tmp_path, mode="exhaustive", boxed=True)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(
        cli_mod,
        "build_reports",
        _wrap_published_detection(cli_mod.build_reports, refused=True),
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert exc.value.code == 3
    published = json.loads(rec_path.with_name("run-report.json").read_text(encoding="utf-8"))
    assert published["faces"]["detection"]["refused"] is True
    assert published["faces"]["detection"]["invariant"] == "published-only-refusal"


def test_score_gate_exits_0_when_published_report_is_clean_even_if_rescore_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-13 case B: published clean + real rescore refused → exit 0.

    roster_only makes ``score_run_record`` refuse detection. The wrap
    stamps a clean detection only onto the published JSON. OR-ing the
    two objects, or gating the rescore, exits 3 and dies here.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=True)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(
        cli_mod,
        "build_reports",
        _wrap_published_detection(cli_mod.build_reports, refused=False),
    )
    cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    published = json.loads(rec_path.with_name("run-report.json").read_text(encoding="utf-8"))
    assert published["faces"]["detection"].get("refused") is not True


# ---------------------------------------------------------------------------
# S2R5-05 — consent is per-metric; one flag must not clear the other
# ---------------------------------------------------------------------------


def test_allow_refused_detection_does_not_consent_to_identification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Shipped roster-only + unboxed: both metrics refuse together.

    Consenting only to detection must still exit 3 on identification.
    A store_true / any-consent flag dies here.
    """
    import scripts.eval_harness.cli as cli_mod
    from scripts.eval_harness.manifest import ScoreInvariant

    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(
            [
                "score",
                "--manifest",
                str(man_path),
                "--run-record",
                str(rec_path),
                "--allow-refused=detection",
            ]
        )
    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "identification=" in err
    assert ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS in err
    assert "detection=" not in err.split("refused metric(s) (")[1].split(")")[0]


def test_allow_refused_identification_does_not_consent_to_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.eval_harness.cli as cli_mod
    from scripts.eval_harness.manifest import ScoreInvariant

    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(
            [
                "score",
                "--manifest",
                str(man_path),
                "--run-record",
                str(rec_path),
                "--allow-refused=identification",
            ]
        )
    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "detection=" in err
    assert ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY in err
    assert "identification=" not in err.split("refused metric(s) (")[1].split(")")[0]


def test_allow_refused_both_metrics_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(
        [
            "score",
            "--manifest",
            str(man_path),
            "--run-record",
            str(rec_path),
            "--allow-refused=detection",
            "--allow-refused=identification",
        ]
    )


def test_bare_allow_refused_is_equivalent_to_naming_every_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare --allow-refused must stay working and name every metric in help."""
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(
        [
            "score",
            "--manifest",
            str(man_path),
            "--run-record",
            str(rec_path),
            "--allow-refused",
        ]
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--allow-refused" in help_text
    assert "exit 3" in help_text
    assert "every metric" in help_text
    assert "detection" in help_text
    assert "identification" in help_text


def test_allow_refused_unknown_metric_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.eval_harness.cli as cli_mod

    with pytest.raises(SystemExit) as exc:
        cli_mod.main(
            [
                "score",
                "--manifest",
                str(tmp_path / "m.json"),
                "--run-record",
                str(tmp_path / "r.json"),
                "--allow-refused=caption",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "caption" in err
    assert "detection" in err


# ---------------------------------------------------------------------------
# S2R5-02 — score-face publishes refused identification and must exit 3
# ---------------------------------------------------------------------------


def _unit(vec: list[float]) -> list[float]:
    n = sum(v * v for v in vec) ** 0.5
    return [v / n for v in vec]


def _partial_id_face_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Exhaustive detection-complete group with two unboxed identity claims.

    score_face_run_record publishes refused identification and scores
    detection. Pre-fix score-face wrote that report and exited 0.
    """
    names = ["Alice Example", "Bob Builder", "Cara Cole"]
    dim = 8

    def _box(cx: float, name: str | None) -> dict[str, Any]:
        return {
            "x": cx,
            "y": 0.5,
            "w": 80 / 300,
            "h": 0.8,
            "name": name,
            "source": "iptc",
            "lineage": {
                **_LINEAGE,
                "decision": "named" if name else "stranger",
            },
        }

    def _det(bbox: list[float], emb: list[float]) -> dict[str, Any]:
        return {
            "bbox_px": bbox,
            "landmarks_px": [[0.0, 0.0]] * 5,
            "embedding": emb,
            "det_score": 0.95,
        }

    manifest = {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
        "roster": names,
        "entries": [
            {
                "path": "celebs01/group.jpg",
                "sha256": "a" * 64,
                "media_id": 1,
                "face_count": 3,
                "present_identities": names,
                "context_pack": {"title": "t"},
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
                "face_boxes": [
                    _box(50 / 300, names[0]),
                    _box(150 / 300, None),
                    _box(250 / 300, None),
                ],
            }
        ],
    }
    record = {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "t",
            "leg": "candidate",
            "model_id": "ort-yunet-sface",
            "embedding_dim": dim,
        },
        "items": [
            {
                "media_id": 1,
                "path": "celebs01/group.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [300, 100],
                "faces": [
                    _det([10.0, 10.0, 80.0, 80.0], _unit([1.0] + [0.0] * (dim - 1))),
                    _det([110.0, 10.0, 80.0, 80.0], _unit([0.0, 1.0] + [0.0] * (dim - 2))),
                    _det([210.0, 10.0, 80.0, 80.0], _unit([0.0, 0.0, 1.0] + [0.0] * (dim - 3))),
                ],
            }
        ],
    }
    man_path = tmp_path / "face-man.json"
    rec_path = tmp_path / "face-run.json"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    rec_path.write_text(json.dumps(record), encoding="utf-8")
    return man_path, rec_path


def test_score_face_exits_3_on_refused_identification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-02: a published refused ID slice is exit 3, not a clean 0."""
    import scripts.eval_harness.cli as cli_mod
    from scripts.eval_harness.manifest import ScoreInvariant

    man_path, rec_path = _partial_id_face_inputs(tmp_path)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score-face", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert exc.value.code == 3
    published = json.loads(rec_path.with_name("face-run-face-report.json").read_text(encoding="utf-8"))
    assert published["slices"]["full_corpus_identification"]["refused"] is True
    assert (
        published["slices"]["full_corpus_identification"]["invariant"]
        == ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS
    )
    assert published["detection"].get("refused") is not True


def test_score_face_allow_refused_identification_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _partial_id_face_inputs(tmp_path)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(
        [
            "score-face",
            "--manifest",
            str(man_path),
            "--run-record",
            str(rec_path),
            "--allow-refused=identification",
        ]
    )


def test_score_face_allow_refused_detection_does_not_consent_to_identification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A faces.*-only gate would miss slice-level identification refusal
    and treat --allow-refused=detection as enough. It must not.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _partial_id_face_inputs(tmp_path)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(
            [
                "score-face",
                "--manifest",
                str(man_path),
                "--run-record",
                str(rec_path),
                "--allow-refused=detection",
            ]
        )
    assert exc.value.code == 3


# ---------------------------------------------------------------------------
# S2R5-12 — an aborted run is not a corpus
# ---------------------------------------------------------------------------


def test_score_exits_1_when_run_record_is_aborted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One successful item + aborted=true used to pass the failed>0 gate.

    Filename is run.json (not *-aborted.json) so a path-spelling check
    cannot substitute for reading the flag.
    """
    import scripts.eval_harness.cli as cli_mod

    record = _run_record(face_count=1)
    record["aborted"] = True
    man_path, rec_path = _write_score_inputs(
        tmp_path, mode="exhaustive", boxed=True, record=record
    )
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert exc.value.code == 1
    assert "aborted" in capsys.readouterr().err
    assert (rec_path.with_name("run-report.json")).is_file()


def test_score_face_exits_1_when_run_record_is_aborted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _partial_id_face_inputs(tmp_path)
    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    payload["aborted"] = True
    rec_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score-face", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert exc.value.code == 1
    assert "aborted" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# S2R5-09 — fusion_runner is a publisher and must exit 3 on refusal
# ---------------------------------------------------------------------------


_BAKEOFF = (
    Path(__file__).resolve().parents[3] / "scene" / "tests" / "seed" / "bakeoff_golden.json"
)


def test_fusion_runner_exits_3_on_roster_only_bakeoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.eval_harness.cli import REFUSED_METRIC_EXIT_CODE
    from scripts.eval_harness.fusion_runner import main as fusion_main
    from scripts.eval_harness.manifest import ScoreInvariant

    code = fusion_main(
        ["--manifest", str(_BAKEOFF), "--mode", "staged", "--out-dir", str(tmp_path)]
    )
    assert code == REFUSED_METRIC_EXIT_CODE
    err = capsys.readouterr().err
    assert "detection=" in err
    assert ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY in err
    report = json.loads((tmp_path / "E20-FUSION-staged-report.json").read_text(encoding="utf-8"))
    assert report["faces"]["detection"]["refused"] is True


def test_fusion_runner_allow_refused_detection_does_not_consent_to_identification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.eval_harness.cli import REFUSED_METRIC_EXIT_CODE
    from scripts.eval_harness.fusion_runner import main as fusion_main

    code = fusion_main(
        [
            "--manifest",
            str(_BAKEOFF),
            "--mode",
            "staged",
            "--out-dir",
            str(tmp_path),
            "--allow-refused=detection",
        ]
    )
    assert code == REFUSED_METRIC_EXIT_CODE
    err = capsys.readouterr().err
    assert "identification=" in err
    assert "detection=" not in err.split("refused metric(s) (")[1].split(")")[0]


def test_fusion_runner_bare_allow_refused_exits_zero(tmp_path: Path) -> None:
    from scripts.eval_harness.fusion_runner import main as fusion_main

    code = fusion_main(
        [
            "--manifest",
            str(_BAKEOFF),
            "--mode",
            "staged",
            "--out-dir",
            str(tmp_path),
            "--allow-refused",
        ]
    )
    assert code == 0
