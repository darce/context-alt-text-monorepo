"""Tests for the slim-handoff-response PostToolUse hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
        "tool_name": "mcp__agent-handoff-mcp__get_handoff_state",
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
        payload["tool_name"] = "mcp__agent-handoff-mcp__load_session"
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
            "tool_name": "mcp__agent-handoff-mcp__get_handoff_state",
            "tool_response": "x" * 10_000,
        }
        resp = run_hook(payload)
        ctx = get_context(resp)
        assert ctx is not None

    def test_empty_response(self):
        payload = {
            "tool_name": "mcp__agent-handoff-mcp__get_handoff_state",
            "tool_response": {},
        }
        resp = run_hook(payload)
        assert get_context(resp) is None
