"""Bake-off HTML report builder: cost/latency, token roll-up, failure frame.

Deterministic per-image cost = flat instance $/hr x measured inference seconds
(``rate * latency_s / 3600``) plus an optional run-total / cost-per-image
subtitle. Every assertion is paired with a discrimination guard [TEST-15]:
the same code path with the cost inputs *absent* must NOT emit the cost token,
so a green here proves the renderer reacts to the input rather than always
printing (or always omitting) a cost.

BR-01: the 10-image frame and the ``--cost-total`` denominator must include
every *attempted* media_id, including timeouts and transport failures.
BR-04: ``_tokens_label`` / ``_index_run`` are the token axis; they have no
other home. Tests below kill ``return ""`` and a missing ``tokens`` key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.build_bakeoff_report import (
    _card_html,
    _index_run,
    _pick_varied,
    _tokens_label,
    main,
)

_ENTRY = {"path": "mock_images/alice-pool.jpg", "present_identities": ["Alice Example"]}
_RUN = {
    "Qwen3-VL-30B": {
        1: {"title": "Alice", "alt": "Alice by a pool.", "caption": "A long caption.",
            "latency_s": 5.0, "model_calls": 2, "error": None},
    }
}


def test_card_cost_rendered_only_when_hourly_rate_given() -> None:
    # rate 7.2 $/hr x 5.0 s / 3600 = $0.01000/img — clean closed-form value.
    with_rate = _card_html(1, _ENTRY, _RUN, None, hourly_rate=7.2)
    assert "$0.01000/exposure" in with_rate

    # Discrimination guard: same card, no rate => the cost token must vanish,
    # while the latency it is derived from stays. If this branch also printed a
    # cost the test above would be vacuous.
    without_rate = _card_html(1, _ENTRY, _RUN, None)
    assert "5.00s" in without_rate
    assert "/img" not in without_rate


def test_card_no_cost_when_latency_missing_even_with_rate() -> None:
    run_no_lat = {"M": {1: {"alt": "x", "latency_s": None, "model_calls": 1, "error": None}}}
    card = _card_html(1, _ENTRY, run_no_lat, None, hourly_rate=7.2)
    assert "/img" not in card  # no latency => no deterministic per-image cost


def _write_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    manifest = {"entries": [{"media_id": 1, "path": "mock_images/a.jpg", "present_identities": []},
                            {"media_id": 2, "path": "mock_images/b.jpg", "present_identities": []}]}
    record = {"items": [
        {"media_id": 1, "describe": {"alt_text_draft": "a", "passes": [{"latency_s": 4.0}]}},
        {"media_id": 2, "describe": {"alt_text_draft": "b", "passes": [{"latency_s": 6.0}]}},
    ]}
    mpath = tmp_path / "manifest.json"
    rpath = tmp_path / "run.json"
    mpath.write_text(json.dumps(manifest))
    rpath.write_text(json.dumps(record))
    return mpath, rpath


def test_main_hourly_rate_renders_per_image_cost(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)  # media 1,2 with pass latency 4.0s, 6.0s
    out = tmp_path / "report.html"

    # 7.2 $/hr x 4.0 s / 3600 = $0.00800/img ; x 6.0 s = $0.01200/img
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out), "--hourly-rate", "7.2"])
    assert rc == 0
    doc = out.read_text()
    assert "$0.00800/exposure" in doc
    assert "$0.01200/exposure" in doc

    # Discrimination guard: no --hourly-rate => the per-image cost token vanishes.
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out)])
    assert rc == 0
    assert "/img" not in out.read_text()


def test_main_hourly_rate_zero_is_free_not_suppressed(tmp_path: Path) -> None:
    # 0 $/hr is a legitimate free-tier rate; it must render $0, not be dropped as falsy.
    mpath, rpath = _write_fixtures(tmp_path)
    out = tmp_path / "report.html"
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out), "--hourly-rate", "0"])
    assert rc == 0
    assert "$0.00000/exposure" in out.read_text()


def test_main_rejects_negative_cost_args(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)
    out = tmp_path / "report.html"
    for bad in (["--hourly-rate", "-1"], ["--cost-total", "-5"]):
        with pytest.raises(SystemExit):  # argparse .error() exits non-zero
            main(["--manifest", str(mpath), "--run", f"M={rpath}",
                  "--media-ids", "1,2", "--out", str(out), *bad])


def test_subtitle_cost_total_rendered_only_with_flag(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)
    out = tmp_path / "report.html"

    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out), "--cost-total", "10.0",
               "--cost-denominator", "exposure"])
    assert rc == 0
    doc = out.read_text()
    assert "total $10.00" in doc
    assert "$5.0000/exposure" in doc  # 10.0 / 2 model exposures

    # Discrimination guard: drop --cost-total, the subtitle cost fragment goes away.
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out)])
    assert rc == 0
    doc = out.read_text()
    assert "total $" not in doc
    assert "/image" not in doc


# ---------------------------------------------------------------------------
# BR-04 — token column: _tokens_label reader contract + _index_run key
# ---------------------------------------------------------------------------

_TOKENS_NONE = {
    "prompt_tokens": None,
    "completion_tokens": None,
    "total_tokens": None,
    "complete": False,
}
_TOKENS_PARTIAL = {
    "prompt_tokens": 2400,
    "completion_tokens": 410,
    "total_tokens": 2810,
    "complete": False,
}
_TOKENS_COMPLETE = {
    "prompt_tokens": 2400,
    "completion_tokens": 410,
    "total_tokens": 2810,
    "complete": True,
}


def test_tokens_label_none_counts_are_not_captured() -> None:
    # Zero passes carried usage: counts are None, complete is False.
    # Empty string is the bug — operator cannot tell "not measured" from N/A.
    assert _tokens_label(_TOKENS_NONE) == " · tokens not captured"


def test_tokens_label_partial_integer_counts_mark_incomplete() -> None:
    # Some-but-not-all passes carried usage: integer sums, complete False.
    # The trailing + is the only signal a partial sum is not the whole image.
    assert _tokens_label(_TOKENS_PARTIAL) == " · 2810+ tok (410 out)"


def test_tokens_label_complete_integer_counts_are_plain() -> None:
    assert _tokens_label(_TOKENS_COMPLETE) == " · 2810 tok (410 out)"


def test_tokens_label_integer_zero_does_not_crash() -> None:
    # Characterisation: current writer shape (bare integer 0, or a dict of
    # zeros) may land before or after the sibling _sum_usage change. Must
    # not raise. No kill power on the BR-04 mutations — those live above.
    bare = _tokens_label(0)
    assert isinstance(bare, str)
    zeros = _tokens_label(
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "complete": False}
    )
    assert isinstance(zeros, str)


def test_card_html_renders_tokens_not_captured_marker() -> None:
    run = {
        "Qwen3-VL-30B": {
            1: {
                "title": "Alice",
                "alt": "Alice by a pool.",
                "caption": "A long caption.",
                "latency_s": 5.0,
                "model_calls": 2,
                "error": None,
                "tokens": _TOKENS_NONE,
            }
        }
    }
    card = _card_html(1, _ENTRY, run, None)
    assert "tokens not captured" in card


def test_index_run_always_carries_tokens_key(tmp_path: Path) -> None:
    # Deleting the "tokens" key from the _index_run payload used to go green.
    record = {
        "items": [
            {
                "media_id": 7,
                "describe": {"alt_text_draft": "x", "passes": [{"latency_s": 1.0}]},
                "error": None,
            }
        ]
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(record))
    indexed = _index_run(str(path))
    assert "tokens" in indexed[7]


def test_index_run_forwards_describe_tokens(tmp_path: Path) -> None:
    record = {
        "items": [
            {
                "media_id": 7,
                "describe": {
                    "alt_text_draft": "x",
                    "passes": [{"latency_s": 1.0}],
                    "tokens": _TOKENS_COMPLETE,
                },
                "error": None,
            }
        ]
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(record))
    indexed = _index_run(str(path))
    assert indexed[7]["tokens"] == _TOKENS_COMPLETE


def test_index_run_does_not_invent_calls_or_latency(tmp_path: Path) -> None:
    record = {
        "items": [
            {"media_id": 7, "describe": {"alt_text_draft": "x", "passes": []}},
            {"media_id": 8, "describe": {"alt_text_draft": "y", "passes": [{"raw": "z"}]}},
        ]
    }
    path = tmp_path / "unmeasured.json"
    path.write_text(json.dumps(record))
    indexed = _index_run(str(path))
    assert indexed[7]["model_calls"] is None
    assert indexed[7]["latency_s"] is None
    assert indexed[8]["model_calls"] == 1
    assert indexed[8]["latency_s"] is None


def test_index_run_rejects_duplicate_media_ids(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps({"items": [{"media_id": 7}, {"media_id": 7}]}))
    with pytest.raises(ValueError, match="duplicate media_id"):
        _index_run(str(path))


# ---------------------------------------------------------------------------
# BR-01 — sampling frame + cost denominator admit attempted failures
# ---------------------------------------------------------------------------

def test_pick_varied_admits_errored_attempted_ids() -> None:
    manifest = {
        10: {"present_identities": []},
        20: {"present_identities": []},
    }
    runs = {
        "M": {
            10: {"error": None, "caption": "ok", "alt": "ok"},
            20: {"error": "RemoteClientError: timeout", "caption": None, "alt": None},
        }
    }
    picked = _pick_varied(manifest, runs, 10)
    assert 10 in picked
    assert 20 in picked


def test_pick_varied_keeps_image_both_legs_failed() -> None:
    # Pair report must not omit the image both generations blew the 900 s ceiling on.
    manifest = {
        1: {"present_identities": []},
        2: {"present_identities": []},
        3: {"present_identities": []},
    }
    runs = {
        "prev": {
            1: {"error": None, "caption": "a", "alt": "a"},
            2: {"error": None, "caption": "b", "alt": "b"},
            3: {"error": "timeout", "caption": None, "alt": None},
        },
        "curr": {
            1: {"error": None, "caption": "a2", "alt": "a2"},
            2: {"error": None, "caption": "b2", "alt": "b2"},
            3: {"error": "timeout", "caption": None, "alt": None},
        },
    }
    picked = _pick_varied(manifest, runs, 10)
    assert 3 in picked


def _write_attempted_with_error(tmp_path: Path) -> tuple[Path, Path]:
    """Three attempted images; media 3 is a timeout. Display sample can be a subset."""
    manifest = {
        "entries": [
            {"media_id": 1, "path": "mock_images/a.jpg", "present_identities": []},
            {"media_id": 2, "path": "mock_images/b.jpg", "present_identities": []},
            {"media_id": 3, "path": "mock_images/c.jpg", "present_identities": []},
        ]
    }
    record = {
        "items": [
            {"media_id": 1, "describe": {"alt_text_draft": "a", "passes": [{"latency_s": 4.0}]}},
            {"media_id": 2, "describe": {"alt_text_draft": "b", "passes": [{"latency_s": 6.0}]}},
            {
                "media_id": 3,
                "error": "RemoteClientError: timeout",
                "describe": {},
            },
        ]
    }
    mpath = tmp_path / "manifest.json"
    rpath = tmp_path / "run.json"
    mpath.write_text(json.dumps(manifest))
    rpath.write_text(json.dumps(record))
    return mpath, rpath


def test_cost_denominator_is_attempted_corpus_including_errors(tmp_path: Path) -> None:
    # 3 attempted (one timeout), display only the two survivors, cost $9.
    # Denominator is the corpus (9/3 = $3.0000), not the display sample (9/2 = $4.5000).
    mpath, rpath = _write_attempted_with_error(tmp_path)
    out = tmp_path / "report.html"
    rc = main(
        [
            "--manifest",
            str(mpath),
            "--run",
            f"M={rpath}",
            "--media-ids",
            "1,2",
            "--out",
            str(out),
                "--cost-total",
                "9.0",
                "--cost-denominator",
                "exposure",
        ]
    )
    assert rc == 0
    doc = out.read_text()
    assert "total $9.00" in doc
    assert "$3.0000/exposure" in doc
    assert "$4.5000/exposure" not in doc


def test_cost_exposure_denominator_counts_each_run_exposure(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)
    second = tmp_path / "second.json"
    second.write_text(
        json.dumps({
            "items": [
                {"media_id": 1, "describe": {"passes": [{"latency_s": 2.0}]}},
                {"media_id": 2, "describe": {"passes": [{"latency_s": 3.0}]}},
            ]
        })
    )
    out = tmp_path / "report.html"
    rc = main([
        "--manifest", str(mpath), "--run", f"A={rpath}", "--run", f"B={second}",
        "--media-ids", "1,2", "--out", str(out), "--cost-total", "10.0",
        "--cost-denominator", "exposure",
    ])
    assert rc == 0
    doc = out.read_text()
    assert "$2.5000/exposure" in doc  # 10 / (2 exposures per run × 2 runs)
    assert "$5.0000/exposure" not in doc


def test_cost_call_denominator_refuses_unknown_calls(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)
    rpath.write_text(json.dumps({
        "items": [
            {"media_id": 1, "describe": {"alt_text_draft": "a"}},
            {"media_id": 2, "describe": {"alt_text_draft": "b"}},
        ]
    }))
    out = tmp_path / "report.html"
    with pytest.raises(SystemExit):
        main([
            "--manifest", str(mpath), "--run", f"M={rpath}", "--media-ids", "1,2",
            "--out", str(out), "--cost-total", "10.0", "--cost-denominator", "call",
        ])


def test_auto_pick_renders_failure_card_for_errored_item(tmp_path: Path) -> None:
    mpath, rpath = _write_attempted_with_error(tmp_path)
    out = tmp_path / "report.html"
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}", "--out", str(out), "--limit", "10"])
    assert rc == 0
    doc = out.read_text()
    assert 'class="err"' in doc
    assert "RemoteClientError: timeout" in doc
    assert ">#3<" in doc or "#3" in doc


def _write_gate_record(path: Path, *, n: int = 100) -> None:
    path.write_text(json.dumps({
        "items": [
            {
                "media_id": media_id,
                "describe": {"alt_text_draft": f"d{media_id}", "passes": [{"latency_s": 1.0}]},
                "error": None,
            }
            for media_id in range(1, n + 1)
        ],
        "timing": {"loop": "closed_serial"},
        "gpu": {"sampling": "enabled"},
    }))


def _write_gate_manifest(path: Path, *, n: int = 100) -> None:
    path.write_text(json.dumps({
        "entries": [
            {
                "media_id": media_id,
                "path": f"image-{media_id}.jpg",
                "sha256": f"{media_id:064x}",
                "subject_ids": [f"subject-{(media_id - 1) % 10}"],
                "demographic_cohort": f"cohort-{(media_id - 1) % 2}",
                "domain": "faces",
                "difficulty": "medium",
                "capture_device": "fixture-camera",
                "lighting": "daylight",
                "environment": "studio",
                "session": f"session-{(media_id - 1) % 5}",
                "reference_facts": [{"kind": "visible", "value": f"fact-{media_id}"}],
                "spatial_facts": [{"relation": "left_of", "value": f"fact-{media_id}"}],
                "face_boxes": [{"name": f"subject-{(media_id - 1) % 10}"}],
                "present_identities": [f"subject-{(media_id - 1) % 10}"],
            }
            for media_id in range(1, n + 1)
        ]
    }))


def _write_gate_selection_manifest(path: Path, *, n: int = 10) -> None:
    """A disjoint selection/calibration corpus for the sealed gate fixture."""
    path.write_text(json.dumps({
        "entries": [
            {
                "media_id": 1000 + media_id,
                "path": f"selection-{media_id}.jpg",
                "sha256": f"{1000 + media_id:064x}",
                "subject_ids": [f"selection-subject-{(media_id - 1) % 5}"],
                "present_identities": [f"selection-subject-{(media_id - 1) % 5}"],
            }
            for media_id in range(1, n + 1)
        ]
    }))


def test_bakeoff_gate_passes_only_with_roster_baselines_and_observability(tmp_path: Path) -> None:
    manifest = tmp_path / "golden-100.json"
    _write_gate_manifest(manifest)
    selection = tmp_path / "selection.json"
    _write_gate_selection_manifest(selection)
    candidate = tmp_path / "candidate.json"
    incumbent = tmp_path / "incumbent.json"
    _write_gate_record(candidate)
    _write_gate_record(incumbent)
    baselines = {}
    for label in ("zero_rule_context_echo", "context_only_heuristic", "current_production", "blinded_human"):
        path = tmp_path / f"{label}.json"
        _write_gate_record(path)
        baselines[label] = path
    score = tmp_path / "candidate.score.ok"
    score.touch()
    out = tmp_path / "gate.html"
    argv = [
        "--manifest", str(manifest), "--out", str(out), "--bakeoff-gate",
        "--selection-manifest", str(selection),
        "--expected-candidate", "candidate", "--expected-incumbent", "incumbent",
        "--run", f"candidate={candidate}", "--run", f"incumbent={incumbent}",
        "--score-ok", f"candidate={score}", "--media-ids", "1",
    ]
    for label, path in baselines.items():
        argv.extend(["--baseline-run", f"{label}={path}"])
    assert main(argv) == 0
    doc = out.read_text()
    assert "bakeoff-gate: pass" in doc
    assert "readiness: data=pass selection=pass model=pass infra=pass monitoring=pass" in doc


def test_bakeoff_gate_rejects_selection_subject_or_image_overlap(tmp_path: Path) -> None:
    manifest = tmp_path / "golden-100.json"
    _write_gate_manifest(manifest)
    selection = tmp_path / "selection.json"
    _write_gate_selection_manifest(selection)
    payload = json.loads(selection.read_text())
    payload["entries"][0]["media_id"] = 1
    payload["entries"][0]["sha256"] = f"{1:064x}"
    payload["entries"][0]["subject_ids"] = ["subject-0"]
    payload["entries"][0]["present_identities"] = ["subject-0"]
    selection.write_text(json.dumps(payload))
    evaluation = _gate_evaluation_for_test(manifest, selection)
    assert evaluation["status"] == "not_ready"
    assert evaluation["axes"]["selection"] == "not_ready"
    assert any("selection" in reason and ("media_id" in reason or "sha256" in reason)
               for reason in evaluation["reasons"])
    assert any("subject" in reason for reason in evaluation["reasons"])


def test_bakeoff_gate_refuses_missing_corpus_strata_and_metric_backing(tmp_path: Path) -> None:
    manifest = tmp_path / "golden-100.json"
    _write_gate_manifest(manifest)
    payload = json.loads(manifest.read_text())
    for entry in payload["entries"]:
        entry.pop("reference_facts", None)
        entry.pop("spatial_facts", None)
        entry.pop("face_boxes", None)
        entry.pop("demographic_cohort", None)
        entry.pop("capture_device", None)
        entry.pop("lighting", None)
        entry.pop("environment", None)
        entry.pop("session", None)
    manifest.write_text(json.dumps(payload))
    selection = tmp_path / "selection.json"
    _write_gate_selection_manifest(selection)
    evaluation = _gate_evaluation_for_test(manifest, selection)
    assert evaluation["status"] == "not_ready"
    assert evaluation["axes"]["data"] == "not_ready"
    reasons = " ".join(evaluation["reasons"])
    assert "demographic_cohort" in reasons
    assert "capture_device" in reasons
    assert "reference_facts" in reasons


def _gate_evaluation_for_test(manifest: Path, selection: Path) -> dict:
    """Exercise the report gate without duplicating run/baseline boilerplate."""
    from scripts.eval_harness.build_bakeoff_report import _gate_evaluation, _load_manifest

    entries = _load_manifest(str(manifest))
    selection_entries = _load_manifest(str(selection))
    return _gate_evaluation(
        entries,
        {},
        {},
        {},
        expected_candidates=(),
        expected_incumbents=(),
        required_baselines=(),
        score_ok={},
        selection_manifests={str(selection): selection_entries},
    )


def test_bakeoff_gate_rejects_incomplete_media_id_multiset(tmp_path: Path) -> None:
    manifest = tmp_path / "golden-100.json"
    _write_gate_manifest(manifest)
    candidate = tmp_path / "candidate.json"
    incumbent = tmp_path / "incumbent.json"
    _write_gate_record(candidate, n=99)
    _write_gate_record(incumbent)
    baselines = {}
    for label in ("zero_rule_context_echo", "context_only_heuristic", "current_production", "blinded_human"):
        path = tmp_path / f"{label}.json"
        _write_gate_record(path)
        baselines[label] = path
    score = tmp_path / "candidate.score.ok"
    score.touch()
    out = tmp_path / "gate.html"
    argv = [
        "--manifest", str(manifest), "--out", str(out), "--bakeoff-gate",
        "--expected-candidate", "candidate", "--expected-incumbent", "incumbent",
        "--run", f"candidate={candidate}", "--run", f"incumbent={incumbent}",
        "--score-ok", f"candidate={score}", "--media-ids", "1",
    ]
    for label, path in baselines.items():
        argv.extend(["--baseline-run", f"{label}={path}"])
    assert main(argv) != 0
    doc = out.read_text()
    assert "bakeoff-gate: not_ready" in doc
    assert "incomplete media-id multiset" in doc
    assert "candidate" in doc and "missing 100" in doc


def test_bakeoff_gate_rejects_consented_foreign_required_record(tmp_path: Path) -> None:
    manifest = tmp_path / "golden-100.json"
    _write_gate_manifest(manifest)
    candidate = tmp_path / "candidate.json"
    incumbent = tmp_path / "incumbent.json"
    _write_gate_record(candidate)
    _write_gate_record(incumbent)
    baselines = {}
    for label in ("zero_rule_context_echo", "context_only_heuristic", "current_production", "blinded_human"):
        path = tmp_path / f"{label}.json"
        _write_gate_record(path)
        baselines[label] = path
    candidate_payload = json.loads(candidate.read_text())
    candidate_payload["provenance"] = {"manifest_sha256": "foreign"}
    candidate.write_text(json.dumps(candidate_payload))
    for path in (incumbent, *baselines.values()):
        payload = json.loads(path.read_text())
        payload["provenance"] = {"manifest_sha256": "native"}
        path.write_text(json.dumps(payload))
    score = tmp_path / "candidate.score.ok"
    score.touch()
    out = tmp_path / "gate.html"
    argv = [
        "--manifest", str(manifest), "--out", str(out), "--bakeoff-gate",
        "--allow-foreign-run", "candidate",
        "--expected-candidate", "candidate", "--expected-incumbent", "incumbent",
        "--run", f"candidate={candidate}", "--run", f"incumbent={incumbent}",
        "--score-ok", f"candidate={score}", "--media-ids", "1",
    ]
    for label, path in baselines.items():
        argv.extend(["--baseline-run", f"{label}={path}"])
    assert main(argv) != 0
    doc = out.read_text()
    assert "bakeoff-gate: not_ready" in doc
    assert "foreign run records cannot satisfy bakeoff gate" in doc


def test_bakeoff_gate_is_not_ready_for_a_serving_skip_or_missing_baselines(tmp_path: Path) -> None:
    manifest = tmp_path / "golden-100.json"
    _write_gate_manifest(manifest)
    failure = tmp_path / "skip.json"
    failure.write_text(json.dumps({
        "schema": "acx-eval/v1", "kind": "serving-gate-failed", "status": "serving-gate-failed",
        "candidate_id": "candidate", "model_id": "m", "stack": "vllm",
        "reason": "stack not supported", "evidence": {"planner": "test"},
    }))
    out = tmp_path / "gate.html"
    rc = main([
        "--manifest", str(manifest), "--out", str(out), "--bakeoff-gate",
        "--expected-candidate", "candidate", "--expected-incumbent", "incumbent",
        "--serving-gate-failed", f"candidate={failure}", "--media-ids", "1",
    ])
    assert rc != 0
    doc = out.read_text()
    assert "bakeoff-gate: not_ready" in doc
    assert "serving-gate-failed records" in doc
    assert "missing required baseline arms" in doc


# --- VLM6-CTRL: manifest-comparability gate -------------------------------
#
# A 646-image run record is a superset of a 10-image manifest, so every cell
# populates and the column renders as an unmarked "(control)". The gate refuses
# that silently-wrong comparison [EVAL-01 same split, EXP-07 mismatched
# allocation invalidates] on two independent signals: media_ids the manifest
# does not contain (structural, version-independent) and the stamped
# provenance sha (only when the manifest is a loadable v3).
#
# Every refusal assertion is paired with a discrimination guard [TEST-15]: the
# same path with comparable inputs must exit 0 and carry no badge, so a green
# here proves the gate reacts to the input rather than always firing.

_V3_MANIFEST = str(Path(__file__).resolve().parents[2] / "scripts/eval_harness/bakeoff10-manifest-20260716.json")
_NOT_COMPARABLE = 4


def _load_v3():
    from scripts.eval_harness.manifest import load_manifest

    return load_manifest(
        _V3_MANIFEST,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="report comparability tests do not read image bytes",
    )


def _v3_sha() -> str:
    from scripts.eval_harness.build_bakeoff_report import _expected_shas, _manifest_sha

    shas, mode = _expected_shas(_V3_MANIFEST)
    assert mode == "structural + manifest digest"
    sha = _manifest_sha(_load_v3())
    assert sha in shas
    return sha


def _v3_media_ids() -> list[int]:
    return [int(e["media_id"]) for e in json.loads(Path(_V3_MANIFEST).read_text())["entries"]][:2]


def _run_record(tmp_path: Path, name: str, media_ids: list[int], sha: object) -> Path:
    rec: dict = {"items": [{"media_id": m, "describe": {"alt_text_draft": f"d{m}", "passes": [{"latency_s": 1.0}]}}
                           for m in media_ids]}
    if sha is not None:
        rec["provenance"] = {"manifest_sha256": sha}
    path = tmp_path / name
    path.write_text(json.dumps(rec))
    return path


def _build(tmp_path: Path, runs: list[str], *extra: str, manifest: str = _V3_MANIFEST) -> tuple[int, Path]:
    from scripts.eval_harness.build_bakeoff_report import main as build_main

    out = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.html"
    argv = ["--manifest", manifest, "--out", str(out),
            "--media-ids", ",".join(str(m) for m in _v3_media_ids())]
    for spec in runs:
        argv += ["--run", spec]
    return build_main(argv + list(extra)), out


def test_matching_manifest_sha_renders_unbadged(tmp_path: Path) -> None:
    ids = _v3_media_ids()
    rec = _run_record(tmp_path, "ok.json", ids, _v3_sha())
    rc, out = _build(tmp_path, [f"Candidate={rec}"])
    assert rc == 0
    doc = out.read_text()
    assert "NOT COMPARABLE" not in doc
    assert "manifest identity: structural + manifest digest" in doc


def test_noncanonical_fusion_digest_is_refused(tmp_path: Path) -> None:
    """Fusion records must use the same canonical manifest identity recipe."""
    from scripts.eval_harness.build_bakeoff_report import _manifest_sha

    manifest = _load_v3()
    canonical = _manifest_sha(manifest)
    rec = _run_record(tmp_path, "fusion.json", _v3_media_ids(), "f" * 64)
    rc, out = _build(tmp_path, [f"Fusion={rec}"])
    assert rc == _NOT_COMPARABLE
    assert not out.exists()
    canonical_rec = _run_record(tmp_path, "fusion-canonical.json", _v3_media_ids(), canonical)
    rc, out = _build(tmp_path, [f"Fusion={canonical_rec}"])
    assert rc == 0
    assert "NOT COMPARABLE" not in out.read_text()


def test_foreign_manifest_sha_is_fatal_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ids = _v3_media_ids()
    rec = _run_record(tmp_path, "foreign.json", ids, "f" * 64)
    rc, out = _build(tmp_path, [f"Qwen3-VL-30B (control)={rec}"])
    assert rc == _NOT_COMPARABLE
    assert not out.exists()  # a refused report must not leave a readable artifact
    err = capsys.readouterr().err
    assert "ffffffffffff" in err and _v3_sha()[:12] in err  # both shas named
    assert "--allow-foreign-run" in err  # the error tells the operator the way out


def test_refusal_warns_that_a_pre_existing_report_is_stale(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rec = _run_record(tmp_path, "foreign3.json", _v3_media_ids(), "f" * 64)
    stale = tmp_path / "stale.html"
    stale.write_text("<html>older report</html>")
    from scripts.eval_harness.build_bakeoff_report import main as build_main

    rc = build_main(["--manifest", _V3_MANIFEST, "--out", str(stale),
                     "--media-ids", ",".join(str(m) for m in _v3_media_ids()), "--run", f"C={rec}"])
    assert rc == _NOT_COMPARABLE
    assert stale.read_text() == "<html>older report</html>"  # untouched, not half-written
    assert "still holds an older report" in capsys.readouterr().err


def test_missing_provenance_is_fatal_against_a_real_manifest(tmp_path: Path) -> None:
    rec = _run_record(tmp_path, "noprov.json", _v3_media_ids(), None)
    rc, _ = _build(tmp_path, [f"Candidate={rec}"])
    assert rc == _NOT_COMPARABLE


def test_non_string_provenance_sha_is_refused_not_crashed(tmp_path: Path) -> None:
    rec = _run_record(tmp_path, "intsha.json", _v3_media_ids(), 12345)
    rc, _ = _build(tmp_path, [f"Candidate={rec}"])
    assert rc == _NOT_COMPARABLE  # coerced and compared, not a TypeError traceback


def test_duplicate_run_labels_are_rejected(tmp_path: Path) -> None:
    rec = _run_record(tmp_path, "dup.json", _v3_media_ids(), _v3_sha())
    with pytest.raises(SystemExit):
        _build(tmp_path, [f"Candidate={rec}", f"Candidate={rec}"])


def test_consent_keeps_the_column_but_badges_it(tmp_path: Path) -> None:
    from scripts.eval_harness.build_bakeoff_report import NON_COMPARABLE_BADGE

    ids = _v3_media_ids()
    foreign = _run_record(tmp_path, "foreign2.json", ids, "a" * 64)
    native = _run_record(tmp_path, "native.json", ids, _v3_sha())
    rc, out = _build(tmp_path, [f"Control={foreign}", f"Candidate={native}"],
                     "--allow-foreign-run", "Control")
    assert rc == 0
    doc = out.read_text()
    # Exactly one column per card is badged, and it is the foreign one. An
    # implementation that badged every column fails here [TEST-15].
    assert doc.count('class="model warn"') == len(ids)
    assert doc.count('class="model"') == len(ids)  # the native column stays clean
    assert "aaaaaaaaaaaa" in doc
    for chunk in doc.split('<div class="run">')[1:]:
        head = chunk[:300]
        if "Candidate" in head:
            assert NON_COMPARABLE_BADGE.strip() not in head


def test_structural_mismatch_is_fatal_even_with_a_matching_sha(tmp_path: Path) -> None:
    """The 646-vs-10 case: extra media_ids alone condemn the run [EXP-07]."""
    rec = _run_record(tmp_path, "superset.json", _v3_media_ids() + [999001, 999002], _v3_sha())
    rc, out = _build(tmp_path, [f"Control={rec}"])
    assert rc == _NOT_COMPARABLE
    assert not out.exists()


def test_structural_mismatch_is_fatal_under_a_non_v3_manifest(tmp_path: Path) -> None:
    """No digest anchor available: the structural check must still refuse."""
    mpath, _ = _write_fixtures(tmp_path)  # toy manifest: no manifest_version
    from scripts.eval_harness.build_bakeoff_report import main as build_main

    superset = _run_record(tmp_path, "toy_superset.json", [1, 2, 424242], None)
    out_bad = tmp_path / "toy_bad.html"
    assert build_main(["--manifest", str(mpath), "--run", f"A={superset}",
                       "--media-ids", "1,2", "--out", str(out_bad)]) == _NOT_COMPARABLE
    assert not out_bad.exists()

    # Discrimination guard: same manifest, in-corpus run => renders.
    inside = _run_record(tmp_path, "toy_inside.json", [1, 2], None)
    out_ok = tmp_path / "toy_ok.html"
    assert build_main(["--manifest", str(mpath), "--run", f"A={inside}",
                       "--media-ids", "1,2", "--out", str(out_ok)]) == 0
    assert "manifest identity: structural only" in out_ok.read_text()


def test_manifest_version_as_string_fails_closed(tmp_path: Path) -> None:
    """A stringly-typed version must not silently downgrade to the weaker mode.

    It is claimed as v3, so the gate holds it to v3: it either loads and anchors
    the digest, or it is refused. What it must never do is fall through to
    ``structural only`` and quietly drop the digest check.
    """
    from scripts.eval_harness.build_bakeoff_report import ComparabilityError, _expected_shas

    raw = json.loads(Path(_V3_MANIFEST).read_text())
    raw["manifest_version"] = "3"
    stringly = tmp_path / "stringly.json"
    stringly.write_text(json.dumps(raw))
    try:
        shas, mode = _expected_shas(str(stringly))
    except ComparabilityError as exc:
        assert "does not load as one" in str(exc)
    else:
        assert mode == "structural + manifest digest" and shas


def test_declared_v3_that_does_not_load_is_refused_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"manifest_version": 3, "entries": [{"media_id": "not-an-int"}]}))
    rec = _run_record(tmp_path, "any.json", [1], None)
    from scripts.eval_harness.build_bakeoff_report import main as build_main

    out = tmp_path / "never.html"
    rc = build_main(["--manifest", str(broken), "--run", f"A={rec}", "--media-ids", "1", "--out", str(out)])
    assert rc == _NOT_COMPARABLE
    assert "does not load as one" in capsys.readouterr().err  # diagnosed, not a traceback


def test_non_v3_manifest_falls_back_to_cross_run_agreement(tmp_path: Path) -> None:
    mpath, _ = _write_fixtures(tmp_path)  # toy manifest: no manifest_version
    a = _run_record(tmp_path, "a.json", [1, 2], "1" * 64)
    b_same = _run_record(tmp_path, "b_same.json", [1, 2], "1" * 64)
    b_diff = _run_record(tmp_path, "b_diff.json", [1, 2], "2" * 64)

    from scripts.eval_harness.build_bakeoff_report import main as build_main

    out_ok = tmp_path / "ok.html"
    assert build_main(["--manifest", str(mpath), "--run", f"A={a}", "--run", f"B={b_same}",
                       "--media-ids", "1,2", "--out", str(out_ok)]) == 0
    assert "manifest identity: structural only" in out_ok.read_text()

    # Discrimination guard: same code path, one disagreeing sha => fatal.
    out_bad = tmp_path / "bad.html"
    assert build_main(["--manifest", str(mpath), "--run", f"A={a}", "--run", f"B={b_diff}",
                       "--media-ids", "1,2", "--out", str(out_bad)]) == _NOT_COMPARABLE
    assert not out_bad.exists()
