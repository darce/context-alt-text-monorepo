from __future__ import annotations

import os
import re
from pathlib import Path


PYENV_VERSION_PATTERN = re.compile(r"\bPYENV_VERSION=([A-Za-z0-9._-]+)")


def extract_pyenv_version(commands: list[str]) -> str | None:
    for command in commands:
        match = PYENV_VERSION_PATTERN.search(str(command))
        if match:
            return match.group(1)
    return None


def _lane_runtime_profile(
    orchestrator_root: Path,
    *,
    task_ref: str | None,
    lane_id: str | None,
) -> tuple[str | None, list[str]]:
    if not task_ref or not lane_id:
        return None, []
    try:
        from lane_manifest import get_lane_config

        lane = get_lane_config(task_ref, lane_id, orchestrator_root=str(orchestrator_root))
    except (ImportError, FileNotFoundError, KeyError, ValueError) as exc:
        import sys as _sys
        print(f"_lane_runtime_profile: could not load lane config: {exc}", file=_sys.stderr)
        return None, []
    if not isinstance(lane, dict):
        return None, []

    pyenv_version = extract_pyenv_version([str(command) for command in lane.get("test_commands", [])])

    extra_paths: list[str] = []
    if pyenv_version:
        pyenv_root = Path.home() / ".pyenv"
        venv_bin = pyenv_root / "versions" / pyenv_version / "bin"
        if venv_bin.exists():
            extra_paths.append(str(venv_bin))
        for candidate in (pyenv_root / "shims", pyenv_root / "bin"):
            if candidate.exists():
                extra_paths.append(str(candidate))
    return pyenv_version, extra_paths


def pythonpath_env(
    orchestrator_root: Path,
    *,
    task_ref: str | None = None,
    lane_id: str | None = None,
) -> dict[str, str]:
    """Return an env dict with repo-local MCP, writable temp, and lane runtime hints."""
    env = os.environ.copy()
    pythonpath_parts = [
        str(orchestrator_root / "packages" / "agent-handoff-mcp" / "src"),
        str(orchestrator_root / "packages" / "codex-subagent-bridge" / "src"),
    ]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = ":".join([*pythonpath_parts, existing]) if existing else ":".join(pythonpath_parts)

    temp_root = orchestrator_root / ".task-state" / "tmp"
    if lane_id:
        temp_root = temp_root / lane_id
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_text = str(temp_root)
    env["TMPDIR"] = temp_text
    env["TMP"] = temp_text
    env["TEMP"] = temp_text

    pyenv_version, extra_paths = _lane_runtime_profile(
        orchestrator_root,
        task_ref=task_ref,
        lane_id=lane_id,
    )
    if pyenv_version:
        env["PYENV_VERSION"] = pyenv_version
    if extra_paths:
        current_path = env.get("PATH", "")
        env["PATH"] = ":".join([*extra_paths, current_path]) if current_path else ":".join(extra_paths)
    return env
