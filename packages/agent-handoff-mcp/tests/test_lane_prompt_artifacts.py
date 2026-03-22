"""Integration tests for lane_prompt.py artifact retrieval functions.

Covers:
- _discover_artifact_refs: extracts source IDs from lane-message payloads
- _artifact_context_section: two-phase pinned-ref + FTS fallback rendering,
  budget guard, and context-pressure skip
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_handoff_mcp" / "orchestration"


def _load_lane_prompt():
    """Load lane_prompt as a module, injecting ORCHESTRATION_DIR into sys.path."""
    if str(ORCHESTRATION_DIR) not in sys.path:
        sys.path.insert(0, str(ORCHESTRATION_DIR))
    path = ORCHESTRATION_DIR / "lane_prompt.py"
    spec = importlib.util.spec_from_file_location("lane_prompt", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_prompt from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# _discover_artifact_refs
# ---------------------------------------------------------------------------


class TestDiscoverArtifactRefs:
    def _subject(self):
        return _load_lane_prompt()._discover_artifact_refs

    def test_returns_empty_when_no_messages(self) -> None:
        discover = self._subject()
        assert discover({}) == []
        assert discover({"messages": []}) == []

    def test_extracts_ids_from_payload_dict(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [
                {"payload": {"artifacts": [5, 12]}},
            ]
        }
        assert discover(activity) == [5, 12]

    def test_extracts_ids_from_payload_json_string(self) -> None:
        discover = self._subject()
        payload_str = json.dumps({"artifacts": [3, 7]})
        activity = {
            "messages": [
                {"payload": payload_str},
            ]
        }
        assert discover(activity) == [3, 7]

    def test_deduplicates_across_messages(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [
                {"payload": {"artifacts": [1, 2]}},
                {"payload": {"artifacts": [2, 3]}},
            ]
        }
        # 2 appears in both; dedup keeps first occurrence order
        assert discover(activity) == [1, 2, 3]

    def test_skips_messages_without_payload(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [
                {"message": "plain text, no payload"},
                {"payload": {"artifacts": [9]}},
            ]
        }
        assert discover(activity) == [9]

    def test_skips_non_integer_artifact_values(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [
                {"payload": {"artifacts": ["not-an-int", None, 4]}},
            ]
        }
        # Only int-coercible values are returned
        assert discover(activity) == [4]

    def test_handles_malformed_json_payload_string(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [
                {"payload": "{bad json}"},
                {"payload": {"artifacts": [11]}},
            ]
        }
        assert discover(activity) == [11]

    def test_handles_payload_without_artifacts_key(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [
                {"payload": {"source_lane": "backend", "reason": "test"}},
            ]
        }
        assert discover(activity) == []

    def test_string_artifacts_coerced_to_int(self) -> None:
        """Artifact IDs stored as strings (e.g. from JSON) should be coerced."""
        discover = self._subject()
        activity = {
            "messages": [
                {"payload": {"artifacts": ["5", "10"]}},
            ]
        }
        assert discover(activity) == [5, 10]

    def test_brief_messages_payload_artifacts_found(self) -> None:
        """Brief messages (subject starting with 'brief:') are stored as lane messages;
        their payload.artifacts should be discovered."""
        discover = self._subject()
        activity = {
            "messages": [
                {
                    "subject": "brief:context for backend lane",
                    "message": "See attached artifact.",
                    "payload": {"source_lane": "frontend", "reason": "context", "artifacts": ["42"]},
                }
            ]
        }
        assert discover(activity) == [42]

    def test_latest_worker_report_payload_artifacts_found(self) -> None:
        """Latest worker report payload.artifacts should be discovered (forward-compat path)."""
        discover = self._subject()
        activity = {
            "messages": [],
            "reports": [
                {"summary": "Tests pass.", "payload": {"artifacts": ["99"]}},
            ],
        }
        assert discover(activity) == [99]

    def test_worker_report_deduped_against_messages(self) -> None:
        """Artifact IDs from reports that duplicate message refs are deduplicated."""
        discover = self._subject()
        activity = {
            "messages": [{"payload": {"artifacts": [7]}}],
            "reports": [{"payload": {"artifacts": ["7", "8"]}}],
        }
        assert discover(activity) == [7, 8]

    def test_only_latest_report_scanned(self) -> None:
        """Only the first (latest) report is scanned, not all reports."""
        discover = self._subject()
        activity = {
            "messages": [],
            "reports": [
                {"payload": {"artifacts": [1]}},   # latest - should be scanned
                {"payload": {"artifacts": [2]}},   # older - should NOT be scanned
            ],
        }
        assert discover(activity) == [1]

    def test_returns_empty_when_reports_have_no_payload(self) -> None:
        discover = self._subject()
        activity = {
            "messages": [],
            "reports": [{"summary": "All good.", "changed_files_json": "[]"}],
        }
        assert discover(activity) == []


# ---------------------------------------------------------------------------
# _build_artifact_queries
# ---------------------------------------------------------------------------


class TestBuildArtifactQueries:
    """Tests for _build_artifact_queries expanded query extraction."""

    def _subject(self):
        return _load_lane_prompt()._build_artifact_queries

    def test_empty_activity_returns_empty(self) -> None:
        bq = self._subject()
        assert bq({}) == []

    def test_extracts_message_body(self) -> None:
        bq = self._subject()
        activity = {"messages": [{"message": "fix the flaky test"}]}
        queries = bq(activity)
        assert any("fix the flaky test" in q for q in queries)

    def test_brief_payload_summary_used_as_query(self) -> None:
        """Brief payload.summary should be used as an FTS query term."""
        bq = self._subject()
        activity = {
            "messages": [
                {
                    "subject": "brief:implement retention",
                    "message": "Summary: retention policy.",
                    "payload": {"source_lane": "orch", "reason": "implement retention", "summary": "Retention export endpoint"},
                }
            ]
        }
        queries = bq(activity)
        assert any("Retention export endpoint" in q for q in queries)

    def test_brief_body_excluded_from_message_pass(self) -> None:
        """Brief message bodies should NOT be collected as regular message queries
        (they are handled via payload.summary instead)."""
        bq = self._subject()
        activity = {
            "messages": [
                {
                    "subject": "brief:do something",
                    "message": "do something",
                    "payload": {"source_lane": "orch", "reason": "do something", "summary": "Specific brief summary"},
                },
                {"subject": None, "message": "regular assignment"},
            ]
        }
        queries = bq(activity)
        # "do something" (brief message body) should NOT appear
        assert not any(q == "do something" for q in queries)
        # brief summary SHOULD appear
        assert any("Specific brief summary" in q for q in queries)
        # regular assignment SHOULD appear
        assert any("regular assignment" in q for q in queries)

    def test_latest_report_summary_used_as_fallback(self) -> None:
        """Latest worker report summary should be included as a query term."""
        bq = self._subject()
        activity = {
            "messages": [],
            "reports": [{"summary": "All 14 tests pass after migration fix."}],
        }
        queries = bq(activity)
        assert any("All 14 tests pass after migration fix" in q for q in queries)

    def test_cap_at_four_queries(self) -> None:
        """Total query count is capped at 4 regardless of input size."""
        bq = self._subject()
        activity = {
            "messages": [{"message": f"task {i}"} for i in range(10)],
            "blockers": [{"description": f"blocker {i}"} for i in range(3)],
        }
        assert len(bq(activity)) <= 4



# ---------------------------------------------------------------------------
# _artifact_context_section
# ---------------------------------------------------------------------------


class TestArtifactContextSection:
    """Tests for _artifact_context_section using mocked MCP calls."""

    def _subject(self, module):
        return module._artifact_context_section

    def _make_activity(self, artifact_ids: list[int] | None = None) -> dict[str, Any]:
        """Build a minimal activity dict with optional pinned artifact IDs."""
        messages = []
        if artifact_ids:
            messages.append({"payload": {"artifacts": artifact_ids}})
        else:
            messages.append({"message": "fix the failing test"})
        return {
            "messages": messages,
            "blockers": [],
            "findings": [],
        }

    def test_returns_empty_when_budget_is_zero(self) -> None:
        lp = _load_lane_prompt()
        lines = lp._artifact_context_section(
            task_ref="t",
            lane_id="l",
            activity=self._make_activity(),
            budget_chars=0,
        )
        assert lines == []

    def test_returns_empty_when_search_unavailable(self) -> None:
        lp = _load_lane_prompt()
        original = lp._ARTIFACT_SEARCH_AVAILABLE
        try:
            lp._ARTIFACT_SEARCH_AVAILABLE = False
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=self._make_activity(),
                budget_chars=10000,
            )
            assert lines == []
        finally:
            lp._ARTIFACT_SEARCH_AVAILABLE = original

    def test_pinned_ref_rendered_first(self) -> None:
        lp = _load_lane_prompt()
        mock_source_response = json.dumps({
            "ok": True,
            "source": {
                "id": 7,
                "source_label": "pytest-output",
                "summary": "Test summary of the output",
                "chunks": [{"chunk_order": 1, "title": "Run", "body": "Test body text"}],
            }
        })
        mock_search_response = json.dumps({"ok": True, "hits": []})

        with patch.object(lp, "_mcp_get_artifact_source", return_value=mock_source_response), \
             patch.object(lp, "_mcp_search_artifacts", return_value=mock_search_response), \
             patch.object(lp, "_ARTIFACT_SEARCH_AVAILABLE", True):
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=self._make_activity(artifact_ids=[7]),
                budget_chars=10000,
            )

        assert len(lines) == 1
        assert "[pytest-output]" in lines[0]
        assert "Test summary" in lines[0]

    def test_fts_fallback_when_no_pinned_refs(self) -> None:
        lp = _load_lane_prompt()
        mock_search_response = json.dumps({
            "ok": True,
            "hits": [
                {
                    "source_id": 3,
                    "source_label": "migration-log",
                    "title": "DB migration",
                    "snippet": "Applied 3 migrations",
                },
            ],
        })
        mock_source_response = json.dumps({"ok": False})

        activity = {
            "messages": [{"message": "check migration log"}],
            "blockers": [],
            "findings": [],
        }

        with patch.object(lp, "_mcp_get_artifact_source", return_value=mock_source_response), \
             patch.object(lp, "_mcp_search_artifacts", return_value=mock_search_response), \
             patch.object(lp, "_ARTIFACT_SEARCH_AVAILABLE", True):
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=activity,
                budget_chars=10000,
            )

        assert len(lines) == 1
        assert "[migration-log]" in lines[0]
        assert "DB migration" in lines[0]

    def test_fts_results_skip_already_rendered_pinned_ids(self) -> None:
        """Source IDs already rendered via pinned refs should not be duplicated from FTS."""
        lp = _load_lane_prompt()
        mock_source_response = json.dumps({
            "ok": True,
            "source": {
                "id": 5,
                "source_label": "output",
                "summary": "Pinned summary",
                "chunks": [],
            }
        })
        # FTS returns the same source_id=5 that was already rendered
        mock_search_response = json.dumps({
            "ok": True,
            "hits": [
                {
                    "source_id": 5,
                    "source_label": "output",
                    "title": "FTS hit title",
                    "snippet": "FTS snippet",
                },
            ],
        })

        with patch.object(lp, "_mcp_get_artifact_source", return_value=mock_source_response), \
             patch.object(lp, "_mcp_search_artifacts", return_value=mock_search_response), \
             patch.object(lp, "_ARTIFACT_SEARCH_AVAILABLE", True):
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=self._make_activity(artifact_ids=[5]),
                budget_chars=10000,
            )

        # Only one entry, not duplicated
        assert len(lines) == 1
        assert "FTS" not in lines[0]

    def test_budget_limits_total_rendered_chars(self) -> None:
        lp = _load_lane_prompt()
        long_summary = "A" * 500
        mock_source_response = json.dumps({
            "ok": True,
            "source": {
                "id": 1,
                "source_label": "big-log",
                "summary": long_summary,
                "chunks": [],
            }
        })
        mock_search_response = json.dumps({"ok": True, "hits": []})

        with patch.object(lp, "_mcp_get_artifact_source", return_value=mock_source_response), \
             patch.object(lp, "_mcp_search_artifacts", return_value=mock_search_response), \
             patch.object(lp, "_ARTIFACT_SEARCH_AVAILABLE", True):
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=self._make_activity(artifact_ids=[1]),
                budget_chars=50,  # very small budget
            )

        # Source would require >50 chars; should be empty
        assert lines == []

    def test_mcp_exception_does_not_raise(self) -> None:
        """Errors in MCP calls should be swallowed gracefully."""
        lp = _load_lane_prompt()

        def _raise(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("network error")

        with patch.object(lp, "_mcp_get_artifact_source", side_effect=_raise), \
             patch.object(lp, "_mcp_search_artifacts", side_effect=_raise), \
             patch.object(lp, "_ARTIFACT_SEARCH_AVAILABLE", True):
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=self._make_activity(artifact_ids=[1]),
                budget_chars=10000,
            )

        assert lines == []

    def test_pinned_ref_uses_first_chunk_body_when_no_summary(self) -> None:
        lp = _load_lane_prompt()
        mock_source_response = json.dumps({
            "ok": True,
            "source": {
                "id": 2,
                "source_label": "test-log",
                "summary": "",  # empty summary
                "chunks": [{"chunk_order": 1, "title": "Head", "body": "Chunk body fallback"}],
            }
        })
        mock_search_response = json.dumps({"ok": True, "hits": []})

        with patch.object(lp, "_mcp_get_artifact_source", return_value=mock_source_response), \
             patch.object(lp, "_mcp_search_artifacts", return_value=mock_search_response), \
             patch.object(lp, "_ARTIFACT_SEARCH_AVAILABLE", True):
            lines = lp._artifact_context_section(
                task_ref="t",
                lane_id="l",
                activity=self._make_activity(artifact_ids=[2]),
                budget_chars=10000,
            )

        assert len(lines) == 1
        assert "Chunk body fallback" in lines[0]
