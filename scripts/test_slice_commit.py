from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "agentic" / "slice_commit.py"
    spec = importlib.util.spec_from_file_location("slice_commit_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["slice_commit_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_record_slice_commit_uses_repo_head_for_close_slice_actor() -> None:
    mod = _load_script_module()
    calls: dict[str, Any] = {}

    def runtime_factory(
        workspace_root: str,
        *,
        state_dir: str,
        current_task_path: str,
        exports_dir: str,
    ) -> dict[str, str]:
        calls["runtime_factory"] = {
            "workspace_root": workspace_root,
            "state_dir": state_dir,
            "current_task_path": current_task_path,
            "exports_dir": exports_dir,
        }
        return {"workspace_root": workspace_root}

    def configure_runtime_stub(runtime: object) -> None:
        calls["runtime"] = runtime

    def git_fn(repo_root: Path, *args: str) -> str:
        calls.setdefault("git", []).append((str(repo_root), args))
        if args == ("diff", "--cached", "--name-only"):
            return "scripts/agentic/slice_commit.py\nscripts/test_slice_commit.py\n"
        if args == ("commit", "-m", "chore: fix slice commit provenance"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return "c9fe225c7ef367bae47217f9a430c979e7a91688"
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "feature/maint-harness-terminal-stall-20260511"
        raise AssertionError(f"unexpected git args: {args}")

    def get_handoff_state_stub(*, task_ref: str, sections: str, detail: str) -> dict[str, Any]:
        calls["identity"] = {
            "task_ref": task_ref,
            "sections": sections,
            "detail": detail,
        }
        return {"data": {"active": {"task_ref": task_ref, "revision": 3}}}

    def close_slice_stub(**kwargs: Any) -> dict[str, Any]:
        calls["close_slice"] = kwargs
        return {"ok": True}

    result = mod.record_slice_commit(
        repo_root=Path("/tmp/worktrees/maint-harness-terminal-stall"),
        workspace_root="/tmp/orchestrator-root",
        state_dir="/tmp/orchestrator-root/.task-state",
        current_task_path="/tmp/orchestrator-root/CURRENT_TASK.json",
        exports_dir="/tmp/orchestrator-root/.task-state/exports",
        task_ref="MAINT-harness-terminal-stall-20260511",
        session="MAINT-harness-terminal-stall-20260511-slice-commit-2",
        message="chore: fix slice commit provenance",
        runtime_factory=runtime_factory,
        configure_runtime_fn=configure_runtime_stub,
        git_fn=git_fn,
        get_handoff_state_fn=get_handoff_state_stub,
        close_slice_fn=close_slice_stub,
    )

    assert calls["close_slice"]["actor"] == {
        "branch": "feature/maint-harness-terminal-stall-20260511",
        "commit_sha": "c9fe225c7ef367bae47217f9a430c979e7a91688",
    }
    assert calls["close_slice"]["expected_revision"] == 3
    assert calls["close_slice"]["changed_files"] == [
        "scripts/agentic/slice_commit.py",
        "scripts/test_slice_commit.py",
    ]
    assert result["commit_sha"] == "c9fe225c7ef367bae47217f9a430c979e7a91688"
