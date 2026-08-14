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
        if outcome == "ok":
            successes += 1
            continue
        if outcome == "failed":
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
        "cli_sha": _git_sha(),
        "harness_sha": _git_sha(),
        "license_banner": LICENSE_BANNER,
        "wall_clock_timeout_sec": pair.wall_clock_timeout_sec,
        "job_poll_timeout_sec": pair.job_poll_timeout_sec,
        "phase": "init",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bootstrap_seed": pair.bootstrap_seed,
    }
    (root / "run.json").write_text(json.dumps(run_doc, indent=2), encoding="utf-8")
    redacted = {
        "head_to_head_delta": pair.head_to_head_delta,
        "bootstrap_seed": pair.bootstrap_seed,
        "primary_endpoint": pair.primary_endpoint,
        "secondary_endpoints": list(pair.secondary_endpoints),
        "accepted_set_floor": pair.accepted_set_floor,
        "max_differential_attrition": pair.max_differential_attrition,
        "allow_private_source": pair.allow_private_source,
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
    (root / "stack_pair.json").write_text(json.dumps(redacted, indent=2), encoding="utf-8")
    digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    (root / "manifest.sha").write_text(digest + "\n", encoding="utf-8")
    (root / "manifest.json").write_bytes(Path(manifest_path).read_bytes())
    run_doc["manifest_path"] = str(Path(manifest_path))
    (root / "run.json").write_text(json.dumps(run_doc, indent=2), encoding="utf-8")
    redacted["baseline_manifest_path"] = pair.baseline_manifest_path
    (root / "stack_pair.json").write_text(json.dumps(redacted, indent=2), encoding="utf-8")
    (root / "manifest.json").write_bytes(Path(manifest_path).read_bytes())
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
    if not decision.admits:
        outcome = {
            "status": "failed",
            "phase": "failed",
            "error_code": "cluster_gate_refused",
        }
        (leg / "leg_outcome.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        return decision
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
            prior = latest or store.latest(entry.media_id, "ingest")
            attempt = int((prior or {}).get("attempt", 0)) + 1
            if prior is not None and prior.get("outcome") == "failed" and attempt > pair.item_max_attempts:
                outcomes.append(AnalyzeOutcome(entry.media_id, "failed", pair.item_max_attempts, True))
                continue
            try:
                data = resolve_media_bytes(
                    entry,
                    images_dir,
                    url_map_path=pair.media_url_map_path,
                    allow_private_source=pair.allow_private_source,
                )
                width, height = decode_image_dimensions(data)
                store.append(
                    {
                        "manifest_media_id": entry.media_id,
                        "manifest_path": entry.path,
                        "content_sha256": entry.sha256,
                        "stack_media_id": entry.media_id,
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
                client.wait_job(job_id)
                store.append(
                    {
                        "manifest_media_id": entry.media_id,
                        "manifest_path": entry.path,
                        "content_sha256": entry.sha256,
                        "stack_media_id": entry.media_id,
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
                store.append(
                    {
                        "manifest_media_id": entry.media_id,
                        "manifest_path": entry.path,
                        "content_sha256": entry.sha256,
                        "phase": "ingest" if exc.code in {"media_unresolvable", "image_decode_failed"} else "analyze",
                        "outcome": "failed",
                        "error_code": exc.code,
                        "attempt": attempt,
                        "terminal_ingest_outcome": exc.code,
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
                        "phase": "analyze",
                        "outcome": "failed",
                        "error_code": "analyze_failed",
                        "attempt": attempt,
                        "terminal_ingest_outcome": "analyze_failed",
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
    skip_preflight: bool = True,
) -> Path:
    # Load without images_dir first so floor/superset fail before any media I/O.
    manifest = load_bench_manifest(manifest_path, None)
    assert_floor_fits_corpus(pair.accepted_set_floor, len(manifest.entries))
    if pair.manifest_sha256:
        digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
        if digest != pair.manifest_sha256:
            raise BenchError("manifest_sha_mismatch", "manifest bytes do not match manifest_sha256")
    if pair.baseline_manifest_path:
        baseline = load_bench_manifest(pair.baseline_manifest_path, None)
        assert_baseline_superset(
            {e.media_id for e in manifest.entries},
            {e.media_id for e in baseline.entries},
        )
    root = init_run_dir(out_dir, pair, manifest_path)
    deadline = time.monotonic() + pair.wall_clock_timeout_sec
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
    _set_phase(root, "done")
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
        failed = (leg_dir / "leg_outcome.json").is_file()
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


def _cluster_status_ok(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(payload.get("status", "")).lower() in {"success", "completed", "ok", "completed_with_errors"}


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise BenchError("wall_clock_exceeded", "wall-clock budget exhausted")


def _set_phase(run_dir: Path, phase: str) -> None:
    path = run_dir / "run.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["phase"] = phase
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"
