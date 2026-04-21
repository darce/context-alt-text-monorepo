"""
E17-10 P2 TDD gate — darce/mcp-agent-orchestrator@v0.1.0 remote smoke tests.

Tests confirm:
  1. The v0.1.0 tag is reachable on darce/mcp-agent-orchestrator.
  2. pip install from the remote tag succeeds, transitively resolves
     agent-handoff-mcp from darce/mcp-agent-handoff@v0.1.0 (no path dep),
     and `import agent_orchestrator_mcp` works in a clean scratch venv.

Set SKIP_REMOTE_SMOKE=1 to skip all tests in environments without SSH keys.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REMOTE_URL = "git@github.com:darce/mcp-agent-orchestrator.git"
TAG = "refs/tags/v0.1.0"
INSTALL_URL = "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.0"

if os.getenv("SKIP_REMOTE_SMOKE"):
    pytest.skip("SKIP_REMOTE_SMOKE set", allow_module_level=True)


def test_p2_tag_exists_on_remote() -> None:
    """v0.1.0 tag must be reachable on darce/mcp-agent-orchestrator."""
    result = subprocess.run(
        ["git", "ls-remote", REMOTE_URL, TAG],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"git ls-remote failed: {result.stderr}"
    assert TAG in result.stdout, (
        f"Tag {TAG} not found on {REMOTE_URL}. "
        "Run the P2 extraction sub-slice to push the tag."
    )


def test_p2_pip_install_and_import(tmp_path: Path) -> None:
    """pip install from remote tag succeeds; import works; no path dep to packages/."""
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    pip = venv_dir / "bin" / "pip"
    python = venv_dir / "bin" / "python"

    subprocess.run(
        [str(pip), "install", INSTALL_URL],
        check=True,
    )

    state_dir = tmp_path / "state"
    script = f"""
import sys
from pathlib import Path

# Guard: no monorepo path on sys.path
monorepo_hints = [p for p in sys.path if "context-alt-text-monorepo" in p]
assert not monorepo_hints, f"monorepo path leaked into sys.path: {{monorepo_hints}}"

# Guard: no path dep to packages/
import agent_orchestrator_mcp
import importlib.metadata as meta
dist = meta.distribution("agent-orchestrator-mcp")
# Check that agent-handoff-mcp dep is resolved from standalone repo, not packages/
handoff_dist = meta.distribution("agent-handoff-mcp")
handoff_loc = str(getattr(handoff_dist, 'locate_file', lambda p: p)('.'))
assert "packages" not in handoff_loc or "site-packages" in handoff_loc, (
    f"agent-handoff-mcp resolved from monorepo packages/ path: {{handoff_loc}}"
)

print("P2 smoke: PASS")
"""
    result = subprocess.run(
        [str(python), "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Inline smoke script failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "P2 smoke: PASS" in result.stdout
