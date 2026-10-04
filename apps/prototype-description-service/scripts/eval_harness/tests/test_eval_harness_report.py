"""FIR-11-S2R3-12 — report-layer detection coverage with entry-level stamps.

The scene report suite's unstamped fixtures take the refusal branch, so
PUBLIC rendering / determinism / redaction of a *present* detection
block is no longer exercised at this layer. Stamps live on entries, not
on a parent document: a document-level fill will not survive the
post-E1 resolver (FIR-11-S2R3-02).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.eval_harness.bakeoff as bakeoff
import scripts.eval_harness.build_bakeoff_report as build_bakeoff_report
from scripts.eval_harness.bakeoff import BakeoffClient, _stamp_stage_costs
from scripts.eval_harness.build_bakeoff_report import _format_durable_stage_costs
from scripts.eval_harness.cli import BoundedStallError
from scripts.eval_harness.cli import _extract_detection_boxes, _extract_identities
from scripts.eval_harness.manifest import GoldenManifest, ManifestError, ScoreInvariant, compute_corpus_coverage_gaps
from scripts.eval_harness.report import (
    Audience,
    ReportError,
    build_reports,
    build_score_verdict,
    score_run_record,
)

_TEST_MODEL_STAMPS = {
    "adapter": "seeded",
    "model_id": "seeded-fixtures",
    "model_version": "1",
    "prompt_version": "v1",
    "prompt_sha256": "f" * 64,
}

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

_LOCAL_PATH = "localwp/uploads/jane-doe-birthday.jpg"
_LOCAL_NAME = "Jane Doe Private"
_PUBLIC_PATH = "celebs01/obama-podium.jpg"
_PUBLIC_NAME = "Barack Obama"

# Default 3-item fixture: two scored faces + one failed item.
_DEFAULT_TP, _DEFAULT_FP, _DEFAULT_FN = 2, 0, 0
_LOCAL_TP = 2
# build_reports scores the full corpus once, then redacts for PUBLIC
# (report.py::build_reports docstring, VLM6-R3-03) — detection is never
# re-scored on a filtered population, so PUBLIC == LOCAL here (VLM6-DELTA-11).
_PUBLIC_TP = _LOCAL_TP


def _named_box(name: str | None, *, x: float = 0.5) -> dict:
    return {
        "x": x,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": _LINEAGE,
    }


def _stamp_entry(entry: dict, mode: str) -> dict:
    """Entry-level stamp only. Never writes a parent/document mode."""
    entry["annotation_mode"] = mode
    return entry


def _run_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice-pool.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example relaxes by a pool.",
                    "visual_facts": {"caption": "a person by a pool", "objects": ["pool", "person"]},
                    **_TEST_MODEL_STAMPS,
                    "cached": False,
                },
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 1,
                "error": None,
            },
            {
                "media_id": 2,
                "path": "mock_images/bob-beach.jpg",
                "describe": {
                    "alt_text_draft": "A man on a beach.",
                    "visual_facts": {"caption": "a man on a beach", "objects": ["beach"]},
                    **_TEST_MODEL_STAMPS,
                    "cached": True,
                },
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 1,
                "error": None,
            },
            {
                "media_id": 3,
                "path": "mock_images/glacier.jpg",
                "describe": None,
                "identities": [],
                "face_count": 0,
                "error": "timeout after 60s",
            },
        ],
    }


def _manifest_entries(*, mode: str | None = "exhaustive") -> list[dict]:
    entries = [
        {
            "path": "mock_images/alice-pool.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Alice Example")],
        },
        {
            "path": "mock_images/bob-beach.jpg",
            "media_id": 2,
            "face_count": 1,
            "present_identities": ["Bob Builder"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Bob Builder")],
        },
        {
            "path": "mock_images/glacier.jpg",
            "media_id": 3,
            "face_count": 0,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [],
        },
    ]
    if mode is not None:
        for entry in entries:
            _stamp_entry(entry, mode)
    return entries


def _audience_fixtures(*, mode: str | None = "exhaustive") -> tuple[dict, list[dict]]:
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": [
            {
                "media_id": 10,
                "path": _PUBLIC_PATH,
                "describe": {
                    "alt_text_draft": f"{_PUBLIC_NAME} at a podium.",
                    "visual_facts": {"objects": ["podium"]},
                    **_TEST_MODEL_STAMPS,
                    "cached": False,
                },
                "identities": [{"name": _PUBLIC_NAME, "unpositioned": True}],
                "face_count": 1,
                "error": None,
            },
            {
                "media_id": 20,
                "path": _LOCAL_PATH,
                "describe": {
                    "alt_text_draft": f"{_LOCAL_NAME} at a party.",
                    "visual_facts": {"objects": ["cake"]},
                    **_TEST_MODEL_STAMPS,
                    "cached": False,
                },
                "identities": [{"name": "Wrong Celebrity", "unpositioned": True}],
                "face_count": 1,
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": _PUBLIC_PATH,
            "media_id": 10,
            "face_count": 1,
            "present_identities": [_PUBLIC_NAME],
            "must_right": [_PUBLIC_NAME],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box(_PUBLIC_NAME)],
            "provenance": {
                "source": "celeb",
                "license": "public_domain",
                "publishable": True,
            },
        },
        {
            "path": _LOCAL_PATH,
            "media_id": 20,
            "face_count": 1,
            "present_identities": [_LOCAL_NAME],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box(_LOCAL_NAME)],
            "provenance": {
                "source": "localwp",
                "license": "consented",
                "publishable": False,
            },
        },
    ]
    if mode is not None:
        for entry in entries:
            _stamp_entry(entry, mode)
    return record, entries


def _detection_section(md: str) -> str:
    return md.split("## Face detection")[1].split("## Face identification")[0]


def _assert_scored_detection(det: dict, *, tp: int, fp: int, fn: int) -> None:
    assert det.get("refused") is not True
    assert "invariant" not in det
    assert det["tp"] == tp
    assert det["fp"] == fp
    assert det["fn"] == fn
    denom_p = tp + fp
    denom_r = tp + fn
    assert det["precision"] == (pytest.approx(tp / denom_p) if denom_p else None)
    assert det["recall"] == (pytest.approx(tp / denom_r) if denom_r else None)


def _assert_scored_detection_markdown(md: str, *, tp: int, fp: int, fn: int) -> None:
    section = _detection_section(md)
    assert "REFUSED" not in section
    prec = "null" if tp + fp == 0 else f"{tp / (tp + fp):.3f}"
    rec = "null" if tp + fn == 0 else f"{tp / (tp + fn):.3f}"
    assert f"- precision: {prec} recall: {rec} (tp={tp} fp={fp} fn={fn})" in section


def test_fixtures_stamp_entries_not_parent_document() -> None:
    """S2R3-12 / S2R3-02: a parent-level fill will evaporate when E1 lands."""
    entries = _manifest_entries()
    record, audience = _audience_fixtures()
    assert "annotation_mode" not in record
    assert "annotation_mode" not in record.get("provenance", {})
    for entry in (*entries, *audience):
        assert entry["annotation_mode"] == "exhaustive"
        assert entry.get("face_boxes") is not None
        assert len(entry["face_boxes"]) == entry["face_count"]


def test_score_run_record_emits_scored_detection_arithmetic() -> None:
    scored = score_run_record(_run_record(), _manifest_entries())
    _assert_scored_detection(
        scored["faces"]["detection"], tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN
    )
    assert scored["counts"] == {"total": 3, "scored": 2, "failed": 1}


def test_score_run_record_preserves_homogeneous_model_run_stamps() -> None:
    record = _run_record()
    decoding = {"temperature": 0, "seed": 17, "max_tokens_by_pass": {"caption": 512}}
    stamps = {
        "model_revision": "sha256:fixture-model",
        "seed": 17,
        "prompt_variant": "v2",
        "prompt_version": "v2",
        "prompt_sha256": "a" * 64,
        "task_version": "alt-text-v1",
        "decoding_contract": decoding,
    }
    for item in record["items"][:2]:
        item["describe"].update(stamps)
    record["provenance"].update(stamps)

    scored = score_run_record(record, _manifest_entries())
    model = scored["provenance"]["model"]

    assert model["model_revisions"] == ["sha256:fixture-model"]
    assert model["seeds"] == [17]
    assert model["prompt_versions"] == ["v2"]
    assert model["prompt_sha256s"] == ["a" * 64]
    assert model["task_versions"] == ["alt-text-v1"]
    assert model["decoding_contracts"] == [decoding]
    assert "attribution" not in model


def _otherwise_passing_verdict_input() -> dict:
    return {
        "counts": {"total": 5, "scored": 5, "failed": 0},
        "corpus": {},
        "provenance": {
            "manifest_sha256": "m" * 64,
            "model": {
                "adapters": ["fixture"],
                "model_ids": ["fixture-model"],
                "prompt_versions": ["v1"],
                "prompt_sha256s": ["f" * 64],
            },
        },
        "caption": {
            "must_right_defined_images": 5,
            "easy_wrong_defined_images": 5,
            "must_right_failed_images": 0,
            "insertion_rate": 0.0,
            "mean_gated_score": 1.0,
        },
        "faces": {
            "detection": {"precision": 1.0, "recall": 1.0},
            "identification": {
                "evaluated_images": 5,
                "precision": 1.0,
                "recall": 1.0,
                "wrong_names": [],
                "positional": {
                    "position_accuracy": 1.0,
                    "compared_images": 5,
                    "evaluable": True,
                },
            },
            "identity_ordering": {"positional_images": 5},
        },
        "placement": {"claims": 5, "accuracy": 1.0},
        "hallucination": {
            "images_with_traps": 5,
            "fabricated_fact_rate": 0.0,
            "fabricated_fact_rate_trapped": 0.0,
        },
    }


def test_score_verdict_requires_complete_producer_identity() -> None:
    attributed = _otherwise_passing_verdict_input()
    assert build_score_verdict(attributed)["verdict"] == "pass"

    unattributed = _otherwise_passing_verdict_input()
    unattributed["provenance"]["model"]["attribution"] = {
        "status": "unattributed",
        "missing_dimensions": ["adapter", "model", "prompt identity"],
    }
    verdict = build_score_verdict(unattributed)

    assert verdict["verdict"] == "not_ready"
    assert verdict["reasons"] == [
        "producer identity incomplete: missing adapter, model, prompt identity"
    ]


@pytest.mark.parametrize("setting", [{"seed": 7}, {"decoding_contract": {"temperature": 0}}])
def test_score_run_record_marks_settings_only_model_provenance_unattributed(setting: dict) -> None:
    record = _run_record()
    for item in record["items"][:2]:
        describe = item["describe"]
        for field in ("adapter", "model_id", "model_version", "prompt_version", "prompt_sha256"):
            describe.pop(field, None)
        describe.update(setting)

    report, markdown = build_reports(record, _manifest_entries())
    scored = json.loads(report)
    assert scored["counts"]["scored"] == 2
    assert scored["provenance"]["model"]["attribution"] == {
        "status": "unattributed",
        "missing_dimensions": ["adapter", "model", "prompt identity"],
    }
    assert "unattributed aggregate metrics**: missing adapter, model, prompt identity" in markdown
    assert "diagnostic only; report is not adoption-ready" in markdown
    assert any(
        reason == "producer identity incomplete: missing adapter, model, prompt identity"
        for reason in scored["verdict"]["reasons"]
    )


@pytest.mark.parametrize(
    ("fields", "missing"),
    [(("adapter",), "adapter"), (("model_id",), "model"),
     (("prompt_version", "prompt_sha256"), "prompt identity")],
)
def test_score_run_record_names_each_missing_identity(fields: tuple, missing: str) -> None:
    record = _run_record()
    for item in record["items"][:2]:
        for field in fields:
            item["describe"].pop(field)
    report, markdown = build_reports(record, _manifest_entries())
    assert json.loads(report)["provenance"]["model"]["attribution"] == {
        "status": "unattributed", "missing_dimensions": [missing],
    }
    assert f"unattributed aggregate metrics**: missing {missing}" in markdown


@pytest.mark.parametrize("declaration", [None, False, "true", 1])
def test_prompt_free_requires_explicit_boolean_run_declaration(declaration: object) -> None:
    record = _run_record()
    for item in record["items"][:2]:
        item["describe"].pop("prompt_version")
        item["describe"].pop("prompt_sha256")
        item["describe"]["prompt_variant"] = "v1"
    if declaration is not None:
        record["provenance"]["prompt_free"] = declaration
    scored = score_run_record(record, _manifest_entries())
    assert scored["provenance"]["model"]["attribution"] == {
        "status": "unattributed", "missing_dimensions": ["prompt identity"],
    }


def test_zero_rule_prompt_free_record_scores_and_builds_reports() -> None:
    from scripts.eval_harness.zero_rule_baseline import (
        build_zero_rule_run_record, load_held_out_manifest, stamped_entries,
    )

    manifest = load_held_out_manifest()
    record = build_zero_rule_run_record(manifest, started_at="t", head_sha=None)
    assert record["provenance"]["prompt_free"] is True
    entries = stamped_entries(manifest)
    scored = score_run_record(record, entries)
    assert scored["counts"]["scored"] == len(entries)
    assert scored["provenance"]["model"]["prompt_free_flags"] == [True]
    assert "attribution" not in scored["provenance"]["model"]
    report, markdown = build_reports(record, entries)
    assert json.loads(report)["counts"]["scored"] == len(entries)
    assert markdown

    record["provenance"].pop("prompt_free")
    report, markdown = build_reports(record, entries)
    assert json.loads(report)["provenance"]["model"]["attribution"] == {
        "status": "unattributed", "missing_dimensions": ["prompt identity"],
    }
    assert "unattributed aggregate metrics**: missing prompt identity" in markdown


@pytest.mark.parametrize("field", ["adapter", "model_id"])
def test_prompt_free_does_not_exempt_producer_identity(field: str) -> None:
    record = _run_record()
    record["provenance"]["prompt_free"] = True
    for item in record["items"][:2]:
        for missing in (field, "prompt_version", "prompt_sha256"):
            item["describe"].pop(missing)
    scored = score_run_record(record, _manifest_entries())
    assert scored["provenance"]["model"]["attribution"] == {
        "status": "unattributed",
        "missing_dimensions": ["adapter" if field == "adapter" else "model"],
    }


@pytest.mark.parametrize(
    ("field", "mixed_value"),
    [
        ("model_id", "other-model"),
        ("model_revision", "sha256:other-model"),
        ("seed", 42),
        ("prompt_sha256", "b" * 64),
        ("task_version", "alt-text-v2"),
        ("decoding_contract", {"temperature": 0.7, "seed": 17, "max_tokens_by_pass": {"caption": 512}}),
    ],
)
def test_score_run_record_refuses_mixed_model_or_run_stamps(field: str, mixed_value: object) -> None:
    record = _run_record()
    common = {
        "model_revision": "sha256:fixture-model",
        "seed": 17,
        "prompt_variant": "v2",
        "prompt_version": "v2",
        "prompt_sha256": "a" * 64,
        "task_version": "alt-text-v1",
        "decoding_contract": {"temperature": 0, "seed": 17, "max_tokens_by_pass": {"caption": 512}},
    }
    for item in record["items"][:2]:
        item["describe"].update(common)
    record["items"][1]["describe"][field] = mixed_value

    with pytest.raises(ReportError, match="refusing aggregate score"):
        score_run_record(record, _manifest_entries())


def test_bakeoff_stamps_measured_stage_costs_and_explicit_unknowns() -> None:
    record = {
        "provenance": {},
        "timing": {"cold_load_s": 3600.0, "warmup": {"elapsed_s": 60.0}},
        "items": [{"latency_s": 10.0}, {"latency_s": 5.0}],
    }
    _stamp_stage_costs(record, hourly_rate=3.6)

    costs = record["provenance"]["stage_costs"]
    assert costs["model_load"]["amount_usd"] == 3.6
    assert costs["scored_inference"]["amount_usd"] == 0.015
    assert costs["offline_report_scoring"]["status"] == "unknown"
    assert costs["offline_report_scoring"]["reason"] == "stage duration was not measured"

    unknown_rate_record = {"provenance": {}, "timing": {"warmup": {"elapsed_s": 5.0}}, "items": []}
    _stamp_stage_costs(unknown_rate_record, hourly_rate=None)
    assert unknown_rate_record["provenance"]["stage_costs"]["warmup"]["amount_usd"] is None
    assert (
        unknown_rate_record["provenance"]["stage_costs"]["warmup"]["reason"]
        == "operator hourly rate was not supplied"
    )


def test_bakeoff_main_persists_stage_costs_for_completed_and_aborted_records(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = SimpleNamespace(
        media_id=1,
        present_identities=[],
        easy_wrong=[],
        must_right=[],
        face_boxes=[],
    )
    manifest = SimpleNamespace(entries=[entry], roster=[])

    class StubClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run_configuration(self) -> dict:
            return {}

        def close(self) -> None:
            pass

    monkeypatch.setattr(bakeoff, "__file__", str(tmp_path / "bakeoff.py"))
    monkeypatch.setattr(bakeoff, "load_manifest", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(bakeoff, "BakeoffClient", StubClient)
    monkeypatch.setattr(bakeoff, "_head_sha", lambda: "0" * 40)
    monkeypatch.setattr(bakeoff, "prune_out_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(tmp_path))

    for outcome in ("completed", "aborted"):
        record = {
            "provenance": {},
            "items": [{"media_id": 1, "latency_s": 2.0, "error": None}],
        }

        def fake_fetch(*_args, _outcome=outcome, **_kwargs):
            if _outcome == "aborted":
                raise BoundedStallError("fixture stalled", record)
            return record

        monkeypatch.setattr(bakeoff, "fetch_run_record", fake_fetch)
        run_path = tmp_path / f"{outcome}.json"
        argv = [
            "--endpoint", "http://candidate",
            "--model-id", "fixture-model",
            "--manifest", str(tmp_path / "manifest.json"),
            "--out", str(run_path),
            "--warmup", "0",
            "--cold-load-s", "36",
            "--hourly-rate", "3.6",
            "--vram-sample-interval-s", "0",
        ]
        if outcome == "aborted":
            with pytest.raises(SystemExit):
                bakeoff.main(argv)
            run_path = run_path.with_name("aborted-aborted.json")
        else:
            bakeoff.main(argv)

        written_record = json.loads(run_path.read_text())
        assert written_record["provenance"]["stage_costs"]["model_load"]["amount_usd"] == 0.036


def test_bakeoff_stamps_run_defining_revision_seed_prompt_and_decoding() -> None:
    client = BakeoffClient(
        "http://candidate",
        model_id="candidate/model",
        model_revision="sha256:checkpoint",
        seed=17,
    )
    try:
        provenance = client.run_configuration()
    finally:
        client.close()

    assert provenance["model_revision"] == "sha256:checkpoint"
    assert provenance["model_revision_source"] == "operator_supplied"
    assert provenance["seed"] == 17
    assert provenance["prompt_version"] == "v1"
    assert len(provenance["prompt_sha256"]) == 64
    assert provenance["task_version"] == "alt-text-v1"
    assert provenance["decoding_contract"]["temperature"] == 0
    assert provenance["decoding_contract"]["seed"] == 17


def test_bakeoff_report_surfaces_durable_stage_costs() -> None:
    formatted = _format_durable_stage_costs(
        {
            "candidate": {
                "stage_costs": {
                    "model_load": {"status": "estimated", "amount_usd": 0.25},
                    "inference": {"status": "unknown", "amount_usd": None},
                }
            }
        }
    )

    assert formatted == "candidate [inference=unknown, model_load=$0.250000]"


@pytest.mark.parametrize("saved_costs", [True, False])
def test_bakeoff_report_main_renders_saved_stage_costs(tmp_path, saved_costs: bool) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"entries": [{"media_id": 7, "path": "images/sample.jpg"}]}))
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "provenance": {
                    "stage_costs": {
                        "model_load": {"status": "estimated", "amount_usd": 0.25},
                        "inference": {"status": "unknown", "amount_usd": None},
                    }
                } if saved_costs else {},
                "items": [{"media_id": 7, "describe": {"alt_text_draft": "A sample caption."}}],
            }
        )
    )
    report_path = tmp_path / "report.html"

    exit_code = build_bakeoff_report.main(
        [
            "--manifest", str(manifest_path),
            "--run", f"candidate={run_path}",
            "--out", str(report_path),
            "--media-ids", "7",
        ]
    )

    assert exit_code == 0
    report_html = report_path.read_text()
    if saved_costs:
        assert "durable stage costs: candidate [inference=unknown, model_load=$0.250000]" in report_html
    else:
        assert "durable stage costs:" not in report_html


def test_live_score_stamps_mapping_corpus_coverage_audit() -> None:
    """Live reports must carry honest registry counts (AUDIT-07 / EVAL-23)."""
    entries = _manifest_entries()
    gaps = compute_corpus_coverage_gaps(entries)
    assert gaps["face_boxes"]["populated"] == 2
    assert gaps["spatial_facts"]["populated"] == 0

    scored = score_run_record(_run_record(), entries)
    stamped = scored["provenance"]["coverage_gaps"]
    assert stamped == gaps
    assert stamped["reference_facts"]["below_threshold"] is True
    assert stamped["demographic_cohort"]["pi_zero"] is True


def test_markdown_surfaces_live_corpus_coverage_audit() -> None:
    """Operators must see metric backing gaps without opening JSON (AUDIT-07)."""
    _json_doc, markdown = build_reports(_run_record(), _manifest_entries())
    assert "## Corpus coverage audit" in markdown
    assert "reference_facts=0/3" in markdown
    assert "face_boxes=2/3" in markdown
    assert "below_threshold=true" in markdown


def test_live_score_labels_offline_proxy_verdict() -> None:
    """Offline score envelopes must not masquerade as product validation (EVAL-22)."""
    record, entries = _run_record(), _manifest_entries()
    scored = score_run_record(record, entries)
    assert scored["evaluation_status"] == "unvalidated_proxy"
    assert scored["provenance"]["evaluation_status"] == "unvalidated_proxy"
    assert scored["verdict"]["evaluation_status"] == "unvalidated_proxy"
    _json_doc, markdown = build_reports(record, entries)
    assert "- evaluation_status: `unvalidated_proxy`" in markdown
    public_json, _public_markdown = build_reports(record, entries, audience=Audience.PUBLIC)
    public = json.loads(public_json)
    assert public["evaluation_status"] == "unvalidated_proxy"
    assert public["provenance"]["evaluation_status"] == "unvalidated_proxy"


def test_build_reports_scored_detection_is_deterministic() -> None:
    record, entries = _run_record(), _manifest_entries()
    json_a, md_a = build_reports(record, entries)
    json_b, md_b = build_reports(record, entries)
    assert json_a == json_b
    assert md_a == md_b
    _assert_scored_detection(
        json.loads(json_a)["faces"]["detection"],
        tp=_DEFAULT_TP,
        fp=_DEFAULT_FP,
        fn=_DEFAULT_FN,
    )
    _assert_scored_detection_markdown(md_a, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)


def test_local_matches_default_audience_with_scored_detection() -> None:
    record, entries = _run_record(), _manifest_entries()
    default_json, default_md = build_reports(record, entries)
    local_json, local_md = build_reports(record, entries, audience=Audience.LOCAL)
    assert default_json == local_json
    assert default_md == local_md
    _assert_scored_detection(
        json.loads(local_json)["faces"]["detection"],
        tp=_DEFAULT_TP,
        fp=_DEFAULT_FP,
        fn=_DEFAULT_FN,
    )


def test_public_audience_renders_scored_detection() -> None:
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=_PUBLIC_TP, fp=0, fn=0)
    _assert_scored_detection_markdown(md, tp=_PUBLIC_TP, fp=0, fn=0)
    media_ids = {row["media_id"] for row in scored["per_image"]}
    assert media_ids == {10}


def test_local_audience_renders_full_scored_detection() -> None:
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.LOCAL)
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=_LOCAL_TP, fp=0, fn=0)
    _assert_scored_detection_markdown(md, tp=_LOCAL_TP, fp=0, fn=0)
    assert {row["media_id"] for row in scored["per_image"]} == {10, 20}


def test_public_redaction_keeps_scored_detection_and_withholds_private() -> None:
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=_PUBLIC_TP, fp=0, fn=0)
    # VLM6-DELTA-11: redaction block gained mode/unknown_media_items/
    # withheld_manifest_entries/total_manifest_entries/note fields
    # (report.py::_redact_caption_report_for_public, ~line 1026).
    assert scored["redaction"] == {
        "audience": "public",
        "mode": "post_score_redact_caption_report",
        "withheld_items": 1,
        "unknown_media_items": 0,
        "withheld_manifest_entries": 1,
        "total_items": 2,
        "total_manifest_entries": 2,
        "note": (
            "Aggregates scored on the full corpus (roster/rubric intact); "
            "identity-bearing detail lists and non-publishable per_image rows "
            "stripped. unknown_media_items are corpus-integrity failures, not privacy."
        ),
    }
    assert "withheld 1 of 2 items" in md
    for blob in (json_doc, md):
        assert _LOCAL_PATH not in blob
        assert _LOCAL_NAME not in blob
        assert "Wrong Celebrity" not in blob
    assert _PUBLIC_NAME in json_doc
    # RV4-05: PUBLIC per_image "path" is always the opaque media_id:N token —
    # never an operator basename/path, even for a publishable item
    # (_public_free_text_value, report.py ~line 792). VLM6-DELTA-11.
    assert _PUBLIC_PATH not in json_doc
    assert {row["media_id"] for row in scored["per_image"]} == {10}


def test_public_scored_detection_is_deterministic() -> None:
    record, entries = _audience_fixtures()
    a_json, a_md = build_reports(record, entries, audience=Audience.PUBLIC)
    b_json, b_md = build_reports(record, entries, audience=Audience.PUBLIC)
    assert a_json == b_json
    assert a_md == b_md
    _assert_scored_detection(json.loads(a_json)["faces"]["detection"], tp=_PUBLIC_TP, fp=0, fn=0)
    _assert_scored_detection_markdown(a_md, tp=_PUBLIC_TP, fp=0, fn=0)


def test_overshoot_markdown_names_fp() -> None:
    """pred=3 labeled=1 must surface tp=1 fp=2, not a refused block."""
    record = {
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
                    "alt_text_draft": "Alice Example.",
                    "visual_facts": {"objects": []},
                    **_TEST_MODEL_STAMPS,
                },
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 3,
                "error": None,
            }
        ],
    }
    entry = _stamp_entry(
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Alice Example")],
        },
        "exhaustive",
    )
    json_doc, md = build_reports(record, [entry])
    _assert_scored_detection(json.loads(json_doc)["faces"]["detection"], tp=1, fp=2, fn=0)
    _assert_scored_detection_markdown(md, tp=1, fp=2, fn=0)


def test_stranger_faces_are_not_detection_fps() -> None:
    record = {
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
                "path": "mock_images/group.jpg",
                "describe": {
                    "alt_text_draft": "Muted and friends.",
                    "visual_facts": {"objects": []},
                    **_TEST_MODEL_STAMPS,
                },
                "identities": [{"name": "Muted Yarrow", "unpositioned": True}],
                "face_count": 3,
                "error": None,
            }
        ],
    }
    entry = _stamp_entry(
        {
            "path": "mock_images/group.jpg",
            "media_id": 1,
            "face_count": 3,
            "present_identities": ["Muted Yarrow"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                _named_box("Muted Yarrow"),
                _named_box(None, x=0.2),
                _named_box(None, x=0.8),
            ],
        },
        "exhaustive",
    )
    json_doc, md = build_reports(record, [entry])
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=3, fp=0, fn=0)
    _assert_scored_detection_markdown(md, tp=3, fp=0, fn=0)
    assert scored["faces"]["identification"]["true_rejections"] == 1


def test_strict_detection_uses_wire_boxes_for_unrecognized_faces() -> None:
    confirmed_bbox = {"x": 40, "y": 25, "width": 20, "height": 30}
    unrecognized_bbox = {"x": 10, "y": 25, "width": 20, "height": 30}
    wire_rows = [
        {
            "media_id": 1,
            "cluster_label": "Alice Example",
            "is_auto_label": False,
            "bbox": confirmed_bbox,
        },
        {
            "media_id": 1,
            "cluster_label": None,
            "is_auto_label": False,
            "bbox": unrecognized_bbox,
        },
    ]
    identities, face_count, _ordering = _extract_identities(
        wire_rows, 1, image_width=100, image_height=100
    )
    detection_boxes = _extract_detection_boxes(wire_rows, 1)
    assert [identity["name"] for identity in identities] == ["Alice Example"]
    assert face_count == 2
    assert detection_boxes == [confirmed_bbox, unrecognized_bbox]
    record = {
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
                "path": "mock_images/group.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example and a friend.",
                    "visual_facts": {"objects": []},
                    **_TEST_MODEL_STAMPS,
                },
                "identities": identities,
                "detection_boxes": detection_boxes,
                "face_count": face_count,
                "image_width": 100,
                "image_height": 100,
                "error": None,
            }
        ],
    }
    entry = _stamp_entry(
        {
            "path": "mock_images/group.jpg",
            "media_id": 1,
            "face_count": 2,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Alice Example"), _named_box(None, x=0.2)],
        },
        "exhaustive",
    )

    adjudication_records = []
    for box_index, box in enumerate(entry["face_boxes"]):
        record_id = f"report-review-{box_index}"
        box["adjudication_source"] = f"human_adjudicated:{record_id}"
        adjudication_records.append(
            {
                "record_id": record_id,
                "media_id": 1,
                "box_index": box_index,
                "reviewer_id": "test-reviewer",
                "reviewer_kind": "human",
                "review_method": "independent_blind_review",
                "decision": "confirmed",
                "reviewed_at": "2026-08-15T00:00:00Z",
            }
        )
    run_manifest_entry = {key: value for key, value in entry.items() if key != "annotation_mode"}
    run_manifest_entry["sha256"] = "a" * 64
    run_manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 3,
            "annotation_mode": "exhaustive",
            "iou_threshold": 0.5,
            "roster": ["Alice Example"],
            "entries": [run_manifest_entry],
            "adjudication_records": adjudication_records,
        }
    ).model_dump()

    try:
        scored = score_run_record(record, [entry], run_manifest=run_manifest)
    except ManifestError as exc:
        pytest.fail(f"strict detection refused mixed recognized/unrecognized faces: {exc}", pytrace=False)

    detection = scored["faces"]["detection"]
    _assert_scored_detection(detection, tp=2, fp=0, fn=0)
    assert detection["tp"] + detection["fp"] == 2
    assert len(record["items"][0]["identities"]) == 1


def test_wrong_name_markdown_alongside_scored_detection() -> None:
    _json_doc, md = build_reports(_run_record(), _manifest_entries())
    _assert_scored_detection_markdown(md, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)
    assert "mock_images/bob-beach.jpg" in md
    assert "Alice Example" in md
    assert "Wrong-name" in md or "wrong-name" in md


def test_json_and_markdown_detection_agree() -> None:
    scored = score_run_record(_run_record(), _manifest_entries())
    json_doc, md = build_reports(_run_record(), _manifest_entries())
    built = json.loads(json_doc)["faces"]["detection"]
    assert built == scored["faces"]["detection"]
    _assert_scored_detection(built, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)
    _assert_scored_detection_markdown(md, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)


def test_caption_quality_metrics_ignore_identity_spelling() -> None:
    def _score_identity_variant(present_identity: str, caption: str, objects: list[str]) -> tuple[tuple, tuple, tuple]:
        record = {
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
                    "path": "mock_images/cake.jpg",
                    "describe": {
                        "alt_text_draft": caption,
                        "visual_facts": {"objects": objects},
                        **_TEST_MODEL_STAMPS,
                        "cached": False,
                    },
                    "identities": [{"name": present_identity, "unpositioned": True}],
                    "face_count": 1,
                    "error": None,
                }
            ],
        }
        entry = _stamp_entry(
            {
                "path": "mock_images/cake.jpg",
                "media_id": 1,
                "face_count": 1,
                "present_identities": [present_identity],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [_named_box(present_identity)],
            },
            "exhaustive",
        )
        scored = score_run_record(record, [entry])
        per_image = scored["per_image"][0]
        return (
            (
                per_image["fkre"],
                per_image["repetition_ratio"],
                per_image["tag_coverage"],
            ),
            (
                scored["quality"]["mean_fkre"],
                scored["quality"]["mean_repetition_ratio"],
                scored["quality"]["mean_tag_coverage"],
            ),
            (
                per_image["inserted_identities"],
                per_image["missing_identities"],
                per_image["gated_score"],
            ),
        )

    real_style = _score_identity_variant(
        "Alexandria Cunningham",
        "Alexandria Cunningham smiles while Alexandria Cunningham holds a cake.",
        ["Alexandria", "Cunningham", "birthday cake"],
    )
    pseudonym = _score_identity_variant(
        "Nimbus",
        "Nimbus smiles while Nimbus holds a cake.",
        ["Nimbus", "birthday cake"],
    )

    expected_quality = (42.62, 0.1429, 0.0)
    assert pseudonym[0] == real_style[0] == expected_quality
    assert pseudonym[1] == real_style[1] == expected_quality
    assert real_style[2] == (["Alexandria Cunningham"], [], 1.0)
    assert pseudonym[2] == (["Nimbus"], [], 1.0)

    mismatched_roster = _score_identity_variant(
        "Nimbus",
        "Alexandria Cunningham smiles while Alexandria Cunningham holds a cake.",
        ["Alexandria", "Cunningham", "birthday cake"],
    )
    assert mismatched_roster[2] == ([], ["Nimbus"], 0.0)


def test_unstamped_entries_refuse_missing_mode() -> None:
    """Subject is the missing-stamp refusal — leave unstamped on purpose."""
    json_doc, md = build_reports(_run_record(), _manifest_entries(mode=None))
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE
    assert det["tp"] is None
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_requires_annotation_mode): "
        "detection P/R is not computed without a resolved annotation_mode; "
        "omission is not exhaustive"
    ) in section


def test_roster_only_stamp_refuses_detection() -> None:
    """Subject is the roster_only refusal — stamp the restrictive mode."""
    json_doc, md = build_reports(_run_record(), _manifest_entries(mode="roster_only"))
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert det["tp"] is None
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_refuses_roster_only): "
        "detection P/R is not computed unless annotation_mode is exhaustive"
    ) in section


def test_markdown_names_refused_detection_explanation_literally() -> None:
    """S2R3-11: pin the published sentence, not the production constant.

    Mutating the explanation to 'detection scored normally; refusal is
    cosmetic' must fail this pin. Importing DETECTION_REFUSED_EXPLANATION
    or REFUSAL_EXPLANATIONS would stay green.
    """
    _json_doc, md = build_reports(_run_record(), _manifest_entries(mode="roster_only"))
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_refuses_roster_only): "
        "detection P/R is not computed unless annotation_mode is exhaustive"
    ) in section
    assert "detection scored normally" not in section
    assert "refusal is cosmetic" not in section
    assert "used anyway" not in section
    assert "zero scored observations" not in section
    assert "precision: null" not in section


def test_all_failed_items_refuse_empty_observations() -> None:
    """Stamped exhaustive still refuses: zero scored observations, not missing mode."""
    record = _run_record()
    for item in record["items"]:
        item["error"] = "boom"
    json_doc, md = build_reports(record, _manifest_entries())
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_EMPTY_OBSERVATIONS
    assert det["precision"] is None
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_refuses_empty_observations): "
        "detection P/R is not computed from zero scored observations"
    ) in section
    assert json.loads(json_doc)["counts"]["scored"] == 0
