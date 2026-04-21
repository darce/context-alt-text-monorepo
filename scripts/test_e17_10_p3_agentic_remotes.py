"""TDD gate for E17-10 Slice 4 P3: agentic-system + agentic-bootstrap external repos.

Verifies that ``darce/agentic-system`` and ``darce/agentic-bootstrap`` both
publish a ``v0.1.0`` tag on their standalone GitHub remotes, and that
``darce/agentic-system@v0.1.0`` ships the canonical shared agentic surface
(``.claude/skills/``, ``.github/hooks/``, ``scripts/hooks/``,
``.github/prompts/``, ``docs/agentic/contracts/``, ``.claude/commands/``,
plus the validators and ``portable_commands.json``).

Skip with ``SKIP_REMOTE_SMOKE=1`` when running offline.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

AGENTIC_SYSTEM_REMOTE = "git@github.com:darce/agentic-system.git"
AGENTIC_BOOTSTRAP_REMOTE = "git@github.com:darce/agentic-bootstrap.git"
TAG = "v0.1.0"

# The surface every consumer of darce/agentic-system@v0.1.0 must receive.
# Aligned with E17-10 Slice 0 scope for darce/agentic-system.
EXPECTED_AGENTIC_SYSTEM_PATHS = [
    ".claude/skills",
    ".claude/commands",
    ".github/hooks",
    ".github/prompts",
    "scripts/hooks",
    "docs/agentic/contracts",
    "config/agent-workflows/portable_commands.json",
    "scripts/generate_agent_workflows.py",
    "scripts/check_skills.py",
    "scripts/check_harness_sync.py",
    "README.md",
]


def _skip_if_offline() -> None:
    if os.environ.get("SKIP_REMOTE_SMOKE") == "1":
        pytest.skip("SKIP_REMOTE_SMOKE=1; remote smoke disabled.")


def _ls_remote_tag(remote: str, tag: str) -> str:
    result = subprocess.run(
        ["git", "ls-remote", remote, f"refs/tags/{tag}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def test_p3_agentic_system_tag_exists_on_remote() -> None:
    """darce/agentic-system must publish refs/tags/v0.1.0."""
    _skip_if_offline()
    out = _ls_remote_tag(AGENTIC_SYSTEM_REMOTE, TAG)
    assert out, (
        f"refs/tags/{TAG} not found on {AGENTIC_SYSTEM_REMOTE}. "
        f"Publish the initial extraction commit and push the tag."
    )
    sha, _ref = out.split()
    assert len(sha) == 40, f"unexpected SHA shape from ls-remote: {out!r}"


def test_p3_agentic_bootstrap_tag_exists_on_remote() -> None:
    """darce/agentic-bootstrap must publish refs/tags/v0.1.0 (README-only seed)."""
    _skip_if_offline()
    out = _ls_remote_tag(AGENTIC_BOOTSTRAP_REMOTE, TAG)
    assert out, (
        f"refs/tags/{TAG} not found on {AGENTIC_BOOTSTRAP_REMOTE}. "
        f"Publish the README-only seed commit and push the tag."
    )
    sha, _ref = out.split()
    assert len(sha) == 40, f"unexpected SHA shape from ls-remote: {out!r}"


def test_p3_agentic_system_tag_ships_expected_surface(tmp_path: Path) -> None:
    """A shallow clone of darce/agentic-system@v0.1.0 must contain the canonical surface."""
    _skip_if_offline()
    clone_dir = tmp_path / "agentic-system-smoke"
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            TAG,
            AGENTIC_SYSTEM_REMOTE,
            str(clone_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    missing: list[str] = []
    for relpath in EXPECTED_AGENTIC_SYSTEM_PATHS:
        if not (clone_dir / relpath).exists():
            missing.append(relpath)
    assert not missing, (
        f"darce/agentic-system@{TAG} is missing expected surface paths: {missing}"
    )
