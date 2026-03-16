#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
MANIFEST_DIR = REPO_ROOT / "config" / "lane-orchestration"

REQUIRED_TOP_LEVEL_KEYS = ("task_ref", "merge_order", "lanes", "downstream")
REQUIRED_LANE_KEYS = ("branch", "worktree_path", "owned_paths", "test_commands")


def manifest_dir() -> Path:
    return MANIFEST_DIR


def list_task_refs() -> list[str]:
    if not MANIFEST_DIR.exists():
        return []
    return sorted(path.stem for path in MANIFEST_DIR.glob("*.json"))


def _require_key(container: dict[str, Any], key: str, *, path: Path, context: str) -> None:
    if key not in container:
        raise RuntimeError(f"lane manifest missing required {context} key '{key}': {path}")


def _derive_commit_paths(owned_paths: list[str]) -> list[str]:
    derived: list[str] = []
    for path in owned_paths:
        value = str(path).strip()
        if not value:
            continue
        if value.endswith("/**"):
            value = value[:-3]
        derived.append(value.rstrip("/") if value != "/" else value)
    return list(dict.fromkeys(item for item in derived if item))


def _derive_routing_from_owned_paths(lanes: dict[str, Any]) -> list[tuple[str, str]]:
    derived: list[tuple[str, str]] = []
    for lane_id, lane in lanes.items():
        if not isinstance(lane_id, str) or not isinstance(lane, dict):
            continue
        owned_paths = lane.get("owned_paths", [])
        if not isinstance(owned_paths, list):
            continue
        for raw in owned_paths:
            value = str(raw).strip()
            if not value:
                continue
            if value.endswith("/**"):
                value = value[:-3].rstrip("/") + "/"
            derived.append((value, lane_id))
    return list(dict.fromkeys(derived))


def validate_manifest(data: dict[str, Any], path: Path) -> dict[str, Any]:
    for key in REQUIRED_TOP_LEVEL_KEYS:
        _require_key(data, key, path=path, context="top-level")

    merge_order = data.get("merge_order")
    lanes = data.get("lanes")
    downstream = data.get("downstream")
    if not isinstance(merge_order, list):
        raise RuntimeError(f"lane manifest merge_order must be a list: {path}")
    if not isinstance(lanes, dict):
        raise RuntimeError(f"lane manifest lanes must be an object: {path}")
    if not isinstance(downstream, dict):
        raise RuntimeError(f"lane manifest downstream must be an object: {path}")

    lane_ids = set(lane_id for lane_id in lanes.keys() if isinstance(lane_id, str))
    unknown_merge_order = [lane_id for lane_id in merge_order if isinstance(lane_id, str) and lane_id not in lane_ids]
    if unknown_merge_order:
        raise RuntimeError(
            f"lane manifest merge_order references unknown lane(s) {unknown_merge_order}: {path}"
        )

    for lane_id, lane in lanes.items():
        if not isinstance(lane_id, str) or not isinstance(lane, dict):
            raise RuntimeError(f"lane manifest lanes entries must be string->object pairs: {path}")
        for key in REQUIRED_LANE_KEYS:
            _require_key(lane, key, path=path, context=f"lane '{lane_id}'")
        if not isinstance(lane.get("branch"), str) or not str(lane.get("branch")).strip():
            raise RuntimeError(f"lane '{lane_id}' must define a non-empty branch: {path}")
        if not isinstance(lane.get("worktree_path"), str) or not str(lane.get("worktree_path")).strip():
            raise RuntimeError(f"lane '{lane_id}' must define a non-empty worktree_path: {path}")
        if not isinstance(lane.get("owned_paths"), list):
            raise RuntimeError(f"lane '{lane_id}' owned_paths must be a list: {path}")
        if not isinstance(lane.get("test_commands"), list):
            raise RuntimeError(f"lane '{lane_id}' test_commands must be a list: {path}")
        if "commit_paths" in lane and not isinstance(lane.get("commit_paths"), list):
            raise RuntimeError(f"lane '{lane_id}' commit_paths must be a list when present: {path}")
        if "tooling_paths" in lane and not isinstance(lane.get("tooling_paths"), list):
            raise RuntimeError(f"lane '{lane_id}' tooling_paths must be a list when present: {path}")
        if "guidance_fallbacks" in lane and not isinstance(lane.get("guidance_fallbacks"), list):
            raise RuntimeError(f"lane '{lane_id}' guidance_fallbacks must be a list when present: {path}")

    for lane_id, dependents in downstream.items():
        if lane_id not in lane_ids:
            raise RuntimeError(f"lane manifest downstream references unknown source lane '{lane_id}': {path}")
        if not isinstance(dependents, list):
            raise RuntimeError(f"lane manifest downstream for lane '{lane_id}' must be a list: {path}")
        unknown_dependents = [dep for dep in dependents if isinstance(dep, str) and dep not in lane_ids]
        if unknown_dependents:
            raise RuntimeError(
                f"lane manifest downstream for lane '{lane_id}' references unknown lane(s) {unknown_dependents}: {path}"
            )

    return data


def load_manifest(task_ref: str) -> dict[str, Any]:
    path = MANIFEST_DIR / f"{task_ref}.json"
    if not path.exists():
        raise FileNotFoundError(f"lane manifest not found for task {task_ref}: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"lane manifest must be a JSON object: {path}")
    return validate_manifest(data, path)


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
    owned_paths = [str(item) for item in result.get("owned_paths", []) if str(item).strip()]
    commit_paths = result.get("commit_paths")
    if not isinstance(commit_paths, list) or not commit_paths:
        result["commit_paths"] = _derive_commit_paths(owned_paths)
    result.setdefault("tooling_paths", [])
    result.setdefault("guidance_fallbacks", [])
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


def infer_task_from_branch_or_worktree(
    branch: str,
    *,
    worktree_path: str | None = None,
    orchestrator_root: str | None = None,
) -> str:
    candidates: list[str] = []
    normalized_worktree = str(Path(worktree_path).expanduser().resolve()) if worktree_path else ""

    for candidate_task in list_task_refs():
        manifest = load_manifest(candidate_task)
        lanes = manifest.get("lanes", {})
        if not isinstance(lanes, dict):
            continue
        for _lane_id, lane in lanes.items():
            if not isinstance(lane, dict):
                continue
            lane_branch = str(lane.get("branch", "")).strip()
            lane_worktree = str(lane.get("worktree_path", "")).strip()
            if orchestrator_root and lane_worktree:
                lane_worktree = expand_path_template(lane_worktree, orchestrator_root=orchestrator_root)
            lane_worktree_resolved = (
                str(Path(lane_worktree).expanduser().resolve()) if lane_worktree else ""
            )
            if branch and lane_branch == branch:
                candidates.append(candidate_task)
            elif normalized_worktree and lane_worktree_resolved == normalized_worktree:
                candidates.append(candidate_task)

    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0]
    return ""


def route_patterns(task_ref: str) -> list[tuple[str, str]]:
    manifest = load_manifest(task_ref)
    routes = manifest.get("routing", [])
    lanes = manifest.get("lanes", {})
    if not isinstance(routes, list) or not routes:
        return _derive_routing_from_owned_paths(lanes if isinstance(lanes, dict) else {})
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


def guidance_fallbacks(task_ref: str, lane_id: str) -> list[dict[str, Any]]:
    lane = _lane_manifest(task_ref, lane_id)
    if lane is None:
        return []
    fallbacks = lane.get("guidance_fallbacks", [])
    if not isinstance(fallbacks, list):
        return []
    return [row for row in fallbacks if isinstance(row, dict)]
