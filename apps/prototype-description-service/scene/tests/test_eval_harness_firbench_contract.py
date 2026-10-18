"""FIRBENCH-1 S0 contract: shared names, decision manifest, unseal gate, interchange schemas.

Synthetic identifiers only (``id-0001``, ``image-0001``). No file from
``benchmarks/private/`` is read here.
"""

from __future__ import annotations

import ast
import dataclasses
import enum
import hashlib
import inspect
import json
import shutil
import threading
import tokenize
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc

REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST_PATH = REPO_ROOT / "benchmarks" / "manifests" / "fir-bench-decision-v1.json"
GATE_PATH = REPO_ROOT / "benchmarks" / "manifests" / "fir-gate-contract-v1.json"
MODULE_PATH = Path(fc.__file__)
SCHEMA_DIR = MODULE_PATH.parent / "firbench_schemas"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "firbench_interchange_v1"
INTERCHANGE_NAMES = ("frame-v1", "face-search-record-v1", "scores-v1", "clusters-v1", "comparison-v1")
SEALED_AT = "2026-10-15T09:00:00+00:00"
CONSUMED_AT = "2026-10-15T09:05:00+00:00"
RATIFIED_AT = "2026-10-15T08:00:00+00:00"
DECISION_SHA = "e" * 64
RUN_ID = "run-0001"
CODE_SHA = "1" * 40
SCORER_SHA = "2" * 40


def _committed_payload() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _load_payload(tmp_path: Path, payload: dict) -> fc.DecisionManifest:
    manifest_path = tmp_path / "fir-bench-decision-v1.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    shutil.copyfile(GATE_PATH, tmp_path / "fir-gate-contract-v1.json")
    return fc.load_decision_manifest(manifest_path)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _frame(*, sealed: bool = True, frame_id: str = "confirm-v1") -> fc.FrameSpec:
    return fc.FrameSpec(
        frame_id=frame_id,
        admissibility=fc.Admissibility.confirmatory,
        sealed=sealed,
        source_sha256="d" * 64,
        exhaustive=True,
    )


def _token(frame: fc.FrameSpec, **overrides: object) -> fc.UnsealToken:
    fields: dict[str, object] = {
        "frame_id": frame.frame_id,
        "frame_sha256": frame.source_sha256,
        "decision_sha256": DECISION_SHA,
        "run_id": RUN_ID,
        "code_sha": CODE_SHA,
        "scorer_sha": SCORER_SHA,
        "consumed_at": None,
    }
    fields.update(overrides)
    return fc.UnsealToken(**fields)  # type: ignore[arg-type]


def _read(frame: fc.FrameSpec, token: fc.UnsealToken | None, repo_root: Path, **overrides: object) -> fc.UnsealToken:
    kwargs: dict[str, object] = {
        "decision_sha256": DECISION_SHA,
        "run_id": RUN_ID,
        "code_sha": CODE_SHA,
        "scorer_sha": SCORER_SHA,
        "repo_root": repo_root,
        "consumed_at": CONSUMED_AT,
    }
    kwargs.update(overrides)
    return fc.require_frame_read_allowed(frame, token, **kwargs)  # type: ignore[arg-type]


def _sealable_payload() -> dict:
    payload = _committed_payload()
    payload["gallery_lineage"]["templates_sha256"] = "c" * 64
    # Controlled fake evidence is supplied before sealing, never patched in afterwards.
    for frame in payload["frames"]:
        frame.update(source_sha256="d" * 64, exhaustive=True)
    return payload


def _ratified_payload() -> dict:
    payload = _sealable_payload()
    payload["ratification"] = {"decision_ref": "test-decision-ref", "ratified_at": RATIFIED_AT}
    return payload


# --- shared names -----------------------------------------------------------

SHARED_NAMES = (
    "Admissibility",
    "VerdictState",
    "InconclusiveReason",
    "FaceOutcome",
    "BoundarySemantics",
    "Arm",
    "ArmStatus",
    "SearchStage",
    "IdentityStatus",
    "SamplingArm",
    "FoldRole",
    "AlignmentMode",
    "LegKind",
    "LegId",
    "FrameSpec",
    "DecisionManifest",
    "UnsealToken",
    "require_private_output_path",
    "load_decision_manifest",
    "manifest_sha256",
    "seal",
    "require_verdict_allowed",
    "require_frame_read_allowed",
    "validate_interchange",
    "FirBenchError",
)


@pytest.mark.parametrize("name", SHARED_NAMES)
def test_shared_name_is_exported(name: str) -> None:
    assert hasattr(fc, name)


@pytest.mark.parametrize(
    ("enum_cls", "members"),
    [
        (fc.Admissibility, {"diagnostic", "development", "confirmatory"}),
        (fc.VerdictState, {"superior", "non_inferior", "inconclusive", "guardrail_vetoed", "unratified"}),
        (
            fc.InconclusiveReason,
            {
                "primary_fpir_unresolvable",
                "required_guardrail_unscored",
                "margin_unreachable_mde_gt_delta",
                "non_confirmatory_frame",
                "insufficient_independent_psus",
            },
        ),
        (
            fc.FaceOutcome,
            {"missed", "unaligned", "wrong_identity", "rejected", "correct", "false_accept", "correct_reject"},
        ),
        (fc.BoundarySemantics, {"legacy_v1", "v2"}),
        (fc.Arm, {"native", "gt_crop_redetect", "cached_yunet_landmark_replay"}),
        (fc.ArmStatus, {"available", "unavailable", "unavailable_fused"}),
        (fc.SearchStage, {"missed", "detected", "unaligned", "embedded", "unavailable"}),
        (fc.IdentityStatus, {"named", "unknown", "unresolved"}),
        (fc.SamplingArm, {"probability", "challenge"}),
        (fc.FoldRole, {"fit", "test"}),
        (fc.AlignmentMode, {"separable", "fused_internal"}),
        (fc.LegKind, {"sface", "auraface", "insightface", "canary"}),
        (fc.HypothesisKind, {"superiority", "non_inferiority"}),
        (fc.HypothesisDirection, {"lower_bound_above_margin", "upper_bound_below_margin"}),
        (fc.GuardrailRole, {"veto", "report_only"}),
        (fc.IntervalMethod, {"paired_cluster_bootstrap"}),
        (fc.PsuKind, {"image_identity_component"}),
        (fc.Multiplicity, {"holm"}),
    ],
)
def test_enum_has_exactly_the_shared_members(enum_cls: type[enum.StrEnum], members: set[str]) -> None:
    assert issubclass(enum_cls, enum.StrEnum)
    assert {member.value for member in enum_cls} == members


def test_search_stage_has_no_fused_only_members() -> None:
    values = {member.value for member in fc.SearchStage}
    assert "fused_internal" not in values
    assert "unavailable_fused" not in values


def test_arm_status_marks_fused_attribution_separately() -> None:
    assert fc.ArmStatus.unavailable_fused.value == "unavailable_fused"
    assert fc.AlignmentMode.fused_internal.value == "fused_internal"


@pytest.mark.parametrize(
    "name",
    [
        "FirBenchError",
        "UnratifiedDecisionError",
        "SealedFrameReadError",
        "CrossSpaceComparisonError",
        "RuntimeMismatchError",
        "CalibrationLeakError",
        "NonPrivateOutputError",
        "ProjectionLeakError",
        "LinkageMetricError",
        "CanaryInSealedRunError",
        "CanaryConfigError",
        "FrameContractError",
        "TauInfeasibleError",
        "UndeclaredH2LegError",
    ],
)
def test_error_is_firbench_error_subclass(name: str) -> None:
    error = getattr(fc, name)
    assert issubclass(error, fc.FirBenchError)
    assert issubclass(fc.FirBenchError, Exception)


def test_leg_id_key_is_stable_and_path_safe() -> None:
    leg = fc.LegId(
        kind=fc.LegKind.sface,
        arm=fc.Arm.native,
        space_fingerprint="ab12cd",
        opencv_version="4.10.0",
        ort_version="1.18.0",
    )
    assert leg.key() == "sface__native__ab12cd__cv4.10.0__ort1.18.0"
    with pytest.raises(fc.FrameContractError):
        fc.LegId(
            kind=fc.LegKind.sface,
            arm=fc.Arm.native,
            space_fingerprint="ab/12",
            opencv_version="4.10.0",
            ort_version="1.18.0",
        )


def test_frame_spec_rejects_path_like_frame_id() -> None:
    with pytest.raises(fc.FrameContractError):
        fc.FrameSpec(
            frame_id="../escape",
            admissibility=fc.Admissibility.development,
            sealed=False,
            source_sha256=None,
            exhaustive=None,
        )


def test_require_frame_read_allowed_signature_is_frozen() -> None:
    params = inspect.signature(fc.require_frame_read_allowed).parameters
    assert list(params)[:2] == ["frame", "token"]
    keyword_only = {name for name, param in params.items() if param.kind is inspect.Parameter.KEYWORD_ONLY}
    assert keyword_only == {"decision_sha256", "run_id", "code_sha", "scorer_sha", "repo_root", "consumed_at"}


# --- interchange schemas ----------------------------------------------------


@pytest.mark.parametrize("name", INTERCHANGE_NAMES)
def test_schema_document_declares_draft_2020_12_and_version_one(name: str) -> None:
    schema = json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"] == {"const": 1}
    assert "schema_version" in schema["required"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("name", INTERCHANGE_NAMES)
def test_interchange_schema_accepts_its_fixture(name: str) -> None:
    fc.validate_interchange(name, _fixture(name))


@pytest.mark.parametrize("name", INTERCHANGE_NAMES)
def test_interchange_schema_rejects_unknown_key(name: str) -> None:
    payload = _fixture(name)
    payload["unexpected_key"] = "x"
    with pytest.raises(fc.FrameContractError):
        fc.validate_interchange(name, payload)


@pytest.mark.parametrize("name", INTERCHANGE_NAMES)
def test_interchange_schema_rejects_each_removed_required_key(name: str) -> None:
    schema = json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))
    for key in schema["required"]:
        payload = _fixture(name)
        del payload[key]
        with pytest.raises(fc.FrameContractError):
            fc.validate_interchange(name, payload)


@pytest.mark.parametrize("name", INTERCHANGE_NAMES)
def test_interchange_schema_rejects_other_schema_version(name: str) -> None:
    payload = _fixture(name)
    payload["schema_version"] = 2
    with pytest.raises(fc.FrameContractError):
        fc.validate_interchange(name, payload)


def test_interchange_rejects_unknown_schema_name() -> None:
    with pytest.raises(fc.FrameContractError):
        fc.validate_interchange("not-a-schema-v1", {"schema_version": 1})


def test_interchange_rejects_bool_as_version() -> None:
    payload = _fixture("scores-v1")
    payload["schema_version"] = True
    with pytest.raises(fc.FrameContractError):
        fc.validate_interchange("scores-v1", payload)


# --- decision manifest: load ------------------------------------------------


def test_committed_manifest_loads_with_declared_policy_values() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    assert isinstance(manifest, fc.DecisionManifest)
    assert manifest.planning_icc == pytest.approx(0.10)
    assert manifest.p_d == pytest.approx(0.15)
    assert manifest.power == pytest.approx(0.80)
    assert manifest.min_n_independent == 50
    assert manifest.cell_floor_n_independent == 30
    assert manifest.primary.fpir_target == pytest.approx(0.01)
    assert manifest.primary.comparison == ("sface", "auraface")
    assert manifest.primary.end_to_end is True
    assert manifest.alpha_family == pytest.approx(0.05)
    assert manifest.multiplicity is fc.Multiplicity.holm
    assert manifest.boundary_semantics is fc.BoundarySemantics.v2


def test_committed_manifest_hypotheses_follow_holm_order() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    h1, h2 = manifest.hypotheses
    assert (h1.id, h1.kind, h1.legs, h1.margin) == ("H1", fc.HypothesisKind.superiority, ("sface", "auraface"), 0)
    assert h2.kind is fc.HypothesisKind.non_inferiority
    assert h2.legs == ("auraface", "insightface")
    assert h2.margin == pytest.approx(0.05)


def test_committed_manifest_keeps_unknown_values_null() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    assert manifest.gallery_lineage.templates_sha256 is None
    assert manifest.ratification is not None
    assert manifest.ratification.decision_ref is None
    assert manifest.ratification.ratified_at is None
    assert manifest.seal is None
    for frame in manifest.frames:
        assert frame.source_sha256 is None
        assert frame.exhaustive is None


def test_committed_manifest_has_declared_frame_registry() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    registry = {frame.frame_id: frame for frame in manifest.frames}
    assert registry["golden150-v1"].admissibility is fc.Admissibility.diagnostic
    assert registry["corpus646-v3r"].admissibility is fc.Admissibility.development
    assert registry["fir-occ-v1-prob"].admissibility is fc.Admissibility.development
    assert registry["fir-occ-v1-chal"].admissibility is fc.Admissibility.development
    assert registry["confirm-v1"].admissibility is fc.Admissibility.confirmatory
    assert registry["confirm-v1"].sealed is True
    assert all(not registry[name].sealed for name in registry if name != "confirm-v1")


def test_committed_manifest_declares_three_dated_disconfirmers() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    assert len(manifest.disconfirmers) == 3
    for disconfirmer in manifest.disconfirmers:
        assert disconfirmer.statement
        assert disconfirmer.review_date


def test_committed_manifest_guardrail_roles() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    roles = {guardrail.metric: guardrail.role for guardrail in manifest.guardrails}
    assert roles["cost_per_accepted_description"] is fc.GuardrailRole.report_only
    veto_metrics = {metric for metric, role in roles.items() if role is fc.GuardrailRole.veto}
    assert len(veto_metrics) == 4


def test_committed_gate_contract_sha_matches_real_file() -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    assert manifest.gate_contract_sha256 == hashlib.sha256(GATE_PATH.read_bytes()).hexdigest()


def test_committed_fold_gallery_and_bootstrap_seeds_follow_declared_derivation() -> None:
    def derived(tag: str) -> int:
        return int.from_bytes(hashlib.sha256(f"FIRBENCH-1/v1/{tag}".encode()).digest()[:4], "big")

    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    assert manifest.fold_protocol.k == 5
    assert manifest.fold_protocol.seed == derived("folds") == 2406466110
    assert manifest.gallery_lineage.split_seed == derived("gallery") == 2468935812
    assert manifest.interval.seed == derived("bootstrap") == 2429382368
    assert manifest.interval.n_boot == 10000
    assert derived("label_queue") == 336880394


def test_load_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    payload = _committed_payload()
    payload["surprise"] = True
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_interval_level_field(tmp_path: Path) -> None:
    payload = _committed_payload()
    payload["interval"]["level"] = 0.95
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_missing_interval_seed(tmp_path: Path) -> None:
    payload = _committed_payload()
    del payload["interval"]["seed"]
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


@pytest.mark.parametrize("legs", [["insightface", "insightface"], ["sface", "auraface"]])
def test_load_rejects_h2_without_exactly_one_inhouse_leg(tmp_path: Path, legs: list[str]) -> None:
    payload = _committed_payload()
    payload["hypotheses"][1]["legs"] = legs
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_guardrail_without_role(tmp_path: Path) -> None:
    payload = _committed_payload()
    del payload["guardrails"][0]["role"]
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_unknown_guardrail_role(tmp_path: Path) -> None:
    payload = _committed_payload()
    payload["guardrails"][0]["role"] = "advisory"
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_confirmatory_frame_that_is_not_sealed(tmp_path: Path) -> None:
    payload = _committed_payload()
    for frame in payload["frames"]:
        if frame["frame_id"] == "confirm-v1":
            frame["sealed"] = False
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_gate_contract_sha_mismatch(tmp_path: Path) -> None:
    payload = _committed_payload()
    payload["gate_contract_sha256"] = "0" * 64
    with pytest.raises(fc.FrameContractError):
        _load_payload(tmp_path, payload)


def test_load_rejects_missing_gate_contract_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "fir-bench-decision-v1.json"
    manifest_path.write_text(json.dumps(_committed_payload()), encoding="utf-8")
    with pytest.raises(fc.FrameContractError):
        fc.load_decision_manifest(manifest_path)


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "fir-bench-decision-v1.json"
    manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(fc.FrameContractError):
        fc.load_decision_manifest(manifest_path)


def test_load_rejects_duplicate_keys(tmp_path: Path) -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8").replace(
        '"alpha_family": 0.05,', '"alpha_family": 0.05, "alpha_family": 0.05,', 1
    )
    manifest_path = tmp_path / "fir-bench-decision-v1.json"
    manifest_path.write_text(text, encoding="utf-8")
    shutil.copyfile(GATE_PATH, tmp_path / "fir-gate-contract-v1.json")
    with pytest.raises(fc.FrameContractError):
        fc.load_decision_manifest(manifest_path)


# --- decision manifest: hash and seal --------------------------------------


def test_manifest_sha256_is_stable_under_key_reordering(tmp_path: Path) -> None:
    committed = fc.load_decision_manifest(MANIFEST_PATH)
    reordered = dict(reversed(list(_committed_payload().items())))
    manifest_path = tmp_path / "fir-bench-decision-v1.json"
    manifest_path.write_text(json.dumps(reordered), encoding="utf-8")
    shutil.copyfile(GATE_PATH, tmp_path / "fir-gate-contract-v1.json")
    reloaded = fc.load_decision_manifest(manifest_path)
    assert fc.manifest_sha256(reloaded) == fc.manifest_sha256(committed)


def test_manifest_sha256_changes_when_fpir_target_changes(tmp_path: Path) -> None:
    base = fc.load_decision_manifest(MANIFEST_PATH)
    payload = _committed_payload()
    payload["primary"]["fpir_target"] = 0.02
    changed = _load_payload(tmp_path, payload)
    assert fc.manifest_sha256(changed) != fc.manifest_sha256(base)


def test_manifest_sha256_excludes_seal_block(tmp_path: Path) -> None:
    manifest = _load_payload(tmp_path, _sealable_payload())
    sealed = fc.seal(manifest, sealed_at=SEALED_AT)
    assert sealed.seal is not None
    assert sealed.seal.sha256 == fc.manifest_sha256(manifest)
    assert fc.manifest_sha256(sealed) == sealed.seal.sha256


@pytest.mark.parametrize(
    "path",
    [
        ("planning_icc",),
        ("fold_protocol", "k"),
        ("fold_protocol", "seed"),
        ("gallery_lineage", "split_seed"),
        ("gallery_lineage", "templates_sha256"),
        ("interval", "n_boot"),
        ("interval", "seed"),
    ],
)
def test_seal_refuses_null_sealable_field(tmp_path: Path, path: tuple[str, ...]) -> None:
    payload = _sealable_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = None
    manifest = _load_payload(tmp_path, payload)
    with pytest.raises(fc.FrameContractError):
        fc.seal(manifest, sealed_at=SEALED_AT)


def test_seal_refuses_committed_manifest_with_unresolved_hashes(tmp_path: Path) -> None:
    manifest = fc.load_decision_manifest(MANIFEST_PATH)
    with pytest.raises(fc.FrameContractError):
        fc.seal(manifest, sealed_at=SEALED_AT)


@pytest.mark.parametrize("frame_index", range(5))
@pytest.mark.parametrize("field", ["source_sha256", "exhaustive"])
def test_seal_refuses_unresolved_included_frame(tmp_path: Path, frame_index: int, field: str) -> None:
    payload = _sealable_payload()
    for frame in payload["frames"]:
        frame.update(source_sha256="d" * 64, exhaustive=True)
    payload["frames"][frame_index][field] = None
    manifest = _load_payload(tmp_path, payload)
    with pytest.raises(fc.FrameContractError, match=field):
        fc.seal(manifest, sealed_at=SEALED_AT)


def test_seal_refuses_resealing(tmp_path: Path) -> None:
    sealed = fc.seal(_load_payload(tmp_path, _sealable_payload()), sealed_at=SEALED_AT)
    with pytest.raises(fc.FrameContractError):
        fc.seal(sealed, sealed_at=SEALED_AT)


def test_load_accepts_committed_manifest_with_nulls_in_sealable_fields(tmp_path: Path) -> None:
    payload = _committed_payload()
    payload["planning_icc"] = None
    payload["fold_protocol"] = {"k": None, "seed": None}
    payload["interval"]["seed"] = None
    manifest = _load_payload(tmp_path, payload)
    assert manifest.planning_icc is None
    assert manifest.interval.seed is None


# --- verdict gate ------------------------------------------------------------


def test_verdict_refused_when_unratified(tmp_path: Path) -> None:
    manifest = fc.seal(_load_payload(tmp_path, _sealable_payload()), sealed_at=SEALED_AT)
    with pytest.raises(fc.UnratifiedDecisionError):
        fc.require_verdict_allowed(manifest, frame=_frame(sealed=False))


def test_verdict_refused_when_unsealed(tmp_path: Path) -> None:
    manifest = _load_payload(tmp_path, _ratified_payload())
    with pytest.raises(fc.UnratifiedDecisionError):
        fc.require_verdict_allowed(manifest, frame=_frame(sealed=False))


def test_verdict_refused_when_tampered_after_seal(tmp_path: Path) -> None:
    sealed = fc.seal(_load_payload(tmp_path, _ratified_payload()), sealed_at=SEALED_AT)
    tampered = fc.DecisionManifest(**{**_field_dict(sealed), "primary": _with_fpir(sealed.primary, 0.02)})
    with pytest.raises(fc.UnratifiedDecisionError):
        fc.require_verdict_allowed(tampered, frame=_frame(sealed=False))


def test_verdict_refused_for_sealed_frame_with_unsealed_manifest(tmp_path: Path) -> None:
    manifest = _load_payload(tmp_path, _ratified_payload())
    with pytest.raises(fc.SealedFrameReadError):
        fc.require_verdict_allowed(manifest, frame=_frame(sealed=True))


def test_verdict_allowed_for_ratified_sealed_manifest(tmp_path: Path) -> None:
    manifest = fc.seal(_load_payload(tmp_path, _ratified_payload()), sealed_at=SEALED_AT)
    fc.require_verdict_allowed(manifest, frame=manifest.frame("corpus646-v3r"))


def _resolved_ratified_manifest(tmp_path: Path) -> fc.DecisionManifest:
    payload = _ratified_payload()
    for frame in payload["frames"]:
        frame.update(source_sha256="d" * 64, exhaustive=True)
    return _load_payload(tmp_path, payload)


def test_verdict_refuses_unregistered_frame(tmp_path: Path) -> None:
    manifest = fc.seal(_resolved_ratified_manifest(tmp_path), sealed_at=SEALED_AT)
    with pytest.raises(fc.FrameContractError, match="registry"):
        fc.require_verdict_allowed(manifest, frame=_frame(frame_id="unregistered"))


@pytest.mark.parametrize(
    "changes",
    [
        {"admissibility": fc.Admissibility.development},
        {"sealed": False},
        {"source_sha256": "a" * 64},
        {"source_sha256": None},
        {"exhaustive": False},
        {"exhaustive": None},
    ],
)
def test_verdict_refuses_altered_registry_frame(tmp_path: Path, changes: dict) -> None:
    manifest = fc.seal(_resolved_ratified_manifest(tmp_path), sealed_at=SEALED_AT)
    frame = dataclasses.replace(manifest.frame("confirm-v1"), **changes)
    with pytest.raises(fc.FrameContractError, match="registry"):
        fc.require_verdict_allowed(manifest, frame=frame)


@pytest.mark.parametrize("field", ["source_sha256", "exhaustive"])
@pytest.mark.parametrize("frame_id", ["confirm-v1", "corpus646-v3r"])
def test_verdict_refuses_synthetic_seal_over_unresolved_registry(tmp_path: Path, field: str, frame_id: str) -> None:
    manifest = _resolved_ratified_manifest(tmp_path)
    frames = tuple(
        dataclasses.replace(frame, **{field: None}) if frame.frame_id == frame_id else frame
        for frame in manifest.frames
    )
    manifest = dataclasses.replace(manifest, frames=frames)
    # A matching digest alone is not proof that the no-absent-input seal gate ran.
    manifest = dataclasses.replace(manifest, seal=fc.Seal(sealed_at=SEALED_AT, sha256=fc.manifest_sha256(manifest)))
    with pytest.raises(fc.UnratifiedDecisionError, match="unresolved"):
        fc.require_verdict_allowed(manifest, frame=manifest.frame("confirm-v1"))


def test_verdict_refuses_registered_nonexhaustive_frame(tmp_path: Path) -> None:
    manifest = _resolved_ratified_manifest(tmp_path)
    frames = tuple(
        dataclasses.replace(frame, exhaustive=False) if frame.frame_id == "confirm-v1" else frame
        for frame in manifest.frames
    )
    manifest = fc.seal(dataclasses.replace(manifest, frames=frames), sealed_at=SEALED_AT)
    with pytest.raises(fc.FrameContractError, match="exhaustive"):
        fc.require_verdict_allowed(manifest, frame=manifest.frame("confirm-v1"))


def _field_dict(manifest: fc.DecisionManifest) -> dict[str, object]:
    return {field: getattr(manifest, field) for field in manifest.__dataclass_fields__}


def _with_fpir(primary: fc.Primary, fpir_target: float) -> fc.Primary:
    return fc.Primary(
        estimand=primary.estimand,
        comparison=primary.comparison,
        fpir_target=fpir_target,
        end_to_end=primary.end_to_end,
    )


# --- frame-read gate ---------------------------------------------------------


def test_frame_read_refused_without_token(tmp_path: Path) -> None:
    with pytest.raises(fc.SealedFrameReadError):
        _read(_frame(), None, tmp_path)


def test_frame_read_refused_for_token_bound_to_other_run(tmp_path: Path) -> None:
    frame = _frame()
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame, run_id="run-0002"), tmp_path)


def test_frame_read_refused_for_token_of_other_decision(tmp_path: Path) -> None:
    frame = _frame()
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame, decision_sha256="f" * 64), tmp_path)


@pytest.mark.parametrize(
    "override",
    [
        {"frame_sha256": "9" * 64},
        {"frame_id": "other-v1"},
        {"code_sha": "3" * 40},
        {"scorer_sha": "4" * 40},
        {"consumed_at": CONSUMED_AT},
    ],
)
def test_frame_read_refused_for_token_field_mismatch(tmp_path: Path, override: dict[str, object]) -> None:
    frame = _frame()
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame, **override), tmp_path)


def test_frame_read_refused_when_runtime_context_differs(tmp_path: Path) -> None:
    frame = _frame()
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame), tmp_path, code_sha="5" * 40)


def test_frame_read_refused_when_frame_has_no_source_hash(tmp_path: Path) -> None:
    unhashed = fc.FrameSpec(
        frame_id="confirm-v1",
        admissibility=fc.Admissibility.confirmatory,
        sealed=True,
        source_sha256=None,
        exhaustive=True,
    )
    with pytest.raises(fc.SealedFrameReadError):
        _read(unhashed, _token(_frame()), tmp_path)


def test_frame_read_rejects_unsealed_frame_as_misuse(tmp_path: Path) -> None:
    frame = _frame(sealed=False)
    with pytest.raises(fc.FrameContractError):
        _read(frame, _token(frame), tmp_path)


def test_first_frame_read_spends_frame_and_records_consumption(tmp_path: Path) -> None:
    frame = _frame()
    consumed = _read(frame, _token(frame), tmp_path)
    assert consumed.consumed_at == CONSUMED_AT
    marker = tmp_path / "benchmarks" / "private" / "firbench" / "spent" / "confirm-v1.spent"
    assert marker.exists()
    ledger_rows = [
        json.loads(line)
        for line in (tmp_path / "benchmarks" / "private" / "firbench" / "unseal-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert ledger_rows[-1]["consumed_at"] == CONSUMED_AT
    assert ledger_rows[-1]["run_id"] == RUN_ID


def test_second_frame_read_is_refused_after_marker_exists(tmp_path: Path) -> None:
    frame = _frame()
    _read(frame, _token(frame), tmp_path)
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame), tmp_path)


def test_new_decision_sha_cannot_reopen_spent_frame(tmp_path: Path) -> None:
    frame = _frame()
    _read(frame, _token(frame), tmp_path)
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame, decision_sha256="f" * 64), tmp_path, decision_sha256="f" * 64)


def test_new_run_directory_cannot_reopen_spent_frame(tmp_path: Path) -> None:
    frame = _frame()
    _read(frame, _token(frame), tmp_path)
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame, run_id="run-0009"), tmp_path, run_id="run-0009")


def test_concurrent_first_reads_of_one_frame_have_exactly_one_winner(tmp_path: Path) -> None:
    frame = _frame()
    token = _token(frame)
    attempts = 8
    barrier = threading.Barrier(attempts)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            _read(frame, token, tmp_path)
            outcome = "read"
        except fc.SealedFrameReadError:
            outcome = "refused"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert outcomes.count("read") == 1
    assert outcomes.count("refused") == attempts - 1


def test_ledger_append_failure_after_spend_stays_refused(tmp_path: Path) -> None:
    frame = _frame()
    private = tmp_path / "benchmarks" / "private" / "firbench"
    private.mkdir(parents=True)
    (private / "unseal-ledger.jsonl").mkdir()  # a directory cannot be appended to
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame), tmp_path)
    assert (private / "spent" / "confirm-v1.spent").exists()
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame), tmp_path)


def test_spent_marker_create_failure_refuses_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _frame()
    real_open = fc.os.open

    def failing_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if str(path).endswith(".spent"):
            raise PermissionError("denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(fc.os, "open", failing_open)
    with pytest.raises(fc.SealedFrameReadError):
        _read(frame, _token(frame), tmp_path)


# --- private output path -----------------------------------------------------


def test_private_output_path_accepts_private_html(tmp_path: Path) -> None:
    resolved = fc.require_private_output_path("benchmarks/private/x/y.html", repo_root=tmp_path)
    assert resolved == (tmp_path / "benchmarks" / "private" / "x" / "y.html").resolve()


def test_private_output_path_rejects_reports_directory(tmp_path: Path) -> None:
    with pytest.raises(fc.NonPrivateOutputError):
        fc.require_private_output_path("benchmarks/reports/x.html", repo_root=tmp_path)


def test_private_output_path_rejects_dotdot_escape(tmp_path: Path) -> None:
    with pytest.raises(fc.NonPrivateOutputError):
        fc.require_private_output_path("benchmarks/private/../reports/x.html", repo_root=tmp_path)


def test_private_output_path_rejects_symlink_out_of_private(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    private = tmp_path / "benchmarks" / "private"
    private.mkdir(parents=True)
    (private / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(fc.NonPrivateOutputError):
        fc.require_private_output_path("benchmarks/private/link/y.html", repo_root=tmp_path)


def test_private_output_path_rejects_private_root_itself(tmp_path: Path) -> None:
    with pytest.raises(fc.NonPrivateOutputError):
        fc.require_private_output_path("benchmarks/private", repo_root=tmp_path)


@pytest.mark.parametrize("link_part", ["private", "benchmarks", "inner"])
@pytest.mark.parametrize("target_exists", [True, False])
def test_private_output_path_rejects_redirected_boundary(tmp_path: Path, link_part: str, target_exists: bool) -> None:
    target = tmp_path / "public-reports"
    if target_exists:
        target.mkdir()
    private = tmp_path / "benchmarks" / "private"
    link = {"private": private, "benchmarks": private.parent, "inner": private / "inner"}[link_part]
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    relative = "benchmarks/private/inner/report.html"
    with pytest.raises(fc.NonPrivateOutputError):
        fc.require_private_output_path(relative, repo_root=tmp_path)
    with pytest.raises(fc.NonPrivateOutputError):
        fc.require_private_output_path(tmp_path / relative, repo_root=tmp_path)


@pytest.mark.parametrize("link_part", ["private", "benchmarks", "firbench"])
def test_frame_read_refuses_redirected_private_storage_without_spending(tmp_path: Path, link_part: str) -> None:
    target = tmp_path / "public-reports"
    target.mkdir()
    private = tmp_path / "benchmarks" / "private"
    link = {"private": private, "benchmarks": private.parent, "firbench": private / "firbench"}[link_part]
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    frame = _frame()
    with pytest.raises(fc.NonPrivateOutputError):
        _read(frame, _token(frame), tmp_path)
    assert list(target.iterdir()) == []


# --- binding values stay in the manifest ------------------------------------


def test_module_has_no_numeric_literal_equal_to_binding_values() -> None:
    payload = _committed_payload()
    bound = {float(payload["primary"]["fpir_target"]), float(payload["alpha_family"])}
    bound |= {float(value) for value in payload["secondary_fpir_targets"]}
    bound |= {float(hypothesis["margin"]) for hypothesis in payload["hypotheses"]}
    bound |= {float(payload["planning_icc"]), float(payload["p_d"]), float(payload["power"])}
    bound |= {float(payload["min_n_independent"]), float(payload["cell_floor_n_independent"])}
    # Zero is structural (an H1 margin of 0 and bounds checks), so it is not a binding literal.
    bound -= {0.0, 1.0}
    found: list[object] = []
    with MODULE_PATH.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.NUMBER:
                value = ast.literal_eval(token.string)
                if float(value) in bound:
                    found.append(value)
    assert found == []


# --- interchange fixture sanity ---------------------------------------------


def test_end_to_end_on_fakes_seal_ratify_gate_and_single_sealed_read(tmp_path: Path) -> None:
    """Fake evidence is sealed, serialized, reloaded, bound to a verdict, and spent once."""
    manifest = fc.seal(_load_payload(tmp_path, _ratified_payload()), sealed_at=SEALED_AT)
    reloaded = _load_payload(tmp_path, dataclasses.asdict(manifest))
    assert reloaded == manifest
    manifest = reloaded
    decision_sha = fc.manifest_sha256(manifest)
    frame = manifest.frame("confirm-v1")

    with pytest.raises(fc.FrameContractError, match="registry"):
        fc.require_verdict_allowed(manifest, frame=dataclasses.replace(frame, source_sha256="a" * 64))
    assert not (tmp_path / "benchmarks" / "private").exists()
    fc.require_verdict_allowed(manifest, frame=frame)
    token = fc.UnsealToken(
        frame_id=frame.frame_id,
        frame_sha256="d" * 64,
        decision_sha256=decision_sha,
        run_id=RUN_ID,
        code_sha=CODE_SHA,
        scorer_sha=SCORER_SHA,
        consumed_at=None,
    )
    binding = {
        "decision_sha256": decision_sha,
        "run_id": RUN_ID,
        "code_sha": CODE_SHA,
        "scorer_sha": SCORER_SHA,
        "repo_root": tmp_path,
        "consumed_at": CONSUMED_AT,
    }
    consumed = fc.require_frame_read_allowed(frame, token, **binding)  # type: ignore[arg-type]
    assert consumed.consumed_at == CONSUMED_AT
    with pytest.raises(fc.SealedFrameReadError):
        fc.require_frame_read_allowed(frame, token, **binding)  # type: ignore[arg-type]


def test_interchange_fixtures_reference_no_private_paths() -> None:
    for name in INTERCHANGE_NAMES:
        text = (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
        assert "benchmarks/private" not in text
