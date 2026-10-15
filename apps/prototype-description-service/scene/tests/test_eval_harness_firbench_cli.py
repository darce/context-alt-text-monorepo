"""FIRBENCH-1 S6a: CLI ``run`` and ``score`` with fake collaborators.

Synthetic identifiers only (``id-0001``, ``face-0001``). No file from
``benchmarks/private/`` is read: every run writes under a temporary repository root.
The S1-S3 collaborators are replaced by fakes that follow the S0 contract and the
S2/S3 briefs; the real ones are not on this branch.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
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


def test_run_then_score_writes_full_layout_with_one_ledger_row_per_face_leg_arm(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)
    _run(repo, decision=decision, out=out, created_at="2026-10-15T09:00:00Z")

    scores_path = cli.score_run(out, repo_root=repo)

    assert scores_path == out / "scores.json"
    assert (out / "manifest.json").is_file()
    assert (out / "timings.json").is_file()
    assert json.loads(scores_path.read_text(encoding="utf-8"))["schema_version"] == 1
    leg_keys = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["firbench"]["leg_keys"]
    assert len(leg_keys) == len(LEGS) * len(ARMS)
    for key in leg_keys:
        rows = [json.loads(line) for line in (out / "ledger" / f"{key}.jsonl").read_text().splitlines()]
        assert len(rows) == len(GT_FACE_IDS)
        assert sorted(row["face_id"] for row in rows) == list(GT_FACE_IDS)
        assert all(not row["face_id"].startswith("det:") for row in rows)


def test_two_runs_on_pinned_inputs_yield_identical_semantic_artifacts(repo: Path) -> None:
    decision = _write_decision(repo)
    first = _out_dir(repo, parent="runs/a")
    second = _out_dir(repo, parent="runs/b")
    _run(repo, decision=decision, out=first, created_at="2026-10-15T09:00:00Z")
    _run(repo, decision=decision, out=second, created_at="2026-10-15T09:00:00Z")
    cli.score_run(first, repo_root=repo)
    cli.score_run(second, repo_root=repo)

    def semantic(root: Path) -> dict[str, str]:
        keep = {"manifest.json", "scores.json"}
        return {
            rel: digest
            for rel, digest in _snapshot(root).items()
            if rel in keep or rel.endswith("searches.jsonl") or rel.startswith("ledger/")
        }

    assert semantic(first) == semantic(second)
    assert semantic(first)


def test_score_refuses_a_decision_whose_sha_differs_from_the_run(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)
    _run(repo, decision=decision, out=out, created_at="2026-10-15T09:00:00Z")
    _write_decision(repo, ratified_at=RATIFIED_AT)  # same path, different bytes

    with pytest.raises(FrameContractError):
        cli.score_run(out, repo_root=repo)

    assert not (out / "scores.json").exists()


def test_score_never_rewrites_timings(repo: Path) -> None:
    decision = _write_decision(repo)
    out = _out_dir(repo)
    _run(repo, decision=decision, out=out, created_at="2026-10-15T09:00:00Z")
    before = _sha_file(out / "timings.json")

    cli.score_run(out, repo_root=repo)

    assert _sha_file(out / "timings.json") == before


def test_missing_s1_to_s3_collaborators_refuse_before_any_write(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unwired() -> cli.FirBenchCollaborators:
        raise NotImplementedError("S1-S3 are not merged on this branch")

    monkeypatch.setattr(cli, "_load_collaborators", unwired)
    decision = _write_decision(repo)
    out = _out_dir(repo)

    with pytest.raises(NotImplementedError):
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


def test_score_writer_io_failure_preserves_receipt_and_existing_score(repo, monkeypatch):
    out = _out_dir(repo)
    _run(repo, decision=_write_decision(repo), out=out, created_at=SEALED_AT)
    cli.score_run(out, repo_root=repo)
    before = _snapshot(out)

    def deny(*args, **kwargs):
        raise PermissionError("score replace denied")

    monkeypatch.setattr(cli.os, "replace", deny)
    with pytest.raises(FrameContractError, match="score replace denied"):
        cli.score_run(out, repo_root=repo)
    assert _snapshot(out) == before
