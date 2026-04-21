from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TOOL_PROFILE = "all"
_VALID_TOOL_PROFILES = ("all",)
_GIT_SUBPROCESS_TIMEOUT_SECONDS = 5


class ConsumerRootResolutionError(RuntimeError):
    """Raised when packaged consumer startup cannot infer a git-backed root."""


def _resolve_runtime_path(path_value: str | Path, *, workspace_root: Path) -> Path:
    """Resolve config paths relative to the runtime workspace root.

    Explicit relative paths from harness config should anchor at the
    declared workspace root, not the process cwd. This keeps consumer
    configs like ".", ".task-state", and "CURRENT_TASK.json" stable even
    when the server is launched from a different directory.
    """
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    return candidate.resolve()


def _resolve_primary_worktree_root(start_dir: Path) -> Path | None:
    """Resolve the primary git worktree root from a starting directory.

    Uses ``git rev-parse --git-common-dir`` to find the shared ``.git``
    location across all linked worktrees of the same physical repository,
    then walks one level up to the primary worktree root.

    Returns ``None`` when git is not available, when the start directory is
    not inside a git repository, or when the resolved common dir does not
    point at a recognisable ``.git`` directory.

    The output of ``git rev-parse --git-common-dir`` is documented to be
    relative to the cwd of the git invocation when the call is made from the
    primary worktree (typically ``.git``) and an absolute path when called
    from a linked worktree (the absolute path of the primary's ``.git``
    directory). The two cases are normalised here so callers always receive
    the primary worktree's root directory.
    """
    if not start_dir.exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(start_dir), "rev-parse", "--git-common-dir"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_GIT_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    common_path = Path(raw)
    if not common_path.is_absolute():
        # Relative paths are relative to the cwd of the git invocation, which
        # is start_dir.
        common_path = (start_dir / common_path).resolve()
    else:
        common_path = common_path.resolve()
    if common_path.name == ".git":
        return common_path.parent
    # Defensive: a bare repo or unusual layout returned a non-".git" path.
    # Use it as-is rather than guessing at a parent that may not be a
    # checkout root.
    return common_path


@dataclass(frozen=True)
class RuntimeConfig:
    workspace_root: Path
    state_dir: Path
    db_path: Path
    current_task_path: Path
    dashboard_path: Path
    exports_dir: Path
    artifact_db_path: Path
    artifact_index_min_bytes: int = 4096
    artifact_index_min_lines: int = 80
    tool_profile: str = _DEFAULT_TOOL_PROFILE

    def __post_init__(self) -> None:
        if self.tool_profile not in _VALID_TOOL_PROFILES:
            raise ValueError(f"Invalid tool_profile: {self.tool_profile!r}")

    @classmethod
    def for_workspace(
        cls,
        workspace_root: str | Path,
        *,
        state_dir: str | Path | None = None,
        current_task_path: str | Path | None = None,
        dashboard_path: str | Path | None = None,
        exports_dir: str | Path | None = None,
        tool_profile: str | None = None,
    ) -> RuntimeConfig:
        resolved_workspace_root = Path(workspace_root).expanduser().resolve()
        resolved_state_dir = (
            _resolve_runtime_path(state_dir, workspace_root=resolved_workspace_root)
            if state_dir is not None
            else resolved_workspace_root / ".task-state"
        )
        resolved_current_task_path = (
            _resolve_runtime_path(current_task_path, workspace_root=resolved_workspace_root)
            if current_task_path is not None
            else resolved_workspace_root / "CURRENT_TASK.json"
        )
        resolved_dashboard_path = (
            _resolve_runtime_path(dashboard_path, workspace_root=resolved_workspace_root)
            if dashboard_path is not None
            else resolved_workspace_root / "DASHBOARD.txt"
        )
        resolved_exports_dir = (
            _resolve_runtime_path(exports_dir, workspace_root=resolved_workspace_root)
            if exports_dir is not None
            else resolved_state_dir / "exports"
        )
        return cls(
            workspace_root=resolved_workspace_root,
            state_dir=resolved_state_dir,
            db_path=resolved_state_dir / "handoff.db",
            current_task_path=resolved_current_task_path,
            dashboard_path=resolved_dashboard_path,
            exports_dir=resolved_exports_dir,
            artifact_db_path=resolved_state_dir / "mcp-artifacts.db",
            tool_profile=tool_profile or _DEFAULT_TOOL_PROFILE,
        )

    @classmethod
    def for_repo(
        cls,
        start_dir: str | Path | None = None,
        *,
        state_dir: str | Path | None = None,
        current_task_path: str | Path | None = None,
        dashboard_path: str | Path | None = None,
        exports_dir: str | Path | None = None,
        tool_profile: str | None = None,
    ) -> RuntimeConfig:
        """Build a RuntimeConfig anchored at the primary git worktree.

        Resolves the workspace root by walking from ``start_dir`` (or the
        current working directory if omitted) to the primary git worktree
        via ``git rev-parse --git-common-dir``. Every linked worktree of the
        same physical repository will therefore resolve to the same
        ``.task-state/handoff.db``, eliminating the per-worktree DB
        divergence that breaks ``make context`` when run from a linked
        worktree while the MCP server reads the primary worktree's DB.

        When git is not available or ``start_dir`` is not inside a git
        repository, this falls back to ``RuntimeConfig.for_workspace``
        anchored at ``start_dir`` (or the current working directory). This
        keeps non-git contexts (tests, ad-hoc tmpdir setups) working
        unchanged.

        Explicit ``state_dir`` / ``current_task_path`` / ``exports_dir``
        arguments are passed through and override the resolved defaults
        unchanged. This means a caller can still anchor the DB at an
        arbitrary path if it has a reason to bypass the primary-worktree
        resolution (e.g. running against a snapshotted state directory in
        a fixture).
        """
        start = Path(start_dir).expanduser().resolve() if start_dir is not None else Path.cwd().resolve()
        primary_root = _resolve_primary_worktree_root(start)
        workspace_root = primary_root if primary_root is not None else start
        return cls.for_workspace(
            workspace_root,
            state_dir=state_dir,
            current_task_path=current_task_path,
            dashboard_path=dashboard_path,
            exports_dir=exports_dir,
            tool_profile=tool_profile,
        )

    @classmethod
    def from_args(cls, args: object) -> RuntimeConfig:
        """Build a RuntimeConfig from CLI args / env vars.

        AHMCP-16-BR-01: ``from_args`` routes the resolved ``workspace_root``
        through ``for_repo`` so an MCP server (or any other CLI entry point)
        launched with ``--workspace-root`` pointing at a *linked* git
        worktree silently collapses to the primary worktree's
        ``.task-state/handoff.db``. Without this redirection the MCP server
        and the lifecycle scripts (which already use ``for_repo`` after the
        AHMCP-16 base slice) end up writing to two different per-worktree
        DBs, defeating the divergence-loop closure the slice claims.

        Explicit ``--state-dir`` / ``--current-task-path`` / ``--exports-dir``
        overrides remain authoritative and are passed through unchanged.
        Callers that genuinely need a per-worktree state directory (e.g.
        a snapshot fixture or a per-worker isolation test) keep that
        escape hatch. The fix only affects the default-resolution path
        where the harness invokes the server with just
        ``--workspace-root``.
        """
        workspace_root = getattr(args, "workspace_root", None) or os.environ.get("AGENT_HANDOFF_WORKSPACE_ROOT")
        if not workspace_root:
            raise RuntimeError("AGENT_HANDOFF_WORKSPACE_ROOT must be set or passed via --workspace-root")

        state_dir = getattr(args, "state_dir", None) or os.environ.get("AGENT_HANDOFF_STATE_DIR")
        current_task_path = getattr(args, "current_task_path", None) or os.environ.get("AGENT_HANDOFF_CURRENT_TASK_PATH")
        dashboard_path = getattr(args, "dashboard_path", None) or os.environ.get("AGENT_HANDOFF_DASHBOARD_PATH")
        exports_dir = getattr(args, "exports_dir", None) or os.environ.get("AGENT_HANDOFF_EXPORTS_DIR")
        start = Path(workspace_root).expanduser().resolve()

        if (
            _resolve_primary_worktree_root(start) is None
            and state_dir is None
            and current_task_path is None
            and dashboard_path is None
            and exports_dir is None
        ):
            raise ConsumerRootResolutionError(
                "agent-handoff-mcp could not resolve <consumer-root> "
                f"- caller cwd {start} is not inside a git repository. "
                "Set AGENT_HANDOFF_WORKSPACE_ROOT and, if needed, "
                "AGENT_HANDOFF_STATE_DIR / AGENT_HANDOFF_DASHBOARD_PATH / "
                "AGENT_HANDOFF_CURRENT_TASK_PATH explicitly, or call "
                "RuntimeConfig.for_workspace(...) for a non-git fixture."
            )

        return cls.for_repo(
            workspace_root,
            state_dir=state_dir,
            current_task_path=current_task_path,
            dashboard_path=dashboard_path,
            exports_dir=exports_dir,
            tool_profile=getattr(args, "tool_profile", None) or os.environ.get("AGENT_HANDOFF_TOOL_PROFILE"),
        )
