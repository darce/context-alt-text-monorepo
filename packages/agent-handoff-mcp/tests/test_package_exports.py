from agent_handoff_mcp import close_worktree_lane


def test_package_exports_close_worktree_lane() -> None:
    assert callable(close_worktree_lane)
