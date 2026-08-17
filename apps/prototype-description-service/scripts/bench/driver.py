"""Ingest → analyze → cluster → export driver with resume and cluster gate."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.bench.corpus import (
    ItemOutcomeStore,
    assert_baseline_superset,
    assert_floor_fits_corpus,
    decode_image_dimensions,
    load_bench_manifest,
    resolve_media_bytes,
)
from scripts.bench.export_map import export_leg
from scripts.bench.production_shaped_guard import assert_named_bench_stack
from scripts.bench.stack_pair import BenchError, FIR23_STACK_ALLOWLIST, StackEndpoint, StackPairConfig
from scripts.bench.status import (
    ANALYZE_PARTIAL_SUCCESS,
    CLUSTER_SUCCESS_STATUSES,
    ItemOutcome,
    ItemPhase,
    RunPhase,
)
from scripts.eval_harness.remote_client import RemoteSceneClient

LICENSE_BANNER = (
    "INTERNAL BENCH ONLY — insightface/buffalo_l outputs must never be user-facing "
    "or used as training data."
)


@dataclass(frozen=True)
class AnalyzeOutcome:
    manifest_media_id: int
    outcome: str
    attempt: int
    terminal: bool


@dataclass(frozen=True)
class ClusterGateDecision:
    admits: bool
    reason: str | None = None


def evaluate_cluster_gate(items: list[Any], item_max_attempts: int = 2) -> ClusterGateDecision:
    """Every analyze job terminal (success, or failure with attempts exhausted) AND ≥1 success."""
    if not items:
        return ClusterGateDecision(False, "cluster_gate_refused")
    successes = 0
    for item in items:
        outcome = item.get("outcome") if isinstance(item, dict) else getattr(item, "outcome", None)
        attempt = item.get("attempt", 1) if isinstance(item, dict) else getattr(item, "attempt", 1)
        if outcome == ItemOutcome.OK:
            successes += 1
            continue
        if outcome == ItemOutcome.FAILED:
            if int(attempt or 0) < int(item_max_attempts):
                return ClusterGateDecision(False, None)
            continue
        return ClusterGateDecision(False, None)
    if successes < 1:
        return ClusterGateDecision(False, "cluster_gate_refused")
    return ClusterGateDecision(True, None)


def cluster_gate_admits(items: list[Any], item_max_attempts: int = 2) -> bool:
    return evaluate_cluster_gate(items, item_max_attempts=item_max_attempts).admits


def init_run_dir(run_dir: Path | str, pair: StackPairConfig, manifest_path: Path | str) -> Path:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = root.name
    run_doc = {
        "run_stamp": stamp,
        "cli_sha": _package_sha("scripts/bench"),
        "harness_sha": _package_sha("scripts/eval_harness"),
        "license_banner": LICENSE_BANNER,
        "wall_clock_timeout_sec": pair.wall_clock_timeout_sec,
        "job_poll_timeout_sec": pair.job_poll_timeout_sec,
        "phase": "init",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bootstrap_seed": pair.bootstrap_seed,
    }
    redacted = {
        "head_to_head_delta": pair.head_to_head_delta,
        "bootstrap_seed": pair.bootstrap_seed,
        "primary_endpoint": pair.primary_endpoint,
        "secondary_endpoints": list(pair.secondary_endpoints),
        "accepted_set_floor": pair.accepted_set_floor,
        "max_differential_attrition": pair.max_differential_attrition,
        "allow_private_source": pair.allow_private_source,
        "baseline_manifest_path": pair.baseline_manifest_path,
        "stacks": [
            {
                "stack_id": s.stack_id,
                "role": s.role,
                "base_url": s.base_url,
                "expected_profile": s.expected_profile,
                "expected_pgvector_dim": s.expected_pgvector_dim,
                "opencv_major": s.opencv_major,
                "api_key_env": s.api_key_env,
                "tenant_id_env": s.tenant_id_env,
            }
            for s in pair.stacks
        ],
    }
    digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    (root / "manifest.sha").write_text(digest + "\n", encoding="utf-8")
    (root / "manifest.json").write_bytes(Path(manifest_path).read_bytes())
    run_doc["manifest_path"] = str(Path(manifest_path))
    (root / "run.json").write_text(json.dumps(run_doc, indent=2), encoding="utf-8")
    (root / "stack_pair.json").write_text(json.dumps(redacted, indent=2), encoding="utf-8")
    for stack in pair.stacks:
        (root / "legs" / stack.stack_id).mkdir(parents=True, exist_ok=True)
    return root


def run_cluster_phase(
    run_dir: Path | str,
    stack_id: str,
    client: Any,
    tenant_id: str = "",
    item_max_attempts: int = 2,
    analyze_outcomes: list[Any] | None = None,
) -> ClusterGateDecision:
    leg = Path(run_dir) / "legs" / stack_id
    leg.mkdir(parents=True, exist_ok=True)
    if analyze_outcomes is None:
        store = ItemOutcomeStore(leg / "items.jsonl")
        analyze_outcomes = list(store.latest_analyze_by_media().values())
    decision = evaluate_cluster_gate(analyze_outcomes, item_max_attempts=item_max_attempts)
    latch = leg / "leg_outcome.json"
    if not decision.admits:
        if decision.reason == "cluster_gate_refused":
            outcome = {
                "status": "failed",
                "phase": "failed",
                "error_code": "cluster_gate_refused",
            }
            latch.write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        elif latch.is_file():
            # Retryable refusal: do not leave a stale terminal latch in the
            # window where item_max_attempts was raised after a prior refuse.
            latch.unlink()
        return decision
    if latch.is_file():
        latch.unlink()
    payload = client.clustering_job(tenant_id, mode="sync")
    (leg / "cluster_job.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return decision


def run_leg(
    endpoint: StackEndpoint,
    pair: StackPairConfig,
    *,
    manifest_path: Path | str,
    images_dir: Path | str | None,
    run_dir: Path | str,
    client: Any | None = None,
    deadline: float | None = None,
) -> list[AnalyzeOutcome]:
    assert_named_bench_stack(endpoint, FIR23_STACK_ALLOWLIST)
    root = Path(run_dir)
    leg_dir = root / "legs" / endpoint.stack_id
    leg_dir.mkdir(parents=True, exist_ok=True)
    store = ItemOutcomeStore(leg_dir / "items.jsonl")
    manifest = load_bench_manifest(manifest_path, images_dir)
    owned_client = False
    if client is None:
        client = RemoteSceneClient(
            endpoint.base_url,
            os.environ.get(endpoint.api_key_env, ""),
            tenant_id=os.environ.get(endpoint.tenant_id_env, ""),
            timeout_s=float(pair.job_poll_timeout_sec),
        )
        owned_client = True
    outcomes: list[AnalyzeOutcome] = []
    try:
        for entry in manifest.entries:
            _check_deadline(deadline)
            latest = store.latest(entry.media_id, "analyze")
            if latest is not None and latest.get("outcome") == "ok":
                outcomes.append(AnalyzeOutcome(entry.media_id, "ok", int(latest.get("attempt", 1)), True))
                continue
            # Analyze attempts are per-phase. An ingest-ok row must not seed
            # the analyze counter (that burned the first analyze try).
            attempt = int((latest or {}).get("attempt", 0)) + 1
            if latest is not None and latest.get("outcome") == "failed" and attempt > pair.item_max_attempts:
                outcomes.append(AnalyzeOutcome(entry.media_id, "failed", pair.item_max_attempts, True))
                continue
            try:
                data = resolve_media_bytes(
                    entry,
                    images_dir,
                    url_map_path=pair.media_url_map_path,
                    allow_private_source=pair.allow_private_source,
                )
                prior_ingest = store.latest(entry.media_id, "ingest")
                if prior_ingest is not None and prior_ingest.get("outcome") == "ok":
                    width = int(prior_ingest["image_width"])
                    height = int(prior_ingest["image_height"])
                else:
                    width, height = decode_image_dimensions(data)
                    store.append(
                        {
                            "manifest_media_id": entry.media_id,
                            "manifest_path": entry.path,
                            "content_sha256": entry.sha256,
                            "stack_media_id": None,
                            "image_width": width,
                            "image_height": height,
                            "phase": "ingest",
                            "outcome": "ok",
                            "error_code": None,
                            "attempt": attempt,
                            "terminal_ingest_outcome": "success",
                        }
                    )
                job_id = client.analyze([(entry.media_id, Path(entry.path).name, data)])
                job = client.wait_job(job_id)
                if _analyze_job_failed(job):
                    store.append(
                        {
                            "manifest_media_id": entry.media_id,
                            "manifest_path": entry.path,
                            "content_sha256": entry.sha256,
                            "stack_media_id": None,
                            "image_width": width,
                            "image_height": height,
                            "phase": "analyze",
                            "outcome": "failed",
                            "error_code": "analyze_completed_with_errors",
                            "attempt": attempt,
                            "terminal_ingest_outcome": "success",
                        }
                    )
                    terminal = attempt >= pair.item_max_attempts
                    outcomes.append(AnalyzeOutcome(entry.media_id, "failed", attempt, terminal))
                    continue
                stack_media_id = _stack_media_id_from_job(job, entry.media_id)
                store.append(
                    {
                        "manifest_media_id": entry.media_id,
                        "manifest_path": entry.path,
                        "content_sha256": entry.sha256,
                        "stack_media_id": stack_media_id,
                        "image_width": width,
                        "image_height": height,
                        "phase": "analyze",
                        "outcome": "ok",
                        "error_code": None,
                        "attempt": attempt,
                        "terminal_ingest_outcome": "success",
                    }
                )
                outcomes.append(AnalyzeOutcome(entry.media_id, "ok", attempt, True))
            except BenchError as exc:
                ingest_failed = exc.code in {"media_unresolvable", "image_decode_failed"}
                store.append(
                    {
                        "manifest_media_id": entry.media_id,
                        "manifest_path": entry.path,
                        "content_sha256": entry.sha256,
                        "stack_media_id": None,
                        "phase": "ingest" if ingest_failed else "analyze",
                        "outcome": "failed",
                        "error_code": exc.code,
                        "attempt": attempt,
                        "terminal_ingest_outcome": exc.code if ingest_failed else "success",
                    }
                )
                terminal = attempt >= pair.item_max_attempts
                outcomes.append(AnalyzeOutcome(entry.media_id, "failed", attempt, terminal))
            except Exception as exc:  # noqa: BLE001 — per-item isolation
                store.append(
                    {
                        "manifest_media_id": entry.media_id,
                        "manifest_path": entry.path,
                        "content_sha256": entry.sha256,
                        "stack_media_id": None,
                        "phase": "analyze",
                        "outcome": "failed",
                        "error_code": "analyze_failed",
                        "attempt": attempt,
                        "terminal_ingest_outcome": "success",
                    }
                )
                terminal = attempt >= pair.item_max_attempts
                outcomes.append(AnalyzeOutcome(entry.media_id, "failed", attempt, terminal))
                _ = exc

        cluster_path = leg_dir / "cluster_job.json"
        cluster_ok = cluster_path.is_file() and _cluster_status_ok(cluster_path)
        if not cluster_ok:
            decision = run_cluster_phase(
                root,
                endpoint.stack_id,
                client,
                tenant_id=os.environ.get(endpoint.tenant_id_env, ""),
                item_max_attempts=pair.item_max_attempts,
                analyze_outcomes=outcomes,
            )
            if not decision.admits:
                return outcomes
        exports = leg_dir / "exports"
        needed = ("media_identities.json", "clusters.json", "cluster_members.json")
        if not all((exports / name).is_file() for name in needed):
            export_leg(client, root, endpoint.stack_id)
        return outcomes
    finally:
        if owned_client:
            client.close()


def run_pair(
    pair: StackPairConfig,
    *,
    manifest_path: Path | str,
    images_dir: Path | str | None,
    out_dir: Path | str,
    clients: dict[str, Any] | None = None,
    skip_preflight: bool = False,
    preflight_transports: dict[str, Any] | None = None,
) -> Path:
    # Load without images_dir first so floor/superset fail before any media I/O.
    # Deliberate metadata-only load (VLM6-PANEL6L-rvM-01 / OBS-04): only
    # entry counts and media_id sets are read here, never image bytes.
    manifest = load_bench_manifest(manifest_path, None, skip_hash_verification=True)
    assert_floor_fits_corpus(pair.accepted_set_floor, len(manifest.entries))
    if pair.manifest_sha256:
        digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
        if digest != pair.manifest_sha256:
            raise BenchError("manifest_sha_mismatch", "manifest bytes do not match manifest_sha256")
    if pair.baseline_manifest_path:
        baseline = load_bench_manifest(pair.baseline_manifest_path, None, skip_hash_verification=True)
        assert_baseline_superset(
            {e.media_id for e in manifest.entries},
            {e.media_id for e in baseline.entries},
        )
    preflight_results = None
    if not skip_preflight:
        from scripts.bench.preflight import preflight_pair

        keys = {s.stack_id: os.environ.get(s.api_key_env, "") for s in pair.stacks}
        # Abort before any media/run-dir writes; persist after init.
        preflight_results = preflight_pair(pair, transports=preflight_transports, api_keys=keys)
    root = init_run_dir(out_dir, pair, manifest_path)
    if preflight_results is not None:
        from scripts.bench.preflight import write_preflight_json

        for stack_id, result in preflight_results.items():
            dest = root / "legs" / stack_id / "preflight.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_preflight_json(dest, result)
    if pair.baseline_manifest_path:
        _stamp_run_field(root, "baseline_superset_checked", True)
    deadline = time.monotonic() + pair.wall_clock_timeout_sec
    incomplete: list[str] = []
    for endpoint in pair.stacks:
        client = (clients or {}).get(endpoint.stack_id)
        run_leg(
            endpoint,
            pair,
            manifest_path=manifest_path,
            images_dir=images_dir if images_dir is not None else pair.images_dir,
            run_dir=root,
            client=client,
            deadline=deadline,
        )
        if not _leg_complete(root, endpoint.stack_id):
            incomplete.append(endpoint.stack_id)
    if incomplete:
        _set_phase(root, RunPhase.INCOMPLETE)
        raise BenchError(
            "run_incomplete",
            f"leg(s) not exported: {incomplete}; not marking run done",
        )
    _set_phase(root, RunPhase.DONE)
    return root


def read_status(run_dir: Path | str) -> dict[str, Any]:
    root = Path(run_dir)
    if not root.is_dir() or not (root / "run.json").is_file():
        raise BenchError("run_dir_invalid", f"run-dir missing or corrupt: {root}")
    run_doc = json.loads((root / "run.json").read_text(encoding="utf-8"))
    legs: dict[str, Any] = {}
    for leg_dir in sorted((root / "legs").glob("*")):
        if not leg_dir.is_dir():
            continue
        store = ItemOutcomeStore(leg_dir / "items.jsonl")
        records = store.read_all() if store.path.exists() else []
        by_phase: dict[str, dict[str, int]] = {}
        for record in records:
            phase = str(record.get("phase", "?"))
            outcome = str(record.get("outcome", "?"))
            by_phase.setdefault(phase, {})
            by_phase[phase][outcome] = by_phase[phase].get(outcome, 0) + 1
        cluster = (leg_dir / "cluster_job.json").is_file()
        exported = (leg_dir / "exports" / "media_identities.json").is_file()
        failed = _terminal_leg_refusal(leg_dir / "leg_outcome.json")
        if failed:
            phase_est = "failed"
        elif exported:
            phase_est = "done"
        elif cluster:
            phase_est = "export"
        elif any(r.get("phase") == "analyze" for r in records):
            phase_est = "cluster"
        elif any(r.get("phase") == "ingest" for r in records):
            phase_est = "analyze"
        else:
            phase_est = "ingest"
        legs[leg_dir.name] = {
            "counts": by_phase,
            "phase": phase_est,
            "cluster_job": cluster,
            "exports": exported,
        }
    return {"run": run_doc, "legs": legs}


def _analyze_job_failed(job: Any) -> bool:
    if not isinstance(job, dict):
        return False
    status = str(job.get("status", "")).lower()
    return status == ANALYZE_PARTIAL_SUCCESS


def _stack_media_id_from_job(job: Any, fallback: int) -> int:
    del fallback  # never echo the manifest id into the join domain
    if not isinstance(job, dict):
        raise BenchError("stack_media_id_missing", "analyze job payload is not an object")
    for key in ("media_id", "stack_media_id"):
        value = job.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    raise BenchError("stack_media_id_missing", "analyze job payload has no media_id/stack_media_id")


def _leg_complete(run_dir: Path, stack_id: str) -> bool:
    leg = run_dir / "legs" / stack_id
    if _terminal_leg_refusal(leg / "leg_outcome.json"):
        return False
    exports = leg / "exports"
    needed = ("media_identities.json", "clusters.json", "cluster_members.json")
    return _cluster_status_ok(leg / "cluster_job.json") and all((exports / name).is_file() for name in needed)


def _terminal_leg_refusal(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchError("leg_outcome_unreadable", f"unreadable leg_outcome.json: {path}") from exc
    return doc.get("error_code") == "cluster_gate_refused"


def _stamp_run_field(run_dir: Path, key: str, value: Any) -> None:
    path = run_dir / "run.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc[key] = value
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _cluster_status_ok(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("status", "")).lower() in CLUSTER_SUCCESS_STATUSES


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise BenchError("wall_clock_exceeded", "wall-clock budget exhausted")


def _set_phase(run_dir: Path, phase: str) -> None:
    path = run_dir / "run.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["phase"] = phase
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _package_sha(rel_path: str) -> str:
    repo = Path(__file__).resolve().parents[4]
    tracked = f"apps/prototype-description-service/{rel_path}"
    try:
        sha = (
            subprocess.check_output(
                ["git", "log", "-1", "--format=%H", "--", tracked],
                cwd=repo,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        if sha:
            return sha
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        raise BenchError("provenance_sha_unavailable", f"git sha unavailable for {tracked}") from exc
    raise BenchError("provenance_sha_unavailable", f"git sha empty for {tracked}")
