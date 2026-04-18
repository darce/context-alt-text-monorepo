from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    """Load check-task-context.py as a module (hyphen in filename blocks normal import)."""
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "check-task-context.py"
    spec = importlib.util.spec_from_file_location("check_task_context_under_test", script_path)
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
