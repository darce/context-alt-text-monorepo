"""Tests for ACE-related orchestrator surfaces after ace_reflect extraction.

The core ACE logic (classify, increment, apply, reflect) was extracted to
scripts/ace/ace_reflect.py and is tested there. This file covers only the
orchestrator's remaining ACE surface: the dashboard metrics summary line.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_orchestrator_mcp.orchestration import dashboard_live


class TestMetricsSummaryLine:
    def test_returns_string_when_modules_unavailable(self, tmp_path: Path) -> None:
        """When ace_metrics is not importable, return a safe fallback string."""
        with patch.dict(
            "sys.modules",
            {
                "agent_orchestrator_mcp.orchestration.ace_metrics": None,
            },
        ):
            result = dashboard_live._metrics_summary_line("test-task", tmp_path, tmp_path)
        assert isinstance(result, str)
        assert "metrics:" in result

    def test_returns_formatted_string_on_success(self, tmp_path: Path) -> None:
        """Returns a line containing expected metric label tokens."""
        mock_snap = {
            "token_burn": {"data_available": True, "total_tokens": 1234, "by_lane": {}},
            "context_pressure": {"data_available": True, "latest_pressure": "normal"},
            "fts5_retrieval": {
                "data_available": False,
                "artifact_sources_indexed": 0,
                "artifact_chunks_fts_count": 0,
                "handoff_record_counts": {},
            },
            "lane_health": {"data_available": False},
            "ace_documentation": {
                "data_available": True,
                "total_strategy_bullets": 20,
                "pruning_candidates": 0,
                "pruning_candidate_ids": [],
                "total_helpful": 10,
                "total_harmful": 1,
                "instruction_file_lines": 500,
            },
        }
        mock_ace_metrics = MagicMock()
        mock_ace_metrics.build_snapshot.return_value = mock_snap

        with patch.dict(
            "sys.modules",
            {
                "agent_orchestrator_mcp.orchestration.ace_metrics": mock_ace_metrics,
            },
        ):
            result = dashboard_live._metrics_summary_line("test-task", tmp_path, tmp_path)

        assert "tokens=" in result
        assert "pressure=" in result
        assert "bullets=" in result
