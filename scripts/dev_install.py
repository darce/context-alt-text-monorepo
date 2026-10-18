#!/usr/bin/env python3
"""Dev-editable redirect heal for this consumer repo — deliberately a no-op.

``workbay_lifecycle.uv_provisioning._heal_dev_editables`` runs this script after
every ``uv sync`` that creates a worktree ``.venv``, to re-point copy-editable
workspace members at their source trees (uv has no PEP 660 support, so a sync
reverts src redirects). It resolves the script at ``<worktree>/scripts/dev_install.py``
and — when a ``packages/`` directory exists — treats its absence as fail-closed,
aborting ``make task-start`` with ``dev_install_missing``.

That heuristic mis-fires here. This repo is not a uv workspace: the root
``pyproject.toml`` sets ``package = false`` and declares no
``[tool.uv.workspace]`` members, and ``packages/`` holds non-Python surfaces
(``shared-contracts``, ``codex-subagent-bridge``). There are no copy-editables,
so there is nothing to heal and a no-op is the correct behaviour — not a
silenced check (sr-001).

To keep that a checked claim rather than an assumption, this script FAILS if the
precondition ever stops holding: the moment the root ``pyproject.toml`` grows a
``[tool.uv.workspace]`` table, provisioning breaks loudly and whoever added the
workspace must implement a real heal here (see
``agentic-protocol-monorepo/scripts/dev_install.py`` for the reference
implementation).

Contract (fixed by the caller): ``--repo <worktree> --venv <venv> --emit-json``,
exit 0 on success, JSON receipt on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


def _has_uv_workspace(repo: Path) -> bool:
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return False
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return "workspace" in data.get("tool", {}).get("uv", {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--venv", required=True, type=Path)
    parser.add_argument("--emit-json", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()

    if _has_uv_workspace(repo):
        print(
            f"dev_install: {repo}/pyproject.toml now declares [tool.uv.workspace]. "
            "This repo's no-op heal is no longer valid — implement real src "
            "redirects here before provisioning can succeed.",
            file=sys.stderr,
        )
        return 2

    receipt = {
        "ok": True,
        "repo": str(repo),
        "venv": str(args.venv),
        "healed": [],
        "skipped_reason": "no_uv_workspace_members",
    }
    if args.emit_json:
        print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
