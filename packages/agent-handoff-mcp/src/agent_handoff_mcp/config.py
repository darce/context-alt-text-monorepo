from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    workspace_root: Path
    state_dir: Path
    db_path: Path
    current_task_path: Path
    exports_dir: Path
    artifact_db_path: Path
    artifact_index_min_bytes: int = 4096
    artifact_index_min_lines: int = 80

    @classmethod
    def for_workspace(
        cls,
        workspace_root: str | Path,
        *,
        state_dir: str | Path | None = None,
        current_task_path: str | Path | None = None,
        exports_dir: str | Path | None = None,
    ) -> "RuntimeConfig":
        resolved_workspace_root = Path(workspace_root).expanduser().resolve()
        resolved_state_dir = (
            Path(state_dir).expanduser().resolve()
            if state_dir is not None
            else resolved_workspace_root / ".task-state"
        )
        resolved_current_task_path = (
            Path(current_task_path).expanduser().resolve()
            if current_task_path is not None
            else resolved_workspace_root / "CURRENT_TASK.md"
        )
        resolved_exports_dir = (
            Path(exports_dir).expanduser().resolve()
            if exports_dir is not None
            else resolved_state_dir / "exports"
        )
        return cls(
            workspace_root=resolved_workspace_root,
            state_dir=resolved_state_dir,
            db_path=resolved_state_dir / "handoff.db",
            current_task_path=resolved_current_task_path,
            exports_dir=resolved_exports_dir,
            artifact_db_path=resolved_state_dir / "mcp-artifacts.db",
        )

    @classmethod
    def from_args(cls, args: object) -> "RuntimeConfig":
        workspace_root = getattr(args, "workspace_root", None) or os.environ.get("AGENT_HANDOFF_WORKSPACE_ROOT")
        if not workspace_root:
            raise RuntimeError("AGENT_HANDOFF_WORKSPACE_ROOT must be set or passed via --workspace-root")

        state_dir = getattr(args, "state_dir", None) or os.environ.get("AGENT_HANDOFF_STATE_DIR")
        current_task_path = (
            getattr(args, "current_task_path", None)
            or os.environ.get("AGENT_HANDOFF_CURRENT_TASK_PATH")
        )
        exports_dir = getattr(args, "exports_dir", None) or os.environ.get("AGENT_HANDOFF_EXPORTS_DIR")
        return cls.for_workspace(
            workspace_root,
            state_dir=state_dir,
            current_task_path=current_task_path,
            exports_dir=exports_dir,
        )
