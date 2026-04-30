from __future__ import annotations

import io
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


HOOK_SCRIPT = Path(__file__).parent / "guard-handoff-provenance.py"


def _load_hook_module():
    spec = spec_from_file_location("guard_handoff_provenance", str(HOOK_SCRIPT))
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(*, tool_name: str, task_ref: str, actor_branch: str, actor_commit: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {
            "event": {
                "event_kind": "decision",
                "task_ref": task_ref,
                "actor": {
                    "branch": actor_branch,
                    "commit_sha": actor_commit,
                },
            }
        },
    }


def test_allows_matching_target_head(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_hook_module()
    monkeypatch.setattr(
        mod,
        "_load_task_identity",
        lambda task_ref: {
            "task_ref": task_ref,
            "target_branch": "feature/e16-1",
            "target_worktree_path": "/tmp/e16-1",
        },
    )
    monkeypatch.setattr(mod, "_resolve_head", lambda _path: "abc123" * 6 + "ab")
    monkeypatch.setattr(mod, "_resolve_commit", lambda _path, _commit: "abc123" * 6 + "ab")
    monkeypatch.setattr(
        mod.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                _payload(
                    tool_name="mcp_altcontext-mc_record_event",
                    task_ref="E16-1",
                    actor_branch="feature/e16-1",
                    actor_commit="abc1234",
                )
            )
        ),
    )

    assert mod.main() == 0


def test_blocks_branch_sha_drift_against_target_worktree(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _load_hook_module()
    monkeypatch.setattr(
        mod,
        "_load_task_identity",
        lambda task_ref: {
            "task_ref": task_ref,
            "target_branch": "feature/e16-1",
            "target_worktree_path": "/tmp/e16-1",
        },
    )
    monkeypatch.setattr(mod, "_resolve_head", lambda _path: "f" * 40)
    monkeypatch.setattr(mod, "_resolve_commit", lambda _path, _commit: "a" * 40)
    monkeypatch.setattr(
        mod.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                _payload(
                    tool_name="mcp_altcontext-mc_record_event",
                    task_ref="E16-1",
                    actor_branch="feature/e16-1",
                    actor_commit="b837a3f",
                )
            )
        ),
    )

    assert mod.main() == 2
    stderr = capsys.readouterr().err
    assert "handoff provenance drift" in stderr
    assert "feature/e16-1" in stderr


def test_ignores_writes_without_explicit_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_hook_module()
    monkeypatch.setattr(
        mod.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "mcp_altcontext-mc_record_event",
                    "tool_input": {
                        "event": {
                            "event_kind": "test_result",
                            "task_ref": "E16-1",
                        }
                    },
                }
            )
        ),
    )

    assert mod.main() == 0