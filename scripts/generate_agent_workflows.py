#!/usr/bin/env python3
"""Delegate to the hoisted generator and apply the Cursor skills-only patch."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # single source of truth for the overlay clone location — no hardcoded paths
    from scripts._overlay_clone import hoisted_generator_path
except ModuleNotFoundError:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from _overlay_clone import hoisted_generator_path

REMOTE_GENERATOR = hoisted_generator_path(REPO_ROOT)
CURSOR_PATCH = REPO_ROOT / "scripts" / "apply_cursor_skills_only_surface.py"
LOCAL_MANIFEST = REPO_ROOT / "config" / "agent-workflows" / "portable_commands.json"
LOCAL_SKILLS = REPO_ROOT / "skills"


def _installed_workbay_tool() -> tuple[Path, Path] | None:
    """Return (python, generator) for the installed uv tool payload, if present."""
    tool_dir = os.environ.get("WORKBAY_UV_TOOL_DIR")
    if tool_dir is None:
        completed = subprocess.run(
            ["uv", "tool", "dir"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return None
        tool_dir = completed.stdout.strip()
    if not tool_dir:
        return None

    workbay_tool = Path(tool_dir) / "workbay"
    python = workbay_tool / "bin" / "python"
    site_packages_parent = workbay_tool / "lib"
    if not python.is_file() or not site_packages_parent.is_dir():
        return None
    matches = sorted(
        site_packages_parent.glob(
            "python*/site-packages/workbay_system/payload/scripts/generate_agent_workflows.py"
        )
    )
    if not matches:
        return None
    return python, matches[0]


def _load_remote_generator():
    if REMOTE_GENERATOR is None or not REMOTE_GENERATOR.is_file():
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
    if REMOTE_GENERATOR is None or not REMOTE_GENERATOR.is_file():
        installed_tool = _installed_workbay_tool()
        if installed_tool is None:
            print(
                "generate_agent_workflows shim: neither .workbay/remote nor the "
                "installed workbay uv tool payload is available.",
                file=sys.stderr,
            )
            return 1
        python, generator = installed_tool
        completed = subprocess.run(
            [
                str(python),
                str(generator),
                "--manifest",
                str(LOCAL_MANIFEST),
                "--skills-source-root",
                str(LOCAL_SKILLS),
                "--target",
                str(REPO_ROOT),
                *args,
            ],
            check=False,
        )
        return completed.returncode
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
