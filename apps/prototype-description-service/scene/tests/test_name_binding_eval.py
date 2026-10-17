"""DESCBAKE-1 B3: offline name/phrase-binding evaluator (IDWEAVE L13 wrong-binding ledger).

Pure, offline checks over precomputed proposals. Each test names the behaviour it pins;
prior attempted paths (embedding similarity, set equality, case-sensitive scrubbing,
ignore-lists, score-time manifest swaps, pseudonymisation) are each refused by a test below.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

import scripts.eval_harness.name_binding_eval as nbe

APP_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = APP_ROOT / "scripts" / "eval_harness" / "name_binding_example.json"
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def _image(
    image_id="img-1",
    *,
    phrases=("ph-left", "ph-right"),
    required=("alice", "bob"),
    allowed=(),
    prohibited=("mallory",),
    gold=None,
):
    if gold is None:
        gold = [("ph-left", "alice"), ("ph-right", "bob")]
    return {
        "image_id": image_id,
        "source": {
            "anonymous_base_digest": DIGEST,
            "generation_id": "gen-unit",
            "reweave_id": "reweave-unit",
        },
        "phrases": list(phrases),
        "identity_roles": {
            "required": list(required),
            "allowed": list(allowed),
            "prohibited": list(prohibited),
        },
        "gold_bindings": [{"phrase_id": p, "person_id": q} for p, q in gold],
    }


def _pred(image_id="img-1", arm_id="arm-a", bindings=(), digest=DIGEST):
    return {
        "arm_id": arm_id,
        "image_id": image_id,
        "source_anonymous_base_digest": digest,
        "source_generation_id": "gen-unit",
        "source_reweave_id": "reweave-unit",
        "bindings": [{"phrase_id": p, "person_id": q} for p, q in bindings],
    }


def _fixture(**overrides):
    payload = {
        "schema": "name_binding_eval/v2",
        "fixture_id": "unit-fixture",
        "arm_ids": ["arm-a"],
        "frozen_images": [_image()],
        "predictions": [],
    }
    payload.update(overrides)
    return payload


def _run(payload):
    return nbe.evaluate_bytes(json.dumps(payload).encode())


def _arm(report, arm_id="arm-a"):
    return report["arms"][arm_id]


def _outcome_counts(**expected):
    base = {"correct": 0, "wrong_person": 0, "wrong_phrase": 0, "abstained": 0, "missing_record": 0}
    base.update(expected)
    return base


def test_schema_identifiers_are_versioned():
    assert nbe.INPUT_SCHEMA == "name_binding_eval/v2"
    assert nbe.REPORT_SCHEMA == "name_binding_eval_report/v2"


def test_role_swapped_names_are_wrong_person_and_not_hidden_by_set_equality():
    payload = _fixture(predictions=[_pred(bindings=[("ph-left", "bob"), ("ph-right", "alice")])])
    gold_people = {b["person_id"] for b in payload["frozen_images"][0]["gold_bindings"]}
    pred_people = {b["person_id"] for b in payload["predictions"][0]["bindings"]}
    # A set-equality scorer would call this correct: the same two people appear on both sides.
    assert gold_people == pred_people

    arm = _arm(_run(payload))
    assert arm["gold_outcome_counts"] == _outcome_counts(wrong_person=2)
    assert arm["misattributed_identity_bindings"] == 2
    rows = arm["image_ledger"][0]["gold_outcomes"]
    assert {(r["phrase_id"], r["predicted_person_id"], r["misattributed_to_phrase"]) for r in rows} == {
        ("ph-left", "bob", "ph-right"),
        ("ph-right", "alice", "ph-left"),
    }


def test_same_name_on_a_different_phrase_is_a_wrong_binding_not_a_correct_one():
    payload = _fixture(predictions=[_pred(bindings=[("ph-left", "alice"), ("ph-right", "alice")])])
    arm = _arm(_run(payload))
    assert arm["gold_outcome_counts"] == _outcome_counts(correct=1, wrong_person=1)
    assert arm["misattributed_identity_bindings"] == 1


def test_identity_on_the_other_phrase_with_gold_phrase_left_empty_is_wrong_phrase():
    payload = _fixture(predictions=[_pred(bindings=[("ph-right", "alice")])])
    arm = _arm(_run(payload))
    assert arm["gold_outcome_counts"] == _outcome_counts(wrong_person=1, wrong_phrase=1)
    rows = {r["phrase_id"]: r["outcome"] for r in arm["image_ledger"][0]["gold_outcomes"]}
    assert rows == {"ph-left": "wrong_phrase", "ph-right": "wrong_person"}


def test_prohibited_name_is_an_addition_and_never_a_correct_binding():
    payload = _fixture(predictions=[_pred(bindings=[("ph-left", "alice"), ("ph-right", "mallory")])])
    arm = _arm(_run(payload))
    assert arm["prohibited_name_additions"] == 1
    assert arm["prohibited_name_addition_rate"] == 1.0
    assert arm["gold_outcome_counts"] == _outcome_counts(correct=1, wrong_person=1)
    assert arm["misattributed_identity_bindings"] == 0


def test_missing_arm_image_record_is_explicit_and_never_counted_as_success():
    payload = _fixture(
        frozen_images=[_image("img-1"), _image("img-2")],
        predictions=[_pred("img-1", bindings=[("ph-left", "alice"), ("ph-right", "bob")])],
    )
    arm = _arm(_run(payload))
    assert arm["status"] == "partial"
    assert arm["scored_image_count"] == 1
    assert arm["missing_image_count"] == 1
    assert arm["coverage"] == 0.5
    assert arm["gold_outcome_counts"] == _outcome_counts(correct=2, missing_record=2)
    # Denominator is the frozen gold set (4 bindings), so the missing image dilutes recall.
    assert arm["gold_outcome_rates"]["correct"] == 0.5
    statuses = [row["record_status"] for row in arm["image_ledger"]]
    assert statuses == ["scored", "missing"]


def test_arm_without_any_record_reports_no_rates_rather_than_zero():
    arm = _arm(_run(_fixture()))
    assert arm["status"] == "no_records"
    assert arm["gold_outcome_counts"] == _outcome_counts(missing_record=2)
    assert arm["gold_outcome_rates"] is None


def test_all_abstain_is_explicit_abstention_with_zero_wrong_bindings():
    arm = _arm(_run(_fixture(predictions=[_pred(bindings=[])])))
    assert arm["gold_outcome_counts"] == _outcome_counts(abstained=2)
    assert arm["gold_outcome_rates"]["abstained"] == 1.0
    # The record exists and says "no bindings": zero correct is a measured zero, not unknown.
    assert arm["gold_outcome_rates"]["correct"] == 0.0
    assert arm["all_abstain_images"] == 1
    assert arm["all_abstain_image_rate"] == 1.0
    assert arm["required_identity_omissions"] == 2


def test_required_omission_counts_only_identities_never_named_anywhere():
    arm = _arm(_run(_fixture(predictions=[_pred(bindings=[("ph-right", "alice")])])))
    # alice is named (on the wrong phrase), so she is not omitted; bob is never named.
    assert arm["required_identity_omissions"] == 1
    assert arm["required_identity_count"] == 2


def test_denominator_is_frozen_gold_bindings_not_predicted_bindings():
    arm = _arm(_run(_fixture(predictions=[_pred(bindings=[("ph-left", "alice")])])))
    assert arm["gold_binding_count"] == 2
    assert arm["gold_outcome_rates"]["correct"] == 0.5
    assert arm["gold_outcome_counts"] == _outcome_counts(correct=1, abstained=1)


def test_empty_frozen_image_list_is_refused():
    with pytest.raises(nbe.NameBindingEvalError, match="frozen_images"):
        _run(_fixture(frozen_images=[]))


def test_empty_arm_list_is_refused():
    with pytest.raises(nbe.NameBindingEvalError, match="arm_ids"):
        _run(_fixture(arm_ids=[]))


def test_empty_gold_gives_none_rates_and_keeps_unbound_predictions_visible():
    payload = _fixture(
        frozen_images=[_image("img-1", required=(), allowed=("alice",), gold=[])],
        predictions=[_pred(bindings=[("ph-left", "alice")])],
    )
    arm = _arm(_run(payload))
    assert arm["gold_binding_count"] == 0
    assert arm["gold_outcome_rates"] is None
    assert arm["unbound_phrase_bindings"] == 1


def test_duplicate_arm_image_record_is_refused():
    payload = _fixture(predictions=[_pred(bindings=[]), _pred(bindings=[])])
    with pytest.raises(nbe.NameBindingEvalError, match="duplicate"):
        _run(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["predictions"].append(_pred(image_id="img-9")), "unknown image_id"),
        (lambda p: p["predictions"].append(_pred(arm_id="arm-z")), "unknown arm_id"),
        (lambda p: p["predictions"].append(_pred(bindings=[("ph-nope", "alice")])), "unknown phrase_id"),
        (lambda p: p["predictions"].append(_pred(bindings=[("PH-LEFT", "alice")])), "unknown phrase_id"),
        (lambda p: p["predictions"].append(_pred(bindings=[("ph-left", "carol")])), "undeclared person_id"),
        (
            lambda p: p["predictions"].append(_pred(bindings=[("ph-left", "alice"), ("ph-left", "bob")])),
            "duplicate phrase_id",
        ),
        (lambda p: p["predictions"].append(_pred(digest=OTHER_DIGEST)), "source_anonymous_base_digest"),
        (
            lambda p: p["frozen_images"][0]["gold_bindings"].append({"phrase_id": "ph-x", "person_id": "alice"}),
            "unknown phrase_id",
        ),
        (
            lambda p: p["frozen_images"][0]["identity_roles"]["prohibited"].append("alice"),
            "overlap",
        ),
        (
            lambda p: p["frozen_images"][0]["gold_bindings"].pop(),
            "required person without gold",
        ),
    ],
)
def test_unknown_or_inconsistent_references_are_refused(mutate, message):
    payload = _fixture()
    mutate(payload)
    with pytest.raises(nbe.NameBindingEvalError, match=message):
        _run(payload)


def test_source_digest_mismatch_is_refused_not_rederived_at_score_time():
    payload = _fixture(predictions=[_pred(bindings=[("ph-left", "alice")], digest=OTHER_DIGEST)])
    with pytest.raises(nbe.NameBindingEvalError, match="source_anonymous_base_digest"):
        _run(payload)


@pytest.mark.parametrize(
    "predictions",
    [
        [],
        [_pred(bindings=[("ph-left", "alice"), ("ph-right", "bob")])],
        [_pred(bindings=[])],
        [_pred(bindings=[("ph-left", "bob"), ("ph-right", "alice")])],
        [_pred(bindings=[("ph-right", "alice")])],
        [_pred(bindings=[("ph-left", "alice"), ("ph-right", "mallory")])],
    ],
)
def test_gold_outcomes_partition_the_frozen_gold_denominator(predictions):
    arm = _arm(_run(_fixture(predictions=predictions)))
    assert sum(arm["gold_outcome_counts"].values()) == arm["gold_binding_count"] == 2


def test_binding_order_is_not_evidence():
    a = _run(_fixture(predictions=[_pred(bindings=[("ph-left", "alice"), ("ph-right", "bob")])]))
    b = _run(_fixture(predictions=[_pred(bindings=[("ph-right", "bob"), ("ph-left", "alice")])]))
    assert a["arms"] == b["arms"]


def test_report_carries_input_digest_source_provenance_and_no_ranking():
    raw = json.dumps(_fixture(predictions=[_pred(bindings=[("ph-left", "alice")])])).encode()
    report = nbe.evaluate_bytes(raw)
    assert report["schema"] == nbe.REPORT_SCHEMA
    assert report["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["image_sources"] == {
        "img-1": {
            "anonymous_base_digest": DIGEST,
            "generation_id": "gen-unit",
            "reweave_id": "reweave-unit",
        }
    }
    assert report["ranking"] is None


def test_cli_writes_report_for_valid_input(tmp_path):
    inp = tmp_path / "in.json"
    raw = json.dumps(_fixture(predictions=[_pred(bindings=[("ph-left", "alice")])])).encode()
    inp.write_bytes(raw)
    out = tmp_path / "report.json"

    rc = nbe.main([str(inp), "--output", str(out)])

    assert rc == 0
    report = json.loads(out.read_text())
    assert report["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["ranking"] is None


def test_cli_refuses_invalid_input_without_writing_output(tmp_path, capsys):
    inp = tmp_path / "bad.json"
    inp.write_text(json.dumps(_fixture(frozen_images=[])))
    out = tmp_path / "report.json"

    rc = nbe.main([str(inp), "--output", str(out)])

    assert rc == nbe.EXIT_INVALID_INPUT
    assert not out.exists()
    assert "frozen_images" in capsys.readouterr().err


def test_committed_example_validates_and_scores_offline():
    fixture = json.loads(EXAMPLE.read_text())
    report = nbe.evaluate_file(EXAMPLE)
    assert report["schema"] == nbe.REPORT_SCHEMA
    assert report["fixture_id"] == fixture["fixture_id"]
    assert report["frozen_image_count"] == len(fixture["frozen_images"])
    assert set(report["arms"]) == set(fixture["arm_ids"])
    assert report["ranking"] is None


def test_module_imports_no_network_model_client_or_similarity_library():
    tree = ast.parse(Path(nbe.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "socket",
        "urllib",
        "http",
        "httpx",
        "requests",
        "aiohttp",
        "anthropic",
        "openai",
        "difflib",
        "rapidfuzz",
        "sentence_transformers",
    }
    assert not imported & forbidden


def _per_image_fixture():
    """Synthetic proposals: local phrase IDs may recur in independently frozen captions."""
    payload = _fixture()
    payload["schema"] = "name_binding_eval/v2"
    payload.pop("source", None)
    payload["frozen_images"] = []
    payload["predictions"] = []
    for number, digest in ((1, DIGEST), (2, OTHER_DIGEST)):
        image = _image(f"img-{number}", phrases=("ph-local",), required=("alice",), gold=[("ph-local", "alice")])
        source = {
            "anonymous_base_digest": digest,
            "generation_id": f"synthetic-gen-{number}",
            "reweave_id": f"synthetic-reweave-{number}",
        }
        image["source"] = source
        payload["frozen_images"].append(image)
        prediction = _pred(image["image_id"], bindings=[("ph-local", "alice")], digest=digest)
        prediction["source_generation_id"] = source["generation_id"]
        prediction["source_reweave_id"] = source["reweave_id"]
        payload["predictions"].append(prediction)
    return payload


def test_independent_image_lineage_accepts_distinct_bases_with_reused_local_phrase_ids():
    payload = _per_image_fixture()
    report = _run(payload)
    assert _arm(report)["gold_outcome_counts"] == _outcome_counts(correct=2)
    assert _arm(report)["coverage"] == 1
    assert report["image_sources"] == {image["image_id"]: image["source"] for image in payload["frozen_images"]}
    assert "source" not in report  # No batch value is presented as an individual caption digest.


@pytest.mark.parametrize("field", ["anonymous_base_digest", "generation_id", "reweave_id"])
def test_cross_image_lineage_field_swap_is_refused_even_when_phrase_and_person_match(field):
    payload = _per_image_fixture()
    payload["predictions"][1][f"source_{field}"] = payload["frozen_images"][0]["source"][field]
    with pytest.raises(nbe.NameBindingEvalError, match=f"source_{field} does not match.*img-2"):
        _run(payload)


def test_entire_cross_image_source_swap_is_refused():
    payload = _per_image_fixture()
    for field, value in payload["frozen_images"][0]["source"].items():
        payload["predictions"][1][f"source_{field}"] = value
    with pytest.raises(nbe.NameBindingEvalError, match="source_anonymous_base_digest does not match.*img-2"):
        _run(payload)


def test_legacy_fixture_global_lineage_is_refused_instead_of_silently_trusted():
    payload = _per_image_fixture()
    payload["schema"] = "name_binding_eval/v1"
    payload["source"] = {
        "anonymous_base_digest": DIGEST,
        "generation_id": "gen-unit",
        "reweave_id": "reweave-unit",
    }
    for image in payload["frozen_images"]:
        image.pop("source", None)
    for prediction in payload["predictions"]:
        prediction["source_anonymous_base_digest"] = DIGEST
        prediction.pop("source_generation_id", None)
        prediction.pop("source_reweave_id", None)
    with pytest.raises(nbe.NameBindingEvalError, match="input schema violation"):
        _run(payload)


@pytest.mark.parametrize("field", ["gold_bindings", "bindings"])
def test_omitted_evidence_is_refused_not_converted_to_negative_gold_or_abstention(field):
    payload = _fixture(
        frozen_images=[_image(required=(), allowed=("alice",), gold=[])],
        predictions=[_pred(bindings=[])],
    )
    record = payload["frozen_images"][0] if field == "gold_bindings" else payload["predictions"][0]
    del record[field]
    with pytest.raises(nbe.NameBindingEvalError, match=field):
        _run(payload)


def test_explicit_negative_gold_and_empty_prediction_remain_measured():
    arm = _arm(_run(_fixture(frozen_images=[_image(required=(), gold=[])], predictions=[_pred(bindings=[])])))
    assert arm["status"] == "complete"
    assert arm["coverage"] == 1
    assert arm["gold_binding_count"] == 0
    assert arm["gold_outcome_rates"] is None
    assert arm["all_abstain_images"] == 1


def test_missing_negative_control_prediction_is_unknown_even_with_zero_gold_errors():
    arm = _arm(_run(_fixture(frozen_images=[_image(required=(), gold=[])])))
    assert arm["status"] == "no_records"
    assert arm["coverage"] == 0
    assert arm["gold_outcome_rates"] is None
    assert arm["all_abstain_images"] == 0
    assert arm["image_ledger"][0]["all_abstain"] is None


def test_cli_missing_output_parent_is_a_concise_error(tmp_path, capsys):
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps(_fixture()))
    out = tmp_path / "missing" / "report.json"
    assert nbe.main([str(inp), "--output", str(out)]) == 1
    error = capsys.readouterr().err
    assert "cannot write report" in error
    assert "Traceback" not in error
    assert not out.exists()
    assert list(tmp_path.iterdir()) == [inp]


@pytest.mark.parametrize("prior_exists", [False, True])
def test_cli_mid_write_failure_preserves_prior_report_and_removes_temporary_file(
    tmp_path, monkeypatch, capsys, prior_exists
):
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps(_fixture()))
    out = tmp_path / "report.json"
    previous = b"previous complete report\n"
    if prior_exists:
        out.write_bytes(previous)
    original_write = Path.write_text
    written = []

    def fail_after_partial_write(path, text, *args, **kwargs):
        # Exercise the real filesystem write boundary, not a replacement evaluator.
        written.append(path)
        original_write(path, text[:20], *args, **kwargs)
        raise OSError("simulated-full-disk")

    monkeypatch.setattr(Path, "write_text", fail_after_partial_write)
    assert nbe.main([str(inp), "--output", str(out)]) == 1
    assert written and all(path.parent == out.parent for path in written)
    assert "cannot write report" in capsys.readouterr().err
    assert out.read_bytes() == previous if prior_exists else not out.exists()
    assert set(tmp_path.iterdir()) == ({inp, out} if prior_exists else {inp})


def test_cli_replace_failure_preserves_prior_report_and_cleans_sibling(tmp_path, monkeypatch, capsys):
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps(_fixture()))
    out = tmp_path / "report.json"
    previous = b"previous complete report\n"
    out.write_bytes(previous)

    def fail_replace(src, dst):
        assert Path(src).parent == out.parent
        assert Path(dst) == out
        assert json.loads(Path(src).read_text())["schema"] == nbe.REPORT_SCHEMA
        assert out.read_bytes() == previous
        raise OSError("simulated-replace-failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    assert nbe.main([str(inp), "--output", str(out)]) == 1
    assert "cannot write report" in capsys.readouterr().err
    assert out.read_bytes() == previous
    assert set(tmp_path.iterdir()) == {inp, out}


def test_cli_invalid_input_preserves_prior_report_without_attempting_output(tmp_path, monkeypatch, capsys):
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps(_fixture(frozen_images=[])))
    out = tmp_path / "report.json"
    previous = b"previous complete report\n"
    out.write_bytes(previous)

    def unexpected_write(*args, **kwargs):
        pytest.fail("invalid input attempted report creation")

    monkeypatch.setattr(Path, "write_text", unexpected_write)
    assert nbe.main([str(inp), "--output", str(out)]) == 1
    assert "frozen_images" in capsys.readouterr().err
    assert out.read_bytes() == previous
    assert set(tmp_path.iterdir()) == {inp, out}
