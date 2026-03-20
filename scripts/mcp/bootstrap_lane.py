#!/usr/bin/env python3
"""Bootstrap lane dependencies: link or install composer/npm for worktree lanes."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lane_manifest import get_lane_config


def _bootstrap(
    orchestrator_root: str | Path,
    task_ref: str,
    lane_id: str,
    worktree_path: str | Path,
) -> int:
    lane_cfg = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root))
    if not lane_cfg:
        print(f"No lane config found for {task_ref} / {lane_id}")
        return 1

    if "owned_paths" not in lane_cfg:
        print(f"Warning: 'owned_paths' not found in lane config for {lane_id}.")

    owned_paths = [str(p).strip() for p in lane_cfg.get("owned_paths", []) if str(p).strip()]
    
    for relative_path in owned_paths:
        full_path = Path(worktree_path) / relative_path
        if not full_path.is_dir():
            continue

        # PHP Bootstrap
        if (full_path / "composer.json").is_file():
            print(f"Bootstrapping PHP/Composer dependencies in {relative_path}...")
            root_vendor = Path(orchestrator_root) / relative_path / "vendor"
            lane_vendor = full_path / "vendor"
            if root_vendor.is_dir() and not lane_vendor.exists():
                print(f"  Symlinking vendor from orchestrator root: {root_vendor}")
                lane_vendor.symlink_to(root_vendor, target_is_directory=True)
            elif not lane_vendor.exists():
                print(f"  Running composer install in {relative_path}")
                result = subprocess.run(
                    ["composer", "install", "--no-interaction", "--no-progress"],
                    cwd=full_path,
                )
                if result.returncode != 0:
                    print(f"Error: composer install failed with code {result.returncode}")
                    return result.returncode
            else:
                print(f"  Vendor already present in {relative_path}")

        # JS/Node Bootstrap
        if (full_path / "package.json").is_file():
            print(f"Bootstrapping NPM dependencies in {relative_path}...")
            root_nm = Path(orchestrator_root) / relative_path / "node_modules"
            lane_nm = full_path / "node_modules"
            if root_nm.is_dir() and not lane_nm.exists():
                print(f"  Symlinking node_modules from orchestrator root: {root_nm}")
                lane_nm.symlink_to(root_nm, target_is_directory=True)
            elif not lane_nm.exists():
                print(f"  Running npm install in {relative_path}")
                result = subprocess.run(
                    ["npm", "install", "--no-audit", "--no-fund"],
                    cwd=full_path,
                )
                if result.returncode != 0:
                    print(f"Error: npm install failed with code {result.returncode}")
                    return result.returncode
            else:
                print(f"  Node modules already present in {relative_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser("Bootstrap lane dependencies")
    parser.add_argument("--orchestrator-root", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--worktree-path", required=True)
    args = parser.parse_args()

    return _bootstrap(
        orchestrator_root=args.orchestrator_root,
        task_ref=args.task_ref,
        lane_id=args.lane_id,
        worktree_path=args.worktree_path,
    )


if __name__ == "__main__":
    sys.exit(main())
