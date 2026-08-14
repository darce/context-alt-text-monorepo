"""S1: persist public exports. S2 extends with GT mapping symbols."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.bench.stack_pair import BenchError

_CLUSTER_SUCCESS = frozenset({"success", "completed", "ok", "completed_with_errors"})


@dataclass
class LegExport:
    stack_id: str
    media_identities: Any
    clusters: Any
    cluster_members: Any
    paths: dict[str, Path] = field(default_factory=dict)


def require_cluster_success(run_dir: Path | str, stack_id: str) -> dict[str, Any]:
    path = Path(run_dir) / "legs" / stack_id / "cluster_job.json"
    if not path.is_file():
        raise BenchError("cluster_gate_refused", f"cluster_job.json missing for {stack_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = str(payload.get("status", "")).lower()
    if status not in _CLUSTER_SUCCESS:
        raise BenchError("cluster_gate_refused", f"cluster job status {status!r} is not success")
    return payload


def export_leg(client: Any, run_dir: Path | str, stack_id: str) -> LegExport:
    require_cluster_success(run_dir, stack_id)
    media_ids = _roster_stack_media_ids(run_dir, stack_id)
    identities = client.media_identities(media_ids)
    clusters = client.clusters()
    members: Any
    if isinstance(clusters, list):
        collected: list[Any] = []
        for cluster in clusters:
            cid = cluster.get("id") or cluster.get("cluster_id") if isinstance(cluster, dict) else None
            if cid is None:
                continue
            collected.append(client.cluster_members(str(cid)))
        members = collected
    elif isinstance(clusters, dict):
        rows = clusters.get("data") or clusters.get("clusters") or []
        members = [client.cluster_members(str(c.get("id") or c.get("cluster_id"))) for c in rows if isinstance(c, dict)]
    else:
        members = []

    export_dir = Path(run_dir) / "legs" / stack_id / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "media_identities": export_dir / "media_identities.json",
        "clusters": export_dir / "clusters.json",
        "cluster_members": export_dir / "cluster_members.json",
    }
    _write_preserved(paths["media_identities"], identities)
    _write_preserved(paths["clusters"], clusters)
    _write_preserved(paths["cluster_members"], members)
    return LegExport(
        stack_id=stack_id,
        media_identities=identities,
        clusters=clusters,
        cluster_members=members,
        paths=paths,
    )


def load_leg_exports(run_dir: Path | str, stack_id: str) -> LegExport:
    export_dir = Path(run_dir) / "legs" / stack_id / "exports"
    return LegExport(
        stack_id=stack_id,
        media_identities=json.loads((export_dir / "media_identities.json").read_text(encoding="utf-8")),
        clusters=json.loads((export_dir / "clusters.json").read_text(encoding="utf-8")),
        cluster_members=json.loads((export_dir / "cluster_members.json").read_text(encoding="utf-8")),
        paths={
            "media_identities": export_dir / "media_identities.json",
            "clusters": export_dir / "clusters.json",
            "cluster_members": export_dir / "cluster_members.json",
        },
    )


def _write_preserved(path: Path, payload: Any) -> None:
    # Persist the upstream payload as-is. Never invent envelope fields.
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _roster_stack_media_ids(run_dir: Path | str, stack_id: str) -> list[int]:
    from scripts.bench.corpus import ItemOutcomeStore

    store = ItemOutcomeStore(Path(run_dir) / "legs" / stack_id / "items.jsonl")
    ids: list[int] = []
    seen: set[int] = set()
    for record in store.read_all():
        if record.get("phase") != "analyze" or record.get("outcome") != "ok":
            continue
        mid = record.get("stack_media_id")
        if isinstance(mid, int) and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids
