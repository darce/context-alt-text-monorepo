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

# (a) Both packages import from the venv's site-packages tree, not a
# shadow checkout.  We assert __file__ explicitly instead of trusting a
# locate_file() fallback that can collapse to '.' on edge distributions.
import agent_orchestrator_mcp
import agent_handoff_mcp

orch_file = Path(agent_orchestrator_mcp.__file__).resolve()
handoff_file = Path(agent_handoff_mcp.__file__).resolve()
for label, pkg_file in (("agent_orchestrator_mcp", orch_file), ("agent_handoff_mcp", handoff_file)):
    assert "site-packages" in pkg_file.parts, (
        f"{{label}} imported from non-site-packages location: {{pkg_file}}"
    )
    assert "context-alt-text-monorepo" not in str(pkg_file), (
        f"{{label}} __file__ leaks monorepo reference: {{pkg_file}}"
    )
    # Belt and braces: any 'packages/' segment in the import path means the
    # monorepo's editable layout is shadowing the standalone install.
    parts = pkg_file.parts
    assert not (
        "packages" in parts and "site-packages" not in parts
    ), f"{{label}} resolved from monorepo packages/ tree: {{pkg_file}}"

# (b) Distribution metadata names the standalone packages.
import importlib.metadata as meta
for dist_name in ("agent-orchestrator-mcp", "agent-handoff-mcp"):
    dist = meta.distribution(dist_name)  # raises PackageNotFoundError on miss

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
