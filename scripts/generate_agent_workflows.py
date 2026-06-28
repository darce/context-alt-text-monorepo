#!/usr/bin/env python3
"""Delegate to the hoisted generator and apply the Cursor skills-only patch."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_GENERATOR = (
    REPO_ROOT
    / ".workbay/remote/packages/workbay-system/workstate_system/payload/scripts/generate_agent_workflows.py"
)
CURSOR_PATCH = REPO_ROOT / "scripts" / "apply_cursor_skills_only_surface.py"


def _load_remote_generator():
    if not REMOTE_GENERATOR.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_gaw_remote", REMOTE_GENERATOR)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def __getattr__(name: str):
    # workbay-bootstrap coherence probes seams like _expected_hooks_outputs
    # by importing this script; delegate to the hoisted generator.
    module = _load_remote_generator()
    if module is None or not hasattr(module, name):
        raise AttributeError(name)
    return getattr(module, name)


def _runs_plugin_mode(argv: list[str]) -> bool:
    for index, arg in enumerate(argv):
        if arg == "--mode=plugin":
            return True
        if arg == "--mode" and index + 1 < len(argv) and argv[index + 1] == "plugin":
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not REMOTE_GENERATOR.is_file():
        print(
            f"generate_agent_workflows shim: missing hoisted generator at {REMOTE_GENERATOR}",
            file=sys.stderr,
        )
        return 1
    if not CURSOR_PATCH.is_file():
        print(
            f"generate_agent_workflows shim: missing Cursor patch at {CURSOR_PATCH}",
            file=sys.stderr,
        )
        return 1

    completed = subprocess.run(
        [sys.executable, str(REMOTE_GENERATOR), *args],
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode

    if not _runs_plugin_mode(args):
        return 0

    patch_args = [sys.executable, str(CURSOR_PATCH)]
    if "--check" in args:
        patch_args.append("--check")
    patched = subprocess.run(patch_args, check=False)
    return patched.returncode


if __name__ == "__main__":
    raise SystemExit(main())
