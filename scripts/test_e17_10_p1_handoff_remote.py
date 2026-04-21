"""
E17-10 P1 smoke test: darce/mcp-agent-handoff v0.1.0 tag reachable and pip-installable.

TDD gate for the P1 extraction sub-slice:
  - RED before the extracted content is pushed and tagged.
  - GREEN after `v0.1.0` is pushed to git@github.com:darce/mcp-agent-handoff.git.

Runs the minimum verification the Slice 1 proof spec requires:
  1. The v0.1.0 tag resolves on the remote.
  2. `pip install git+ssh://…@v0.1.0` into a scratch venv succeeds.
  3. The installed package imports, configures a runtime against a temp dir,
     and creates handoff.db at <tmp>/.task-state/handoff.db — NOT at any
     monorepo-relative path.
  4. run_doctor() completes without a monorepo-relative stacktrace (no
     `parents[N]`-based path that assumes a sibling `packages/` tree exists).

Skip automatically when SKIP_REMOTE_SMOKE=1 is set (for CI without SSH keys).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REMOTE_URL = "git@github.com:darce/mcp-agent-handoff.git"
TAG = "v0.1.0"
INSTALL_URL = f"git+ssh://{REMOTE_URL.replace(':', '/', 1)}@{TAG}"


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

SKIP_REMOTE = os.environ.get("SKIP_REMOTE_SMOKE", "0") == "1"
pytestmark = pytest.mark.skipif(SKIP_REMOTE, reason="SKIP_REMOTE_SMOKE=1")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_p1_tag_exists_on_remote() -> None:
    """The v0.1.0 tag must resolve on darce/mcp-agent-handoff before anything else."""
    result = subprocess.run(
        ["git", "ls-remote", REMOTE_URL, f"refs/tags/{TAG}"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git ls-remote failed: {result.stderr}"
    assert TAG in result.stdout, (
        f"Tag {TAG} not found on {REMOTE_URL}. "
        "Run the P1 extraction sub-slice to push the tag."
    )


def test_p1_pip_install_and_db_isolation(tmp_path: Path) -> None:
    """pip install from the remote tag succeeds; DB is created under tmp_path, not the monorepo."""
    # Create scratch venv
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    pip = venv_dir / "bin" / "pip"
    python = venv_dir / "bin" / "python"

    # Install from the remote tag (no editable, no path dep)
    subprocess.run(
        [str(pip), "install", INSTALL_URL],
        check=True,
    )

    # Run an inline script that proves the behaviors the Slice 1 spec
    # requires the packaged install to support:
    #   (a) the package imports cleanly from the standalone venv with no
    #       monorepo path on sys.path,
    #   (b) the installed package's __file__ resolves under the venv's
    #       site-packages tree (not a shadow checkout),
    #   (c) RuntimeConfig.for_workspace + a real handoff write actually
    #       creates handoff.db at <state_dir>/handoff.db,
    #   (d) run_doctor(config) succeeds end-to-end against the same config
    #       (FTS5 probe, writable probe, FTS table presence, stdio CLI probe)
    #       — the path that previously assumed Path(__file__).resolve().parents[4]
    #       and would fail in any pip-installed consumer environment.
    state_dir = tmp_path / "state"
    workspace_root = state_dir.parent
    script = f"""
import sys
from pathlib import Path

# Guard: we must NOT have the monorepo src on sys.path
monorepo_src_hints = [p for p in sys.path if "context-alt-text-monorepo" in p]
assert not monorepo_src_hints, f"monorepo path leaked into sys.path: {{monorepo_src_hints}}"

import agent_handoff_mcp
pkg_file = Path(agent_handoff_mcp.__file__).resolve()
assert "site-packages" in pkg_file.parts, (
    f"agent_handoff_mcp imported from non-site-packages location: {{pkg_file}}"
)
assert "context-alt-text-monorepo" not in str(pkg_file), (
    f"agent_handoff_mcp __file__ leaks monorepo reference: {{pkg_file}}"
)

from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    set_handoff_state,
)
from agent_handoff_mcp.api import run_doctor

state_dir = Path("{state_dir}")
workspace_root = Path("{workspace_root}")
state_dir.mkdir(parents=True, exist_ok=True)
config = RuntimeConfig.for_workspace(workspace_root, state_dir=state_dir)
configure_runtime(config)

assert config.db_path == state_dir / "handoff.db", f"unexpected db_path: {{config.db_path}}"
assert "context-alt-text-monorepo" not in str(config.db_path), (
    f"DB path leaks monorepo reference: {{config.db_path}}"
)

# (c) Force handoff.db creation via a real write.
set_handoff_state(
    task_ref="E17-10-P1-SMOKE",
    objective="P1 packaged-install smoke proof",
    status="in_progress",
)
assert config.db_path.exists(), f"handoff.db not created at {{config.db_path}}"

# (d) run_doctor succeeds against the packaged install.
report = run_doctor(config)
assert isinstance(report, dict) or report is None, (
    f"run_doctor returned unexpected type: {{type(report)}}"
)

print("P1 smoke: PASS")
"""
    result = subprocess.run(
        [str(python), "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Inline smoke script failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "P1 smoke: PASS" in result.stdout
