"""FIRBENCH-1 CLI: ``run`` and ``score`` (S6a); ``report``, ``compare`` and ``unseal`` (S6b).

Static refusals run before claiming ownership or spending: private output path, an
existing non-empty run directory, canary on a sealed frame, ``created_at`` precedence
(MCP 16773). The owner then checks the sealed-frame token (S0 Build 7). The S1-S3 modules are reached
only through ``FirBenchCollaborators``. Nothing here reads the wall clock except
``_attempt_timestamp``, the non-replayable attempt-receipt boundary (FLOW-18).

``unseal`` appends one unspent token under a cross-process ledger lock and refuses any frame that
already holds a token under any decision sha (EVAL-07). ``compare`` refuses on the compatibility key
before any metric is computed; a refusal writes nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib
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
    require_verdict_allowed,
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
            frame_text = frame_json(prepared.frame) + "\n"
            bundle = getattr(prepared, "label_evidence", None)
            evidence_files = {}
            if bundle is not None:
                # Snapshot the handoff before writing any declaration or support.
                try:
                    descriptor = json.loads(json.dumps(dict(bundle.descriptor), allow_nan=False))
                    evidence_files = dict(bundle.files)
                    declared = {row["path"]: row["sha256"] for row in descriptor["files"]}
                    if (
                        descriptor["schema"] != "firbench-label-evidence/v1"
                        or descriptor["frame_sha256"] != hashlib.sha256(frame_text.encode("utf-8")).hexdigest()
                        or len(declared) != len(descriptor["files"])
                        or set(declared) != set(evidence_files)
                    ):
                        raise FrameContractError("label_evidence declaration does not bind frame/files")
                    for relative, data in evidence_files.items():
                        if (
                            not isinstance(relative, str)
                            or not relative.startswith("label-evidence/benchmarks/private/")
                            or any(part in {"", ".", ".."} for part in relative.split("/"))
                            or "\\" in relative
                            or not isinstance(data, bytes)
                            or hashlib.sha256(data).hexdigest() != declared[relative]
                        ):
                            raise FrameContractError("label_evidence file path/bytes/hash mismatch")
                        target = run_dir / relative
                        if any(p.is_symlink() for p in (target, *target.parents)):
                            raise FrameContractError("label_evidence file path contains a symlink")
                        require_private_output_path(target, repo_root=repo_root)
                    manifest["firbench"]["label_evidence"] = descriptor
                except (AttributeError, KeyError, TypeError, ValueError) as exc:
                    raise FrameContractError(f"invalid label_evidence bundle: {exc}") from exc
            for relative, data in sorted(evidence_files.items()):
                target = run_dir / relative
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                except OSError as exc:
                    raise FrameContractError(f"cannot create label_evidence artifact {relative}: {exc}") from exc
            # The complete validated declaration is durable before any query outcome.
            _write_new(run_dir / "frame.json", frame_text)
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


_UNSEAL_LOCK = Path("benchmarks") / "private" / "firbench" / "unseal-ledger.lock"


@contextmanager
def _ledger_lock(repo_root: Path) -> Iterator[None]:
    """Serialise unseal appends across processes; flock is held for the whole read-check-append."""
    lock = require_private_output_path(repo_root / _UNSEAL_LOCK, repo_root=repo_root)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise SealedFrameReadError(f"cannot lock the unseal ledger: {exc}") from exc


def unseal_frame(*, decision_path: Path, frame_id: str, run_id: str, repo_root: Path) -> str:
    """Append one unspent ``UnsealToken`` for a sealed frame and return its token ref (S6b Build 3).

    Requires a ratified, sealed decision (``require_verdict_allowed``). A frame that holds any
    token, spent or unspent and under any decision sha, is refused (EVAL-07). Creates no run
    directory and spends nothing; the first sealed read in S6a consumes the token.
    """
    collaborators = _load_collaborators()
    decision = load_decision_manifest(decision_path)
    frame: FrameSpec = decision.frame(frame_id)
    if not frame.sealed:
        raise FrameContractError(f"frame {frame_id} is not sealed; only sealed frames have unseal tokens")
    require_verdict_allowed(decision, frame=frame)
    token = UnsealToken(
        frame_id=frame_id,
        frame_sha256=frame.source_sha256 or "",
        decision_sha256=_file_sha256(decision_path),
        run_id=run_id,
        code_sha=_head_sha(repo_root),
        scorer_sha=collaborators.scorer_sha,
        consumed_at=None,
    )
    row = json.dumps(asdict(token), sort_keys=True, separators=(",", ":"))
    with _ledger_lock(repo_root):
        if any(existing.get("frame_id") == frame_id for existing in _read_unseal_ledger(repo_root)):
            raise SealedFrameReadError(
                f"frame {frame_id} already holds an unseal token; a frame is unsealed once under any decision"
            )
        ledger = require_private_output_path(repo_root / _UNSEAL_LEDGER, repo_root=repo_root)
        try:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write(row + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SealedFrameReadError(f"cannot append the unseal token for {frame_id}: {exc}") from exc
    return _token_ref(token)


def report_run(run_dir: Path, *, include_crops: bool, repo_root: Path) -> Path:
    """Materialise clusters through S4 IO, then render S5 into ``<run_dir>/report/``.

    Import both producers before materializing so a missing S4 IO or S5 module
    refuses with a named error before either producer writes.
    """
    resolved = require_private_output_path(run_dir, repo_root=repo_root)
    try:
        clusters = importlib.import_module("scripts.eval_harness.firbench_cluster_io")
        report = importlib.import_module("scripts.eval_harness.firbench_report")
    except ImportError as exc:
        raise NotImplementedError(f"report needs the S4 clusters and S5 report producers: {exc}") from exc
    clusters.materialize_clusters(resolved)
    return report.render_report(resolved, out_dir=resolved / "report", include_crops=include_crops)


# --- compare: compatibility key (S6b Build 2; MCP 16869/16882 wire) ---------------------

_EXPLORATORY_LABEL = "exploratory: multi-factor, no verdict"
_LEG_CONTRACT_LABEL = "leg contract changed (expected)"
_NEVER_TREATABLE = (
    "frame_id",
    "frame_bytes_sha256",
    "face_set_sha256",
    "annotation_bytes_sha256",
    "scorer_sha",
    "boundary_semantics",
    "opencv_version",
    "ort_version",
)
_TREATABLE = (
    "estimand",
    "fpir_target",
    "gallery_sha256",
    "enrolment_probe_allocation",
    "fold_calibration_policy",
    "arm",
    "psu_weighting_policy",
)
# Only exact leaf paths map to treatment fields. Parent sections remain binding.
_MAPPED_DECISION_KEYS = frozenset()
_TREATMENT_PATHS = {
    "estimand": (("primary", "estimand"),),
    "fpir_target": (("primary", "fpir_target"),),
    "gallery_sha256": (("gallery_lineage", "templates_sha256"),),
    "enrolment_probe_allocation": (),
    "fold_calibration_policy": (("fold_protocol", "k"), ("fold_protocol", "seed"), ("gallery_lineage", "split_seed")),
    "arm": (),
    "psu_weighting_policy": (("planning_icc",), ("interval", "psu")),
}
_LEG_KEY = re.compile(r"^(?P<kind>[a-z]+)__(?P<arm>[a-z_]+?)__(?P<space>.+)__cv(?P<cv>.+?)__ort(?P<ort>.+)$")


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FrameContractError(f"invalid compatibility JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> Any:
    from scripts.eval_harness import firbench_contract as fc

    try:
        value = json.loads(
            path.read_bytes(), object_pairs_hook=fc._reject_duplicate_keys, parse_constant=fc._reject_non_finite
        )
        # parse_constant does not catch overflowing exponent literals (e.g. 1e999).
        _digest(value)
        return value
    except (OSError, UnicodeError, ValueError) as exc:
        raise FrameContractError(f"cannot read {path}: {exc}") from exc


def _comparison_original_seal(raw: Mapping[str, Any]) -> DecisionManifest | None:
    """Validate S0's original body hash before deriving any comparison projection."""
    from scripts.eval_harness import firbench_contract as fc

    if raw.get("seal") is None:
        return None
    original = fc._parse_manifest(raw)
    if original.seal is None or original.seal.sha256 != fc.manifest_sha256(original):
        raise FrameContractError("seal.sha256: original seal hash does not match the manifest")
    return original


def _without_treatment(raw: Mapping[str, Any], treatment: str | None) -> dict[str, Any]:
    if treatment is not None and treatment not in _TREATABLE:
        raise FrameContractError(f"unknown or refused treatment field: {treatment!r}")
    original = _comparison_original_seal(raw)
    copied: dict[str, Any] = json.loads(json.dumps(raw, allow_nan=False))
    paths = _TREATMENT_PATHS[treatment] if treatment is not None else ()
    for path in paths:
        parent = copied
        for part in path[:-1]:
            parent = parent[part]
        parent.pop(path[-1], None)
    if original is not None and paths:
        # This is a comparison digest, never a new S0 seal or a persisted decision.
        # Keep the timestamp and every other seal/ratification leaf binding.
        copied["seal"]["sha256"] = _digest({key: value for key, value in copied.items() if key != "seal"})
    return copied


def _compatibility_path(root: Path, relative: object, *, name: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise FrameContractError(f"{name}: missing or unsafe path binding")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise FrameContractError(f"{name}: path containment refusal")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise FrameContractError(f"{name}: path containment refusal")
    return target


def _compatibility_scores(scores: dict, *, decision: DecisionManifest, firbench: dict, inventory: Any,
                          records: list, validate_outcomes: bool = False) -> None:
    """Check persisted score context and measured rates, without selecting a threshold or resampling."""
    from scripts.eval_harness import firbench_score_io as io

    validate_interchange("scores-v1", scores)
    expected = {
        "decision_sha256": firbench["decision_sha256"], "frame_id": inventory.spec.frame_id,
        "admissibility": inventory.spec.admissibility.value, "boundary_semantics": decision.boundary_semantics.value,
        "planning_icc": decision.planning_icc, "p_d": decision.p_d, "power": decision.power,
        "min_n_independent": decision.min_n_independent, "cell_floor_n_independent": decision.cell_floor_n_independent,
    }
    for name, value in expected.items():
        if scores[name] != value:
            raise FrameContractError(f"scores {name} binding mismatch")
    if scores["primary"]["fpir_target"] != decision.primary.fpir_target:
        raise FrameContractError("scores primary.fpir_target binding mismatch")
    native = {key for key in firbench["leg_keys"] if _LEG_KEY.fullmatch(key)["arm"] == "native"}
    keys = [row["leg_key"] for row in scores["legs"]]
    if len(set(keys)) != len(keys) or set(keys) != native:
        raise FrameContractError("scores duplicate or missing native leg binding")
    hypotheses = {h.id: h for h in decision.hypotheses}
    if len(scores["hypotheses"]) != len(hypotheses) or {h["id"] for h in scores["hypotheses"]} != set(hypotheses):
        raise FrameContractError("scores hypotheses binding mismatch")
    guards = {g.id: g for g in decision.guardrails}
    rows = scores["guardrails"]
    if len(rows) != len(guards) or {r["id"] for r in rows} != set(guards):
        raise FrameContractError("scores guardrail registry binding mismatch")
    for row in rows:
        if row["metric"] != guards[row["id"]].metric or row["role"] != guards[row["id"]].role.value:
            raise FrameContractError("scores guardrail policy binding mismatch")
    for row in scores["hypotheses"]:
        if row["kind"] != hypotheses[row["id"]].kind.value:
            raise FrameContractError("scores hypothesis kind binding mismatch")
    if not validate_outcomes:
        return
    for leg in scores["legs"]:
        key = leg["leg_key"]
        selected = [r for r in records if r.leg_key == key and r.sampling_arm.value == "probability"]
        mated = io._mated([r for r in selected if r.fold == inventory.test_fold])
        tau = leg["tau"]["data"]
        fnir = leg["operating_point"]["fnir"]
        if tau is None:
            if fnir["status"] == "available":
                raise FrameContractError("scores FNIR requires actual calibration binding")
            continue
        fit_units = [u for fold in range(decision.fold_protocol.k) if fold != inventory.test_fold
                     for u in io._units(inventory, fold, io.fc.SamplingArm.probability)]
        if tau["pooled_units"] != len(fit_units):
            raise FrameContractError("scores calibration pooled_units binding mismatch")
        fit_rows = [r for r in selected if r.fold != inventory.test_fold]
        point = io.core.curve(fit_rows, units=fit_units, thresholds=[tau["value"]], boundary=decision.boundary_semantics)[0]
        if tau["fpi_at_tau"] != {"count": point.fpi, "rate": point.fpir}:
            raise FrameContractError("scores calibration fpi_at_tau binding mismatch")
        if not mated:
            if fnir["status"] == "available":
                raise FrameContractError("scores FNIR has no actual mated cohort")
            continue
        outcomes = io.core.finish_outcomes(mated, tau["value"], decision.boundary_semantics)
        weights = [io.core._weight(r) for r in mated]
        misses = [o is not io.fc.FaceOutcome.correct for o in outcomes]
        neff = io.core._n_eff([r.psu_id for r in mated], decision.planning_icc)
        expected_fnir = {"misses": sum(misses), "n_mated": len(mated), "n_eff": neff,
                         "design_effect": len(mated) / neff,
                         "rate": sum(w * m for w, m in zip(weights, misses, strict=True)) / sum(weights)}
        if fnir["status"] != "available" or any(fnir["data"][n] != v for n, v in expected_fnir.items()):
            raise FrameContractError("scores FNIR actual outcome/PSU/weight binding mismatch")


def _run_identity(run_dir: Path, *, repo_root: Path, treatment: str | None) -> dict[str, Any]:
    """Read actual persisted evidence through S3 IO; never reopen source pixels or refit."""
    from scripts.eval_harness import firbench_contract as fc
    from scripts.eval_harness import firbench_score_io as io

    if treatment is not None and treatment not in _TREATABLE:
        raise FrameContractError(f"unknown or refused treatment field: {treatment!r}")
    run = require_private_output_path(run_dir, repo_root=repo_root)
    try:
        manifest = _read_json(_compatibility_path(run, "manifest.json", name="manifest"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
            raise FrameContractError("run manifest schema_version binding mismatch")
        firbench = manifest.get("firbench")
        if not isinstance(firbench, dict):
            raise FrameContractError("missing firbench manifest binding")
        decision_path = _compatibility_path(Path(repo_root), firbench["decision_path"], name="decision_path")
        decision_sha = fc._require_sha(firbench["decision_sha256"], "decision_sha256")
        if _file_sha256(decision_path) != decision_sha:
            raise FrameContractError("decision_sha256: decision file no longer matches its raw SHA")
        raw = _read_json(decision_path)
        _compatibility_path(decision_path.parent, raw["gate_contract_path"], name="gate_contract_path")
        decision = load_decision_manifest(decision_path)
        scorer_sha = fc._require_sha(firbench["scorer_sha256"], "scorer_sha")
        if decision.interval.n_boot is None or decision.interval.seed is None:
            raise FrameContractError("missing interval n_boot/seed binding")
        fc._require_sha(decision.gallery_lineage.templates_sha256, "gallery template lineage binding")
        leg_keys, arms = firbench["leg_keys"], firbench["arms"]
        if not isinstance(leg_keys, list) or not leg_keys or len(set(leg_keys)) != len(leg_keys):
            raise FrameContractError("duplicate or missing leg keys binding")
        if not isinstance(arms, list) or not arms or len(set(arms)) != len(arms):
            raise FrameContractError("duplicate or missing arm binding")
        for arm in arms:
            Arm(arm)
        if "native" not in arms:
            raise FrameContractError("primary native arm binding is required")
        legs, cv_versions, ort_versions = {}, set(), set()
        for key in leg_keys:
            if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", key) is None:
                raise FrameContractError("unsafe leg_key binding")
            match = _LEG_KEY.fullmatch(key)
            if match is None:
                raise FrameContractError(f"malformed leg_key binding: {key!r}")
            LegKind(match["kind"])
            Arm(match["arm"])
            kind_arm = f"{match['kind']}__{match['arm']}"
            if kind_arm in legs:
                raise FrameContractError(f"duplicate leg kind/arm binding: {kind_arm}")
            legs[kind_arm] = key
            cv_versions.add(match["cv"])
            ort_versions.add(match["ort"])
            _compatibility_path(run, f"legs/{key}/searches.jsonl", name="searches")
        kinds = {LegKind(k.split("__")[0]) for k in leg_keys}
        if not isinstance(firbench["legs"], list) or len(set(firbench["legs"])) != len(firbench["legs"]):
            raise FrameContractError("duplicate or missing leg kinds binding")
        if set(firbench["legs"]) != {k.value for k in kinds} or set(legs) != {
            f"{kind.value}__{arm}" for kind in kinds for arm in arms
        }:
            raise FrameContractError("manifest leg/arm registry binding mismatch")
        required = set(decision.primary.comparison) | {k for h in decision.hypotheses for k in h.legs}
        if not required <= kinds:
            raise FrameContractError("missing native hypothesis leg binding")
        for row in firbench["gallery_membership"]:
            if set(row) - {"leg_key", "fold", "gallery_sha256", "enrolled_identity_ids", "identity_folds", "enrolled_occluders"}:
                raise FrameContractError("unsupported gallery registry binding field")
        registry, enrolled = io._registry(firbench, decision)
        space_galleries = {}
        for (key, fold), row in registry.items():
            match = _LEG_KEY.fullmatch(key)
            token = (match["kind"], match["space"], fold)
            if space_galleries.setdefault(token, row["gallery_sha256"]) != row["gallery_sha256"]:
                raise FrameContractError("gallery_sha256 contradictory same-space arm binding")
        frame_path = _compatibility_path(run, "frame.json", name="frame_bytes_sha256")
        payload = _read_json(frame_path)
        fc._require_sha(payload["source_sha256"], "frame_bytes_sha256 source binding")
        inventory = io._inventory(payload, decision, enrolled)
        if firbench["frame"] != {n: payload[n] for n in ("frame_id", "admissibility", "sealed", "source_sha256", "exhaustive")}:
            raise FrameContractError("frame_id/frame_bytes_sha256 manifest binding mismatch")
        for row in registry.values():
            if any(row["identity_folds"].get(i) != f for i, f in inventory.identity_folds.items()):
                raise FrameContractError("gallery identity fold binding mismatch")
        expected_seeds = {"folds": decision.fold_protocol.seed, "gallery_split": decision.gallery_lineage.split_seed,
                          "bootstrap": decision.interval.seed}
        if firbench["seeds"] != expected_seeds:
            raise FrameContractError("manifest seeds binding mismatch")
        basis = firbench["gallery_hash_basis"]
        if basis not in leg_keys or _LEG_KEY.fullmatch(basis)["arm"] != "native":
            raise FrameContractError("gallery_hash_basis native binding mismatch")
        frame_galleries = io._unique(payload["gallery_sha256_by_fold"], "fold", "sha256")
        if frame_galleries != {fold: registry[basis, fold]["gallery_sha256"] for fold in range(decision.fold_protocol.k)}:
            raise FrameContractError("frame gallery_sha256_by_fold binding mismatch")
        records = io._records(run, firbench, inventory, registry)
        # Also catch exponent overflow in arbitrary numeric JSON fields before any metric/output.
        for record in records:
            _digest(asdict(record))
        scores_path = _compatibility_path(run, "scores.json", name="scores binding")
        scores = _read_json(scores_path)
        timing_path = _compatibility_path(run, "timings.json", name="timings binding")
        _read_json(timing_path)
        timing_sha = _file_sha256(timing_path)
        scores_sha = _file_sha256(scores_path)
        if "scores_sha256" in firbench and firbench["scores_sha256"] != scores_sha:
            raise FrameContractError("scores_sha256 binding mismatch")
        _compatibility_scores(scores, decision=decision, firbench=firbench, inventory=inventory,
                              records=records)
        for row in scores["guardrails"]:
            if row["timings_sha256"] is not None and row["timings_sha256"] != timing_sha:
                raise FrameContractError("scores timings_sha256 receipt binding mismatch")
        annotation = _digest(sorted(
            ({"face_id": face["face_id"], "image_id": face["image_id"], "box": face["box"],
              "identity_id": face["identity_id"], "identity_status": face["identity_status"],
              "cohort": face["cohort"], "annotation": face["annotation"]} for face in payload["faces"]),
            key=lambda face: face["face_id"],
        ))
        if "annotation_bytes_sha256" in firbench and firbench["annotation_bytes_sha256"] != annotation:
            raise FrameContractError("annotation_bytes_sha256 actual face binding mismatch")
        def rows(fields):
            return [[_LEG_KEY.fullmatch(key)["kind"], _LEG_KEY.fullmatch(key)["arm"], fold,
                     *[row.get(field) for field in fields]] for (key, fold), row in sorted(registry.items())]
        return {
            "run_id": firbench["run_id"], "decision_sha256": decision_sha, "scores_sha256": scores_sha,
            "frame_id": payload["frame_id"], "frame_bytes_sha256": _file_sha256(frame_path),
            "face_set_sha256": _digest(sorted(inventory.faces)), "annotation_bytes_sha256": annotation,
            "scorer_sha": scorer_sha, "boundary_semantics": decision.boundary_semantics.value,
            "opencv_version": ",".join(sorted(cv_versions)), "ort_version": ",".join(sorted(ort_versions)),
            "estimand": decision.primary.estimand, "fpir_target": decision.primary.fpir_target,
            "gallery_sha256": _digest({"vectors": rows(("gallery_sha256",)),
                                        "templates_sha256": decision.gallery_lineage.templates_sha256}),
            "enrolment_probe_allocation": _digest({"enrolled": rows(("enrolled_identity_ids", "enrolled_occluders")),
                                                   "subset": firbench["subset"], "subset_seed": firbench["subset_seed"]}),
            "fold_calibration_policy": _digest({"fold_protocol": raw["fold_protocol"],
                                                "split_seed": decision.gallery_lineage.split_seed,
                                                "identity_folds": next(iter(registry.values()))["identity_folds"]}),
            "arm": ",".join(sorted(arms)),
            "psu_weighting_policy": _digest({"psu": decision.interval.psu.value, "planning_icc": decision.planning_icc,
                                             "psus": inventory.psus, "folds": inventory.folds,
                                             "sampling": [asdict(i) for _, i in sorted(inventory.images.items())]}),
            "decision_sha256_without_treatment": _digest(_without_treatment(raw, treatment)),
            "legs": legs, "raw_decision": raw, "treatment_raw": _without_treatment(raw, treatment),
            "run_dir": run, "decision": decision, "frame_payload": payload, "scores": scores,
            "firbench": firbench, "inventory": inventory, "records": records,
        }
    except FrameContractError:
        raise
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise FrameContractError(f"missing or invalid comparison binding: {exc}") from exc


def _compatibility_leaf_differences(first: Any, second: Any, path: tuple = ()) -> list[tuple]:
    if isinstance(first, dict) and isinstance(second, dict):
        result = []
        for key in sorted(set(first) | set(second)):
            if key not in first or key not in second:
                result.append((*path, key))
            else:
                result.extend(_compatibility_leaf_differences(first[key], second[key], (*path, key)))
        return result
    if isinstance(first, list) and isinstance(second, list) and len(first) == len(second):
        return [p for index, (a, b) in enumerate(zip(first, second, strict=True))
                for p in _compatibility_leaf_differences(a, b, (*path, str(index)))]
    return [] if type(first) is type(second) and first == second else [path]


def _compatibility_arm(identity: dict, *, treatment: str | None, profiles_differ: bool) -> Arm:
    declared = identity["firbench"].get("analysis_arm")
    arms = {Arm(a) for a in identity["firbench"]["arms"]}
    if declared is not None:
        try:
            arm = Arm(declared)
        except ValueError as exc:
            raise FrameContractError("unknown analysis arm binding") from exc
        if arm not in arms:
            raise FrameContractError("analysis arm outside declared arm scope")
        return arm
    if treatment != "arm" or not profiles_differ or arms == {Arm.native}:
        return Arm.native
    attribution = arms - {Arm.native}
    if len(attribution) != 1:
        raise FrameContractError("ambiguous analysis arm scope: multiple attribution arms")
    return next(iter(attribution))


def _comparison_compatibility(first: dict, second: dict, *, treatment: str | None) -> dict:
    """Adjudicate validated inputs before the metrics lane computes or writes anything."""
    if treatment is not None and treatment not in _TREATABLE:
        raise FrameContractError(f"unknown or refused treatment field: {treatment!r}")
    never = [name for name in _NEVER_TREATABLE if first[name] != second[name]]
    # Aggregate version sets alone would conceal a runtime swap between two legs.
    for kind in sorted({k.split("__")[0] for k in first["legs"]} | {k.split("__")[0] for k in second["legs"]}):
        for field, label in (("cv", "opencv_version"), ("ort", "ort_version")):
            a = {_LEG_KEY.fullmatch(v)[field] for k, v in first["legs"].items() if k.split("__")[0] == kind}
            b = {_LEG_KEY.fullmatch(v)[field] for k, v in second["legs"].items() if k.split("__")[0] == kind}
            if a != b and label not in never:
                never.append(label)
    for token in sorted(set(first["legs"]) & set(second["legs"])):
        a = _LEG_KEY.fullmatch(first["legs"][token])
        b = _LEG_KEY.fullmatch(second["legs"][token])
        for field, label in (("cv", "opencv_version"), ("ort", "ort_version")):
            if a[field] != b[field] and label not in never:
                never.append(label)
    if never:
        raise FrameContractError("compare refuses never-treatable field(s): " + ", ".join(never))
    for identity in (first, second):
        original = _comparison_original_seal(identity["raw_decision"])
        if original is not None:
            if original != identity["decision"]:
                raise FrameContractError("original sealed decision binding mismatch")
            if original.ratification.decision_ref is not None and original.ratification.ratified_at is not None:
                require_verdict_allowed(original, frame=original.frame(identity["frame_id"]))
    kinds_a = {k.split("__")[0] for k in first["legs"]}
    kinds_b = {k.split("__")[0] for k in second["legs"]}
    if kinds_a != kinds_b:
        raise FrameContractError("native leg kind inventory binding mismatch")
    diffs = [name for name in _TREATABLE if first[name] != second[name]]
    profiles_differ = first["arm"] != second["arm"]
    arm_a = _compatibility_arm(first, treatment=treatment, profiles_differ=profiles_differ)
    arm_b = _compatibility_arm(second, treatment=treatment, profiles_differ=profiles_differ)
    if arm_a != arm_b and "arm" not in diffs:
        diffs.append("arm")
    leg_changes = []
    for kind_arm in sorted(set(first["legs"]) & set(second["legs"])):
        a, b = first["legs"][kind_arm], second["legs"][kind_arm]
        if _LEG_KEY.fullmatch(a)["space"] != _LEG_KEY.fullmatch(b)["space"]:
            leg_changes.append({"leg_kind": LegKind(kind_arm.split("__")[0]), "leg_key_a": a, "leg_key_b": b,
                                "label": _LEG_CONTRACT_LABEL})
    def registry(identity):
        return {(f"{_LEG_KEY.fullmatch(r['leg_key'])['kind']}__{_LEG_KEY.fullmatch(r['leg_key'])['arm']}", r["fold"]): r
                for r in identity["firbench"]["gallery_membership"]}
    reg_a, reg_b = registry(first), registry(second)
    lineage_same = first["raw_decision"]["gallery_lineage"] == second["raw_decision"]["gallery_lineage"]
    protocol_same = first["fold_calibration_policy"] == second["fold_calibration_policy"]
    unexplained = []
    for token in sorted(set(reg_a) & set(reg_b)):
        a, b = reg_a[token], reg_b[token]
        if a["gallery_sha256"] == b["gallery_sha256"]:
            continue
        changed_space = _LEG_KEY.fullmatch(a["leg_key"])["space"] != _LEG_KEY.fullmatch(b["leg_key"])["space"]
        inputs_same = {k: v for k, v in a.items() if k not in {"leg_key", "gallery_sha256"}} == {
            k: v for k, v in b.items() if k not in {"leg_key", "gallery_sha256"}}
        if not (changed_space and lineage_same and protocol_same and inputs_same):
            unexplained.append(token)
    if unexplained and treatment != "gallery_sha256":
        raise FrameContractError("gallery_sha256 unexplained same-space/input-lineage change")
    # Arm profiles do not change gallery input lineage. Compare matched per-leg/fold rows,
    # allowing a derived vector hash only within the particular changed leg contract.
    if "gallery_sha256" in diffs and not unexplained and lineage_same:
        diffs.remove("gallery_sha256")
    # Remove arm replication from allocation/fold hashes; it is not a second factor.
    for field, names in (("enrolment_probe_allocation", ("enrolled_identity_ids", "enrolled_occluders")),
                         ("fold_calibration_policy", ("identity_folds",))):
        if field in diffs and profiles_differ:
            def native_rows(reg, names=names):
                return {token: {name: row.get(name) for name in names} for token, row in reg.items()
                        if token[0].endswith("__native")}
            extra_same = (first["firbench"]["subset"], first["firbench"]["subset_seed"]) == (
                second["firbench"]["subset"], second["firbench"]["subset_seed"])
            if field == "fold_calibration_policy":
                extra_same = first["raw_decision"]["fold_protocol"] == second["raw_decision"]["fold_protocol"] and lineage_same
            if native_rows(reg_a) == native_rows(reg_b) and extra_same:
                diffs.remove(field)
    leaf_owners = {path: field for field, paths in _TREATMENT_PATHS.items() for path in paths}
    normalized_a = _without_treatment(first["raw_decision"], treatment)
    normalized_b = _without_treatment(second["raw_decision"], treatment)
    derived_seal_change = (
        treatment is not None
        and treatment in diffs
        and first["decision"].seal is not None
        and second["decision"].seal is not None
        and normalized_a == normalized_b
    )
    outside = [
        ".".join(path)
        for path in _compatibility_leaf_differences(first["raw_decision"], second["raw_decision"])
        if leaf_owners.get(path) not in diffs and not (derived_seal_change and path == ("seal", "sha256"))
    ]
    # Runtime/analysis policy not represented by a treatment remains binding. Explicit run
    # metadata can vary; never discard seeds, crop policy, permutations or unknown fields.
    metadata = {"run_id", "head_sha", "decision_path", "decision_sha256", "frame", "legs", "arms", "leg_keys",
                "gallery_membership", "gallery_hash_basis", "created_at", "created_at_source", "unseal_token_ref",
                "subset", "subset_seed", "seeds", "analysis_arm", "scores_sha256", "annotation_bytes_sha256"}
    outside.extend("manifest.firbench." + ".".join(path) for path in _compatibility_leaf_differences(
        {k: v for k, v in first["firbench"].items() if k not in metadata},
        {k: v for k, v in second["firbench"].items() if k not in metadata}))
    if outside:
        raise FrameContractError("compare refuses decision/context field(s): " + ", ".join(outside))
    undeclared = [name for name in diffs if name != treatment]
    if len(undeclared) == 1:
        raise FrameContractError(f"compare refuses: {undeclared[0]} differs and is not the declared treatment")
    state = "exploratory" if len(undeclared) >= 2 else "comparable"
    for identity in (first, second):
        _compatibility_scores(identity["scores"], decision=identity["decision"], firbench=identity["firbench"],
                              inventory=identity["inventory"], records=identity["records"], validate_outcomes=True)
    # frame_id/face_set are internal refusals; the frozen wire has exactly fourteen keys.
    compatibility = {name: first[name] for name in _NEVER_TREATABLE + _TREATABLE
                     if name not in {"frame_id", "face_set_sha256"}}
    compatibility["arm"] = arm_a.value
    compatibility["decision_sha256_without_treatment"] = _digest(normalized_a)
    return {"state": state, "differences": diffs, "compatibility": compatibility, "leg_changes": leg_changes,
            "analysis_arm_a": arm_a, "analysis_arm_b": arm_b}


def _comparison_scope(identity: Mapping[str, Any], arm: Arm) -> dict[str, str]:
    """Select declared leg contracts, never infer an analysis arm from outcomes."""
    if not isinstance(arm, Arm):
        raise FrameContractError("comparison analysis scope must declare an Arm")
    selected: dict[str, str] = {}
    for key in identity["firbench"]["leg_keys"]:
        match = _LEG_KEY.fullmatch(key)
        if match is None:
            raise FrameContractError(f"comparison has malformed leg_key {key!r}")
        if match["arm"] == arm.value:
            kind = LegKind(match["kind"]).value
            if kind in selected:
                raise FrameContractError(f"ambiguous comparison leg scope: {kind}/{arm.value}")
            selected[kind] = key
    if not selected:
        raise FrameContractError(f"comparison analysis arm not declared: {arm.value}")
    return selected


def _comparison_snapshot(identity: Mapping[str, Any], key: str, arm: Arm) -> dict[str, Any]:
    """Assemble the full native mated cohort from validated inventory and searches.

    Unavailable searches stay in the cohort. Neither missing searches nor absent
    calibration can be converted into correct outcomes or a smaller cohort.
    """
    from scripts.eval_harness import firbench_score as core

    inventory = identity["inventory"]
    kind = key.split("__")[0]
    native = _comparison_scope(identity, Arm.native).get(kind)
    if native is None:
        raise FrameContractError(f"comparison lacks native cohort for {kind}")
    declarations = [
        row
        for row in identity["firbench"]["gallery_membership"]
        if row["leg_key"] == native and row["fold"] == inventory.test_fold
    ]
    if len(declarations) != 1:
        raise FrameContractError(f"comparison lacks unique native gallery cohort for {kind}")
    enrolled = set(declarations[0]["enrolled_identity_ids"])
    expected = {
        face.face_id: face
        for face in inventory.faces.values()
        if face.identity_id in enrolled
        and inventory.images[face.image_id].sampling_arm.value == "probability"
        and inventory.folds[inventory.psus[face.image_id]] == inventory.test_fold
    }
    by_face = {}
    for record in identity["records"]:
        if record.leg_key != key or record.face_id not in inventory.faces:
            continue
        if record.face_id in by_face:
            raise FrameContractError(f"duplicate GT face in comparison searches: {record.face_id}")
        by_face[record.face_id] = record
    if set(by_face) != set(inventory.faces):
        raise FrameContractError(f"comparison searches must contain every GT face for {key}")
    rows, bindings = [], []
    for face_id, face in sorted(expected.items()):
        record = by_face[face_id]
        image = inventory.images[face.image_id]
        psu = inventory.psus[face.image_id]
        if (
            record.arm is not arm
            or record.image_id != face.image_id
            or record.psu_id != psu
            or record.fold != inventory.test_fold
            or record.identity_id != face.identity_id
            or not core._is_mated(record)
            or record.sampling_arm != image.sampling_arm
            or record.inclusion_probability != image.inclusion_probability
        ):
            raise FrameContractError(f"comparison GT/PSU/weight binding mismatch: {face_id}")
        rows.append(record)
        bindings.append((face_id, face, psu, core._weight(record)))
    scored = [leg for leg in identity["scores"]["legs"] if leg["leg_key"] == key]
    if len(scored) > 1:
        raise FrameContractError(f"duplicate scored comparison leg: {key}")
    source = scored[0] if scored else None
    calibration = None if source is None else source["tau"]
    tau = None
    reason = "analysis_arm_calibration_not_supplied" if source is None else calibration["reason"]
    if calibration is not None and calibration["status"] == "available":
        tau = calibration["data"]["value"]
        core._require_finite_tau(tau)
    elif reason is None:
        reason = "calibration_unavailable"
    if any(r.arm_availability.value != "available" for r in rows):
        reason = f"{arm.value}_search_unavailable"
    psus = [r.psu_id for r in rows]
    return {
        "rows": rows,
        "bindings": bindings,
        "psus": psus,
        "weights": [core._weight(r) for r in rows],
        "n_eff": core._n_eff(psus, identity["decision"].planning_icc),
        "tau": tau,
        "reason": reason,
        "source": source,
    }


def _comparison_history_point(identity: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only an actual supplied score point, including its missing state."""
    source = snapshot["source"]
    fnir = None if source is None else source["operating_point"]["fnir"]
    value = None if fnir is None or fnir["status"] != "available" else fnir["data"]["rate"]
    reason = snapshot["reason"]
    if value is None and reason is None:
        reason = "fnir_unavailable" if fnir is None else fnir["reason"]
    return {"run_id": identity["run_id"], "fnir": value, "tau": snapshot["tau"], "reason": reason}


def _comparison_metrics(
    first: Mapping[str, Any], second: Mapping[str, Any], *, analysis_arm_a: Arm, analysis_arm_b: Arm
) -> dict[str, Any]:
    """Paired cross-run FNIR(B)-FNIR(A), using the entire fixed native cohort.

    Core inference consumes outcomes, never vectors across embedding spaces.
    Thresholds come from recorded S3 calibration; comparison never refits them.
    """
    from scripts.eval_harness import firbench_score as core

    a, b = _comparison_scope(first, analysis_arm_a), _comparison_scope(second, analysis_arm_b)
    if set(a) != set(b):
        raise FrameContractError("comparison leg kinds differ; no silent intersection")
    snapshots = {}
    # Validate all pairings before bootstrapping any leg.
    for kind in sorted(a):
        left = _comparison_snapshot(first, a[kind], analysis_arm_a)
        right = _comparison_snapshot(second, b[kind], analysis_arm_b)
        if left["bindings"] != right["bindings"]:
            raise FrameContractError(f"comparison fixed native GT/PSU/weights cohort differs: {kind}")
        snapshots[kind] = left, right
    if first["decision"].interval != second["decision"].interval:
        raise FrameContractError("comparison paired bootstrap policies differ")
    paired, history, spread = [], {}, []
    for kind, (left, right) in snapshots.items():
        n, n_psu = len(left["rows"]), len(set(left["psus"]))
        row = {
            "leg_kind": kind,
            "leg_key_a": a[kind],
            "leg_key_b": b[kind],
            "status": "not_scored",
            "reason": None,
            "n_searches": n,
            "n_psu": n_psu,
            "n_eff": min(left["n_eff"], right["n_eff"]),
            "point": None,
            "lower": None,
            "upper": None,
        }
        reason = left["reason"] or right["reason"]
        if not n:
            reason = "no_mated_queries"
        elif n_psu < max(first["decision"].min_n_independent, second["decision"].min_n_independent):
            reason = "insufficient_independent_psus"
        if reason is None:
            # Core subtracts its second array from its first and returns .delta.
            interval = core.paired_cluster_bootstrap(
                core.finish_outcomes(right["rows"], right["tau"], second["decision"].boundary_semantics),
                core.finish_outcomes(left["rows"], left["tau"], first["decision"].boundary_semantics),
                left["psus"],
                weights=left["weights"],
                n_boot=first["decision"].interval.n_boot,
                seed=first["decision"].interval.seed,
                level=0.95,
            )
            row.update(status="scored", point=interval.delta, lower=interval.lower, upper=interval.upper)
            if not all(math.isfinite(row[k]) for k in ("point", "lower", "upper")) or not (
                row["lower"] <= row["point"] <= row["upper"]
            ):
                raise FrameContractError(f"invalid paired comparison interval: {kind}")
        else:
            row["reason"] = reason
        paired.append(row)
        for identity, key, snapshot in ((first, a[kind], left), (second, b[kind], right)):
            series = history.setdefault((kind, key), {"leg_kind": kind, "leg_key": key, "points": []})
            series["points"].append(_comparison_history_point(identity, snapshot))
            # S3 persists one pooled threshold and an aggregate diagnostic spread,
            # not predeclared fold-indexed estimates. That scalar cannot supply values.
            spread.append(
                {
                    "leg_kind": kind,
                    "run_id": identity["run_id"],
                    "status": "unavailable",
                    "reason": "pooled_fit_threshold_no_per_fold_estimates",
                    "values": [],
                    "minimum": None,
                    "maximum": None,
                }
            )
    primary = next((r for r in paired if r["leg_kind"] == first["decision"].primary.comparison[0].value), None)
    delta = None
    if (
        analysis_arm_a is Arm.native
        and analysis_arm_b is Arm.native
        and primary is not None
        and primary["status"] == "scored"
    ):
        delta = {k: primary[k] for k in ("point", "lower", "upper")}
    return {"paired_deltas": paired, "history": list(history.values()), "tau_spread": spread, "delta": delta}


def _comparison_write(path: Path, text: str) -> None:
    """Replay identical derived bytes; refuse conflicting or redirected output."""
    if path.is_symlink():
        raise FrameContractError("comparison.json must not be a symlink")
    if path.exists():
        if path.is_file() and path.read_bytes() == text.encode("utf-8"):
            return
        raise FrameContractError("comparison.json already exists with conflicting content")
    try:
        _write_new(path, text)
    except FrameContractError:
        # A concurrent identical writer may have won O_EXCL. Never overwrite it.
        if not path.is_symlink() and path.is_file() and path.read_bytes() == text.encode("utf-8"):
            return
        raise


def _comparison_summary(
    first: Mapping[str, Any], second: Mapping[str, Any], metrics: Mapping[str, Any], *, state: str
) -> dict[str, Any]:
    """Retain original verdict context, with no verdict or legacy delta in exploration."""
    if state == "exploratory":
        return {"label": _EXPLORATORY_LABEL, "delta": None, "verdicts": None}
    if state != "comparable":
        raise FrameContractError("comparison compatibility helper returned an invalid state")
    return {
        "label": "paired FNIR(B) - FNIR(A); positive is worse",
        "delta": metrics["delta"],
        "verdicts": {"run_a": first["scores"]["verdict"]["state"], "run_b": second["scores"]["verdict"]["state"]},
    }


def compare_runs(run_a: Path, run_b: Path, *, out_dir: Path, treatment: str | None, repo_root: Path) -> Path:
    """Compare two runs under the compatibility key and return ``comparison.json`` (S6b Build 2).

    Never-treatable fields refuse with the field named, even under ``treatment``. A differing
    field refuses unless it is the one declared treatment. Two or more undeclared differences give
    an exploratory contrast with no verdict word and no winner.
    """
    if treatment is not None and treatment not in _TREATABLE:
        raise FrameContractError(f"--treatment {treatment!r} is not a declared treatment field")
    compatibility_helper = globals().get("_comparison_compatibility")
    if not callable(compatibility_helper):
        raise FrameContractError("comparison compatibility helper _comparison_compatibility is not installed")
    first = _run_identity(run_a, repo_root=repo_root, treatment=treatment)
    second = _run_identity(run_b, repo_root=repo_root, treatment=treatment)
    contract = compatibility_helper(first, second, treatment=treatment)
    state = contract["state"]
    if state not in {"comparable", "exploratory"}:
        raise FrameContractError("comparison compatibility helper returned an invalid state")
    if first["scores_sha256"] is None or second["scores_sha256"] is None:
        raise FrameContractError("score both runs before compare: scores.json is missing")
    metrics = _comparison_metrics(
        first, second, analysis_arm_a=contract["analysis_arm_a"], analysis_arm_b=contract["analysis_arm_b"]
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "comparison_state": state,
        **_comparison_summary(first, second, metrics, state=state),
        "estimand": first["estimand"],
        "fpir_target": first["fpir_target"],
        "compatibility": contract["compatibility"],
        "treatment": {"name": treatment, "fields": [treatment] if treatment else []},
        "run_a": {key: first[key] for key in ("run_id", "decision_sha256", "scores_sha256")},
        "run_b": {key: second[key] for key in ("run_id", "decision_sha256", "scores_sha256")},
        "differences": contract["differences"],
        "paired_deltas": metrics["paired_deltas"],
        "history": metrics["history"],
        "tau_spread": metrics["tau_spread"],
        "leg_changes": contract["leg_changes"],
    }
    target = require_private_output_path(out_dir, repo_root=repo_root)
    validate_interchange("comparison-v1", payload)
    target.mkdir(parents=True, exist_ok=True)
    _comparison_write(target / "comparison.json", json.dumps(payload, sort_keys=True, indent=2) + "\n")
    return target / "comparison.json"


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
    report = commands.add_parser("report", help="render the private report for an existing run")
    report.add_argument("run_dir", type=Path)
    report.add_argument("--include-crops", action="store_true")
    compare = commands.add_parser("compare", help="compare two scored runs under the compatibility key")
    compare.add_argument("run_a", type=Path)
    compare.add_argument("run_b", type=Path)
    compare.add_argument("--out", required=True, type=Path)
    compare.add_argument("--treatment")
    unseal = commands.add_parser("unseal", help="append one unspent unseal token for a sealed frame")
    unseal.add_argument("--decision", required=True, type=Path)
    unseal.add_argument("--frame", required=True)
    unseal.add_argument("--run-id", required=True)
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
        elif args.command == "score":
            path = score_run(args.run_dir, repo_root=repo_root)
        elif args.command == "report":
            path = report_run(args.run_dir, include_crops=args.include_crops, repo_root=repo_root)
        elif args.command == "compare":
            path = compare_runs(
                args.run_a,
                args.run_b,
                out_dir=args.out,
                treatment=args.treatment,
                repo_root=repo_root,
            )
        else:
            path = unseal_frame(
                decision_path=args.decision,
                frame_id=args.frame,
                run_id=args.run_id,
                repo_root=repo_root,
            )
    except (FirBenchError, NotImplementedError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
