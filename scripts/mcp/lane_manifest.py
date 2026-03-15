#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
MANIFEST_DIR = REPO_ROOT / "config" / "lane-orchestration"


def manifest_dir() -> Path:
    return MANIFEST_DIR


def list_task_refs() -> list[str]:
    if not MANIFEST_DIR.exists():
        return []
    return sorted(path.stem for path in MANIFEST_DIR.glob("*.json"))


def load_manifest(task_ref: str) -> dict[str, Any]:
    path = MANIFEST_DIR / f"{task_ref}.json"
    if not path.exists():
        raise FileNotFoundError(f"lane manifest not found for task {task_ref}: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"lane manifest must be a JSON object: {path}")
    return data


def list_lanes(task_ref: str) -> list[str]:
    manifest = load_manifest(task_ref)
    lanes = manifest.get("lanes", {})
    if not isinstance(lanes, dict):
        return []
    return sorted(lanes.keys())


def _lane_manifest(task_ref: str, lane_id: str) -> dict[str, Any] | None:
    lanes = load_manifest(task_ref).get("lanes", {})
    if not isinstance(lanes, dict):
        return None
    lane = lanes.get(lane_id)
    return lane if isinstance(lane, dict) else None


def expand_path_template(template: str, *, orchestrator_root: str) -> str:
    return template.replace("{orchestrator_root}", orchestrator_root)


def get_lane_config(task_ref: str, lane_id: str, *, orchestrator_root: str | None = None) -> dict[str, Any] | None:
    lane = _lane_manifest(task_ref, lane_id)
    if lane is None:
        return None
    result = dict(lane)
    if orchestrator_root and isinstance(result.get("worktree_path"), str):
        result["worktree_path"] = expand_path_template(result["worktree_path"], orchestrator_root=orchestrator_root)
    return result


def infer_lane_from_branch(branch: str, task_ref: str | None = None, *, orchestrator_root: str | None = None) -> str:
    if not branch:
        return ""

    task_refs = [task_ref] if task_ref else list_task_refs()
    matches: list[str] = []
    for candidate_task in task_refs:
        if not candidate_task:
            continue
        manifest = load_manifest(candidate_task)
        lanes = manifest.get("lanes", {})
        if not isinstance(lanes, dict):
            continue
        for lane_id, lane in lanes.items():
            if not isinstance(lane, dict):
                continue
            if lane.get("branch") == branch:
                matches.append(lane_id)
    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    return ""


def route_patterns(task_ref: str) -> list[tuple[str, str]]:
    manifest = load_manifest(task_ref)
    routes = manifest.get("routing", [])
    if not isinstance(routes, list):
        return []
    patterns: list[tuple[str, str]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        prefix = route.get("prefix")
        lane = route.get("lane")
        if isinstance(prefix, str) and isinstance(lane, str):
            patterns.append((prefix, lane))
    return patterns


def lane_route_hints(task_ref: str) -> dict[str, tuple[str, ...]]:
    manifest = load_manifest(task_ref)
    lanes = manifest.get("lanes", {})
    if not isinstance(lanes, dict):
        return {}

    hints: dict[str, tuple[str, ...]] = {}
    for lane_id, lane in lanes.items():
        if not isinstance(lane_id, str) or not isinstance(lane, dict):
            continue
        values: list[str] = [lane_id]
        title = lane.get("title")
        branch = lane.get("branch")
        worktree_path = lane.get("worktree_path")
        route_hints_value = lane.get("route_hints", [])
        if isinstance(title, str) and title.strip():
            values.append(title)
            values.append(title.lower())
        if isinstance(branch, str) and branch.strip():
            values.append(branch)
        if isinstance(worktree_path, str) and worktree_path.strip():
            values.append(worktree_path)
            values.append(Path(worktree_path).name)
        if isinstance(route_hints_value, list):
            values.extend(str(item) for item in route_hints_value if str(item).strip())
        normalized = tuple(dict.fromkeys(value for value in values if value and value.strip()))
        hints[lane_id] = normalized
    return hints


def merge_order(task_ref: str) -> list[str]:
    manifest = load_manifest(task_ref)
    order = manifest.get("merge_order", [])
    if not isinstance(order, list):
        return []
    return [lane for lane in order if isinstance(lane, str)]


def downstream_lanes(task_ref: str, lane_id: str) -> list[str]:
    """Return the declared downstream dependents for *lane_id*, or ``[]``."""
    manifest = load_manifest(task_ref)
    downstream = manifest.get("downstream", {})
    if not isinstance(downstream, dict):
        return []
    deps = downstream.get(lane_id, [])
    if not isinstance(deps, list):
        return []
    return [d for d in deps if isinstance(d, str)]
