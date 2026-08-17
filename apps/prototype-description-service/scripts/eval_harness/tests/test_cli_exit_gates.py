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


def _manifest_doc(*, mode: str, boxed: bool, n: int = 1) -> dict[str, Any]:
    # VLM6-DELTA-03: n>1 replicates the single canonical entry under distinct
    # media_ids/paths so a test can clear SCORE_PASS_MIN_SCORED_IMAGES (=5,
    # branch-only category-vacuity gate) without changing per-entry semantics.
    return {
        "manifest_version": 3,
        "annotation_mode": mode,
        "roster": ["Alice Example", "Zed Zeta"],
        "entries": [
            {
                "path": f"mock_images/alice{i}.jpg",
                "sha256": "a" * 64,
                "media_id": i,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "Alice Example.",
                "must_right": ["Alice Example"],
                # VLM6-DELTA-03: non-empty so the branch-only empty-rubric gate
                # (score empty-rubric gate: easy_wrong is vacuous corpus-wide)
                # does not fire ahead of the refusal/consent gates these tests
                # actually exercise. "Zed Zeta" never appears in base_caption or
                # alt_text_draft, so the wrong-name trap stays untripped.
                "easy_wrong": ["Zed Zeta"],
                # VLM6-DELTA-03: one applicable, phrase-matched spatial_fact so
                # score_placement() records a "correct" claim (claims=1) instead
                # of an abstention — placement is a branch-only category-vacuity
                # sub-check (report.py score_vacuous_category_labels) and an
                # empty/abstained-only spatial_facts list leaves it vacuous
                # regardless of corpus size. The phrase below is echoed
                # verbatim in alt_text_draft below.
                "spatial_facts": [
                    {
                        "subject": "Alice Example",
                        "relation": "foreground",
                        "phrases": ["in the foreground"],
                    }
                ],
                # VLM6-DELTA-03: one false-polarity reference_fact (a fabrication
                # trap the caption never states) so images_with_traps > 0 and
                # fabricated_fact_is_vacuous() clears — without any authored
                # trap, fabricated-fact rate is structurally non-observable
                # (EVAL-19), independent of corpus size. Caption never mentions
                # "a dog", so this trap is not tripped (clean pass, not a fail).
                "reference_facts": [
                    {
                        "text": "a dog",
                        "kind": "object",
                        "polarity": "false",
                        "phrases": ["a dog"],
                    }
                ],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
                "face_boxes": [_named_box("Alice Example")] if boxed else [],
            }
            for i in range(1, n + 1)
        ],
    }


def _run_record(*, face_count: int = 3, n: int = 1) -> dict[str, Any]:
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
                "media_id": i,
                "path": f"mock_images/alice{i}.jpg",
                "describe": {
                    # "in the foreground" echoes the spatial_fact phrase in
                    # _manifest_doc() (near-verbatim correct placement claim);
                    # "a dog" is never mentioned, so the reference_facts trap
                    # is not tripped (VLM6-DELTA-03).
                    "alt_text_draft": "Alice Example in the foreground by the pool.",
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": "Alice Example",
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
                # VLM6-DELTA-03: clears identity_ordering category-vacuity
                # (report.py score_run_record counts ordering_positional only
                # when this equals IdentityOrdering.POSITIONAL).
                "identity_ordering": "positional",
                "face_count": face_count,
                "error": None,
            }
            for i in range(1, n + 1)
        ],
    }


def _write_score_inputs(
    tmp_path: Path,
    *,
    mode: str,
    boxed: bool,
    record: dict[str, Any] | None = None,
    n: int = 1,
) -> tuple[Path, Path]:
    # VLM6-DELTA-02: stamp the record's provenance.manifest_sha256 with the real
    # fetch-time hash of the manifest actually written to disk. A dummy sha
    # ("m" * 64) trips the branch-only manifest-drift gate
    # (_fold_manifest_drift_into_verdict / SCORE_GATE_PREFIX_MANIFEST_DRIFT)
    # before a test's intended gate ever fires, masking every downstream
    # assertion in this file (main has no such gate at all).
    import scripts.eval_harness.cli as cli_mod
    import scripts.eval_harness.manifest as man_mod

    man_path = tmp_path / f"{mode}.json"
    man_path.write_text(json.dumps(_manifest_doc(mode=mode, boxed=boxed, n=n)), encoding="utf-8")
    loaded_manifest = man_mod.load_manifest(str(man_path), skip_hash_verification=True)
    fetch_manifest_sha256 = cli_mod._manifest_sha(loaded_manifest)
    record = dict(record) if record is not None else _run_record(n=n)
    record = json.loads(json.dumps(record))  # defensive deep copy before mutating provenance
    record.setdefault("provenance", {})["manifest_sha256"] = fetch_manifest_sha256
    rec_path = tmp_path / "run.json"
    rec_path.write_text(json.dumps(record), encoding="utf-8")
    return man_path, rec_path


# ---------------------------------------------------------------------------
# S2R5-13 — gate must read the published report, not a second score call
# ---------------------------------------------------------------------------


def test_score_gate_exits_0_when_scored_and_published_report_agree_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-13 case A, re-pointed at the current single-build architecture.

    VLM6-DELTA-03: the original case A monkeypatched ``cli_mod.build_reports``
    to stamp a refusal onto ONLY the published JSON, expecting the exit gate
    (driven by a separate "real" rescore) to still catch it. Under FIR-11's
    current ``_cmd_score`` (F2d / GATE-05, "the documents written are exactly
    the documents ... certified — one build"), the default (no
    ``--check-determinism``, no ``--audience public``) path never calls
    ``build_reports`` at all: ``scored = score_run_record(...)`` is computed
    once and serialised directly to ``run-report.json``. The monkeypatch is
    therefore inert — proven live via ``uv run python3`` before this edit,
    confirming exit 0 / verdict=pass with the wrap installed and ignored. The
    published-vs-rescore divergence S2R5-13 guarded against is now
    structurally impossible for the LOCAL report by construction, so this
    test asserts that invariant directly: the single scored document that
    decided the exit code is exactly what landed on disk.
    """
    import scripts.eval_harness.cli as cli_mod

    # n=5 clears SCORE_PASS_MIN_SCORED_IMAGES (branch-only category-vacuity
    # gate); exhaustive + boxed GT is genuinely clean (no refusal at all).
    man_path, rec_path = _write_score_inputs(tmp_path, mode="exhaustive", boxed=True, n=5)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    published = json.loads(rec_path.with_name("run-report.json").read_text(encoding="utf-8"))
    assert published["faces"]["detection"].get("refused") is not True
    assert published["verdict"]["verdict"] == "pass"


def test_score_gate_exits_category_vacuity_when_roster_only_detection_is_unconsented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2R5-13 case B, re-pointed at the current single-build architecture.

    VLM6-DELTA-03: the original case B monkeypatched ``build_reports`` to
    stamp a clean detection onto ONLY the published JSON, expecting the exit
    gate to green-exit over a "real" refused rescore. As with case A, the
    monkeypatch never fires under the default score path (no
    ``build_reports`` call at all — see the sibling test above), so there is
    no published/rescore divergence to exercise. ``roster_only`` mode
    structurally refuses detection regardless of GT boxing (report.py:
    ``elif mode is AnnotationMode.ROSTER_ONLY: det = None``), and with no
    ``--allow-refused`` this is a genuine, unconsented, vacuous category —
    the canonical current behaviour is a hard non-zero exit via
    ``SCORE_GATE_PREFIX_CATEGORY_VACUITY`` (fires ahead of
    ``raise_if_unconsented_refusals`` in ``_cmd_score``), never a silent
    exit 0. Verified live: exit code is the category-vacuity string, not
    int 3 and not 0.
    """
    import scripts.eval_harness.cli as cli_mod

    # n=5 clears SCORE_PASS_MIN_SCORED_IMAGES so the sole vacuity driver is
    # the genuinely-refused, unconsented face_detection category.
    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=True, n=5)
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert isinstance(exc.value.code, str)
    assert exc.value.code.startswith(cli_mod.SCORE_GATE_PREFIX_CATEGORY_VACUITY)
    published = json.loads(rec_path.with_name("run-report.json").read_text(encoding="utf-8"))
    assert published["faces"]["detection"]["refused"] is True
    assert published["faces"]["detection"]["invariant"] == "detection_refuses_roster_only"
    assert published["verdict"]["verdict"] == "not_ready"


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

    # VLM6-GATE-INT-01: n=5 clears SCORE_PASS_MIN_SCORED_IMAGES so the narrowed
    # category-vacuity gate (which now suppresses only identification/detection
    # restatement reasons) does not also hard-fail on sample_size ahead of the
    # refusal-consent path these tests target.
    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False, n=5)
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

    # VLM6-GATE-INT-01: n=5 clears SCORE_PASS_MIN_SCORED_IMAGES so the narrowed
    # category-vacuity gate (which now suppresses only identification/detection
    # restatement reasons) does not also hard-fail on sample_size ahead of the
    # refusal-consent path these tests target.
    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False, n=5)
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

    # VLM6-GATE-INT-01: n=5 clears SCORE_PASS_MIN_SCORED_IMAGES so the narrowed
    # category-vacuity gate (which now suppresses only identification/detection
    # restatement reasons) does not also hard-fail on sample_size ahead of the
    # refusal-consent path these tests target.
    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False, n=5)
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

    # VLM6-GATE-INT-01: n=5 clears SCORE_PASS_MIN_SCORED_IMAGES so the narrowed
    # category-vacuity gate (which now suppresses only identification/detection
    # restatement reasons) does not also hard-fail on sample_size ahead of the
    # refusal-consent path these tests target.
    man_path, rec_path = _write_score_inputs(tmp_path, mode="roster_only", boxed=False, n=5)
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

    main's ``raise_if_aborted_run`` exits int 1 pre-scoring. This branch moved
    the aborted check to a post-write gate (VLM6-S2A-A-02, see cli.py
    ``if record.get("aborted")`` in ``_cmd_score``) so a failing report is
    still written for triage (OBS-04) before the exit fires; the gate raises
    ``ScoreGateError`` and ``main()`` maps that to ``sys.exit(str(exc))``, so
    the exit code is the class-unique gate string, not an int. main's
    ``raise_if_aborted_run`` is dead code on this branch (defined, never
    called) — out of scope here (VLM6-DELTA-03 territory, not this test).
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
    assert isinstance(exc.value.code, str)
    assert exc.value.code.startswith(cli_mod.SCORE_GATE_PREFIX_ABORTED_RECORD)
    assert "aborted" in exc.value.code
    assert (rec_path.with_name("run-report.json")).is_file()


def test_score_face_exits_1_when_run_record_is_aborted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """See test_score_exits_1_when_run_record_is_aborted docstring: this branch
    moved the aborted check to a post-write ScoreGateError gate (VLM6-R2-F-03),
    so the exit code is the class-unique gate string, not int 1.
    """
    import scripts.eval_harness.cli as cli_mod

    man_path, rec_path = _partial_id_face_inputs(tmp_path)
    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    payload["aborted"] = True
    rec_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score-face", "--manifest", str(man_path), "--run-record", str(rec_path)])
    assert isinstance(exc.value.code, str)
    assert exc.value.code.startswith(cli_mod.SCORE_GATE_PREFIX_ABORTED_RECORD)
    assert "aborted" in exc.value.code


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
