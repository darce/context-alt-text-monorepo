"""Tests for the slim-handoff-response PostToolUse hook."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

HOOK = Path(__file__).parent / "slim-handoff-response.py"


def run_hook(payload: dict) -> dict:
    """Run the hook and return parsed JSON stdout."""
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, f"Hook exited {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)


def get_context(resp: dict) -> str | None:
    hso = resp.get("hookSpecificOutput")
    if hso:
        return hso.get("additionalContext")
    return None


def make_handoff_payload(response_chars: int) -> dict:
    """Create a payload simulating a get_handoff_state response of given size."""
    padding = "x" * response_chars
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "mcp_altcontext-mc_get_handoff_state",
        "tool_input": {"task_ref": "TEST-1"},
        "tool_response": {
            "active": {"task_ref": "TEST-1", "objective": "test"},
            "decisions": [{"rationale": padding}],
        },
    }


# ---------------------------------------------------------------------------
# Below threshold: no-op
# ---------------------------------------------------------------------------


class TestBelowThreshold:
    def test_small_response(self):
        resp = run_hook(make_handoff_payload(100))
        assert get_context(resp) is None

    def test_just_under_threshold(self):
        resp = run_hook(make_handoff_payload(7000))
        assert get_context(resp) is None


# ---------------------------------------------------------------------------
# Above threshold: advisory injected
# ---------------------------------------------------------------------------


class TestAboveThreshold:
    def test_large_response_warns(self):
        resp = run_hook(make_handoff_payload(10_000))
        ctx = get_context(resp)
        assert ctx is not None
        assert "tokens" in ctx
        assert "bounded-read" in ctx.lower() or "sections=" in ctx

    def test_advisory_mentions_levers(self):
        resp = run_hook(make_handoff_payload(15_000))
        ctx = get_context(resp)
        assert 'sections="identity"' in ctx
        assert 'detail="summary"' in ctx

    def test_load_session_also_triggers(self):
        payload = make_handoff_payload(10_000)
        payload["tool_name"] = "mcp_altcontext-mc_load_session"
        resp = run_hook(payload)
        ctx = get_context(resp)
        assert ctx is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_malformed_json(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}

    def test_string_response(self):
        payload = {
            "tool_name": "mcp_altcontext-mc_get_handoff_state",
            "tool_response": "x" * 10_000,
        }
        resp = run_hook(payload)
        ctx = get_context(resp)
        assert ctx is not None

    def test_empty_response(self):
        payload = {
            "tool_name": "mcp_altcontext-mc_get_handoff_state",
            "tool_response": {},
        }
        resp = run_hook(payload)
        assert get_context(resp) is None


# ---------------------------------------------------------------------------
# Metrics recording: _record_advisory_metric unit tests
# ---------------------------------------------------------------------------


def _load_hook_module():
    """Import the hook by file path (hyphen in filename prevents normal import)."""
    spec = importlib.util.spec_from_file_location("slim_handoff_response", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMetricsRecording:
    def test_record_turn_metrics_args(self):
        mod = _load_hook_module()
        with (
            mock.patch("agent_handoff_mcp.configure_runtime"),
            mock.patch("agent_handoff_mcp.RuntimeConfig"),
            mock.patch("agent_orchestrator_mcp.lanes.record_turn_metric") as mock_record,
        ):
            mod._record_advisory_metric(12_000, 3_000, {"decisions": 5})

        mock_record.assert_called_once()
        kw = mock_record.call_args.kwargs
        assert kw["session"] == "slim_handoff_advisory"
        assert kw["phase"] == "handoff_read_advisory"
        assert kw["backend"] == "slim_handoff_hook"
        pm = kw["prompt_metrics"]
        assert pm.prompt_chars == 12_000
        assert pm.prompt_tokens == 3_000
        assert pm.pressure_level == "high"
        assert pm.prompt_token_source == "char_estimate"
        assert kw["section_sizes"] == {"decisions": 5}

    def test_record_survives_package_unavailable(self):
        mod = _load_hook_module()
        with mock.patch.dict(sys.modules, {
            "agent_handoff_mcp": None,
            "agent_orchestrator_mcp": None,
            "agent_orchestrator_mcp.lanes": None,
        }):
            mod._record_advisory_metric(10_000, 2_500, {})  # must not raise

    def test_main_calls_record_above_threshold(self):
        import io
        mod = _load_hook_module()
        payload = json.dumps(make_handoff_payload(10_000))
        with mock.patch.object(mod, "_record_advisory_metric") as mock_rec:
            sys.stdin, orig_in = io.StringIO(payload), sys.stdin
            sys.stdout, orig_out = io.StringIO(), sys.stdout
            try:
                mod.main()
            finally:
                sys.stdin, sys.stdout = orig_in, orig_out
        mock_rec.assert_called_once()

    def test_main_skips_record_below_threshold(self):
        import io
        mod = _load_hook_module()
        payload = json.dumps(make_handoff_payload(100))
        with mock.patch.object(mod, "_record_advisory_metric") as mock_rec:
            sys.stdin, orig_in = io.StringIO(payload), sys.stdin
            sys.stdout, orig_out = io.StringIO(), sys.stdout
            try:
                mod.main()
            finally:
                sys.stdin, sys.stdout = orig_in, orig_out
        mock_rec.assert_not_called()
