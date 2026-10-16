"""FIRBENCH-1 S6a/S6b: CLI ``run``, ``score``, ``report``, ``compare`` and ``unseal``.

Synthetic identifiers only (``id-0001``, ``face-0001``). All pixels, source annotations and model responses are synthetic and live under a temporary
repository root. No operator private data or model weights are read.

Legacy run/unseal boundary cases use S0 collaborator fakes. Comparison cases and positive cases
use the ``real`` fixture: the actual S1-S3 default collaborators (frames, legs, scoring) with
synthetic pixels and fake model kernels only. In a positive case the score and compare
producers are never faked; only the git HEAD lookup and the attempt clock are fixed, as in every test.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import shutil
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from recognition import config
from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.config.settings import RecognitionSettings
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_cluster_io as cluster_io
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_legs as legs
from scripts.eval_harness import firbench_score_io as score_io
from scripts.eval_harness.firbench_contract import (
    Arm,
    CanaryInSealedRunError,
    FrameContractError,
    LegId,
    LegKind,
    NonPrivateOutputError,
    SealedFrameReadError,
    UnsealToken,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
COMMITTED_DECISION = REPO_ROOT / "benchmarks" / "manifests" / "fir-bench-decision-v1.json"
COMMITTED_GATE = REPO_ROOT / "benchmarks" / "manifests" / "fir-gate-contract-v1.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "firbench_interchange_v1"

HEAD_SHA = "1" * 40
SCORER_SHA = "2" * 64
ATTEMPT_AT = "2026-10-15T10:00:00+00:00"
RATIFIED_AT = "2026-10-15T08:00:00+00:00"
SEALED_AT = "2026-10-15T09:00:00+00:00"
SEAL_FRAME_SHA = "f" * 64
GT_FACE_IDS = ("face-0001", "face-0002", "face-0003")
SYNTHETIC_FRAME = "golden150-v1"
SEALED_FRAME = "confirm-v1"
LEGS = (LegKind.sface, LegKind.auraface, LegKind.insightface)
ARMS = (Arm.native, Arm.gt_crop_redetect)
REAL_FRAME = "fake-only"
# Small default for file-bound refusals; the eligible comparison uses 520 identities:
# five actual folds, then the actual G1/G2 enrollment split leave 52 mated test PSUs.
REAL_IDENTITIES = 30
ELIGIBLE_IDENTITIES = 520
REAL_CREATED_AT = "2026-10-15T09:00:00Z"
# The actual loader, captured before the autouse fakes below replace it.
_REAL_LOAD_COLLABORATORS = cli._load_collaborators


# --- fixtures and fakes ---------------------------------------------------------


def _leg_id(kind: LegKind, arm: Arm) -> LegId:
    return LegId(kind=kind, arm=arm, space_fingerprint="ab12cd", opencv_version="4.10.0", ort_version="1.18.0")


def _search_row(leg_key: str, arm: str, face_id: str, *, image_id: str, unit_id: str | None = None) -> dict[str, Any]:
    template = json.loads((FIXTURES / "face-search-record-v1.json").read_text(encoding="utf-8"))
    is_detection = unit_id is not None
    template.update(
        face_id=face_id,
        image_id=image_id,
        psu_id=f"psu-{image_id[-4:]}",
        identity_id=None if is_detection else "id-0001",
        unit_id=unit_id,
        leg_key=leg_key,
        arm=arm,
        timing_receipt_ref=f"{leg_key}/{arm}/{face_id}",
    )
    return template


def _fake_collaborators(**overrides: Any) -> cli.FirBenchCollaborators:
    def leg_keys(*, legs, arms, **_: Any) -> tuple[str, ...]:
        return tuple(sorted(_leg_id(kind, arm).key() for kind in legs for arm in arms))

    def run_legs(*, legs, arms, **_: Any) -> cli.LegRunResult:
        searches: dict[str, list[dict[str, Any]]] = {}
        ledger: dict[str, list[dict[str, Any]]] = {}
        timings: dict[str, float] = {}
        for kind in legs:
            for arm in arms:
                key = _leg_id(kind, arm).key()
                rows = [_search_row(key, arm.value, face, image_id="image-0001") for face in GT_FACE_IDS]
                rows.append(
                    _search_row(
                        key,
                        arm.value,
                        "det:image-0001:0",
                        image_id="image-0001",
                        unit_id="background:image-0001",
                    )
                )
                searches[key] = rows
                ledger[key] = [
                    {"face_id": face, "leg_key": key, "arm": arm.value, "stage_reached": "embedded"}
                    for face in GT_FACE_IDS
                ]
                for row in rows:
                    timings[row["timing_receipt_ref"]] = 12.5
        return cli.LegRunResult(
            gt_face_ids=GT_FACE_IDS,
            searches=searches,
            ledger=ledger,
            timings_ms=timings,
        )

    def score_run(run_dir: Path, *, decision: Any) -> dict[str, Any]:
        return json.loads((FIXTURES / "scores-v1.json").read_text(encoding="utf-8"))

    values: dict[str, Any] = {
        "leg_keys": leg_keys,
        "run_legs": run_legs,
        "score_run": score_run,
        "scorer_sha": SCORER_SHA,
        "similarity_threshold": 0.6,
    }
    values.update(overrides)
    return cli.FirBenchCollaborators(**values)


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> cli.FirBenchCollaborators:
    collaborators = _fake_collaborators()
    monkeypatch.setattr(cli, "_load_collaborators", lambda: collaborators)
    monkeypatch.setattr(cli, "_head_sha", lambda repo_root: HEAD_SHA)
    monkeypatch.setattr(cli, "_attempt_timestamp", lambda: ATTEMPT_AT)
    return collaborators


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "benchmarks" / "private" / "firbench").mkdir(parents=True)
    (root / "benchmarks" / "manifests").mkdir(parents=True)
    (root / "benchmarks" / "manifests" / COMMITTED_GATE.name).write_bytes(COMMITTED_GATE.read_bytes())
    return root


def _write_decision(
    repo: Path,
    *,
    ratified_at: str | None = None,
    sealed_at: str | None = None,
    sealed_frame_sha: str | None = None,
) -> Path:
    payload = json.loads(COMMITTED_DECISION.read_text(encoding="utf-8"))
    if ratified_at is not None:
        payload["ratification"] = {"decision_ref": "decision-0001", "ratified_at": ratified_at}
    if sealed_frame_sha is not None:
        for frame in payload["frames"]:
            if frame["frame_id"] == SEALED_FRAME:
                frame["source_sha256"] = sealed_frame_sha
    path = repo / "benchmarks" / "manifests" / "decision.json"
    if sealed_at is not None:
        # A sealed manifest needs every sealable field resolved (S0 Build 2). These synthetic
        # values exist only in this fixture; the seal hash is then taken over the final body.
        payload["gallery_lineage"]["templates_sha256"] = "e" * 64
        for frame in payload["frames"]:
            frame["source_sha256"] = frame["source_sha256"] or SEAL_FRAME_SHA
            frame["exhaustive"] = True
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if sealed_at is not None:
        payload["seal"] = {"sealed_at": sealed_at, "sha256": fc.manifest_sha256(fc.load_decision_manifest(path))}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _out_dir(repo: Path, parent: str = "runs/a") -> Path:
    return repo / "benchmarks" / "private" / "firbench" / parent / "run-0001"


def _run(
    repo: Path, *, decision: Path, out: Path, frame: str = SYNTHETIC_FRAME, legs=LEGS, arms=ARMS, created_at=None
) -> Path:
    return cli.run_frame(
        frame_id=frame,
        decision_path=decision,
        legs=tuple(legs),
        arms=tuple(arms),
        subset=None,
        subset_seed=None,
        out_dir=out,
        repo_root=repo,
        created_at=created_at,
    )


def _write_unseal_token(
    repo: Path, *, frame: str, decision_sha: str, run_id: str, consumed_at: str | None = None
) -> None:
    token = UnsealToken(
        frame_id=frame,
        frame_sha256=SEAL_FRAME_SHA,
        decision_sha256=decision_sha,
        run_id=run_id,
        code_sha=HEAD_SHA,
        scorer_sha=SCORER_SHA,
        consumed_at=consumed_at,
    )
    ledger = repo / "benchmarks" / "private" / "firbench" / "unseal-ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(token), sort_keys=True) + "\n")


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): _sha_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


# --- refusals before any output -----------------------------------------------------


def test_run_refuses_non_private_out_dir_and_writes_nothing(repo: Path) -> None:
    decision = _write_decision(repo)
    out = repo / "benchmarks" / "reports" / "run-0001"

    with pytest.raises(NonPrivateOutputError):
        _run(repo, decision=decision, out=out)

    assert not out.exists()


def test_run_refuses_nonempty_run_dir_and_leaves_it_untouched(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)
    out.mkdir(parents=True)
    keeper = out / "keep.txt"
    keeper.write_text("prior run", encoding="utf-8")

    with pytest.raises(FrameContractError):
        _run(repo, decision=decision, out=out)

    assert _snapshot(out) == {"keep.txt": _sha_file(keeper)}


def test_run_refuses_canary_leg_on_sealed_frame_before_consumption(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)
    decision_sha = _sha_file(decision)
    _write_unseal_token(repo, frame=SEALED_FRAME, decision_sha=decision_sha, run_id="run-0001")
    out = _out_dir(repo)

    with pytest.raises(CanaryInSealedRunError):
        _run(repo, decision=decision, out=out, frame=SEALED_FRAME, legs=(LegKind.canary,), created_at=None)

    assert not out.exists()
    assert not (repo / "benchmarks" / "private" / "firbench" / "spent").exists()


def test_sealed_run_without_unspent_token_raises_and_writes_nothing(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)
    out = _out_dir(repo)

    with pytest.raises(SealedFrameReadError):
        _run(repo, decision=decision, out=out, frame=SEALED_FRAME)

    assert not out.exists()


def test_sealed_token_naming_another_run_raises_and_writes_nothing(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)
    _write_unseal_token(repo, frame=SEALED_FRAME, decision_sha=_sha_file(decision), run_id="run-9999")
    out = _out_dir(repo)

    with pytest.raises(SealedFrameReadError):
        _run(repo, decision=decision, out=out, frame=SEALED_FRAME)

    assert not out.exists()


def test_sealed_run_records_attempt_time_and_refuses_second_read(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)
    _write_unseal_token(repo, frame=SEALED_FRAME, decision_sha=_sha_file(decision), run_id="run-0001")
    out = _out_dir(repo)

    _run(repo, decision=decision, out=out, frame=SEALED_FRAME)

    ledger_rows = [
        json.loads(line) for line in (repo / "benchmarks/private/firbench/unseal-ledger.jsonl").read_text().splitlines()
    ]
    consumed = [row for row in ledger_rows if row["consumed_at"] is not None]
    assert [row["consumed_at"] for row in consumed] == [ATTEMPT_AT]
    assert ATTEMPT_AT != SEALED_AT
    assert (repo / "benchmarks/private/firbench/spent" / f"{SEALED_FRAME}.spent").exists()

    second = _out_dir(repo, parent="runs/b")
    _write_unseal_token(repo, frame=SEALED_FRAME, decision_sha=_sha_file(decision), run_id="run-0001")
    with pytest.raises(SealedFrameReadError):
        _run(repo, decision=decision, out=second, frame=SEALED_FRAME)
    assert not second.exists()


# --- created_at seam ----------------------------------------------------------------------


def test_no_created_at_source_raises_and_writes_nothing(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)

    with pytest.raises(FrameContractError):
        _run(repo, decision=decision, out=out)

    assert not out.exists()


@pytest.mark.parametrize("literal", ["2026-10-15T09:00:00", "not-a-timestamp"])
def test_naive_or_malformed_created_at_refused_before_writes(repo: Path, literal: str) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT)
    out = _out_dir(repo)

    with pytest.raises(FrameContractError):
        _run(repo, decision=decision, out=out, created_at=literal)

    assert not out.exists()


def test_explicit_created_at_without_derived_source_is_used(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)

    _run(repo, decision=decision, out=out, created_at="2026-10-15T09:00:00Z")

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["firbench"]["created_at"] == SEALED_AT
    assert manifest["firbench"]["created_at_source"] == "explicit"


def test_seal_is_selected_over_ratification_and_equivalent_offset_accepted(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)
    out = _out_dir(repo)
    equivalent = "2026-10-15T11:00:00+02:00"

    _run(repo, decision=decision, out=out, created_at=equivalent)

    firbench = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["firbench"]
    assert firbench["created_at"] == SEALED_AT
    assert firbench["created_at_source"] == "seal.sealed_at"


def test_explicit_matching_only_ratification_is_refused_when_sealed(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)
    out = _out_dir(repo)

    with pytest.raises(FrameContractError):
        _run(repo, decision=decision, out=out, created_at=RATIFIED_AT)

    assert not out.exists()


def test_ratification_is_selected_when_unsealed(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT)
    out = _out_dir(repo)

    _run(repo, decision=decision, out=out)

    firbench = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["firbench"]
    assert firbench["created_at"] == RATIFIED_AT
    assert firbench["created_at_source"] == "ratification.ratified_at"


# --- artifacts, ledger and determinism -------------------------------------------------


def test_run_then_score_writes_full_layout_with_one_ledger_row_per_face_leg_arm(real) -> None:
    out = _real_run(real, "run-layout", _real_decision(real, "decision"))
    scores_path = cli.score_run(out, repo_root=real.repo)
    assert scores_path == out / "scores.json"
    for name in ("manifest.json", "timings.json", "frame.json"):
        assert (out / name).is_file()
    fc.validate_interchange("scores-v1", json.loads(scores_path.read_text()))
    leg_keys = json.loads((out / "manifest.json").read_text())["firbench"]["leg_keys"]
    assert len(leg_keys) == len(LEGS) * len(ARMS)
    for key in leg_keys:
        rows = [json.loads(line) for line in (out / "ledger" / f"{key}.jsonl").read_text().splitlines()]
        assert len(rows) == real.n_identities
        assert sorted(row["face_id"] for row in rows) == [f"face-{i:04d}" for i in range(real.n_identities)]
        assert all(not row["face_id"].startswith("det:") for row in rows)


def test_two_runs_on_pinned_inputs_yield_identical_semantic_artifacts(real) -> None:
    decision = _real_decision(real, "decision")
    first = _real_run(real, "a/run-0001", decision)
    second = _real_run(real, "b/run-0001", decision)

    def semantic(root: Path) -> dict[str, str]:
        return {
            rel: digest
            for rel, digest in _snapshot(root).items()
            if rel in {"manifest.json", "frame.json"} or rel.endswith("searches.jsonl") or rel.startswith("ledger/")
        }

    assert semantic(first) == semantic(second)
    assert semantic(first)
    originals = {path: _snapshot(path) for path in (first, second)}
    # Full score replay needs one pinned receipt. Preserve both original cold receipts;
    # explicit verification snapshots are the only files receiving the shared receipt.
    snapshots = [real.private / name / "run-0001" for name in ("verify-a", "verify-b")]
    pinned_receipt = (first / "timings.json").read_bytes()
    for original, snapshot in zip((first, second), snapshots, strict=True):
        shutil.copytree(original, snapshot)
        (snapshot / "timings.json").write_bytes(pinned_receipt)
        cli.score_run(snapshot, repo_root=real.repo)
    assert (snapshots[0] / "scores.json").read_bytes() == (snapshots[1] / "scores.json").read_bytes()
    assert all(_snapshot(original) == before for original, before in originals.items())


def test_score_refuses_a_decision_whose_sha_differs_from_the_run(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)
    _run(repo, decision=decision, out=out, created_at="2026-10-15T09:00:00Z")
    _write_decision(repo, ratified_at=RATIFIED_AT)  # same path, different bytes

    with pytest.raises(FrameContractError):
        cli.score_run(out, repo_root=repo)

    assert not (out / "scores.json").exists()


def test_score_never_rewrites_timings(real) -> None:
    out = _real_run(real, "run-timings", _real_decision(real, "decision"))
    before = _sha_file(out / "timings.json")
    cli.score_run(out, repo_root=real.repo)
    assert _sha_file(out / "timings.json") == before


def test_collaborator_load_failure_refuses_before_any_write(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable() -> cli.FirBenchCollaborators:
        raise fc.FrameContractError("S1-S3 collaborators cannot be loaded for this run")

    monkeypatch.setattr(cli, "_load_collaborators", unavailable)
    decision = _write_decision(repo)
    out = _out_dir(repo)

    with pytest.raises(fc.FrameContractError, match="cannot be loaded"):
        _run(repo, decision=decision, out=out, created_at="2026-10-15T09:00:00Z")

    assert not out.exists()


def test_unreadable_decision_path_is_a_contract_error(repo: Path) -> None:
    out = _out_dir(repo)

    with pytest.raises(FrameContractError):
        _run(
            repo,
            decision=repo / "benchmarks" / "manifests" / "missing.json",
            out=out,
            created_at="2026-10-15T09:00:00Z",
        )

    assert not out.exists()


def test_only_the_attempt_boundary_reads_the_wall_clock() -> None:
    """Static scan (FLOW-18, MCP 16773): clock and entropy calls are confined to ``_attempt_timestamp``."""
    module = Path(cli.__file__)
    tree = ast.parse(module.read_text(encoding="utf-8"))
    banned = {"now", "utcnow", "time", "uuid4", "uuid1", "random", "token_hex", "urandom"}
    offenders: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in banned and (not self.scope or self.scope[-1] != "_attempt_timestamp"):
                offenders.append(f"{name}@{node.lineno}")
            self.generic_visit(node)

    Visitor().visit(tree)
    assert offenders == []


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_timing_refuses_without_semantic_outputs(repo, monkeypatch, fakes, value):
    def invalid(**kwargs):
        result = fakes.run_legs(**kwargs)
        timings = dict(result.timings_ms)
        timings[next(iter(timings))] = value
        return dataclasses.replace(result, timings_ms=timings)

    monkeypatch.setattr(cli, "_load_collaborators", lambda: _fake_collaborators(run_legs=invalid))
    out = _out_dir(repo)
    with pytest.raises(FrameContractError, match="finite non-negative"):
        _run(repo, decision=_write_decision(repo), out=out, created_at=SEALED_AT)
    assert _snapshot(out) == {}


@pytest.mark.parametrize("sealed", [False, True])
@pytest.mark.parametrize("existing_empty", [False, True])
def test_concurrent_runs_have_one_owner_before_any_spend(repo, monkeypatch, fakes, sealed, existing_empty):
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT if sealed else None)
    out = _out_dir(repo)
    if existing_empty:
        out.mkdir(parents=True)
    if sealed:
        _write_unseal_token(repo, frame=SEALED_FRAME, decision_sha=_sha_file(decision), run_id=out.name)
    barrier = threading.Barrier(2, timeout=10)
    loser_done = threading.Event()
    fresh = cli._require_fresh_run_dir
    spend = cli.require_frame_read_allowed
    spends = []
    runners = []

    def synchronized_fresh(*args, **kwargs):
        result = fresh(*args, **kwargs)
        barrier.wait()
        return result

    def spending(*args, **kwargs):
        spends.append(kwargs)
        if len(spends) == 1:
            assert loser_done.wait(10)
        return spend(*args, **kwargs)

    def running(**kwargs):
        runners.append(kwargs)
        if not sealed:
            assert loser_done.wait(10)
        return fakes.run_legs(**kwargs)

    monkeypatch.setattr(cli, "_require_fresh_run_dir", synchronized_fresh)
    monkeypatch.setattr(cli, "require_frame_read_allowed", spending)
    monkeypatch.setattr(cli, "_load_collaborators", lambda: _fake_collaborators(run_legs=running))

    def attempt():
        try:
            return _run(repo, decision=decision, out=out, frame=SEALED_FRAME if sealed else SYNTHETIC_FRAME)
        except Exception as exc:
            loser_done.set()
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results.count(out) == 1
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1 and type(errors[0]) is FrameContractError
    assert len(runners) == 1
    assert len(spends) == int(sealed)
    if sealed:
        assert set(spends[0]) == {"decision_sha256", "run_id", "code_sha", "scorer_sha", "repo_root", "consumed_at"}
        assert spends[0]["consumed_at"] == ATTEMPT_AT
    assert (out / "timings.json").is_file()


@pytest.mark.parametrize("redirect", ["ledger", "firbench", "private", "benchmarks"])
def test_unseal_ledger_containment_is_checked_before_read(repo, tmp_path, monkeypatch, redirect):
    _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT)
    ledger = repo / cli._UNSEAL_LEDGER
    outside = tmp_path / "outside"
    outside.mkdir()
    if redirect == "ledger":
        target = outside / ledger.name
        target.write_text("private bytes", encoding="utf-8")
        ledger.symlink_to(target)
    else:
        link = {"firbench": ledger.parent, "private": ledger.parent.parent, "benchmarks": repo / "benchmarks"}[redirect]
        moved = outside / link.name
        link.rename(moved)
        link.symlink_to(moved, target_is_directory=True)
    reads = []
    read_text = Path.read_text

    def observe(path, *args, **kwargs):
        if path.name == ledger.name:
            reads.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", observe)
    # Directly exercise the private input boundary, including redirected decision parents.
    with pytest.raises(NonPrivateOutputError):
        cli._read_unseal_ledger(repo)
    assert reads == []
    assert not _out_dir(repo).exists()


def test_unseal_ledger_read_io_failure_is_not_a_missing_token(repo, monkeypatch):
    ledger = repo / cli._UNSEAL_LEDGER
    ledger.write_text("", encoding="utf-8")
    read_text = Path.read_text

    def deny(path, *args, **kwargs):
        if path == ledger:
            raise PermissionError("ledger denied")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(SealedFrameReadError, match="cannot read.*ledger denied"):
        cli._read_unseal_ledger(repo)


def test_writer_io_failure_is_a_named_contract_error(repo, monkeypatch):
    out = _out_dir(repo)
    original = Path.open

    def deny(path, *args, **kwargs):
        if path.name == "manifest.json":
            raise PermissionError("artifact denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(FrameContractError, match="artifact denied"):
        _run(repo, decision=_write_decision(repo), out=out, created_at=SEALED_AT)


def test_existing_empty_run_directory_is_allowed(repo):
    out = _out_dir(repo)
    out.mkdir(parents=True)
    assert _run(repo, decision=_write_decision(repo), out=out, created_at=SEALED_AT) == out


@pytest.mark.parametrize("existing_empty", [False, True])
def test_failed_sealed_authorization_releases_claim_without_deleting_work(repo, monkeypatch, existing_empty):
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT)
    out = _out_dir(repo)
    if existing_empty:
        out.mkdir(parents=True)
    before = _snapshot(repo)
    with pytest.raises(SealedFrameReadError):
        _run(repo, decision=decision, out=out, frame=SEALED_FRAME)
    assert _snapshot(repo) == before
    assert out.exists() == existing_empty

    def foreign_work(*args, **kwargs):
        out.mkdir(parents=True, exist_ok=True)
        (out / "foreign.txt").write_text("another process", encoding="utf-8")
        raise SealedFrameReadError("read refused")

    monkeypatch.setattr(cli, "require_frame_read_allowed", foreign_work)
    with pytest.raises(SealedFrameReadError, match="read refused"):
        _run(repo, decision=decision, out=out, frame=SEALED_FRAME)
    assert (out / "foreign.txt").read_text() == "another process"


def test_claim_io_failure_precedes_sealed_spend(repo, monkeypatch):
    decision = _write_decision(repo, ratified_at=RATIFIED_AT, sealed_at=SEALED_AT)
    out = _out_dir(repo)
    _write_unseal_token(repo, frame=SEALED_FRAME, decision_sha=_sha_file(decision), run_id=out.name)
    original = Path.mkdir

    def deny(path, *args, **kwargs):
        if path == out.parent:
            raise PermissionError("claim directory denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(FrameContractError, match="claim directory denied"):
        _run(repo, decision=decision, out=out, frame=SEALED_FRAME)
    assert not (repo / "benchmarks/private/firbench/spent").exists()
    assert not out.exists()


def test_score_writer_io_failure_preserves_receipt_and_existing_score(real, monkeypatch):
    out = _real_run(real, "run-score-writer", _real_decision(real, "decision"))
    cli.score_run(out, repo_root=real.repo)
    before = _snapshot(out)

    def deny(*args, **kwargs):
        raise PermissionError("score replace denied")

    monkeypatch.setattr(cli.os, "replace", deny)
    with pytest.raises(FrameContractError, match="score replace denied"):
        cli.score_run(out, repo_root=real.repo)
    assert _snapshot(out) == before


# --- S6b: unseal, report and compare -------------------------------------------------

UNSEAL_LEDGER = Path("benchmarks") / "private" / "firbench" / "unseal-ledger.jsonl"
COMPARE_OUT = Path("benchmarks") / "private" / "firbench" / "compare" / "out"


def _sealed_decision(repo: Path, *, ratified_at: str | None = RATIFIED_AT) -> Path:
    return _write_decision(repo, ratified_at=ratified_at, sealed_at=SEALED_AT, sealed_frame_sha=SEAL_FRAME_SHA)


def _unseal_rows(repo: Path) -> list[dict[str, Any]]:
    ledger = repo / UNSEAL_LEDGER
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]


def _unseal(repo: Path, decision: Path, *, frame: str = SEALED_FRAME, run_id: str = "run-0001") -> str:
    return cli.unseal_frame(decision_path=decision, frame_id=frame, run_id=run_id, repo_root=repo)


def test_unseal_refuses_an_unratified_decision_and_appends_nothing(repo: Path) -> None:
    decision = _sealed_decision(repo, ratified_at=None)
    with pytest.raises(fc.UnratifiedDecisionError):
        _unseal(repo, decision)
    assert _unseal_rows(repo) == []


def test_unseal_refuses_an_unsealed_decision_for_a_sealed_frame(repo: Path) -> None:
    decision = _write_decision(repo, ratified_at=RATIFIED_AT)
    with pytest.raises(fc.SealedFrameReadError):
        _unseal(repo, decision)
    assert _unseal_rows(repo) == []


def test_unseal_refuses_a_frame_that_is_not_sealed(repo: Path) -> None:
    decision = _sealed_decision(repo)
    with pytest.raises(FrameContractError, match=SYNTHETIC_FRAME):
        _unseal(repo, decision, frame=SYNTHETIC_FRAME)
    assert _unseal_rows(repo) == []


def test_unseal_appends_one_unspent_token_bound_to_the_decision_and_run(repo: Path) -> None:
    decision = _sealed_decision(repo)
    token_ref = _unseal(repo, decision)
    assert _unseal_rows(repo) == [
        {
            "frame_id": SEALED_FRAME,
            "frame_sha256": SEAL_FRAME_SHA,
            "decision_sha256": _sha_file(decision),
            "run_id": "run-0001",
            "code_sha": HEAD_SHA,
            "scorer_sha": SCORER_SHA,
            "consumed_at": None,
        }
    ]
    assert token_ref == cli._token_ref(fc.UnsealToken(**_unseal_rows(repo)[0]))
    # Unsealing never spends the frame, creates a run directory or writes a run manifest.
    assert not (repo / "benchmarks/private/firbench/spent").exists()
    assert not (repo / "benchmarks/private/firbench/runs").exists()


def test_unseal_refuses_a_second_call_for_the_same_frame_and_decision(repo: Path) -> None:
    decision = _sealed_decision(repo)
    _unseal(repo, decision, run_id="run-0001")
    with pytest.raises(fc.SealedFrameReadError):
        _unseal(repo, decision, run_id="run-0002")
    assert len(_unseal_rows(repo)) == 1


def test_unseal_refuses_a_new_decision_sha_for_a_frame_that_already_has_a_token(repo: Path) -> None:
    decision = _sealed_decision(repo)
    _unseal(repo, decision)
    before = _sha_file(decision)
    other = _sealed_decision(repo, ratified_at="2026-10-15T08:30:00+00:00")
    assert _sha_file(other) != before
    with pytest.raises(fc.SealedFrameReadError):
        _unseal(repo, other, run_id="run-0002")
    assert len(_unseal_rows(repo)) == 1


def test_concurrent_unseal_of_one_frame_has_exactly_one_winner(repo: Path) -> None:
    decision = _sealed_decision(repo)

    def attempt(run_id: str) -> str:
        try:
            _unseal(repo, decision, run_id=run_id)
        except fc.SealedFrameReadError:
            return "refused"
        return "appended"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, ["run-0001", "run-0002"]))
    assert outcomes == ["appended", "refused"]
    assert len(_unseal_rows(repo)) == 1


def test_report_refuses_a_run_dir_outside_benchmarks_private_before_rendering(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    fake = types.ModuleType("scripts.eval_harness.firbench_report")
    fake.render_report = lambda *args, **kwargs: calls.append("render")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.eval_harness.firbench_report", fake)
    run_dir = tmp_path / "outside" / "run-0001"
    run_dir.mkdir(parents=True)
    with pytest.raises(fc.NonPrivateOutputError):
        cli.report_run(run_dir, include_crops=False, repo_root=repo)
    assert calls == []
    assert list(run_dir.iterdir()) == []


def test_report_materializes_clusters_then_renders_into_the_run_report_dir(repo: Path, monkeypatch) -> None:
    """Unit spy: call order only. ``materialize_clusters`` is defined in ``firbench_cluster_io``."""
    run = _run(repo, decision=_write_decision(repo), out=_out_dir(repo), created_at=RATIFIED_AT)
    order: list[tuple[str, Any]] = []
    monkeypatch.setattr(cluster_io, "materialize_clusters", lambda run_dir: order.append(("clusters", Path(run_dir))))
    report = types.ModuleType("scripts.eval_harness.firbench_report")

    def render_report(run_dir: Path, *, out_dir: Path, include_crops: bool = False) -> Path:
        order.append(("render", (Path(run_dir), Path(out_dir), include_crops)))
        return Path(out_dir) / "index.html"

    report.render_report = render_report  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.eval_harness.firbench_report", report)
    index = cli.report_run(run, include_crops=True, repo_root=repo)
    assert index == run / "report" / "index.html"
    assert order == [
        ("clusters", run),
        ("render", (run, run / "report", True)),
    ]


def test_report_make_target_runs_the_cli_without_an_eval_flag() -> None:
    text = (REPO_ROOT / "mk" / "evals.mk").read_text(encoding="utf-8")
    for target in ("fir-bench-report", "fir-bench-compare", "fir-bench-unseal"):
        assert f"\n{target}:" in text, target
    recipe = text.split("\nfir-bench-report:", 1)[1].split("\n## ", 1)[0]
    assert "firbench_cli report" in recipe
    assert "--extra dev" in recipe
    assert "ACX_EVAL_BENCH" not in recipe


def test_parser_exposes_report_compare_and_unseal_subcommands() -> None:
    parser = cli._build_parser()
    assert parser.parse_args(["report", "run-dir"]).command == "report"
    compare = parser.parse_args(["compare", "a", "b", "--out", "o", "--treatment", "arm"])
    assert (compare.command, compare.treatment) == ("compare", "arm")
    unseal = parser.parse_args(["unseal", "--decision", "d.json", "--frame", "confirm-v1", "--run-id", "r"])
    assert (unseal.command, unseal.frame, unseal.run_id) == ("unseal", "confirm-v1", "r")


# --- compare: compatibility refusals (AE-9) ---------------------------------------


def _tamper_firbench(run: Path, mutate: Any) -> None:
    """Write a manifest whose firbench block carries producer-shaped gallery membership."""
    path = run / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload["firbench"])
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _assert_comparison_refused(real, run_a, run_b, field, *, treatment=None):
    before = _snapshot(real.repo)
    with pytest.raises(FrameContractError, match=field):
        _compare_real(real, run_a, run_b, treatment=treatment)
    assert _snapshot(real.repo) == before
    assert not (real.repo / COMPARE_OUT).exists()


def _different_frame_pair(real):
    def second_frame(payload):
        alternate = dict(payload["frames"][0], frame_id="other-synthetic-frame")
        payload["frames"].append(alternate)

    binding = real.private / "inputs" / f"{REAL_FRAME}.json"
    binding.with_name("other-synthetic-frame.json").write_bytes(binding.read_bytes())
    decision = _real_decision(real, "decision", second_frame)
    a = _real_run(real, "run-a", decision)
    b = _real_run(real, "run-b", decision, frame="other-synthetic-frame")
    _score_both(real, a, b)
    return a, b


def test_compare_refuses_a_frame_mismatch_naming_the_field_and_writes_nothing(real):
    _assert_comparison_refused(real, *_different_frame_pair(real), "frame_id")


def test_compare_refuses_a_boundary_mismatch_naming_the_field(real):
    a = _real_decision(real, "decision-a")
    b = _real_decision(real, "decision-b", lambda p: p.update(boundary_semantics="legacy_v1"))
    runs = _real_pair(real, a, b)
    _assert_comparison_refused(real, *runs, "boundary_semantics")


@pytest.mark.parametrize("runtime_field", ["opencv_version", "ort_version"])
@pytest.mark.parametrize("treatment", [None, "fpir_target"])
def test_compare_refuses_a_runtime_mismatch_naming_the_runtime_field(real, runtime_field, treatment):
    decision = _real_decision(real, "decision")
    a = _real_run(real, "run-a", decision)
    setattr(real.state, runtime_field, "changed-fake-runtime")
    b = _real_run(real, "run-b", decision)
    _score_both(real, a, b)
    _assert_comparison_refused(real, a, b, runtime_field, treatment=treatment)


@pytest.mark.parametrize("treatment", ["fpir_target", "arm"])
def test_compare_frame_mismatch_stays_refused_with_treatment(real, treatment):
    _assert_comparison_refused(real, *_different_frame_pair(real), "frame_id", treatment=treatment)


def test_compare_boundary_mismatch_stays_refused_with_treatment(real):
    a = _real_decision(real, "decision-a")
    b = _real_decision(real, "decision-b", lambda p: p.update(boundary_semantics="legacy_v1"))
    _assert_comparison_refused(real, *_real_pair(real, a, b), "boundary_semantics", treatment="fpir_target")


def test_compare_refuses_fpir_target_change_unless_declared_as_treatment(real):
    a = _real_decision(real, "decision-a", lambda p: p["primary"].update(fpir_target=0.05))
    b = _real_decision(real, "decision-b")
    _assert_comparison_refused(real, *_real_pair(real, a, b), "fpir_target")


def test_compare_refuses_a_native_versus_gt_crop_arm_change_unless_declared(real):
    decision = _real_decision(real, "decision")
    a = _real_run(real, "run-a", decision, arms=(Arm.native,))
    b = _real_run(real, "run-b", decision)
    _score_both(real, a, b)
    _assert_comparison_refused(real, a, b, "arm")


def test_compare_refuses_a_gallery_snapshot_mismatch(real):
    decision = _real_decision(real, "decision")
    run_a, run_b = _real_pair(real, decision, decision)
    _tamper_firbench(run_a, lambda fb: fb["gallery_membership"][0].update(gallery_sha256="b" * 64))
    _assert_comparison_refused(real, run_a, run_b, "gallery_sha256")


def test_compare_refuses_an_enrolment_allocation_change(real):
    decision = _real_decision(real, "decision")
    run_a, run_b = _real_pair(real, decision, decision)
    # Run scope is a declared input to allocation; changing it cannot be hidden as a treatment.
    _tamper_firbench(run_b, lambda fb: fb.update(subset="undeclared-subset"))
    _assert_comparison_refused(real, run_a, run_b, "enrolment_probe_allocation")


def test_compare_refuses_a_fold_policy_change(real):
    a = _real_decision(real, "decision-a")
    b = _real_decision(real, "decision-b", lambda p: p["fold_protocol"].update(seed=1))
    # Actual reallocation also changes persisted frame bytes: the never-treatable boundary wins.
    _assert_comparison_refused(real, *_real_pair(real, a, b), "frame_bytes_sha256")


def test_compare_refuses_an_estimand_change(real):
    a = _real_decision(real, "decision-a", lambda p: p["primary"].update(estimand="paired delta FNIR"))
    b = _real_decision(real, "decision-b", lambda p: p["primary"].update(estimand="paired delta FPIR"))
    _assert_comparison_refused(real, *_real_pair(real, a, b), "estimand")


# --- positive cases: actual S1-S3 producers, fake pixels and model kernels only ----------------


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request) -> types.SimpleNamespace:
    """Actual S0-S3 through the default collaborators; fake pixels and model kernels only.

    The binding names one population source and one template inventory, both hash-bound in the
    decision. Each fake kernel returns the deterministic vector named by its pixel marker, so every query
    matches its own template and the outcomes are known in closed form. No model weight is read.
    """
    import cv2

    from scripts.eval_harness import firbench_runtime as runtime

    repo = tmp_path / "repo"
    private = repo / "benchmarks" / "private" / "firbench"
    manifests = repo / "benchmarks" / "manifests"
    private.mkdir(parents=True)
    manifests.mkdir(parents=True)
    (manifests / COMMITTED_GATE.name).write_bytes(COMMITTED_GATE.read_bytes())
    images, faces, templates, query_images = [], [], [], {}
    n_identities = getattr(request, "param", REAL_IDENTITIES)
    for index in range(n_identities):
        for purpose in ("query", "template"):
            pixels = np.zeros((24, 24, 3), dtype=np.uint8)
            pixels[:, :, 0] = index % 256
            pixels[:, :, 2] = index // 256
            pixels[0, 0, 1] = 1 if purpose == "query" else 2
            ok, encoded = cv2.imencode(".png", pixels)
            assert ok
            path = private / f"{purpose}-{index:04d}.png"
            path.write_bytes(encoded.tobytes())
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            relative = path.relative_to(repo).as_posix()
            if purpose == "query":
                image_id = f"image-{index:04d}"
                query_images[image_id] = {"path": relative, "media_ids": [index]}
                images.append(
                    {
                        "image_id": image_id,
                        "sha256": sha,
                        "sampling_arm": "probability",
                        "inclusion_probability": 1.0,
                        "duplicate_group": None,
                        "synthetic_parent_id": image_id,
                    }
                )
                faces.append(
                    {
                        "face_id": f"face-{index:04d}",
                        "image_id": image_id,
                        "box": [0, 0, 24, 24],
                        "identity_status": "named",
                        "identity_id": f"id-{index:04d}",
                        "cohort": None,
                        "annotation": {
                            "occluders": ["mask", "sunglasses"] if index % 2 else [],
                            "visibility": dict.fromkeys(("left_eye", "right_eye", "nose", "mouth"), "visible"),
                            "annotation_tier": "b",
                            "exhaustive": True,
                            "provenance_ref": "synthetic:generated-box-and-identity",
                            "rule_id": "synthetic:one-face-per-image",
                            "qc_ref": "synthetic:closed-form-construction",
                        },
                    }
                )
            else:
                templates.append(
                    {
                        "template_id": f"template-{index:04d}",
                        "identity_id": f"id-{index:04d}",
                        "media_ids": [1000 + index],
                        "path": relative,
                        "sha256": sha,
                        "box": [0, 0, 24, 24],
                        "occluders": [],
                    }
                )
    source = private / "source.json"
    source_sha = write_json(source, {"images": images, "faces": faces})
    template_path = private / "templates.json"
    template_sha = write_json(template_path, {"schema": "firbench-templates/v1", "templates": templates})
    binding = {
        "schema": "firbench-inputs/v1",
        "query_source": {
            "kind": "population_draft",
            "path": source.relative_to(repo).as_posix(),
            "sha256": source_sha,
        },
        "gallery_templates": {"path": template_path.relative_to(repo).as_posix(), "sha256": template_sha},
        "query_images": query_images,
    }
    write_json(private / "inputs" / f"{REAL_FRAME}.json", binding)
    base = json.loads(COMMITTED_DECISION.read_text(encoding="utf-8"))
    base["frames"] = [
        {
            "frame_id": REAL_FRAME,
            "admissibility": "development",
            "sealed": False,
            "source_sha256": source_sha,
            "exhaustive": True,
        }
    ]
    base["gallery_lineage"]["templates_sha256"] = template_sha
    settings = RecognitionSettings()
    settings.face_pipeline.profile = "face_pipeline"
    settings.face_pipeline.face_similarity_threshold = 0.73
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_load_collaborators", _REAL_LOAD_COLLABORATORS)
    state = types.SimpleNamespace(
        run=None, opencv_version="fake-cv", ort_version="fake-ort", changed_kind=None, missing_queries=set()
    )  # the run directory currently being written

    def vector(pixel, dimensions):
        index = int(pixel[0, 0, 0]) + 256 * int(pixel[0, 0, 2])
        # An exact binary codebook keeps the real threshold sweep small. Sixteen
        # nonzero +/-1 entries have norm 4, so cosine scores lie exactly on a
        # finite grid; each identity still has a unique vector and self-score 1.
        result = np.zeros(dimensions)
        result[:16] = [1.0 if index & (1 << bit) else -1.0 for bit in range(16)]
        return result

    def factory(kind, *, models_dir, embedder_models_dir=None):
        dimensions = 128 if kind is fc.LegKind.sface else 512

        class Detector:
            def detect(self, batch):
                for pixel in batch:
                    if pixel[0, 0, 1] == 1:
                        # Query outcomes are computed only after the complete declaration is durable.
                        assert (state.run / "frame.json").is_file()
                return [
                    []
                    if (
                        int(pixel[0, 0, 0]) + 256 * int(pixel[0, 0, 2]) in state.missing_queries and pixel[0, 0, 1] == 1
                    )
                    else [types.SimpleNamespace(bbox=(0, 0, 24, 24), landmarks=np.zeros((5, 2)), score=1.0)]
                    for pixel in batch
                ]

        class Embedder:
            embedding_dim = dimensions

            def embed(self, batch):
                values = np.array([vector(p, dimensions) for p in batch])
                if kind is state.changed_kind:
                    values = values[:, ::-1].copy()
                return types.SimpleNamespace(vectors=values)

        return legs.build_face_pipeline_leg(
            kind,
            manifest=EmbeddingModelManifest("fake", kind.value, dimensions, "l2", "cosine"),
            detector=Detector(),
            aligner=types.SimpleNamespace(align=lambda p, _: types.SimpleNamespace(crop=p)),
            embedder=Embedder(),
            weights_sha256=hashlib.sha256(
                (kind.value + (":changed-synthetic-kernel" if kind is state.changed_kind else "")).encode()
            ).hexdigest(),
            preprocessing=None,
            opencv_version=state.opencv_version,
            ort_version=state.ort_version,
        )

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", factory)

    def buffalo(_settings):
        detection = legs.DetectedFace((0, 0, 24, 24), np.zeros((5, 2)), 1.0)

        def process(pixel):
            if pixel[0, 0, 1] == 1:
                assert (state.run / "frame.json").is_file()
                if int(pixel[0, 0, 0]) + 256 * int(pixel[0, 0, 2]) in state.missing_queries:
                    return []
            return [
                {
                    "bbox_px": detection.bbox_px,
                    "landmarks_px": detection.landmarks_px,
                    "det_score": 1.0,
                    "embedding": vector(pixel, 512),
                }
            ]

        return legs.BuffaloLeg(
            process=process,
            embedding_dim=512,
            weights_sha256="b" * 64,
            opencv_version=state.opencv_version,
            ort_version=state.ort_version,
        )

    monkeypatch.setattr(runtime, "_load_buffalo_leg", buffalo)
    return types.SimpleNamespace(repo=repo, private=private, base=base, state=state, n_identities=n_identities)


def _real_decision(real: types.SimpleNamespace, name: str, mutate: Any = None, *, sealed=False) -> Path:
    """Actual bindings, optionally sealed with a SYNTHETIC ratification reference.

    This models the complete decision API, never an operator ratification, human
    observation or real ground truth. The development frame stays open for two runs;
    sealing a decision does not falsely authorize a second read of a sealed frame.
    """
    payload = json.loads(json.dumps(real.base))
    if mutate is not None:
        mutate(payload)
    if sealed:
        payload["ratification"] = {"decision_ref": "synthetic:fixture-ratification-only", "ratified_at": RATIFIED_AT}
    path = real.repo / "benchmarks" / "manifests" / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if sealed:
        decision = fc.seal(fc.load_decision_manifest(path), sealed_at=SEALED_AT)
        payload["seal"] = dataclasses.asdict(decision.seal)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        validated = fc.load_decision_manifest(path)
        fc.require_verdict_allowed(validated, frame=validated.frame(REAL_FRAME))
    return path


def _real_run(real: types.SimpleNamespace, name: str, decision: Path, *, frame=REAL_FRAME, arms=ARMS) -> Path:
    out = real.private / "runs" / name
    real.state.run = out
    return cli.run_frame(
        frame_id=frame,
        decision_path=decision,
        legs=LEGS,
        arms=arms,
        subset=None,
        subset_seed=None,
        out_dir=out,
        repo_root=real.repo,
        created_at=REAL_CREATED_AT,
    )


def _real_pair(real: types.SimpleNamespace, decision_a: Path, decision_b: Path) -> tuple[Path, Path]:
    runs = _real_run(real, "run-a", decision_a), _real_run(real, "run-b", decision_b)
    _score_both(real, *runs)
    return runs


def _score_both(real: types.SimpleNamespace, *runs: Path) -> None:
    for run in runs:
        cli.score_run(run, repo_root=real.repo)


def _compare_real(real: types.SimpleNamespace, run_a: Path, run_b: Path, *, treatment: str | None = None) -> Path:
    return cli.compare_runs(run_a, run_b, out_dir=real.repo / COMPARE_OUT, treatment=treatment, repo_root=real.repo)


def _assert_annotation_bound(real, *runs: Path) -> None:
    """Verify the actual comparison producer's digest against the full persisted annotations.

    annotation_bytes_sha256 is derived from validated frame rows; it is optional in the run
    manifest. Never mint a hash to fill an absent manifest field or bypass the IO validator.
    """
    for run in runs:
        identity = cli._run_identity(run, repo_root=real.repo, treatment=None)
        payload = json.loads((run / "frame.json").read_text())
        fields = ("face_id", "image_id", "box", "identity_id", "identity_status", "cohort", "annotation")
        annotations = sorted(
            ({key: face[key] for key in fields} for face in payload["faces"]), key=lambda face: face["face_id"]
        )
        expected = hashlib.sha256(
            json.dumps(annotations, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        assert identity["annotation_bytes_sha256"] == expected
        assert isinstance(identity["decision"], fc.DecisionManifest)
        assert isinstance(identity["inventory"], score_io.Inventory)
        assert identity["records"] and all(isinstance(r, legs.FaceSearchRecord) for r in identity["records"])
        assert identity["run_dir"] == run


def _assert_compare_touched_only_its_output(real: types.SimpleNamespace, before: dict[str, str]) -> None:
    """Compare writes only its own private comparison output; every run, decision and input byte is unchanged."""
    after = _snapshot(real.repo)
    changed = {rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel)}
    assert {rel for rel in changed if not rel.startswith(str(COMPARE_OUT))} == set()


def test_default_collaborators_complete_a_run_and_score_without_placeholders(real: types.SimpleNamespace) -> None:
    run = _real_run(real, "run-complete", _real_decision(real, "decision"))
    assert run.is_relative_to(real.repo / "benchmarks" / "private")
    firbench = json.loads((run / "manifest.json").read_text(encoding="utf-8"))["firbench"]
    assert len(firbench["leg_keys"]) == len(LEGS) * len(ARMS)
    expected_faces = [f"face-{index:04d}" for index in range(real.n_identities)]
    for key in firbench["leg_keys"]:
        rows = [json.loads(line) for line in (run / "ledger" / f"{key}.jsonl").read_text().splitlines()]
        assert sorted(row["face_id"] for row in rows) == expected_faces
        assert all(row["leg_key"] == key for row in rows)
    scores = cli.score_run(run, repo_root=real.repo)
    assert scores == run / "scores.json"
    fc.validate_interchange("scores-v1", json.loads(scores.read_text(encoding="utf-8")))
    pinned = _snapshot(run)
    assert cli.score_run(run, repo_root=real.repo) == scores
    assert _snapshot(run) == pinned


def test_compare_names_every_undeclared_difference_as_exploratory_without_a_verdict(
    real: types.SimpleNamespace,
) -> None:
    a = _real_decision(
        real, "decision-a", lambda p: p["primary"].update(fpir_target=0.05, estimand="paired delta FNIR")
    )
    b = _real_decision(
        real, "decision-b", lambda p: p["primary"].update(fpir_target=0.01, estimand="paired delta FPIR")
    )
    run_a, run_b = _real_pair(real, a, b)
    _assert_annotation_bound(real, run_a, run_b)
    before = _snapshot(real.repo)
    path = _compare_real(real, run_a, run_b)
    assert path.is_relative_to(real.repo / "benchmarks" / "private")
    _assert_compare_touched_only_its_output(real, before)
    payload = json.loads(path.read_text(encoding="utf-8"))
    fc.validate_interchange("comparison-v1", payload)
    assert payload["comparison_state"] == "exploratory"
    assert payload["label"] == "exploratory: multi-factor, no verdict"
    assert payload["verdicts"] is None
    assert payload["delta"] is None
    assert set(payload["differences"]) == {"fpir_target", "estimand"}


@pytest.mark.parametrize("real", [ELIGIBLE_IDENTITIES], indirect=True)
def test_identical_real_runs_compare_as_comparable_with_zero_paired_movement(real: types.SimpleNamespace) -> None:
    decision = _real_decision(real, "decision")
    run_a, run_b = _real_pair(real, decision, decision)
    _assert_annotation_bound(real, run_a, run_b)
    before = _snapshot(real.repo)
    path = _compare_real(real, run_a, run_b)
    assert path.is_relative_to(real.repo / "benchmarks" / "private")
    _assert_compare_touched_only_its_output(real, before)
    payload = json.loads(path.read_text(encoding="utf-8"))
    fc.validate_interchange("comparison-v1", payload)
    # Same decision and identical actual outcomes: no undeclared difference, so the state is comparable.
    assert payload["comparison_state"] == "comparable"
    assert payload["differences"] == []
    assert payload["treatment"] == {"name": None, "fields": []}
    assert payload["verdicts"] == {"run_a": "unratified", "run_b": "unratified"}
    assert payload["leg_changes"] == []
    schema = json.loads((Path(fc.__file__).parent / "firbench_schemas" / "comparison-v1.json").read_text())
    assert set(payload["compatibility"]) == set(schema["properties"]["compatibility"]["required"])
    assert len(payload["compatibility"]) == 14
    assert payload["compatibility"]["arm"] == "native"
    assert json.loads((run_a / "frame.json").read_text())["n_eff"] == ELIGIBLE_IDENTITIES
    assert isinstance(payload["label"], str) and payload["label"]
    # The actual fold and gallery splits leave 52 mated PSUs; full 10000 draws remain declared.
    assert json.loads(decision.read_text(encoding="utf-8"))["interval"]["n_boot"] == 10000
    assert len(payload["paired_deltas"]) == 3
    for row in payload["paired_deltas"]:
        assert row["status"] == "scored"
        assert row["n_searches"] == row["n_psu"] == row["n_eff"] == 52
        assert row["reason"] is None
        assert row["point"] == row["lower"] == row["upper"] == 0.0
    assert payload["delta"] == {"point": 0.0, "lower": 0.0, "upper": 0.0}
    assert "positive is worse" in payload["label"]
    assert len(payload["history"]) == 3
    for series in payload["history"]:
        assert [point["run_id"] for point in series["points"]] == ["run-a", "run-b"]
        assert all(point["fnir"] == 0.0 for point in series["points"])
    assert len(payload["tau_spread"]) == 6
    for spread in payload["tau_spread"]:
        assert spread["status"] == "unavailable"
        assert spread["reason"] == "pooled_fit_threshold_no_per_fold_estimates"
        assert spread["values"] == []
        assert spread["minimum"] is spread["maximum"] is None
    # Byte replay uses the same original timing receipts and never refits or rewrites them.
    published = _snapshot(real.repo)
    assert _compare_real(real, run_a, run_b) == path
    assert _snapshot(real.repo) == published


def test_exactly_one_declared_treatment_is_comparable_and_names_only_that_field(real: types.SimpleNamespace) -> None:
    a = _real_decision(real, "decision-a", lambda p: p["primary"].update(fpir_target=0.05))
    b = _real_decision(real, "decision-b")
    raw_a, raw_b = json.loads(a.read_text()), json.loads(b.read_text())
    assert raw_a["primary"].pop("fpir_target") == 0.05
    assert raw_b["primary"].pop("fpir_target") == 0.01
    assert raw_a == raw_b  # no change to seeds, floors, margins, hypotheses or other policy
    run_a, run_b = _real_pair(real, a, b)
    _assert_annotation_bound(real, run_a, run_b)
    path = _compare_real(real, run_a, run_b, treatment="fpir_target")
    payload = json.loads(path.read_text(encoding="utf-8"))
    fc.validate_interchange("comparison-v1", payload)
    assert payload["comparison_state"] == "comparable"
    assert payload["differences"] == ["fpir_target"]
    assert payload["treatment"] == {"name": "fpir_target", "fields": ["fpir_target"]}
    for row in payload["paired_deltas"]:
        if row["status"] == "scored":
            assert row["lower"] <= row["point"] <= row["upper"]
            assert row["n_psu"] >= 50
        else:
            assert row["reason"] and row["point"] is None and row["lower"] is None and row["upper"] is None


@pytest.mark.parametrize("missing", [False, True])
def test_report_renders_an_actual_scored_run_into_its_report_directory(real: types.SimpleNamespace, missing) -> None:
    if missing:
        real.state.missing_queries = {0}
    run = _real_run(real, "run-report", _real_decision(real, "decision"))
    # Downstream producers must use persisted evidence without reopening fake pixels or models.
    for path in real.private.glob("*.png"):
        path.unlink()
    (real.private / "source.json").unlink()
    (real.private / "templates.json").unlink()
    (real.private / "inputs" / f"{REAL_FRAME}.json").unlink()
    cli.score_run(run, repo_root=real.repo)
    before = _snapshot(run)
    index = cli.report_run(run, include_crops=False, repo_root=real.repo)
    assert index == run / "report" / "index.html"
    assert index.is_file()
    after = _snapshot(run)
    assert {rel: digest for rel, digest in after.items() if rel in before} == before
    clusters = json.loads((run / "clusters.json").read_text())
    fc.validate_interchange("clusters-v1", clusters)
    assert len(clusters["legs"]) == len(LEGS) * len(ARMS)
    for leg in clusters["legs"]:
        # The fused model cannot supply the GT-crop arm. Missing vectors in that arm,
        # or one actual detector miss, never suppress diagnostics for the remaining GT.
        fused_attribution = leg["leg_key"].startswith("insightface__gt_crop_redetect__")
        n_embedded = 0 if fused_attribution else REAL_IDENTITIES - int(missing)
        assert leg["vector_coverage"] == {
            "label": "diagnostics conditional on available GT vectors",
            "conditional": True,
            "n_gt_faces": REAL_IDENTITIES,
            "n_named_gt_faces": REAL_IDENTITIES,
            "n_embedded_gt_faces": n_embedded,
            "n_missing_gt_faces": REAL_IDENTITIES - n_embedded,
            "n_embedded_named_faces": n_embedded,
            "n_detector_only_rows": 0,
        }
    report = json.loads((index.parent / "report.json").read_text())
    assert report["verdict"] == json.loads((run / "scores.json").read_text())["verdict"]
    assert report["verdict"]["state"] == "unratified"
    for name in ("scores.json", "clusters.json", "frame.json", "manifest.json"):
        assert report["inputs"][name] == _sha_file(run / name)
    assert {"legs.csv", "curves.csv", "cells.csv", "waterfall.csv", "failures.csv"} <= {
        path.name for path in index.parent.glob("*.csv")
    }
    replay = _snapshot(run)
    assert cli.report_run(run, include_crops=False, repo_root=real.repo) == index
    assert _snapshot(run) == replay
    # Existing clusters must not let validation skip a changed cache or overwrite derived bytes.
    next((run / "legs").glob("*/cache.npz")).write_bytes(b"invalid synthetic cache")
    corrupted = _snapshot(run)
    with pytest.raises(FrameContractError, match="cache.npz"):
        cli.report_run(run, include_crops=False, repo_root=real.repo)
    assert _snapshot(run) == corrupted


@pytest.mark.parametrize("field", ["raw_frame", "scorer", "annotation", "PSU", "search_psu"])
@pytest.mark.parametrize("treatment", [None, "fpir_target"])
def test_actual_never_bindings_refuse_before_any_output(real, field, treatment):
    decision = _real_decision(real, "decision")
    run_a, run_b = _real_pair(real, decision, decision)
    expected = field
    if field == "raw_frame":
        with (run_b / "frame.json").open("ab") as stream:
            stream.write(b" ")
        expected = "frame_bytes_sha256"
    elif field == "scorer":
        _tamper_firbench(run_b, lambda fb: fb.update(scorer_sha256="9" * 64))
        expected = "scorer_sha"
    elif field == "search_psu":
        path = next((run_b / "legs").glob("*/searches.jsonl"))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["psu_id"] = "synthetic:foreign-psu"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        expected = "PSU|psu"
    else:
        path = run_b / "frame.json"
        payload = json.loads(path.read_text())
        if field == "annotation":
            payload["faces"][0]["annotation"]["rule_id"] = "synthetic:different-annotation-rule"
            expected = "annotation_bytes_sha256"
        else:
            payload["psu_map"][0]["psu_id"] = payload["psu_map"][1]["psu_id"]
        write_json(path, payload)
    _assert_comparison_refused(real, run_a, run_b, expected, treatment=treatment)


def test_actual_underfloor_comparison_keeps_full_cohort_and_named_nulls(real):
    decision = _real_decision(real, "decision")
    a, b = _real_pair(real, decision, decision)
    payload = json.loads(_compare_real(real, a, b).read_text())
    assert payload["comparison_state"] == "comparable"
    assert payload["delta"] is None
    assert len(payload["paired_deltas"]) == 3
    for row in payload["paired_deltas"]:
        assert row["status"] == "not_scored"
        assert row["reason"] == "insufficient_independent_psus"
        assert row["n_searches"] == row["n_psu"] == row["n_eff"] == 3
        assert row["point"] is row["lower"] is row["upper"] is None


def test_synthetic_sealed_decision_comparison_uses_actual_seal_and_verdict_context(real):
    decision = _real_decision(real, "synthetic-sealed", sealed=True)
    loaded = fc.load_decision_manifest(decision)
    assert loaded.seal.sha256 == fc.manifest_sha256(loaded)
    assert loaded.ratification.decision_ref == "synthetic:fixture-ratification-only"
    a, b = _real_pair(real, decision, decision)
    _assert_annotation_bound(real, a, b)
    payload = json.loads(_compare_real(real, a, b).read_text())
    fc.validate_interchange("comparison-v1", payload)
    assert payload["comparison_state"] == "comparable"
    assert payload["differences"] == []
    source = {
        label: json.loads((run / "scores.json").read_text())["verdict"]["state"]
        for label, run in (("run_a", a), ("run_b", b))
    }
    assert payload["verdicts"] == source == {"run_a": "inconclusive", "run_b": "inconclusive"}


def test_synthetic_sealed_fpir_treatment_allows_its_necessarily_derived_seal_hash(real):
    """Honest RED counterexample: exact FPIR treatment also changes seal.sha256.

    Both decisions pass the real seal/verdict gate. No ratification, timestamp,
    input, seed or other policy changes. Current compatibility rejects the derived
    seal leaf as an undeclared context field; the fixture must not strip that seal.
    """
    a = _real_decision(real, "synthetic-sealed-a", sealed=True)
    b = _real_decision(real, "synthetic-sealed-b", lambda p: p["primary"].update(fpir_target=0.05), sealed=True)
    raw_a, raw_b = json.loads(a.read_text()), json.loads(b.read_text())
    seal_a, seal_b = raw_a.pop("seal"), raw_b.pop("seal")
    assert seal_a["sealed_at"] == seal_b["sealed_at"]
    assert seal_a["sha256"] != seal_b["sha256"]
    assert raw_a["primary"].pop("fpir_target") == 0.01
    assert raw_b["primary"].pop("fpir_target") == 0.05
    assert raw_a == raw_b
    run_a, run_b = _real_pair(real, a, b)
    before = _snapshot(real.repo)
    # No expected-refusal wrapper: this remains a failing integration requirement.
    try:
        path = _compare_real(real, run_a, run_b, treatment="fpir_target")
    except FrameContractError:
        assert _snapshot(real.repo) == before
        assert not (real.repo / COMPARE_OUT).exists()
        raise
    _assert_compare_touched_only_its_output(real, before)
    payload = json.loads(path.read_text())
    fc.validate_interchange("comparison-v1", payload)
    assert payload["comparison_state"] == "comparable"
    assert payload["differences"] == ["fpir_target"]
    assert payload["treatment"] == {"name": "fpir_target", "fields": ["fpir_target"]}


def test_actual_space_change_labels_only_that_leg_and_keeps_separate_history(real):
    decision = _real_decision(real, "decision")
    a = _real_run(real, "run-a", decision)
    real.state.changed_kind = LegKind.auraface
    b = _real_run(real, "run-b", decision)
    _score_both(real, a, b)
    first = cli._run_identity(a, repo_root=real.repo, treatment=None)
    second = cli._run_identity(b, repo_root=real.repo, treatment=None)
    assert first["frame_bytes_sha256"] == second["frame_bytes_sha256"]
    payload = json.loads(_compare_real(real, a, b).read_text())
    fc.validate_interchange("comparison-v1", payload)
    assert payload["comparison_state"] == "comparable"
    assert payload["differences"] == []
    assert payload["leg_changes"] == [
        {
            "leg_kind": "auraface",
            "leg_key_a": first["legs"][f"auraface__{arm.value}"],
            "leg_key_b": second["legs"][f"auraface__{arm.value}"],
            "label": "leg contract changed (expected)",
        }
        for arm in sorted(ARMS, key=lambda arm: arm.value)
    ]
    registry_a = {
        (row["leg_key"].split("__")[0], row["leg_key"].split("__")[1], row["fold"]): row
        for row in first["firbench"]["gallery_membership"]
    }
    for row in second["firbench"]["gallery_membership"]:
        kind, arm = row["leg_key"].split("__")[:2]
        prior = registry_a[kind, arm, row["fold"]]
        assert prior["identity_folds"] == row["identity_folds"]
        assert prior["enrolled_identity_ids"] == row["enrolled_identity_ids"]
        assert (prior["gallery_sha256"] != row["gallery_sha256"]) == (kind == "auraface")
    assert len(payload["history"]) == 4
    for series in payload["history"]:
        expected = 1 if series["leg_kind"] == "auraface" else 2
        assert len(series["points"]) == expected
        assert series["leg_key"] in first["firbench"]["leg_keys"] + second["firbench"]["leg_keys"]
    assert all(row["status"] == "unavailable" and row["values"] == [] for row in payload["tau_spread"])


@pytest.mark.parametrize("real", [ELIGIBLE_IDENTITIES], indirect=True)
def test_actual_kernel_misses_change_crossrun_fnir_b_minus_a(real):
    """Plant only test-query detector misses; actual calibration, scoring and resampling remain intact."""
    decision_path = _real_decision(real, "decision")
    decision = fc.load_decision_manifest(decision_path)
    a = _real_run(real, "run-a", decision_path, arms=(Arm.native,))
    frame = json.loads((a / "frame.json").read_text())
    firbench = json.loads((a / "manifest.json").read_text())["firbench"]
    test_fold = decision.fold_protocol.seed % decision.fold_protocol.k
    gallery = next(
        row
        for row in firbench["gallery_membership"]
        if row["leg_key"].startswith("sface__native__") and row["fold"] == test_fold
    )
    enrolled = set(gallery["enrolled_identity_ids"])
    mated = sorted(face["face_id"] for face in frame["faces"] if face["identity_id"] in enrolled)
    assert len(mated) == 52
    planted = set(mated[:7])
    real.state.missing_queries = {int(face_id.removeprefix("face-")) for face_id in planted}
    b = _real_run(real, "run-b", decision_path, arms=(Arm.native,))
    _score_both(real, a, b)
    before = _snapshot(real.repo)
    forward = json.loads(_compare_real(real, a, b).read_text())
    reverse_path = cli.compare_runs(
        b, a, out_dir=real.private / "reverse-comparison", treatment=None, repo_root=real.repo
    )
    reverse = json.loads(reverse_path.read_text())
    after = _snapshot(real.repo)
    assert all(after.get(path) == digest for path, digest in before.items())
    for payload in (forward, reverse):
        fc.validate_interchange("comparison-v1", payload)
        assert payload["comparison_state"] == "comparable"
        assert payload["differences"] == []
        assert payload["verdicts"] == {"run_a": "unratified", "run_b": "unratified"}
    # Independent sufficient-statistic oracle, with all 10000 PSU draws. Unit
    # weights and one face per PSU make the exact point Fraction(7, 52).
    identity = cli._run_identity(a, repo_root=real.repo, treatment=None)
    psu_by_face = {
        face_id: identity["inventory"].psus[identity["inventory"].faces[face_id].image_id] for face_id in mated
    }
    psus = sorted(psu_by_face.values())
    missed_psus = {psu_by_face[face_id] for face_id in planted}
    misses = np.array([psu in missed_psus for psu in psus], dtype=int)
    assert decision.interval.n_boot == 10000
    draws = np.random.default_rng(decision.interval.seed).integers(0, len(psus), size=(10000, len(psus)))
    lower, upper = np.quantile(misses[draws].sum(axis=1) / len(psus), [0.025, 0.975])
    for row in forward["paired_deltas"]:
        back = next(other for other in reverse["paired_deltas"] if other["leg_kind"] == row["leg_kind"])
        assert row["status"] == back["status"] == "scored"
        assert row["n_searches"] == row["n_psu"] == row["n_eff"] == len(mated)
        assert row["point"] == pytest.approx(float(Fraction(7, 52)), abs=1e-12, rel=0)
        assert row["lower"] == pytest.approx(lower, abs=1e-12, rel=0)
        assert row["upper"] == pytest.approx(upper, abs=1e-12, rel=0)
        assert back["point"] == -row["point"]
        assert (back["lower"], back["upper"]) == (-row["upper"], -row["lower"])
    primary = next(row for row in forward["paired_deltas"] if row["leg_kind"] == "sface")
    assert forward["delta"] == {key: primary[key] for key in ("point", "lower", "upper")}
    scores_a, scores_b = (json.loads((run / "scores.json").read_text()) for run in (a, b))
    assert [row["tau"] for row in scores_a["legs"]] == [row["tau"] for row in scores_b["legs"]]
