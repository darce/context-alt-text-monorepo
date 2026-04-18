import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from agent_handoff_mcp.config import RuntimeConfig, _resolve_primary_worktree_root


def test_runtime_config_defaults_to_workspace_state() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    runtime = RuntimeConfig.for_workspace(root)

    assert runtime.workspace_root == root
    assert runtime.state_dir == root / ".task-state"
    assert runtime.db_path == root / ".task-state" / "handoff.db"
    assert runtime.current_task_path == root / "CURRENT_TASK.json"
    assert runtime.exports_dir == root / ".task-state" / "exports"


def test_runtime_config_default_tool_profile_is_all() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    runtime = RuntimeConfig.for_workspace(root)
    assert runtime.tool_profile == "all"


def test_runtime_config_rejects_legacy_core_tool_profile() -> None:
    root = Path("/tmp/agent-handoff").resolve()
    with pytest.raises(ValueError, match="Invalid tool_profile"):
        RuntimeConfig.for_workspace(root, tool_profile="core")


def test_runtime_config_from_args_rejects_legacy_tool_profile_env() -> None:
    root = Path("/tmp/agent-handoff").resolve()

    class FakeArgs:
        workspace_root = str(root)
        state_dir = None
        current_task_path = None
        exports_dir = None
        tool_profile = None

    with mock.patch.dict(os.environ, {"AGENT_HANDOFF_TOOL_PROFILE": "core"}):
        with pytest.raises(ValueError, match="Invalid tool_profile"):
            RuntimeConfig.from_args(FakeArgs())


def test_runtime_config_from_args_defaults_to_all() -> None:
    root = Path("/tmp/agent-handoff").resolve()

    class FakeArgs:
        workspace_root = str(root)
        state_dir = None
        current_task_path = None
        exports_dir = None
        tool_profile = None

    with mock.patch.dict(os.environ, {}, clear=True):
        os.environ["AGENT_HANDOFF_WORKSPACE_ROOT"] = str(root)
        runtime = RuntimeConfig.from_args(FakeArgs())
    assert runtime.tool_profile == "all"


def test_runtime_config_from_args_rejects_legacy_cli_tool_profile() -> None:
    root = Path("/tmp/agent-handoff").resolve()

    class FakeArgs:
        workspace_root = str(root)
        state_dir = None
        current_task_path = None
        exports_dir = None
        tool_profile = "extended"

    with mock.patch.dict(os.environ, {"AGENT_HANDOFF_TOOL_PROFILE": "core"}):
        with pytest.raises(ValueError, match="Invalid tool_profile"):
            RuntimeConfig.from_args(FakeArgs())


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def git_repo_with_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a primary git repo plus a linked worktree under tmp_path.

    Returns ``(primary_root, linked_root)``. The linked worktree is on a
    second branch checked out into a sibling directory, mirroring the
    monorepo's `make task-start` layout.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _run_git(primary, "init", "-q", "-b", "main")
    _run_git(primary, "config", "user.email", "test@example.com")
    _run_git(primary, "config", "user.name", "Test User")
    _run_git(primary, "commit", "--allow-empty", "-m", "init", "-q")
    linked = tmp_path / "primary-feature"
    _run_git(primary, "branch", "feature/test")
    _run_git(primary, "worktree", "add", "-q", str(linked), "feature/test")
    return primary, linked


def test_for_repo_resolves_primary_root_from_primary_worktree(
    git_repo_with_linked_worktree: tuple[Path, Path],
) -> None:
    """When called from inside the primary worktree, for_repo() returns the
    primary worktree's root."""
    primary, _linked = git_repo_with_linked_worktree
    runtime = RuntimeConfig.for_repo(primary)
    assert runtime.workspace_root == primary.resolve()
    assert runtime.state_dir == primary.resolve() / ".task-state"
    assert runtime.db_path == primary.resolve() / ".task-state" / "handoff.db"


def test_for_repo_collapses_linked_worktree_to_primary_root(
    git_repo_with_linked_worktree: tuple[Path, Path],
) -> None:
    """When called from inside a linked worktree, for_repo() must still
    resolve to the primary worktree's root so all worktrees share a single
    handoff DB. This is the AHMCP-16 fix."""
    primary, linked = git_repo_with_linked_worktree
    runtime = RuntimeConfig.for_repo(linked)
    assert runtime.workspace_root == primary.resolve()
    assert runtime.db_path == primary.resolve() / ".task-state" / "handoff.db"


def test_for_repo_falls_back_to_start_dir_outside_git(tmp_path: Path) -> None:
    """When start_dir is not inside any git repo, for_repo() falls back to
    using start_dir as the workspace root."""
    not_a_repo = tmp_path / "scratch"
    not_a_repo.mkdir()
    runtime = RuntimeConfig.for_repo(not_a_repo)
    assert runtime.workspace_root == not_a_repo.resolve()


def test_for_repo_passes_through_explicit_state_dir(
    git_repo_with_linked_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    """An explicit state_dir override must take precedence over the
    primary-worktree resolution. This preserves the escape hatch for
    fixtures that anchor at a snapshotted state directory."""
    _primary, linked = git_repo_with_linked_worktree
    custom_state = tmp_path / "custom-state"
    runtime = RuntimeConfig.for_repo(linked, state_dir=custom_state)
    assert runtime.state_dir == custom_state.resolve()
    assert runtime.db_path == custom_state.resolve() / "handoff.db"


def test_resolve_primary_worktree_root_returns_none_for_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert _resolve_primary_worktree_root(missing) is None


def test_from_args_collapses_linked_worktree_workspace_root_to_primary(
    git_repo_with_linked_worktree: tuple[Path, Path],
) -> None:
    """AHMCP-16-BR-01 regression: from_args() must route through for_repo()
    so an MCP server launched with --workspace-root pointing at a linked
    worktree binds to the primary worktree's .task-state/handoff.db.

    This is the structural divergence loop the AHMCP-16 base slice claimed
    to close. Before the fix, from_args() called for_workspace() directly,
    so the linked-worktree workspace_root resolved to a fresh empty
    per-worktree DB, defeating the resolution that for_repo() does for
    the lifecycle scripts.
    """
    primary, linked = git_repo_with_linked_worktree

    class FakeArgs:
        workspace_root = str(linked)
        state_dir = None
        current_task_path = None
        exports_dir = None
        tool_profile = None

    with mock.patch.dict(os.environ, {}, clear=True):
        runtime = RuntimeConfig.from_args(FakeArgs())

    assert runtime.workspace_root == primary.resolve(), (
        "from_args must collapse a linked-worktree workspace_root to the primary "
        f"(got {runtime.workspace_root}, expected {primary.resolve()})"
    )
    assert runtime.db_path == primary.resolve() / ".task-state" / "handoff.db"
    assert runtime.current_task_path == primary.resolve() / "CURRENT_TASK.json"
    assert runtime.exports_dir == primary.resolve() / ".task-state" / "exports"


def test_from_args_preserves_explicit_state_dir_override(
    git_repo_with_linked_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    """AHMCP-16-BR-01 escape hatch: an explicit --state-dir override remains
    authoritative even when from_args() is routing workspace_root through
    for_repo. Callers with a legitimate per-worktree-state use case (test
    snapshots, isolation fixtures) keep their override semantics."""
    primary, linked = git_repo_with_linked_worktree
    explicit_state = tmp_path / "explicit-state"

    class FakeArgs:
        workspace_root = str(linked)
        state_dir = str(explicit_state)
        current_task_path = None
        exports_dir = None
        tool_profile = None

    with mock.patch.dict(os.environ, {}, clear=True):
        runtime = RuntimeConfig.from_args(FakeArgs())

    # workspace_root still collapses to the primary worktree (the structural
    # default), but the explicit state_dir override is honored byte-for-byte.
    assert runtime.workspace_root == primary.resolve()
    assert runtime.state_dir == explicit_state.resolve()
    assert runtime.db_path == explicit_state.resolve() / "handoff.db"


def test_runtime_config_rejects_invalid_tool_profile() -> None:
    root = Path("/tmp/agent-handoff").resolve()

    with mock.patch.dict(os.environ, {"AGENT_HANDOFF_TOOL_PROFILE": "invalid"}):
        with mock.patch.dict(os.environ, {"AGENT_HANDOFF_WORKSPACE_ROOT": str(root)}, clear=False):

            class FakeArgs:
                workspace_root = str(root)
                state_dir = None
                current_task_path = None
                exports_dir = None
                tool_profile = None

            with pytest.raises(ValueError, match="Invalid tool_profile"):
                RuntimeConfig.from_args(FakeArgs())
