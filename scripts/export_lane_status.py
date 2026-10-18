#!/usr/bin/env python3
"""Export live lane statuses for the owned-path overlap check.

``check_lane_manifest_overlaps.py`` is deliberately stdlib-only: it reads the
checked-in lane manifests and knows nothing about the handoff database.  The
manifests, however, do not carry a lifecycle ``status`` key at all, so the
overlap gate needs an authoritative live view from the orchestrator to tell a
running lane from one that merged months ago.

This helper produces that view.  It reads the task refs present in the manifest
directory and asks the public orchestrator API for each task's lanes, writing
``{"lanes": [{"task_ref", "lane_id", "status"}, ...]}``.  Asking per task ref is
deliberate: a task-less lane listing resolves the active task from the workspace
path and raises on a repository with several live tasks.

Exits 0 on success, 2 when the orchestrator package or database is unavailable
(the caller treats that as "skip the gate", not "fail the build").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def manifest_task_refs(manifest_dir: Path) -> list[str]:
    """Return the task refs described by the manifests in ``manifest_dir``.

    The ``task_ref`` key inside the document wins over the file stem so a
    renamed manifest file still resolves to the right task.
    """
    task_refs: list[str] = []
    seen: set[str] = set()
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            document = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        task_ref = document.get("task_ref")
        if not isinstance(task_ref, str) or not task_ref.strip():
            task_ref = path.stem
        task_ref = task_ref.strip()
        if task_ref and task_ref not in seen:
            seen.add(task_ref)
            task_refs.append(task_ref)
    return task_refs


def normalise_rows(task_ref: str, payload: Any) -> list[dict[str, str]]:
    """Pull ``{task_ref, lane_id, status}`` triples out of a lane-list envelope."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    rows = payload.get("lanes") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    normalised: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lane_id = row.get("lane_id")
        status = row.get("status")
        if not isinstance(lane_id, str) or not lane_id.strip():
            continue
        normalised.append(
            {
                "task_ref": str(row.get("task_ref") or task_ref),
                "lane_id": lane_id,
                # A lane row with a NULL status is still live; only the manifest
                # side treats a missing status as "unknown".
                "status": status if isinstance(status, str) and status else "active",
            }
        )
    return normalised


def collect(manifest_dir: Path, workspace_root: Path, page_size: int) -> list[dict[str, str]]:
    from workbay_handoff_mcp import RuntimeConfig, configure_runtime
    from workbay_orchestrator_mcp import api  # type: ignore[import-untyped]

    runtime = RuntimeConfig.for_repo(workspace_root)
    configure_runtime(runtime)
    api.configure_runtime(runtime)

    lanes: list[dict[str, str]] = []
    for task_ref in manifest_task_refs(manifest_dir):
        offset = 0
        while True:
            response = api.manage_worktree_lane(
                operation="list",
                task_ref=task_ref,
                status="all",
                limit=page_size,
                offset=offset,
            )
            if not response.get("ok", True):
                raise RuntimeError(f"lane listing failed for {task_ref}: {response.get('error')}")
            page = normalise_rows(task_ref, response)
            lanes.extend(page)
            envelope = response.get("data") if isinstance(response.get("data"), dict) else response
            has_more = bool(envelope.get("has_more")) if isinstance(envelope, dict) else False
            if not has_more or not page:
                break
            offset += len(page)
    return lanes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--page-size", type=int, default=200)
    args = parser.parse_args(argv)

    if args.page_size <= 0:
        parser.error("--page-size must be a positive integer")
    if not args.manifest_dir.is_dir():
        print(f"No lane manifest directory at {args.manifest_dir}.", file=sys.stderr)
        return 2

    try:
        lanes = collect(args.manifest_dir, args.workspace_root, args.page_size)
    except ImportError as error:
        print(f"Orchestrator package unavailable: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - any backend fault is "no export"
        print(f"Lane status export failed: {error}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"lanes": lanes}) + "\n")
    print(f"Exported {len(lanes)} live lane rows to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
