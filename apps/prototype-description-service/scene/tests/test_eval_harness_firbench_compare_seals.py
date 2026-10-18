"""Synthetic seals exercise code bindings, never operator ratification or human truth."""

from __future__ import annotations

import dataclasses
import json

import pytest

from scene.tests import test_eval_harness_firbench_cli as source
from scene.tests.test_eval_harness_firbench_cli import real  # noqa: F401
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score_io as io


@pytest.fixture
def producer(real, monkeypatch):
    head = cli._head_sha(source.REPO_ROOT)
    monkeypatch.setattr(cli, "_head_sha", lambda _: head)
    monkeypatch.setattr(cli, "_repo_root", lambda: real.repo)

    def produce(name, edit=None, *, sealed=True, frame=source.REAL_FRAME):
        decision = source._real_decision(real, name, edit, sealed=sealed)
        run = real.private / "runs" / name
        real.state.run = run
        assert (
            cli.main(
                [
                    "run",
                    "--frame",
                    frame,
                    "--decision",
                    str(decision),
                    "--legs",
                    "sface,auraface,insightface",
                    "--arms",
                    "native",
                    "--out",
                    str(run),
                    "--created-at",
                    source.REAL_CREATED_AT,
                ]
            )
            == 0
        )
        assert cli.main(["score", str(run)]) == 0
        return decision, run

    return produce


def _fpir(raw):
    raw["primary"]["fpir_target"] = 0.05


def _compare(real, a, b, *, treatment="fpir_target", out=None):
    return cli.compare_runs(a, b, out_dir=out or real.private / "comparison", treatment=treatment, repo_root=real.repo)


def _refused(real, a, b, reason, *, treatment="fpir_target"):
    before = source._snapshot(real.repo)
    with pytest.raises(fc.FirBenchError, match=reason):
        _compare(real, a, b, treatment=treatment)
    assert source._snapshot(real.repo) == before


def _rewrite_bound_decision(real, run, decision, raw, *, reseal):
    if reseal:
        raw["seal"] = None
        decision.write_text(json.dumps(raw))
        raw["seal"] = dataclasses.asdict(fc.seal(fc.load_decision_manifest(decision), sealed_at=source.SEALED_AT).seal)
    decision.write_text(json.dumps(raw))
    # Preserve the raw file binding when attacking the independently checked seal.
    digest = cli._file_sha256(decision)
    for filename, section in (("manifest.json", "firbench"), ("scores.json", None)):
        path = run / filename
        payload = json.loads(path.read_text())
        target = payload if section is None else payload[section]
        target["decision_sha256"] = digest
        path.write_text(json.dumps(payload))


@pytest.mark.parametrize("real", [source.ELIGIBLE_IDENTITIES], indirect=True)
def test_valid_sealed_fpir_cli_wire_normalization_and_immutable_replay(real, producer):
    da, a = producer("a")
    db, b = producer("b", _fpir)
    for path in (da, db):
        original = fc.load_decision_manifest(path)
        fc.require_verdict_allowed(original, frame=original.frame(source.REAL_FRAME))
        assert original.interval.n_boot == 10000
    # Compare consumes persisted evidence only: remove source pixels, GT and bindings.
    for path in real.private.glob("*.png"):
        path.unlink()
    for name in ("source.json", "templates.json", "inputs/fake-only.json"):
        (real.private / name).unlink()
    before = source._snapshot(real.repo)
    assert cli.main(["compare", str(a), str(b), "--treatment", "fpir_target", "--out", str(a)]) == 0
    output = a / "comparison.json"
    payload = json.loads(output.read_text())
    fc.validate_interchange("comparison-v1", payload)
    after = source._snapshot(real.repo)
    assert {k: v for k, v in after.items() if k != str(output.relative_to(real.repo))} == before
    assert payload["comparison_state"] == "comparable"
    assert payload["differences"] == ["fpir_target"]
    assert payload["verdicts"] == {"run_a": "inconclusive", "run_b": "inconclusive"}
    assert payload["run_a"]["decision_sha256"] == cli._file_sha256(da)
    assert payload["run_b"]["decision_sha256"] == cli._file_sha256(db)
    assert payload["run_a"]["decision_sha256"] != payload["run_b"]["decision_sha256"]
    identities = [cli._run_identity(run, repo_root=real.repo, treatment="fpir_target") for run in (a, b)]
    for identity in identities:
        assert isinstance(identity["decision"], fc.DecisionManifest)
        assert isinstance(identity["inventory"], io.Inventory)
        assert identity["records"]
    hashes = [i["decision_sha256_without_treatment"] for i in identities]
    assert hashes[0] == hashes[1] == payload["compatibility"]["decision_sha256_without_treatment"]
    for row in payload["paired_deltas"]:
        assert row["status"] == "scored"
        assert row["n_searches"] == row["n_psu"] == row["n_eff"] == 52
        assert (row["point"], row["lower"], row["upper"]) == (0.0, 0.0, 0.0)
    assert payload["delta"] == {k: payload["paired_deltas"][0][k] for k in ("point", "lower", "upper")}
    assert all(row["reason"] == "pooled_fit_threshold_no_per_fold_estimates" for row in payload["tau_spread"])
    assert _compare(real, a, b, out=a) == output
    assert source._snapshot(real.repo) == after
    output.write_text("conflicting derived output")
    before_conflict = source._snapshot(real.repo)
    with pytest.raises(fc.FrameContractError, match="conflict|overwrite"):
        _compare(real, a, b, out=a)
    assert source._snapshot(real.repo) == before_conflict


@pytest.mark.parametrize("forgery", ["false", "copied", "both_same", "digest_only"])
def test_original_seals_must_validate_even_when_raw_file_bindings_match(real, producer, forgery):
    da, a = producer("a")
    db, b = producer("b", None if forgery == "digest_only" else _fpir)
    raw_a, raw_b = json.loads(da.read_text()), json.loads(db.read_text())
    raw_b["seal"]["sha256"] = "0" * 64 if forgery in {"false", "both_same"} else raw_a["seal"]["sha256"]
    if forgery == "digest_only":
        # No body change at all; a different digest still cannot be normalized away.
        raw_b = json.loads(da.read_text())
        raw_b["seal"]["sha256"] = "0" * 64
    if forgery == "both_same":
        raw_a["seal"]["sha256"] = "0" * 64
        _rewrite_bound_decision(real, a, da, raw_a, reseal=False)
    _rewrite_bound_decision(real, b, db, raw_b, reseal=False)
    _refused(real, a, b, "seal.*hash|seal.sha256")


@pytest.mark.parametrize(
    "field",
    ["seal.sealed_at", "ratification.decision_ref", "ratification.ratified_at", "hypotheses.1.margin", "interval.seed"],
)
def test_valid_seals_do_not_hide_undeclared_nested_policy_or_context(real, producer, field):
    _, a = producer("a")

    def edit(raw):
        _fpir(raw)
        if field == "hypotheses.1.margin":
            raw["hypotheses"][1]["margin"] = 0.06
        elif field == "interval.seed":
            raw["interval"]["seed"] += 1

    decision, b = producer("b", edit)
    raw = json.loads(decision.read_text())
    if field.startswith("ratification."):
        key = field.split(".")[1]
        raw["ratification"][key] = (
            "synthetic:other-fixture-reference" if key == "decision_ref" else "2026-10-15T08:01:00Z"
        )
        _rewrite_bound_decision(real, b, decision, raw, reseal=True)
    elif field == "seal.sealed_at":
        raw["seal"]["sealed_at"] = "2026-10-15T09:01:00Z"
        _rewrite_bound_decision(real, b, decision, raw, reseal=False)
    _refused(real, a, b, field.replace(".", r"\."))


@pytest.mark.parametrize(
    "field",
    [
        "frame_id",
        "frame_bytes_sha256",
        "face_set_sha256",
        "annotation_bytes_sha256",
        "scorer_sha",
        "boundary_semantics",
        "opencv_version",
        "ort_version",
    ],
)
def test_seal_treatment_cannot_relax_independent_never_fields(real, producer, field):
    _, a = producer("a")
    if field in {"opencv_version", "ort_version"}:
        setattr(real.state, field, "different-runtime")
    if field == "face_set_sha256":
        path = real.private / "source.json"
        raw = json.loads(path.read_text())
        raw["faces"][0]["face_id"] = "replacement-face"
        sha = source.write_json(path, raw)
        real.base["frames"][0]["source_sha256"] = sha
        path = real.private / "inputs/fake-only.json"
        binding = json.loads(path.read_text())
        binding["query_source"]["sha256"] = sha
        source.write_json(path, binding)
    frame = "other-frame" if field == "frame_id" else source.REAL_FRAME
    if field == "frame_id":
        (real.private / "inputs/other-frame.json").write_bytes((real.private / "inputs/fake-only.json").read_bytes())

    def edit(raw):
        _fpir(raw)
        if field == "boundary_semantics":
            raw["boundary_semantics"] = "legacy_v1"
        elif field == "frame_id":
            raw["frames"].append({**raw["frames"][0], "frame_id": frame})

    _, b = producer("b", edit, frame=frame)
    if field == "frame_bytes_sha256":
        with (b / "frame.json").open("ab") as stream:
            stream.write(b" ")
        assert (
            json.loads((a / "frame.json").read_text())["source_sha256"]
            == json.loads((b / "frame.json").read_text())["source_sha256"]
        )
    elif field == "scorer_sha":
        path = b / "manifest.json"
        raw = json.loads(path.read_text())
        raw["firbench"]["scorer_sha256"] = "a" * 64
        path.write_text(json.dumps(raw))
    elif field == "annotation_bytes_sha256":
        path = b / "frame.json"
        raw = json.loads(path.read_text())
        raw["faces"][0]["annotation"]["rule_id"] = "synthetic:different-rule"
        path.write_text(json.dumps(raw))
    _refused(real, a, b, field)


def test_unratified_development_comparison_stays_numbers_only(real, producer):
    _, a = producer("a", sealed=False)
    _, b = producer("b", _fpir, sealed=False)
    payload = json.loads(_compare(real, a, b).read_text())
    assert payload["verdicts"] == {"run_a": "unratified", "run_b": "unratified"}
    assert fc.load_decision_manifest(real.repo / "benchmarks/manifests/a.json").seal is None


def test_valid_sealed_fpir_change_requires_declaration(real, producer):
    _, a = producer("a")
    _, b = producer("b", _fpir)
    _refused(real, a, b, "fpir_target|seal.sha256", treatment=None)


def test_normalization_preserves_every_unowned_leaf_and_original_body(real, producer):
    decision, _ = producer("a")
    raw = json.loads(decision.read_text())
    before = json.loads(json.dumps(raw))
    projected = cli._without_treatment(raw, "fpir_target")
    assert raw == before
    differences = cli._compatibility_leaf_differences(raw, projected)
    assert set(differences) == {("primary", "fpir_target"), ("seal", "sha256")}
    assert cli._without_treatment(raw, None) == raw
    # A digest projected from an invalid original must never become admissible.
    raw["primary"]["fpir_target"] = 0.05
    with pytest.raises(fc.FrameContractError, match="seal.*hash"):
        cli._without_treatment(raw, "fpir_target")
