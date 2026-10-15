"""FIRBENCH-1 S6a: ``run`` creates one immutable run, ``score`` assesses it (S0 Build 10).

Static refusals run before claiming ownership or spending: private output path, an
existing non-empty run directory, canary on a sealed frame, ``created_at`` precedence
(MCP 16773). The owner then checks the sealed-frame token (S0 Build 7). The S1-S3 modules are reached
only through ``FirBenchCollaborators``. Nothing here reads the wall clock except
``_attempt_timestamp``, the non-replayable attempt-receipt boundary (FLOW-18).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.eval_harness.firbench_contract import (
    Arm,
    CanaryInSealedRunError,
    DecisionManifest,
    FirBenchError,
    FrameContractError,
    FrameSpec,
    LegKind,
    SealedFrameReadError,
    UnsealToken,
    load_decision_manifest,
    require_frame_read_allowed,
    require_private_output_path,
    validate_interchange,
)

SCHEMA_VERSION = 1
_UNSEAL_LEDGER = Path("benchmarks") / "private" / "firbench" / "unseal-ledger.jsonl"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class LegRunResult:
    """What the leg runner returns to the driver. The driver writes and validates every file."""

    gt_face_ids: tuple[str, ...]
    searches: Mapping[str, Sequence[Mapping[str, Any]]]
    ledger: Mapping[str, Sequence[Mapping[str, Any]]]
    timings_ms: Mapping[str, float]


@dataclass(frozen=True)
class FirBenchCollaborators:
    """Seams to the accepted S1 (frames), S2 (legs) and S3 (scoring) producers.

    ``leg_keys`` gives the ``LegId.key()`` values before any leg runs, for the manifest.
    ``run_legs`` returns searches, ledger rows and per-face milliseconds. ``score_run``
    returns a ``scores-v1`` payload. ``scorer_sha`` is the S3 scorer identity.
    """

    leg_keys: Callable[..., tuple[str, ...]]
    run_legs: Callable[..., LegRunResult] | None
    score_run: Callable[..., Mapping[str, Any]]
    scorer_sha: str
    similarity_threshold: float
    prepare_run: Callable[..., Any] | None = None


def _load_collaborators() -> FirBenchCollaborators:
    from scripts.eval_harness.firbench_runtime import default_collaborators

    return default_collaborators()


def _attempt_timestamp() -> str:
    """Non-replayable attempt boundary (FLOW-18; MCP 16773). Never used by a semantic writer."""
    return dt.datetime.now(dt.UTC).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _parse_instant(value: object, name: str) -> dt.datetime:
    if not isinstance(value, str):
        raise FrameContractError(f"{name} must be an ISO 8601 literal with an explicit offset")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise FrameContractError(f"{name} is not an ISO 8601 literal: {exc}") from exc
    if parsed.tzinfo is None:
        raise FrameContractError(f"{name} must carry an explicit offset (Z or ±HH:MM)")
    return parsed


def resolve_created_at(manifest: DecisionManifest, explicit: str | None) -> tuple[str, str]:
    """Return ``(created_at, created_at_source)`` by MCP 16773 precedence.

    Seal, else ratification, else the explicit literal. An explicit literal must equal the
    derived instant when one exists. Instants are compared as parsed values.
    """
    supplied = None if explicit is None else _parse_instant(explicit, "--created-at")
    if manifest.seal is not None:
        derived, source = manifest.seal.sealed_at, "seal.sealed_at"
    elif manifest.ratification.ratified_at is not None:
        derived, source = manifest.ratification.ratified_at, "ratification.ratified_at"
    else:
        derived, source = None, "explicit"
    if derived is None:
        if supplied is None:
            raise FrameContractError(
                "run has no created_at: the decision is neither sealed nor ratified and no --created-at was given"
            )
        return supplied.isoformat(), source
    selected = _parse_instant(derived, source)
    if supplied is not None and supplied != selected:
        raise FrameContractError(f"--created-at does not match the selected {source} instant")
    return selected.isoformat(), source


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise FrameContractError(f"cannot read {path}: {exc}") from exc


def _head_sha(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise FrameContractError(f"cannot resolve the HEAD sha: {exc}") from exc
    sha = completed.stdout.strip()
    if completed.returncode != 0 or not _HEX40.match(sha):
        raise FrameContractError("cannot resolve the HEAD sha for this run")
    return sha


def _check_empty_run_dir(run_dir: Path) -> None:
    try:
        try:
            info = run_dir.stat()
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(info.st_mode) or any(run_dir.iterdir()):
            raise FrameContractError(f"run directory {run_dir} already exists and is not empty")
    except OSError as exc:
        raise FrameContractError(f"cannot inspect run directory {run_dir}: {exc}") from exc


def _require_fresh_run_dir(out_dir: Path, *, repo_root: Path) -> Path:
    resolved = require_private_output_path(out_dir, repo_root=repo_root)
    _check_empty_run_dir(resolved)
    return resolved


@contextmanager
def _claim_run_dir(run_dir: Path, *, repo_root: Path) -> Iterator[None]:
    """Exclude concurrent attempts before spending, including for an existing empty dir.

    The sibling claim leaves the run itself untouched on authorization refusal. A crash
    leaves a claim that fails closed. Cleanup never removes run directories or artifacts.
    [CON-11] Atomicity violation (check-then-act), Operating Systems: Three Easy Pieces, ch. 32.
    """
    claim = run_dir.with_name(f".{run_dir.name}.claim")
    require_private_output_path(claim, repo_root=repo_root)
    try:
        claim.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FrameContractError(f"run directory {run_dir} is already claimed") from exc
    except OSError as exc:
        raise FrameContractError(f"cannot claim run directory {run_dir}: {exc}") from exc
    try:
        # The earlier freshness check may have preceded a now-completed owner's claim.
        _check_empty_run_dir(run_dir)
        yield
    finally:
        try:
            try:
                current = claim.lstat()
            except FileNotFoundError:
                current = None
            owned = os.fstat(fd)
            if current is not None and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                claim.unlink()
        except OSError as exc:
            raise FrameContractError(f"cannot release run claim {claim}: {exc}") from exc
        finally:
            os.close(fd)


def _read_unseal_ledger(repo_root: Path) -> list[Mapping[str, Any]]:
    ledger = require_private_output_path(repo_root / _UNSEAL_LEDGER, repo_root=repo_root)
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError) as exc:
        raise SealedFrameReadError(f"cannot read the unseal ledger: {exc}") from exc
    rows: list[Mapping[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SealedFrameReadError(f"the unseal ledger holds a malformed row: {exc}") from exc
        if not isinstance(row, dict):
            raise SealedFrameReadError("the unseal ledger holds a non-object row")
        rows.append(row)
    return rows


def _unspent_token(repo_root: Path, *, frame_id: str, decision_sha256: str, run_id: str) -> UnsealToken | None:
    """Return the latest unspent token bound to this frame, decision and run, or None."""
    candidates = [
        row
        for row in _read_unseal_ledger(repo_root)
        if row.get("frame_id") == frame_id
        and row.get("decision_sha256") == decision_sha256
        and row.get("run_id") == run_id
        and row.get("consumed_at") is None
    ]
    if not candidates:
        return None
    try:
        return UnsealToken(**candidates[-1])
    except (TypeError, FrameContractError) as exc:
        raise SealedFrameReadError(f"the unseal ledger token for {frame_id} is malformed: {exc}") from exc


def _token_ref(token: UnsealToken) -> str:
    body = {key: value for key, value in asdict(token).items() if key != "consumed_at"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = sorted(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) for row in rows)
    return "".join(line + "\n" for line in lines)


def _write_new(path: Path, text: str) -> None:
    """Create a run artifact exactly once. An existing file is never rewritten."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise FrameContractError(f"cannot create run artifact {path}: {exc}") from exc


def _check_run_result(result: LegRunResult, *, leg_keys: tuple[str, ...], arms: tuple[Arm, ...]) -> None:
    if set(result.searches) != set(leg_keys) or set(result.ledger) != set(leg_keys):
        raise FrameContractError("the leg runner returned rows for a different set of legs than the manifest")
    for arm in arms:
        if not any(f"__{arm.value}__" in key for key in leg_keys):
            raise FrameContractError(f"no leg key carries arm {arm.value}")
    for key in leg_keys:
        rows = result.ledger[key]
        for row in rows:
            if row.get("leg_key") != key:
                raise FrameContractError(f"ledger row for {key} names another leg")
            if str(row.get("face_id", "")).startswith("det:") or row.get("unit_id") is not None:
                raise FrameContractError("the per-recognition ledger holds a background or unit row")
        arm_names = {str(row.get("arm")) for row in rows}
        if any(f"__{name}__" not in key for name in arm_names) or len(arm_names) > 1:
            raise FrameContractError(f"ledger rows for {key} must name the single arm of their leg key")
        if sorted(str(row.get("face_id")) for row in rows) != sorted(result.gt_face_ids):
            raise FrameContractError(f"ledger for {key} must hold exactly one row per GT face")
        for row in result.searches[key]:
            validate_interchange("face-search-record-v1", dict(row))
            if row.get("leg_key") != key:
                raise FrameContractError(f"search row for {key} names another leg")
    refs = {str(row["timing_receipt_ref"]) for key in leg_keys for row in result.searches[key]}
    missing = sorted(refs - set(result.timings_ms))
    if missing:
        raise FrameContractError(f"timing receipt missing for {len(missing)} search rows")
    for ref, value in result.timings_ms.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or value < 0
        ):
            raise FrameContractError(f"timing receipt value for {ref} is not a finite non-negative number")


def run_frame(
    *,
    frame_id: str,
    decision_path: Path,
    legs: tuple[LegKind, ...],
    arms: tuple[Arm, ...],
    subset: int | None,
    subset_seed: int | None,
    out_dir: Path,
    repo_root: Path,
    created_at: str | None = None,
) -> Path:
    """Create one immutable run directory and return it (S0 Build 10)."""
    collaborators = _load_collaborators()
    if subset is not None and subset_seed is None:
        raise FrameContractError("--subset requires --subset-seed")
    decision = load_decision_manifest(decision_path)
    frame: FrameSpec = decision.frame(frame_id)
    if frame.sealed and LegKind.canary in legs:
        raise CanaryInSealedRunError(f"a canary leg cannot run on sealed frame {frame_id}")
    run_dir = _require_fresh_run_dir(out_dir, repo_root=repo_root)
    run_id = run_dir.name
    decision_sha = _file_sha256(decision_path)
    created, source = resolve_created_at(decision, created_at)
    head = _head_sha(repo_root)
    leg_keys = tuple(sorted(collaborators.leg_keys(legs=legs, arms=arms)))
    try:
        decision_rel = os.path.relpath(Path(decision_path).resolve(), Path(repo_root).resolve())
    except (OSError, ValueError) as exc:
        raise FrameContractError(f"cannot resolve decision path relative to the repository root: {exc}") from exc
    with _claim_run_dir(run_dir, repo_root=repo_root):
        token_ref = None
        if frame.sealed:
            token = _unspent_token(repo_root, frame_id=frame_id, decision_sha256=decision_sha, run_id=run_id)
            consumed = require_frame_read_allowed(
                frame,
                token,
                decision_sha256=decision_sha,
                run_id=run_id,
                code_sha=head,
                scorer_sha=collaborators.scorer_sha,
                repo_root=repo_root,
                consumed_at=_attempt_timestamp(),
            )
            token_ref = _token_ref(consumed)
        attempt_started_at = _attempt_timestamp()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "firbench": {
                "run_id": run_id,
                "head_sha": head,
                "decision_path": decision_rel,
                "decision_sha256": decision_sha,
                "frame": {
                    "frame_id": frame.frame_id,
                    "admissibility": frame.admissibility.value,
                    "sealed": frame.sealed,
                    "source_sha256": frame.source_sha256,
                    "exhaustive": frame.exhaustive,
                },
                "legs": sorted(kind.value for kind in legs),
                "arms": sorted(arm.value for arm in arms),
                "leg_keys": list(leg_keys),
                "subset": subset,
                "subset_seed": subset_seed,
                "seeds": {
                    "folds": decision.fold_protocol.seed,
                    "gallery_split": decision.gallery_lineage.split_seed,
                    "bootstrap": decision.interval.seed,
                },
                "similarity_threshold": collaborators.similarity_threshold,
                "scorer_sha256": collaborators.scorer_sha,
                "created_at": created,
                "created_at_source": source,
                "unseal_token_ref": token_ref,
            },
        }
        arguments = {
            "frame": frame,
            "legs": legs,
            "arms": arms,
            "subset": subset,
            "subset_seed": subset_seed,
            "decision": decision,
            "out_dir": run_dir,
        }
        prepared = None
        if collaborators.prepare_run is not None:
            prepared = collaborators.prepare_run(**arguments, repo_root=repo_root)
            from scripts.eval_harness.firbench_frames import frame_json

            manifest["firbench"].update(
                gallery_membership=list(prepared.gallery_membership),
                gallery_hash_basis=prepared.gallery_hash_basis,
                crop_margin=prepared.crop_margin,
                canary_permutations=prepared.canary_permutations,
            )
            # The complete validated declaration is durable before any query outcome.
            _write_new(run_dir / "frame.json", frame_json(prepared.frame) + "\n")
            _write_new(run_dir / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        try:
            runner = prepared.run_legs if prepared is not None else collaborators.run_legs
            if runner is None:
                raise FrameContractError("no prepared leg runner")
            result = runner(**arguments)
            _check_run_result(result, leg_keys=leg_keys, arms=arms)
        except Exception as exc:
            if prepared is not None:
                _write_new(
                    run_dir / "attempt-failure.json",
                    json.dumps(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "attempt_started_at": attempt_started_at,
                            "error_type": type(exc).__name__,
                            "phase": "query_outcomes",
                        },
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n",
                )
            raise
        if prepared is None:
            # Backwards-compatible injected collaborators retain their original seam.
            _write_new(run_dir / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        for key in leg_keys:
            _write_new(run_dir / "legs" / key / "searches.jsonl", _jsonl(result.searches[key]))
            _write_new(run_dir / "ledger" / f"{key}.jsonl", _jsonl(result.ledger[key]))
        timings = {
            "schema_version": SCHEMA_VERSION,
            "attempt_started_at": attempt_started_at,
            "timing_receipt_ms": {ref: float(result.timings_ms[ref]) for ref in sorted(result.timings_ms)},
        }
        _write_new(run_dir / "timings.json", json.dumps(timings, sort_keys=True, indent=2) + "\n")
        return run_dir


def score_run(run_dir: Path, *, repo_root: Path) -> Path:
    """Write ``scores.json`` for a run and return its path (S0 Build 10).

    ``timings.json`` is read and never rewritten. A decision whose sha differs from the one
    the run was created under is refused.
    """
    collaborators = _load_collaborators()
    resolved = require_private_output_path(run_dir, repo_root=repo_root)
    manifest_path = resolved / "manifest.json"
    timings_path = resolved / "timings.json"
    try:
        firbench = json.loads(manifest_path.read_text(encoding="utf-8"))["firbench"]
        json.loads(timings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FrameContractError(f"run {resolved} lacks a readable manifest or timing receipt: {exc}") from exc
    decision_path = Path(repo_root) / firbench["decision_path"]
    decision = load_decision_manifest(decision_path)
    if _file_sha256(decision_path) != firbench["decision_sha256"]:
        raise FrameContractError(
            "the decision sha256 differs from the one this run was created under; refusing to score"
        )
    payload = dict(collaborators.score_run(resolved, decision=decision))
    validate_interchange("scores-v1", payload)
    target = resolved / "scores.json"
    # The temporary name is writer coordination only; it never enters semantic bytes.
    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=resolved, prefix=".scores-", suffix=".tmp", delete=False
        ) as handle:
            staging = Path(handle.name)
            handle.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        os.replace(staging, target)
    except OSError as exc:
        raise FrameContractError(f"cannot write scores {target}: {exc}") from exc
    finally:
        if staging is not None:
            try:
                staging.unlink(missing_ok=True)
            except OSError as exc:
                raise FrameContractError(f"cannot remove score staging file {staging}: {exc}") from exc
    return target


def _parse_enum_list(enum_cls: type, text: str, flag: str) -> tuple[Any, ...]:
    values = [item.strip() for item in text.split(",") if item.strip()]
    if not values:
        raise FrameContractError(f"{flag} must name at least one member")
    try:
        return tuple(enum_cls(value) for value in values)
    except ValueError as exc:
        raise FrameContractError(f"{flag}: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_harness.firbench_cli")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="create one immutable run directory")
    run.add_argument("--frame", required=True)
    run.add_argument("--decision", required=True, type=Path)
    run.add_argument("--legs", required=True)
    run.add_argument("--arms", default=Arm.native.value)
    run.add_argument("--subset", type=int)
    run.add_argument("--subset-seed", type=int)
    run.add_argument("--created-at")
    run.add_argument("--out", required=True, type=Path)
    score = commands.add_parser("score", help="write scores.json for an existing run")
    score.add_argument("run_dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = _repo_root()
    try:
        if args.command == "run":
            path = run_frame(
                frame_id=args.frame,
                decision_path=args.decision,
                legs=_parse_enum_list(LegKind, args.legs, "--legs"),
                arms=_parse_enum_list(Arm, args.arms, "--arms"),
                subset=args.subset,
                subset_seed=args.subset_seed,
                out_dir=args.out,
                repo_root=repo_root,
                created_at=args.created_at,
            )
        else:
            path = score_run(args.run_dir, repo_root=repo_root)
    except (FirBenchError, NotImplementedError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
