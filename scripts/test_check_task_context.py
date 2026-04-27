from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path


def _load_module():
    """Load check-task-context.py as a module (hyphen in filename blocks normal import)."""
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "check-task-context.py"
    spec = importlib.util.spec_from_file_location(
        "check_task_context_under_test", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_task_context_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_interpret_handoff_envelope_happy_path_returns_state_and_no_error():
    mod = _load_module()
    parsed = {
        "ok": True,
        "data": {
            "active": {"task_ref": "E17-12", "status": "in_progress"},
            "limits": {},
        },
    }
    state, err = mod._interpret_handoff_envelope(parsed)
    assert err is None
    assert state is not None
    assert state.get("active", {}).get("task_ref") == "E17-12"


def test_interpret_handoff_envelope_no_active_task_returns_empty_state():
    mod = _load_module()
    parsed = {"ok": True, "data": {"active": None, "limits": {}}}
    state, err = mod._interpret_handoff_envelope(parsed)
    assert err is None
    assert state is not None
    assert state.get("active") is None


def test_interpret_handoff_envelope_error_envelope_surfaces_message():
    mod = _load_module()
    parsed = {
        "ok": False,
        "data": {
            "error": "Ambiguous active task for workspace path; matching task_refs: E17-12, MAINT-RESTORE-E17-12-SCOPE-20260418",
        },
    }
    state, err = mod._interpret_handoff_envelope(parsed)
    assert state is None
    assert err is not None
    assert "Ambiguous active task" in err
    assert "E17-12" in err
    assert "MAINT-RESTORE" in err
    # Hint for the specific ambiguity case:
    assert "Archive" in err or "archive" in err
    # Must point agents at the one-command recovery path:
    assert "make maint-archive-stale" in err


def test_interpret_handoff_envelope_ambiguous_classifies_as_ambiguous():
    """Ambiguity is recoverable (caller should return 0) — not an infra error."""
    mod = _load_module()
    parsed = {
        "ok": False,
        "data": {
            "error": "Ambiguous active task for workspace path; matching task_refs: E17-12, MAINT-X-20260419",
        },
    }
    assert mod._is_ambiguous_active_task_error(parsed) is True


def test_interpret_handoff_envelope_non_ambiguous_errors_are_infra():
    mod = _load_module()
    assert (
        mod._is_ambiguous_active_task_error(
            {"ok": False, "data": {"error": "something else broke"}}
        )
        is False
    )
    assert (
        mod._is_ambiguous_active_task_error({"ok": True, "data": {"active": None}})
        is False
    )


def test_interpret_handoff_envelope_ok_false_without_error_message_still_surfaces():
    mod = _load_module()
    parsed = {"ok": False, "data": {}}
    state, err = mod._interpret_handoff_envelope(parsed)
    assert state is None
    assert err is not None
    assert "ok=false" in err or "no error message" in err


def test_interpret_handoff_envelope_non_dict_payload_surfaces_type_error():
    mod = _load_module()
    state, err = mod._interpret_handoff_envelope("not a dict")
    assert state is None
    assert err is not None
    assert "non-dict" in err or "str" in err


def test_interpret_handoff_envelope_missing_active_key_surfaces_keys():
    mod = _load_module()
    parsed = {"ok": True, "data": {"limits": {}}}  # no 'active'
    state, err = mod._interpret_handoff_envelope(parsed)
    assert state is None
    assert err is not None
    assert "active" in err


# ---------- Root-worktree-on-non-main guard ----------


def test_is_root_worktree_returns_true_for_root(tmp_path, monkeypatch):
    """When .git is a directory (root worktree), _is_root_worktree returns True."""
    mod = _load_module()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    import subprocess
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ".git"
            stderr = ""
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert mod._is_root_worktree() is True


def test_is_root_worktree_returns_false_for_linked(tmp_path, monkeypatch):
    """When .git is a file (linked worktree), _is_root_worktree returns False."""
    mod = _load_module()
    git_file = tmp_path / ".git"
    git_file.write_text("gitdir: /some/path/.git/worktrees/feature")
    monkeypatch.chdir(tmp_path)

    import subprocess
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ".git"
            stderr = ""
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert mod._is_root_worktree() is False


def test_load_open_findings_count_reads_total_matching(monkeypatch):
    mod = _load_module()

    def fake_import(module_name, attr):
        assert module_name == "api"
        assert attr == "list_review_findings"
        return lambda **kwargs: {"data": {"total_matching": 3}}

    monkeypatch.setattr(mod, "_import_handoff_attr", fake_import)
    assert mod._load_open_findings_count("TASK-1") == 3


def test_emit_startup_summary_prints_findings_and_role_hint(monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setattr(mod, "_load_open_findings_count", lambda task_ref: 2)

    mod._emit_startup_summary({"task_ref": "TASK-1"})

    out = capsys.readouterr().out
    assert "Open findings: 2" in out
    assert "Role routing" in out
    assert "make maint-start" in out


def test_emit_maintenance_task_hint_prefers_make_maint_start(monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda: ["scripts/thing.py"])

    mod._emit_maintenance_task_hint_if_needed("main")

    out = capsys.readouterr().out
    assert "make maint-start" in out
    assert "set_handoff_state" not in out
