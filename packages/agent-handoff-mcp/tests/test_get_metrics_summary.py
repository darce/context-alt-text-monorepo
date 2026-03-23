"""Tests for the get_metrics_summary MCP tool.

Covers:
- Returns markdown string by default (output_format="markdown")
- Returns JSON response when output_format="json"
- Handles missing logs/state directories gracefully (zero-data snapshot)
- task_ref resolves to the active task when None is passed
- ok: true in JSON mode; snapshot has required keys
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_env(tmp_path: Path) -> dict:
    """Provision a minimal isolated runtime so get_metrics_summary can run."""
    state_dir = tmp_path / ".task-state"
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
    )
    mcp_server.configure_runtime(runtime)

    handoff_core.set_handoff_state(
        task_ref="metrics-test",
        objective="Test task for get_metrics_summary",
        status="in_progress",
    )

    return {
        "tmp_path": tmp_path,
        "state_dir": state_dir,
        "task_ref": "metrics-test",
    }


def _parse(payload: str | dict) -> dict:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetMetricsSummaryMarkdown:
    def test_returns_string_by_default(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary()
        assert isinstance(result, str)

    def test_contains_metrics_header(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary()
        assert "ACE Metrics Snapshot" in result

    def test_contains_required_sections(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary()
        for section in [
            "Token Efficiency",
            "Context Pressure",
            "Retrieval Activity",
            "Lane Stability",
            "Phase Timing",
            "Documentation Fitness",
        ]:
            assert section in result, f"Missing section in markdown output: {section}"

    def test_with_explicit_task_ref(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary(task_ref="metrics-test")
        assert "metrics-test" in result

    def test_zero_data_does_not_raise(self, isolated_env: dict) -> None:
        # No log files exist; should still return a valid markdown string
        result = mcp_server.get_metrics_summary()
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetMetricsSummaryJson:
    def test_output_format_json_returns_ok_true(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary(output_format="json")
        parsed = _parse(result)
        assert parsed["ok"] is True

    def test_json_snapshot_has_required_keys(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary(output_format="json")
        parsed = _parse(result)
        assert "snapshot" in parsed
        snapshot = parsed["snapshot"]
        required = {
            "timestamp", "task_ref", "token_burn", "context_pressure",
            "fts5_retrieval", "lane_health", "phase_timing", "ace_documentation",
        }
        assert required.issubset(snapshot.keys())

    def test_json_snapshot_task_ref_resolved(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary(output_format="json")
        parsed = _parse(result)
        # Should resolve to the active task (metrics-test) or "unknown"
        task_ref = parsed["snapshot"]["task_ref"]
        assert isinstance(task_ref, str)
        assert len(task_ref) > 0

    def test_json_zero_data_flags_false(self, isolated_env: dict) -> None:
        result = mcp_server.get_metrics_summary(output_format="json")
        parsed = _parse(result)
        snapshot = parsed["snapshot"]
        # No log data: all sections should be data_available: false
        assert snapshot["token_burn"]["data_available"] is False
        assert snapshot["context_pressure"]["data_available"] is False
        assert snapshot["phase_timing"]["data_available"] is False
